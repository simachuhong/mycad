# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Build closed planar BREP profiles from replayed neutral sketch entities."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol, cast

from build123d import Edge, Face, Plane, Vector, Wire

from mycad.core.exceptions import GeometryBuildError
from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    EllipseEntity,
    LineEntity,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SplineEntity,
)

Point2D = tuple[float, float]
Point3D = tuple[float, float, float]


class _BoundaryDistance(Protocol):
    """Narrow the upstream generic Shape parameter to the wire pair we use."""

    def distance_to_with_closest_points(self, other: Wire) -> tuple[float, Vector, Vector]: ...


@dataclass(frozen=True, slots=True)
class _Curve:
    start: Point2D
    end: Point2D
    points: tuple[Point2D, ...]
    edge: Edge
    entity_id: str


@dataclass(frozen=True, slots=True)
class _Contour:
    wire: Wire
    points: tuple[Point2D, ...]
    entity_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SketchRegion:
    """Exact face and stable authored identities of its boundary contours."""

    face: Face
    boundary_entity_ids: tuple[str, ...]
    hole_entity_ids: tuple[tuple[str, ...], ...]


def _distance(first: Point2D, second: Point2D) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _world(sketch: Sketch, point: Point2D) -> Point3D:
    return sketch.frame.local_to_world(point)


def _line_curve(sketch: Sketch, start: Point2D, end: Point2D, entity_id: str) -> _Curve:
    return _Curve(
        start,
        end,
        (start, end),
        Edge.make_line(_world(sketch, start), _world(sketch, end)),
        entity_id,
    )


def _arc_curve(sketch: Sketch, arc: ArcEntity) -> _Curve:
    step_count = max(2, math.ceil(abs(arc.sweep_angle_deg) / 7.5))
    points = tuple(
        (
            arc.center_mm[0]
            + arc.radius_mm
            * math.cos(math.radians(arc.start_angle_deg + arc.sweep_angle_deg * i / step_count)),
            arc.center_mm[1]
            + arc.radius_mm
            * math.sin(math.radians(arc.start_angle_deg + arc.sweep_angle_deg * i / step_count)),
        )
        for i in range(step_count + 1)
    )
    # The authored midpoint disambiguates major arcs and clockwise sweeps.
    midpoint = points[step_count // 2]
    if step_count % 2 == 1:
        middle_angle = math.radians(arc.start_angle_deg + arc.sweep_angle_deg / 2.0)
        midpoint = (
            arc.center_mm[0] + arc.radius_mm * math.cos(middle_angle),
            arc.center_mm[1] + arc.radius_mm * math.sin(middle_angle),
        )
    edge = Edge.make_three_point_arc(
        _world(sketch, points[0]), _world(sketch, midpoint), _world(sketch, points[-1])
    )
    return _Curve(points[0], points[-1], points, edge, arc.entity_id)


def _occt_member(value: object, name: str) -> object:
    """Resolve one member at the untyped extension boundary."""
    return getattr(value, name)


def _set_occt_array_value(array: object, index: int, value: object) -> None:
    setter = cast("Callable[[int, object], None]", _occt_member(array, "SetValue"))
    setter(index, value)


def spline_edge(sketch: Sketch, entity: SplineEntity) -> Edge:
    """Build an exact curve; narrow the untyped OCP boundary to APIs used here."""
    point_array = cast(
        "Callable[[int, int], object]", import_module("OCP.TColgp").TColgp_Array1OfPnt
    )
    real_array = cast(
        "Callable[[int, int], object]", import_module("OCP.TColStd").TColStd_Array1OfReal
    )
    int_array = cast(
        "Callable[[int, int], object]", import_module("OCP.TColStd").TColStd_Array1OfInteger
    )
    make_point = cast("Callable[[float, float, float], object]", import_module("OCP.gp").gp_Pnt)
    make_curve = cast(
        "Callable[[object, object, object, int, bool], object]",
        import_module("OCP.Geom").Geom_BSplineCurve,
    )
    make_edge = cast(
        "Callable[[object], object]",
        import_module("OCP.BRepBuilderAPI").BRepBuilderAPI_MakeEdge,
    )
    wrap_edge = cast("Callable[[object], Edge]", Edge)
    poles = point_array(1, len(entity.control_points_mm))
    for index, point in enumerate(entity.control_points_mm, 1):
        _set_occt_array_value(poles, index, make_point(*_world(sketch, point)))
    values = tuple(dict.fromkeys(entity.knots))
    knots = real_array(1, len(values))
    multiplicities = int_array(1, len(values))
    for index, value in enumerate(values, 1):
        _set_occt_array_value(knots, index, value)
        _set_occt_array_value(multiplicities, index, entity.knots.count(value))
    curve = make_curve(poles, knots, multiplicities, 3, False)
    edge_value = cast("Callable[[], object]", _occt_member(make_edge(curve), "Edge"))
    return wrap_edge(edge_value())


def _entities_to_curves(sketch: Sketch) -> tuple[list[_Curve], list[_Contour]]:
    curves: list[_Curve] = []
    contours: list[_Contour] = []
    for entity in sketch.entities:
        if entity.construction or isinstance(entity, PointEntity):
            continue
        if isinstance(entity, EllipseEntity):
            from mycad.geom.offset_ellipse import ellipse_edge

            points = entity.sampled_points()
            edge = ellipse_edge(entity, frame=sketch.frame)
            if entity.closed:
                contours.append(_Contour(Wire([edge]), points[:-1], (entity.entity_id,)))
            else:
                curves.append(_Curve(points[0], points[-1], points, edge, entity.entity_id))
        elif isinstance(entity, CircleEntity):
            center = _world(sketch, entity.center_mm)
            plane = Plane(origin=center, x_dir=sketch.frame.u_axis, z_dir=sketch.frame.normal)
            points = tuple(
                (
                    entity.center_mm[0] + entity.radius_mm * math.cos(2.0 * math.pi * index / 128),
                    entity.center_mm[1] + entity.radius_mm * math.sin(2.0 * math.pi * index / 128),
                )
                for index in range(128)
            )
            contours.append(
                _Contour(Wire.make_circle(entity.radius_mm, plane), points, (entity.entity_id,))
            )
        elif isinstance(entity, SplineEntity):
            points = entity.sampled_points()
            curves.append(
                _Curve(points[0], points[-1], points, spline_edge(sketch, entity), entity.entity_id)
            )
        elif isinstance(entity, LineEntity):
            curves.append(_line_curve(sketch, entity.start_mm, entity.end_mm, entity.entity_id))
        elif isinstance(entity, PolylineEntity):
            if entity.bulges:
                segments = polyline_curve_segments(
                    entity.points_mm, entity.bulges, entity.closed, entity.entity_id
                )
                curves.extend(
                    _arc_curve(sketch, segment)
                    if isinstance(segment, ArcEntity)
                    else _line_curve(sketch, segment.start_mm, segment.end_mm, entity.entity_id)
                    for segment in segments
                )
            else:
                pairs = list(zip(entity.points_mm, entity.points_mm[1:], strict=False))
                if entity.closed:
                    pairs.append((entity.points_mm[-1], entity.points_mm[0]))
                curves.extend(
                    _line_curve(sketch, start, end, entity.entity_id) for start, end in pairs
                )
        elif isinstance(entity, RectangleEntity):
            first_u, first_v = entity.first_corner_mm
            opposite_u, opposite_v = entity.opposite_corner_mm
            points = (
                (first_u, first_v),
                (opposite_u, first_v),
                (opposite_u, opposite_v),
                (first_u, opposite_v),
            )
            curves.extend(
                _line_curve(sketch, start, end, entity.entity_id)
                for start, end in zip(points, (*points[1:], points[0]), strict=True)
            )
        else:
            curves.append(_arc_curve(sketch, entity))
    return curves, contours


def _node_index(nodes: list[Point2D], point: Point2D, tolerance: float) -> int:
    for index, node in enumerate(nodes):
        if _distance(node, point) <= tolerance:
            return index
    nodes.append(point)
    return len(nodes) - 1


def _located_error(
    message: str, identities: Sequence[str], points: Sequence[Point2D]
) -> GeometryBuildError:
    coordinates = "; ".join(f"({u:.9g}, {v:.9g})" for u, v in points)
    ids = ", ".join(dict.fromkeys(identities))
    return GeometryBuildError(
        f"{message} 草图局部 U/V (mm)：{coordinates}；相关图元：{ids}",
        command_id="feature.extrude",
    )


def _curve_contours(curves: list[_Curve], tolerance: float) -> list[_Contour]:
    if not curves:
        return []
    nodes: list[Point2D] = []
    endpoints = [
        (_node_index(nodes, curve.start, tolerance), _node_index(nodes, curve.end, tolerance))
        for curve in curves
    ]
    adjacency: dict[int, list[int]] = defaultdict(list)
    for index, (start, end) in enumerate(endpoints):
        if start == end:
            raise _located_error(
                "草图轮廓包含退化边。",
                (curves[index].entity_id,),
                (curves[index].start, curves[index].end),
            )
        adjacency[start].append(index)
        adjacency[end].append(index)
    for node, edges in adjacency.items():
        if len(edges) != 2:
            raise _located_error(
                "闭合轮廓存在开口；请检查此端点。"
                if len(edges) == 1
                else "草图轮廓在此端点存在多条分支；请检查连接。",
                tuple(curves[index].entity_id for index in edges),
                (nodes[node],),
            )

    unused = set(range(len(curves)))
    result: list[_Contour] = []
    while unused:
        first_edge = min(unused)
        start_node = endpoints[first_edge][0]
        current_node = start_node
        current_edge = first_edge
        ordered_edges: list[int] = []
        polygon_points: list[Point2D] = []
        while True:
            if current_edge not in unused:
                raise GeometryBuildError("草图轮廓发生重复连接。", command_id="feature.extrude")
            unused.remove(current_edge)
            edge_start, edge_end = endpoints[current_edge]
            if current_node == edge_start:
                next_node = edge_end
                curve_points = curves[current_edge].points
            else:
                next_node = edge_start
                curve_points = tuple(reversed(curves[current_edge].points))
            ordered_edges.append(current_edge)
            polygon_points.extend(curve_points[:-1])
            if next_node == start_node:
                break
            candidates = [edge for edge in adjacency[next_node] if edge in unused]
            if len(candidates) != 1:
                raise GeometryBuildError("草图轮廓未形成单一闭环。", command_id="feature.extrude")
            current_node, current_edge = next_node, candidates[0]
        identities = tuple(dict.fromkeys(curves[index].entity_id for index in ordered_edges))
        try:
            wires = Wire.combine([curves[index].edge for index in ordered_edges], tol=tolerance)
        except Exception as exc:
            raise GeometryBuildError(
                f"草图轮廓无法组合成闭环：{exc}", command_id="feature.extrude"
            ) from exc
        if len(wires) != 1 or not wires[0].is_closed:
            raise GeometryBuildError("草图轮廓无法闭合。", command_id="feature.extrude")
        result.append(_Contour(wires[0], tuple(polygon_points), identities))
    return result


def _orientation(first: Point2D, second: Point2D, third: Point2D) -> float:
    return (second[0] - first[0]) * (third[1] - first[1]) - (second[1] - first[1]) * (
        third[0] - first[0]
    )


def _segments_intersect(
    first_start: Point2D,
    first_end: Point2D,
    second_start: Point2D,
    second_end: Point2D,
    tolerance: float,
) -> bool:
    orientations = (
        _orientation(first_start, first_end, second_start),
        _orientation(first_start, first_end, second_end),
        _orientation(second_start, second_end, first_start),
        _orientation(second_start, second_end, first_end),
    )
    extent = max(
        _distance(first_start, first_end),
        _distance(second_start, second_end),
        1.0,
    )
    epsilon = tolerance * extent
    if orientations[0] * orientations[1] < -(epsilon**2) and orientations[2] * orientations[3] < -(
        epsilon**2
    ):
        return True
    for orientation, start, end, point in (
        (orientations[0], first_start, first_end, second_start),
        (orientations[1], first_start, first_end, second_end),
        (orientations[2], second_start, second_end, first_start),
        (orientations[3], second_start, second_end, first_end),
    ):
        if (
            abs(orientation) <= epsilon
            and min(start[0], end[0]) - tolerance <= point[0] <= max(start[0], end[0]) + tolerance
            and min(start[1], end[1]) - tolerance <= point[1] <= max(start[1], end[1]) + tolerance
        ):
            return True
    return False


def _self_intersection_points(
    points: Sequence[Point2D], tolerance: float
) -> tuple[Point2D, ...] | None:
    pairs = tuple(zip(points, (*points[1:], points[0]), strict=True))
    for first_index, (first_start, first_end) in enumerate(pairs):
        for second_index in range(first_index + 1, len(pairs)):
            if second_index == first_index + 1 or (
                first_index == 0 and second_index == len(pairs) - 1
            ):
                continue
            second_start, second_end = pairs[second_index]
            if _segments_intersect(first_start, first_end, second_start, second_end, tolerance):
                return (first_start, first_end, second_start, second_end)
    return None


def _checked_contour_face(contour: _Contour, tolerance: float) -> Face:
    """Use the exact BREP for validity; sampled segments only locate an error."""
    try:
        face = Face(contour.wire)
        if face.is_valid and face.area > tolerance * tolerance:
            return face
    except (ValueError, RuntimeError):
        pass
    crossing = _self_intersection_points(contour.points, tolerance)
    if crossing is not None:
        raise _located_error(
            "草图闭合轮廓存在自相交；以下两对点为交叉区段端点。",
            contour.entity_ids,
            crossing,
        )
    raise _located_error(
        "草图轮廓面积为零或闭环无效；轮廓起点如下。",
        contour.entity_ids,
        contour.points[:1],
    )


def _reverse(wire: Wire) -> Wire:
    reversed_wires = Wire.combine([edge.reversed() for edge in wire.edges()])
    if len(reversed_wires) != 1 or not reversed_wires[0].is_closed:
        raise GeometryBuildError("草图轮廓方向校正失败。", command_id="feature.extrude")
    return reversed_wires[0]


def make_sketch_regions(sketch: Sketch) -> tuple[SketchRegion, ...]:
    """Create valid planar regions with their authored boundary identities."""
    curves, circles = _entities_to_curves(sketch)
    points = [point for curve in curves for point in curve.points]
    points.extend(point for contour in circles for point in contour.points)
    if not points:
        raise GeometryBuildError("草图没有可用的闭合轮廓。", command_id="feature.extrude")
    extent = max(
        max(point[0] for point in points) - min(point[0] for point in points),
        max(point[1] for point in points) - min(point[1] for point in points),
        1.0,
    )
    tolerance = max(1e-8, extent * 1e-9)
    contours = [*_curve_contours(curves, tolerance), *circles]
    if not contours:
        raise GeometryBuildError("草图没有可用的闭合轮廓。", command_id="feature.extrude")
    contour_faces = [_checked_contour_face(contour, tolerance) for contour in contours]
    for first_index, first in enumerate(contours):
        for second in contours[first_index + 1 :]:
            distance, first_point, second_point = cast(
                "_BoundaryDistance", first.wire
            ).distance_to_with_closest_points(second.wire)
            if distance <= tolerance:
                raise _located_error(
                    "草图内外轮廓不能相交或相切；精确边界接触位置如下。",
                    (*first.entity_ids, *second.entity_ids),
                    (
                        sketch.frame.world_to_local((first_point.X, first_point.Y, first_point.Z)),
                        sketch.frame.world_to_local(
                            (second_point.X, second_point.Y, second_point.Z)
                        ),
                    ),
                )
    # Once exact boundary contact has been excluded, any boundary point is a
    # reliable containment probe, including nested islands near curved edges.
    containing = [
        [
            other_index
            for other_index, face in enumerate(contour_faces)
            if index != other_index and face.is_inside(_world(sketch, contour.points[0]), tolerance)
        ]
        for index, contour in enumerate(contours)
    ]
    depths = [len(parents) for parents in containing]
    parents = {
        index: max(candidates, key=lambda candidate: depths[candidate], default=None)
        for index, candidates in enumerate(containing)
    }
    positive = [face.normal_at().dot(Vector(sketch.frame.normal)) > 0 for face in contour_faces]

    regions: list[SketchRegion] = []
    for outer_index, depth in enumerate(depths):
        if depth % 2:
            continue
        outer = contours[outer_index]
        hole_indices = [
            index
            for index, parent in parents.items()
            if parent == outer_index and depths[index] == depth + 1
        ]
        outer_wire = outer.wire if positive[outer_index] else _reverse(outer.wire)
        hole_wires = [
            contours[index].wire if not positive[index] else _reverse(contours[index].wire)
            for index in hole_indices
        ]
        try:
            face = Face(outer_wire, inner_wires=hole_wires)
        except Exception as exc:
            raise GeometryBuildError(
                f"草图轮廓无效，请检查开口、自交或相交内环：{exc}",
                command_id="feature.extrude",
            ) from exc
        if not face.is_valid or face.area <= tolerance * tolerance:
            raise GeometryBuildError(
                "草图轮廓无效，请检查开口、自交或相交内环。", command_id="feature.extrude"
            )
        regions.append(
            SketchRegion(
                face,
                tuple(sorted(outer.entity_ids)),
                tuple(sorted(tuple(sorted(contours[index].entity_ids)) for index in hole_indices)),
            )
        )
    if not regions:
        raise GeometryBuildError("草图没有有效的实体区域。", command_id="feature.extrude")
    return tuple(regions)


def make_sketch_faces(sketch: Sketch) -> tuple[Face, ...]:
    """Create valid planar regions from every even-depth contour and its holes."""
    return tuple(region.face for region in make_sketch_regions(sketch))


def select_sketch_region(
    sketch: Sketch, boundary_entity_ids: tuple[str, ...], *, command_id: str = "feature.extrude"
) -> SketchRegion:
    """Resolve an authored contour without guessing when a region has changed."""
    identity = tuple(sorted(boundary_entity_ids))
    matches = [
        region for region in make_sketch_regions(sketch) if region.boundary_entity_ids == identity
    ]
    if not identity or len(set(identity)) != len(identity) or len(matches) != 1:
        raise GeometryBuildError(
            "草图区域引用已失效或存在歧义，请重新选择区域。", command_id=command_id
        )
    return matches[0]


def make_sketch_face(sketch: Sketch) -> Face:
    """Create a single-region face for consumers that require one profile."""
    faces = make_sketch_faces(sketch)
    if len(faces) != 1:
        raise GeometryBuildError(
            "此操作要求一个连续草图区域；请分开选择实体岛。", command_id="feature.revolve"
        )
    return faces[0]
