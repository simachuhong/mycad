# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Explicit polyline identity mapping for annotation attachment edits.

The editor must supply the mapping from its own topology operation; coordinates
alone cannot prove vertex identity. Command integration must also validate the
source and destination topology and the direction of curved segments.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid5

from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, FeatureControlFrame
from mycad.core.sketch import PolylineEntity, Sketch, SplineEntity
from mycad.core.sketch_constraints import SketchGeometryReference

if TYPE_CHECKING:
    from mycad.core.associative_array import ArrayEntityRef, AssociativeRectArray
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency


def _derive_curve_point_identities(entity_id: str, kind: str, count: int) -> tuple[str, ...]:
    SketchGeometryReference(entity_id, "geometry")
    if kind not in ("polyline", "spline"):
        raise ValueError("曲线身份类型无效。")
    minimum = 2 if kind == "polyline" else 4
    if isinstance(count, bool) or not isinstance(cast("object", count), int) or count < minimum:
        raise ValueError("曲线身份点数量无效。")
    namespace = UUID(entity_id)
    return tuple(uuid5(namespace, f"mycad-{kind}-point-v1:{index}").hex for index in range(count))


def legacy_curve_point_identities(entity_id: str, kind: str, count: int) -> tuple[str, ...]:
    """Derive reproducible legacy upgrade identities; not proof of an edit."""
    return _derive_curve_point_identities(entity_id, kind, count)


def new_curve_point_identities(entity_id: str, kind: str, count: int) -> tuple[str, ...]:
    """Derive point identities for a newly assigned, distinct curve identity."""
    return _derive_curve_point_identities(entity_id, kind, count)


@dataclass(frozen=True, slots=True)
class CurvePointIdentities:
    """Serializable point identities, never sufficient proof of an edit by themselves."""

    entity_id: str
    kind: str
    point_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        SketchGeometryReference(self.entity_id, "geometry")
        if self.kind not in ("polyline", "spline"):
            raise ValueError("曲线身份类型无效。")
        minimum = 2 if self.kind == "polyline" else 4
        if not isinstance(cast("object", self.point_ids), tuple) or len(self.point_ids) < minimum:
            raise ValueError("曲线身份点数量无效。")
        for point_id in self.point_ids:
            if not isinstance(cast("object", point_id), str):
                raise ValueError("曲线点身份无效。")
            try:
                parsed = UUID(point_id)
            except ValueError as exc:
                raise ValueError("曲线点身份无效。") from exc
            if point_id != parsed.hex:
                raise ValueError("曲线点身份必须使用小写 UUID 十六进制格式。")
        if len(set(self.point_ids)) != len(self.point_ids):
            raise ValueError("曲线点身份重复。")

    @classmethod
    def from_legacy(cls, entity_id: str, kind: str, count: int) -> CurvePointIdentities:
        return cls(entity_id, kind, legacy_curve_point_identities(entity_id, kind, count))

    def to_mapping(self) -> dict[str, object]:
        return {
            "version": 1,
            "entity_id": self.entity_id,
            "kind": self.kind,
            "point_ids": list(self.point_ids),
        }

    def validate_entity(self, entity: PolylineEntity | SplineEntity) -> None:
        """Check the stored identity sequence belongs to the supplied curve."""
        if self.entity_id != entity.entity_id:
            raise ValueError("曲线身份图元不一致。")
        if isinstance(entity, PolylineEntity) and self.kind == "polyline":
            count = len(entity.points_mm)
        elif isinstance(entity, SplineEntity) and self.kind == "spline":
            count = len(entity.control_points_mm)
        else:
            raise ValueError("曲线身份类型不匹配。")
        if len(self.point_ids) != count:
            raise ValueError("曲线身份点数量不匹配。")

    @classmethod
    def from_mapping(cls, value: object) -> CurvePointIdentities:
        if not isinstance(value, Mapping):
            raise ValueError("曲线点身份必须是对象。")
        data = cast("Mapping[str, object]", value)
        if set(data) != {"version", "entity_id", "kind", "point_ids"}:
            raise ValueError("曲线点身份字段无效。")
        if type(data["version"]) is not int or data["version"] != 1:
            raise ValueError("曲线点身份版本无效。")
        points = data["point_ids"]
        if not isinstance(points, list | tuple):
            raise ValueError("曲线点身份必须是数组。")
        return cls(
            cast("str", data["entity_id"]),
            cast("str", data["kind"]),
            tuple(cast("Sequence[str]", points)),
        )

    def polyline_map_to(
        self, destination: CurvePointIdentities, *, closed: bool
    ) -> PolylineTopologyMap:
        """Prepare an index map; the calling operation must prove its provenance."""
        if self.kind != "polyline" or destination.kind != "polyline":
            raise ValueError("仅多段线身份可生成多段线拓扑映射。")
        if UUID(self.entity_id) != UUID(destination.entity_id):
            raise ValueError("曲线身份图元不一致。")
        positions = {identity: index for index, identity in enumerate(destination.point_ids)}
        return PolylineTopologyMap(
            self.entity_id,
            tuple(positions.get(identity) for identity in self.point_ids),
            len(destination.point_ids),
            closed,
        )


def prepare_curve_identity_upgrade(
    sketch: Sketch, entity_ids: tuple[str, ...]
) -> tuple[CurvePointIdentities, ...]:
    """Prepare deterministic records for selected legacy curves, without mutation."""
    if not entity_ids or len(set(entity_ids)) != len(entity_ids):
        raise ValueError("升级目标不能为空或重复。")
    entities = {entity.entity_id: entity for entity in sketch.entities}
    records: list[CurvePointIdentities] = []
    for identity in entity_ids:
        entity = entities.get(identity)
        if isinstance(entity, PolylineEntity):
            kind, count = "polyline", len(entity.points_mm)
        elif isinstance(entity, SplineEntity):
            kind, count = "spline", len(entity.control_points_mm)
        else:
            raise ValueError("升级目标必须是存在的多段线或样条。")
        if entity.point_ids:
            raise ValueError("曲线已有点身份，不能重复升级。")
        records.append(CurvePointIdentities.from_legacy(identity, kind, count))
    return tuple(records)


def apply_curve_identity_upgrade(
    sketch: Sketch, base_state_sha256: str, records: tuple[CurvePointIdentities, ...]
) -> Sketch:
    """Verify and prepare an identity-only upgrade for a particular sketch state."""
    if base_state_sha256 != sketch.local_state_digest():
        raise ValueError("曲线身份升级的草图状态已过期。")
    if not records or any(
        not isinstance(cast("object", item), CurvePointIdentities) for item in records
    ):
        raise ValueError("曲线身份升级记录无效。")
    expected = prepare_curve_identity_upgrade(sketch, tuple(item.entity_id for item in records))
    if records != expected:
        raise ValueError("曲线身份升级记录与确定性身份不一致。")
    by_id = {record.entity_id: record for record in records}
    entities = tuple(
        replace(entity, point_ids=by_id[entity.entity_id].point_ids)
        if isinstance(entity, PolylineEntity | SplineEntity) and entity.entity_id in by_id
        else entity
        for entity in sketch.entities
    )
    return replace(sketch, entities=entities)


def validate_curve_identity_preservation(before: Sketch, after: Sketch) -> None:
    """Forbid unverified point identity loss or reassignment in a sketch edit.

    Unchanged identity arrays do not prove that changed coordinates retain their
    original meaning; the existing attachment guards must still run.
    """
    if before.sketch_id != after.sketch_id:
        raise ValueError("曲线身份保护的草图不一致。")
    old = {entity.entity_id: entity for entity in before.entities}
    for entity in after.entities:
        previous = old.get(entity.entity_id)
        if (
            previous is None
            and isinstance(entity, PolylineEntity | SplineEntity)
            and entity.point_ids
        ):
            kind = "polyline" if isinstance(entity, PolylineEntity) else "spline"
            if entity.point_ids != new_curve_point_identities(
                entity.entity_id, kind, len(entity.point_ids)
            ):
                raise ValueError("新曲线点身份不符合该图元的确定性身份。")
            continue
        old_ids = previous.point_ids if isinstance(previous, PolylineEntity | SplineEntity) else ()
        new_ids = entity.point_ids if isinstance(entity, PolylineEntity | SplineEntity) else ()
        if old_ids != new_ids:
            if (
                isinstance(previous, PolylineEntity)
                and isinstance(entity, PolylineEntity)
                and old_ids
                and len(old_ids) == len(new_ids)
                and set(old_ids) == set(new_ids)
            ):
                positions = {identity: index for index, identity in enumerate(new_ids)}
                mapping = PolylineTopologyMap(
                    previous.entity_id,
                    tuple(positions[identity] for identity in old_ids),
                    len(new_ids),
                    previous.closed,
                )
                try:
                    mapping.validate_exact_reorder(previous, entity)
                except ValueError:
                    pass
                else:
                    continue
            raise ValueError("曲线点身份被移除或更改；该操作缺少身份变更证据。")


@dataclass(frozen=True, slots=True)
class PolylineTopologyMap:
    """Map each old vertex index to its new index, or None when deleted."""

    entity_id: str
    old_to_new: tuple[int | None, ...]
    new_count: int
    closed: bool

    def __post_init__(self) -> None:
        SketchGeometryReference(self.entity_id, "geometry")
        if not isinstance(cast("object", self.closed), bool):
            raise ValueError("多段线拓扑闭合状态无效。")
        minimum = 3 if self.closed else 2
        if (
            isinstance(self.new_count, bool)
            or not isinstance(cast("object", self.new_count), int)
            or self.new_count < minimum
            or not isinstance(cast("object", self.old_to_new), tuple)
            or len(self.old_to_new) < minimum
        ):
            raise ValueError("多段线拓扑顶点数量无效。")
        seen: set[int] = set()
        for target in self.old_to_new:
            if target is None:
                continue
            if (
                isinstance(target, bool)
                or not isinstance(cast("object", target), int)
                or not 0 <= target < self.new_count
                or target in seen
            ):
                raise ValueError("多段线拓扑顶点身份映射无效。")
            seen.add(target)

    def remap(self, attachment: DatumAttachment) -> DatumAttachment:
        """Remap a point or segment without guessing a deleted or split edge."""
        reference = attachment.reference
        if reference.entity_id != self.entity_id:
            raise ValueError("附着目标与拓扑身份不匹配。")
        if attachment.segment_kind is not None or attachment.curve_kind is not None:
            raise ValueError("此附着不是多段线拓扑引用。")
        old_count = len(self.old_to_new)
        if reference.kind in ("start", "end", "vertex"):
            index = (
                0
                if reference.kind == "start"
                else old_count - 1
                if reference.kind == "end"
                else reference.index
            )
            if index is None or index >= old_count or self.old_to_new[index] is None:
                raise ValueError("附着顶点已删除或身份无法确认。")
            target = self.old_to_new[index]
            if reference.kind == "start" and target == 0:
                updated = SketchGeometryReference(self.entity_id, "start")
            elif reference.kind == "end" and target == self.new_count - 1:
                updated = SketchGeometryReference(self.entity_id, "end")
            else:
                updated = SketchGeometryReference(self.entity_id, "vertex", target)
            return replace(attachment, reference=updated)
        if reference.kind != "segment" or reference.index is None:
            raise ValueError("此附着不是多段线顶点或线段引用。")
        old_segments = old_count if self.closed else old_count - 1
        new_segments = self.new_count if self.closed else self.new_count - 1
        if attachment.segment_count != old_segments or reference.index >= old_segments:
            raise ValueError("原多段线线段数量不匹配。")
        start = self.old_to_new[reference.index]
        end = self.old_to_new[(reference.index + 1) % old_count]
        if start is None or end is None:
            raise ValueError("附着线段的顶点已删除。")
        if start < new_segments and (start + 1) % self.new_count == end:
            index, reversed_segment = start, False
        elif end < new_segments and (end + 1) % self.new_count == start:
            index, reversed_segment = end, True
        else:
            raise ValueError("附着线段已拆分或身份无法确认。")
        parameter = attachment.parameter
        if parameter is None:
            raise ValueError("附着线段缺少参数。")
        return replace(
            attachment,
            reference=SketchGeometryReference(self.entity_id, "segment", index),
            parameter=1.0 - parameter if reversed_segment else parameter,
            segment_count=new_segments,
        )

    def remap_checked(
        self,
        attachment: DatumAttachment,
        source: PolylineEntity,
        destination: PolylineEntity,
    ) -> DatumAttachment:
        """Check structural evidence before applying an operation-supplied map.

        These checks do not prove vertex identity; the editing operation must
        supply that provenance. Curvature changes require a separate mapping.
        """
        self.validate_entities(source, destination)
        updated = self.remap(attachment)
        old_index = attachment.reference.index
        new_index = updated.reference.index
        if (
            attachment.reference.kind == "segment"
            and old_index is not None
            and new_index is not None
        ):
            old_bulge = source.bulges[old_index] if source.bulges else 0.0
            new_bulge = destination.bulges[new_index] if destination.bulges else 0.0
            forward = self.old_to_new[old_index] == new_index
            if new_bulge != (old_bulge if forward else -old_bulge):
                raise ValueError("附着线段的圆弧方向或曲率已变化，无法确认映射。")
        return updated

    def validate_entities(self, source: PolylineEntity, destination: PolylineEntity) -> None:
        """Reject topology evidence that is inconsistent with the two entities."""
        if (
            source.entity_id != self.entity_id
            or destination.entity_id != self.entity_id
            or source.closed != self.closed
            or destination.closed != self.closed
            or len(source.points_mm) != len(self.old_to_new)
            or len(destination.points_mm) != self.new_count
        ):
            raise ValueError("多段线拓扑映射与原图元或新图元不一致。")

    def validate_exact_reorder(self, source: PolylineEntity, destination: PolylineEntity) -> None:
        """Verify an exact reorder without relying on an untrusted identity claim."""
        self.validate_entities(source, destination)
        count = len(source.points_mm)
        if self.new_count != count or len(set(source.points_mm)) != count:
            raise ValueError("顶点数量或坐标不能唯一确定身份。")
        for old_index, new_index in enumerate(self.old_to_new):
            if new_index is None or source.points_mm[old_index] != destination.points_mm[new_index]:
                raise ValueError("拓扑映射与顶点坐标不一致。")
            if (source.point_ids or destination.point_ids) and (
                not source.point_ids
                or not destination.point_ids
                or source.point_ids[old_index] != destination.point_ids[new_index]
            ):
                raise ValueError("多段线点身份与拓扑映射不一致。")
        segments = count if self.closed else count - 1
        for old_index in range(segments):
            start = self.old_to_new[old_index]
            end = self.old_to_new[(old_index + 1) % count]
            if start is None or end is None:
                raise ValueError("拓扑映射缺少线段端点。")
            if start < segments and (start + 1) % count == end:
                target, reversed_segment = start, False
            elif end < segments and (end + 1) % count == start:
                target, reversed_segment = end, True
            else:
                raise ValueError("拓扑映射改变了线段连接。")
            old_bulge = source.bulges[old_index] if source.bulges else 0.0
            new_bulge = destination.bulges[target] if destination.bulges else 0.0
            if new_bulge != (-old_bulge if reversed_segment else old_bulge):
                raise ValueError("拓扑映射改变了线段曲率。")

    def to_mapping(self) -> dict[str, object]:
        """Return plain command data, including deleted vertex entries."""
        return {
            "entity_id": self.entity_id,
            "old_to_new": list(self.old_to_new),
            "new_count": self.new_count,
            "closed": self.closed,
        }

    @classmethod
    def from_mapping(cls, value: object) -> PolylineTopologyMap:
        if not isinstance(value, Mapping):
            raise ValueError("多段线拓扑映射必须是对象。")
        data = cast("Mapping[str, object]", value)
        if set(data) != {"entity_id", "old_to_new", "new_count", "closed"}:
            raise ValueError("多段线拓扑映射字段无效。")
        indices = data["old_to_new"]
        if not isinstance(indices, list | tuple):
            raise ValueError("多段线拓扑顶点映射必须是数组。")
        return cls(
            cast("str", data["entity_id"]),
            tuple(cast("Sequence[int | None]", indices)),
            cast("int", data["new_count"]),
            cast("bool", data["closed"]),
        )


def remap_annotations(
    before: Sketch,
    after: Sketch,
    mappings: tuple[PolylineTopologyMap, ...],
    datums: tuple[DatumIdentifier, ...],
    frames: tuple[FeatureControlFrame, ...],
) -> tuple[tuple[DatumIdentifier, ...], tuple[FeatureControlFrame, ...]]:
    """Prepare annotation references without mutating either sketch or the inputs.

    Only exact reorders with unique coordinates are accepted. This does not
    modify constraint, array or tangency references; the caller must check
    those before committing.
    """
    if before.sketch_id != after.sketch_id:
        raise ValueError("拓扑映射的草图身份不匹配。")
    by_id = {item.entity_id: item for item in mappings}
    if len(by_id) != len(mappings):
        raise ValueError("拓扑映射包含重复图元身份。")
    sources = {entity.entity_id: entity for entity in before.entities}
    destinations = {entity.entity_id: entity for entity in after.entities}
    pairs: dict[str, tuple[PolylineEntity, PolylineEntity]] = {}
    for identity, mapping in by_id.items():
        source, destination = sources.get(identity), destinations.get(identity)
        if not isinstance(source, PolylineEntity) or not isinstance(destination, PolylineEntity):
            raise ValueError("拓扑映射必须指向修订前后的同一多段线。")
        mapping.validate_exact_reorder(source, destination)
        pairs[identity] = (source, destination)

    def mapped(attachment: DatumAttachment | None) -> DatumAttachment | None:
        if attachment is None or attachment.sketch_id != before.sketch_id:
            return attachment
        identity = attachment.reference.entity_id
        if identity not in by_id:
            return attachment
        source, destination = pairs[identity]
        return by_id[identity].remap_checked(attachment, source, destination)

    updated_datums = tuple(replace(item, attachment=mapped(item.attachment)) for item in datums)
    updated_frames = tuple(
        replace(item, leader_attachment=mapped(item.leader_attachment)) for item in frames
    )
    return updated_datums, updated_frames


def associative_topology_entities(
    arrays: Sequence[AssociativeRectArray], relations: Sequence[CrossSketchTangency]
) -> frozenset[tuple[str, str]]:
    """Collect all geometry identities participating in arrays or tangencies."""
    identities: set[tuple[str, str]] = set()

    def add(ref: ArrayEntityRef | None) -> None:
        if ref is not None:
            identities.add((ref.sketch_id, ref.entity_id))

    for relation in relations:
        identities.add((relation.first.sketch_id, relation.first.entity_id))
        identities.add((relation.second.sketch_id, relation.second.entity_id))
    for array in arrays:
        for source in array.sources:
            add(source)
        if array.base_point is not None:
            add(array.base_point.source)
        for member in array.members:
            add(member.source)
            add(member.target)
            if member.replacement is not None:
                add(member.replacement.source)
                add(member.replacement.anchor_source)
        for output in array.extra_outputs:
            add(output.source)
            add(output.target)
            add(output.anchor_source)
    return frozenset(identities)


def simple_array_reorder_members(
    arrays: Sequence[AssociativeRectArray],
    sources: frozenset[tuple[str, str]],
    *,
    stable_anchor_sources: frozenset[tuple[str, str]] = frozenset(),
    stable_base_arrays: frozenset[str] = frozenset(),
    allow_stable_replacements: bool = False,
    allow_stable_extra_outputs: bool = False,
    allow_reordered_extra_outputs: bool = False,
    allow_independent_extra_sources: bool = False,
    allow_replacement_source: bool = False,
    allow_simultaneous_replacements: bool = False,
    allow_internal_generated_sources: bool = False,
    allow_mixed_replacement_extras: bool = False,
) -> tuple[tuple[ArrayEntityRef, ArrayEntityRef], ...]:
    """Identify array members whose rotation anchor is proven unchanged.

    Dynamic bases and replacements require explicit proofs; changed rotation
    anchors and chained targets are rejected instead of guessed.
    """
    involved = associative_topology_entities(arrays, ()) & sources
    source_refs = {
        (source.sketch_id, source.entity_id) for array in arrays for source in array.sources
    }
    independent_refs: set[tuple[str, str]] = (
        {
            (output.source.sketch_id, output.source.entity_id)
            for array in arrays
            for output in array.extra_outputs
        }
        if allow_independent_extra_sources
        else set()
    )
    replacement_refs: set[tuple[str, str]] = (
        {
            (member.replacement.source.sketch_id, member.replacement.source.entity_id)
            for array in arrays
            for member in array.members
            if member.replacement is not None
        }
        if allow_replacement_source
        else set()
    )
    independent_refs |= replacement_refs
    if not involved.issubset(source_refs | independent_refs):
        raise ValueError("阵列成员或替换来源不能直接重排。")
    for array in arrays:
        array_sources = {(ref.sketch_id, ref.entity_id) for ref in array.sources}
        allowed: set[tuple[str, str]] = array_sources | (
            {(output.source.sketch_id, output.source.entity_id) for output in array.extra_outputs}
            if allow_independent_extra_sources
            else set()
        )
        if allow_replacement_source:
            allowed |= {
                (member.replacement.source.sketch_id, member.replacement.source.entity_id)
                for member in array.members
                if member.replacement is not None
            }
        if (associative_topology_entities((array,), ()) & sources) - allowed:
            raise ValueError("阵列成员或替换来源不能直接重排。")
        if not allow_internal_generated_sources and any(
            (member.target.sketch_id, member.target.entity_id) in sources
            for member in array.members
        ):
            raise ValueError("阵列成员不能直接重排。")
        if not allow_internal_generated_sources and any(
            (output.target.sketch_id, output.target.entity_id) in sources
            for output in array.extra_outputs
        ):
            raise ValueError("阵列额外输出不能直接重排。")
    outputs: list[tuple[ArrayEntityRef, ArrayEntityRef]] = []
    for array in arrays:
        selected = {
            source for source in array.sources if (source.sketch_id, source.entity_id) in sources
        }
        selected_extras = tuple(
            output.source
            for output in array.extra_outputs
            if (output.source.sketch_id, output.source.entity_id) in sources
        )
        selected_replacements = tuple(
            member.replacement.source
            for member in array.members
            if allow_replacement_source
            and member.replacement is not None
            and (member.replacement.source.sketch_id, member.replacement.source.entity_id)
            in sources
        )
        if not selected and not selected_extras and not selected_replacements:
            continue
        if (
            (
                bool(selected_replacements)
                and bool(array.extra_outputs)
                and not allow_mixed_replacement_extras
            )
            or any(
                member.source in selected
                and member.replacement is not None
                and member.replacement.source in selected_replacements
                and (
                    not allow_simultaneous_replacements
                    or (
                        member.replacement.source.sketch_id,
                        member.replacement.source.entity_id,
                    )
                    not in stable_anchor_sources
                )
                for member in array.members
            )
            or (
                array.base_point is not None
                and array.base_point.source is not None
                and array.array_id not in stable_base_arrays
            )
            or (array.extra_outputs and not allow_stable_extra_outputs)
            or any(
                (
                    (output.source.sketch_id, output.source.entity_id) in sources
                    and not allow_reordered_extra_outputs
                )
                or (
                    output.anchor_source in selected
                    and (output.anchor_source.sketch_id, output.anchor_source.entity_id)
                    not in stable_anchor_sources
                )
                for output in array.extra_outputs
            )
            or any(
                (
                    member.rotation_deg != 0
                    and member.source in selected
                    and (member.source.sketch_id, member.source.entity_id)
                    not in stable_anchor_sources
                )
                or (
                    member.replacement is not None
                    and (
                        not allow_stable_replacements
                        or (
                            member.source in selected
                            and (member.source.sketch_id, member.source.entity_id)
                            not in stable_anchor_sources
                        )
                        or (
                            member.source not in selected
                            and (
                                (
                                    (
                                        member.replacement.source.sketch_id,
                                        member.replacement.source.entity_id,
                                    )
                                    in sources
                                    and (
                                        not allow_replacement_source
                                        or (
                                            member.replacement.source.sketch_id,
                                            member.replacement.source.entity_id,
                                        )
                                        not in stable_anchor_sources
                                    )
                                )
                                or (
                                    member.replacement.anchor_source is not None
                                    and (
                                        member.replacement.anchor_source.sketch_id,
                                        member.replacement.anchor_source.entity_id,
                                    )
                                    in sources
                                )
                            )
                        )
                    )
                )
                or member.erased_index is not None
                for member in array.members
            )
        ):
            raise ValueError("该阵列的基点、旋转或替换需要单独重绑定。")
        for member in array.members:
            if member.source in selected or (
                member.replacement is not None
                and member.replacement.source in selected_replacements
            ):
                target = (member.target.sketch_id, member.target.entity_id)
                if target in source_refs:
                    raise ValueError("链式阵列成员需要单独重绑定。")
                if any(
                    other is not array and target in associative_topology_entities((other,), ())
                    for other in arrays
                ):
                    raise ValueError("阵列成员还有其他关联，需要单独重绑定。")
                outputs.append(
                    (
                        member.replacement.source
                        if member.replacement is not None
                        and member.replacement.source in selected_replacements
                        else member.source,
                        member.target,
                    )
                )
        for output in array.extra_outputs:
            target = (output.target.sketch_id, output.target.entity_id)
            if target in source_refs or any(
                other is not array and target in associative_topology_entities((other,), ())
                for other in arrays
            ):
                raise ValueError("阵列额外输出还有其他关联，需要单独重绑定。")
            outputs.append(
                (
                    output.source
                    if (output.source.sketch_id, output.source.entity_id) in sources
                    else output.anchor_source
                    if output.anchor_source in selected
                    else next(
                        (source for source in array.sources if source in selected),
                        selected_extras[0] if selected_extras else output.anchor_source,
                    ),
                    output.target,
                )
            )
    return tuple(outputs)


def has_internal_reorder_dependents(
    arrays: Sequence[AssociativeRectArray],
    edges: Sequence[tuple[ArrayEntityRef, ArrayEntityRef]],
) -> bool:
    """Detect generated objects used as geometry sources in their owning array."""
    targets = {target for _source, target in edges}
    return any(
        generated in targets
        and (
            any(
                other.replacement is not None and other.replacement.source == generated
                for other in array.members
            )
            or any(output.source == generated for output in array.extra_outputs)
        )
        for array in arrays
        for generated in (
            *(member.target for member in array.members),
            *(output.target for output in array.extra_outputs),
        )
    )


def simple_array_reorder_chain(
    arrays: Sequence[AssociativeRectArray],
    sources: frozenset[tuple[str, str]],
    *,
    stable_anchor_sources: frozenset[tuple[str, str]] = frozenset(),
    allow_stable_bases: bool = False,
    stable_base_vertices: Mapping[tuple[str, str], frozenset[int]] | None = None,
    allow_base_rebinding: bool = False,
    allow_unchanged_replacements: bool = False,
    allow_reordered_replacements: bool = False,
    allow_extra_outputs: bool = False,
    allow_simultaneous_replacements: bool = False,
    defer_affected_dependencies: bool = False,
    allow_mixed_replacement_extras: bool = False,
    known_stable_base_arrays: frozenset[str] = frozenset(),
) -> tuple[tuple[ArrayEntityRef, ArrayEntityRef], ...]:
    """Order proven-simple array edges; geometry still needs validation per edge."""
    from mycad.core.associative_array import validate_array_network

    validate_array_network(tuple(arrays))
    generated = {
        (member.target.sketch_id, member.target.entity_id)
        for array in arrays
        for member in array.members
    } | {
        (output.target.sketch_id, output.target.entity_id)
        for array in arrays
        for output in array.extra_outputs
    }
    if sources & generated:
        raise ValueError("阵列成员不能直接重排。")
    array_sources = {
        (source.sketch_id, source.entity_id) for array in arrays for source in array.sources
    }
    if allow_reordered_replacements:
        array_sources |= {
            (member.replacement.source.sketch_id, member.replacement.source.entity_id)
            for array in arrays
            for member in array.members
            if member.replacement is not None
        }
    if allow_extra_outputs:
        array_sources |= {
            (output.source.sketch_id, output.source.entity_id)
            for array in arrays
            for output in array.extra_outputs
        }
    if (associative_topology_entities(arrays, ()) & sources) - array_sources:
        raise ValueError("阵列来源角色需要单独重绑定。")
    pending = set(sources)
    affected = set(sources)
    if defer_affected_dependencies:
        while True:
            previous = len(affected)
            for array in arrays:
                for member in array.members:
                    dependencies = [member.source]
                    if member.replacement is not None:
                        dependencies.append(member.replacement.source)
                        if member.replacement.anchor_source is not None:
                            dependencies.append(member.replacement.anchor_source)
                    if any((ref.sketch_id, ref.entity_id) in affected for ref in dependencies):
                        affected.add((member.target.sketch_id, member.target.entity_id))
                for output in array.extra_outputs:
                    if any(
                        (ref.sketch_id, ref.entity_id) in affected
                        for ref in (output.source, output.anchor_source)
                    ):
                        affected.add((output.target.sketch_id, output.target.entity_id))
            if len(affected) == previous:
                break
    ready = set(sources)
    stable = set(stable_anchor_sources & sources)
    stable_vertices = {
        key: frozenset((0,)) | (stable_base_vertices or {}).get(key, frozenset())
        if key in stable
        else (stable_base_vertices or {}).get(key, frozenset())
        for key in sources
    }
    edges: list[tuple[ArrayEntityRef, ArrayEntityRef]] = []
    planned: set[tuple[str, str]] = set()
    while pending:
        following: set[tuple[str, str]] = set()
        deferred = False
        for array in arrays:
            base = array.base_point
            stable_base = (
                allow_stable_bases
                and base is not None
                and base.source is not None
                and base.reference is not None
                and base.reference.kind == "vertex"
                and base.reference.index
                in stable_vertices.get((base.source.sketch_id, base.source.entity_id), frozenset())
            ) or (
                defer_affected_dependencies
                and array.array_id in known_stable_base_arrays
                and base is not None
                and base.source is not None
                and (base.source.sketch_id, base.source.entity_id) not in affected
            )
            rebind_base = (
                allow_base_rebinding
                and base is not None
                and base.source is not None
                and base.reference is not None
                and base.reference.kind in ("start", "end", "vertex")
                and (base.reference.kind != "vertex" or base.reference.index is not None)
                and (
                    (base.source.sketch_id, base.source.entity_id) in pending
                    or (
                        defer_affected_dependencies
                        and (base.source.sketch_id, base.source.entity_id) in affected
                        and (base.source.sketch_id, base.source.entity_id) in ready
                    )
                )
            )
            special_sources = (
                *((base.source,) if base is not None and not (stable_base or rebind_base) else ()),
                *(
                    ref
                    for member in array.members
                    if member.replacement is not None
                    for ref in (
                        None if allow_reordered_replacements else member.replacement.source,
                        member.replacement.anchor_source,
                    )
                ),
                *(
                    ref
                    for output in array.extra_outputs
                    for ref in (
                        None if allow_extra_outputs else output.source,
                        None if allow_extra_outputs else output.anchor_source,
                    )
                ),
            )
            if any(
                ref is not None and (ref.sketch_id, ref.entity_id) in pending
                for ref in special_sources
            ):
                raise ValueError("阵列基点、替换或额外输出关联需要单独重绑定。")
            selected = frozenset(
                (ref.sketch_id, ref.entity_id)
                for ref in array.sources
                if (ref.sketch_id, ref.entity_id) in pending
            )
            if allow_reordered_replacements:
                selected |= frozenset(
                    (member.replacement.source.sketch_id, member.replacement.source.entity_id)
                    for member in array.members
                    if member.replacement is not None
                    and (member.replacement.source.sketch_id, member.replacement.source.entity_id)
                    in pending
                    and (
                        not defer_affected_dependencies
                        or (member.target.sketch_id, member.target.entity_id) not in planned
                    )
                )
            if allow_extra_outputs:
                selected |= frozenset(
                    (output.source.sketch_id, output.source.entity_id)
                    for output in array.extra_outputs
                    if (output.source.sketch_id, output.source.entity_id) in pending
                    and (
                        not defer_affected_dependencies
                        or (output.target.sketch_id, output.target.entity_id) not in planned
                    )
                )
            if not selected:
                continue
            if (
                defer_affected_dependencies
                and base is not None
                and base.source is not None
                and (base.source.sketch_id, base.source.entity_id) in affected
                and (base.source.sketch_id, base.source.entity_id) not in ready
            ):
                deferred = True
                continue
            for source, target in simple_array_reorder_members(
                (array,),
                selected,
                stable_anchor_sources=frozenset(stable),
                stable_base_arrays=(
                    frozenset((array.array_id,)) if stable_base or rebind_base else frozenset()
                ),
                allow_stable_replacements=allow_unchanged_replacements,
                allow_replacement_source=allow_reordered_replacements,
                allow_stable_extra_outputs=allow_extra_outputs,
                allow_reordered_extra_outputs=allow_extra_outputs,
                allow_independent_extra_sources=allow_extra_outputs,
                allow_simultaneous_replacements=allow_simultaneous_replacements,
                allow_internal_generated_sources=defer_affected_dependencies,
                allow_mixed_replacement_extras=allow_mixed_replacement_extras,
            ):
                target_key = (target.sketch_id, target.entity_id)
                if allow_extra_outputs:
                    output = next(
                        (item for item in array.extra_outputs if item.target == target), None
                    )
                    if output is not None and not (
                        (output.source.sketch_id, output.source.entity_id) in pending
                        or (output.anchor_source.sketch_id, output.anchor_source.entity_id)
                        in pending
                    ):
                        continue
                else:
                    output = None
                if defer_affected_dependencies:
                    member = next((item for item in array.members if item.target == target), None)
                    geometry_source = (
                        output.source
                        if output is not None
                        else member.replacement.source
                        if member is not None and member.replacement is not None
                        else source
                    )
                    anchor_source = (
                        output.anchor_source
                        if output is not None
                        else member.source
                        if member is not None and member.replacement is not None
                        else None
                    )
                    dependencies = (
                        (geometry_source,)
                        if anchor_source is None
                        else (geometry_source, anchor_source)
                    )
                    if any(
                        (ref.sketch_id, ref.entity_id) in affected
                        and (ref.sketch_id, ref.entity_id) not in ready
                        for ref in dependencies
                    ):
                        deferred = True
                        continue
                    if anchor_source is not None:
                        anchor_key = (anchor_source.sketch_id, anchor_source.entity_id)
                        if anchor_key in affected and anchor_key not in stable:
                            raise ValueError("阵列锚点变化，无法证明替换或额外输出。")
                    if (geometry_source.sketch_id, geometry_source.entity_id) in affected:
                        source = geometry_source
                if allow_simultaneous_replacements and target_key in planned:
                    if defer_affected_dependencies:
                        continue
                    raise ValueError("链式阵列目标重复或依赖顺序不明确。")
                for other in arrays:
                    if other is array:
                        continue
                    if (
                        target_key in associative_topology_entities((other,), ())
                        and target not in other.sources
                        and not (
                            allow_reordered_replacements
                            and any(
                                member.replacement is not None
                                and member.replacement.source == target
                                for member in other.members
                            )
                        )
                        and not (
                            allow_extra_outputs
                            and any(output.source == target for output in other.extra_outputs)
                        )
                    ):
                        raise ValueError("阵列成员还有其他关联，需要单独重绑定。")
                edges.append((source, target))
                planned.add(target_key)
                following.add(target_key)
                ready.add(target_key)
                if (source.sketch_id, source.entity_id) in stable:
                    stable.add(target_key)
                stable_vertices[target_key] = stable_vertices.get(
                    (source.sketch_id, source.entity_id), frozenset()
                )
        if deferred and not following:
            raise ValueError("链式阵列依赖未能按顺序证明。")
        pending = following
    return tuple(edges)


def stable_array_base_ids(
    arrays: Sequence[AssociativeRectArray],
    before: Sequence[Sketch],
    after: Sequence[Sketch],
    mappings: Mapping[tuple[str, str], PolylineTopologyMap],
) -> frozenset[str]:
    """Prove dynamic bases retain both the same point identity and coordinates."""
    from mycad.core.sketch_references import resolve_point_reference

    old_sketches = {item.sketch_id: item for item in before}
    new_sketches = {item.sketch_id: item for item in after}
    result: set[str] = set()
    for array in arrays:
        base = array.base_point
        if base is None or base.source is None or base.reference is None:
            continue
        key = (base.source.sketch_id, base.source.entity_id)
        old_sketch, new_sketch = old_sketches.get(key[0]), new_sketches.get(key[0])
        if old_sketch is None or new_sketch is None or old_sketch.frame != new_sketch.frame:
            continue
        old = next((item for item in old_sketch.entities if item.entity_id == key[1]), None)
        new = next((item for item in new_sketch.entities if item.entity_id == key[1]), None)
        if old is None or new is None:
            continue
        if old != new:
            mapping = mappings.get(key)
            if (
                mapping is None
                or not isinstance(old, PolylineEntity)
                or not isinstance(new, PolylineEntity)
            ):
                continue
            try:
                mapping.validate_exact_reorder(old, new)
                attachment = DatumAttachment(key[0], base.reference)
                if mapping.remap_checked(attachment, old, new).reference != base.reference:
                    continue
            except ValueError:
                continue
        old_point = resolve_point_reference(base.reference, {key[1]: old})
        new_point = resolve_point_reference(base.reference, {key[1]: new})
        if old_point is not None and old_point == new_point:
            result.add(array.array_id)
    return frozenset(result)


def rebind_array_base(
    array: AssociativeRectArray,
    before: Sketch,
    after: Sketch,
    mapping: PolylineTopologyMap,
) -> AssociativeRectArray:
    """Prepare a base reference update only when the identical point is proven."""
    from mycad.core.sketch_references import resolve_point_reference

    base = array.base_point
    if (
        base is None
        or base.source is None
        or base.reference is None
        or before.sketch_id != after.sketch_id
        or before.frame != after.frame
        or base.source.sketch_id != before.sketch_id
        or base.source.entity_id != mapping.entity_id
    ):
        raise ValueError("阵列基点与拓扑映射不匹配。")
    old = next((item for item in before.entities if item.entity_id == mapping.entity_id), None)
    new = next((item for item in after.entities if item.entity_id == mapping.entity_id), None)
    if not isinstance(old, PolylineEntity) or not isinstance(new, PolylineEntity):
        raise ValueError("阵列基点来源不是同一多段线。")
    mapping.validate_exact_reorder(old, new)
    original = DatumAttachment(before.sketch_id, base.reference)
    mapped = mapping.remap_checked(original, old, new)
    old_point = resolve_point_reference(base.reference, {mapping.entity_id: old})
    new_point = resolve_point_reference(mapped.reference, {mapping.entity_id: new})
    if old_point is None or old_point != new_point:
        raise ValueError("阵列基点位置无法确认。")
    return replace(array, base_point=replace(base, reference=mapped.reference))


def rebind_proven_array_tangencies(
    previous: Sequence[Sketch],
    updated: Sequence[Sketch],
    relations: Sequence[CrossSketchTangency],
    mappings: Mapping[tuple[str, str], PolylineTopologyMap],
    *,
    allow_reversed_segments: bool = False,
) -> tuple[CrossSketchTangency, ...]:
    """Rebind only exact, uniquely retained, directed generated segments."""
    from mycad.core.cross_sketch_tangency import unique_unchanged_polyline_segment

    old_sketches = {sketch.sketch_id: sketch for sketch in previous}
    new_sketches = {sketch.sketch_id: sketch for sketch in updated}
    if len(old_sketches) != len(previous) or len(new_sketches) != len(updated):
        raise ValueError("相切重绑定草图身份重复。")
    entities: dict[tuple[str, str], tuple[PolylineEntity, PolylineEntity]] = {}
    for key, mapping in mappings.items():
        sketch_id, entity_id = key
        before, after = old_sketches.get(sketch_id), new_sketches.get(sketch_id)
        if before is None or after is None or before.frame != after.frame:
            raise ValueError("相切重绑定草图不存在或坐标系已变化。")
        old = next((item for item in before.entities if item.entity_id == entity_id), None)
        new = next((item for item in after.entities if item.entity_id == entity_id), None)
        if (
            not isinstance(old, PolylineEntity)
            or not isinstance(new, PolylineEntity)
            or mapping.entity_id != entity_id
        ):
            raise ValueError("相切重绑定多段线无效。")
        mapping.validate_exact_reorder(old, new)
        if replace(old, points_mm=new.points_mm, bulges=new.bulges, point_ids=new.point_ids) != new:
            raise ValueError("相切重绑定包含未经证明的图元属性变化。")
        entities[key] = (old, new)

    result: list[CrossSketchTangency] = []
    for relation in relations:
        refs: list[CrossSketchRef] = []
        endpoints = [relation.first_endpoint, relation.second_endpoint]
        branch = relation.branch
        for position, ref in enumerate((relation.first, relation.second)):
            key = (ref.sketch_id, ref.entity_id)
            pair = entities.get(key)
            if pair is None:
                before, after = old_sketches.get(ref.sketch_id), new_sketches.get(ref.sketch_id)
                if before is None or after is None or before.frame != after.frame:
                    raise ValueError("相切重绑定引用的草图不存在或坐标系已变化。")
                old = next(
                    (item for item in before.entities if item.entity_id == ref.entity_id), None
                )
                new = next(
                    (item for item in after.entities if item.entity_id == ref.entity_id), None
                )
                if old is None or old != new:
                    raise ValueError("相切重绑定包含未经证明的图元变化。")
                refs.append(ref)
                continue
            if ref.segment_index is None:
                raise ValueError("阵列多段线相切必须引用具体线段。")
            index = unique_unchanged_polyline_segment(*pair, ref.segment_index)
            if index is None and allow_reversed_segments:
                old, new = pair
                mapping = mappings[key]
                old_segments = len(old.points_mm) if old.closed else len(old.points_mm) - 1
                if not 0 <= ref.segment_index < old_segments:
                    raise ValueError("相切线段索引无效。")
                candidate = mapping.old_to_new[(ref.segment_index + 1) % len(old.points_mm)]
                if candidate is not None:
                    old_start = old.points_mm[ref.segment_index]
                    old_end = old.points_mm[(ref.segment_index + 1) % len(old.points_mm)]
                    new_segments = len(new.points_mm) if new.closed else len(new.points_mm) - 1
                    if (
                        candidate < new_segments
                        and new.points_mm[candidate] == old_end
                        and new.points_mm[(candidate + 1) % len(new.points_mm)] == old_start
                    ):
                        index = candidate
                        endpoint = endpoints[position]
                        if endpoint is not None:
                            endpoints[position] = "end" if endpoint == "start" else "start"
                        bulge = old.bulges[ref.segment_index] if old.bulges else 0.0
                        if not bulge and branch in ("line_left", "line_right"):
                            branch = "line_right" if branch == "line_left" else "line_left"
            if index is None:
                raise ValueError("无法证明阵列成员的相切段方向和几何保持不变。")
            refs.append(replace(ref, segment_index=index))
        result.append(
            replace(
                relation,
                first=refs[0],
                second=refs[1],
                first_endpoint=endpoints[0],
                second_endpoint=endpoints[1],
                branch=branch,
            )
        )
    return tuple(result)


def validate_topology_constraint_rebinding(
    before: Sketch, after: Sketch, entity_ids: frozenset[str]
) -> None:
    """Allow only existing constraints proven to reference the same directed geometry."""
    if not any(
        ref.entity_id in entity_ids
        for constraint in (*before.constraints, *after.constraints)
        for ref in constraint.references
    ):
        return
    from mycad.core.cross_sketch_tangency import rebind_unchanged_user_polyline_constraints

    try:
        expected = rebind_unchanged_user_polyline_constraints(before, after, include_inferred=True)
    except ValueError as exc:
        raise ValueError("多段线重排无法保留相关约束。") from exc
    if expected != after.constraints:
        raise ValueError("多段线重排的约束引用未按原几何重绑定。")
