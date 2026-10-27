# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Measured annotations and paper geometry shared by canvas, DXF and PDF."""

from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from mycad.core.drawing import DrawingAnnotation
from mycad.core.drawing_projection import (
    ArcCurve,
    CurveGeometry,
    LineCurve,
    Point2,
    ProjectionResult,
    SceneView,
)
from mycad.core.drawing_references import ReferenceStatus, resolve_reference


@dataclass(frozen=True, slots=True)
class SceneAnnotation:
    annotation_id: UUID
    view_id: UUID
    kind: str
    position_mm: Point2
    text: str
    value: float | None
    anchors: tuple[Point2, ...] = ()
    curves: tuple[CurveGeometry, ...] = ()
    status: ReferenceStatus = "resolved"
    message: str = ""


def _point(curve: CurveGeometry, role: str) -> Point2:
    if isinstance(curve, LineCurve):
        start, end = sorted((curve.start, curve.end))
        if role == "start":
            return start
        if role == "end":
            return end
        return ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    if isinstance(curve, ArcCurve):
        return curve.center
    raise ValueError("此标注需要直线端点或真实圆心")


def _arrow(point: Point2, toward: Point2) -> tuple[LineCurve, ...]:
    dx, dy = toward[0] - point[0], toward[1] - point[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return ()
    ux, uy = dx / length, dy / length
    return tuple(
        LineCurve(
            point, (point[0] + 2.5 * ux - sign * 0.8 * uy, point[1] + 2.5 * uy + sign * 0.8 * ux)
        )
        for sign in (-1, 1)
    )


def resolve_annotation(
    annotation: DrawingAnnotation, projection: ProjectionResult, view: SceneView
) -> SceneAnnotation:
    def failed(message: str, status: ReferenceStatus = "orphaned") -> SceneAnnotation:
        return SceneAnnotation(
            annotation.annotation_id,
            annotation.view_id,
            annotation.kind,
            annotation.position_mm,
            "⚠ 失关联" if status == "orphaned" else "⚠ 多候选",
            None,
            status=status,
            message=message,
        )

    selected: list[CurveGeometry] = []
    for reference in annotation.references:
        resolution = resolve_reference(reference, projection)
        if resolution.status != "resolved":
            return failed(resolution.message, resolution.status)
        selected.append(
            next(c.geometry for c in projection.curves if c.curve_id == resolution.curve_ids[0])
        )
    try:
        return _layout(annotation, selected, view)
    except ValueError as error:
        return failed(str(error))


def _layout(
    annotation: DrawingAnnotation, selected: list[CurveGeometry], view: SceneView
) -> SceneAnnotation:
    kind = annotation.kind
    position = annotation.position_mm
    lines: list[CurveGeometry] = []
    anchors: tuple[Point2, ...]
    value: float | None = None
    symbol = ""
    suffix = annotation.suffix
    if kind in ("horizontal", "vertical", "aligned"):
        if len(selected) != 2:
            raise ValueError("线性标注需要两个关联点")
        points = tuple(
            _point(c, r.role) for c, r in zip(selected, annotation.references, strict=True)
        )
        a, b = (view.to_paper(point) for point in points)
        anchors = (a, b)
        if kind == "horizontal":
            value = abs(points[1][0] - points[0][0])
            x, y = (a[0], position[1]), (b[0], position[1])
        elif kind == "vertical":
            value = abs(points[1][1] - points[0][1])
            x, y = (position[0], a[1]), (position[0], b[1])
        else:
            value = math.dist(*points)
            distance = math.dist(a, b)
            if distance <= 1e-9:
                raise ValueError("不能标注重合点")
            normal = (-(b[1] - a[1]) / distance, (b[0] - a[0]) / distance)
            offset = (position[0] - a[0]) * normal[0] + (position[1] - a[1]) * normal[1]
            x = (a[0] + offset * normal[0], a[1] + offset * normal[1])
            y = (b[0] + offset * normal[0], b[1] + offset * normal[1])
        if value <= 1e-9:
            raise ValueError("不能标注零投影长度")
        lines.extend(
            (LineCurve(a, x), LineCurve(b, y), LineCurve(x, y), *_arrow(x, y), *_arrow(y, x))
        )
    elif kind in ("radius", "diameter", "center"):
        if len(selected) != 1:
            raise ValueError("此标注需要一个圆或一条中心线")
        geometry = selected[0]
        if kind == "center" and isinstance(geometry, LineCurve):
            a, b = view.to_paper(geometry.start), view.to_paper(geometry.end)
            anchors = (a, b)
            lines.append(LineCurve(a, b))
        else:
            if not isinstance(geometry, ArcCurve):
                raise ValueError("半径、直径和圆心标记需要真实圆/圆弧，椭圆不能作为圆标注")
            center = view.to_paper(geometry.center)
            anchors = (center,)
            radius = geometry.radius * view.scale
            if kind == "center":
                extent = radius + 3
                lines.extend(
                    (
                        LineCurve((center[0] - extent, center[1]), (center[0] + extent, center[1])),
                        LineCurve((center[0], center[1] - extent), (center[0], center[1] + extent)),
                    )
                )
            else:
                value = geometry.radius * (2 if kind == "diameter" else 1)
                symbol = "⌀" if kind == "diameter" else "R"
                angle_deg = math.degrees(
                    math.atan2(position[1] - center[1], position[0] - center[0])
                )
                sign = 1 if geometry.sweep_deg > 0 else -1
                offset = ((angle_deg - geometry.start_deg) * sign) % 360
                if offset > abs(geometry.sweep_deg):
                    endpoints = (geometry.start_deg, geometry.start_deg + geometry.sweep_deg)
                    angle_deg = min(
                        endpoints, key=lambda value: abs((value - angle_deg + 180) % 360 - 180)
                    )
                angle = math.radians(angle_deg)
                rim = (center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle))
                lines.extend(
                    (LineCurve(center, rim), LineCurve(rim, position), *_arrow(rim, center))
                )
    else:
        if len(selected) != 2 or not all(isinstance(c, LineCurve) for c in selected):
            raise ValueError("角度标注需要两条直线")
        first, second = selected
        assert isinstance(first, LineCurve) and isinstance(second, LineCurve)
        u = (first.end[0] - first.start[0], first.end[1] - first.start[1])
        v = (second.end[0] - second.start[0], second.end[1] - second.start[1])
        det = u[0] * v[1] - u[1] * v[0]
        if abs(det) < 1e-9:
            raise ValueError("平行直线不能生成角度圆弧")
        delta = (second.start[0] - first.start[0], second.start[1] - first.start[1])
        t = (delta[0] * v[1] - delta[1] * v[0]) / det
        center = view.to_paper((first.start[0] + t * u[0], first.start[1] + t * u[1]))
        start = math.degrees(math.atan2(u[1], u[0])) % 180
        end = math.degrees(math.atan2(v[1], v[0])) % 180
        rays = sorted((start, end, start + 180, end + 180))
        theta = math.degrees(math.atan2(position[1] - center[1], position[0] - center[0])) % 360
        sectors = tuple(zip(rays, (*rays[1:], rays[0] + 360), strict=True))
        start, end = next((a, b) for a, b in sectors if (theta - a) % 360 <= b - a + 1e-9)
        value = end - start
        radius = math.dist(position, center)
        if radius <= 1e-9:
            raise ValueError("请将角度文字放在交点之外")
        a = (
            center[0] + radius * math.cos(math.radians(start)),
            center[1] + radius * math.sin(math.radians(start)),
        )
        b = (
            center[0] + radius * math.cos(math.radians(end)),
            center[1] + radius * math.sin(math.radians(end)),
        )
        anchors = (center,)
        lines.extend(
            (
                ArcCurve(center, radius, start, value),
                LineCurve(center, a),
                LineCurve(center, b),
                *_arrow(a, b),
                *_arrow(b, a),
            )
        )
        suffix = "°" if suffix == " mm" else suffix
    text = (
        ""
        if value is None
        else f"{annotation.prefix}{symbol}{value:.{annotation.precision}f}{suffix}"
    )
    return SceneAnnotation(
        annotation.annotation_id,
        annotation.view_id,
        kind,
        position,
        text,
        value,
        anchors,
        tuple(lines),
    )
