# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Error-bounded fitting of offset curves to neutral cubic splines."""

from __future__ import annotations

import math
from collections.abc import Callable
from importlib import import_module
from typing import cast
from uuid import uuid4

from build123d import Edge, Wire

from mycad.core.sketch import Point2D, Sketch, SplineEntity, WorkPlaneFrame


def _elevate(points: tuple[Point2D, ...], degree: int) -> tuple[Point2D, ...]:
    old = len(points) - 1
    if old > degree:
        raise ValueError("Cannot elevate to a lower degree.")
    return tuple(
        (
            sum(
                points[j][0]
                * math.comb(old, j)
                * math.comb(degree - old, i - j)
                / math.comb(degree, i)
                for j in range(max(0, i - degree + old), min(old, i) + 1)
            ),
            sum(
                points[j][1]
                * math.comb(old, j)
                * math.comb(degree - old, i - j)
                / math.comb(degree, i)
                for j in range(max(0, i - degree + old), min(old, i) + 1)
            ),
        )
        for i in range(degree + 1)
    )


def _split(points: tuple[Point2D, ...]) -> tuple[tuple[Point2D, ...], tuple[Point2D, ...]]:
    rows = [points]
    while len(rows[-1]) > 1:
        rows.append(
            tuple(
                ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                for a, b in zip(rows[-1], rows[-1][1:], strict=False)
            )
        )
    return tuple(row[0] for row in rows), tuple(row[-1] for row in reversed(rows))


def reduce_bezier(points: tuple[Point2D, ...], tolerance: float) -> tuple[tuple[Point2D, ...], ...]:
    """Return cubic pieces approximating a planar Bezier curve."""
    return tuple(piece for piece, _start, _end in reduce_bezier_with_intervals(points, tolerance))


def reduce_bezier_with_intervals(
    points: tuple[Point2D, ...], tolerance: float
) -> tuple[tuple[tuple[Point2D, ...], float, float], ...]:
    """Bound the error using the convex hull of elevated Bernstein differences."""
    if len(points) < 2 or not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Invalid Bezier curve or approximation tolerance.")
    if any(not math.isfinite(value) for point in points for value in point):
        raise ValueError("Bezier control points must be finite.")
    result: list[tuple[tuple[Point2D, ...], float, float]] = []
    pending: list[tuple[tuple[Point2D, ...], float, float, int]] = [(points, 0.0, 1.0, 0)]
    while pending:
        original, start, end, depth = pending.pop()
        degree = len(original) - 1
        if degree <= 3:
            cubic = _elevate(original, 3)
            error = 0.0
        else:
            first, second, penultimate, last = original[0], original[1], original[-2], original[-1]
            factor = degree / 3
            cubic = (
                first,
                (
                    first[0] + factor * (second[0] - first[0]),
                    first[1] + factor * (second[1] - first[1]),
                ),
                (
                    last[0] + factor * (penultimate[0] - last[0]),
                    last[1] + factor * (penultimate[1] - last[1]),
                ),
                last,
            )
            elevated = _elevate(cubic, degree)
            error = max(math.dist(a, b) for a, b in zip(original, elevated, strict=True))
        if error <= tolerance:
            result.append((cubic, start, end))
            continue
        if depth >= 20 or len(result) + len(pending) >= 4096:
            raise ValueError("Bezier approximation exceeds the subdivision limit.")
        left, right = _split(original)
        mid = (start + end) / 2
        pending.append((right, mid, end, depth + 1))
        pending.append((left, start, mid, depth + 1))
    return tuple(result)


def offset_spline(source: SplineEntity, distance: float) -> tuple[SplineEntity, ...]:
    """Offset an open spline and approximate its OCCT curves within 0.001 mm.

    Each returned cubic Bezier is stored as an ordinary four-control-point spline.
    OCCT's approximation error is limited to 0.00025 mm and Bernstein reduction
    to 0.00025 mm; endpoint normalization is limited to 0.000001 mm.
    """
    return offset_spline_path((source,), distance)


def offset_spline_path(
    sources: tuple[SplineEntity, ...], distance: float
) -> tuple[SplineEntity, ...]:
    """Offset connected cubic pieces as a single wire, preserving its branches."""
    if not sources:
        raise ValueError("偏置样条路径不能为空。")
    if len({source.entity_id for source in sources}) != len(sources):
        raise ValueError("偏置样条路径中存在重复身份。")
    if any(
        source.layer_name != sources[0].layer_name or source.construction != sources[0].construction
        for source in sources
    ):
        raise ValueError("偏置样条路径的图层或构造属性不一致。")
    branches: list[list[SplineEntity]] = [[sources[0]]]
    for piece in sources[1:]:
        current = branches[-1]
        branch_closed = (
            math.dist(current[0].control_points_mm[0], current[-1].control_points_mm[-1]) <= 1e-6
        )
        if (
            branch_closed
            or math.dist(current[-1].control_points_mm[-1], piece.control_points_mm[0]) > 1e-6
        ):
            branches.append([])
        branches[-1].append(piece)
    if len(branches) > 1:
        return tuple(
            piece for branch in branches for piece in offset_spline_path(tuple(branch), distance)
        )
    source = sources[0]
    if not math.isfinite(distance) or abs(distance) <= 1e-9:
        raise ValueError("偏置距离须为非零有限值。")
    from mycad.geom.sketch_profiles import spline_edge

    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    source_edges = tuple(spline_edge(sketch, item) for item in sources)
    source_wire = Wire(list(source_edges))
    make_offset = cast(
        "Callable[[object, object, bool], object]",
        import_module("OCP.BRepOffsetAPI").BRepOffsetAPI_MakeOffset,
    )
    intersection = cast("object", import_module("OCP.GeomAbs").GeomAbs_Intersection)
    make_explorer = cast(
        "Callable[[object, object], object]", import_module("OCP.TopExp").TopExp_Explorer
    )
    wire_kind = cast("object", import_module("OCP.TopAbs").TopAbs_WIRE)
    wire_cast = cast("Callable[[object], object]", import_module("OCP.TopoDS").TopoDS.Wire_s)
    wrap_wire = cast("Callable[[object], Wire]", Wire)
    try:
        builder = make_offset(source_wire.wrapped, intersection, True)
        cast("Callable[[float], None]", _member(builder, "Perform"))(-distance)
        if not cast("Callable[[], bool]", _member(builder, "IsDone"))():
            raise ValueError("样条偏置无法完成。")
        shape = cast("Callable[[], object]", _member(builder, "Shape"))()
        explorer = make_explorer(shape, wire_kind)
        more = cast("Callable[[], bool]", _member(explorer, "More"))
        current = cast("Callable[[], object]", _member(explorer, "Current"))
        advance = cast("Callable[[], None]", _member(explorer, "Next"))
        components: list[tuple[list[tuple[Point2D, ...]], bool]] = []
        while more():
            output = wrap_wire(wire_cast(current()))
            pieces: list[tuple[Point2D, ...]] = []
            for edge in output.order_edges():
                pieces.extend(approximate_offset_edge(edge))
            if not pieces:
                raise ValueError("样条偏置产生空分支。")
            closed = output.is_closed or math.dist(pieces[0][0], pieces[-1][-1]) <= 1e-6
            components.append((pieces, closed))
            advance()
        if not components:
            raise ValueError("样条偏置没有有效结果。")
        start = source.control_points_mm[0]
        next_point = source.control_points_mm[1]
        direction = (next_point[0] - start[0], next_point[1] - start[1])
        length = math.hypot(*direction)
        if length <= 1e-9:
            raise ValueError("样条起点切向退化。")
        expected = (
            start[0] - distance * direction[1] / length,
            start[1] + distance * direction[0] / length,
        )
        normalized: list[tuple[Point2D, ...]] = []
        source_closed = (
            math.dist(sources[0].control_points_mm[0], sources[-1].control_points_mm[-1]) <= 1e-6
        )
        if len(components) == 1:
            pieces, closed = components[0]
            if closed:
                _key, pieces = _orient_closed_component(sources, source_edges, pieces)
            elif math.dist(pieces[-1][-1], expected) < math.dist(pieces[0][0], expected):
                pieces = [tuple(reversed(piece)) for piece in reversed(pieces)]
            components[0] = (pieces, closed)
        else:
            ordered: list[tuple[float, list[tuple[Point2D, ...]], bool]] = []
            for pieces, closed in components:
                if closed or source_closed:
                    first, pieces = _orient_closed_component(sources, source_edges, pieces)
                    ordered.append((first, pieces, closed))
                    continue
                first = _path_parameter_near_end(sources, source_edges, pieces[0], start=True)
                last = _path_parameter_near_end(sources, source_edges, pieces[-1], start=False)
                if abs(first - last) <= 1e-9:
                    raise ValueError("样条偏置分支方向不明确。")
                if first > last:
                    pieces = [tuple(reversed(piece)) for piece in reversed(pieces)]
                    first, last = last, first
                ordered.append((first, pieces, closed))
            ordered.sort(key=lambda item: item[0])
            if any(abs(a[0] - b[0]) <= 1e-9 for a, b in zip(ordered, ordered[1:], strict=False)):
                raise ValueError("样条偏置分支顺序不明确。")
            components = [(pieces, closed) for _parameter, pieces, closed in ordered]
        for pieces, closed in components:
            component: list[tuple[Point2D, ...]] = []
            for piece in pieces:
                if component:
                    error = math.dist(component[-1][-1], piece[0])
                    if error > 1e-6:
                        raise ValueError("样条偏置分段不连续。")
                    piece = (component[-1][-1], *piece[1:])
                component.append(piece)
            if closed:
                if math.dist(component[-1][-1], component[0][0]) > 1e-6:
                    raise ValueError("样条偏置闭合分支不连续。")
                component[-1] = (*component[-1][:-1], component[0][0])
            normalized.extend(component)
        return tuple(
            SplineEntity(uuid4().hex, piece, source.construction, source.layer_name)
            for piece in normalized
        )
    except RuntimeError as exc:
        raise ValueError("样条偏置几何计算失败。") from exc


def _member(value: object, name: str) -> object:
    return getattr(value, name)


def _orient_closed_component(
    sources: tuple[SplineEntity, ...], edges: tuple[Edge, ...], pieces: list[tuple[Point2D, ...]]
) -> tuple[float, list[tuple[Point2D, ...]]]:
    """Follow the original curve through a loop, ignoring projection jumps at crossings."""
    votes: list[float] = []
    first_parameter: float | None = None
    for piece in pieces:
        try:
            first = _path_parameter_near_end(sources, edges, piece, start=True)
            last = _path_parameter_near_end(sources, edges, piece, start=False)
        except ValueError:
            continue
        if first_parameter is None:
            first_parameter = first
        difference = last - first
        if 1e-9 < abs(difference) < len(sources) / 2:
            votes.append(difference)
    if first_parameter is None or not votes:
        raise ValueError("样条闭合分支方向不明确。")
    forward = sum(value > 0 for value in votes)
    backward = len(votes) - forward
    if forward == backward:
        raise ValueError("样条闭合分支方向不明确。")
    if backward > forward:
        pieces = [tuple(reversed(piece)) for piece in reversed(pieces)]
    return first_parameter, pieces


def _path_parameter_near_end(
    sources: tuple[SplineEntity, ...],
    edges: tuple[Edge, ...],
    piece: tuple[Point2D, ...],
    *,
    start: bool,
) -> float:
    """Use interior points when a branch endpoint meets multiple source normals."""
    for value in (0.0, 0.1, 0.25, 0.5):
        parameter = value if start else 1 - value
        work: list[Point2D] = list(piece)
        while len(work) > 1:
            work = [
                (
                    (1 - parameter) * left[0] + parameter * right[0],
                    (1 - parameter) * left[1] + parameter * right[1],
                )
                for left, right in zip(work, work[1:], strict=False)
            ]
        try:
            return _source_path_parameter(sources, edges, work[0])
        except ValueError:
            continue
    raise ValueError("样条偏置分支与源曲线的对应位置不明确。")


def _source_path_parameter(
    sources: tuple[SplineEntity, ...], edges: tuple[Edge, ...], point: Point2D
) -> float:
    candidates = [
        (separation, index + parameter)
        for index, (source, edge) in enumerate(zip(sources, edges, strict=True))
        for separation, parameter in [_source_projection(source, edge, point)]
    ]
    candidates.sort()
    best_distance, best_parameter = candidates[0]
    if any(
        abs(other_distance - best_distance) <= 1e-8 and abs(other_parameter - best_parameter) > 1e-7
        for other_distance, other_parameter in candidates[1:]
    ):
        raise ValueError("样条偏置分支与源曲线的对应位置不明确。")
    return best_parameter


def _source_projection(source: SplineEntity, edge: Edge, point: Point2D) -> tuple[float, float]:
    """Locate a branch endpoint on one source piece."""
    make_point = cast("Callable[[float, float, float], object]", import_module("OCP.gp").gp_Pnt)
    curve_tool = import_module("OCP.BRep").BRep_Tool
    get_curve = cast("Callable[[object, float, float], object]", _member(curve_tool, "Curve_s"))
    make_projection = cast(
        "Callable[[object, object, float, float], object]",
        import_module("OCP.GeomAPI").GeomAPI_ProjectPointOnCurve,
    )
    projection = make_projection(
        make_point(*point, 0.0), get_curve(edge.wrapped, 0.0, 0.0), 0.0, 1.0
    )
    count = cast("Callable[[], int]", _member(projection, "NbPoints"))()
    parameter = cast("Callable[[int], float]", _member(projection, "Parameter"))
    separation = cast("Callable[[int], float]", _member(projection, "Distance"))
    candidates = [(math.dist(point, source.point_at(t)), t) for t in (0.0, 1.0)]
    candidates.extend((separation(i), parameter(i)) for i in range(1, count + 1))
    candidates.sort()
    best_distance, best_parameter = candidates[0]
    if any(
        abs(other_distance - best_distance) <= 1e-8 and abs(other_parameter - best_parameter) > 1e-7
        for other_distance, other_parameter in candidates[1:]
    ):
        raise ValueError("样条偏置分支与源曲线的对应位置不明确。")
    return best_distance, best_parameter


def approximate_offset_edge(edge: Edge) -> list[tuple[Point2D, ...]]:
    """Convert one trimmed OCCT offset edge to bounded-error cubic pieces."""
    adaptor_factory = cast(
        "Callable[[object], object]", import_module("OCP.BRepAdaptor").BRepAdaptor_Curve
    )
    adaptor = adaptor_factory(edge.wrapped)
    first = cast("Callable[[], float]", _member(adaptor, "FirstParameter"))()
    last = cast("Callable[[], float]", _member(adaptor, "LastParameter"))()
    tool = import_module("OCP.BRep").BRep_Tool
    get_curve = cast("Callable[[object, float, float], object]", _member(tool, "Curve_s"))
    curve = get_curve(edge.wrapped, 0.0, 0.0)
    trimmed = cast(
        "Callable[[object, float, float], object]", import_module("OCP.Geom").Geom_TrimmedCurve
    )(curve, first, last)
    continuity = cast("object", import_module("OCP.GeomAbs").GeomAbs_C2)
    make_fit = cast(
        "Callable[[object, float, object, int, int], object]",
        import_module("OCP.GeomConvert").GeomConvert_ApproxCurve,
    )
    fit = make_fit(trimmed, 0.00025, continuity, 100, 5)
    if (
        not cast("Callable[[], bool]", _member(fit, "IsDone"))()
        or cast("Callable[[], float]", _member(fit, "MaxError"))() > 0.00025
    ):
        raise ValueError("样条偏置无法达到 0.001 mm 的精度。")
    curve = cast("Callable[[], object]", _member(fit, "Curve"))()
    make_converter = cast(
        "Callable[[object], object]",
        import_module("OCP.GeomConvert").GeomConvert_BSplineCurveToBezierCurve,
    )
    converter = make_converter(curve)
    count = cast("Callable[[], int]", _member(converter, "NbArcs"))()
    arc_at = cast("Callable[[int], object]", _member(converter, "Arc"))
    pieces: list[tuple[Point2D, ...]] = []
    for index in range(1, count + 1):
        bezier = arc_at(index)
        if cast("Callable[[], bool]", _member(bezier, "IsRational"))():
            raise ValueError("不支持有理偏置样条。")
        pole_count = cast("Callable[[], int]", _member(bezier, "NbPoles"))()
        pole_at = cast("Callable[[int], object]", _member(bezier, "Pole"))
        controls: list[Point2D] = []
        for pole_index in range(1, pole_count + 1):
            point = pole_at(pole_index)
            x = cast("Callable[[], float]", _member(point, "X"))()
            y = cast("Callable[[], float]", _member(point, "Y"))()
            controls.append((x, y))
        pieces.extend(reduce_bezier(tuple(controls), 0.00025))
    start = edge.position_at(0)
    if pieces and math.dist((start.X, start.Y), pieces[-1][-1]) < math.dist(
        (start.X, start.Y), pieces[0][0]
    ):
        pieces = [tuple(reversed(piece)) for piece in reversed(pieces)]
    return pieces
