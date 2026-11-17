# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Create identifiable labels for dimensions in a transient part sketch."""

from dataclasses import dataclass
from math import atan2, cos, hypot, radians, sin, sqrt

from mycad.core.sketch import ArcEntity, CircleEntity, Point2D, Point3D, Sketch
from mycad.core.sketch_constraints import DIMENSION_KINDS, SketchConstraint
from mycad.core.viewport_protocol import ViewportSketchDimension
from mycad.ui.dimension_text import dimension_text
from mycad.ui.sketch_editor import SketchCanvas


@dataclass(frozen=True)
class DraftDimensionLeader:
    constraint_id: str
    segments: tuple[tuple[Point3D, Point3D], ...]
    color_rgb: tuple[int, int, int]


def _angle_center(
    first: tuple[Point2D, Point2D], second: tuple[Point2D, Point2D]
) -> Point2D | None:
    a, b = first
    c, d = second
    u, v = (b[0] - a[0], b[1] - a[1]), (d[0] - c[0], d[1] - c[1])
    cross = u[0] * v[1] - u[1] * v[0]
    if abs(cross) <= 1e-12:
        return None
    offset = (c[0] - a[0], c[1] - a[1])
    factor = (offset[0] * v[1] - offset[1] * v[0]) / cross
    return (a[0] + factor * u[0], a[1] + factor * u[1])


def _anchor(sketch: Sketch, constraint: SketchConstraint) -> Point2D | None:
    entities = {entity.entity_id: entity for entity in sketch.entities}
    if any(ref.entity_id not in entities for ref in constraint.references):
        return None
    position = constraint.text_position_mm or constraint.position_mm
    if position is not None:
        return position
    reference = constraint.references[0]
    entity = entities[reference.entity_id]
    offset = 5.0 * constraint.scale
    if constraint.kind in ("radius", "diameter", "arc_length"):
        if not isinstance(entity, CircleEntity | ArcEntity):
            return None
        delta = (entity.radius_mm + offset) / sqrt(2.0)
        return (entity.center_mm[0] + delta, entity.center_mm[1] + delta)
    if constraint.kind in ("length", "angle"):
        segment = SketchCanvas.line_for_reference(reference, entities)
        if (
            constraint.kind == "angle"
            and SketchCanvas.line_for_reference(constraint.references[1], entities) is None
        ):
            return None
    elif constraint.kind == "distance":
        first = SketchCanvas.point_for_reference(reference, entities)
        second = SketchCanvas.point_for_reference(constraint.references[1], entities)
        segment = (first, second) if first is not None and second is not None else None
    else:
        return None
    if segment is None:
        return None
    first, second = segment
    dx, dy = second[0] - first[0], second[1] - first[1]
    length = hypot(dx, dy)
    if length <= 1e-12:
        return None
    return (
        (first[0] + second[0]) / 2 - dy * offset / length,
        (first[1] + second[1]) / 2 + dx * offset / length,
    )


def draft_dimensions(sketch: Sketch) -> tuple[ViewportSketchDimension, ...]:
    """Build labels only for measurable, visible dimensions with stable identities."""
    entities = {entity.entity_id: entity for entity in sketch.entities}
    result: list[ViewportSketchDimension] = []
    auto_positions: dict[Point2D, int] = {}
    for constraint in sketch.constraints:
        if constraint.kind not in DIMENSION_KINDS or constraint.value is None:
            continue
        entity = entities.get(constraint.references[0].entity_id)
        if entity is None:
            continue
        layer = sketch.layers.get(constraint.layer_name or entity.layer_name)
        if not layer.displayed:
            continue
        point = _anchor(sketch, constraint)
        if point is None:
            continue
        if constraint.position_mm is None and constraint.text_position_mm is None:
            count = auto_positions.get(point, 0)
            auto_positions[point] = count + 1
            point = (point[0], point[1] + count * 5.0 * constraint.scale)
        mode = "驱动" if constraint.driving else "参考"
        result.append(
            ViewportSketchDimension(
                constraint.constraint_id,
                f"{dimension_text(constraint)} [{mode}]",
                sketch.frame.local_to_world(point),
                (32, 92, 160) if constraint.driving else (95, 103, 112),
                constraint.scale,
            )
        )
    return tuple(result)


def draft_dimension_leaders(
    sketch: Sketch, dimensions: tuple[ViewportSketchDimension, ...]
) -> tuple[DraftDimensionLeader, ...]:
    """Connect linear and radial dimension text to its measured geometry."""
    entities = {entity.entity_id: entity for entity in sketch.entities}
    constraints = {item.constraint_id: item for item in sketch.constraints}
    leaders: list[DraftDimensionLeader] = []
    for dimension in dimensions:
        constraint = constraints.get(dimension.constraint_id)
        if constraint is None:
            continue
        label = sketch.frame.world_to_local(dimension.position)
        reference = constraint.references[0]
        entity = entities.get(reference.entity_id)
        segments: tuple[tuple[Point2D, Point2D], ...] = ()
        if constraint.kind in ("radius", "diameter") and isinstance(
            entity, CircleEntity | ArcEntity
        ):
            center = entity.center_mm
            dx, dy = label[0] - center[0], label[1] - center[1]
            length = hypot(dx, dy)
            if length <= 1e-12:
                continue
            unit = (dx / length, dy / length)
            rim = (center[0] + entity.radius_mm * unit[0], center[1] + entity.radius_mm * unit[1])
            origin = (
                (center[0] - entity.radius_mm * unit[0], center[1] - entity.radius_mm * unit[1])
                if constraint.kind == "diameter"
                else center
            )
            segments = ((origin, rim), (rim, label))
        elif constraint.kind in ("length", "distance"):
            if constraint.kind == "length":
                line = SketchCanvas.line_for_reference(reference, entities)
            else:
                first = SketchCanvas.point_for_reference(reference, entities)
                second = SketchCanvas.point_for_reference(constraint.references[1], entities)
                line = (first, second) if first is not None and second is not None else None
            if line is None:
                continue
            first, second = line
            dx, dy = second[0] - first[0], second[1] - first[1]
            length = hypot(dx, dy)
            if length <= 1e-12:
                continue
            if constraint.axis == "horizontal":
                start, end = (first[0], label[1]), (second[0], label[1])
            elif constraint.axis == "vertical":
                start, end = (label[0], first[1]), (label[0], second[1])
            elif constraint.axis == "aligned":
                normal = (-dy / length, dx / length)
                offset = (label[0] - first[0]) * normal[0] + (label[1] - first[1]) * normal[1]
                start = (first[0] + normal[0] * offset, first[1] + normal[1] * offset)
                end = (second[0] + normal[0] * offset, second[1] + normal[1] * offset)
            else:
                continue
            segments = ((first, start), (second, end), (start, end))
        elif constraint.kind == "angle" and constraint.value is not None:
            first_line = SketchCanvas.line_for_reference(reference, entities)
            second_line = SketchCanvas.line_for_reference(constraint.references[1], entities)
            if first_line is None or second_line is None:
                continue
            center = _angle_center(first_line, second_line)
            if center is None:
                continue
            radius = hypot(label[0] - center[0], label[1] - center[1])
            if radius <= 1e-12:
                continue
            start_angle = atan2(
                first_line[1][1] - first_line[0][1], first_line[1][0] - first_line[0][0]
            )
            sweep = radians(constraint.value)
            points = tuple(
                (
                    center[0] + radius * cos(start_angle + sweep * i / 24),
                    center[1] + radius * sin(start_angle + sweep * i / 24),
                )
                for i in range(25)
            )
            segments = (
                *tuple(zip(points, points[1:], strict=False)),
                (center, points[0]),
                (center, points[-1]),
            )
        if segments:
            leaders.append(
                DraftDimensionLeader(
                    dimension.constraint_id,
                    tuple(
                        (sketch.frame.local_to_world(a), sketch.frame.local_to_world(b))
                        for a, b in segments
                    ),
                    dimension.color_rgb,
                )
            )
    return tuple(leaders)
