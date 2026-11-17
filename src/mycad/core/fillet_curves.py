# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared finite-curve checks for planar fillet candidates."""

from __future__ import annotations

import math
from dataclasses import replace

from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Point2D


def trim_arc_at_contact(arc: ArcEntity, contact: Point2D, pick: Point2D) -> ArcEntity:
    """Trim to the picked side or extend the nearer endpoint to the contact."""
    if abs(math.dist(arc.center_mm, contact) - arc.radius_mm) > max(
        1e-8, arc.radius_mm * 1e-9
    ) or not contact_on_curve(arc, pick):
        raise ValueError("圆角切点或拾取点不在所选圆弧上。")
    sign = 1.0 if arc.sweep_angle_deg > 0 else -1.0

    def position(point: Point2D) -> float:
        angle = math.degrees(math.atan2(point[1] - arc.center_mm[1], point[0] - arc.center_mm[0]))
        offset = (sign * (angle - arc.start_angle_deg)) % 360.0
        return 0.0 if offset >= 360.0 - 1e-8 else offset

    cut = position(contact)
    chosen = position(pick)
    if abs(chosen - cut) <= 1e-8:
        raise ValueError("请在圆角切点的一侧选取圆弧，以确定保留方向。")
    if cut > abs(arc.sweep_angle_deg) + 1e-8:
        extend_end = cut - abs(arc.sweep_angle_deg)
        extend_start = 360.0 - cut
        if abs(extend_start - extend_end) <= 1e-8:
            raise ValueError("圆弧延长方向不明确，请重新选择。")
        if extend_start < extend_end:
            return replace(
                arc,
                start_angle_deg=arc.start_angle_deg - sign * extend_start,
                sweep_angle_deg=arc.sweep_angle_deg + sign * extend_start,
            )
        return replace(arc, sweep_angle_deg=sign * cut)
    if cut <= 1e-8 or cut >= abs(arc.sweep_angle_deg) - 1e-8:
        return arc
    if chosen < cut:
        return replace(arc, sweep_angle_deg=sign * cut)
    return replace(
        arc,
        start_angle_deg=arc.start_angle_deg + sign * cut,
        sweep_angle_deg=arc.sweep_angle_deg - sign * cut,
    )


def contact_on_curve(curve: CircleEntity | ArcEntity, point: Point2D) -> bool:
    """Check that a point on the supporting circle belongs to its finite arc."""
    if isinstance(curve, CircleEntity):
        return True
    angle = math.degrees(math.atan2(point[1] - curve.center_mm[1], point[0] - curve.center_mm[0]))
    offset = (
        (angle - curve.start_angle_deg) % 360.0
        if curve.sweep_angle_deg > 0
        else (curve.start_angle_deg - angle) % 360.0
    )
    return offset <= abs(curve.sweep_angle_deg) + 1e-8 or offset >= 360.0 - 1e-8


def tangent_on_curves(
    first: LineEntity | CircleEntity | ArcEntity,
    second: LineEntity | CircleEntity | ArcEntity,
) -> bool:
    """Check geometric tangency at a point belonging to both finite entities."""
    if isinstance(first, LineEntity) and isinstance(second, LineEntity):
        return False
    if isinstance(second, LineEntity):
        first, second = second, first
    if isinstance(first, LineEntity):
        if isinstance(second, LineEntity):
            return False
        dx, dy = first.end_mm[0] - first.start_mm[0], first.end_mm[1] - first.start_mm[1]
        length_squared = dx * dx + dy * dy
        position = (
            (second.center_mm[0] - first.start_mm[0]) * dx
            + (second.center_mm[1] - first.start_mm[1]) * dy
        ) / length_squared
        if position < -1e-9 or position > 1 + 1e-9:
            return False
        contact = (first.start_mm[0] + position * dx, first.start_mm[1] + position * dy)
        tolerance = max(1e-8, second.radius_mm * 1e-9)
        return abs(
            math.dist(contact, second.center_mm) - second.radius_mm
        ) <= tolerance and contact_on_curve(second, contact)
    if isinstance(second, LineEntity):
        return False
    dx = second.center_mm[0] - first.center_mm[0]
    dy = second.center_mm[1] - first.center_mm[1]
    distance = math.hypot(dx, dy)
    if distance <= 1e-10:
        return False
    tolerance = max(1e-8, first.radius_mm * 1e-9, second.radius_mm * 1e-9)
    for sign in (-1, 1):
        contact = (
            first.center_mm[0] + sign * first.radius_mm * dx / distance,
            first.center_mm[1] + sign * first.radius_mm * dy / distance,
        )
        if (
            abs(math.dist(contact, second.center_mm) - second.radius_mm) <= tolerance
            and contact_on_curve(first, contact)
            and contact_on_curve(second, contact)
        ):
            return True
    return False
