# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Circular detail regions and exact clipping of lines and circular arcs."""

from __future__ import annotations

from dataclasses import dataclass
from math import acos, atan2, cos, degrees, dist, isfinite, radians, sin, sqrt
from typing import TYPE_CHECKING
from uuid import UUID

from mycad.core.drawing_projection import (
    ArcCurve,
    CurveGeometry,
    EllipseCurve,
    LineCurve,
    Point2,
    ProjectedCurve,
    ProjectionResult,
    SplineCurve,
    finite,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class DetailRegion:
    center: Point2
    radius: float

    def __post_init__(self) -> None:
        finite((*self.center, self.radius), "detail region")
        if self.radius <= 0:
            raise ValueError("detail radius must be positive")


def clip_detail(curve: CurveGeometry, region: DetailRegion) -> tuple[CurveGeometry, ...]:
    """Return exact visible pieces; unsupported curves fail rather than disappear."""
    if isinstance(curve, LineCurve):
        return _clip_line(curve, region)
    if isinstance(curve, ArcCurve):
        return _clip_arc(curve, region)
    if isinstance(curve, EllipseCurve):
        gap = dist(curve.center, region.center)
        if not isfinite(gap):
            raise ValueError("detail clipping coordinates exceed numerical range")
        if gap + curve.major_radius <= region.radius:
            return (curve,)
        if gap - curve.major_radius >= region.radius:
            return ()
    if isinstance(curve, SplineCurve):
        if all(dist(point, region.center) <= region.radius for point in curve.poles):
            return (curve,)
        xs, ys = [point[0] for point in curve.poles], [point[1] for point in curve.poles]
        nearest = (
            max(min(xs), min(region.center[0], max(xs))),
            max(min(ys), min(region.center[1], max(ys))),
        )
        if dist(nearest, region.center) >= region.radius:
            return ()
    raise ValueError(
        "detail boundary intersects an ellipse or spline; clipping is not yet supported"
    )


def clip_detail_projection(
    parent: ProjectionResult,
    region: DetailRegion,
    view_id: UUID,
    generation: int,
    *,
    clipper: Callable[[CurveGeometry, DetailRegion], tuple[CurveGeometry, ...]] | None = None,
) -> ProjectionResult:
    """Crop the parent result and center its coordinates on the detail region."""
    if parent.diagnostics:
        raise ValueError("detail requires an error-free parent projection")
    if parent.hatch:
        raise ValueError("details of section views are not yet supported")
    if generation < 0:
        raise ValueError("detail generation must be nonnegative")
    curves: list[ProjectedCurve] = []
    for original in parent.curves:
        for piece in (clipper or clip_detail)(original.geometry, region):
            if isinstance(piece, LineCurve):
                geometry: CurveGeometry = LineCurve(
                    (piece.start[0] - region.center[0], piece.start[1] - region.center[1]),
                    (piece.end[0] - region.center[0], piece.end[1] - region.center[1]),
                )
            elif isinstance(piece, ArcCurve):
                geometry = ArcCurve(
                    (piece.center[0] - region.center[0], piece.center[1] - region.center[1]),
                    piece.radius,
                    piece.start_deg,
                    piece.sweep_deg,
                )
            elif isinstance(piece, EllipseCurve):
                geometry = EllipseCurve(
                    (piece.center[0] - region.center[0], piece.center[1] - region.center[1]),
                    piece.major_radius,
                    piece.minor_radius,
                    piece.rotation_deg,
                    piece.start_deg,
                    piece.sweep_deg,
                )
            else:
                geometry = SplineCurve(
                    tuple((x - region.center[0], y - region.center[1]) for x, y in piece.poles),
                    piece.degree,
                    piece.knots,
                    piece.multiplicities,
                    piece.weights,
                    piece.periodic,
                )
            curves.append(
                ProjectedCurve(
                    f"detail-{len(curves)}",
                    geometry,
                    original.visibility,
                    original.source if piece == original.geometry else None,
                    original.silhouette,
                    original.source_count,
                )
            )
    if not curves:
        raise ValueError("所选范围内没有可显示的投影几何")
    return ProjectionResult(view_id, parent.source_fingerprint, generation, tuple(curves))


def _clip_line(line: LineCurve, region: DetailRegion) -> tuple[LineCurve, ...]:
    # The disk is convex, so a segment with both endpoints inside is unchanged.
    # Returning the original geometry also retains its associative source reference.
    if (
        dist(line.start, region.center) <= region.radius
        and dist(line.end, region.center) <= region.radius
    ):
        return (line,)
    x, y = line.start[0] - region.center[0], line.start[1] - region.center[1]
    dx, dy = line.end[0] - line.start[0], line.end[1] - line.start[1]
    a = dx * dx + dy * dy
    b = 2 * (x * dx + y * dy)
    c = x * x + y * y - region.radius * region.radius
    discriminant = b * b - 4 * a * c
    if not all(isfinite(value) for value in (a, b, c, discriminant)):
        raise ValueError("detail clipping coordinates exceed numerical range")
    cuts = [0.0, 1.0]
    if discriminant >= 0:
        root = sqrt(discriminant)
        cuts.extend(t for t in ((-b - root) / (2 * a), (-b + root) / (2 * a)) if 0 < t < 1)
    cuts = sorted(set(cuts))
    pieces: list[LineCurve] = []
    for start, end in zip(cuts, cuts[1:], strict=False):
        middle = (start + end) / 2
        if dist((x + middle * dx, y + middle * dy), (0, 0)) < region.radius:
            p0 = (line.start[0] + start * dx, line.start[1] + start * dy)
            p1 = (line.start[0] + end * dx, line.start[1] + end * dy)
            if dist(p0, p1) >= 1e-12:
                pieces.append(LineCurve(p0, p1))
    return tuple(pieces)


def _clip_arc(arc: ArcCurve, region: DetailRegion) -> tuple[ArcCurve, ...]:
    dx, dy = region.center[0] - arc.center[0], region.center[1] - arc.center[1]
    distance = dist(region.center, arc.center)
    if not isfinite(distance):
        raise ValueError("detail clipping coordinates exceed numerical range")
    scale = max(arc.radius, distance, region.radius)
    radius, gap, limit = arc.radius / scale, distance / scale, region.radius / scale
    if gap + radius <= limit:
        return (arc,)
    if gap >= radius + limit or gap + limit <= radius:
        return ()
    cuts = [0.0, 1.0]
    if distance > 0:
        denominator = 2 * radius * gap
        if denominator == 0:
            raise ValueError("detail clipping coordinates exceed numerical range")
        cosine = (radius * radius + gap * gap - limit * limit) / denominator
        if not isfinite(cosine):
            raise ValueError("detail clipping coordinates exceed numerical range")
        cosine = max(-1.0, min(1.0, cosine))
        if -1 <= cosine <= 1:
            angle = degrees(atan2(dy, dx))
            delta = degrees(acos(cosine))
            for boundary in (angle - delta, angle + delta):
                travel = (
                    (boundary - arc.start_deg) % 360
                    if arc.sweep_deg > 0
                    else (arc.start_deg - boundary) % 360
                )
                parameter = travel / abs(arc.sweep_deg)
                if 0 < parameter < 1:
                    cuts.append(parameter)
    cuts = sorted(set(cuts))
    pieces: list[ArcCurve] = []
    for start, end in zip(cuts, cuts[1:], strict=False):
        middle = radians(arc.start_deg + (start + end) / 2 * arc.sweep_deg)
        point = (
            arc.center[0] + arc.radius * cos(middle),
            arc.center[1] + arc.radius * sin(middle),
        )
        if dist(point, region.center) < region.radius and end - start > 1e-12:
            pieces.append(
                ArcCurve(
                    arc.center,
                    arc.radius,
                    arc.start_deg + start * arc.sweep_deg,
                    (end - start) * arc.sweep_deg,
                )
            )
    return tuple(pieces)
