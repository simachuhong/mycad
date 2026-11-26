# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Resolve a picked side to the sketch offset algorithm's signed distance."""

from __future__ import annotations

import math
from collections.abc import Callable

from mycad.core.fillet_curves import contact_on_curve
from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    EllipseEntity,
    LineEntity,
    Point2D,
    PolylineEntity,
    RectangleEntity,
    SketchEntity,
    SplineEntity,
)
from mycad.core.sketch_edit import offset_entities

type ClosedOffset = Callable[[PolylineEntity, float, int], tuple[PolylineEntity, ...]]
type SplineOffset = Callable[[SplineEntity, float], tuple[SplineEntity, ...]]
type SplinePathOffset = Callable[[tuple[SplineEntity, ...], float], tuple[SplineEntity, ...]]
type EllipseOffset = Callable[[EllipseEntity, float], tuple[SplineEntity, ...]]


def spline_path_side(pieces: tuple[SplineEntity, ...], point: Point2D) -> float:
    """Return the oriented normal distance to the closest spline piece."""
    candidates = sorted((_spline_projection(piece, point) for piece in pieces), key=lambda x: x[1])
    if not candidates:
        raise ValueError("样条路径为空。")
    side, separation = candidates[0]
    if any(
        abs(other_separation - separation) <= 1e-8 and side * other_side < -1e-12
        for other_side, other_separation in candidates[1:]
    ):
        raise ValueError("侧点靠近样条路径多个方向，请重新选择。")
    if abs(side) <= 1e-9:
        raise ValueError("侧点位于对象上，请重新选择偏移侧。")
    return side


def spline_path_separation(pieces: tuple[SplineEntity, ...], point: Point2D) -> float:
    """Measure distance to the finite pieces of an offset path."""
    if not pieces:
        raise ValueError("样条路径为空。")
    return min(_spline_projection(piece, point)[1] for piece in pieces)


def offset_with_backend(
    entities: tuple[SketchEntity, ...],
    selected_ids: tuple[str, ...],
    distance: float,
    *,
    gap_type: int = 0,
    closed_offset: ClosedOffset | None = None,
    spline_offset: SplineOffset | None = None,
    ellipse_offset: EllipseOffset | None = None,
) -> tuple[SketchEntity, ...]:
    """Use exact existing paths first, falling back to the geometry service when needed."""
    try:
        return offset_entities(entities, selected_ids, distance, gap_type=gap_type)
    except ValueError:
        if closed_offset is None and spline_offset is None and ellipse_offset is None:
            raise
    if not selected_ids:
        raise ValueError("请选择要偏置的对象。")
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("选择的图元身份不唯一。")
    identities = [entity.entity_id for entity in entities]
    if len(set(identities)) != len(identities):
        raise ValueError("草图中存在重复的元素身份，无法安全编辑。")
    matches = [entity for entity in entities if entity.entity_id in selected_ids]
    if len(matches) != len(selected_ids):
        raise ValueError("选择的图元不存在或身份不唯一。")
    additions: list[SketchEntity] = []
    for entity in matches:
        try:
            additions.extend(
                offset_entities((entity,), (entity.entity_id,), distance, gap_type=gap_type)[1:]
            )
        except ValueError:
            if isinstance(entity, PolylineEntity) and closed_offset is not None:
                additions.extend(closed_offset(entity, distance, gap_type))
            elif isinstance(entity, SplineEntity) and spline_offset is not None:
                additions.extend(spline_offset(entity, distance))
            elif isinstance(entity, EllipseEntity) and ellipse_offset is not None:
                additions.extend(ellipse_offset(entity, distance))
            else:
                raise
    return (*entities, *additions)


def _curved_path_side(entity: PolylineEntity, point: Point2D) -> tuple[float, bool]:
    candidates: list[tuple[float, float, bool]] = []
    for segment in polyline_curve_segments(
        entity.points_mm,
        entity.bulges
        or (0.0,) * (len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1),
        entity.closed,
        entity.entity_id,
    ):
        if isinstance(segment, LineEntity):
            dx = segment.end_mm[0] - segment.start_mm[0]
            dy = segment.end_mm[1] - segment.start_mm[1]
            length = math.hypot(dx, dy)
            raw = (
                (point[0] - segment.start_mm[0]) * dx + (point[1] - segment.start_mm[1]) * dy
            ) / length**2
            ratio = min(1.0, max(0.0, raw))
            nearest = (segment.start_mm[0] + ratio * dx, segment.start_mm[1] + ratio * dy)
            side = (
                dx * (point[1] - segment.start_mm[1]) - dy * (point[0] - segment.start_mm[0])
            ) / length
            candidates.append((math.dist(point, nearest), side, -1e-9 <= raw <= 1 + 1e-9))
        else:
            radius = math.dist(point, segment.center_mm)
            in_arc = radius > 1e-9 and contact_on_curve(segment, point)
            side = (radius - segment.radius_mm) * -math.copysign(1.0, segment.sweep_angle_deg)
            if in_arc:
                separation = abs(radius - segment.radius_mm)
            else:
                ends = tuple(
                    (
                        segment.center_mm[0] + segment.radius_mm * math.cos(math.radians(a)),
                        segment.center_mm[1] + segment.radius_mm * math.sin(math.radians(a)),
                    )
                    for a in (
                        segment.start_angle_deg,
                        segment.start_angle_deg + segment.sweep_angle_deg,
                    )
                )
                separation = min(math.dist(point, end) for end in ends)
            candidates.append((separation, side, in_arc))
    candidates.sort(key=lambda value: value[0])
    if len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) <= 1e-9:
        raise ValueError("侧点靠近多个路径段，请重新选择。")
    return candidates[0][1], candidates[0][2]


def _point_on_path(entity: PolylineEntity, point: Point2D) -> bool:
    segments = polyline_curve_segments(
        entity.points_mm,
        entity.bulges
        or (0.0,) * (len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1),
        entity.closed,
        entity.entity_id,
    )
    for segment in segments:
        if isinstance(segment, ArcEntity):
            if abs(
                math.dist(point, segment.center_mm) - segment.radius_mm
            ) <= 1e-8 and contact_on_curve(segment, point):
                return True
        else:
            dx = segment.end_mm[0] - segment.start_mm[0]
            dy = segment.end_mm[1] - segment.start_mm[1]
            length = math.hypot(dx, dy)
            along = (
                (point[0] - segment.start_mm[0]) * dx + (point[1] - segment.start_mm[1]) * dy
            ) / length
            cross = (
                abs(dx * (point[1] - segment.start_mm[1]) - dy * (point[0] - segment.start_mm[0]))
                / length
            )
            if -1e-9 <= along <= length + 1e-9 and cross <= 1e-8:
                return True
    return False


def _corner_through_distance(
    entity: PolylineEntity | RectangleEntity,
    point: Point2D,
    gap_type: int,
    closed_offset: ClosedOffset | None,
) -> float | None:
    if isinstance(entity, RectangleEntity):
        x1, y1 = entity.first_corner_mm
        x2, y2 = entity.opposite_corner_mm
        path = PolylineEntity(entity.entity_id, ((x1, y1), (x2, y1), (x2, y2), (x1, y2)), True)
    else:
        path = entity
    segments = polyline_curve_segments(
        path.points_mm,
        path.bulges or (0.0,) * (len(path.points_mm) if path.closed else len(path.points_mm) - 1),
        path.closed,
        path.entity_id,
    )

    def normal(segment: LineEntity | ArcEntity, *, end: bool) -> Point2D:
        if isinstance(segment, LineEntity):
            dx = segment.end_mm[0] - segment.start_mm[0]
            dy = segment.end_mm[1] - segment.start_mm[1]
            length = math.hypot(dx, dy)
            return -dy / length, dx / length
        angle = math.radians(segment.start_angle_deg + (segment.sweep_angle_deg if end else 0))
        sign = math.copysign(1, segment.sweep_angle_deg)
        return -sign * math.cos(angle), -sign * math.sin(angle)

    found: list[float] = []
    count = len(segments) if path.closed else len(segments) - 1
    for index in range(count):
        first, second = segments[index], segments[(index + 1) % len(segments)]
        vertex = path.points_mm[(index + 1) % len(path.points_mm)]
        nx, ny = normal(first, end=True)
        mx, my = normal(second, end=False)
        vx, vy = point[0] - vertex[0], point[1] - vertex[1]
        side1, side2 = vx * nx + vy * ny, vx * mx + vy * my
        if side1 * side2 <= 1e-18:
            continue
        if gap_type == 1:
            distance = math.copysign(math.hypot(vx, vy), side1)
        else:
            bisector_length = math.hypot(nx + mx, ny + my)
            if bisector_length <= 1e-12:
                continue
            distance = (vx * (nx + mx) + vy * (ny + my)) / bisector_length
        if abs(distance) <= 1e-9:
            continue
        try:
            outputs = offset_with_backend(
                (entity,),
                (entity.entity_id,),
                distance,
                gap_type=gap_type,
                closed_offset=closed_offset,
            )[1:]
        except ValueError:
            continue
        if not any(abs(distance - prior) <= 1e-8 for prior in found) and any(
            isinstance(output, PolylineEntity) and _point_on_path(output, point)
            for output in outputs
        ):
            found.append(distance)
    if len(found) > 1:
        raise ValueError("通过点对应多个偏移结果，请重新选择。")
    return found[0] if found else None


def through_offset_distance(
    entity: object,
    point: Point2D,
    *,
    gap_type: int = 0,
    closed_offset: ClosedOffset | None = None,
    spline_offset: SplineOffset | None = None,
    ellipse_offset: EllipseOffset | None = None,
) -> float:
    """Resolve an offset whose resulting finite line or circular curve passes through point."""
    if not all(map(math.isfinite, point)):
        raise ValueError("通过点坐标必须有限。")
    if gap_type in (1, 2) and isinstance(entity, PolylineEntity | RectangleEntity):
        corner_distance = _corner_through_distance(entity, point, gap_type, closed_offset)
        if corner_distance is not None:
            return corner_distance
    if isinstance(entity, EllipseEntity):
        side, _distance = _ellipse_projection(entity, point)
        if abs(side) <= 1e-9 or ellipse_offset is None:
            raise ValueError("通过点位于椭圆上或椭圆偏置不可用。")
        results = ellipse_offset(entity, side)
        if not results or spline_path_separation(results, point) > 0.001:
            raise ValueError("通过点不在偏置后的有限椭圆路径上。")
        return side
    if isinstance(entity, SplineEntity):
        side, _distance = _spline_projection(entity, point)
        if abs(side) <= 1e-9 or spline_offset is None:
            raise ValueError("通过点位于样条上或样条偏置不可用。")
        results = spline_offset(entity, side)
        if not results or min(_spline_projection(result, point)[1] for result in results) > 0.001:
            raise ValueError("通过点不在偏置后的有限样条上。")
        return side
    if isinstance(entity, PolylineEntity) and entity.bulges:
        side, finite_projection = _curved_path_side(entity, point)
        if not finite_projection or abs(side) <= 1e-9:
            raise ValueError("通过点不在有效的偏移区间内。")
        results = offset_with_backend(
            (entity,), (entity.entity_id,), side, gap_type=gap_type, closed_offset=closed_offset
        )[1:]
        for result in results:
            if not isinstance(result, PolylineEntity):
                raise ValueError("偏移结果无效。")
            remaining, on_segment = _curved_path_side(result, point)
            if on_segment and abs(remaining) <= 1e-8:
                return side
        raise ValueError("通过点不在偏移后的有限路径上。")
    if isinstance(entity, LineEntity):
        dx = entity.end_mm[0] - entity.start_mm[0]
        dy = entity.end_mm[1] - entity.start_mm[1]
        length = math.hypot(dx, dy)
        if not math.isfinite(length) or length <= 1e-9:
            raise ValueError("直线长度无效。")
        along = (
            (point[0] - entity.start_mm[0]) * dx + (point[1] - entity.start_mm[1]) * dy
        ) / length
        if not math.isfinite(along) or along < -1e-9 or along > length + 1e-9:
            raise ValueError("通过点的投影不在线段范围内。")
        distance = abs(
            (dx * (point[1] - entity.start_mm[1]) - dy * (point[0] - entity.start_mm[0])) / length
        )
    elif isinstance(entity, CircleEntity | ArcEntity):
        radius = math.dist(point, entity.center_mm)
        if not math.isfinite(radius) or radius <= 1e-9:
            raise ValueError("通过点不能位于圆心。")
        if isinstance(entity, ArcEntity) and not contact_on_curve(entity, point):
            raise ValueError("通过点方向不在圆弧范围内。")
        distance = abs(radius - entity.radius_mm)
    elif isinstance(entity, PolylineEntity | RectangleEntity):
        if isinstance(entity, RectangleEntity):
            x1, y1 = entity.first_corner_mm
            x2, y2 = entity.opposite_corner_mm
            points, closed = ((x1, y1), (x2, y1), (x2, y2), (x1, y2)), True
        else:
            points, closed = entity.points_mm, entity.closed
        ends = (*points[1:], points[0]) if closed else points[1:]
        candidates: list[tuple[float, float]] = []
        for start, end in zip(points, ends, strict=closed):
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = math.hypot(dx, dy)
            if not math.isfinite(length) or length <= 1e-9:
                raise ValueError("偏移路径包含无效线段。")
            projection = max(
                0.0, min(length, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length)
            )
            nearest = (start[0] + projection * dx / length, start[1] + projection * dy / length)
            side = (dx * (point[1] - start[1]) - dy * (point[0] - start[0])) / length
            candidates.append((math.dist(point, nearest), side))
        candidates.sort(key=lambda value: value[0])
        if len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) <= 1e-9:
            raise ValueError("通过点靠近多个线段，请重新选择。")
        distance = abs(candidates[0][1])
        signed = signed_offset_distance(entity, point, distance)
        results = offset_with_backend(
            (entity,), (entity.entity_id,), signed, gap_type=gap_type, closed_offset=closed_offset
        )[1:]
        for result in results:
            if not isinstance(result, PolylineEntity):
                raise ValueError("偏移结果无效。")
            if result.bulges:
                remaining, on_segment = _curved_path_side(result, point)
                if on_segment and abs(remaining) <= 1e-8:
                    return signed
                continue
            result_ends = (
                (*result.points_mm[1:], result.points_mm[0])
                if result.closed
                else result.points_mm[1:]
            )
            for start, end in zip(result.points_mm, result_ends, strict=result.closed):
                dx, dy = end[0] - start[0], end[1] - start[1]
                length = math.hypot(dx, dy)
                projection = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length
                perpendicular = (
                    abs(dx * (point[1] - start[1]) - dy * (point[0] - start[0])) / length
                )
                if -1e-9 <= projection <= length + 1e-9 and perpendicular <= 1e-8:
                    return signed
        raise ValueError("通过点不在偏移后的有限路径上。")
    else:
        raise ValueError("当前图元不支持通过点偏移。")
    return signed_offset_distance(entity, point, distance)


def signed_offset_distance(entity: object, point: Point2D, distance: float) -> float:
    """Return the signed distance for an unambiguous side of a line or curve."""
    if not math.isfinite(distance) or distance <= 0 or not all(map(math.isfinite, point)):
        raise ValueError("偏移距离须为正的有限数值，侧点坐标须有限。")
    if isinstance(entity, EllipseEntity):
        side, _distance = _ellipse_projection(entity, point)
        if abs(side) <= 1e-9:
            raise ValueError("侧点位于对象上，请重新选择偏移侧。")
        return math.copysign(distance, side)
    if isinstance(entity, SplineEntity):
        side, _distance = _spline_projection(entity, point)
        if abs(side) <= 1e-9:
            raise ValueError("侧点位于对象上，请重新选择偏移侧。")
        return math.copysign(distance, side)
    if isinstance(entity, PolylineEntity) and entity.bulges:
        side, finite_projection = _curved_path_side(entity, point)
        if not finite_projection or abs(side) <= 1e-9:
            raise ValueError("侧点不在有效的偏移区间内。")
        return math.copysign(distance, side)
    if isinstance(entity, LineEntity):
        dx = entity.end_mm[0] - entity.start_mm[0]
        dy = entity.end_mm[1] - entity.start_mm[1]
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            raise ValueError("零长度线段不能偏移。")
        side = (
            dx * (point[1] - entity.start_mm[1]) - dy * (point[0] - entity.start_mm[0])
        ) / length
    elif isinstance(entity, PolylineEntity | RectangleEntity):
        if isinstance(entity, RectangleEntity):
            x1, y1 = entity.first_corner_mm
            x2, y2 = entity.opposite_corner_mm
            points = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
            closed = True
        else:
            points = entity.points_mm
            closed = entity.closed
        end_points = (*points[1:], points[0]) if closed else points[1:]
        candidates: list[tuple[float, float]] = []
        for start, end in zip(points, end_points, strict=closed):
            dx, dy = end[0] - start[0], end[1] - start[1]
            length_sq = dx * dx + dy * dy
            if not math.isfinite(length_sq) or length_sq <= 1e-18:
                raise ValueError("偏移路径包含零长度线段。")
            ratio = max(
                0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq)
            )
            nearest = (start[0] + ratio * dx, start[1] + ratio * dy)
            side_value = (dx * (point[1] - start[1]) - dy * (point[0] - start[0])) / math.sqrt(
                length_sq
            )
            separation = math.dist(point, nearest)
            if not math.isfinite(separation) or not math.isfinite(side_value):
                raise ValueError("坐标超出可用范围。")
            candidates.append((separation, side_value))
        candidates.sort(key=lambda item: item[0])
        if len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) <= 1e-9:
            raise ValueError("侧点靠近多个线段，请重新选择。")
        side = candidates[0][1]
    elif isinstance(entity, CircleEntity | ArcEntity):
        side = math.dist(point, entity.center_mm) - entity.radius_mm
        if isinstance(entity, ArcEntity):
            side *= -math.copysign(1.0, entity.sweep_angle_deg)
    else:
        raise ValueError("当前图元暂不支持交互偏移。")
    if not math.isfinite(side):
        raise ValueError("坐标超出可用范围。")
    if abs(side) <= 1e-9:
        raise ValueError("侧点位于对象上，请重新选择偏移侧。")
    return math.copysign(distance, side)


def _ellipse_projection(entity: EllipseEntity, point: Point2D) -> tuple[float, float]:
    """Find the closest finite ellipse location and its directed normal distance."""
    count = 128

    def at(value: float) -> Point2D:
        parameter = value % 1.0 if entity.closed else max(0.0, min(1.0, value))
        return entity.point_at(parameter)

    def squared(value: float) -> float:
        location = at(value)
        return (point[0] - location[0]) ** 2 + (point[1] - location[1]) ** 2

    samples = [squared(index / count) for index in range(count + 1)]
    indices = range(count) if entity.closed else range(count + 1)
    intervals: list[tuple[float, float]] = []
    for index in indices:
        left = samples[(index - 1) % count] if entity.closed else samples[max(0, index - 1)]
        right = samples[(index + 1) % count] if entity.closed else samples[min(count, index + 1)]
        if samples[index] <= left and samples[index] <= right:
            intervals.append(((index - 1) / count, (index + 1) / count))
    ratio = (math.sqrt(5) - 1) / 2
    candidates: list[tuple[float, float]] = []
    for low, high in intervals:
        left, right = high - ratio * (high - low), low + ratio * (high - low)
        for _ in range(48):
            if squared(left) < squared(right):
                high, right = right, left
                left = high - ratio * (high - low)
            else:
                low, left = left, right
                right = low + ratio * (high - low)
        value = (low + high) / 2
        candidates.append((squared(value), value))
    candidates.sort()
    if not candidates:
        raise ValueError("无法确定椭圆上的最近点。")
    if len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) <= 1e-12:
        raise ValueError("侧点靠近椭圆多个位置，请重新选择。")
    separation, parameter = candidates[0]
    base, before, after = at(parameter), at(parameter - 1e-6), at(parameter + 1e-6)
    tangent = (after[0] - before[0], after[1] - before[1])
    length = math.hypot(*tangent)
    if length <= 1e-12:
        raise ValueError("椭圆切向退化，请选择其他位置。")
    signed = (tangent[0] * (point[1] - base[1]) - tangent[1] * (point[0] - base[0])) / length
    return signed, math.sqrt(separation)


def _spline_projection(entity: SplineEntity, point: Point2D) -> tuple[float, float]:
    """Find the closest point and its oriented normal distance on a finite spline."""
    count = max(64, (len(entity.control_points_mm) - 3) * 32)

    def squared(parameter: float) -> float:
        target = entity.point_at(parameter)
        return (target[0] - point[0]) ** 2 + (target[1] - point[1]) ** 2

    sampled = [squared(i / count) for i in range(count + 1)]
    intervals = [
        (max(0, i - 1) / count, min(count, i + 1) / count)
        for i in range(count + 1)
        if (i == 0 or sampled[i] <= sampled[i - 1]) and (i == count or sampled[i] <= sampled[i + 1])
    ]
    candidates: list[tuple[float, float]] = []
    ratio = (math.sqrt(5) - 1) / 2
    for low, high in intervals:
        left, right = high - ratio * (high - low), low + ratio * (high - low)
        left_value, right_value = squared(left), squared(right)
        for _ in range(48):
            if left_value < right_value:
                high, right, right_value = right, left, left_value
                left = high - ratio * (high - low)
                left_value = squared(left)
            else:
                low, left, left_value = left, right, right_value
                right = low + ratio * (high - low)
                right_value = squared(right)
        parameter = (low + high) / 2
        candidates.append((squared(parameter), parameter))
    candidates.sort()
    if len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) <= 1e-12:
        raise ValueError("侧点靠近样条多个位置，请重新选择。")
    value, parameter = candidates[0]
    base = entity.point_at(parameter)
    before, after = (
        entity.point_at(max(0.0, parameter - 1e-6)),
        entity.point_at(min(1.0, parameter + 1e-6)),
    )
    tangent = (after[0] - before[0], after[1] - before[1])
    length = math.hypot(*tangent)
    if length <= 1e-12:
        raise ValueError("样条切向退化，请选择其他位置。")
    signed = (tangent[0] * (point[1] - base[1]) - tangent[1] * (point[0] - base[0])) / length
    return signed, math.sqrt(value)
