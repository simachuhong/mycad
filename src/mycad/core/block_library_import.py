# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Prepare replayable imports of portable block assets into a drawing."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from mycad.core.block_library import BlockAsset
from mycad.core.drawing_blocks import BlockDefinition, BlockInstance, assign_new_curve_point_ids
from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
from mycad.core.drawing_text import TextStyleTable
from mycad.core.exceptions import ValidationError
from mycad.core.replay_proposal import ReplayAppend
from mycad.core.sketch import Point2D, sketch_entity_to_mapping
from mycad.core.sketch_edit import copy_entities
from mycad.core.sketch_layers import SketchLayerTable
from mycad.core.text_interchange import reconcile_text_style_ids


@dataclass(frozen=True, slots=True)
class BlockPlacement:
    insertion_mm: Point2D
    rotation_deg: float
    scale: float
    layer_name: str


@dataclass(frozen=True, slots=True)
class AssetIssue:
    code: str
    message: str
    field_path: str | None = None


@dataclass(frozen=True, slots=True)
class PreparedBlockImport:
    operation: ReplayAppend | None
    definition_id: str
    instance_id: str | None
    issues: tuple[AssetIssue, ...]


def _layers_for_asset(
    asset: BlockAsset, target: SketchLayerTable
) -> tuple[SketchLayerTable, dict[str, str], tuple[AssetIssue, ...]]:
    layers = target
    mapping = {"0": "0"}
    issues: list[AssetIssue] = []
    used = {
        item.layer_name.casefold() for item in (*asset.definition.entities, *asset.definition.texts)
    } - {"0"}
    for name in sorted(used):
        source = asset.layers.get(name)
        try:
            existing = layers.get(source.name)
        except KeyError:
            layers = layers.add(source)
            mapping[name] = source.name
            continue
        if existing.locked or not existing.displayed:
            raise ValueError(f"目标图层 {existing.name} 隐藏、冻结或已锁定。")
        if replace(source, name=existing.name) == existing:
            mapping[name] = existing.name
            continue
        base = f"{source.name} 副本"
        index = 1
        while True:
            proposed = base if index == 1 else f"{base} {index}"
            try:
                other = layers.get(proposed)
            except KeyError:
                other = replace(source, name=proposed)
                layers = layers.add(other)
                break
            if replace(source, name=other.name) == other and other.displayed and not other.locked:
                break
            index += 1
        mapping[name] = other.name
        issues.append(AssetIssue("layer_conflict", f"图层 {source.name} 已映射为 {other.name}。"))
    return layers, mapping, tuple(issues)


def _equivalent(
    source: BlockDefinition, candidate: BlockDefinition, styles: TextStyleTable
) -> bool:
    if len(source.entities) != len(candidate.entities) or len(source.texts) != len(candidate.texts):
        return False
    for left, right in zip(source.entities, candidate.entities, strict=True):
        a, b = sketch_entity_to_mapping(left), sketch_entity_to_mapping(right)
        for record in (a, b):
            record.pop("entity_id", None)
            record.pop("point_ids", None)
        if a != b:
            return False
    for left, right in zip(source.texts, candidate.texts, strict=True):
        a, b = left.to_mapping(), right.to_mapping()
        for record in (a, b):
            record.pop("text_id", None)
            record.pop("style_id", None)
        if a != b:
            return False
        left_style, right_style = styles.get(left.style_id), styles.get(right.style_id)
        if replace(left_style, style_id=right_style.style_id, name=right_style.name) != right_style:
            return False
    return True


def prepare_block_library_import(
    asset: BlockAsset, target: DrawingCollectionSnapshot, *, placement: BlockPlacement | None
) -> PreparedBlockImport:
    """Freeze one atomic import or reuse an unchanged definition from the same asset version."""
    try:
        layers, mapping, issues = _layers_for_asset(asset, target.layers)
        styles, style_ids = reconcile_text_style_ids(
            tuple(item.style_id for item in asset.definition.texts),
            asset.text_styles,
            target.text_styles,
        )
        source = replace(
            asset.definition,
            entities=tuple(
                replace(item, layer_name=mapping[item.layer_name.casefold()])
                for item in asset.definition.entities
            ),
            texts=tuple(
                replace(
                    item,
                    layer_name=mapping[item.layer_name.casefold()],
                    style_id=style_ids[item.style_id],
                )
                for item in asset.definition.texts
            ),
        )
        candidates = {item.definition_id: item for item in target.block_definitions}
        existing = next(
            (
                candidates[origin.definition_id]
                for origin in sorted(
                    target.block_library_origins, key=lambda item: item.definition_id
                )
                if origin.asset_id == asset.asset_id
                and origin.content_sha256 == asset.content_sha256
                and origin.definition_id in candidates
                and _equivalent(source, candidates[origin.definition_id], styles)
            ),
            None,
        )
        operations: list[dict[str, object]] = []
        if existing is None:
            if layers != target.layers:
                operations.append(
                    {
                        "id": "drawing.layers.set",
                        "version": 1,
                        "params": {
                            "layers": layers.to_mapping(),
                            "dimension_layer": target.dimension_layer,
                        },
                    }
                )
            if styles != target.text_styles:
                operations.append(
                    {
                        "id": "drawing.text.batch",
                        "version": 1,
                        "params": {
                            "add": [],
                            "update": [],
                            "remove": [],
                            "styles": styles.to_mapping(),
                        },
                    }
                )
            names = {item.name.casefold() for item in target.block_definitions}
            name, n = source.name, 1
            while name.casefold() in names:
                name = f"{source.name} 副本" if n == 1 else f"{source.name} 副本 {n}"
                n += 1
            if name != source.name:
                issues += (AssetIssue("block_conflict", f"块名称已调整为 {name}。"),)
            entities = source.entities
            if entities:
                entities = copy_entities(
                    entities, tuple(item.entity_id for item in entities), (0, 0)
                )[len(entities) :]
                entities = tuple(assign_new_curve_point_ids(item) for item in entities)
            existing = replace(
                source,
                definition_id=uuid4().hex,
                name=name,
                entities=entities,
                texts=tuple(replace(item, text_id=uuid4().hex) for item in source.texts),
            )
            operations.append(
                {"id": "drawing.block.create", "version": 1, "params": existing.to_mapping()}
            )
            operations.append(
                {
                    "id": "drawing.block_library.bind",
                    "version": 1,
                    "params": {
                        "definition_id": existing.definition_id,
                        "asset_id": asset.asset_id,
                        "content_sha256": asset.content_sha256,
                    },
                }
            )
        instance_id = None
        if placement is not None:
            layer = target.layers.get(placement.layer_name)
            if layer.locked or not layer.displayed:
                raise ValueError(f"目标图层 {layer.name} 隐藏、冻结或已锁定。")
            instance = BlockInstance(
                uuid4().hex,
                existing.definition_id,
                placement.insertion_mm,
                placement.rotation_deg,
                placement.scale,
                layer.name,
            )
            instance_id = instance.instance_id
            operations.append(
                {
                    "id": "drawing.block_instance.insert",
                    "version": 1,
                    "params": instance.to_mapping(),
                }
            )
        operation = (
            ReplayAppend("drawing.objects.batch", 1, {"operations": operations}, "local")
            if operations
            else None
        )
        return PreparedBlockImport(operation, existing.definition_id, instance_id, issues)
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationError(str(exc)) from exc
