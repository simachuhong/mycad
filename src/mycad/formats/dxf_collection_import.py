# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Prepare one atomic import of native drawing collections."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.drawing_blocks import BlockDefinition
from mycad.core.drawing_collection_clipboard import (
    DrawingCollectionClipboard,
    prepare_collection_paste,
)
from mycad.core.drawing_groups import DrawingGroup
from mycad.core.drawing_text import TextStyleTable
from mycad.core.exceptions import ValidationError
from mycad.core.replay_proposal import ReplayAppend
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.formats.dxf_collections import unique_import_name

if TYPE_CHECKING:
    from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch_constraints import SketchConstraint
    from mycad.formats.providers.dxf_provider import DxfSketchImport


@dataclass(frozen=True, slots=True)
class PreparedDxfCollectionImport:
    operation: ReplayAppend
    warnings: tuple[str, ...]


def _remap_target_layer_conflicts(
    payload: DrawingCollectionClipboard, target: DrawingCollectionSnapshot
) -> tuple[DrawingCollectionClipboard, tuple[str, ...]]:
    """Preserve source layer properties without changing conflicting target layers."""
    used_names = {
        layer.name.casefold() for layer in (*target.layers.layers, *payload.layers.layers)
    }
    used_source = {
        item.layer_name.casefold() for sketch in payload.sketches for item in sketch.entities
    }
    used_source.update(
        item.layer_name.casefold()
        for sketch in payload.sketches
        for item in sketch.constraints
        if item.layer_name is not None
    )
    used_source.update(
        item.layer_name.casefold()
        for item in (
            *payload.texts,
            *payload.rasters,
            *payload.frames,
            *payload.datums,
            *payload.reference_dimensions,
            *payload.block_instances,
        )
    )
    used_source.update(
        item.layer_name.casefold()
        for definition in payload.block_definitions
        for item in (*definition.entities, *definition.texts)
        if item.layer_name.casefold() != "0"
    )
    mapping: dict[str, str] = {}
    layers = payload.layers
    warnings: list[str] = []
    for layer in payload.layers.layers:
        if layer.name.casefold() not in used_source:
            continue
        try:
            existing = target.layers.get(layer.name)
        except KeyError:
            continue
        restricted = existing.locked or not existing.displayed
        if not restricted and replace(layer, name=existing.name) == existing:
            continue
        name = unique_import_name(layer.name, used_names, max_length=255)
        used_names.add(name.casefold())
        layers = layers.add(replace(layer, name=name))
        mapping[layer.name.casefold()] = name
        warnings.append(
            f"目标图层受限：{layer.name} → {name}。"
            if restricted
            else f"图层名称冲突：{layer.name} → {name}（属性不同）。"
        )
    if not mapping:
        return payload, ()

    def mapped(name: str) -> str:
        return mapping.get(name.casefold(), name)

    sketches = tuple(
        replace(
            sketch,
            entities=tuple(
                replace(item, layer_name=mapped(item.layer_name)) for item in sketch.entities
            ),
            constraints=tuple(
                replace(item, layer_name=mapped(item.layer_name))
                if item.layer_name is not None
                else item
                for item in sketch.constraints
            ),
            layers=layers,
        )
        for sketch in payload.sketches
    )
    definitions = tuple(
        replace(
            definition,
            entities=tuple(
                replace(item, layer_name=mapped(item.layer_name))
                if item.layer_name.casefold() != "0"
                else item
                for item in definition.entities
            ),
            texts=tuple(
                replace(item, layer_name=mapped(item.layer_name))
                if item.layer_name.casefold() != "0"
                else item
                for item in definition.texts
            ),
        )
        for definition in payload.block_definitions
    )
    return (
        replace(
            payload,
            sketches=sketches,
            layers=layers,
            texts=tuple(
                replace(item, layer_name=mapped(item.layer_name)) for item in payload.texts
            ),
            rasters=tuple(
                replace(item, layer_name=mapped(item.layer_name)) for item in payload.rasters
            ),
            frames=tuple(
                replace(item, layer_name=mapped(item.layer_name)) for item in payload.frames
            ),
            datums=tuple(
                replace(item, layer_name=mapped(item.layer_name)) for item in payload.datums
            ),
            reference_dimensions=tuple(
                replace(item, layer_name=mapped(item.layer_name))
                for item in payload.reference_dimensions
            ),
            block_definitions=definitions,
            block_instances=tuple(
                replace(item, layer_name=mapped(item.layer_name))
                for item in payload.block_instances
            ),
        ),
        tuple(warnings),
    )


def prepare_dxf_collection_import(
    imported: DxfSketchImport,
    target: DrawingCollectionSnapshot,
    *,
    datum_relayout: Callable[[DatumIdentifier, TextStyleTable], DatumIdentifier] | None = None,
) -> PreparedDxfCollectionImport:
    """Freeze new identities, resource merges, and name conflicts before preview."""
    source_styles = dict(imported.dimension_styles)
    dimension_styles: list[DimensionStyle] = []
    constraints: list[SketchConstraint] = []
    for constraint in imported.sketch.constraints:
        style = source_styles.get(constraint.constraint_id)
        if style is not None:
            equivalent = next((item for item in dimension_styles if item == style), None)
            if equivalent is None:
                name, suffix = style.name, 1
                names = {item.name.casefold() for item in dimension_styles}
                while name.casefold() in names:
                    suffix_text = f" ({suffix})"
                    name = style.name[: 80 - len(suffix_text)] + suffix_text
                    suffix += 1
                equivalent = replace(style, name=name)
                dimension_styles.append(equivalent)
            constraint = replace(constraint, style_name=equivalent.name)
        constraints.append(constraint)
    sketch = replace(imported.sketch, constraints=tuple(constraints))
    table = (
        DimensionStyleTable(tuple(dimension_styles), dimension_styles[0].name)
        if dimension_styles
        else None
    )
    payload = DrawingCollectionClipboard(
        (sketch,) if sketch.entities else (),
        imported.texts,
        (),
        imported.groups,
        imported.text_styles or TextStyleTable(),
        sketch.layers,
        table,
        imported.tolerance_frames,
        imported.datum_identifiers,
        imported.detached_dimensions,
        (),
        imported.block_definitions,
        imported.block_instances,
    )
    try:
        payload, layer_warnings = _remap_target_layer_conflicts(payload, target)
        # New source layers are restored after their objects have passed the
        # normal command validators. Existing target layers are never unlocked.
        relaxed_layers = payload.layers
        restricted_new_layers: list[SketchLayer] = []
        for layer in payload.layers.layers:
            try:
                target.layers.get(layer.name)
            except KeyError:
                if layer.locked or not layer.displayed:
                    restricted_new_layers.append(layer)
                    relaxed_layers = relaxed_layers.replace(
                        replace(layer, locked=False, frozen=False, visible=True)
                    )
        payload = replace(payload, layers=relaxed_layers)
        operation = prepare_collection_paste(
            payload, target, (0, 0), datum_relayout=datum_relayout, reuse_block_definitions=False
        )
        operations = cast("list[dict[str, object]]", operation.params["operations"])
        imported_layers = target.layers
        for item in operations:
            if item["id"] in {"drawing.layers.set", "drawing.clipboard.prepare"}:
                params = cast("dict[str, object]", item["params"])
                imported_layers = SketchLayerTable.from_mapping(params["layers"])
        final_layers = imported_layers
        for layer in restricted_new_layers:
            try:
                final_layers.get(layer.name)
            except KeyError:
                continue
            final_layers = final_layers.replace(layer)
        if final_layers != imported_layers:
            operations.append(
                {
                    "id": "drawing.layers.set",
                    "version": 1,
                    "params": {
                        "layers": final_layers.to_mapping(),
                        "dimension_layer": target.dimension_layer,
                    },
                }
            )
            operation = replace(operation, params={"operations": operations})
        copied_blocks = tuple(
            BlockDefinition.from_mapping(item["params"])
            for item in operations
            if item["id"] == "drawing.block.create"
        )
        copied_groups = tuple(
            DrawingGroup.from_mapping(item["params"])
            for item in operations
            if item["id"] == "drawing.group.create"
        )
        warnings = (
            layer_warnings
            + tuple(
                f"块名称冲突：{old.name} → {new.name}"
                for old, new in zip(imported.block_definitions, copied_blocks, strict=True)
                if old.name != new.name
            )
            + tuple(
                f"组名称冲突：{old.name} → {new.name}"
                for old, new in zip(imported.groups, copied_groups, strict=True)
                if old.name != new.name
            )
        )
        return PreparedDxfCollectionImport(operation, warnings)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError(f"无法准备 DXF 集合导入：{exc}") from exc
