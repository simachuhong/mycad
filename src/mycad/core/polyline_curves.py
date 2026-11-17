# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact conversion between directed polyline bulges and circular arcs."""

from __future__ import annotations

import math
from dataclasses import replace

from mycad.core.sketch import ArcEntity, LineEntity, Point2D, PolylineEntity


def bulge_arc(start: Point2D, end: Point2D, bulge: float, identity: str) -> ArcEntity:
    """Construct the signed circular arc joining two directed segment endpoints."""
    if not math.isfinite(bulge) or abs(bulge) <= 1e-12:
        raise ValueError("圆弧 bulge 必须是非零有限数值。")
    dx, dy = end[0] - start[0], end[1] - start[1]
    chord = math.hypot(dx, dy)
    if not math.isfinite(chord) or chord <= 1e-9:
        raise ValueError("圆弧段端点必须不同且坐标有限。")
    offset = (1 / bulge - bulge) / 4
    center = ((start[0] + end[0]) / 2 - dy * offset, (start[1] + end[1]) / 2 + dx * offset)
    radius = math.hypot(start[0] - center[0], start[1] - center[1])
    angle = math.degrees(math.atan2(start[1] - center[1], start[0] - center[0]))
    sweep = math.degrees(4 * math.atan(bulge))
    return ArcEntity(identity, center, radius, angle, sweep)


def polyline_arc_segment(entity: PolylineEntity, index: int) -> ArcEntity:
    """Return the exact directed circular segment selected by its stable index."""
    if index < 0 or index >= len(entity.bulges) or entity.bulges[index] == 0:
        raise ValueError("所选多段线段不是圆弧。")
    return bulge_arc(
        entity.points_mm[index],
        entity.points_mm[(index + 1) % len(entity.points_mm)],
        entity.bulges[index],
        entity.entity_id,
    )


def polyline_curve_segments(
    points: tuple[Point2D, ...],
    bulges: tuple[float, ...],
    closed: bool,
    identity: str,
    *,
    construction: bool = False,
    layer_name: str = "0",
) -> tuple[LineEntity | ArcEntity, ...]:
    """Expand directed bulges to exact geometry, retaining the parent identity."""
    count = len(points) if closed else len(points) - 1
    if len(points) < (3 if closed else 2) or len(bulges) != count:
        raise ValueError("多段线的顶点数与曲线段数不匹配。")
    if any(not math.isfinite(value) for value in bulges):
        raise ValueError("多段线 bulge 必须是有限数值。")
    segments: list[LineEntity | ArcEntity] = []
    for index, bulge in enumerate(bulges):
        start, end = points[index], points[(index + 1) % len(points)]
        if bulge == 0:
            segments.append(LineEntity(identity, start, end, construction, layer_name))
        else:
            arc = bulge_arc(start, end, bulge, identity)
            segments.append(replace(arc, construction=construction, layer_name=layer_name))
    return tuple(segments)


def polyline_sampled_points(entity: PolylineEntity) -> tuple[Point2D, ...]:
    """Sample circular segments for display while preserving authored vertices."""
    if not entity.bulges:
        return (*entity.points_mm, entity.points_mm[0]) if entity.closed else entity.points_mm
    segments = polyline_curve_segments(
        entity.points_mm, entity.bulges, entity.closed, entity.entity_id
    )
    points: list[Point2D] = [entity.points_mm[0]]
    for index, segment in enumerate(segments):
        if isinstance(segment, ArcEntity):
            count = max(2, math.ceil(abs(segment.sweep_angle_deg) / 7.5))
            for step in range(1, count):
                angle = math.radians(
                    segment.start_angle_deg + segment.sweep_angle_deg * step / count
                )
                points.append(
                    (
                        segment.center_mm[0] + segment.radius_mm * math.cos(angle),
                        segment.center_mm[1] + segment.radius_mm * math.sin(angle),
                    )
                )
        points.append(entity.points_mm[(index + 1) % len(entity.points_mm)])
    return tuple(points)
