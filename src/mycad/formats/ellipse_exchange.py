# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Lossless planar sketch ellipse conversion to native DXF parameters."""

from __future__ import annotations

import math
from dataclasses import dataclass

from mycad.core.sketch import EllipseEntity


@dataclass(frozen=True, slots=True)
class DxfEllipseParameters:
    center: tuple[float, float, float]
    major_axis: tuple[float, float, float]
    ratio: float
    start_param: float
    end_param: float


def ellipse_to_dxf(ellipse: EllipseEntity) -> DxfEllipseParameters:
    rotation = math.radians(ellipse.rotation_deg)
    major_axis = (
        ellipse.major_radius_mm * math.cos(rotation),
        ellipse.major_radius_mm * math.sin(rotation),
        0.0,
    )
    if ellipse.closed:
        start, end = 0.0, math.tau
    else:
        first = math.radians(ellipse.start_angle_deg)
        last = math.radians(ellipse.start_angle_deg + ellipse.sweep_angle_deg)
        start, end = (first, last) if ellipse.sweep_angle_deg > 0 else (last, first)
        start, end = start % math.tau, end % math.tau
    return DxfEllipseParameters(
        (ellipse.center_mm[0], ellipse.center_mm[1], 0.0),
        major_axis,
        ellipse.minor_radius_mm / ellipse.major_radius_mm,
        start,
        end,
    )


def ellipse_from_dxf(
    entity_id: str,
    center: tuple[float, ...],
    major_axis: tuple[float, ...],
    ratio: float,
    start_param: float,
    end_param: float,
    *,
    clockwise: bool = False,
    full_start_deg: float | None = None,
    normal: tuple[float, ...] = (0.0, 0.0, 1.0),
    construction: bool = False,
    layer_name: str = "0",
    strict_sweep: bool = False,
) -> EllipseEntity:
    """Convert a world-XY DXF ellipse; direction and full seam come from metadata."""
    if len(center) != 3 or len(major_axis) != 3 or len(normal) != 3:
        raise ValueError("DXF 椭圆坐标必须是三维坐标。")
    if not all(
        math.isfinite(value)
        for value in (*center, *major_axis, *normal, ratio, start_param, end_param)
    ):
        raise ValueError("DXF 椭圆参数必须有限。")
    if abs(normal[0]) > 1e-9 or abs(normal[1]) > 1e-9 or abs(normal[2] - 1) > 1e-9:
        raise ValueError("只支持全局 XY 平面的正向椭圆法向。")
    if abs(center[2]) > 1e-7 or abs(major_axis[2]) > 1e-7:
        raise ValueError("只支持位于全局 XY 平面的椭圆。")
    major = math.hypot(major_axis[0], major_axis[1])
    if major <= 1e-10 or not 0 < ratio <= 1:
        raise ValueError("DXF 椭圆主轴或轴比无效。")
    raw_sweep = end_param - start_param
    full = (
        raw_sweep != 0
        and (
            abs(raw_sweep) == math.tau
            or end_param == start_param + math.tau
            or start_param == end_param + math.tau
        )
        if strict_sweep
        else abs(abs(raw_sweep) - math.tau) <= 1e-9
    )
    if abs(raw_sweep) > (math.tau if strict_sweep else math.tau + 1e-9) and not full:
        raise ValueError("DXF 椭圆参数范围无效。")
    if full:
        start = full_start_deg if full_start_deg is not None else math.degrees(start_param)
        sweep = -360.0 if clockwise else 360.0
    else:
        extent = raw_sweep % math.tau
        if extent <= (0.0 if strict_sweep else 1e-10):
            raise ValueError("DXF 椭圆弧参数范围为空。")
        start = math.degrees(end_param if clockwise else start_param)
        sweep = math.degrees(-extent if clockwise else extent)
        if strict_sweep and abs(sweep) >= 360:
            raise ValueError("椭圆弧角度无法精确保留。")
    return EllipseEntity(
        entity_id,
        (center[0], center[1]),
        major,
        major * ratio,
        math.degrees(math.atan2(major_axis[1], major_axis[0])),
        start,
        sweep,
        construction,
        layer_name,
    )
