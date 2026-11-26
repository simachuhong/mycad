# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Versioned clipboard payload for complete drawing groups."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import cast
from uuid import UUID, uuid4

from mycad.core.cross_sketch_tangency import CrossSketchTangency, project_coplanar_vector
from mycad.core.detached_dimension import DetachedDimension
from mycad.core.dimension_interchange import reconcile_clipboard_fonts, reconcile_clipboard_styles
from mycad.core.dimension_styles import DimensionStyleTable
from mycad.core.drawing_blocks import BlockDefinition, BlockInstance, assign_new_curve_point_ids
from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef, expand_group_selection
from mycad.core.drawing_object_refs import DrawingObjectCatalog, validate_group_members
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.drawing_text import DrawingText, TextStyleTable, move_text
from mycad.core.drawing_transactions import validate_collection_copy_geometry
from mycad.core.exceptions import ValidationError
from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame
from mycad.core.geometric_tolerance_copy import copy_geometric_annotations
from mycad.core.replay_proposal import ReplayAppend
from mycad.core.sketch import Sketch, WorkPlaneFrame, sketch_entity_to_mapping
from mycad.core.sketch_constraints import DIMENSION_KINDS, SketchConstraint
from mycad.core.sketch_edit import copy_entities
from mycad.core.sketch_layers import SketchLayerTable, merge_layer_tables
from mycad.core.text_interchange import reconcile_text_style_ids, reconcile_text_styles

_MAX_BYTES = 32_000_000
DRAWING_COLLECTION_CLIPBOARD_MIME = "application/x-mycad-drawing-collections+json"


def clipboard_datum_labels(
    source: tuple[DatumIdentifier, ...],
    target: tuple[DatumIdentifier, ...],
    *,
    allow_relayout: bool = False,
) -> dict[str, str]:
    """Resolve the labels that both clipboard preview and paste will use."""
    used_labels = {item.label.casefold() for item in target}
    labels: dict[str, str] = {}
    for datum in source:
        label = datum.label
        if label.casefold() in used_labels:
            label = next(
                (chr(value) for value in range(65, 91) if chr(value).casefold() not in used_labels),
                "",
            )
            if not label:
                raise ValueError("没有可用的基准字母；请先调整基准名称。")
        if datum.box_size_mm is not None and label != datum.label and not allow_relayout:
            raise ValueError("复制带固定文字框的基准需要先重新计算文字布局。")
        labels[datum.datum_id] = label
        used_labels.add(label.casefold())
    return labels


@dataclass(frozen=True, slots=True)
class DrawingCollectionClipboard:
    sketches: tuple[Sketch, ...]
    texts: tuple[DrawingText, ...]
    rasters: tuple[DrawingRaster, ...]
    groups: tuple[DrawingGroup, ...]
    text_styles: TextStyleTable
    layers: SketchLayerTable = SketchLayerTable()
    dimension_styles: DimensionStyleTable | None = None
    frames: tuple[FeatureControlFrame, ...] = ()
    datums: tuple[DatumIdentifier, ...] = ()
    reference_dimensions: tuple[DetachedDimension, ...] = ()
    cross_tangencies: tuple[CrossSketchTangency, ...] = ()
    block_definitions: tuple[BlockDefinition, ...] = ()
    block_instances: tuple[BlockInstance, ...] = ()
    source_token: str | None = None
    external_objects: tuple[tuple[DrawingObjectRef, str], ...] = ()


def _external_annotation_refs(payload: DrawingCollectionClipboard) -> frozenset[DrawingObjectRef]:
    internal = {
        *(
            DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id)
            for sketch in payload.sketches
            for entity in sketch.entities
        ),
        *(
            DrawingObjectRef("dimension", constraint.constraint_id, sketch.sketch_id)
            for sketch in payload.sketches
            for constraint in sketch.constraints
            if constraint.kind in DIMENSION_KINDS
        ),
        *(DrawingObjectRef("tolerance", item.frame_id) for item in payload.frames),
        *(DrawingObjectRef("datum", item.datum_id) for item in payload.datums),
        *(
            DrawingObjectRef("reference_dimension", item.dimension_id)
            for item in payload.reference_dimensions
        ),
    }
    referenced: set[DrawingObjectRef] = set()
    for item in (*payload.frames, *payload.datums):
        geometry = (
            item.leader_attachment if isinstance(item, FeatureControlFrame) else item.attachment
        )
        annotation = (
            item.leader_annotation_attachment
            if isinstance(item, FeatureControlFrame)
            else item.annotation_attachment
        )
        if geometry is not None:
            referenced.add(
                DrawingObjectRef("geometry", geometry.reference.entity_id, geometry.sketch_id)
            )
        if annotation is not None:
            kind = {
                "frame": "tolerance",
                "reference_dimension": "reference_dimension",
                "sketch_dimension": "dimension",
            }[annotation.kind]
            referenced.add(DrawingObjectRef(kind, annotation.object_id, annotation.sketch_id))
    for frame in payload.frames:
        for row in frame.rows:
            referenced.update(
                DrawingObjectRef("datum", ref.datum_id)
                for ref in row.datums
                if ref.datum_id is not None
            )
    return frozenset(referenced - internal)


def _external_digest(snapshot: DrawingCollectionSnapshot, ref: DrawingObjectRef) -> str:
    """Fingerprint the referenced object and its sketch frame, if applicable."""
    value: object
    if ref.kind in {"geometry", "dimension"}:
        sketch = next((item for item in snapshot.sketches if item.sketch_id == ref.sketch_id), None)
        if sketch is None:
            raise ValueError("外部关联目标已不存在。")
        if ref.kind == "geometry":
            entity = next(
                (item for item in sketch.entities if item.entity_id == ref.object_id), None
            )
            if entity is None:
                raise ValueError("外部关联几何已不存在。")
            value = {"frame": sketch.frame.to_mapping(), "object": sketch_entity_to_mapping(entity)}
        else:
            constraint = next(
                (
                    item
                    for item in sketch.constraints
                    if item.constraint_id == ref.object_id and item.kind in DIMENSION_KINDS
                ),
                None,
            )
            if constraint is None:
                raise ValueError("外部关联尺寸已不存在。")
            entities = {item.entity_id: item for item in sketch.entities}
            try:
                referenced = [
                    sketch_entity_to_mapping(entities[item.entity_id])
                    for item in constraint.references
                ]
            except KeyError as exc:
                raise ValueError("外部关联尺寸的几何已不存在。") from exc
            value = {
                "frame": sketch.frame.to_mapping(),
                "object": constraint.to_mapping(),
                "geometry": referenced,
            }
    else:
        objects = {
            "tolerance": tuple((item.frame_id, item.to_mapping()) for item in snapshot.frames),
            "datum": tuple((item.datum_id, item.to_mapping()) for item in snapshot.datums),
            "reference_dimension": tuple(
                (item.dimension_id, item.to_mapping()) for item in snapshot.reference_dimensions
            ),
        }
        matches = [
            item for identity, item in objects.get(ref.kind, ()) if identity == ref.object_id
        ]
        if len(matches) != 1:
            raise ValueError("外部关联目标已不存在或身份不唯一。")
        value = matches[0]
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _validate(payload: DrawingCollectionClipboard, *, require_layers: bool = True) -> None:
    if (
        not payload.sketches
        and not payload.texts
        and not payload.rasters
        and not payload.frames
        and not payload.datums
        and not payload.reference_dimensions
        and not payload.block_instances
        and not payload.block_definitions
    ):
        raise ValueError("剪贴板没有可复制对象。")
    if len({UUID(sketch.sketch_id).hex for sketch in payload.sketches}) != len(payload.sketches):
        raise ValueError("剪贴板草图身份重复。")
    if any(not sketch.entities or sketch.support_face for sketch in payload.sketches):
        raise ValueError("当前组剪贴板不支持空草图或附着平面。")
    for sketch in payload.sketches:
        for constraint in sketch.constraints:
            if constraint.style_name is not None:
                if payload.dimension_styles is None:
                    raise ValueError("组剪贴板缺少标注样式。")
                try:
                    style = payload.dimension_styles.get(constraint.style_name)
                    if style.text_style_id is not None:
                        payload.text_styles.get(style.text_style_id)
                except KeyError as exc:
                    raise ValueError("组剪贴板缺少标注样式或文字样式。") from exc
    for sketch in payload.sketches:
        identities = {item.entity_id for item in sketch.entities}
        if any(
            ref.entity_id not in identities
            for item in sketch.constraints
            for ref in item.references
        ):
            raise ValueError("组剪贴板约束引用的几何不存在。")
    objects = (
        tuple(
            DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id)
            for sketch in payload.sketches
            for entity in sketch.entities
        )
        + tuple(
            DrawingObjectRef("dimension", constraint.constraint_id, sketch.sketch_id)
            for sketch in payload.sketches
            for constraint in sketch.constraints
            if constraint.kind in DIMENSION_KINDS
        )
        + tuple(DrawingObjectRef("text", text.text_id) for text in payload.texts)
        + tuple(DrawingObjectRef("raster", image.image_id) for image in payload.rasters)
        + tuple(DrawingObjectRef("tolerance", item.frame_id) for item in payload.frames)
        + tuple(DrawingObjectRef("datum", item.datum_id) for item in payload.datums)
        + tuple(
            DrawingObjectRef("reference_dimension", item.dimension_id)
            for item in payload.reference_dimensions
        )
        + tuple(
            DrawingObjectRef("block_instance", item.instance_id) for item in payload.block_instances
        )
    )
    if len({UUID(item.instance_id).hex for item in payload.block_instances}) != len(
        payload.block_instances
    ):
        raise ValueError("组剪贴板块实例身份重复。")
    definitions = {item.definition_id: item for item in payload.block_definitions}
    if len({UUID(item.definition_id).hex for item in payload.block_definitions}) != len(
        payload.block_definitions
    ):
        raise ValueError("组剪贴板块定义身份重复。")
    if len({item.name.casefold() for item in payload.block_definitions}) != len(definitions):
        raise ValueError("组剪贴板块定义名称重复。")
    if not {item.definition_id for item in payload.block_instances}.issubset(definitions):
        raise ValueError("组剪贴板块定义引用不完整。")
    catalog = DrawingObjectCatalog(objects)
    validate_group_members(payload.groups, catalog)
    for text in payload.texts:
        payload.text_styles.get(text.style_id)
    for definition in payload.block_definitions:
        for text in definition.texts:
            payload.text_styles.get(text.style_id)
    for item in (*payload.frames, *payload.datums):
        if item.text_style_id is not None:
            payload.text_styles.get(item.text_style_id)
    known = set(objects)
    external = {ref for ref, _digest in payload.external_objects}
    if frozenset(external) != _external_annotation_refs(payload) or len(external) != len(
        payload.external_objects
    ):
        raise ValueError("剪贴板外部关联清单无效。")
    if external:
        if payload.source_token is None or UUID(payload.source_token).hex != payload.source_token:
            raise ValueError("剪贴板缺少有效来源身份。")
        if any(
            len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)
            for _, digest in payload.external_objects
        ):
            raise ValueError("剪贴板外部关联摘要无效。")
    elif payload.source_token is not None:
        raise ValueError("剪贴板来源身份没有外部关联。")
    known |= external
    if len({item.relation_id for item in payload.cross_tangencies}) != len(
        payload.cross_tangencies
    ):
        raise ValueError("组剪贴板相切关系身份重复。")
    for relation in payload.cross_tangencies:
        if any(
            DrawingObjectRef("geometry", ref.entity_id, ref.sketch_id) not in known
            for ref in (relation.first, relation.second)
        ):
            raise ValueError("组剪贴板相切关系引用的几何未完整复制。")
    for item in (*payload.frames, *payload.datums):
        geometry = (
            item.leader_attachment if isinstance(item, FeatureControlFrame) else item.attachment
        )
        annotation = (
            item.leader_annotation_attachment
            if isinstance(item, FeatureControlFrame)
            else item.annotation_attachment
        )
        if (
            geometry is not None
            and DrawingObjectRef("geometry", geometry.reference.entity_id, geometry.sketch_id)
            not in known
        ):
            raise ValueError("附着标注引用的几何未完整复制。")
        if annotation is not None:
            kind = {
                "frame": "tolerance",
                "reference_dimension": "reference_dimension",
                "sketch_dimension": "dimension",
            }[annotation.kind]
            if DrawingObjectRef(kind, annotation.object_id, annotation.sketch_id) not in known:
                raise ValueError("附着标注引用的目标未完整复制。")
    for frame in payload.frames:
        for row in frame.rows:
            for datum in row.datums:
                if (
                    datum.datum_id is not None
                    and DrawingObjectRef("datum", datum.datum_id) not in known
                ):
                    raise ValueError("公差框引用的基准未完整复制。")
    if require_layers:
        names = {item.layer_name for sketch in payload.sketches for item in sketch.entities}
        names.update(
            item.layer_name
            for sketch in payload.sketches
            for item in sketch.constraints
            if item.layer_name is not None
        )
        names.update(item.layer_name for item in payload.block_instances)
        names.update(
            item.layer_name
            for definition in payload.block_definitions
            for item in (*definition.entities, *definition.texts)
        )
        names.update(
            item.layer_name
            for item in (
                *payload.texts,
                *payload.rasters,
                *payload.frames,
                *payload.datums,
                *payload.reference_dimensions,
            )
        )
        for name in names:
            try:
                payload.layers.get(name)
            except KeyError as exc:
                raise ValueError("组剪贴板缺少对象图层。") from exc


def capture_collection_clipboard(
    snapshot: DrawingCollectionSnapshot,
    seeds: tuple[DrawingObjectRef, ...],
    *,
    expand_selection: bool = True,
    source_token: str | None = None,
) -> DrawingCollectionClipboard:
    """Capture eligible objects and only groups whose members are all copied."""
    selected = (
        expand_group_selection(seeds, snapshot.groups) if expand_selection else frozenset(seeds)
    )
    if not selected or any(
        ref.kind
        not in {
            "geometry",
            "dimension",
            "text",
            "raster",
            "tolerance",
            "datum",
            "reference_dimension",
            "block_instance",
        }
        for ref in selected
    ):
        raise ValidationError("组剪贴板暂不支持所选成员类型。")
    validate_collection_copy_geometry(
        snapshot, tuple(item for item in selected if item.kind == "geometry")
    )
    sketches: list[Sketch] = []
    for sketch in snapshot.sketches:
        entities = tuple(
            item
            for item in sketch.entities
            if DrawingObjectRef("geometry", item.entity_id, sketch.sketch_id) in selected
        )
        if not entities:
            continue
        ids = {item.entity_id for item in entities}
        constraints = tuple(
            item
            for item in sketch.constraints
            if all(ref.entity_id in ids for ref in item.references)
            and (
                item.kind not in DIMENSION_KINDS
                or DrawingObjectRef("dimension", item.constraint_id, sketch.sketch_id) in selected
            )
        )
        sketches.append(replace(sketch, entities=entities, constraints=constraints))
    texts = tuple(
        item for item in snapshot.texts if DrawingObjectRef("text", item.text_id) in selected
    )
    rasters = tuple(
        item for item in snapshot.rasters if DrawingObjectRef("raster", item.image_id) in selected
    )
    frames = tuple(
        item for item in snapshot.frames if DrawingObjectRef("tolerance", item.frame_id) in selected
    )
    datums = tuple(
        item for item in snapshot.datums if DrawingObjectRef("datum", item.datum_id) in selected
    )
    references = tuple(
        item
        for item in snapshot.reference_dimensions
        if DrawingObjectRef("reference_dimension", item.dimension_id) in selected
    )
    groups = tuple(group for group in snapshot.groups if set(group.members).issubset(selected))
    instances = tuple(
        item
        for item in snapshot.block_instances
        if DrawingObjectRef("block_instance", item.instance_id) in selected
    )
    definition_ids = {item.definition_id for item in instances}
    definitions = tuple(
        item for item in snapshot.block_definitions if item.definition_id in definition_ids
    )
    payload = DrawingCollectionClipboard(
        tuple(sketches),
        texts,
        rasters,
        groups,
        snapshot.text_styles,
        snapshot.layers,
        snapshot.dimension_styles,
        frames,
        datums,
        references,
        tuple(
            relation
            for relation in snapshot.cross_tangencies
            if all(
                DrawingObjectRef("geometry", ref.entity_id, ref.sketch_id) in selected
                for ref in (relation.first, relation.second)
            )
        ),
        definitions,
        instances,
    )
    try:
        for sketch in snapshot.sketches:
            for constraint in sketch.constraints:
                if (
                    constraint.kind in DIMENSION_KINDS
                    and DrawingObjectRef("dimension", constraint.constraint_id, sketch.sketch_id)
                    in selected
                    and any(
                        DrawingObjectRef("geometry", ref.entity_id, sketch.sketch_id)
                        not in selected
                        for ref in constraint.references
                    )
                ):
                    raise ValueError("复制尺寸须同时选择其全部关联几何。")
        external = _external_annotation_refs(payload)
        if external:
            if source_token is None:
                raise ValueError("复制附着标注时请同时选择关联目标。")
            payload = replace(
                payload,
                source_token=source_token,
                external_objects=tuple(
                    (ref, _external_digest(snapshot, ref))
                    for ref in sorted(
                        external, key=lambda item: (item.kind, item.sketch_id or "", item.object_id)
                    )
                ),
            )
        for item in (
            *(entity for sketch in sketches for entity in sketch.entities),
            *texts,
            *rasters,
            *frames,
            *datums,
            *references,
        ):
            layer = snapshot.layers.get(item.layer_name)
            if layer.locked or not layer.displayed:
                raise ValueError("所选成员位于锁定或隐藏图层；复制未应用。")
        definitions_by_id = {item.definition_id: item for item in definitions}
        for instance in instances:
            definition = definitions_by_id.get(instance.definition_id)
            if definition is None:
                raise ValueError("所选块实例的定义不存在。")
            for name in (
                instance.layer_name,
                *(
                    instance.layer_name if item.layer_name.casefold() == "0" else item.layer_name
                    for item in (*definition.entities, *definition.texts)
                ),
            ):
                layer = snapshot.layers.get(name)
                if layer.locked or not layer.displayed:
                    raise ValueError("所选块实例或成员位于锁定或隐藏图层；复制未应用。")
        for sketch in sketches:
            for constraint in sketch.constraints:
                if constraint.kind in DIMENSION_KINDS:
                    entity = next(
                        item
                        for item in sketch.entities
                        if item.entity_id == constraint.references[0].entity_id
                    )
                    layer = snapshot.layers.get(constraint.layer_name or entity.layer_name)
                    if layer.locked or not layer.displayed:
                        raise ValueError("所选尺寸位于锁定或隐藏图层；复制未应用。")
        _validate(payload)
        captured = (
            {
                DrawingObjectRef("geometry", item.entity_id, sketch.sketch_id)
                for sketch in payload.sketches
                for item in sketch.entities
            }
            | {DrawingObjectRef("text", item.text_id) for item in texts}
            | {DrawingObjectRef("raster", item.image_id) for item in rasters}
            | {DrawingObjectRef("tolerance", item.frame_id) for item in frames}
            | {DrawingObjectRef("datum", item.datum_id) for item in datums}
            | {DrawingObjectRef("reference_dimension", item.dimension_id) for item in references}
            | {DrawingObjectRef("block_instance", item.instance_id) for item in instances}
            | {
                DrawingObjectRef("dimension", constraint.constraint_id, sketch.sketch_id)
                for sketch in sketches
                for constraint in sketch.constraints
                if constraint.kind in DIMENSION_KINDS
            }
        )
        if not selected.issubset(captured):
            raise ValueError("所选对象不存在或身份不唯一。")
    except (KeyError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    return payload


def encode_collection_clipboard(payload: DrawingCollectionClipboard) -> bytes:
    _validate(payload)
    value = {
        "format": "mycad-drawing-collections",
        "version": 7,
        "sketches": [item.to_state_mapping() for item in payload.sketches],
        "texts": [item.to_mapping() for item in payload.texts],
        "rasters": [item.to_mapping(version=2) for item in payload.rasters],
        "groups": [item.to_mapping() for item in payload.groups],
        "text_styles": payload.text_styles.to_mapping(),
        "layers": payload.layers.to_mapping(),
        "dimension_styles": payload.dimension_styles.to_mapping()
        if payload.dimension_styles is not None
        else None,
        "frames": [item.to_mapping() for item in payload.frames],
        "datums": [item.to_mapping() for item in payload.datums],
        "reference_dimensions": [item.to_mapping() for item in payload.reference_dimensions],
        "cross_tangencies": [item.to_mapping() for item in payload.cross_tangencies],
        "block_definitions": [item.to_mapping() for item in payload.block_definitions],
        "block_instances": [item.to_mapping() for item in payload.block_instances],
    }
    if payload.external_objects:
        value["version"] = 8
        value["source_token"] = payload.source_token
        value["external_objects"] = [
            {"ref": ref.to_mapping(), "digest": digest} for ref, digest in payload.external_objects
        ]
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    if len(data) > _MAX_BYTES:
        raise ValueError("组剪贴板数据过大。")
    return data


def decode_collection_clipboard(data: bytes) -> DrawingCollectionClipboard:
    if not data or len(data) > _MAX_BYTES:
        raise ValueError("组剪贴板数据无效或过大。")
    try:
        value: object = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("组剪贴板数据无效。")
        record = cast("dict[str, object]", value)
        version = record.get("version")
        expected = {"format", "version", "sketches", "texts", "rasters", "groups", "text_styles"}
        if type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7, 8):
            raise ValueError("不支持的组剪贴板格式。")
        if version >= 2:
            expected.add("layers")
        if version >= 4:
            expected.add("dimension_styles")
        if version >= 5:
            expected.update({"frames", "datums", "reference_dimensions"})
        if version >= 6:
            expected.add("cross_tangencies")
        if version >= 7:
            expected.update({"block_definitions", "block_instances"})
        if version >= 8:
            expected.update({"source_token", "external_objects"})
        if set(record) != expected or record["format"] != "mycad-drawing-collections":
            raise ValueError("不支持的组剪贴板格式。")
        for key in (
            ("sketches", "texts", "rasters", "groups", "frames", "datums", "reference_dimensions")
            if version >= 5
            else ("sketches", "texts", "rasters", "groups")
        ):
            if not isinstance(record[key], list) or len(cast("list[object]", record[key])) > 10000:
                raise ValueError("组剪贴板对象列表无效。")
        if version >= 6 and (
            not isinstance(record["cross_tangencies"], list)
            or len(cast("list[object]", record["cross_tangencies"])) > 10000
        ):
            raise ValueError("组剪贴板相切关系列表无效。")
        if version >= 7 and any(
            not isinstance(record[key], list) or len(cast("list[object]", record[key])) > 10000
            for key in ("block_definitions", "block_instances")
        ):
            raise ValueError("组剪贴板块列表无效。")
        external_objects: list[tuple[DrawingObjectRef, str]] = []
        token: str | None = None
        if version >= 8:
            if not isinstance(record["source_token"], str) or not isinstance(
                record["external_objects"], list
            ):
                raise ValueError("组剪贴板外部关联无效。")
            token = record["source_token"]
            entries = cast("list[object]", record["external_objects"])
            if not entries or len(entries) > 10000:
                raise ValueError("组剪贴板外部关联列表无效。")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("组剪贴板外部关联无效。")
                external_entry = cast("dict[str, object]", entry)
                if set(external_entry) != {"ref", "digest"} or not isinstance(
                    external_entry["digest"], str
                ):
                    raise ValueError("组剪贴板外部关联无效。")
                external_objects.append(
                    (
                        DrawingObjectRef.from_mapping(external_entry["ref"]),
                        external_entry["digest"],
                    )
                )
        sketches = tuple(
            Sketch.from_mapping(item) for item in cast("list[object]", record["sketches"])
        )
        if version < 3 and any(item.constraints for item in sketches):
            raise ValueError("旧版组剪贴板不支持约束。")
        layers = (
            SketchLayerTable.from_mapping(record["layers"])
            if version >= 2
            else merge_layer_tables(*(item.layers for item in sketches))
        )
        payload = DrawingCollectionClipboard(
            sketches,
            tuple(DrawingText.from_mapping(item) for item in cast("list[object]", record["texts"])),
            tuple(
                DrawingRaster.from_mapping(item) for item in cast("list[object]", record["rasters"])
            ),
            tuple(
                DrawingGroup.from_mapping(item) for item in cast("list[object]", record["groups"])
            ),
            TextStyleTable.from_mapping(record["text_styles"]),
            layers,
            DimensionStyleTable.from_mapping(record["dimension_styles"])
            if version >= 4 and record["dimension_styles"] is not None
            else None,
            tuple(
                FeatureControlFrame.from_mapping(item)
                for item in cast("list[object]", record["frames"])
            )
            if version >= 5
            else (),
            tuple(
                DatumIdentifier.from_mapping(item)
                for item in cast("list[object]", record["datums"])
            )
            if version >= 5
            else (),
            tuple(
                DetachedDimension.from_mapping(item)
                for item in cast("list[object]", record["reference_dimensions"])
            )
            if version >= 5
            else (),
            tuple(
                CrossSketchTangency.from_mapping(item)
                for item in cast("list[object]", record["cross_tangencies"])
            )
            if version >= 6
            else (),
            tuple(
                BlockDefinition.from_mapping(item)
                for item in cast("list[object]", record["block_definitions"])
            )
            if version >= 7
            else (),
            tuple(
                BlockInstance.from_mapping(item)
                for item in cast("list[object]", record["block_instances"])
            )
            if version >= 7
            else (),
            token,
            tuple(external_objects),
        )
        _validate(payload, require_layers=version >= 2)
        return payload
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("组剪贴板数据无效。") from exc


def prepare_collection_paste(
    payload: DrawingCollectionClipboard,
    target: DrawingCollectionSnapshot,
    delta: tuple[float, float],
    *,
    datum_relayout: Callable[[DatumIdentifier, TextStyleTable], DatumIdentifier] | None = None,
    reuse_block_definitions: bool = True,
    preserve_external: bool = False,
) -> ReplayAppend:
    """Freeze new object/group identities and styles for one atomic paste."""
    _validate(payload, require_layers=False)
    mapping: dict[DrawingObjectRef, DrawingObjectRef] = {}
    operations: list[dict[str, object]] = []
    try:
        if preserve_external:
            for ref, digest in payload.external_objects:
                if _external_digest(target, ref) != digest:
                    raise ValueError("外部关联目标已变化；请重新复制。")
        names = {item.layer_name for sketch in payload.sketches for item in sketch.entities}
        names.update(
            item.layer_name
            for sketch in payload.sketches
            for item in sketch.constraints
            if item.layer_name is not None
        )
        names.update(
            item.layer_name
            for item in (
                *payload.texts,
                *payload.rasters,
                *payload.frames,
                *payload.datums,
                *payload.reference_dimensions,
            )
        )
        names.update(item.layer_name for item in payload.block_instances)
        names.update(
            item.layer_name
            for definition in payload.block_definitions
            for item in (*definition.entities, *definition.texts)
            if item.layer_name.casefold() != "0"
        )
        layers = target.layers
        for name in sorted(names, key=str.casefold):
            try:
                layer = layers.get(name)
            except KeyError:
                layer = payload.layers.get(name)
                layers = layers.add(layer)
            if layer.locked or not layer.displayed:
                raise ValueError(f"目标图层 {name} 隐藏或已锁定。")
        dimension_styles = target.dimension_styles
        fonts = target.text_styles
        sketches = payload.sketches
        used_styles = {
            constraint.style_name.casefold()
            for sketch in sketches
            for constraint in sketch.constraints
            if constraint.style_name is not None
        }
        if used_styles:
            if payload.dimension_styles is None:
                raise ValueError("组剪贴板缺少标注样式。")
            source_styles = tuple(
                style
                for style in payload.dimension_styles.styles
                if style.name.casefold() in used_styles
            )
            if not source_styles:
                raise ValueError("组剪贴板缺少标注样式。")
            source_table = DimensionStyleTable(source_styles, source_styles[0].name)
            source_table, fonts = reconcile_clipboard_fonts(
                source_table, payload.text_styles, fonts
            )
            updated_sketches: list[Sketch] = []
            for sketch in sketches:
                dimension_styles, adjusted = reconcile_clipboard_styles(
                    sketch, source_table, dimension_styles
                )
                updated_sketches.append(adjusted)
            sketches = tuple(updated_sketches)
        styles, reconciled = reconcile_text_styles(payload.texts, payload.text_styles, fonts)
        annotation_font_ids = tuple(
            item.text_style_id
            for item in (*payload.frames, *payload.datums)
            if item.text_style_id is not None
        )
        styles, annotation_fonts = reconcile_text_style_ids(
            annotation_font_ids, payload.text_styles, styles
        )
        styles, block_fonts = reconcile_text_style_ids(
            tuple(
                text.style_id
                for definition in payload.block_definitions
                for text in definition.texts
            ),
            payload.text_styles,
            styles,
        )
        source_frames = tuple(
            replace(item, text_style_id=annotation_fonts[item.text_style_id])
            if item.text_style_id is not None
            else item
            for item in payload.frames
        )
        source_datums = tuple(
            replace(item, text_style_id=annotation_fonts[item.text_style_id])
            if item.text_style_id is not None
            else item
            for item in payload.datums
        )
        if dimension_styles != target.dimension_styles:
            prepare_params: dict[str, object] = {
                "layers": layers.to_mapping(),
                "dimension_layer": target.dimension_layer,
                "clipboard_styles": dimension_styles.to_mapping(),
            }
            if styles != target.text_styles:
                prepare_params["clipboard_text_styles"] = styles.to_mapping()
            operations.append(
                {"id": "drawing.clipboard.prepare", "version": 9, "params": prepare_params}
            )
        elif layers != target.layers:
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
        pasted_sketches: list[Sketch] = []
        for sketch in sketches:
            local_delta = project_coplanar_vector(delta, WorkPlaneFrame.xy(), sketch.frame)
            copied = copy_entities(
                sketch.entities, tuple(item.entity_id for item in sketch.entities), local_delta
            )[len(sketch.entities) :]
            copied = tuple(assign_new_curve_point_ids(item) for item in copied)
            sketch_id = uuid4().hex
            for source, clone in zip(sketch.entities, copied, strict=True):
                mapping[DrawingObjectRef("geometry", source.entity_id, sketch.sketch_id)] = (
                    DrawingObjectRef("geometry", clone.entity_id, sketch_id)
                )
            copied_constraints: list[SketchConstraint] = []
            for constraint in sketch.constraints:
                identity = uuid4().hex
                geometry_refs = tuple(
                    replace(
                        reference,
                        entity_id=mapping[
                            DrawingObjectRef("geometry", reference.entity_id, sketch.sketch_id)
                        ].object_id,
                    )
                    for reference in constraint.references
                )
                clone = replace(
                    constraint,
                    constraint_id=identity,
                    references=geometry_refs,
                    position_mm=(
                        constraint.position_mm[0] + local_delta[0],
                        constraint.position_mm[1] + local_delta[1],
                    )
                    if constraint.position_mm is not None
                    else None,
                    text_position_mm=(
                        constraint.text_position_mm[0] + local_delta[0],
                        constraint.text_position_mm[1] + local_delta[1],
                    )
                    if constraint.text_position_mm is not None
                    else None,
                )
                copied_constraints.append(clone)
                if constraint.kind in DIMENSION_KINDS:
                    mapping[
                        DrawingObjectRef("dimension", constraint.constraint_id, sketch.sketch_id)
                    ] = DrawingObjectRef("dimension", identity, sketch_id)
            result = Sketch(
                sketch_id, sketch.frame, copied, tuple(copied_constraints), layers=layers
            )
            pasted_sketches.append(result)
            operations.append(
                {"id": "sketch.create", "version": 58, "params": result.to_state_mapping()}
            )
        if payload.cross_tangencies:
            relations: list[CrossSketchTangency] = []
            for relation in payload.cross_tangencies:
                first, second = (
                    mapping[DrawingObjectRef("geometry", ref.entity_id, ref.sketch_id)]
                    for ref in (relation.first, relation.second)
                )
                assert first.sketch_id is not None and second.sketch_id is not None
                relations.append(
                    replace(
                        relation,
                        relation_id=uuid4().hex,
                        first=replace(
                            relation.first, sketch_id=first.sketch_id, entity_id=first.object_id
                        ),
                        second=replace(
                            relation.second, sketch_id=second.sketch_id, entity_id=second.object_id
                        ),
                    )
                )
            anchor = pasted_sketches[0]
            state = anchor.to_state_mapping()
            operations.append(
                {
                    "id": "drawing.sketch.revise",
                    "version": 79,
                    "params": {
                        "revisions": [
                            {
                                "sketch_id": anchor.sketch_id,
                                "base_state_sha256": anchor.local_state_digest(),
                                "entities": state["entities"],
                                "constraints": state["constraints"],
                            }
                        ],
                        "cross_tangencies": [item.to_mapping() for item in relations],
                    },
                }
            )
        texts = tuple(replace(move_text(item, delta), text_id=uuid4().hex) for item in reconciled)
        for source, clone in zip(payload.texts, texts, strict=True):
            mapping[DrawingObjectRef("text", source.text_id)] = DrawingObjectRef(
                "text", clone.text_id
            )
        if texts or (styles != target.text_styles and dimension_styles == target.dimension_styles):
            params: dict[str, object] = {
                "add": [item.to_mapping() for item in texts],
                "update": [],
                "remove": [],
            }
            if styles != target.text_styles and dimension_styles == target.dimension_styles:
                params["styles"] = styles.to_mapping()
            operations.append({"id": "drawing.text.batch", "version": 1, "params": params})
        images = tuple(
            replace(
                item,
                image_id=uuid4().hex,
                origin_mm=(item.origin_mm[0] + delta[0], item.origin_mm[1] + delta[1]),
            )
            for item in payload.rasters
        )
        for source, clone in zip(payload.rasters, images, strict=True):
            mapping[DrawingObjectRef("raster", source.image_id)] = DrawingObjectRef(
                "raster", clone.image_id
            )
        if images:
            operations.append(
                {
                    "id": "drawing.raster.batch",
                    "version": 2,
                    "params": {
                        "action": "add",
                        "images": [item.to_mapping(version=2) for item in images],
                    },
                }
            )
        references = tuple(
            replace(
                item,
                dimension_id=uuid4().hex,
                first_mm=(item.first_mm[0] + delta[0], item.first_mm[1] + delta[1]),
                second_mm=(item.second_mm[0] + delta[0], item.second_mm[1] + delta[1]),
                location_mm=(item.location_mm[0] + delta[0], item.location_mm[1] + delta[1]),
                vertex_mm=(item.vertex_mm[0] + delta[0], item.vertex_mm[1] + delta[1])
                if item.vertex_mm is not None
                else None,
            )
            for item in payload.reference_dimensions
        )
        for source, clone in zip(payload.reference_dimensions, references, strict=True):
            mapping[DrawingObjectRef("reference_dimension", source.dimension_id)] = (
                DrawingObjectRef("reference_dimension", clone.dimension_id)
            )
        if references:
            operations.append(
                {
                    "id": "drawing.reference_dimensions.batch",
                    "version": 10,
                    "params": {"add": [item.to_mapping() for item in references]},
                }
            )
        if source_frames or source_datums:
            labels = clipboard_datum_labels(
                source_datums, target.datums, allow_relayout=datum_relayout is not None
            )
            entity_ids = {
                (source.sketch_id, source.object_id): clone.object_id
                for source, clone in mapping.items()
                if source.kind == "geometry" and source.sketch_id is not None
            }
            entity_sketches = {
                (source.sketch_id, source.object_id): clone.sketch_id
                for source, clone in mapping.items()
                if source.kind == "geometry"
                and source.sketch_id is not None
                and clone.sketch_id is not None
            }
            dimension_ids = {
                (source.sketch_id, source.object_id): clone.object_id
                for source, clone in mapping.items()
                if source.kind == "dimension" and source.sketch_id is not None
            }
            dimension_sketches = {
                (source.sketch_id, source.object_id): clone.sketch_id
                for source, clone in mapping.items()
                if source.kind == "dimension"
                and source.sketch_id is not None
                and clone.sketch_id is not None
            }
            copied_frames, copied_datums = copy_geometric_annotations(
                source_frames,
                source_datums,
                entity_ids,
                "0" * 32,
                delta,
                labels,
                preserve_external=preserve_external,
                reference_mapping={
                    source.dimension_id: clone.dimension_id
                    for source, clone in zip(payload.reference_dimensions, references, strict=True)
                },
                dimension_mapping=dimension_ids,
                entity_sketch_mapping=entity_sketches,
                dimension_sketch_mapping=dimension_sketches,
            )
            if datum_relayout is not None:
                laid_out = tuple(
                    datum_relayout(clone, styles)
                    if clone.box_size_mm is not None and clone.label != source.label
                    else clone
                    for source, clone in zip(source_datums, copied_datums, strict=True)
                )
                if any(
                    replace(
                        original,
                        box_size_mm=updated.box_size_mm,
                        leader_offsets=updated.leader_offsets,
                    )
                    != updated
                    for original, updated in zip(copied_datums, laid_out, strict=True)
                ):
                    raise ValueError("基准文字布局不能修改对象身份或关联。")
                copied_datums = laid_out
            for source, clone in zip(payload.frames, copied_frames, strict=True):
                mapping[DrawingObjectRef("tolerance", source.frame_id)] = DrawingObjectRef(
                    "tolerance", clone.frame_id
                )
            for source, clone in zip(payload.datums, copied_datums, strict=True):
                mapping[DrawingObjectRef("datum", source.datum_id)] = DrawingObjectRef(
                    "datum", clone.datum_id
                )
            operations.append(
                {
                    "id": "drawing.tolerance.batch",
                    "version": 29
                    if any(item.arrow_style != "filled" for item in copied_datums)
                    else 28,
                    "params": {
                        "add_frames": [item.to_mapping() for item in copied_frames],
                        "add_datums": [item.to_mapping() for item in copied_datums],
                    },
                }
            )
        definitions_by_id = {
            UUID(item.definition_id).hex: item for item in target.block_definitions
        }
        definition_names = {item.name.casefold() for item in target.block_definitions}
        definition_mapping: dict[str, str] = {}
        for definition in payload.block_definitions:
            adjusted = replace(
                definition,
                texts=tuple(
                    replace(text, style_id=block_fonts[text.style_id]) for text in definition.texts
                ),
            )
            existing = definitions_by_id.get(UUID(definition.definition_id).hex)
            if (
                reuse_block_definitions
                and existing is not None
                and replace(adjusted, definition_id=existing.definition_id) == existing
            ):
                definition_mapping[definition.definition_id] = existing.definition_id
                continue
            name = adjusted.name
            if name.casefold() in definition_names:
                base, suffix = f"{name} 副本", 1
                name = base
                while name.casefold() in definition_names:
                    suffix += 1
                    name = f"{base} {suffix}"
            definition_names.add(name.casefold())
            entities = adjusted.entities
            if entities:
                entities = copy_entities(
                    entities, tuple(item.entity_id for item in entities), (0, 0)
                )[len(entities) :]
                entities = tuple(assign_new_curve_point_ids(item) for item in entities)
            clone = replace(
                adjusted,
                definition_id=uuid4().hex,
                name=name,
                entities=entities,
                texts=tuple(replace(item, text_id=uuid4().hex) for item in adjusted.texts),
            )
            definition_mapping[definition.definition_id] = clone.definition_id
            operations.append(
                {"id": "drawing.block.create", "version": 1, "params": clone.to_mapping()}
            )
        for instance in payload.block_instances:
            clone = replace(
                instance,
                instance_id=uuid4().hex,
                definition_id=definition_mapping[instance.definition_id],
                insertion_mm=(
                    instance.insertion_mm[0] + delta[0],
                    instance.insertion_mm[1] + delta[1],
                ),
            )
            mapping[DrawingObjectRef("block_instance", instance.instance_id)] = DrawingObjectRef(
                "block_instance", clone.instance_id
            )
            operations.append(
                {"id": "drawing.block_instance.insert", "version": 1, "params": clone.to_mapping()}
            )
        used = {group.name.casefold() for group in target.groups if group.name is not None}
        for group in payload.groups:
            name = group.name
            if name is not None and name.casefold() in used:
                base, suffix = f"{name} 副本", 1
                name = base
                while name.casefold() in used:
                    suffix += 1
                    name = f"{base} {suffix}"
            if name is not None:
                used.add(name.casefold())
            clone = replace(
                group,
                group_id=uuid4().hex,
                name=name,
                members=tuple(mapping[item] for item in group.members),
            )
            operations.append(
                {"id": "drawing.group.create", "version": 1, "params": clone.to_mapping()}
            )
    except (KeyError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    return ReplayAppend("drawing.objects.batch", 1, {"operations": operations}, "local")
