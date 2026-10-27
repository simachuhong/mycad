# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Rational curves to vector cubics with a Bernstein coefficient error bound.

For a homogeneous Bezier P/W and a cubic Q, the convex-hull bound on
P-QW divided by min(W) bounds the Euclidean error over the whole interval.
Subdivision tightens that bound; no point sampling is used as a proof.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mycad.core.drawing_projection import (
    ArcCurve,
    CurveGeometry,
    EllipseCurve,
    LineCurve,
    Point2,
    SplineCurve,
)

Homogeneous = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class CubicBezier:
    start: Point2
    control1: Point2
    control2: Point2
    end: Point2
    parameter_range: tuple[float, float] = (0, 1)

    def point(self, t: float) -> Point2:
        weights = ((1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t**3)
        points = (self.start, self.control1, self.control2, self.end)
        return (
            sum(w * p[0] for w, p in zip(weights, points, strict=True)),
            sum(w * p[1] for w, p in zip(weights, points, strict=True)),
        )


def _mix(a: Homogeneous, b: Homogeneous, t: float) -> Homogeneous:
    return ((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1], (1 - t) * a[2] + t * b[2])


def _fit(points: tuple[Homogeneous, ...], interval: tuple[float, float]) -> CubicBezier:
    p = len(points) - 1
    a, b = points[0], points[-1]
    start, end = (a[0] / a[2], a[1] / a[2]), (b[0] / b[2], b[1] / b[2])
    left, right = points[1], points[-2]
    c1 = tuple(start[i] + p * left[2] / a[2] * (left[i] / left[2] - start[i]) / 3 for i in range(2))
    c2 = tuple(end[i] - p * right[2] / b[2] * (end[i] - right[i] / right[2]) / 3 for i in range(2))
    return CubicBezier(start, (c1[0], c1[1]), (c2[0], c2[1]), end, interval)


def _bound(points: tuple[Homogeneous, ...], cubic: CubicBezier) -> float:
    p = len(points) - 1
    q = (cubic.start, cubic.control1, cubic.control2, cubic.end)
    maximum = 0.0
    for k in range(p + 4):
        dx = dy = 0.0
        denominator = math.comb(p + 3, k)
        for i in range(max(0, k - p), min(3, k) + 1):
            j = k - i
            factor = math.comb(3, i) * math.comb(p, j) / denominator
            dx += factor * (points[j][0] - q[i][0] * points[j][2])
            dy += factor * (points[j][1] - q[i][1] * points[j][2])
        maximum = max(maximum, math.hypot(dx, dy))
    return maximum / min(point[2] for point in points)


def _approximate(
    points: tuple[Homogeneous, ...], interval: tuple[float, float], tolerance: float, depth: int = 0
) -> tuple[CubicBezier, ...]:
    cubic = _fit(points, interval)
    if _bound(points, cubic) <= tolerance:
        return (cubic,)
    if depth >= 24:
        raise ValueError("曲线在规定细分深度内未达到纸上精度，不能出图")
    rows = [points]
    while len(rows[-1]) > 1:
        rows.append(tuple(_mix(a, b, 0.5) for a, b in zip(rows[-1], rows[-1][1:], strict=False)))
    left = tuple(row[0] for row in rows)
    right = tuple(row[-1] for row in reversed(rows))
    mid = (interval[0] + interval[1]) / 2
    return (
        *_approximate(left, (interval[0], mid), tolerance, depth + 1),
        *_approximate(right, (mid, interval[1]), tolerance, depth + 1),
    )


def _spline_spans(
    curve: SplineCurve,
) -> tuple[tuple[tuple[Homogeneous, ...], tuple[float, float]], ...]:
    p = curve.degree
    if curve.periodic or curve.multiplicities[0] != p + 1 or curve.multiplicities[-1] != p + 1:
        raise ValueError("周期或未夹持样条需要先规范化为非周期精确曲线")
    controls = [
        (point[0] * weight, point[1] * weight, weight)
        for point, weight in zip(curve.poles, curve.weights, strict=True)
    ]
    knots = [
        k for k, count in zip(curve.knots, curve.multiplicities, strict=True) for _ in range(count)
    ]
    # Insert interior knots until each nonzero span is a rational Bezier.
    for value, count in zip(curve.knots[1:-1], curve.multiplicities[1:-1], strict=True):
        for multiplicity in range(count, p):
            span = max(i for i, knot in enumerate(knots) if knot <= value)
            inserted: list[Homogeneous] = [(0, 0, 1)] * (len(controls) + 1)
            for i in range(span - p + 1):
                inserted[i] = controls[i]
            for i in range(span - multiplicity, len(controls)):
                inserted[i + 1] = controls[i]
            for i in range(span - p + 1, span - multiplicity + 1):
                alpha = (value - knots[i]) / (knots[i + p] - knots[i])
                inserted[i] = _mix(controls[i - 1], controls[i], alpha)
            controls = inserted
            knots.insert(span + 1, value)
    return tuple(
        (tuple(controls[i - p : i + 1]), (knots[i], knots[i + 1]))
        for i in range(p, len(controls))
        if knots[i + 1] > knots[i]
    )


def cubic_segments(curve: CurveGeometry, *, tolerance: float = 0.01) -> tuple[CubicBezier, ...]:
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("纸上曲线误差必须为有限正数")
    if isinstance(curve, LineCurve):
        return (
            _fit(((curve.start[0], curve.start[1], 1), (curve.end[0], curve.end[1], 1)), (0, 1)),
        )
    if isinstance(curve, SplineCurve):
        return tuple(
            cubic
            for points, interval in _spline_spans(curve)
            for cubic in _approximate(points, interval, tolerance)
        )
    rx = curve.radius if isinstance(curve, ArcCurve) else curve.major_radius
    ry = curve.radius if isinstance(curve, ArcCurve) else curve.minor_radius
    rotation = math.radians(curve.rotation_deg) if isinstance(curve, EllipseCurve) else 0
    count = max(1, math.ceil(abs(curve.sweep_deg) / 90))
    step = math.radians(curve.sweep_deg) / count
    start = math.radians(curve.start_deg)
    result: list[CubicBezier] = []

    def homogeneous(angle: float, weight: float) -> Homogeneous:
        x, y = rx * math.cos(angle), ry * math.sin(angle)
        return (
            curve.center[0] * weight + x * math.cos(rotation) - y * math.sin(rotation),
            curve.center[1] * weight + x * math.sin(rotation) + y * math.cos(rotation),
            weight,
        )

    for i in range(count):
        a = start + i * step
        points = (
            homogeneous(a, 1),
            homogeneous(a + step / 2, math.cos(step / 2)),
            homogeneous(a + step, 1),
        )
        result.extend(_approximate(points, (float(i), float(i + 1)), tolerance))
    return tuple(result)
