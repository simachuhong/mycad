# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Derive a read-only drawing preview from two candidate projections."""

from __future__ import annotations

from dataclasses import replace

from mycad.core.drawing_blocks import expand_block
from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
from mycad.core.drawing_text import DrawingText
from mycad.core.sketch import Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import DIMENSION_KINDS


def collection_preview_payload(
    before: DrawingCollectionSnapshot, after: DrawingCollectionSnapshot
) -> DrawingCollectionClipboard:
    """Keep changed objects and geometry needed to render affected dimensions."""
    old_sketches = {item.sketch_id: item for item in before.sketches}
    sketches: list[Sketch] = []
    for sketch in after.sketches:
        previous = old_sketches.get(sketch.sketch_id)
        old_entities = {item.entity_id: item for item in previous.entities} if previous else {}
        old_constraints = (
            {item.constraint_id: item for item in previous.constraints} if previous else {}
        )
        changed = {
            item.entity_id
            for item in sketch.entities
            if previous is None
            or sketch.frame != previous.frame
            or old_entities.get(item.entity_id) != item
        }
        dimensions = tuple(
            item
            for item in sketch.constraints
            if item.kind in DIMENSION_KINDS
            and (
                old_constraints.get(item.constraint_id) != item
                or any(ref.entity_id in changed for ref in item.references)
            )
        )
        needed = changed | {ref.entity_id for item in dimensions for ref in item.references}
        if needed or dimensions:
            sketches.append(
                replace(
                    sketch,
                    entities=tuple(item for item in sketch.entities if item.entity_id in needed),
                    constraints=dimensions,
                )
            )
    old_texts = {item.text_id: item for item in before.texts}
    old_instances = {item.instance_id: item for item in before.block_instances}
    old_definitions = {item.definition_id: item for item in before.block_definitions}
    definitions = {item.definition_id: item for item in after.block_definitions}
    block_texts: list[DrawingText] = []
    for instance in after.block_instances:
        definition = definitions[instance.definition_id]
        if (
            old_instances.get(instance.instance_id) == instance
            and old_definitions.get(definition.definition_id) == definition
            and before.text_styles == after.text_styles
        ):
            continue
        expansion = expand_block(definition, instance, after.text_styles)
        if expansion.entities:
            sketches.append(
                Sketch(
                    instance.instance_id,
                    WorkPlaneFrame.xy(),
                    expansion.entities,
                    layers=after.layers,
                )
            )
        block_texts.extend(expansion.texts)
    old_rasters = {item.image_id: item for item in before.rasters}
    old_frames = {item.frame_id: item for item in before.frames}
    old_datums = {item.datum_id: item for item in before.datums}
    old_references = {item.dimension_id: item for item in before.reference_dimensions}
    return DrawingCollectionClipboard(
        tuple(sketches),
        (*tuple(item for item in after.texts if old_texts.get(item.text_id) != item), *block_texts),
        tuple(item for item in after.rasters if old_rasters.get(item.image_id) != item),
        (),
        after.text_styles,
        after.layers,
        after.dimension_styles,
        tuple(item for item in after.frames if old_frames.get(item.frame_id) != item),
        tuple(item for item in after.datums if old_datums.get(item.datum_id) != item),
        tuple(
            item
            for item in after.reference_dimensions
            if old_references.get(item.dimension_id) != item
        ),
    )
