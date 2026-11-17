# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Fillets between lines and finite circular curves."""

from __future__ import annotations

import math
from dataclasses import replace

from mycad.core.fillet_curves import contact_on_curve, trim_arc_at_contact
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Point2D

_EPSILON = 1e-10


def line_circle_fillet_trim(
    line: LineEntity,
    circle: CircleEntity | ArcEntity,
    line_pick: Point2D,
    circle_pick: Point2D,
    radius: float,
    identity: str,
    *,
    layer_name: str = "0",
) -> tuple[LineEntity, ArcEntity]:
    """Retain the picked side of the line and leave the circular source untouched."""
    arc = line_circle_fillet_notrim(
        line,
        circle,
        line_pick,
        circle_pick,
        radius,
        identity,
        layer_name=layer_name,
        extend_line=True,
        extend_arc=True,
    )
    start = math.radians(arc.start_angle_deg)
    contact = (
        arc.center_mm[0] + radius * math.cos(start),
        arc.center_mm[1] + radius * math.sin(start),
    )
    dx = line.end_mm[0] - line.start_mm[0]
    dy = line.end_mm[1] - line.start_mm[1]
    projection = (line_pick[0] - contact[0]) * dx + (line_pick[1] - contact[1]) * dy
    if abs(projection) <= _EPSILON:
        raise ValueError("请在线段切点一侧选取，以确定保留方向。")
    trimmed = replace(line, start_mm=contact) if projection > 0 else replace(line, end_mm=contact)
    return trimmed, arc


def line_circle_fillet_notrim(
    line: LineEntity,
    circle: CircleEntity | ArcEntity,
    line_pick: Point2D,
    circle_pick: Point2D,
    radius: float,
    identity: str,
    *,
    layer_name: str = "0",
    extend_line: bool = False,
    extend_arc: bool = False,
) -> ArcEntity:
    """Choose the nearest internal or external tangent arc on the requested line span."""
    if line.entity_id == circle.entity_id:
        raise ValueError("请选择两个不同的对象。")
    if line.construction != circle.construction:
        raise ValueError("构造线和普通图元不能混合创建圆角。")
    values = (
        *line.start_mm,
        *line.end_mm,
        *circle.center_mm,
        circle.radius_mm,
        *line_pick,
        *circle_pick,
        radius,
    )
    if (
        not all(math.isfinite(value) for value in values)
        or radius <= _EPSILON
        or circle.radius_mm <= _EPSILON
    ):
        raise ValueError("圆角坐标和半径必须是有效的有限数值。")
    dx, dy = line.end_mm[0] - line.start_mm[0], line.end_mm[1] - line.start_mm[1]
    length = math.hypot(dx, dy)
    offsets = ((circle.radius_mm + radius, 1.0), (abs(circle.radius_mm - radius), -1.0))
    if not math.isfinite(length) or length <= _EPSILON or not math.isfinite(offsets[0][0]):
        raise ValueError("直线长度或圆角数值无效。")
    direction = (dx / length, dy / length)
    normal = (-direction[1], direction[0])
    delta = (circle.center_mm[0] - line.start_mm[0], circle.center_mm[1] - line.start_mm[1])
    along = delta[0] * direction[0] + delta[1] * direction[1]
    perpendicular = delta[0] * normal[0] + delta[1] * normal[1]
    candidates: list[tuple[float, Point2D, float, float]] = []
    for offset, mode in offsets:
        if offset <= _EPSILON:
            continue
        for side in (-1, 1):
            normal_distance = perpendicular - side * radius
            height_squared = offset * offset - normal_distance * normal_distance
            if not math.isfinite(height_squared) or height_squared < -_EPSILON:
                continue
            height = math.sqrt(max(0.0, height_squared))
            for shift in (0.0,) if height <= _EPSILON else (-height, height):
                position = along + shift
                if not extend_line and (position < -_EPSILON or position > length + _EPSILON):
                    continue
                contact = (
                    line.start_mm[0] + position * direction[0],
                    line.start_mm[1] + position * direction[1],
                )
                center = (
                    contact[0] + side * radius * normal[0],
                    contact[1] + side * radius * normal[1],
                )
                direction_sign = mode if circle.radius_mm > radius else 1.0
                circle_direction = (
                    direction_sign * (circle.center_mm[0] - center[0]) / offset,
                    direction_sign * (circle.center_mm[1] - center[1]) / offset,
                )
                circle_contact = (
                    center[0] + radius * circle_direction[0],
                    center[1] + radius * circle_direction[1],
                )
                if not contact_on_curve(circle, circle_contact):
                    if not extend_arc or not isinstance(circle, ArcEntity):
                        continue
                    try:
                        trim_arc_at_contact(circle, circle_contact, circle_pick)
                    except ValueError:
                        continue
                start = math.degrees(math.atan2(-side * normal[1], -side * normal[0]))
                end = math.degrees(math.atan2(circle_direction[1], circle_direction[0]))
                sweep = (end - start + 180.0) % 360.0 - 180.0
                score = math.dist(contact, line_pick) + math.dist(circle_contact, circle_pick)
                if abs(sweep) > _EPSILON and math.isfinite(score):
                    candidates.append((score, center, start, sweep))
    candidates.sort(key=lambda candidate: candidate[0])
    if not candidates:
        raise ValueError("该半径无法在线段上创建与圆外切的圆角。")
    if len(candidates) > 1 and math.isclose(candidates[0][0], candidates[1][0], abs_tol=_EPSILON):
        raise ValueError("无法确定圆角方向，请靠近目标切点重新选择。")
    _, center, start, sweep = candidates[0]
    return ArcEntity(
        identity,
        center,
        radius,
        start,
        sweep,
        construction=line.construction,
        layer_name=layer_name,
    )
