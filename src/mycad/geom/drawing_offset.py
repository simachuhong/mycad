# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Convert exact OCCT drawing offsets into neutral sketch entities."""

from __future__ import annotations

import math
from collections.abc import Callable
from importlib import import_module
from typing import cast
from uuid import uuid4

from build123d import Edge, Face, GeomType, Wire

from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.sketch import (
    ArcEntity,
    LineEntity,
    Point2D,
    PolylineEntity,
    polyline_self_intersection,
)
from mycad.core.sketch_edit import validate_curved_offset_source


def _member(value: object, name: str) -> object:
    return getattr(value, name)


def offset_closed_path(
    source: PolylineEntity, distance: float, gap_type: int = 0
) -> tuple[PolylineEntity, ...]:
    """Offset a path on its directed left; retain every representable component."""
    if isinstance(gap_type, bool) or gap_type not in (0, 1, 2):
        raise ValueError("偏置间隙模式须为 0、1 或 2。")
    if not source.closed and source.bulges:
        validate_curved_offset_source(source)
    if not math.isfinite(distance) or abs(distance) <= 1e-9:
        raise ValueError("偏置距离须为非零有限值。")
    points = source.points_mm
    next_points = (*points[1:], points[0]) if source.closed else points[1:]
    pairs = tuple(zip(points, next_points, strict=source.closed))
    segments = polyline_curve_segments(
        points, source.bulges or (0.0,) * len(pairs), source.closed, source.entity_id
    )
    edges: list[Edge] = []
    area = 0.0
    for segment, (a, b) in zip(segments, pairs, strict=True):
        if isinstance(segment, LineEntity):
            edges.append(Edge.make_line((*a, 0), (*b, 0)))
            area += a[0] * b[1] - b[0] * a[1]
        else:
            middle = math.radians(segment.start_angle_deg + segment.sweep_angle_deg / 2)
            middle_point = (
                segment.center_mm[0] + segment.radius_mm * math.cos(middle),
                segment.center_mm[1] + segment.radius_mm * math.sin(middle),
                0,
            )
            edges.append(Edge.make_three_point_arc((*a, 0), middle_point, (*b, 0)))
            area += (
                segment.center_mm[0] * (b[1] - a[1])
                - segment.center_mm[1] * (b[0] - a[0])
                + segment.radius_mm**2 * math.radians(segment.sweep_angle_deg)
            )
    if source.closed and (not math.isfinite(area) or abs(area) <= 1e-9):
        raise ValueError("偏置源轮廓面积无效。")
    if (
        not source.closed
        and not source.bulges
        and polyline_self_intersection(points, closed=False) is not None
    ):
        raise ValueError("偏置源路径自交或重叠。")
    wire = Wire(edges)
    try:
        if not wire.is_valid or (source.closed and not Face(wire).is_valid):
            raise ValueError("偏置源轮廓自交或退化。")
    except RuntimeError as exc:
        raise ValueError("偏置源轮廓无效。") from exc
    make_offset = cast(
        "Callable[[object, object, bool], object]",
        import_module("OCP.BRepOffsetAPI").BRepOffsetAPI_MakeOffset,
    )
    geom_abs = import_module("OCP.GeomAbs")
    join = cast("object", geom_abs.GeomAbs_Intersection if gap_type == 0 else geom_abs.GeomAbs_Arc)
    wire_kind = cast("object", import_module("OCP.TopAbs").TopAbs_WIRE)
    make_explorer = cast(
        "Callable[[object, object], object]", import_module("OCP.TopExp").TopExp_Explorer
    )
    wire_cast = cast("Callable[[object], object]", import_module("OCP.TopoDS").TopoDS.Wire_s)
    wrap_wire = cast("Callable[[object], Wire]", Wire)
    try:
        builder = make_offset(wire.wrapped, join, not source.closed)
        cast("Callable[[float], None]", _member(builder, "Perform"))(
            (-math.copysign(1.0, area) if source.closed else -1.0) * distance
        )
        if not cast("Callable[[], bool]", _member(builder, "IsDone"))():
            raise ValueError("偏置无法完成。")
        shape = cast("Callable[[], object]", _member(builder, "Shape"))()
        explorer = make_explorer(shape, wire_kind)
        more = cast("Callable[[], bool]", _member(explorer, "More"))
        current = cast("Callable[[], object]", _member(explorer, "Current"))
        advance = cast("Callable[[], None]", _member(explorer, "Next"))
        result: list[PolylineEntity] = []
        while more():
            output = wrap_wire(wire_cast(current()))
            ordered = output.order_edges()
            if output.is_closed != source.closed:
                raise ValueError("偏置结果的开闭状态发生变化。")
            vertices, bulges = _convert_edges(ordered, gap_type, source, distance)
            result.append(
                PolylineEntity(
                    uuid4().hex,
                    vertices,
                    source.closed,
                    source.construction,
                    source.layer_name,
                    bulges,
                )
            )
            advance()
        if not result:
            raise ValueError("偏置后没有剩余轮廓。")
        return tuple(result)
    except RuntimeError as exc:
        raise ValueError("偏置几何计算失败。") from exc


def _convert_edges(
    edges: list[Edge], gap_type: int, source: PolylineEntity, distance: float
) -> tuple[tuple[Point2D, ...], tuple[float, ...]]:
    closed = source.closed
    starts: list[Point2D] = []
    ends: list[Point2D] = []
    bulges: list[float] = []
    centers: list[Point2D | None] = []
    for edge in edges:
        start, mid, end = (edge.position_at(t) for t in (0, 0.5, 1))
        starts.append((start.X, start.Y))
        ends.append((end.X, end.Y))
        if edge.geom_type == GeomType.LINE:
            bulges.append(0.0)
            centers.append(None)
        elif edge.geom_type == GeomType.CIRCLE:
            center = edge.arc_center
            angles = [math.atan2(p.Y - center.Y, p.X - center.X) for p in (start, mid, end)]
            ccw = (angles[2] - angles[0]) % math.tau
            sweep = ccw if (angles[1] - angles[0]) % math.tau <= ccw + 1e-10 else ccw - math.tau
            bulges.append(math.tan(sweep / 4))
            centers.append((center.X, center.Y))
        else:
            raise ValueError("偏置结果包含无法保存的曲线。")
    if gap_type == 2:
        source_curves = polyline_curve_segments(
            source.points_mm,
            source.bulges
            or (0.0,) * (len(source.points_mm) if closed else len(source.points_mm) - 1),
            closed,
            source.entity_id,
        )
        originals = [curve for curve in source_curves if isinstance(curve, ArcEntity)]
        tolerance = max(1e-7, abs(distance) * 1e-8)
        corners: set[int] = set()
        for index, center in enumerate(centers):
            if center is None:
                continue
            radius = math.dist(center, starts[index])
            original = any(
                math.dist(center, arc.center_mm) <= tolerance
                and abs(
                    radius - (arc.radius_mm - distance * math.copysign(1.0, arc.sweep_angle_deg))
                )
                <= tolerance
                for arc in originals
            )
            corner = abs(radius - abs(distance)) <= tolerance and any(
                math.dist(center, vertex) <= tolerance for vertex in source.points_mm
            )
            if original and corner:
                raise ValueError("偏置圆弧来源不明确。")
            if corner:
                corners.add(index)
            elif not original:
                raise ValueError("偏置圆弧来源无法验证。")
        directions: list[Point2D] = []
        anchors: list[Point2D] = []
        for index, center in enumerate(centers):
            if index not in corners:
                anchors.append(starts[index])
                directions.append(
                    (ends[index][0] - starts[index][0], ends[index][1] - starts[index][1])
                )
            else:
                assert center is not None
                mid = edges[index].position_at(0.5)
                anchors.append((mid.X, mid.Y))
                normal = (mid.X - center[0], mid.Y - center[1])
                direction = (-normal[1], normal[0])
                chord = (ends[index][0] - starts[index][0], ends[index][1] - starts[index][1])
                if direction[0] * chord[0] + direction[1] * chord[1] < 0:
                    direction = (-direction[0], -direction[1])
                directions.append(direction)
        for index in range(len(edges) if closed else len(edges) - 1):
            following = (index + 1) % len(edges)
            if index not in corners and following not in corners:
                continue
            original_circle = next(
                (i for i in (index, following) if centers[i] is not None and i not in corners), None
            )
            if original_circle is None:
                a, b = anchors[index], anchors[following]
                u, v = directions[index], directions[following]
                cross = u[0] * v[1] - u[1] * v[0]
                if abs(cross) <= 1e-12:
                    raise ValueError("偏置倒角方向不明确。")
                ratio = ((b[0] - a[0]) * v[1] - (b[1] - a[1]) * v[0]) / cross
                point = (a[0] + ratio * u[0], a[1] + ratio * u[1])
            else:
                line_index = following if original_circle == index else index
                center = centers[original_circle]
                assert center is not None
                a, direction = anchors[line_index], directions[line_index]
                length = math.hypot(*direction)
                if length <= 1e-12:
                    raise ValueError("偏置倒角方向不明确。")
                unit = (direction[0] / length, direction[1] / length)
                delta = (a[0] - center[0], a[1] - center[1])
                projection = delta[0] * unit[0] + delta[1] * unit[1]
                radius = math.dist(center, starts[original_circle])
                discriminant = projection**2 - (delta[0] ** 2 + delta[1] ** 2 - radius**2)
                if discriminant < -tolerance:
                    raise ValueError("偏置倒角与圆弧不相交。")
                root = math.sqrt(max(0.0, discriminant))
                hits = [
                    (
                        a[0] + (-projection + sign * root) * unit[0],
                        a[1] + (-projection + sign * root) * unit[1],
                    )
                    for sign in (-1, 1)
                ]
                shared = ends[index]
                hits.sort(key=lambda hit: math.dist(hit, shared))
                if (
                    abs(math.dist(hits[0], shared) - math.dist(hits[1], shared)) <= tolerance
                    and root > tolerance
                ):
                    raise ValueError("偏置倒角与圆弧的交点不唯一。")
                point = hits[0]
            ends[index] = starts[following] = point
        for index, center in enumerate(centers):
            if center is not None and index not in corners:
                first = math.atan2(starts[index][1] - center[1], starts[index][0] - center[0])
                last = math.atan2(ends[index][1] - center[1], ends[index][0] - center[0])
                original_sweep = 4 * math.atan(bulges[index])
                sign = math.copysign(1.0, original_sweep)
                sweep = sign * ((sign * (last - first)) % math.tau)
                if abs(sweep) <= 1e-9 or abs(sweep - original_sweep) > math.pi:
                    raise ValueError("偏置倒角使圆弧退化或换支。")
                bulges[index] = math.tan(sweep / 4)
            else:
                direction = directions[index]
                if (
                    (ends[index][0] - starts[index][0]) * direction[0]
                    + (ends[index][1] - starts[index][1]) * direction[1]
                ) <= 1e-10:
                    raise ValueError("偏置倒角发生退化或反转。")
                bulges[index] = 0.0
    for index, end in enumerate(ends if closed else ends[:-1]):
        if math.dist(end, starts[(index + 1) % len(starts)]) > 1e-7:
            raise ValueError("偏置结果不连续。")
    return tuple(starts if closed else (*starts, ends[-1])), tuple(bulges)
