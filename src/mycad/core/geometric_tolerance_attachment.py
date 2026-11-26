# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Resolve stable datum attachments without a CAD or UI backend."""

from __future__ import annotations

import math
from collections.abc import Mapping

from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, FeatureControlFrame
from mycad.core.geometric_tolerance_surface_extension import surface_extension_geometry
from mycad.core.polyline_curves import polyline_curve_segments
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    EllipseEntity,
    LineEntity,
    Point2D,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
    SplineEntity,
)
from mycad.core.sketch_references import resolve_point_reference


def resolve_datum_bar_direction(
    datum: DatumIdentifier,
    sketches: Mapping[str, Sketch],
    frames: Mapping[str, FeatureControlFrame] | None = None,
) -> Point2D | None:
    """Prefer the attached baseline tangent; retain the last known direction if lost."""
    if datum.attachment is not None:
        sketch = sketches.get(datum.attachment.sketch_id)
        if sketch is not None:
            normal = resolve_attachment_normal(
                datum.attachment, sketch, datum.target_mm, enable_spline=True
            )
            if normal is not None:
                return normal[1], -normal[0]
    reference = datum.annotation_attachment
    if reference is not None and reference.kind == "frame" and frames is not None:
        frame = frames.get(reference.object_id)
        if frame is not None:
            angle = math.radians(frame.rotation_deg)
            return math.cos(angle), math.sin(angle)
    return datum.bar_direction


def _spline_tangent(spline: SplineEntity, parameter: float) -> Point2D:
    knots = spline.knots
    points = spline.control_points_mm
    controls = tuple(
        (
            3 * (points[i + 1][0] - points[i][0]) / (knots[i + 4] - knots[i + 1]),
            3 * (points[i + 1][1] - points[i][1]) / (knots[i + 4] - knots[i + 1]),
        )
        for i in range(len(points) - 1)
    )
    reduced = knots[1:-1]
    if parameter == 1.0:
        return controls[-1]
    span = next(i for i in range(2, len(controls)) if reduced[i] <= parameter < reduced[i + 1])
    work = list(controls[span - 2 : span + 1])
    for level in range(1, 3):
        for index in range(2, level - 1, -1):
            knot_index = span - 2 + index
            alpha = (parameter - reduced[knot_index]) / (
                reduced[knot_index + 3 - level] - reduced[knot_index]
            )
            left, right = work[index - 1], work[index]
            work[index] = (
                (1 - alpha) * left[0] + alpha * right[0],
                (1 - alpha) * left[1] + alpha * right[1],
            )
    return work[2]


def resolve_attachment_normal(
    attachment: DatumAttachment, sketch: Sketch, target: Point2D, *, enable_spline: bool = False
) -> Point2D | None:
    """Return the world-plane normal where a stable attachment has a unique tangent."""
    if sketch.sketch_id != attachment.sketch_id:
        return None
    entity = next(
        (item for item in sketch.entities if item.entity_id == attachment.reference.entity_id), None
    )
    if isinstance(entity, RectangleEntity) and attachment.reference.kind == "segment":
        index = attachment.reference.index
        if index is None or index >= 4:
            return None
        x1, y1 = entity.first_corner_mm
        x2, y2 = entity.opposite_corner_mm
        corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        entity = LineEntity(entity.entity_id, corners[index], corners[(index + 1) % 4])
    elif isinstance(entity, PolylineEntity) and attachment.reference.kind == "segment":
        index = attachment.reference.index
        count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
        segments = polyline_curve_segments(
            entity.points_mm, entity.bulges or (0.0,) * count, entity.closed, entity.entity_id
        )
        if index is None or index >= len(segments):
            return None
        entity = segments[index]
    if isinstance(entity, LineEntity):
        dx = entity.end_mm[0] - entity.start_mm[0]
        dy = entity.end_mm[1] - entity.start_mm[1]
        tangent_x = dx * sketch.frame.u_axis[0] + dy * sketch.frame.v_axis[0]
        tangent_y = dx * sketch.frame.u_axis[1] + dy * sketch.frame.v_axis[1]
        length = math.hypot(tangent_x, tangent_y)
        return (-tangent_y / length, tangent_x / length) if length > 1e-12 else None
    if (
        isinstance(entity, EllipseEntity)
        and attachment.curve_kind == "ellipse"
        and attachment.parameter is not None
    ):
        angle = math.radians(entity.start_angle_deg + entity.sweep_angle_deg * attachment.parameter)
        rotation = math.radians(entity.rotation_deg)
        dx = -entity.major_radius_mm * math.sin(angle)
        dy = entity.minor_radius_mm * math.cos(angle)
        tangent_u = dx * math.cos(rotation) - dy * math.sin(rotation)
        tangent_v = dx * math.sin(rotation) + dy * math.cos(rotation)
        tangent_x = tangent_u * sketch.frame.u_axis[0] + tangent_v * sketch.frame.v_axis[0]
        tangent_y = tangent_u * sketch.frame.u_axis[1] + tangent_v * sketch.frame.v_axis[1]
        length = math.hypot(tangent_x, tangent_y)
        return (-tangent_y / length, tangent_x / length) if length > 1e-12 else None
    if (
        enable_spline
        and isinstance(entity, SplineEntity)
        and attachment.curve_kind == "spline"
        and attachment.parameter is not None
        and len(entity.control_points_mm) == attachment.control_count
    ):
        dx, dy = _spline_tangent(entity, attachment.parameter)
        tangent_x = dx * sketch.frame.u_axis[0] + dy * sketch.frame.v_axis[0]
        tangent_y = dx * sketch.frame.u_axis[1] + dy * sketch.frame.v_axis[1]
        length = math.hypot(tangent_x, tangent_y)
        return (-tangent_y / length, tangent_x / length) if length > 1e-12 else None
    if isinstance(entity, CircleEntity | ArcEntity):
        center = sketch.frame.local_to_world(entity.center_mm)
        dx, dy = target[0] - center[0], target[1] - center[1]
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length > 1e-12 else None
    return None


def resolve_attachment_local(
    attachment: DatumAttachment, entities: Mapping[str, SketchEntity]
) -> Point2D | None:
    reference = attachment.reference
    if attachment.parameter is None:
        return resolve_point_reference(reference, entities)
    entity = entities.get(reference.entity_id)
    t = attachment.parameter
    extension = attachment.surface_extension
    if extension is not None:
        if not isinstance(entity, LineEntity | ArcEntity):
            return None
        try:
            return surface_extension_geometry(
                entity,
                extension.side,
                extension.distance_mm,
                extension.offset_mm,
                extension.overshoot_mm,
            ).target_mm
        except ValueError:
            return None
    if attachment.curve_kind == "ellipse":
        return entity.point_at(t) if isinstance(entity, EllipseEntity) else None
    if attachment.curve_kind == "spline":
        if (
            not isinstance(entity, SplineEntity)
            or len(entity.control_points_mm) != attachment.control_count
        ):
            return None
        return entity.point_at(t)
    if reference.kind == "segment":
        if attachment.segment_kind == "rectangle":
            if not isinstance(entity, RectangleEntity) or reference.index is None:
                return None
            x1, y1 = entity.first_corner_mm
            x2, y2 = entity.opposite_corner_mm
            corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
            start, end = corners[reference.index], corners[(reference.index + 1) % 4]
            return (start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1]))
        if not isinstance(entity, PolylineEntity) or reference.index is None:
            return None
        count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
        if reference.index >= count or count != attachment.segment_count:
            return None
        bulges = entity.bulges or (0.0,) * count
        entity = polyline_curve_segments(entity.points_mm, bulges, entity.closed, entity.entity_id)[
            reference.index
        ]
    elif reference.kind != "geometry":
        return None
    if isinstance(entity, LineEntity):
        return (
            entity.start_mm[0] + t * (entity.end_mm[0] - entity.start_mm[0]),
            entity.start_mm[1] + t * (entity.end_mm[1] - entity.start_mm[1]),
        )
    if isinstance(entity, CircleEntity | ArcEntity):
        angle = (
            360 * t
            if isinstance(entity, CircleEntity)
            else entity.start_angle_deg + entity.sweep_angle_deg * t
        )
        radians = math.radians(angle)
        return (
            entity.center_mm[0] + entity.radius_mm * math.cos(radians),
            entity.center_mm[1] + entity.radius_mm * math.sin(radians),
        )
    return None
