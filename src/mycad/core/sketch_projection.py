# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Affine projections of sketch planes without altering their source geometry."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    Point2D,
    Point3D,
    PolylineEntity,
    RectangleEntity,
    SketchEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_edit import extend_curve_at, trim_curve_at


def _dot(first: Point3D, second: Point3D) -> float:
    return sum(a * b for a, b in zip(first, second, strict=True))


@dataclass(frozen=True, slots=True)
class PlaneProjection:
    """Map source coordinates onto a destination plane along a fixed direction."""

    origin: Point2D
    u_axis: Point2D
    v_axis: Point2D

    def map_point(self, point: Point2D) -> Point2D:
        return (
            self.origin[0] + point[0] * self.u_axis[0] + point[1] * self.v_axis[0],
            self.origin[1] + point[0] * self.u_axis[1] + point[1] * self.v_axis[1],
        )


def plane_projection(
    source: WorkPlaneFrame, target: WorkPlaneFrame, direction: Point3D
) -> PlaneProjection:
    """Project along direction; reject rays parallel to the target plane."""
    if not all(math.isfinite(value) for value in direction):
        raise ValueError("投影方向必须是有限向量。")
    magnitude = math.sqrt(_dot(direction, direction))
    denominator = _dot(direction, target.normal)
    if magnitude == 0 or abs(denominator) <= magnitude * 1e-12:
        raise ValueError("投影方向与目标平面平行或退化。")

    def project_vector(vector: Point3D) -> Point2D:
        factor = _dot(vector, target.normal) / denominator
        projected: Point3D = (
            vector[0] - factor * direction[0],
            vector[1] - factor * direction[1],
            vector[2] - factor * direction[2],
        )
        return (_dot(projected, target.u_axis), _dot(projected, target.v_axis))

    delta: Point3D = (
        source.origin_mm[0] - target.origin_mm[0],
        source.origin_mm[1] - target.origin_mm[1],
        source.origin_mm[2] - target.origin_mm[2],
    )
    return PlaneProjection(
        project_vector(delta), project_vector(source.u_axis), project_vector(source.v_axis)
    )


@dataclass(frozen=True, slots=True)
class ProjectedArc:
    """An exact affine image of a finite circle or circular arc."""

    center: Point2D
    cosine: Point2D
    sine: Point2D
    start_angle_deg: float
    sweep_angle_deg: float


def _angle_in_sweep(angle_deg: float, start_deg: float, sweep_deg: float) -> bool:
    if abs(sweep_deg) >= 360:
        return True
    relative = (angle_deg - start_deg) % 360 if sweep_deg > 0 else (start_deg - angle_deg) % 360
    return relative <= abs(sweep_deg) + 1e-9 or relative >= 360 - 1e-9


def project_circular_arc(
    projection: PlaneProjection,
    center: Point2D,
    radius: float,
    start_angle_deg: float,
    sweep_angle_deg: float,
) -> ProjectedArc:
    """Keep the elliptical image exact, including its original angular parameter."""
    if not all(
        math.isfinite(value) for value in (*center, radius, start_angle_deg, sweep_angle_deg)
    ):
        raise ValueError("投影圆弧参数必须有限。")
    if radius <= 0 or not 0 < abs(sweep_angle_deg) <= 360:
        raise ValueError("投影圆弧半径或角度无效。")
    cosine = (radius * projection.u_axis[0], radius * projection.u_axis[1])
    sine = (radius * projection.v_axis[0], radius * projection.v_axis[1])
    return ProjectedArc(
        projection.map_point(center), cosine, sine, start_angle_deg, sweep_angle_deg
    )


def intersect_projected_arc_with_line(
    arc: ProjectedArc,
    start: Point2D,
    end: Point2D,
    *,
    extend_line: bool = False,
    extend_arc: bool = False,
) -> tuple[Point2D, ...]:
    """Intersect an affine circular arc with a segment or its support line."""
    if not all(math.isfinite(value) for point in (start, end) for value in point):
        raise ValueError("求交线段坐标必须有限。")
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-24:
        raise ValueError("求交线段退化。")
    a = dx * arc.cosine[1] - dy * arc.cosine[0]
    b = dx * arc.sine[1] - dy * arc.sine[0]
    c = dx * (arc.center[1] - start[1]) - dy * (arc.center[0] - start[0])
    amplitude = math.hypot(a, b)
    if amplitude <= 1e-12 * math.sqrt(length_squared) * max(
        math.hypot(*arc.cosine), math.hypot(*arc.sine), 1e-12
    ):
        if abs(c) > 1e-9 * math.sqrt(length_squared):
            return ()
        along_cos = (dx * arc.cosine[0] + dy * arc.cosine[1]) / length_squared
        along_sin = (dx * arc.sine[0] + dy * arc.sine[1]) / length_squared
        center_ratio = (
            (arc.center[0] - start[0]) * dx + (arc.center[1] - start[1]) * dy
        ) / length_squared
        maximum_angle = math.degrees(math.atan2(along_sin, along_cos))
        angles = [arc.start_angle_deg, arc.start_angle_deg + arc.sweep_angle_deg]
        angles.extend(
            angle
            for angle in (maximum_angle, maximum_angle + 180)
            if extend_arc or _angle_in_sweep(angle, arc.start_angle_deg, arc.sweep_angle_deg)
        )
        values = [
            center_ratio
            + along_cos * math.cos(math.radians(angle))
            + along_sin * math.sin(math.radians(angle))
            for angle in angles
        ]
        lower, upper = min(values), max(values)
        if not extend_line:
            lower, upper = max(lower, 0.0), min(upper, 1.0)
        tolerance = 1e-9 / math.sqrt(length_squared)
        if upper < lower - tolerance:
            return ()
        if upper > lower + tolerance:
            raise ValueError("投影圆弧与目标重合，交点不唯一。")
        parameter = (lower + upper) / 2
        return ((start[0] + parameter * dx, start[1] + parameter * dy),)
    ratio = -c / amplitude
    if abs(ratio) > 1 + 1e-12:
        return ()
    offset = math.acos(min(1.0, max(-1.0, ratio)))
    phase = math.atan2(b, a)
    hits: list[tuple[float, Point2D]] = []
    for angle in (phase - offset, phase + offset):
        angle_deg = math.degrees(angle)
        if not extend_arc and not _angle_in_sweep(
            angle_deg, arc.start_angle_deg, arc.sweep_angle_deg
        ):
            continue
        point = (
            arc.center[0] + arc.cosine[0] * math.cos(angle) + arc.sine[0] * math.sin(angle),
            arc.center[1] + arc.cosine[1] * math.cos(angle) + arc.sine[1] * math.sin(angle),
        )
        parameter = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
        if (extend_line or -1e-12 <= parameter <= 1 + 1e-12) and not any(
            math.dist(point, existing) <= 1e-9 for _, existing in hits
        ):
            hits.append((parameter, point))
    hits.sort(key=lambda item: item[0])
    return tuple(point for _, point in hits)


def intersect_spatial_segments(
    first_start: Point3D,
    first_end: Point3D,
    second_start: Point3D,
    second_end: Point3D,
    *,
    extend_first: bool = False,
    extend_second: bool = False,
) -> Point3D | None:
    """Return a unique 3D segment intersection; reject overlapping intervals."""
    if not all(
        math.isfinite(value)
        for point in (first_start, first_end, second_start, second_end)
        for value in point
    ):
        raise ValueError("空间坐标必须有限。")

    def subtract(left: Point3D, right: Point3D) -> Point3D:
        return (left[0] - right[0], left[1] - right[1], left[2] - right[2])

    first = subtract(first_end, first_start)
    second = subtract(second_end, second_start)
    separation = subtract(first_start, second_start)
    aa, bb, cc = _dot(first, first), _dot(first, second), _dot(second, second)
    if aa <= 1e-24 or cc <= 1e-24:
        raise ValueError("空间线段退化。")
    dd, ee = _dot(first, separation), _dot(second, separation)
    determinant = aa * cc - bb * bb
    if determinant <= 1e-24 * aa * cc:
        start_parameter = -dd / aa
        perpendicular: Point3D = (
            separation[0] + start_parameter * first[0],
            separation[1] + start_parameter * first[1],
            separation[2] + start_parameter * first[2],
        )
        if math.sqrt(_dot(perpendicular, perpendicular)) > 1e-9:
            return None
        if extend_first or extend_second:
            raise ValueError("空间线段重合，交点不唯一。")
        end_parameter = start_parameter + bb / aa
        lower, upper = (
            max(0.0, min(start_parameter, end_parameter)),
            min(1.0, max(start_parameter, end_parameter)),
        )
        parameter_tolerance = 1e-9 / math.sqrt(aa)
        if upper < lower - parameter_tolerance:
            return None
        if upper > lower + parameter_tolerance:
            raise ValueError("空间线段重合，交点不唯一。")
        parameter = (lower + upper) / 2
        return (
            first_start[0] + parameter * first[0],
            first_start[1] + parameter * first[1],
            first_start[2] + parameter * first[2],
        )
    first_parameter = (bb * ee - cc * dd) / determinant
    second_parameter = (aa * ee - bb * dd) / determinant
    if (not extend_first and not -1e-12 <= first_parameter <= 1 + 1e-12) or (
        not extend_second and not -1e-12 <= second_parameter <= 1 + 1e-12
    ):
        return None
    first_point: Point3D = (
        first_start[0] + first_parameter * first[0],
        first_start[1] + first_parameter * first[1],
        first_start[2] + first_parameter * first[2],
    )
    second_point: Point3D = (
        second_start[0] + second_parameter * second[0],
        second_start[1] + second_parameter * second[1],
        second_start[2] + second_parameter * second[2],
    )
    return first_point if math.dist(first_point, second_point) <= 1e-9 else None


def intersect_spatial_line_arc(
    start: Point3D,
    end: Point3D,
    arc_frame: WorkPlaneFrame,
    center: Point2D,
    radius: float,
    start_angle_deg: float,
    sweep_angle_deg: float,
    *,
    extend_line: bool = False,
    extend_arc: bool = False,
) -> tuple[Point3D, ...]:
    """Find real 3D line/arc intersections without projecting either source."""
    if not all(math.isfinite(value) for point in (start, end) for value in point):
        raise ValueError("空间坐标必须有限。")
    identity = PlaneProjection((0, 0), (1, 0), (0, 1))
    arc = project_circular_arc(identity, center, radius, start_angle_deg, sweep_angle_deg)
    direction: Point3D = (end[0] - start[0], end[1] - start[1], end[2] - start[2])
    if _dot(direction, direction) <= 1e-24:
        raise ValueError("空间线段退化。")
    relative: Point3D = (
        start[0] - arc_frame.origin_mm[0],
        start[1] - arc_frame.origin_mm[1],
        start[2] - arc_frame.origin_mm[2],
    )
    height = _dot(relative, arc_frame.normal)
    vertical = _dot(direction, arc_frame.normal)
    if abs(vertical) <= 1e-12 * math.sqrt(_dot(direction, direction)):
        if abs(height) > 1e-9:
            return ()
        points = intersect_projected_arc_with_line(
            arc,
            arc_frame.world_to_local(start),
            arc_frame.world_to_local(end),
            extend_line=extend_line,
            extend_arc=extend_arc,
        )
        return tuple(arc_frame.local_to_world(point) for point in points)
    parameter = -height / vertical
    if not extend_line and not -1e-12 <= parameter <= 1 + 1e-12:
        return ()
    point: Point3D = (
        start[0] + parameter * direction[0],
        start[1] + parameter * direction[1],
        start[2] + parameter * direction[2],
    )
    local = arc_frame.world_to_local(point)
    dx, dy = local[0] - center[0], local[1] - center[1]
    if abs(math.hypot(dx, dy) - radius) > 1e-9:
        return ()
    angle = math.degrees(math.atan2(dy, dx))
    return (
        (point,) if extend_arc or _angle_in_sweep(angle, start_angle_deg, sweep_angle_deg) else ()
    )


def line_boundary_intersections(
    target: LineEntity,
    target_frame: WorkPlaneFrame,
    boundary: LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity,
    boundary_frame: WorkPlaneFrame,
    direction: Point3D | None,
    *,
    extend_target: bool = False,
    extend_boundary: bool = False,
) -> tuple[Point2D, ...]:
    """Find target-line intersections with a 3D boundary or its planar projection."""
    if isinstance(boundary, PolylineEntity | RectangleEntity):
        if isinstance(boundary, RectangleEntity):
            first, opposite = boundary.first_corner_mm, boundary.opposite_corner_mm
            vertices = (first, (opposite[0], first[1]), opposite, (first[0], opposite[1]))
            bulges, closed = (0.0,) * 4, True
        else:
            vertices, closed = boundary.points_mm, boundary.closed
            count = len(vertices) if closed else len(vertices) - 1
            bulges = boundary.bulges or (0.0,) * count
        segments = polyline_curve_segments(vertices, bulges, closed, boundary.entity_id)
        hits: list[Point2D] = []
        for segment in segments:
            for hit in line_boundary_intersections(
                target,
                target_frame,
                segment,
                boundary_frame,
                direction,
                extend_target=extend_target,
                extend_boundary=extend_boundary,
            ):
                if all(math.dist(hit, existing) > 1e-9 for existing in hits):
                    hits.append(hit)
        dx = target.end_mm[0] - target.start_mm[0]
        dy = target.end_mm[1] - target.start_mm[1]
        hits.sort(
            key=lambda point: (
                (point[0] - target.start_mm[0]) * dx + (point[1] - target.start_mm[1]) * dy
            )
        )
        return tuple(hits)
    if direction is None:
        first, last = (
            target_frame.local_to_world(target.start_mm),
            target_frame.local_to_world(target.end_mm),
        )
        if isinstance(boundary, LineEntity):
            hit = intersect_spatial_segments(
                first,
                last,
                boundary_frame.local_to_world(boundary.start_mm),
                boundary_frame.local_to_world(boundary.end_mm),
                extend_first=extend_target,
                extend_second=extend_boundary,
            )
            return () if hit is None else (target_frame.world_to_local(hit),)
        start_angle = boundary.start_angle_deg if isinstance(boundary, ArcEntity) else 0.0
        sweep = boundary.sweep_angle_deg if isinstance(boundary, ArcEntity) else 360.0
        points = intersect_spatial_line_arc(
            first,
            last,
            boundary_frame,
            boundary.center_mm,
            boundary.radius_mm,
            start_angle,
            sweep,
            extend_line=extend_target,
            extend_arc=extend_boundary,
        )
        return tuple(target_frame.world_to_local(point) for point in points)
    projection = plane_projection(boundary_frame, target_frame, direction)
    if not isinstance(boundary, LineEntity):
        start_angle = boundary.start_angle_deg if isinstance(boundary, ArcEntity) else 0.0
        sweep = boundary.sweep_angle_deg if isinstance(boundary, ArcEntity) else 360.0
        arc = project_circular_arc(
            projection, boundary.center_mm, boundary.radius_mm, start_angle, sweep
        )
        return intersect_projected_arc_with_line(
            arc,
            target.start_mm,
            target.end_mm,
            extend_line=extend_target,
            extend_arc=extend_boundary,
        )
    first = projection.map_point(boundary.start_mm)
    last = projection.map_point(boundary.end_mm)
    x, y = target.end_mm[0] - target.start_mm[0], target.end_mm[1] - target.start_mm[1]
    u, v = last[0] - first[0], last[1] - first[1]
    first_length, second_length = math.hypot(x, y), math.hypot(u, v)
    if first_length <= 1e-12:
        raise ValueError("目标线段退化。")
    dx, dy = first[0] - target.start_mm[0], first[1] - target.start_mm[1]
    if second_length <= 1e-12:
        ratio = (dx * x + dy * y) / (first_length * first_length)
        if abs(dx * y - dy * x) > 1e-9 * first_length or (
            not extend_target and not -1e-12 <= ratio <= 1 + 1e-12
        ):
            return ()
        return ((target.start_mm[0] + ratio * x, target.start_mm[1] + ratio * y),)
    determinant = x * v - y * u
    if abs(determinant) <= 1e-12 * first_length * second_length:
        if abs(dx * y - dy * x) > 1e-9 * first_length:
            return ()
        if extend_target or extend_boundary:
            raise ValueError("投影边界与目标重合，交点不唯一。")
        first_parameter = (dx * x + dy * y) / (first_length * first_length)
        last_parameter = first_parameter + (u * x + v * y) / (first_length * first_length)
        lower = max(0.0, min(first_parameter, last_parameter))
        upper = min(1.0, max(first_parameter, last_parameter))
        tolerance = 1e-9 / first_length
        if upper < lower - tolerance:
            return ()
        if upper > lower + tolerance:
            raise ValueError("投影边界与目标重合，交点不唯一。")
        t = (lower + upper) / 2
        return ((target.start_mm[0] + t * x, target.start_mm[1] + t * y),)
    t, s = (dx * v - dy * u) / determinant, (dx * y - dy * x) / determinant
    if (not extend_target and not -1e-12 <= t <= 1 + 1e-12) or (
        not extend_boundary and not -1e-12 <= s <= 1 + 1e-12
    ):
        return ()
    return ((target.start_mm[0] + t * x, target.start_mm[1] + t * y),)


@dataclass(frozen=True, slots=True)
class SpatialBoundary:
    """Read-only source identity and geometry for cross-plane operations."""

    sketch_id: str
    frame: WorkPlaneFrame
    entity: LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity


def edit_curve_with_spatial_boundaries(
    entities: tuple[SketchEntity, ...],
    target_id: str,
    point: Point2D,
    target_frame: WorkPlaneFrame,
    boundaries: tuple[SpatialBoundary, ...],
    direction: Point3D | None,
    *,
    operation: Literal["trim", "extend"],
    hit_tolerance_mm: float,
    extend_boundaries: bool = False,
    allow_endpoint_intersections: bool = False,
) -> tuple[SketchEntity, ...]:
    """Edit a local line or circular curve using immutable external boundaries."""
    if operation not in ("trim", "extend"):
        raise ValueError("未知的空间边界编辑操作。")
    matches = tuple(entity for entity in entities if entity.entity_id == target_id)
    if len(matches) != 1 or not isinstance(
        matches[0], LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity
    ):
        raise ValueError("空间边界编辑需要唯一的可修剪曲线目标。")
    ids = [entity.entity_id for entity in entities]
    ids.extend(boundary.entity.entity_id for boundary in boundaries)
    if len(ids) != len(set(ids)):
        raise ValueError("空间边界或目标的图元身份不唯一。")
    target = matches[0]
    if operation == "extend" and isinstance(target, CircleEntity):
        raise ValueError("完整圆没有可延伸端点。")
    if isinstance(target, PolylineEntity | RectangleEntity):
        if isinstance(target, RectangleEntity):
            first, opposite = target.first_corner_mm, target.opposite_corner_mm
            vertices = (first, (opposite[0], first[1]), opposite, (first[0], opposite[1]))
            bulges, closed = (0.0,) * 4, True
        else:
            vertices, closed = target.points_mm, target.closed
            count = len(vertices) if closed else len(vertices) - 1
            bulges = target.bulges or (0.0,) * count
        if operation == "extend" and closed:
            raise ValueError("闭合路径没有可延伸端点。")
        segments = polyline_curve_segments(
            vertices,
            bulges,
            closed,
            target.entity_id,
        )
        if operation == "extend":
            segments = (
                segments[0]
                if math.dist(point, vertices[0]) <= math.dist(point, vertices[-1])
                else segments[-1],
            )
    else:
        segments = (target,)
    points: list[Point2D] = []
    for boundary in boundaries:
        if boundary.entity.construction:
            continue
        for segment in segments:
            if isinstance(segment, LineEntity):
                hits = line_boundary_intersections(
                    segment,
                    target_frame,
                    boundary.entity,
                    boundary.frame,
                    direction,
                    extend_target=operation == "extend",
                    extend_boundary=extend_boundaries,
                )
            else:
                hits = circular_boundary_intersections(
                    segment,
                    target_frame,
                    boundary.entity,
                    boundary.frame,
                    direction,
                    extend_target=operation == "extend",
                    extend_boundary=extend_boundaries,
                )
            points.extend(hits)
    if operation == "trim":
        return trim_curve_at(
            entities,
            point,
            hit_tolerance_mm=hit_tolerance_mm,
            target_entity_id=target_id,
            extend_boundaries=extend_boundaries,
            allow_endpoint_intersections=allow_endpoint_intersections,
            extra_intersections_mm=tuple(points),
        )
    return extend_curve_at(
        entities,
        point,
        hit_tolerance_mm=hit_tolerance_mm,
        target_entity_id=target_id,
        extend_boundaries=extend_boundaries,
        extra_intersections_mm=tuple(points),
    )


def _real_polynomial_roots(coefficients: tuple[float, ...]) -> tuple[float, ...]:
    """Isolate real roots through derivative critical points, including repeated roots."""
    scale = max(abs(value) for value in coefficients)
    if scale == 0:
        raise ValueError("投影曲线重合，交点不唯一。")
    values = [value / scale for value in coefficients]
    while len(values) > 1 and abs(values[-1]) <= 1e-14:
        values.pop()
    degree = len(values) - 1
    if degree == 0:
        return ()
    if degree == 1:
        return (-values[0] / values[1],)
    derivative = tuple(index * values[index] for index in range(1, len(values)))
    critical = _real_polynomial_roots(derivative)
    bound = min(1e12, 1 + max(abs(value / values[-1]) for value in values[:-1]))
    partitions = (-bound, *(root for root in critical if -bound < root < bound), bound)

    def evaluate(x: float) -> float:
        result = 0.0
        for value in reversed(values):
            result = result * x + value
        return result

    roots: list[float] = []
    for candidate in critical:
        if not -bound <= candidate <= bound:
            continue
        magnitude = max(1.0, abs(candidate))
        error_scale = sum(abs(value) * magnitude**index for index, value in enumerate(values))
        if abs(evaluate(candidate)) <= 1e-11 * error_scale:
            roots.append(candidate)
    for lower, upper in zip(partitions, partitions[1:], strict=False):
        low_value, high_value = evaluate(lower), evaluate(upper)
        if low_value == 0:
            roots.append(lower)
        if high_value == 0:
            roots.append(upper)
        if low_value * high_value >= 0:
            continue
        for _ in range(100):
            middle = (lower + upper) / 2
            middle_value = evaluate(middle)
            if low_value * middle_value <= 0:
                upper = middle
            else:
                lower, low_value = middle, middle_value
        roots.append((lower + upper) / 2)
    roots.sort()
    unique: list[float] = []
    for root in roots:
        if not unique or abs(root - unique[-1]) > 1e-8 * max(1.0, abs(root)):
            unique.append(root)
    return tuple(unique)


def intersect_projected_arc_with_circle(
    arc: ProjectedArc,
    center: Point2D,
    radius: float,
    *,
    start_angle_deg: float = 0.0,
    sweep_angle_deg: float = 360.0,
    extend_arc: bool = False,
    extend_target: bool = False,
) -> tuple[Point2D, ...]:
    """Intersect an affine circular arc with a circle or finite circular target arc."""
    if not all(
        math.isfinite(value) for value in (*center, radius, start_angle_deg, sweep_angle_deg)
    ):
        raise ValueError("圆形目标参数必须有限。")
    if radius <= 0 or not 0 < abs(sweep_angle_deg) <= 360:
        raise ValueError("圆形目标半径或角度无效。")
    dx, dy = arc.center[0] - center[0], arc.center[1] - center[1]
    ax, ay = arc.cosine
    bx, by = arc.sine
    constant = dx * dx + dy * dy - radius * radius
    cosine, sine = 2 * (dx * ax + dy * ay), 2 * (dx * bx + dy * by)
    cosine_squared, sine_squared = ax * ax + ay * ay, bx * bx + by * by
    mixed = 2 * (ax * bx + ay * by)
    coefficients = (
        constant + cosine + cosine_squared,
        2 * sine + 2 * mixed,
        2 * constant - 2 * cosine_squared + 4 * sine_squared,
        2 * sine - 2 * mixed,
        constant - cosine + cosine_squared,
    )
    geometric_scale = max(radius * radius, dx * dx + dy * dy, cosine_squared, sine_squared, 1e-300)
    if max(abs(value) for value in coefficients) <= 1e-12 * geometric_scale:
        raise ValueError("投影曲线重合，交点不唯一。")
    angles = [2 * math.atan(root) for root in _real_polynomial_roots(coefficients)]
    angles.append(math.pi)
    hits: list[tuple[float, Point2D]] = []
    for angle in angles:
        source_angle = math.degrees(angle)
        if not extend_arc and not _angle_in_sweep(
            source_angle, arc.start_angle_deg, arc.sweep_angle_deg
        ):
            continue
        point = (
            arc.center[0] + ax * math.cos(angle) + bx * math.sin(angle),
            arc.center[1] + ay * math.cos(angle) + by * math.sin(angle),
        )
        if abs(math.dist(point, center) - radius) > 1e-8 * max(1.0, radius):
            continue
        target_angle = math.degrees(math.atan2(point[1] - center[1], point[0] - center[0]))
        if not extend_target and not _angle_in_sweep(
            target_angle, start_angle_deg, sweep_angle_deg
        ):
            continue
        if any(math.dist(point, existing) <= 1e-8 for _, existing in hits):
            continue
        parameter = (
            (source_angle - arc.start_angle_deg) % 360
            if arc.sweep_angle_deg > 0
            else (arc.start_angle_deg - source_angle) % 360
        )
        hits.append((parameter, point))
    hits.sort(key=lambda item: item[0])
    return tuple(point for _, point in hits)


def circular_boundary_intersections(
    target: CircleEntity | ArcEntity,
    target_frame: WorkPlaneFrame,
    boundary: LineEntity | CircleEntity | ArcEntity | PolylineEntity | RectangleEntity,
    boundary_frame: WorkPlaneFrame,
    direction: Point3D | None,
    *,
    extend_target: bool = False,
    extend_boundary: bool = False,
) -> tuple[Point2D, ...]:
    """Find intersections on a local circular target against a 3D source boundary."""
    target_start = target.start_angle_deg if isinstance(target, ArcEntity) else 0.0
    target_sweep = target.sweep_angle_deg if isinstance(target, ArcEntity) else 360.0
    if isinstance(boundary, PolylineEntity | RectangleEntity):
        if isinstance(boundary, RectangleEntity):
            first, opposite = boundary.first_corner_mm, boundary.opposite_corner_mm
            vertices = (first, (opposite[0], first[1]), opposite, (first[0], opposite[1]))
            bulges, closed = (0.0,) * 4, True
        else:
            vertices, closed = boundary.points_mm, boundary.closed
            count = len(vertices) if closed else len(vertices) - 1
            bulges = boundary.bulges or (0.0,) * count
        segments = polyline_curve_segments(vertices, bulges, closed, boundary.entity_id)
        gathered = (
            point
            for segment in segments
            for point in circular_boundary_intersections(
                target,
                target_frame,
                segment,
                boundary_frame,
                direction,
                extend_target=extend_target,
                extend_boundary=extend_boundary,
            )
        )
        hits: list[Point2D] = []
        for point in gathered:
            if all(math.dist(point, existing) > 1e-9 for existing in hits):
                hits.append(point)
        return tuple(hits)
    if isinstance(boundary, LineEntity):
        if direction is None:
            points = intersect_spatial_line_arc(
                boundary_frame.local_to_world(boundary.start_mm),
                boundary_frame.local_to_world(boundary.end_mm),
                target_frame,
                target.center_mm,
                target.radius_mm,
                target_start,
                target_sweep,
                extend_line=extend_boundary,
                extend_arc=extend_target,
            )
            return tuple(target_frame.world_to_local(point) for point in points)
        projection = plane_projection(boundary_frame, target_frame, direction)
        first, last = projection.map_point(boundary.start_mm), projection.map_point(boundary.end_mm)
        if math.dist(first, last) <= 1e-12:
            if abs(math.dist(first, target.center_mm) - target.radius_mm) > 1e-9:
                return ()
            angle = math.degrees(
                math.atan2(first[1] - target.center_mm[1], first[0] - target.center_mm[0])
            )
            return (
                (first,)
                if extend_target or _angle_in_sweep(angle, target_start, target_sweep)
                else ()
            )
        target_arc = project_circular_arc(
            PlaneProjection((0, 0), (1, 0), (0, 1)),
            target.center_mm,
            target.radius_mm,
            target_start,
            target_sweep,
        )
        return intersect_projected_arc_with_line(
            target_arc, first, last, extend_line=extend_boundary, extend_arc=extend_target
        )
    source_start = boundary.start_angle_deg if isinstance(boundary, ArcEntity) else 0.0
    source_sweep = boundary.sweep_angle_deg if isinstance(boundary, ArcEntity) else 360.0
    if direction is not None:
        projection = plane_projection(boundary_frame, target_frame, direction)
        source_arc = project_circular_arc(
            projection, boundary.center_mm, boundary.radius_mm, source_start, source_sweep
        )
        return intersect_projected_arc_with_circle(
            source_arc,
            target.center_mm,
            target.radius_mm,
            start_angle_deg=target_start,
            sweep_angle_deg=target_sweep,
            extend_arc=extend_boundary,
            extend_target=extend_target,
        )
    first_normal, second_normal = target_frame.normal, boundary_frame.normal
    cross: Point3D = (
        first_normal[1] * second_normal[2] - first_normal[2] * second_normal[1],
        first_normal[2] * second_normal[0] - first_normal[0] * second_normal[2],
        first_normal[0] * second_normal[1] - first_normal[1] * second_normal[0],
    )
    cross_squared = _dot(cross, cross)
    if cross_squared <= 1e-24:
        delta: Point3D = (
            boundary_frame.origin_mm[0] - target_frame.origin_mm[0],
            boundary_frame.origin_mm[1] - target_frame.origin_mm[1],
            boundary_frame.origin_mm[2] - target_frame.origin_mm[2],
        )
        if abs(_dot(delta, first_normal)) > 1e-9:
            return ()
        return circular_boundary_intersections(
            target,
            target_frame,
            boundary,
            boundary_frame,
            first_normal,
            extend_target=extend_target,
            extend_boundary=extend_boundary,
        )
    d1, d2 = (
        _dot(first_normal, target_frame.origin_mm),
        _dot(second_normal, boundary_frame.origin_mm),
    )
    p: Point3D = (
        d1 * second_normal[0] - d2 * first_normal[0],
        d1 * second_normal[1] - d2 * first_normal[1],
        d1 * second_normal[2] - d2 * first_normal[2],
    )
    origin: Point3D = (
        (p[1] * cross[2] - p[2] * cross[1]) / cross_squared,
        (p[2] * cross[0] - p[0] * cross[2]) / cross_squared,
        (p[0] * cross[1] - p[1] * cross[0]) / cross_squared,
    )
    endpoint: Point3D = (origin[0] + cross[0], origin[1] + cross[1], origin[2] + cross[2])
    points = intersect_spatial_line_arc(
        origin,
        endpoint,
        boundary_frame,
        boundary.center_mm,
        boundary.radius_mm,
        source_start,
        source_sweep,
        extend_line=True,
        extend_arc=extend_boundary,
    )
    result: list[Point2D] = []
    for point in points:
        local = target_frame.world_to_local(point)
        if abs(math.dist(local, target.center_mm) - target.radius_mm) > 1e-9:
            continue
        angle = math.degrees(
            math.atan2(local[1] - target.center_mm[1], local[0] - target.center_mm[0])
        )
        if extend_target or _angle_in_sweep(angle, target_start, target_sweep):
            result.append(local)
    return tuple(result)


def projected_boundary_in_box(
    boundary: SpatialBoundary,
    target_frame: WorkPlaneFrame,
    first: Point2D,
    second: Point2D,
    *,
    crossing: bool,
) -> bool:
    """Test an exact projected boundary against a 2D selection rectangle."""
    left, right = sorted((first[0], second[0]))
    bottom, top = sorted((first[1], second[1]))
    source = boundary.entity
    if isinstance(source, RectangleEntity):
        a, c = source.first_corner_mm, source.opposite_corner_mm
        vertices = (a, (c[0], a[1]), c, (a[0], c[1]))
        segments = polyline_curve_segments(vertices, (0.0,) * 4, True, source.entity_id)
    elif isinstance(source, PolylineEntity):
        count = len(source.points_mm) if source.closed else len(source.points_mm) - 1
        segments = polyline_curve_segments(
            source.points_mm, source.bulges or (0.0,) * count, source.closed, source.entity_id
        )
    else:
        segments = (source,)
    projection = plane_projection(boundary.frame, target_frame, target_frame.normal)
    extrema: list[Point2D] = []
    for segment in segments:
        if isinstance(segment, LineEntity):
            extrema.extend(
                (projection.map_point(segment.start_mm), projection.map_point(segment.end_mm))
            )
            continue
        start_angle = segment.start_angle_deg if isinstance(segment, ArcEntity) else 0.0
        sweep = segment.sweep_angle_deg if isinstance(segment, ArcEntity) else 360.0
        arc = project_circular_arc(
            projection, segment.center_mm, segment.radius_mm, start_angle, sweep
        )
        angles = [start_angle, start_angle + sweep]
        for index in (0, 1):
            maximum = math.degrees(math.atan2(arc.sine[index], arc.cosine[index]))
            angles.extend(
                angle
                for angle in (maximum, maximum + 180)
                if _angle_in_sweep(angle, start_angle, sweep)
            )
        extrema.extend(
            (
                arc.center[0]
                + arc.cosine[0] * math.cos(math.radians(angle))
                + arc.sine[0] * math.sin(math.radians(angle)),
                arc.center[1]
                + arc.cosine[1] * math.cos(math.radians(angle))
                + arc.sine[1] * math.sin(math.radians(angle)),
            )
            for angle in angles
        )
    inside = tuple(
        left - 1e-9 <= point[0] <= right + 1e-9 and bottom - 1e-9 <= point[1] <= top + 1e-9
        for point in extrema
    )
    if not crossing:
        return all(inside)
    if any(inside):
        return True
    corners = ((left, bottom), (right, bottom), (right, top), (left, top))
    for index, start in enumerate(corners):
        end = corners[(index + 1) % 4]
        if math.dist(start, end) <= 1e-12:
            continue
        edge = LineEntity(source.entity_id, start, end)
        try:
            if line_boundary_intersections(
                edge, target_frame, source, boundary.frame, target_frame.normal
            ):
                return True
        except ValueError as exc:
            if "重合" in str(exc):
                return True
            raise
    return False
