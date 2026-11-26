# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Project persistent drawing annotations into a coplanar canvas."""

from __future__ import annotations

import math
from dataclasses import replace

from mycad.core.cross_sketch_tangency import project_coplanar_vector
from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, SurfaceIndication
from mycad.core.sketch import Point2D, WorkPlaneFrame


def project_surface(
    surface: SurfaceIndication | None, source: WorkPlaneFrame, target: WorkPlaneFrame
) -> SurfaceIndication | None:
    if surface is None:
        return None
    return replace(
        surface,
        reference_start_offset_mm=project_coplanar_vector(
            surface.reference_start_offset_mm, source, target
        ),
        reference_end_offset_mm=project_coplanar_vector(
            surface.reference_end_offset_mm, source, target
        ),
        leader_offsets_mm=tuple(
            project_coplanar_vector(value, source, target) for value in surface.leader_offsets_mm
        ),
    )


def project_annotation(
    item: FeatureControlFrame | DatumIdentifier,
    source: WorkPlaneFrame,
    target: WorkPlaneFrame,
    delta: Point2D = (0, 0),
) -> FeatureControlFrame | DatumIdentifier:
    """Return a display-only annotation without modifying durable identities."""

    def point(value: Point2D) -> Point2D:
        x, y = target.world_to_local(source.local_to_world(value))
        return x + delta[0], y + delta[1]

    def vector(value: Point2D) -> Point2D:
        return project_coplanar_vector(value, source, target)

    project_coplanar_vector((0, 0), source, target)
    projected_surface = project_surface(item.surface_indication, source, target)
    if isinstance(item, FeatureControlFrame):
        angle = math.radians(item.rotation_deg)
        direction = vector((math.cos(angle), math.sin(angle)))
        return replace(
            item,
            position_mm=point(item.position_mm),
            rotation_deg=math.degrees(math.atan2(direction[1], direction[0])),
            leader_target_mm=point(item.leader_target_mm)
            if item.leader_target_mm is not None
            else None,
            leader_offsets=tuple(vector(value) for value in item.leader_offsets),
            leader_anchor_offset=vector(item.leader_anchor_offset)
            if item.leader_anchor_offset is not None
            else None,
            surface_indication=projected_surface,
        )
    return replace(
        item,
        position_mm=point(item.position_mm),
        target_mm=point(item.target_mm),
        bar_direction=vector(item.bar_direction) if item.bar_direction is not None else None,
        leader_offsets=tuple(vector(value) for value in item.leader_offsets),
        surface_indication=projected_surface,
    )
