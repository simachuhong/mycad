# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Fillets between circles and finite arcs in independent drawings."""

from __future__ import annotations

import math

from mycad.core.fillet_curves import contact_on_curve, trim_arc_at_contact
from mycad.core.sketch import ArcEntity, CircleEntity, Point2D


def circle_fillet_notrim(
    first: CircleEntity | ArcEntity,
    second: CircleEntity | ArcEntity,
    first_pick: Point2D,
    second_pick: Point2D,
    radius: float,
    identity: str,
    *,
    layer_name: str = "0",
    extend_arcs: bool = False,
) -> ArcEntity:
    """Return the nearest minor internal or external fillet, retaining both sources."""
    if first.entity_id == second.entity_id:
        raise ValueError("请选择两个不同的圆。")
    if first.construction != second.construction:
        raise ValueError("构造图元和普通图元不能混合创建圆角。")
    if not math.isfinite(radius) or radius <= 1e-10:
        raise ValueError("圆角半径必须是大于零的有限数值。")
    if any(not math.isfinite(v) for point in (first_pick, second_pick) for v in point):
        raise ValueError("拾取坐标必须是有限数值。")
    x1, y1 = first.center_mm
    x2, y2 = second.center_mm
    dx, dy = x2 - x1, y2 - y1
    distance = math.hypot(dx, dy)
    if not math.isfinite(distance) or distance <= 1e-10:
        raise ValueError("圆心重合或数值超出范围，无法创建圆角。")
    ux, uy = dx / distance, dy / distance
    candidates: list[tuple[float, Point2D, float, float]] = []
    first_offsets = ((first.radius_mm + radius, 1.0), (abs(first.radius_mm - radius), -1.0))
    second_offsets = ((second.radius_mm + radius, 1.0), (abs(second.radius_mm - radius), -1.0))
    for offset1, mode1 in first_offsets:
        for offset2, mode2 in second_offsets:
            if min(offset1, offset2) <= 1e-10 or not all(
                math.isfinite(v) for v in (offset1, offset2)
            ):
                continue
            if distance > offset1 + offset2 or distance < abs(offset1 - offset2):
                continue
            along = (distance * distance + offset1 * offset1 - offset2 * offset2) / (2 * distance)
            height_squared = offset1 * offset1 - along * along
            if not math.isfinite(along) or not math.isfinite(height_squared):
                continue
            height = math.sqrt(max(0.0, height_squared))
            for sign in (1,) if height <= 1e-10 else (1, -1):
                center = (
                    x1 + along * ux - sign * height * uy,
                    y1 + along * uy + sign * height * ux,
                )
                contacts: list[Point2D] = []
                angles: list[float] = []
                for circle, offset, mode in ((first, offset1, mode1), (second, offset2, mode2)):
                    direction_sign = mode if circle.radius_mm > radius else 1.0
                    vx = direction_sign * (circle.center_mm[0] - center[0]) / offset
                    vy = direction_sign * (circle.center_mm[1] - center[1]) / offset
                    contacts.append((center[0] + radius * vx, center[1] + radius * vy))
                    angles.append(math.degrees(math.atan2(vy, vx)))
                valid = True
                for curve, contact, pick in zip(
                    (first, second), contacts, (first_pick, second_pick), strict=True
                ):
                    if contact_on_curve(curve, contact):
                        continue
                    if not extend_arcs or not isinstance(curve, ArcEntity):
                        valid = False
                        break
                    try:
                        trim_arc_at_contact(curve, contact, pick)
                    except ValueError:
                        valid = False
                        break
                if not valid:
                    continue
                sweep = (angles[1] - angles[0] + 180.0) % 360.0 - 180.0
                if abs(sweep) <= 1e-10:
                    continue
                score = math.dist(contacts[0], first_pick) + math.dist(contacts[1], second_pick)
                if math.isfinite(score):
                    candidates.append((score, center, angles[0], angles[1]))
    candidates.sort(key=lambda candidate: candidate[0])
    if not candidates:
        raise ValueError("无法创建圆角：无有效切点，或切点不在所选圆弧上。")
    if len(candidates) > 1 and math.isclose(candidates[0][0], candidates[1][0], abs_tol=1e-10):
        raise ValueError("无法确定圆角方向，请靠近目标切点重新选择。")
    _, center, start, end = candidates[0]
    sweep = (end - start + 180.0) % 360.0 - 180.0
    if abs(sweep) <= 1e-10:
        raise ValueError("圆角退化为零长度。")
    return ArcEntity(
        identity,
        center,
        radius,
        start,
        sweep,
        construction=first.construction,
        layer_name=layer_name,
    )
