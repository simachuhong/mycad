# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Read-only geometric primitives for interactive drawing measurements."""

from __future__ import annotations

import math
from dataclasses import dataclass

from mycad.core.drawing_measurement import curve_intersections
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Point2D


@dataclass(frozen=True)
class LinePairMeasurement:
    """Shortest finite-segment distance, witness points, and acute line angle."""

    first_point: Point2D
    second_point: Point2D
    distance_mm: float
    angle_deg: float
    right_angle_directions: tuple[Point2D, Point2D] | None = None


@dataclass(frozen=True)
class QuickRadiusMeasurement:
    """A circular curve's radius and the cursor position used for its label."""

    center: Point2D
    cursor: Point2D
    radius_mm: float


@dataclass(frozen=True)
class CurvePairMeasurement:
    """Shortest distance and witness points for supported circular curves."""

    first_point: Point2D
    second_point: Point2D
    distance_mm: float


def _circle_arcs(circle: CircleEntity) -> tuple[ArcEntity, ArcEntity]:
    return (
        ArcEntity(circle.entity_id, circle.center_mm, circle.radius_mm, 0, 180),
        ArcEntity(circle.entity_id, circle.center_mm, circle.radius_mm, 180, 180),
    )


def _radial_point(circle: CircleEntity, toward: Point2D) -> Point2D:
    dx, dy = toward[0] - circle.center_mm[0], toward[1] - circle.center_mm[1]
    distance = math.hypot(dx, dy)
    if not math.isfinite(distance):
        raise ValueError("曲线间距离超出可测量范围。")
    if distance == 0:
        return (circle.center_mm[0] + circle.radius_mm, circle.center_mm[1])
    return (
        circle.center_mm[0] + circle.radius_mm * (dx / distance),
        circle.center_mm[1] + circle.radius_mm * (dy / distance),
    )


def measure_line_circle(
    line: LineEntity, circle: CircleEntity, *, near: Point2D | None = None
) -> CurvePairMeasurement:
    """Measure finite line to full circle, including lines inside the circle."""
    intersections = tuple(
        point for arc in _circle_arcs(circle) for point in curve_intersections(line, arc, None)
    )
    if intersections:
        point = (
            min(intersections, key=lambda item: math.dist(item, near)) if near else intersections[0]
        )
        return CurvePairMeasurement(point, point, 0.0)
    projected = _project_to_segment(circle.center_mm, line)
    candidates = (projected, line.start_mm, line.end_mm)
    witnesses = tuple((point, _radial_point(circle, point)) for point in candidates)
    first, second = min(witnesses, key=lambda pair: math.dist(*pair))
    distance = math.dist(first, second)
    if not math.isfinite(distance):
        raise ValueError("曲线间距离超出可测量范围。")
    return CurvePairMeasurement(first, second, distance)


def measure_circle_pair(
    first: CircleEntity, second: CircleEntity, *, near: Point2D | None = None
) -> CurvePairMeasurement:
    """Measure full circles, including nested and intersecting circles."""
    center_distance = math.dist(first.center_mm, second.center_mm)
    if not math.isfinite(center_distance):
        raise ValueError("曲线间距离超出可测量范围。")
    if center_distance == 0:
        direction = (
            near
            if near is not None and near != first.center_mm
            else (first.center_mm[0] + 1, first.center_mm[1])
        )
        first_point = _radial_point(first, direction)
        second_point = _radial_point(second, direction)
        return CurvePairMeasurement(first_point, second_point, math.dist(first_point, second_point))
    intersections = tuple(
        point
        for first_arc in _circle_arcs(first)
        for second_arc in _circle_arcs(second)
        for point in curve_intersections(first_arc, second_arc, None)
    )
    if intersections:
        point = (
            min(intersections, key=lambda item: math.dist(item, near)) if near else intersections[0]
        )
        return CurvePairMeasurement(point, point, 0.0)
    dx = (second.center_mm[0] - first.center_mm[0]) / center_distance
    dy = (second.center_mm[1] - first.center_mm[1]) / center_distance
    first_points = tuple(
        (
            first.center_mm[0] + sign * first.radius_mm * dx,
            first.center_mm[1] + sign * first.radius_mm * dy,
        )
        for sign in (-1, 1)
    )
    second_points = tuple(
        (
            second.center_mm[0] + sign * second.radius_mm * dx,
            second.center_mm[1] + sign * second.radius_mm * dy,
        )
        for sign in (-1, 1)
    )
    first_point, second_point = min(
        ((a, b) for a in first_points for b in second_points), key=lambda pair: math.dist(*pair)
    )
    distance = math.dist(first_point, second_point)
    if not math.isfinite(distance):
        raise ValueError("曲线间距离超出可测量范围。")
    return CurvePairMeasurement(first_point, second_point, distance)


def _arc_angle_contains(arc: ArcEntity, angle: float) -> bool:
    relative = (
        (angle - arc.start_angle_deg) % 360
        if arc.sweep_angle_deg > 0
        else (arc.start_angle_deg - angle) % 360
    )
    tolerance = 32 * math.ulp(max(360.0, abs(arc.start_angle_deg), abs(arc.sweep_angle_deg)))
    return relative <= abs(arc.sweep_angle_deg) + tolerance or 360 - relative <= tolerance


def _circular_point(curve: ArcEntity | CircleEntity, angle: float) -> Point2D:
    radians = math.radians(angle)
    return (
        curve.center_mm[0] + curve.radius_mm * math.cos(radians),
        curve.center_mm[1] + curve.radius_mm * math.sin(radians),
    )


def _circular_endpoints(curve: ArcEntity | CircleEntity) -> tuple[Point2D, ...]:
    if isinstance(curve, CircleEntity):
        return ()
    return (
        _circular_point(curve, curve.start_angle_deg),
        _circular_point(curve, curve.start_angle_deg + curve.sweep_angle_deg),
    )


def _closest_circular_point(curve: ArcEntity | CircleEntity, point: Point2D) -> Point2D:
    dx, dy = point[0] - curve.center_mm[0], point[1] - curve.center_mm[1]
    if not math.isfinite(math.hypot(dx, dy)):
        raise ValueError("曲线间距离超出可测量范围。")
    angle = math.degrees(math.atan2(dy, dx))
    if isinstance(curve, CircleEntity) or (
        (dx != 0 or dy != 0) and _arc_angle_contains(curve, angle)
    ):
        return _circular_point(curve, angle)
    return min(_circular_endpoints(curve), key=lambda endpoint: math.dist(endpoint, point))


def _closest_pair(
    candidates: list[tuple[Point2D, Point2D]], near: Point2D | None
) -> CurvePairMeasurement:
    minimum = min(math.dist(*pair) for pair in candidates)
    if not math.isfinite(minimum):
        raise ValueError("曲线间距离超出可测量范围。")
    eligible = [
        pair
        for pair in candidates
        if math.isclose(math.dist(*pair), minimum, rel_tol=1e-12, abs_tol=1e-12)
    ]
    first, second = (
        min(eligible, key=lambda pair: math.dist(pair[0], near) + math.dist(pair[1], near))
        if near is not None
        else eligible[0]
    )
    return CurvePairMeasurement(first, second, math.dist(first, second))


def measure_line_arc(
    line: LineEntity, arc: ArcEntity, *, near: Point2D | None = None
) -> CurvePairMeasurement:
    """Measure a finite line and a finite circular arc using analytic candidates."""
    intersections = curve_intersections(line, arc, None)
    if intersections:
        point = (
            min(intersections, key=lambda item: math.dist(item, near))
            if near is not None
            else intersections[0]
        )
        return CurvePairMeasurement(point, point, 0.0)
    candidates = [
        (endpoint, _closest_circular_point(arc, endpoint))
        for endpoint in (line.start_mm, line.end_mm)
    ]
    candidates.extend(
        (_project_to_segment(endpoint, line), endpoint) for endpoint in _circular_endpoints(arc)
    )
    ux, uy, _ = _direction(line)
    normal_angle = math.degrees(math.atan2(ux, -uy))
    for angle in (normal_angle, normal_angle + 180):
        if _arc_angle_contains(arc, angle):
            point = _circular_point(arc, angle)
            candidates.append((_project_to_segment(point, line), point))
    return _closest_pair(candidates, near)


def measure_circular_curves(
    first: ArcEntity | CircleEntity,
    second: ArcEntity | CircleEntity,
    *,
    near: Point2D | None = None,
) -> CurvePairMeasurement:
    """Measure two finite circular curves, including overlapping arcs."""
    if isinstance(first, CircleEntity) and isinstance(second, CircleEntity):
        return measure_circle_pair(first, second, near=near)
    first_arcs = _circle_arcs(first) if isinstance(first, CircleEntity) else (first,)
    second_arcs = _circle_arcs(second) if isinstance(second, CircleEntity) else (second,)
    for a in first_arcs:
        for b in second_arcs:
            try:
                intersections = curve_intersections(a, b, None)
            except ValueError:
                # Overlapping arcs are handled by their endpoints below.
                continue
            if intersections:
                point = (
                    min(intersections, key=lambda item: math.dist(item, near))
                    if near is not None
                    else intersections[0]
                )
                return CurvePairMeasurement(point, point, 0.0)
    candidates = [
        (point, _closest_circular_point(second, point)) for point in _circular_endpoints(first)
    ]
    candidates.extend(
        (_closest_circular_point(first, point), point) for point in _circular_endpoints(second)
    )
    dx = second.center_mm[0] - first.center_mm[0]
    dy = second.center_mm[1] - first.center_mm[1]
    if not math.isfinite(math.hypot(dx, dy)):
        raise ValueError("曲线间距离超出可测量范围。")
    if dx != 0 or dy != 0:
        angle = math.degrees(math.atan2(dy, dx))
        for a in (angle, angle + 180):
            for b in (angle, angle + 180):
                if (isinstance(first, CircleEntity) or _arc_angle_contains(first, a)) and (
                    isinstance(second, CircleEntity) or _arc_angle_contains(second, b)
                ):
                    candidates.append((_circular_point(first, a), _circular_point(second, b)))
    return _closest_pair(candidates, near)


def _direction(line: LineEntity) -> tuple[float, float, float]:
    dx = line.end_mm[0] - line.start_mm[0]
    dy = line.end_mm[1] - line.start_mm[1]
    length = math.hypot(dx, dy)
    if not math.isfinite(length) or length <= 0:
        raise ValueError("线段长度超出可测量范围。")
    return dx / length, dy / length, length


def _project_to_segment(point: Point2D, line: LineEntity) -> Point2D:
    ux, uy, length = _direction(line)
    delta_x = point[0] - line.start_mm[0]
    delta_y = point[1] - line.start_mm[1]
    along = delta_x * ux + delta_y * uy
    if not math.isfinite(along):
        raise ValueError("线段间距离超出可测量范围。")
    along = min(length, max(0.0, along))
    return (line.start_mm[0] + along * ux, line.start_mm[1] + along * uy)


def _intersection_ray(line: LineEntity, point: Point2D, near: Point2D | None) -> Point2D:
    vectors = tuple(
        (endpoint[0] - point[0], endpoint[1] - point[1])
        for endpoint in (line.start_mm, line.end_mm)
        if endpoint != point
    )
    target = (near[0] - point[0], near[1] - point[1]) if near is not None else (0.0, 0.0)
    vector = max(
        vectors,
        key=lambda item: (
            (item[0] * target[0] + item[1] * target[1]) / math.hypot(*item),
            math.hypot(*item),
        ),
    )
    length = math.hypot(*vector)
    return (vector[0] / length, vector[1] / length)


def measure_line_pair(
    first: LineEntity, second: LineEntity, *, near: Point2D | None = None
) -> LinePairMeasurement:
    """Measure the closest points of two finite lines and their acute angle."""
    ux, uy, _ = _direction(first)
    vx, vy, _ = _direction(second)
    angle = math.degrees(math.atan2(abs(ux * vy - uy * vx), abs(ux * vx + uy * vy)))
    try:
        intersections = curve_intersections(first, second, None)
    except ValueError:
        # Collinear overlaps have no unique intersection; endpoint projections
        # below still provide a valid zero-distance witness.
        intersections = ()
    if intersections:
        point = intersections[0]
        directions = (
            (_intersection_ray(first, point, near), _intersection_ray(second, point, near))
            if math.isclose(angle, 90.0, rel_tol=0.0, abs_tol=1e-9)
            else None
        )
        return LinePairMeasurement(point, point, 0.0, angle, directions)
    candidates = [
        (first.start_mm, _project_to_segment(first.start_mm, second)),
        (first.end_mm, _project_to_segment(first.end_mm, second)),
        (_project_to_segment(second.start_mm, first), second.start_mm),
        (_project_to_segment(second.end_mm, first), second.end_mm),
    ]
    if near is not None:
        on_first = _project_to_segment(near, first)
        on_second = _project_to_segment(near, second)
        candidates.extend(
            (
                (on_first, _project_to_segment(on_first, second)),
                (_project_to_segment(on_second, first), on_second),
            )
        )
    closest = min(math.dist(*pair) for pair in candidates)
    eligible = [
        pair
        for pair in candidates
        if math.isclose(math.dist(*pair), closest, rel_tol=1e-12, abs_tol=1e-12)
    ]
    first_point, second_point = (
        min(eligible, key=lambda pair: math.dist(pair[0], near) + math.dist(pair[1], near))
        if near is not None
        else eligible[0]
    )
    distance = math.dist(first_point, second_point)
    if not math.isfinite(distance):
        raise ValueError("线段间距离超出可测量范围。")
    return LinePairMeasurement(first_point, second_point, distance, angle)
