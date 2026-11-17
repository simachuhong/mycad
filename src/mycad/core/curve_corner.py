# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Zero-radius corners between lines and circular curves."""

from __future__ import annotations

import math
from dataclasses import replace

from mycad.core.fillet_curves import trim_arc_at_contact
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Point2D
from mycad.core.sketch_edit import (
    supporting_circle_intersections,
    supporting_line_circle_intersections,
)

type CornerCurve = LineEntity | CircleEntity | ArcEntity


def curve_corner(
    first: CornerCurve, second: CornerCurve, first_pick: Point2D, second_pick: Point2D
) -> tuple[CornerCurve, CornerCurve]:
    """Trim or extend the picked sides to a supporting-curve intersection."""
    result_first, result_second, _contact = curve_corner_with_contact(
        first, second, first_pick, second_pick
    )
    return result_first, result_second


def curve_corner_with_contact(
    first: CornerCurve, second: CornerCurve, first_pick: Point2D, second_pick: Point2D
) -> tuple[CornerCurve, CornerCurve, Point2D]:
    """Return both edited curves and their selected intersection."""
    if first.entity_id == second.entity_id:
        raise ValueError("请选择两个不同的对象。")
    if first.construction != second.construction:
        raise ValueError("构造线和普通线不能混合创建角点。")
    if any(not math.isfinite(value) for point in (first_pick, second_pick) for value in point):
        raise ValueError("拾取坐标必须是有限数值。")
    if isinstance(first, CircleEntity) and isinstance(second, CircleEntity):
        raise ValueError("两个圆不需要修剪；未创建角点。")
    if isinstance(first, LineEntity) and isinstance(second, LineEntity):
        raise ValueError("两条直线应使用直线角点。")
    if isinstance(first, LineEntity) or isinstance(second, LineEntity):
        line = first if isinstance(first, LineEntity) else second
        circular = second if isinstance(first, LineEntity) else first
        assert isinstance(line, LineEntity) and isinstance(circular, CircleEntity | ArcEntity)
        intersections = supporting_line_circle_intersections(
            line.start_mm, line.end_mm, circular.center_mm, circular.radius_mm
        )
    else:
        intersections = supporting_circle_intersections(
            first.center_mm, first.radius_mm, second.center_mm, second.radius_mm
        )

    def trim(curve: CornerCurve, pick: Point2D, vertex: Point2D) -> CornerCurve:
        if isinstance(curve, CircleEntity):
            return curve
        if isinstance(curve, ArcEntity):
            return trim_arc_at_contact(curve, vertex, pick)
        dx, dy = curve.end_mm[0] - curve.start_mm[0], curve.end_mm[1] - curve.start_mm[1]
        length = math.hypot(dx, dy)
        projection = ((pick[0] - vertex[0]) * dx + (pick[1] - vertex[1]) * dy) / length
        if abs(projection) <= 1e-10:
            raise ValueError("请在交点的一侧选取直线。")
        return replace(curve, start_mm=vertex) if projection > 0 else replace(curve, end_mm=vertex)

    candidates: list[tuple[float, CornerCurve, CornerCurve, Point2D]] = []
    for vertex in intersections:
        try:
            a, b = trim(first, first_pick, vertex), trim(second, second_pick, vertex)
        except ValueError:
            continue
        score = math.dist(first_pick, vertex) + math.dist(second_pick, vertex)
        if math.isfinite(score):
            candidates.append((score, a, b, vertex))
    if not candidates:
        raise ValueError("所选对象没有可用交点；请检查拾取位置。")
    candidates.sort(key=lambda candidate: candidate[0])
    if len(candidates) > 1 and math.isclose(candidates[0][0], candidates[1][0], abs_tol=1e-9):
        raise ValueError("交点选择不明确，请靠近需要的交点选取对象。")
    return candidates[0][1], candidates[0][2], candidates[0][3]
