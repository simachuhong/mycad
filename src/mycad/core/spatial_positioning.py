# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Backend-neutral ray and explicit workplane positioning."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from mycad.core.sketch import Point2D, Point3D, WorkPlaneFrame


@dataclass(frozen=True, slots=True)
class PositionResult:
    """One value-only position in a locked workplane."""

    uv: Point2D
    world: Point3D
    source: Literal["numeric", "grid", "free"]


@dataclass(frozen=True, slots=True)
class ProjectedAnchor:
    """Exact world anchor and its screen position from one interaction scene."""

    kind: Literal["origin", "vertex", "center", "midpoint"]
    key: str
    world: Point3D
    screen: Point2D


@dataclass(frozen=True, slots=True)
class ObjectSnap:
    anchor: ProjectedAnchor
    world: Point3D
    uv: Point2D
    projected: bool


def choose_object_snap(
    anchors: Sequence[ProjectedAnchor],
    pointer: Point2D,
    plane: WorkPlaneFrame,
    *,
    allow_projection: bool = False,
    radius_px: float = 12.0,
    plane_tolerance_mm: float = 1e-6,
) -> ObjectSnap | None:
    """Select a nearby exact anchor; off-plane points require explicit projection."""
    options = object_snap_candidates(
        anchors,
        pointer,
        plane,
        allow_projection=allow_projection,
        radius_px=radius_px,
        plane_tolerance_mm=plane_tolerance_mm,
    )
    return options[0] if options else None


def object_snap_candidates(
    anchors: Sequence[ProjectedAnchor],
    pointer: Point2D,
    plane: WorkPlaneFrame,
    *,
    allow_projection: bool = False,
    radius_px: float = 12.0,
    plane_tolerance_mm: float = 1e-6,
) -> tuple[ObjectSnap, ...]:
    """Return all eligible anchors in deterministic screen-distance order."""
    if (
        radius_px <= 0
        or plane_tolerance_mm < 0
        or not all(math.isfinite(value) for value in (*pointer, radius_px, plane_tolerance_mm))
    ):
        raise ValueError("invalid snap tolerances or pointer")
    priority = {"origin": 0, "vertex": 0, "center": 1, "midpoint": 2}
    options: list[tuple[float, int, str, ObjectSnap]] = []
    for anchor in anchors:
        if anchor.kind not in priority or not anchor.key:
            raise ValueError("invalid snap anchor")
        if not all(math.isfinite(value) for value in (*anchor.world, *anchor.screen)):
            raise ValueError("snap anchor must be finite")
        distance = math.dist(pointer, anchor.screen)
        if distance > radius_px:
            continue
        delta = tuple(anchor.world[i] - plane.origin_mm[i] for i in range(3))
        height = sum(delta[i] * plane.normal[i] for i in range(3))
        projected = abs(height) > plane_tolerance_mm
        if projected and not allow_projection:
            continue
        uv = plane.world_to_local(anchor.world)
        world = plane.local_to_world(uv)
        match = ObjectSnap(anchor, world, uv, projected)
        options.append((distance, priority[anchor.kind], anchor.key, match))
    return tuple(item[3] for item in sorted(options, key=lambda item: item[:3]))


def intersect_plane(origin: Point3D, direction: Point3D, plane: WorkPlaneFrame) -> Point3D | None:
    """Intersect a forward ray with a plane; reject degenerate or parallel rays."""
    if any(not math.isfinite(value) for value in (*origin, *direction)):
        return None
    length = math.hypot(*direction)
    if length == 0.0 or not math.isfinite(length):
        return None
    unit = tuple(value / length for value in direction)
    denominator = sum(unit[i] * plane.normal[i] for i in range(3))
    if abs(denominator) <= 1e-9:
        return None
    distance = sum((plane.origin_mm[i] - origin[i]) * plane.normal[i] for i in range(3))
    distance /= denominator
    if distance < 0.0 or not math.isfinite(distance):
        return None
    point = tuple(origin[i] + distance * unit[i] for i in range(3))
    if any(not math.isfinite(value) for value in point):
        return None
    return (point[0], point[1], point[2])


def locate_uv(
    uv: Point2D,
    plane: WorkPlaneFrame,
    *,
    numeric: bool,
    grid_enabled: bool,
    spacing: float,
) -> PositionResult:
    """Apply grid to pointer values only; typed numeric values remain exact."""
    if any(not math.isfinite(value) for value in uv):
        raise ValueError("position must be finite")
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError("grid spacing must be positive and finite")
    if numeric:
        return PositionResult(uv, plane.local_to_world(uv), "numeric")
    if grid_enabled:

        def nearest(value: float) -> float:
            scaled = value / spacing
            rounded = math.floor(scaled + 0.5) if scaled >= 0 else math.ceil(scaled - 0.5)
            return rounded * spacing

        uv = (nearest(uv[0]), nearest(uv[1]))
        return PositionResult(uv, plane.local_to_world(uv), "grid")
    return PositionResult(uv, plane.local_to_world(uv), "free")
