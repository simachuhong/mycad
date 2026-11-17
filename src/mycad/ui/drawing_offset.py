# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Resolve a picked side to the sketch offset algorithm's signed distance."""

from __future__ import annotations

import math

from mycad.core.fillet_curves import contact_on_curve
from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    Point2D,
    PolylineEntity,
    RectangleEntity,
)
from mycad.core.sketch_edit import offset_entities


def _curved_path_side(entity: PolylineEntity, point: Point2D) -> tuple[float, bool]:
    candidates: list[tuple[float, float, bool]] = []
    for segment in polyline_curve_segments(
        entity.points_mm, entity.bulges, entity.closed, entity.entity_id
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


def through_offset_distance(entity: object, point: Point2D, *, gap_type: int = 0) -> float:
    """Resolve an offset whose resulting finite line or circular curve passes through point."""
    if not all(map(math.isfinite, point)):
        raise ValueError("通过点坐标必须有限。")
    if isinstance(entity, PolylineEntity) and entity.bulges:
        side, finite_projection = _curved_path_side(entity, point)
        if not finite_projection or abs(side) <= 1e-9:
            raise ValueError("通过点不在有效的偏移区间内。")
        result = offset_entities((entity,), (entity.entity_id,), side, gap_type=gap_type)[1]
        if not isinstance(result, PolylineEntity):
            raise ValueError("偏移结果无效。")
        remaining, on_segment = _curved_path_side(result, point)
        if not on_segment or abs(remaining) > 1e-8:
            raise ValueError("通过点不在偏移后的有限路径上。")
        return side
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
        result = offset_entities((entity,), (entity.entity_id,), signed, gap_type=gap_type)[1]
        if not isinstance(result, PolylineEntity):
            raise ValueError("偏移结果无效。")
        if result.bulges:
            remaining, on_segment = _curved_path_side(result, point)
            if on_segment and abs(remaining) <= 1e-8:
                return signed
            raise ValueError("通过点不在偏移后的有限路径上。")
        result_ends = (
            (*result.points_mm[1:], result.points_mm[0]) if result.closed else result.points_mm[1:]
        )
        for start, end in zip(result.points_mm, result_ends, strict=result.closed):
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = math.hypot(dx, dy)
            projection = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length
            perpendicular = abs(dx * (point[1] - start[1]) - dy * (point[0] - start[0])) / length
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
