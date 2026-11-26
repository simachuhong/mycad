# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Immutable neutral view of a drawing collection candidate."""

import re
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from mycad.core.associative_array import AssociativeRectArray
from mycad.core.cross_sketch_tangency import CrossSketchTangency
from mycad.core.detached_dimension import DetachedDimension
from mycad.core.dimension_styles import DimensionStyleTable
from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
from mycad.core.drawing_groups import DrawingGroup, DrawingGroupTable
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.drawing_text import DrawingText, TextStyleTable
from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame
from mycad.core.sketch import Sketch
from mycad.core.sketch_layers import SketchLayerTable


@dataclass(frozen=True, slots=True)
class BlockLibraryOrigin:
    """Replayable provenance for one document-local block definition."""

    definition_id: str
    asset_id: str
    content_sha256: str

    def __post_init__(self) -> None:
        for value in (self.definition_id, self.asset_id):
            if not isinstance(cast("object", value), str):
                raise ValueError("块库来源身份无效。")
            try:
                UUID(value)
            except ValueError as exc:
                raise ValueError("块库来源身份无效。") from exc
        if not isinstance(cast("object", self.content_sha256), str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.content_sha256
        ):
            raise ValueError("块库来源摘要无效。")


@dataclass(frozen=True, slots=True)
class DrawingCollectionState:
    """Immutable collection records independent of expanded block geometry."""

    groups: DrawingGroupTable = DrawingGroupTable()
    block_definitions: tuple[BlockDefinition, ...] = ()
    block_instances: tuple[BlockInstance, ...] = ()
    block_library_origins: tuple[BlockLibraryOrigin, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.groups), DrawingGroupTable):
            raise ValueError("invalid drawing group table")
        definitions, instances = tuple(self.block_definitions), tuple(self.block_instances)
        if any(not isinstance(cast("object", item), BlockDefinition) for item in definitions):
            raise ValueError("invalid block definition")
        if any(not isinstance(cast("object", item), BlockInstance) for item in instances):
            raise ValueError("invalid block instance")
        definition_ids = {item.definition_id for item in definitions}
        if len({UUID(identity).hex for identity in definition_ids}) != len(definitions):
            raise ValueError("duplicate block definition identity")
        if len({item.name.casefold() for item in definitions}) != len(definitions):
            raise ValueError("duplicate block definition name")
        instance_ids = {item.instance_id for item in instances}
        if len({UUID(identity).hex for identity in instance_ids}) != len(instances):
            raise ValueError("duplicate block instance identity")
        if any(item.definition_id not in definition_ids for item in instances):
            raise ValueError("block instance references a missing definition")
        if any(
            member.kind == "block_instance" and member.object_id not in instance_ids
            for group in self.groups.groups
            for member in group.members
        ):
            raise ValueError("group references a missing block instance")
        object.__setattr__(self, "block_definitions", definitions)
        object.__setattr__(self, "block_instances", instances)
        origins = tuple(self.block_library_origins)
        if any(not isinstance(cast("object", origin), BlockLibraryOrigin) for origin in origins):
            raise ValueError("invalid block library origin")
        if len({UUID(item.definition_id).hex for item in origins}) != len(origins):
            raise ValueError("duplicate block library origin")
        if any(item.definition_id not in definition_ids for item in origins):
            raise ValueError("block library origin references missing definition")
        object.__setattr__(self, "block_library_origins", origins)


@dataclass(frozen=True, slots=True)
class DrawingCollectionSnapshot:
    sketches: tuple[Sketch, ...]
    groups: tuple[DrawingGroup, ...]
    texts: tuple[DrawingText, ...]
    text_styles: TextStyleTable
    dimension_styles: DimensionStyleTable
    rasters: tuple[DrawingRaster, ...]
    frames: tuple[FeatureControlFrame, ...]
    datums: tuple[DatumIdentifier, ...]
    reference_dimensions: tuple[DetachedDimension, ...]
    layers: SketchLayerTable
    dimension_layer: str
    cross_tangencies: tuple[CrossSketchTangency, ...]
    associative_arrays: tuple[AssociativeRectArray, ...]
    block_definitions: tuple[BlockDefinition, ...] = ()
    block_instances: tuple[BlockInstance, ...] = ()
    block_library_origins: tuple[BlockLibraryOrigin, ...] = ()
