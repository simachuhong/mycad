# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Resolve stable point references against current neutral sketch geometry."""

import math
from collections.abc import Mapping

from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    Point2D,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    SketchEntity,
    SplineEntity,
)
from mycad.core.sketch_constraints import SketchGeometryReference


def resolve_point_reference(
    reference: SketchGeometryReference, entities: Mapping[str, SketchEntity]
) -> Point2D | None:
    """Resolve a point against its current entity, or return None for invalid references."""
    entity = entities.get(reference.entity_id)
    if entity is None:
        return None
    if isinstance(entity, PointEntity):
        return entity.position_mm if reference.kind == "vertex" and reference.index == 0 else None
    if isinstance(entity, SplineEntity):
        if reference.kind == "start":
            return entity.control_points_mm[0]
        if reference.kind == "end":
            return entity.control_points_mm[-1]
        if reference.kind == "vertex" and reference.index is not None:
            return (
                entity.control_points_mm[reference.index]
                if reference.index < len(entity.control_points_mm)
                else None
            )
    elif isinstance(entity, LineEntity):
        if reference.kind == "start":
            return entity.start_mm
        if reference.kind == "end":
            return entity.end_mm
    elif isinstance(entity, PolylineEntity):
        if reference.kind == "start":
            return entity.points_mm[0]
        if reference.kind == "end":
            return entity.points_mm[-1]
        if reference.kind == "vertex" and reference.index is not None:
            return (
                entity.points_mm[reference.index]
                if reference.index < len(entity.points_mm)
                else None
            )
    elif isinstance(entity, RectangleEntity):
        first_u, first_v = entity.first_corner_mm
        opposite_u, opposite_v = entity.opposite_corner_mm
        corners = (
            (first_u, first_v),
            (opposite_u, first_v),
            (opposite_u, opposite_v),
            (first_u, opposite_v),
        )
        if reference.kind == "vertex" and reference.index is not None:
            return corners[reference.index] if reference.index < len(corners) else None
    elif isinstance(entity, CircleEntity) and reference.kind == "center":
        return entity.center_mm
    elif isinstance(entity, ArcEntity):
        if reference.kind == "center":
            return entity.center_mm
        if reference.kind in ("start", "end"):
            angle = entity.start_angle_deg + (
                entity.sweep_angle_deg if reference.kind == "end" else 0.0
            )
            radians = math.radians(angle)
            return (
                entity.center_mm[0] + entity.radius_mm * math.cos(radians),
                entity.center_mm[1] + entity.radius_mm * math.sin(radians),
            )
    return None
