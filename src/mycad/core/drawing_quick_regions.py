# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Bounded faces of planar finite linework for read-only measurement."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from mycad.core.drawing_measurement import (
    curve_intersections,
    line_boundary_intersections,
    polyline_area_perimeter,
)
from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Point2D, PolylineEntity


def _area(points: Sequence[Point2D]) -> float:
    ox, oy = points[0]
    return (
        math.fsum(
            (a[0] - ox) * (b[1] - oy) - (b[0] - ox) * (a[1] - oy)
            for a, b in zip(points, (*points[1:], points[0]), strict=True)
        )
        / 2
    )


def _perimeter(points: Sequence[Point2D]) -> float:
    return math.fsum(math.dist(a, b) for a, b in zip(points, (*points[1:], points[0]), strict=True))


def _on_boundary(points: Sequence[Point2D], point: Point2D) -> bool:
    x, y = point
    return any(
        (b[0] - a[0]) * (y - a[1]) == (b[1] - a[1]) * (x - a[0])
        and min(a[0], b[0]) <= x <= max(a[0], b[0])
        and min(a[1], b[1]) <= y <= max(a[1], b[1])
        for a, b in zip(points, (*points[1:], points[0]), strict=True)
    )


def _inside(points: Sequence[Point2D], point: Point2D) -> bool:
    if _on_boundary(points, point):
        return False
    x, y = point
    inside = False
    for a, b in zip(points, (*points[1:], points[0]), strict=True):
        dx, dy = b[0] - a[0], b[1] - a[1]
        if (a[1] > y) != (b[1] > y) and x < a[0] + (y - a[1]) * dx / dy:
            inside = not inside
    return inside


@dataclass(frozen=True)
class CircularBoundary:
    center: Point2D
    radius: float


type RegionBoundary = tuple[Point2D, ...] | CircularBoundary | PolylineEntity


def _curved_segments(entity: PolylineEntity) -> tuple[LineEntity | ArcEntity, ...]:
    return polyline_curve_segments(entity.points_mm, entity.bulges, True, entity.entity_id)


def _curved_contains(entity: PolylineEntity, point: Point2D) -> bool:
    x, y = point
    crossings = 0
    for index, segment in enumerate(_curved_segments(entity)):
        start = entity.points_mm[index]
        end = entity.points_mm[(index + 1) % len(entity.points_mm)]
        if isinstance(segment, LineEntity):
            if _on_boundary((start, end), point):
                return False
            if (start[1] > y) != (end[1] > y):
                crossings += x < start[0] + (y - start[1]) * (end[0] - start[0]) / (
                    end[1] - start[1]
                )
            continue
        cx, cy = segment.center_mm
        radius = segment.radius_mm
        start_angle = math.radians(segment.start_angle_deg)
        sweep = math.radians(segment.sweep_angle_deg)
        angles = [start_angle, start_angle + sweep]
        low, high = sorted(angles)
        first_extreme = math.ceil((low - math.pi / 2) / math.pi)
        last_extreme = math.floor((high - math.pi / 2) / math.pi)
        angles.extend(math.pi / 2 + k * math.pi for k in range(first_extreme, last_extreme + 1))
        angles.sort(reverse=sweep < 0)
        for a, b in zip(angles, angles[1:], strict=False):
            if a == b:
                continue
            ay = start[1] if a == start_angle else cy + radius * math.sin(a)
            by = end[1] if b == start_angle + sweep else cy + radius * math.sin(b)
            if (ay > y) != (by > y):
                offset = math.sqrt(max(0.0, (radius - abs(y - cy)) * (radius + abs(y - cy))))
                intersection_x = cx + math.copysign(offset, math.cos((a + b) / 2))
                if x == intersection_x:
                    return False
                crossings += x < intersection_x
        if point in (start, end):
            return False
    return bool(crossings % 2)


def _boundary_contains(boundary: RegionBoundary, point: Point2D) -> bool:
    if isinstance(boundary, CircularBoundary):
        return math.dist(boundary.center, point) < boundary.radius
    if isinstance(boundary, PolylineEntity):
        return not _curved_touches(boundary, point) and _curved_contains(boundary, point)
    return _inside(boundary, point)


def _boundary_touches(boundary: RegionBoundary, point: Point2D) -> bool:
    if isinstance(boundary, CircularBoundary):
        return math.dist(boundary.center, point) == boundary.radius
    if isinstance(boundary, PolylineEntity):
        return _curved_touches(boundary, point)
    return _on_boundary(boundary, point)


def _curved_touches(entity: PolylineEntity, point: Point2D) -> bool:
    for index, segment in enumerate(_curved_segments(entity)):
        start = entity.points_mm[index]
        end = entity.points_mm[(index + 1) % len(entity.points_mm)]
        if isinstance(segment, LineEntity):
            if _on_boundary((start, end), point):
                return True
        elif math.dist(segment.center_mm, point) == segment.radius_mm:
            angle = math.degrees(
                math.atan2(point[1] - segment.center_mm[1], point[0] - segment.center_mm[0])
            )
            delta = (
                (angle - segment.start_angle_deg)
                if segment.sweep_angle_deg > 0
                else (segment.start_angle_deg - angle)
            ) % 360
            if delta <= abs(segment.sweep_angle_deg):
                return True
        if point in (start, end):
            return True
    return False


@dataclass(frozen=True)
class LinearRegion:
    """One bounded face with direct nested boundaries removed as holes."""

    boundary: RegionBoundary
    holes: tuple[RegionBoundary, ...]
    area_mm2: float
    perimeter_mm: float

    def contains(self, point: Point2D) -> bool:
        return _boundary_contains(self.boundary, point) and not any(
            _boundary_contains(hole, point) or _boundary_touches(hole, point) for hole in self.holes
        )


@dataclass(frozen=True)
class SampledMeasuredRegion:
    """Exact measurement with sampled boundaries for display only."""

    boundary: tuple[Point2D, ...]
    holes: tuple[tuple[Point2D, ...], ...]
    area_mm2: float
    perimeter_mm: float


def build_linear_regions(lines: Sequence[LineEntity]) -> tuple[LinearRegion, ...]:
    """Split finite lines at intersections and construct their bounded faces."""
    cuts: list[list[Point2D]] = [[line.start_mm, line.end_mm] for line in lines]
    for i, first in enumerate(lines):
        for j in range(i + 1, len(lines)):
            points = line_boundary_intersections(first, lines[j])
            cuts[i].extend(points)
            cuts[j].extend(points)
    vertices: list[Point2D] = []
    vertex_ids: dict[Point2D, int] = {}
    adjacency: dict[int, set[int]] = {}

    def vertex(point: Point2D) -> int:
        existing = vertex_ids.get(point)
        if existing is not None:
            return existing
        vertices.append(point)
        index = len(vertices) - 1
        vertex_ids[point] = index
        adjacency[index] = set()
        return index

    for line, points in zip(lines, cuts, strict=True):
        ux = line.end_mm[0] - line.start_mm[0]
        uy = line.end_mm[1] - line.start_mm[1]
        axis = 0 if abs(ux) >= abs(uy) else 1
        ordered = sorted(
            points, key=lambda p: p[axis], reverse=line.end_mm[axis] < line.start_mm[axis]
        )
        indices = [vertex(point) for point in ordered]
        for a, b in zip(indices, indices[1:], strict=False):
            if a != b:
                adjacency[a].add(b)
                adjacency[b].add(a)
    pending = [index for index, neighbours in adjacency.items() if len(neighbours) < 2]
    while pending:
        index = pending.pop()
        for neighbour in tuple(adjacency[index]):
            adjacency[neighbour].remove(index)
            if len(adjacency[neighbour]) == 1:
                pending.append(neighbour)
        adjacency[index].clear()
    ordered_neighbours = {
        index: sorted(
            neighbours,
            key=lambda n: math.atan2(
                vertices[n][1] - vertices[index][1], vertices[n][0] - vertices[index][0]
            ),
        )
        for index, neighbours in adjacency.items()
    }
    visited: set[tuple[int, int]] = set()
    faces: list[tuple[Point2D, ...]] = []
    for start, neighbours in ordered_neighbours.items():
        for neighbour in neighbours:
            if (start, neighbour) in visited:
                continue
            first_edge = (start, neighbour)
            edge = first_edge
            indices: list[int] = []
            while edge not in visited:
                visited.add(edge)
                a, b = edge
                indices.append(a)
                around = ordered_neighbours[b]
                edge = (b, around[(around.index(a) - 1) % len(around)])
            if edge == first_edge and len(indices) >= 3:
                polygon = tuple(vertices[index] for index in indices)
                if _area(polygon) > 0:
                    faces.append(polygon)
    areas = [_area(face) for face in faces]
    parents: list[int | None] = []
    for i, face in enumerate(faces):
        containers = [
            j for j, other in enumerate(faces) if areas[j] > areas[i] and _inside(other, face[0])
        ]
        parents.append(min(containers, key=lambda j: areas[j]) if containers else None)
    result: list[LinearRegion] = []
    for i, face in enumerate(faces):
        holes = tuple(other for j, other in enumerate(faces) if parents[j] == i)
        area = areas[i] - math.fsum(_area(hole) for hole in holes)
        perimeter = _perimeter(face) + math.fsum(_perimeter(hole) for hole in holes)
        if not math.isfinite(area) or not math.isfinite(perimeter):
            raise ValueError("区域面积或周长超出可测量范围。")
        if area > 0:
            result.append(LinearRegion(face, holes, area, perimeter))
    return tuple(result)


def _line_crosses_circle(line: LineEntity, circle: CircleEntity) -> bool:
    dx = line.end_mm[0] - line.start_mm[0]
    dy = line.end_mm[1] - line.start_mm[1]
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length <= 0:
        raise ValueError("线段超出可测量范围。")
    ux, uy = dx / length, dy / length
    cx = circle.center_mm[0] - line.start_mm[0]
    cy = circle.center_mm[1] - line.start_mm[1]
    along = max(0.0, min(length, cx * ux + cy * uy))
    closest = (line.start_mm[0] + along * ux, line.start_mm[1] + along * uy)
    minimum = math.dist(closest, circle.center_mm)
    maximum = max(
        math.dist(line.start_mm, circle.center_mm), math.dist(line.end_mm, circle.center_mm)
    )
    return minimum <= circle.radius_mm <= maximum


def build_quick_regions(
    lines: Sequence[LineEntity],
    circles: Sequence[CircleEntity],
    curved_polylines: Sequence[PolylineEntity] = (),
    arcs: Sequence[ArcEntity] = (),
    open_curved_polylines: Sequence[PolylineEntity] = (),
) -> tuple[LinearRegion, ...]:
    """Build line and circular regions, including crossing boundaries and nesting."""
    unique_circles: dict[tuple[Point2D, float], CircleEntity] = {}
    for circle in circles:
        unique_circles.setdefault((circle.center_mm, circle.radius_mm), circle)
    circles = tuple(unique_circles.values())
    expanded_arcs = list(arcs)
    arc_endpoints: list[tuple[Point2D, Point2D]] = []
    if open_curved_polylines:
        from mycad.core.drawing_curved_arrangement import arc_point

        arc_endpoints.extend((arc_point(arc, 0), arc_point(arc, 1)) for arc in arcs)
        for polyline in open_curved_polylines:
            if polyline.closed or not polyline.bulges:
                raise ValueError("请选择开放曲线多段线。")
            for index, segment in enumerate(
                polyline_curve_segments(
                    polyline.points_mm, polyline.bulges, False, polyline.entity_id
                )
            ):
                if isinstance(segment, ArcEntity):
                    expanded_arcs.append(segment)
                    arc_endpoints.append((polyline.points_mm[index], polyline.points_mm[index + 1]))
    needs_arrangement = bool(expanded_arcs)
    for index, circle in enumerate(circles):
        if any(_line_crosses_circle(line, circle) for line in lines):
            needs_arrangement = True
        for other in circles[index + 1 :]:
            distance = math.dist(circle.center_mm, other.center_mm)
            if (
                abs(circle.radius_mm - other.radius_mm)
                <= distance
                <= circle.radius_mm + other.radius_mm
            ):
                needs_arrangement = True
    curve_groups = [_curved_segments(polyline) for polyline in curved_polylines]
    for polyline in curved_polylines:
        polyline_area_perimeter(polyline)
    expand_closed = False
    for index, group in enumerate(curve_groups):
        others: list[LineEntity | ArcEntity] = [*lines, *expanded_arcs]
        for circle in circles:
            others.extend(
                (
                    ArcEntity(circle.entity_id, circle.center_mm, circle.radius_mm, 0, 180),
                    ArcEntity(circle.entity_id, circle.center_mm, circle.radius_mm, 180, 180),
                )
            )
        others.extend(segment for other in curve_groups[index + 1 :] for segment in other)
        for segment in group:
            for other in others:
                try:
                    hits = curve_intersections(segment, other, None)
                except ValueError:
                    expand_closed = True
                    continue
                if hits:
                    expand_closed = True
    expanded_lines = list(lines)
    if expand_closed:
        from mycad.core.drawing_curved_arrangement import arc_point

        if not open_curved_polylines:
            arc_endpoints.extend((arc_point(arc, 0), arc_point(arc, 1)) for arc in arcs)
        for polyline, group in zip(curved_polylines, curve_groups, strict=True):
            for index, segment in enumerate(group):
                if isinstance(segment, LineEntity):
                    expanded_lines.append(segment)
                else:
                    expanded_arcs.append(segment)
                    arc_endpoints.append(
                        (
                            polyline.points_mm[index],
                            polyline.points_mm[(index + 1) % len(polyline.points_mm)],
                        )
                    )
        needs_arrangement = True
    if needs_arrangement:
        from mycad.core.drawing_curved_arrangement import build_curved_faces

        shapes: list[RegionBoundary] = [
            region.boundary
            for region in build_curved_faces(
                expanded_lines,
                circles,
                expanded_arcs,
                arc_endpoints if open_curved_polylines or expand_closed else None,
            )
        ]
    else:
        shapes = [region.boundary for region in build_linear_regions(lines)]
        shapes.extend(CircularBoundary(circle.center_mm, circle.radius_mm) for circle in circles)
    if not expand_closed:
        shapes.extend(curved_polylines)

    def shape_area(shape: RegionBoundary) -> float:
        if isinstance(shape, PolylineEntity):
            return polyline_area_perimeter(shape)[0]
        return math.pi * shape.radius**2 if isinstance(shape, CircularBoundary) else _area(shape)

    def shape_perimeter(shape: RegionBoundary) -> float:
        if isinstance(shape, PolylineEntity):
            return polyline_area_perimeter(shape)[1]
        return math.tau * shape.radius if isinstance(shape, CircularBoundary) else _perimeter(shape)

    areas = [shape_area(shape) for shape in shapes]
    if not all(math.isfinite(area) for area in areas):
        raise ValueError("区域面积超出可测量范围。")
    parents: list[int | None] = []
    for index, shape in enumerate(shapes):
        points = (
            (shape.center,)
            if isinstance(shape, CircularBoundary)
            else shape.points_mm
            if isinstance(shape, PolylineEntity)
            else shape
        )
        containers = [
            other
            for other, candidate in enumerate(shapes)
            if areas[other] > areas[index]
            and any(_boundary_contains(candidate, point) for point in points)
            and all(
                _boundary_contains(candidate, point) or _boundary_touches(candidate, point)
                for point in points
            )
        ]
        parents.append(min(containers, key=lambda other: areas[other]) if containers else None)
    result: list[LinearRegion] = []
    for index, shape in enumerate(shapes):
        holes = tuple(
            candidate for other, candidate in enumerate(shapes) if parents[other] == index
        )
        area = areas[index] - math.fsum(shape_area(hole) for hole in holes)
        perimeter = shape_perimeter(shape) + math.fsum(shape_perimeter(hole) for hole in holes)
        if not math.isfinite(area) or not math.isfinite(perimeter):
            raise ValueError("区域面积或周长超出可测量范围。")
        if area > 0:
            result.append(LinearRegion(shape, holes, area, perimeter))
    return tuple(result)
