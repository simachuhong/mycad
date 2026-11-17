# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Common tangent segments between two finite circular curves."""

from __future__ import annotations

import math

from mycad.core.fillet_curves import contact_on_curve
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Point2D


def common_tangent_line(
    first: CircleEntity | ArcEntity,
    second: CircleEntity | ArcEntity,
    first_pick: Point2D,
    second_pick: Point2D,
    identity: str,
    *,
    construction: bool = False,
    layer_name: str = "0",
) -> LineEntity:
    """Choose a common tangent using the two source-side pick positions."""
    if first.entity_id == second.entity_id:
        raise ValueError("请选择两个不同的切线对象。")
    if any(not math.isfinite(value) for point in (first_pick, second_pick) for value in point):
        raise ValueError("切点拾取坐标必须有限。")
    dx, dy = second.center_mm[0] - first.center_mm[0], second.center_mm[1] - first.center_mm[1]
    distance = math.hypot(dx, dy)
    if distance <= 1e-12:
        raise ValueError("同心圆没有唯一的公共切线。")
    ux, uy = dx / distance, dy / distance
    candidates: list[tuple[float, Point2D, Point2D]] = []
    for side in (1.0, -1.0):
        component = (first.radius_mm - side * second.radius_mm) / distance
        if abs(component) > 1 + 1e-12:
            continue
        component = min(1.0, max(-1.0, component))
        lateral = math.sqrt(max(0.0, 1 - component * component))
        for sign in (-1.0, 1.0):
            nx, ny = component * ux - sign * lateral * uy, component * uy + sign * lateral * ux
            start = (
                first.center_mm[0] + first.radius_mm * nx,
                first.center_mm[1] + first.radius_mm * ny,
            )
            end = (
                second.center_mm[0] + side * second.radius_mm * nx,
                second.center_mm[1] + side * second.radius_mm * ny,
            )
            if (
                math.dist(start, end) <= 1e-9
                or not contact_on_curve(first, start)
                or not contact_on_curve(second, end)
            ):
                continue
            if any(
                math.dist(start, prior_start) <= 1e-9 and math.dist(end, prior_end) <= 1e-9
                for _, prior_start, prior_end in candidates
            ):
                continue
            score = math.dist(start, first_pick) + math.dist(end, second_pick)
            candidates.append((score, start, end))
    candidates.sort(key=lambda item: item[0])
    if not candidates:
        raise ValueError("无法找到所选有限曲线的公共切线。")
    if len(candidates) > 1 and math.isclose(
        candidates[0][0], candidates[1][0], rel_tol=1e-12, abs_tol=1e-9
    ):
        raise ValueError("公共切线方向不明确，请靠近目标切点重新选择。")
    _, start, end = candidates[0]
    return LineEntity(identity, start, end, construction=construction, layer_name=layer_name)


def tangent_line_to_point(
    curve: CircleEntity | ArcEntity,
    point: Point2D,
    pick: Point2D,
    identity: str,
    *,
    from_curve: bool = False,
    construction: bool = False,
    layer_name: str = "0",
) -> LineEntity:
    """Create a finite tangent between a point and a circular curve."""
    if any(not math.isfinite(value) for item in (point, pick) for value in item):
        raise ValueError("切线点坐标必须有限。")
    dx, dy = point[0] - curve.center_mm[0], point[1] - curve.center_mm[1]
    distance = math.hypot(dx, dy)
    if distance <= curve.radius_mm + 1e-9:
        raise ValueError("给定点必须位于圆外，才能生成非零切线。")
    ux, uy = dx / distance, dy / distance
    component = curve.radius_mm / distance
    lateral = math.sqrt(max(0.0, 1 - component * component))
    candidates: list[tuple[float, Point2D]] = []
    for sign in (-1.0, 1.0):
        nx, ny = component * ux - sign * lateral * uy, component * uy + sign * lateral * ux
        contact = (
            curve.center_mm[0] + curve.radius_mm * nx,
            curve.center_mm[1] + curve.radius_mm * ny,
        )
        if contact_on_curve(curve, contact):
            candidates.append((math.dist(contact, pick), contact))
    candidates.sort(key=lambda item: item[0])
    if not candidates:
        raise ValueError("所选有限圆弧上没有可用切点。")
    if len(candidates) > 1 and math.isclose(
        candidates[0][0], candidates[1][0], rel_tol=1e-12, abs_tol=1e-9
    ):
        raise ValueError("切点方向不明确，请靠近目标切点重新选择。")
    contact = candidates[0][1]
    return LineEntity(
        identity,
        contact if from_curve else point,
        point if from_curve else contact,
        construction=construction,
        layer_name=layer_name,
    )
