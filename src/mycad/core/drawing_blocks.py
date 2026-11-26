# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Pure values and deterministic derived geometry for independent 2D blocks."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from mycad.core.cross_sketch_tangency import project_coplanar_entity
from mycad.core.drawing_groups import DrawingObjectRef
from mycad.core.drawing_text import DrawingText, TextStyleTable, move_text, rotate_text, scale_text
from mycad.core.geometric_tolerance_topology import new_curve_point_identities
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    EllipseEntity,
    LineEntity,
    Point2D,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    SketchEntity,
    SplineEntity,
    WorkPlaneFrame,
    sketch_entity_from_mapping,
    sketch_entity_to_mapping,
)
from mycad.core.sketch_edit import move_entities, rotate_entities, scale_entities
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be finite")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _point(value: object, name: str) -> Point2D:
    if not isinstance(value, tuple | list):
        raise ValueError(f"{name} requires two finite coordinates")
    coordinates = cast("tuple[object, ...] | list[object]", value)
    if len(coordinates) != 2:
        raise ValueError(f"{name} requires two finite coordinates")
    return _finite(coordinates[0], name), _finite(coordinates[1], name)


@dataclass(frozen=True, slots=True)
class BlockDefinition:
    """A shared definition whose members use coordinates relative to its base point."""

    definition_id: str
    name: str
    entities: tuple[SketchEntity, ...]
    texts: tuple[DrawingText, ...]

    def __post_init__(self) -> None:
        DrawingObjectRef("block_instance", self.definition_id)
        name = cast("object", self.name)
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ValueError("block name must be nonempty and trimmed")
        entities, texts = tuple(self.entities), tuple(self.texts)
        valid = (
            PointEntity,
            LineEntity,
            PolylineEntity,
            CircleEntity,
            ArcEntity,
            EllipseEntity,
            RectangleEntity,
            SplineEntity,
        )
        if not entities and not texts:
            raise ValueError("block definition must contain geometry or text")
        if any(not isinstance(cast("object", item), valid) for item in entities):
            raise ValueError("block definition only supports geometry and text")
        if any(not isinstance(cast("object", item), DrawingText) for item in texts):
            raise ValueError("block definition only supports geometry and text")
        if len({UUID(item.entity_id).hex for item in entities}) != len(entities):
            raise ValueError("duplicate block geometry identity")
        if len({UUID(item.text_id).hex for item in texts}) != len(texts):
            raise ValueError("duplicate block text identity")
        point_ids = tuple(
            identity
            for item in entities
            if isinstance(item, PolylineEntity | SplineEntity)
            for identity in item.point_ids
        )
        if len(set(point_ids)) != len(point_ids):
            raise ValueError("duplicate block curve point identity")
        object.__setattr__(self, "entities", entities)
        object.__setattr__(self, "texts", texts)

    def to_mapping(self) -> dict[str, object]:
        return {
            "definition_id": self.definition_id,
            "name": self.name,
            "entities": [sketch_entity_to_mapping(item) for item in self.entities],
            "texts": [item.to_mapping() for item in self.texts],
        }

    @classmethod
    def from_mapping(cls, value: object) -> BlockDefinition:
        if not isinstance(value, Mapping):
            raise ValueError("invalid block definition")
        data = cast("Mapping[str, object]", value)
        if set(data) != {"definition_id", "name", "entities", "texts"}:
            raise ValueError("invalid block definition fields")
        entities, texts = data["entities"], data["texts"]
        if not isinstance(entities, list) or not isinstance(texts, list):
            raise ValueError("block members must be arrays")
        return cls(
            cast("str", data["definition_id"]),
            cast("str", data["name"]),
            tuple(sketch_entity_from_mapping(item) for item in cast("list[object]", entities)),
            tuple(DrawingText.from_mapping(item) for item in cast("list[object]", texts)),
        )


@dataclass(frozen=True, slots=True)
class BlockInstance:
    """A placed reference to one block definition with a positive uniform scale."""

    instance_id: str
    definition_id: str
    insertion_mm: Point2D
    rotation_deg: float = 0.0
    scale: float = 1.0
    layer_name: str = "0"

    def __post_init__(self) -> None:
        DrawingObjectRef("block_instance", self.instance_id)
        DrawingObjectRef("block_instance", self.definition_id)
        object.__setattr__(self, "insertion_mm", _point(self.insertion_mm, "block insertion"))
        for name in ("rotation_deg", "scale"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.scale <= 0:
            raise ValueError("block scale must be positive")
        SketchLayer(self.layer_name)

    def to_mapping(self) -> dict[str, object]:
        return {
            "instance_id": self.instance_id,
            "definition_id": self.definition_id,
            "insertion_mm": list(self.insertion_mm),
            "rotation_deg": self.rotation_deg,
            "scale": self.scale,
            "layer_name": self.layer_name,
        }

    @classmethod
    def from_mapping(cls, value: object) -> BlockInstance:
        if not isinstance(value, Mapping):
            raise ValueError("invalid block instance")
        data = cast("Mapping[str, object]", value)
        if set(data) != {
            "instance_id",
            "definition_id",
            "insertion_mm",
            "rotation_deg",
            "scale",
            "layer_name",
        }:
            raise ValueError("invalid block instance fields")
        return cls(
            cast("str", data["instance_id"]),
            cast("str", data["definition_id"]),
            cast("Point2D", data["insertion_mm"]),
            cast("float", data["rotation_deg"]),
            cast("float", data["scale"]),
            cast("str", data["layer_name"]),
        )


@dataclass(frozen=True, slots=True)
class BlockExpansion:
    """Read-only derived members; their identities are scoped to one instance."""

    entities: tuple[SketchEntity, ...]
    texts: tuple[DrawingText, ...]


def assign_new_curve_point_ids(entity: SketchEntity) -> SketchEntity:
    """Give a newly allocated curve identity to every previously anonymous point."""
    if isinstance(entity, PolylineEntity) and not entity.point_ids:
        return replace(
            entity,
            point_ids=new_curve_point_identities(
                entity.entity_id, "polyline", len(entity.points_mm)
            ),
        )
    if isinstance(entity, SplineEntity) and not entity.point_ids:
        return replace(
            entity,
            point_ids=new_curve_point_identities(
                entity.entity_id, "spline", len(entity.control_points_mm)
            ),
        )
    return entity


def make_block_definition(
    definition_id: str,
    name: str,
    sources: tuple[tuple[SketchEntity, WorkPlaneFrame], ...],
    texts: tuple[DrawingText, ...],
    base_mm: Point2D,
) -> BlockDefinition:
    """Normalize same-facing, coplanar source members to a drawing-space base point."""
    x, y = _point(base_mm, "block base")
    drawing_frame = WorkPlaneFrame.xy()
    entities: list[SketchEntity] = []
    for entity, frame in sources:
        if sum(a * b for a, b in zip(frame.normal, drawing_frame.normal, strict=True)) < 1 - 1e-9:
            raise ValueError("块来源必须与图纸平面同向。")
        projected = project_coplanar_entity(entity, frame, drawing_frame)
        entities.append(move_entities((projected,), (projected.entity_id,), (-x, -y))[0])
    return BlockDefinition(
        definition_id, name, tuple(entities), tuple(move_text(item, (-x, -y)) for item in texts)
    )


def validate_block_instance(
    definition: BlockDefinition,
    instance: BlockInstance,
    layers: SketchLayerTable,
    styles: TextStyleTable,
) -> None:
    """Check both effective layers and whether an instance can actually expand."""
    for name in (
        instance.layer_name,
        *(
            instance.layer_name if item.layer_name.casefold() == "0" else item.layer_name
            for item in (*definition.entities, *definition.texts)
        ),
    ):
        layer = layers.get(name)
        if layer.locked or not layer.displayed:
            raise ValueError(f"块使用的图层 {name} 隐藏、冻结或已锁定。")
    try:
        expand_block(definition, instance, styles)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"块实例展开失败：{exc}") from exc


def validate_block_definition_edit(
    definition: BlockDefinition,
    instances: tuple[BlockInstance, ...],
    layers: SketchLayerTable,
    styles: TextStyleTable,
) -> None:
    """Validate affected effective layers for editing or deleting a definition."""
    for item in (*definition.entities, *definition.texts):
        layer = layers.get(item.layer_name)
        if not instances and (layer.locked or not layer.displayed):
            raise ValueError(f"块使用的图层 {item.layer_name} 隐藏、冻结或已锁定。")
    for item in definition.texts:
        styles.get(item.style_id)
    for instance in instances:
        validate_block_instance(definition, instance, layers, styles)


def expand_block(
    definition: BlockDefinition, instance: BlockInstance, styles: TextStyleTable
) -> BlockExpansion:
    """Expand without modifying the shared definition or allocating random IDs."""
    if instance.definition_id != definition.definition_id:
        raise ValueError("block instance references a different definition")

    def identity(kind: str, value: str) -> str:
        return uuid5(NAMESPACE_URL, f"mycad:block:{instance.instance_id}:{kind}:{value}").hex

    entities = definition.entities
    if entities:
        ids = tuple(item.entity_id for item in entities)
        entities = scale_entities(entities, ids, (0, 0), instance.scale)
        entities = rotate_entities(entities, ids, (0, 0), instance.rotation_deg)
        entities = move_entities(
            entities, ids, instance.insertion_mm, preserve_rectangle_order=True
        )
    derived: list[SketchEntity] = []
    for source, entity in zip(definition.entities, entities, strict=True):
        entity = replace(
            entity,
            entity_id=identity("geometry", source.entity_id),
            layer_name=instance.layer_name
            if source.layer_name.casefold() == "0"
            else source.layer_name,
        )
        if isinstance(entity, PolylineEntity | SplineEntity) and entity.point_ids:
            entity = replace(
                entity,
                point_ids=tuple(
                    identity(f"point:{source.entity_id}", point_id) for point_id in entity.point_ids
                ),
            )
        derived.append(entity)
    texts = tuple(
        replace(
            move_text(
                rotate_text(scale_text(item, instance.scale, styles=styles), instance.rotation_deg),
                instance.insertion_mm,
            ),
            text_id=identity("text", item.text_id),
            layer_name=instance.layer_name
            if item.layer_name.casefold() == "0"
            else item.layer_name,
        )
        for item in definition.texts
    )
    return BlockExpansion(tuple(derived), texts)
