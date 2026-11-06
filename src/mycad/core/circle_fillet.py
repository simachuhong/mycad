# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral two-circle external fillet geometry for independent drawings."""

from __future__ import annotations

import math

from mycad.core.sketch import ArcEntity, CircleEntity, Point2D


def circle_fillet_notrim(
    first: CircleEntity,
    second: CircleEntity,
    first_pick: Point2D,
    second_pick: Point2D,
    radius: float,
    identity: str,
    *,
    layer_name: str = "0",
) -> ArcEntity:
    """Return the minor external tangent arc nearest the picks, retaining both circles."""
    if first.entity_id == second.entity_id:
        raise ValueError("请选择两个不同的圆。")
    if not math.isfinite(radius) or radius <= 1e-10:
        raise ValueError("圆角半径必须是大于零的有限数值。")
    if any(not math.isfinite(v) for point in (first_pick, second_pick) for v in point):
        raise ValueError("拾取坐标必须是有限数值。")
    x1, y1 = first.center_mm
    x2, y2 = second.center_mm
    dx, dy = x2 - x1, y2 - y1
    distance = math.hypot(dx, dy)
    offset1, offset2 = first.radius_mm + radius, second.radius_mm + radius
    if not all(math.isfinite(v) for v in (distance, offset1, offset2)) or distance <= 1e-10:
        raise ValueError("圆心重合或数值超出范围，无法创建圆角。")
    if distance > offset1 + offset2 or distance < abs(offset1 - offset2):
        raise ValueError("该半径无法创建两个圆的外切圆角。")
    along = (distance * distance + offset1 * offset1 - offset2 * offset2) / (2 * distance)
    height_squared = offset1 * offset1 - along * along
    if not math.isfinite(along) or not math.isfinite(height_squared):
        raise ValueError("圆角数值超出范围。")
    height = math.sqrt(max(0.0, height_squared))
    ux, uy = dx / distance, dy / distance
    candidates: list[tuple[float, Point2D, float, float]] = []
    for sign in (1, -1):
        center = (x1 + along * ux - sign * height * uy, y1 + along * uy + sign * height * ux)
        contacts: list[Point2D] = []
        angles: list[float] = []
        for circle, offset in ((first, offset1), (second, offset2)):
            vx = (circle.center_mm[0] - center[0]) / offset
            vy = (circle.center_mm[1] - center[1]) / offset
            contacts.append((center[0] + radius * vx, center[1] + radius * vy))
            angles.append(math.degrees(math.atan2(vy, vx)))
        score = math.dist(contacts[0], first_pick) + math.dist(contacts[1], second_pick)
        candidates.append((score, center, angles[0], angles[1]))
    candidates.sort(key=lambda candidate: candidate[0])
    if height > 1e-10 and math.isclose(candidates[0][0], candidates[1][0], abs_tol=1e-10):
        raise ValueError("无法确定圆角方向，请靠近目标切点重新选择。")
    _, center, start, end = candidates[0]
    sweep = (end - start + 180.0) % 360.0 - 180.0
    if abs(sweep) <= 1e-10:
        raise ValueError("圆角退化为零长度。")
    return ArcEntity(identity, center, radius, start, sweep, layer_name=layer_name)
