# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Resolve curve identity conflicts before presenting a DXF import preview."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from uuid import uuid4

from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, FeatureControlFrame
from mycad.core.geometric_tolerance_topology import new_curve_point_identities
from mycad.core.sketch import PolylineEntity, Sketch, SketchEntity, SplineEntity


def remap_colliding_curves(
    sketch: Sketch,
    datums: tuple[DatumIdentifier, ...],
    frames: tuple[FeatureControlFrame, ...],
    existing_sketches: Sequence[Sketch],
) -> tuple[Sketch, tuple[DatumIdentifier, ...], tuple[FeatureControlFrame, ...], int]:
    """Give conflicting imported curves independent IDs and rebind their references."""
    occupied_points = {
        point_id
        for previous in existing_sketches
        for entity in previous.entities
        if isinstance(entity, PolylineEntity | SplineEntity)
        for point_id in entity.point_ids
    }
    occupied_entities = {
        entity.entity_id
        for previous in (*existing_sketches, sketch)
        for entity in previous.entities
    }
    reserved_points = occupied_points | {
        point_id
        for entity in sketch.entities
        if isinstance(entity, PolylineEntity | SplineEntity)
        for point_id in entity.point_ids
    }
    mapping: dict[str, str] = {}
    entities: list[SketchEntity] = []
    for entity in sketch.entities:
        if isinstance(entity, PolylineEntity | SplineEntity) and occupied_points.intersection(
            entity.point_ids
        ):
            kind = "polyline" if isinstance(entity, PolylineEntity) else "spline"
            while True:
                identity = uuid4().hex
                point_ids = new_curve_point_identities(identity, kind, len(entity.point_ids))
                if identity not in occupied_entities and not reserved_points.intersection(
                    point_ids
                ):
                    break
            occupied_entities.add(identity)
            reserved_points.update(point_ids)
            mapping[entity.entity_id] = identity
            entity = replace(entity, entity_id=identity, point_ids=point_ids)
        entities.append(entity)
    if not mapping:
        return sketch, datums, frames, 0

    constraints = tuple(
        replace(
            item,
            references=tuple(
                replace(ref, entity_id=mapping.get(ref.entity_id, ref.entity_id))
                for ref in item.references
            ),
        )
        for item in sketch.constraints
    )

    def rebind(attachment: DatumAttachment | None) -> DatumAttachment | None:
        if attachment is None or attachment.sketch_id != sketch.sketch_id:
            return attachment
        identity = mapping.get(attachment.reference.entity_id)
        if identity is None:
            return attachment
        return replace(attachment, reference=replace(attachment.reference, entity_id=identity))

    updated_datums = tuple(replace(item, attachment=rebind(item.attachment)) for item in datums)
    updated_frames = tuple(
        replace(item, leader_attachment=rebind(item.leader_attachment)) for item in frames
    )
    return (
        replace(sketch, entities=tuple(entities), constraints=constraints),
        updated_datums,
        updated_frames,
        len(mapping),
    )


def remap_datum_labels(
    datums: tuple[DatumIdentifier, ...],
    frames: tuple[FeatureControlFrame, ...],
    existing_datums: Sequence[DatumIdentifier],
) -> tuple[
    tuple[DatumIdentifier, ...], tuple[FeatureControlFrame, ...], tuple[tuple[str, str], ...]
]:
    """Avoid duplicate labels and update only explicitly bound datum references."""
    source_labels = {datum.datum_id: datum.label for datum in datums}
    for frame in frames:
        for row in frame.rows:
            for reference in row.datums:
                if (
                    reference.datum_id in source_labels
                    and source_labels[reference.datum_id] != reference.label
                ):
                    raise ValueError("导入的基准引用标签与目标基准不一致。")
    used = {item.label.casefold() for item in existing_datums}
    reserved = used | {item.label.casefold() for item in datums}
    replacements: dict[str, tuple[str, str]] = {}
    changes: list[tuple[str, str]] = []
    updated: list[DatumIdentifier] = []
    for datum in datums:
        label = datum.label
        if label.casefold() in used:
            index = 2
            while True:
                suffix = f"-{index}"
                candidate = label[: 80 - len(suffix)].rstrip() + suffix
                if candidate.casefold() not in reserved:
                    break
                index += 1
            replacements[datum.datum_id] = (label, candidate)
            changes.append((label, candidate))
            label = candidate
        used.add(label.casefold())
        reserved.add(label.casefold())
        updated.append(replace(datum, label=label))
    updated_frames = tuple(
        replace(
            frame,
            rows=tuple(
                replace(
                    row,
                    datums=tuple(
                        replace(ref, label=replacements[ref.datum_id][1])
                        if ref.datum_id in replacements
                        and ref.label == replacements[ref.datum_id][0]
                        else ref
                        for ref in row.datums
                    ),
                )
                for row in frame.rows
            ),
        )
        for frame in frames
    )
    return tuple(updated), updated_frames, tuple(changes)
