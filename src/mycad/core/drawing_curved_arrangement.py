# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact circular and straight edge arrangements for read-only measurements."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from mycad.core.drawing_measurement import (
    curve_intersections,
    line_boundary_intersections,
    polyline_area_perimeter,
)
from mycad.core.drawing_quick_regions import LinearRegion
from mycad.core.polyline_curves import bulge_arc
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Point2D, PolylineEntity


@dataclass(frozen=True)
class _Edge:
    start: int
    end: int
    bulge: float
    source: tuple[str, int]


def _halves(circle: CircleEntity) -> tuple[ArcEntity, ArcEntity]:
    return (
        ArcEntity(circle.entity_id, circle.center_mm, circle.radius_mm, 0, 180),
        ArcEntity(circle.entity_id, circle.center_mm, circle.radius_mm, 180, 180),
    )


def arc_point(arc: ArcEntity, fraction: float) -> Point2D:
    """Return a point on a circular arc, using exact cardinal directions."""
    angle = (arc.start_angle_deg + fraction * arc.sweep_angle_deg) % 360
    cardinal = {
        0.0: (1.0, 0.0),
        90.0: (0.0, 1.0),
        180.0: (-1.0, 0.0),
        270.0: (0.0, -1.0),
    }
    ux, uy = cardinal.get(angle, (math.cos(math.radians(angle)), math.sin(math.radians(angle))))
    return (arc.center_mm[0] + arc.radius_mm * ux, arc.center_mm[1] + arc.radius_mm * uy)


def _signed_area(points: tuple[Point2D, ...], bulges: tuple[float, ...]) -> float:
    origin = points[0]
    terms: list[float] = []
    for index, (point, bulge) in enumerate(zip(points, bulges, strict=True)):
        following = points[(index + 1) % len(points)]
        ax, ay = point[0] - origin[0], point[1] - origin[1]
        bx, by = following[0] - origin[0], following[1] - origin[1]
        terms.append((ax * by - bx * ay) / 2)
        if bulge:
            theta = 4 * math.atan(bulge)
            radius = math.dist(point, following) * (abs(bulge) + 1 / abs(bulge)) / 4
            difference = (
                theta**3 / 6 - theta**5 / 120 + theta**7 / 5040
                if abs(theta) < 1e-3
                else theta - math.sin(theta)
            )
            terms.append(radius * radius * difference / 2)
    return math.fsum(terms)


def _simple_loops(
    point_ids: list[int], bulges: list[float]
) -> tuple[tuple[tuple[int, ...], tuple[float, ...]], ...]:
    """Separate a closed walk at repeated vertices, retaining directed edges."""
    path = [point_ids[0]]
    path_bulges: list[float] = []
    loops: list[tuple[tuple[int, ...], tuple[float, ...]]] = []
    for target, bulge in zip((*point_ids[1:], point_ids[0]), bulges, strict=True):
        path_bulges.append(bulge)
        if target in path:
            index = path.index(target)
            if len(path) - index >= 2:
                loops.append((tuple(path[index:]), tuple(path_bulges[index:])))
            path = path[: index + 1]
            path_bulges = path_bulges[:index]
        else:
            path.append(target)
    return tuple(loops)


def build_curved_faces(
    lines: Sequence[LineEntity],
    circles: Sequence[CircleEntity],
    arcs: Sequence[ArcEntity] = (),
    arc_endpoints: Sequence[tuple[Point2D, Point2D]] | None = None,
) -> tuple[LinearRegion, ...]:
    """Build bounded simple faces from crossing finite lines and full circles.

    Some tangencies, coincident boundaries and non-simple face loops are rejected.
    Nested disjoint components need a separate containment pass.
    """
    if not lines and not circles and not arcs:
        return ()
    unique_circles: dict[tuple[Point2D, float], CircleEntity] = {}
    for circle in circles:
        unique_circles.setdefault((circle.center_mm, circle.radius_mm), circle)
    circles = tuple(unique_circles.values())
    vertices: list[Point2D] = []
    tangent_pairs: dict[int, set[frozenset[tuple[str, int]]]] = {}

    def vertex(point: Point2D) -> int:
        for index, existing in enumerate(vertices):
            if existing == point:
                return index
            tolerance = 4 * max(math.ulp(value) for value in (*point, *existing))
            if math.dist(existing, point) <= tolerance:
                raise ValueError("区域顶点过近，无法可靠区分。")
        vertices.append(point)
        return len(vertices) - 1

    line_cuts: list[set[int]] = [{vertex(line.start_mm), vertex(line.end_mm)} for line in lines]
    circle_cuts: list[set[int]] = []
    for circle in circles:
        x, y = circle.center_mm
        radius = circle.radius_mm
        circle_cuts.append(
            {
                vertex(point)
                for point in ((x + radius, y), (x, y + radius), (x - radius, y), (x, y - radius))
            }
        )
    endpoints = (
        tuple((arc_point(arc, 0), arc_point(arc, 1)) for arc in arcs)
        if arc_endpoints is None
        else arc_endpoints
    )
    if len(endpoints) != len(arcs):
        raise ValueError("圆弧端点数量不匹配。")
    arc_terminals = [(vertex(start), vertex(end)) for start, end in endpoints]
    arc_cuts: list[set[int]] = [
        {start, vertex(arc_point(arc, 0.5)), end}
        for arc, (start, end) in zip(arcs, arc_terminals, strict=True)
    ]

    def hit_vertex(point: Point2D, shared_ids: set[int], radius: float) -> int:
        matches = [
            index
            for index in shared_ids
            if math.dist(vertices[index], point) <= 16 * math.ulp(radius)
        ]
        if len(matches) > 1:
            raise ValueError("区域交点过近，无法可靠区分。")
        return matches[0] if matches else vertex(point)

    for index, line in enumerate(lines):
        for other_index in range(index + 1, len(lines)):
            hits = line_boundary_intersections(line, lines[other_index])
            for point in hits:
                identity = vertex(point)
                line_cuts[index].add(identity)
                line_cuts[other_index].add(identity)
        dx = line.end_mm[0] - line.start_mm[0]
        dy = line.end_mm[1] - line.start_mm[1]
        length = math.hypot(dx, dy)
        for circle_index, circle in enumerate(circles):
            for half in _halves(circle):
                for point in curve_intersections(line, half, None):
                    dot = (
                        (point[0] - circle.center_mm[0]) * dx
                        + (point[1] - circle.center_mm[1]) * dy
                    ) / length
                    identity = vertex(point)
                    if dot == 0:
                        tangent_pairs.setdefault(identity, set()).add(
                            frozenset((("line", index), ("circle", circle_index)))
                        )
                    elif abs(dot) <= 32 * math.ulp(circle.radius_mm):
                        raise ValueError("圆与直线接近相切，无法可靠分割区域。")
                    line_cuts[index].add(identity)
                    circle_cuts[circle_index].add(identity)
        for arc_index, arc in enumerate(arcs):
            shared_ids = line_cuts[index] & arc_cuts[arc_index]
            shared = vertices[next(iter(shared_ids))] if len(shared_ids) == 1 else None
            for point in curve_intersections(line, arc, shared):
                identity = hit_vertex(point, shared_ids, arc.radius_mm)
                dot = (
                    (point[0] - arc.center_mm[0]) * dx + (point[1] - arc.center_mm[1]) * dy
                ) / length
                if dot == 0:
                    tangent_pairs.setdefault(identity, set()).add(
                        frozenset((("line", index), ("arc", arc_index)))
                    )
                elif abs(dot) <= 32 * math.ulp(arc.radius_mm):
                    raise ValueError("圆弧与直线接近相切，无法可靠分割区域。")
                line_cuts[index].add(identity)
                arc_cuts[arc_index].add(identity)
    for index, circle in enumerate(circles):
        for other_index in range(index + 1, len(circles)):
            other = circles[other_index]
            center_distance = math.dist(circle.center_mm, other.center_mm)
            if center_distance == 0 and circle.radius_mm == other.radius_mm:
                raise ValueError("圆边界重叠，无法确定封闭区域。")
            for first in _halves(circle):
                for second in _halves(other):
                    for point in curve_intersections(first, second, None):
                        ax, ay = point[0] - circle.center_mm[0], point[1] - circle.center_mm[1]
                        bx, by = point[0] - other.center_mm[0], point[1] - other.center_mm[1]
                        identity = vertex(point)
                        cross = ax * by - ay * bx
                        if cross == 0:
                            tangent_pairs.setdefault(identity, set()).add(
                                frozenset((("circle", index), ("circle", other_index)))
                            )
                        elif abs(cross) <= 32 * math.ulp(circle.radius_mm * other.radius_mm):
                            raise ValueError("圆之间接近相切，无法可靠分割区域。")
                        circle_cuts[index].add(identity)
                        circle_cuts[other_index].add(identity)
        for arc_index, arc in enumerate(arcs):
            if circle.center_mm == arc.center_mm and circle.radius_mm == arc.radius_mm:
                continue
            for half in _halves(circle):
                for point in curve_intersections(half, arc, None):
                    ax, ay = point[0] - circle.center_mm[0], point[1] - circle.center_mm[1]
                    bx, by = point[0] - arc.center_mm[0], point[1] - arc.center_mm[1]
                    identity = hit_vertex(
                        point, circle_cuts[index] & arc_cuts[arc_index], arc.radius_mm
                    )
                    cross = ax * by - ay * bx
                    if cross == 0:
                        tangent_pairs.setdefault(identity, set()).add(
                            frozenset((("circle", index), ("arc", arc_index)))
                        )
                    elif abs(cross) <= 32 * math.ulp(circle.radius_mm * arc.radius_mm):
                        raise ValueError("圆与圆弧接近相切，无法可靠分割区域。")
                    circle_cuts[index].add(identity)
                    arc_cuts[arc_index].add(identity)
    for index, arc in enumerate(arcs):
        for other_index in range(index + 1, len(arcs)):
            other = arcs[other_index]
            if arc.center_mm == other.center_mm and arc.radius_mm == other.radius_mm:
                continue
            shared_ids = arc_cuts[index] & arc_cuts[other_index]
            shared = vertices[next(iter(shared_ids))] if len(shared_ids) == 1 else None
            try:
                hits = curve_intersections(arc, other, shared)
            except ValueError as exc:
                raise ValueError("圆弧边界重叠，无法确定封闭区域。") from exc
            for point in hits:
                identity = hit_vertex(point, shared_ids, max(arc.radius_mm, other.radius_mm))
                ax, ay = point[0] - arc.center_mm[0], point[1] - arc.center_mm[1]
                bx, by = point[0] - other.center_mm[0], point[1] - other.center_mm[1]
                cross = ax * by - ay * bx
                if cross == 0:
                    tangent_pairs.setdefault(identity, set()).add(
                        frozenset((("arc", index), ("arc", other_index)))
                    )
                elif abs(cross) <= 32 * math.ulp(arc.radius_mm * other.radius_mm):
                    raise ValueError("圆弧接近相切，无法可靠分割区域。")
                arc_cuts[index].add(identity)
                arc_cuts[other_index].add(identity)

    support_groups: dict[tuple[Point2D, float], tuple[list[int], list[int]]] = {}
    for index, circle in enumerate(circles):
        support_groups.setdefault((circle.center_mm, circle.radius_mm), ([], []))[0].append(index)
    for index, arc in enumerate(arcs):
        support_groups.setdefault((arc.center_mm, arc.radius_mm), ([], []))[1].append(index)
    for (_center, _radius), (circle_indices, arc_indices) in support_groups.items():
        if len(circle_indices) + len(arc_indices) < 2:
            continue
        shared_points = {
            point
            for cuts in (
                *(circle_cuts[index] for index in circle_indices),
                *(arc_cuts[index] for index in arc_indices),
            )
            for point in cuts
        }
        for index in circle_indices:
            circle_cuts[index].update(shared_points)
        for index in arc_indices:
            arc = arcs[index]
            for identity in shared_points:
                point = vertices[identity]
                point_angle = math.degrees(
                    math.atan2(point[1] - arc.center_mm[1], point[0] - arc.center_mm[0])
                )
                delta = (
                    (point_angle - arc.start_angle_deg)
                    if arc.sweep_angle_deg > 0
                    else (arc.start_angle_deg - point_angle)
                ) % 360
                tolerance = 32 * math.ulp(
                    max(360.0, abs(arc.start_angle_deg), abs(arc.sweep_angle_deg))
                )
                if delta <= abs(arc.sweep_angle_deg) + tolerance or 360 - delta <= tolerance:
                    arc_cuts[index].add(identity)

    edges: list[_Edge] = []
    seen_line_edges: set[frozenset[int]] = set()
    for line_index, (line, cuts) in enumerate(zip(lines, line_cuts, strict=True)):
        dx, dy = line.end_mm[0] - line.start_mm[0], line.end_mm[1] - line.start_mm[1]
        axis = 0 if abs(dx) >= abs(dy) else 1
        ordered = sorted(
            cuts,
            key=lambda identity: vertices[identity][axis],
            reverse=line.end_mm[axis] < line.start_mm[axis],
        )
        for a, b in zip(ordered, ordered[1:], strict=False):
            key = frozenset((a, b))
            if a != b and key not in seen_line_edges:
                seen_line_edges.add(key)
                edges.append(_Edge(a, b, 0.0, ("line", line_index)))
    seen_circular_edges: set[tuple[frozenset[int], Point2D, float]] = set()
    for circle_index, (circle, cuts) in enumerate(zip(circles, circle_cuts, strict=True)):

        def angle(identity: int, center: Point2D = circle.center_mm) -> float:
            point = vertices[identity]
            return math.atan2(point[1] - center[1], point[0] - center[0]) % math.tau

        ordered = sorted(cuts, key=angle)
        for a, b in zip(ordered, (*ordered[1:], ordered[0]), strict=True):
            sweep = (angle(b) - angle(a)) % math.tau
            if a != b and sweep:
                seen_circular_edges.add((frozenset((a, b)), circle.center_mm, circle.radius_mm))
                edges.append(_Edge(a, b, math.tan(sweep / 4), ("circle", circle_index)))
    for arc_index, (arc, cuts, (start, end)) in enumerate(
        zip(arcs, arc_cuts, arc_terminals, strict=True)
    ):

        def parameter(
            identity: int, curve: ArcEntity = arc, first: int = start, last: int = end
        ) -> float:
            if identity == first:
                return 0.0
            if identity == last:
                return abs(curve.sweep_angle_deg)
            point = vertices[identity]
            angle = math.degrees(
                math.atan2(point[1] - curve.center_mm[1], point[0] - curve.center_mm[0])
            )
            return (
                (angle - curve.start_angle_deg)
                if curve.sweep_angle_deg > 0
                else (curve.start_angle_deg - angle)
            ) % 360

        ordered = sorted(cuts, key=parameter)
        for a, b in zip(ordered, ordered[1:], strict=False):
            sweep = math.radians(parameter(b) - parameter(a))
            key = (frozenset((a, b)), arc.center_mm, arc.radius_mm)
            if a != b and sweep and key not in seen_circular_edges:
                seen_circular_edges.add(key)
                edges.append(
                    _Edge(
                        a,
                        b,
                        math.copysign(math.tan(sweep / 4), arc.sweep_angle_deg),
                        ("arc", arc_index),
                    )
                )

    adjacency: dict[int, list[tuple[int, bool]]] = {i: [] for i in range(len(vertices))}
    for index, edge in enumerate(edges):
        adjacency[edge.start].append((index, True))
        adjacency[edge.end].append((index, False))
    pending = [identity for identity, outgoing in adjacency.items() if len(outgoing) < 2]
    while pending:
        identity = pending.pop()
        for edge_index, forward in tuple(adjacency[identity]):
            edge = edges[edge_index]
            other = edge.end if forward else edge.start
            adjacency[other].remove((edge_index, not forward))
            if len(adjacency[other]) == 1:
                pending.append(other)
        adjacency[identity].clear()

    def tangent(directed: tuple[int, bool]) -> float:
        edge = edges[directed[0]]
        a, b = (edge.start, edge.end) if directed[1] else (edge.end, edge.start)
        bulge = edge.bulge if directed[1] else -edge.bulge
        if bulge:
            arc = bulge_arc(
                vertices[a],
                vertices[b],
                bulge,
                (
                    lines[0].entity_id
                    if lines
                    else circles[0].entity_id
                    if circles
                    else arcs[0].entity_id
                ),
            )
            return math.radians(arc.start_angle_deg) + math.copysign(math.pi / 2, bulge)
        return math.atan2(vertices[b][1] - vertices[a][1], vertices[b][0] - vertices[a][0])

    def curvature(directed: tuple[int, bool]) -> float:
        edge = edges[directed[0]]
        bulge = edge.bulge if directed[1] else -edge.bulge
        if bulge == 0:
            return 0.0
        chord = math.dist(vertices[edge.start], vertices[edge.end])
        return math.copysign(4 / (chord * (abs(bulge) + 1 / abs(bulge))), bulge)

    for identity, outgoing in adjacency.items():
        outgoing.sort(key=lambda directed: tangent(directed) % math.tau)
        if len(outgoing) > 2:
            angles = tuple(tangent(directed) % math.tau for directed in outgoing)
            gaps = tuple(
                (second - first) % math.tau
                for first, second in zip(angles, (*angles[1:], angles[0]), strict=True)
            )
            if min(gaps) < 1e-10:
                if identity not in tangent_pairs:
                    raise ValueError("边界在交点相切，暂不支持区域分割。")
                split = (max(range(len(gaps)), key=lambda index: gaps[index]) + 1) % len(gaps)
                rotated = outgoing[split:] + outgoing[:split]
                groups: list[list[tuple[int, bool]]] = []
                for directed in rotated:
                    if groups and (tangent(directed) - tangent(groups[-1][-1])) % math.tau < 1e-10:
                        groups[-1].append(directed)
                    else:
                        groups.append([directed])
                for group in groups:
                    for index, first in enumerate(group):
                        for second in group[index + 1 :]:
                            pair = frozenset((edges[first[0]].source, edges[second[0]].source))
                            if pair not in tangent_pairs[identity]:
                                raise ValueError("边界方向过近，无法可靠分割区域。")
                outgoing[:] = [
                    directed for group in groups for directed in sorted(group, key=curvature)
                ]
    visited: set[tuple[int, bool]] = set()
    result: list[LinearRegion] = []
    identity = (
        lines[0].entity_id if lines else circles[0].entity_id if circles else arcs[0].entity_id
    )
    for outgoing in adjacency.values():
        for start in outgoing:
            if start in visited:
                continue
            current = start
            point_ids: list[int] = []
            bulges: list[float] = []
            while current not in visited:
                visited.add(current)
                edge, forward = edges[current[0]], current[1]
                point_ids.append(edge.start if forward else edge.end)
                bulges.append(edge.bulge if forward else -edge.bulge)
                target = edge.end if forward else edge.start
                around = adjacency[target]
                reverse = (current[0], not forward)
                current = around[(around.index(reverse) - 1) % len(around)]
            if current != start or len(point_ids) < 2:
                continue
            for loop_ids, loop_bulges in _simple_loops(point_ids, bulges):
                points = tuple(vertices[index] for index in loop_ids)
                if _signed_area(points, loop_bulges) <= 0:
                    continue
                if len(points) == 2:
                    split = 0 if loop_bulges[0] else 1
                    if not loop_bulges[split]:
                        continue
                    arc = bulge_arc(points[split], points[1 - split], loop_bulges[split], identity)
                    midpoint = arc_point(arc, 0.5)
                    if midpoint in points:
                        raise ValueError("区域过小，无法可靠分割边界。")
                    half_bulge = math.tan(math.atan(loop_bulges[split]) / 2)
                    points = (*points[: split + 1], midpoint, *points[split + 1 :])
                    loop_bulges = (
                        *loop_bulges[:split],
                        half_bulge,
                        half_bulge,
                        *loop_bulges[split + 1 :],
                    )
                polyline = PolylineEntity(identity, points, True, bulges=loop_bulges)
                area, perimeter = polyline_area_perimeter(polyline)
                result.append(LinearRegion(polyline, (), area, perimeter))
    return tuple(result)
