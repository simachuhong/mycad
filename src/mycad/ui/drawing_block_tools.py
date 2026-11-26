# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Read-only display projection of independent drawing block instances."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from mycad.core.cross_sketch_tangency import project_coplanar_entity, project_coplanar_vector
from mycad.core.drawing_blocks import BlockDefinition, BlockInstance, expand_block
from mycad.core.drawing_text import DrawingText, TextStyleTable
from mycad.core.sketch import SketchEntity, WorkPlaneFrame
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable


@dataclass(frozen=True, slots=True)
class BlockGeometryView:
    instance_id: str
    entity: SketchEntity
    layer: SketchLayer
    pickable: bool


@dataclass(frozen=True, slots=True)
class BlockTextView:
    instance_id: str
    text: DrawingText
    layer: SketchLayer
    pickable: bool


@dataclass(frozen=True, slots=True)
class DrawingBlockView:
    geometry: tuple[BlockGeometryView, ...]
    texts: tuple[BlockTextView, ...]


class DrawingBlockViewCache:
    """Cache the one projection used for block drawing, picking and snapping."""

    def __init__(self) -> None:
        self._key: tuple[object, ...] | None = None
        self._view: DrawingBlockView | None = None

    def build(
        self,
        definitions: tuple[BlockDefinition, ...],
        instances: tuple[BlockInstance, ...],
        layers: SketchLayerTable,
        styles: TextStyleTable,
        frame: WorkPlaneFrame,
    ) -> DrawingBlockView:
        key = (definitions, instances, layers, styles, frame)
        if key == self._key and self._view is not None:
            return self._view
        by_id = {item.definition_id: item for item in definitions}
        geometry: list[BlockGeometryView] = []
        texts: list[BlockTextView] = []
        drawing_frame = WorkPlaneFrame.xy()
        try:
            project_coplanar_vector((1.0, 0.0), drawing_frame, frame)
        except ValueError:
            view = DrawingBlockView((), ())
            self._key, self._view = key, view
            return view
        for instance in instances:
            instance_layer = layers.get(instance.layer_name)
            if not instance_layer.displayed:
                continue
            expansion = expand_block(by_id[instance.definition_id], instance, styles)
            for entity in expansion.entities:
                layer = layers.get(entity.layer_name)
                if layer.displayed:
                    geometry.append(
                        BlockGeometryView(
                            instance.instance_id,
                            project_coplanar_entity(entity, drawing_frame, frame),
                            layer,
                            not instance_layer.locked and not layer.locked,
                        )
                    )
            for item in expansion.texts:
                layer = layers.get(item.layer_name)
                if not layer.displayed:
                    continue
                angle = math.radians(item.rotation_deg)
                direction = project_coplanar_vector(
                    (math.cos(angle), math.sin(angle)), drawing_frame, frame
                )
                projected = replace(
                    item,
                    position_mm=frame.world_to_local(
                        drawing_frame.local_to_world(item.position_mm)
                    ),
                    rotation_deg=math.degrees(math.atan2(direction[1], direction[0])),
                )
                texts.append(
                    BlockTextView(
                        instance.instance_id,
                        projected,
                        layer,
                        not instance_layer.locked and not layer.locked,
                    )
                )
        view = DrawingBlockView(tuple(geometry), tuple(texts))
        self._key, self._view = key, view
        return view
