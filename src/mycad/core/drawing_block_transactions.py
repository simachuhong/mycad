# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Prepare replayable block operations without mutating document state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

from mycad.core.drawing_blocks import (
    BlockDefinition,
    BlockInstance,
    assign_new_curve_point_ids,
    expand_block,
    make_block_definition,
    validate_block_instance,
)
from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef, expand_group_selection
from mycad.core.drawing_object_refs import remap_group_members
from mycad.core.drawing_text import TextStyleTable
from mycad.core.drawing_transactions import (
    prepare_collection_delete,
    validate_collection_copy_geometry,
)
from mycad.core.exceptions import ValidationError
from mycad.core.geometric_tolerance_topology import new_curve_point_identities
from mycad.core.replay_proposal import ReplayAppend
from mycad.core.sketch import (
    Point2D,
    PolylineEntity,
    Sketch,
    SketchEntity,
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_edit import copy_entities
from mycad.core.sketch_layers import SketchLayerTable


def _block_explosion_source(
    definitions: tuple[BlockDefinition, ...],
    instances: tuple[BlockInstance, ...],
    instance_id: str,
) -> tuple[BlockDefinition, BlockInstance]:
    instance = next((item for item in instances if item.instance_id == instance_id), None)
    if instance is None:
        raise ValidationError("块实例不存在。")
    definition = next(
        (item for item in definitions if item.definition_id == instance.definition_id), None
    )
    if definition is None:
        raise ValidationError("块定义不存在。")
    return definition, instance


def _block_explosion_digest(
    definition: BlockDefinition,
    instance: BlockInstance,
    groups: tuple[DrawingGroup, ...],
    styles: TextStyleTable,
) -> str:
    source = DrawingObjectRef("block_instance", instance.instance_id)
    value = {
        "definition": definition.to_mapping(),
        "instance": instance.to_mapping(),
        "groups": [group.to_mapping() for group in groups if source in group.members],
        "styles": styles.to_mapping(),
    }
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def prepare_block_explode(snapshot: DrawingCollectionSnapshot, instance_id: str) -> ReplayAppend:
    """Allocate all identities before preview and freeze one typed explosion command."""
    definition, instance = _block_explosion_source(
        snapshot.block_definitions, snapshot.block_instances, instance_id
    )
    expansion = expand_block(definition, instance, snapshot.text_styles)
    identities: list[dict[str, object]] = []
    for item in expansion.entities:
        identity = uuid4().hex
        if isinstance(item, PolylineEntity):
            points = new_curve_point_identities(identity, "polyline", len(item.points_mm))
        elif isinstance(item, SplineEntity):
            points = new_curve_point_identities(identity, "spline", len(item.control_points_mm))
        else:
            points = ()
        identities.append({"entity_id": identity, "point_ids": list(points)})
    params: dict[str, object] = {
        "instance_id": instance_id,
        "source_digest": _block_explosion_digest(
            definition, instance, snapshot.groups, snapshot.text_styles
        ),
        "sketch_id": uuid4().hex if expansion.entities else None,
        "geometry_ids": identities,
        "text_ids": [uuid4().hex for _ in expansion.texts],
    }
    build_block_explode_batch(
        snapshot.block_definitions,
        snapshot.block_instances,
        snapshot.groups,
        snapshot.layers,
        snapshot.text_styles,
        params,
    )
    return ReplayAppend("drawing.block_instance.explode", 1, params, "local")


def build_block_explode_batch(
    definitions: tuple[BlockDefinition, ...],
    instances: tuple[BlockInstance, ...],
    groups: tuple[DrawingGroup, ...],
    layers: SketchLayerTable,
    styles: TextStyleTable,
    params: Mapping[str, object],
    *,
    reserved_ids: tuple[str, ...] = (),
) -> Mapping[str, object]:
    """Derive only the explosion's child operations from the current state and frozen IDs."""
    instance_id = cast("str", params["instance_id"])
    definition, instance = _block_explosion_source(definitions, instances, instance_id)
    if params["source_digest"] != _block_explosion_digest(definition, instance, groups, styles):
        raise ValidationError("块定义、实例、组或文字样式已变化；分解操作已过期。")
    expansion = expand_block(definition, instance, styles)
    for name in (
        instance.layer_name,
        *(item.layer_name for item in expansion.entities),
        *(item.layer_name for item in expansion.texts),
    ):
        layer = layers.get(name)
        if layer.locked or not layer.displayed:
            raise ValidationError("块实例或成员位于锁定或隐藏图层；分解未应用。")
    raw_geometry = cast("list[Mapping[str, object]]", params["geometry_ids"])
    text_ids = cast("list[str]", params["text_ids"])
    sketch_id = cast("str | None", params["sketch_id"])
    if (
        len(raw_geometry) != len(expansion.entities)
        or len(text_ids) != len(expansion.texts)
        or bool(sketch_id) != bool(expansion.entities)
    ):
        raise ValidationError("分解成员身份与块内容不匹配。")
    allocated: list[str] = ([sketch_id] if sketch_id else []) + text_ids
    copied: list[SketchEntity] = []
    for entity, entry in zip(expansion.entities, raw_geometry, strict=True):
        identity = cast("str", entry["entity_id"])
        points = cast("list[str]", entry["point_ids"])
        expected = (
            len(entity.points_mm)
            if isinstance(entity, PolylineEntity)
            else len(entity.control_points_mm)
            if isinstance(entity, SplineEntity)
            else 0
        )
        # Older v1 explode commands omitted identities for legacy curves.
        # Keep those saved commands replayable while new operations allocate them.
        legacy_empty = (
            isinstance(entity, PolylineEntity | SplineEntity)
            and not entity.point_ids
            and not points
        )
        if len(points) != expected and not legacy_empty:
            raise ValidationError("分解曲线点身份数量不匹配。")
        allocated.extend((identity, *points))
        if isinstance(entity, PolylineEntity | SplineEntity):
            copied.append(replace(entity, entity_id=identity, point_ids=tuple(points)))
        else:
            copied.append(replace(entity, entity_id=identity))
    try:
        reserved = {
            UUID(item).hex
            for item in (
                *reserved_ids,
                *(item.definition_id for item in definitions),
                *(item.instance_id for item in instances),
                *(item.group_id for item in groups),
                *(entity.entity_id for item in definitions for entity in item.entities),
                *(text.text_id for item in definitions for text in item.texts),
                *(
                    point_id
                    for item in definitions
                    for entity in item.entities
                    if isinstance(entity, PolylineEntity | SplineEntity)
                    for point_id in entity.point_ids
                ),
            )
        }
        if (
            len(set(allocated)) != len(allocated)
            or any(UUID(item).hex != item for item in allocated)
            or bool(set(allocated) & reserved)
        ):
            raise ValueError("分解身份必须是不同的十六进制 UUID。")
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError("分解身份无效或重复。") from exc
    operations: list[dict[str, object]] = []
    refs: list[DrawingObjectRef] = []
    if copied:
        assert sketch_id is not None
        sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), tuple(copied), (), layers)
        operations.append(
            {"id": "sketch.create", "version": 58, "params": sketch.to_state_mapping()}
        )
        refs.extend(DrawingObjectRef("geometry", item.entity_id, sketch_id) for item in copied)
    texts = tuple(
        replace(item, text_id=identity)
        for item, identity in zip(expansion.texts, text_ids, strict=True)
    )
    if texts:
        operations.append(
            {
                "id": "drawing.text.batch",
                "version": 1,
                "params": {
                    "add": [item.to_mapping() for item in texts],
                    "update": [],
                    "remove": [],
                },
            }
        )
        refs.extend(DrawingObjectRef("text", item.text_id) for item in texts)
    source = DrawingObjectRef("block_instance", instance_id)
    for group in remap_group_members(groups, {source: tuple(refs)}):
        if group not in groups:
            operations.append(
                {"id": "drawing.group.update", "version": 1, "params": group.to_mapping()}
            )
    operations.append(
        {
            "id": "drawing.block_instance.remove",
            "version": 1,
            "params": {"instance_id": instance_id},
        }
    )
    return {"operations": operations}


def prepare_block_create(
    snapshot: DrawingCollectionSnapshot,
    seeds: tuple[DrawingObjectRef, ...],
    name: str,
    base_mm: Point2D,
    *,
    convert_sources: bool,
    layer_name: str = "0",
) -> ReplayAppend:
    """Freeze a definition and, when requested, atomically replace its source objects."""
    selected = expand_group_selection(seeds, snapshot.groups)
    if not selected or any(item.kind not in {"geometry", "text"} for item in selected):
        raise ValidationError("块定义仅支持几何和文字。")
    geometry = tuple(item for item in selected if item.kind == "geometry")
    validate_collection_copy_geometry(
        snapshot, geometry, allow_array_dependencies=not convert_sources
    )
    texts = tuple(
        item for item in snapshot.texts if DrawingObjectRef("text", item.text_id) in selected
    )
    if len(texts) != sum(item.kind == "text" for item in selected):
        raise ValidationError("所选文字不存在或身份不唯一。")
    for item in texts:
        layer = snapshot.layers.get(item.layer_name)
        if layer.locked or not layer.displayed:
            raise ValidationError("所选文字位于锁定或隐藏图层。")
    if any(item.name.casefold() == name.casefold() for item in snapshot.block_definitions):
        raise ValidationError("块定义名称已存在。")
    if convert_sources:
        memberships = {
            frozenset(group.group_id for group in snapshot.groups if ref in group.members)
            for ref in selected
        }
        if len(memberships) != 1:
            raise ValidationError("所选对象的组归属不同，请先调整编组。")
        geometry_ids = {(item.sketch_id, item.object_id) for item in geometry}
        if any(
            any((sketch.sketch_id, ref.entity_id) in geometry_ids for ref in constraint.references)
            for sketch in snapshot.sketches
            for constraint in sketch.constraints
        ) or any(
            (ref.sketch_id, ref.entity_id) in geometry_ids
            for relation in snapshot.cross_tangencies
            for ref in (relation.first, relation.second)
        ):
            raise ValidationError("所选几何存在尺寸或约束关联，不能转换为块。")
        attachments = (
            *(item.leader_attachment for item in snapshot.frames),
            *(item.attachment for item in snapshot.datums),
        )
        if any(
            item is not None and (item.sketch_id, item.reference.entity_id) in geometry_ids
            for item in attachments
        ):
            raise ValidationError("所选几何存在公差或基准附着，不能转换为块。")
    sources: list[tuple[SketchEntity, WorkPlaneFrame]] = []
    for sketch in snapshot.sketches:
        ids = tuple(
            item.entity_id
            for item in sketch.entities
            if DrawingObjectRef("geometry", item.entity_id, sketch.sketch_id) in selected
        )
        if ids:
            clones = copy_entities(sketch.entities, ids, (0, 0))[len(sketch.entities) :]
            sources.extend((item, sketch.frame) for item in clones)
    try:
        definition = make_block_definition(
            uuid4().hex,
            name,
            tuple(sources),
            tuple(replace(item, text_id=uuid4().hex) for item in texts),
            base_mm,
        )
        definition = replace(
            definition,
            entities=tuple(assign_new_curve_point_ids(item) for item in definition.entities),
        )
        operations: list[dict[str, object]] = [
            {"id": "drawing.block.create", "version": 1, "params": definition.to_mapping()}
        ]
        if convert_sources:
            instance = BlockInstance(
                uuid4().hex, definition.definition_id, base_mm, layer_name=layer_name
            )
            validate_block_instance(definition, instance, snapshot.layers, snapshot.text_styles)
            operations.append(
                {
                    "id": "drawing.block_instance.insert",
                    "version": 1,
                    "params": instance.to_mapping(),
                }
            )
            replacement = DrawingObjectRef("block_instance", instance.instance_id)
            mapped = remap_group_members(snapshot.groups, dict.fromkeys(selected, (replacement,)))
            by_id = {group.group_id: group for group in mapped}
            for group in snapshot.groups:
                updated = by_id.get(group.group_id)
                if updated is not None and updated != group:
                    operations.append(
                        {"id": "drawing.group.update", "version": 1, "params": updated.to_mapping()}
                    )
            delete = prepare_collection_delete(replace(snapshot, groups=()), tuple(selected))
            operations.extend(cast("list[dict[str, object]]", delete.params["operations"]))
        return ReplayAppend("drawing.objects.batch", 1, {"operations": operations}, "local")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
