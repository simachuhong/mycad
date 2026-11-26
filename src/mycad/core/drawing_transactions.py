# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Prepare restricted collection operations from an immutable candidate view."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from typing import cast
from uuid import uuid4

from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    RectangleTransformEvidence,
    project_coplanar_rotation,
    project_coplanar_vector,
    rebind_committed_tangencies_for_edit,
    rebind_rectangle_constraints_for_sketch,
    tangent_endpoints_satisfied,
    tangent_entity_curve,
)
from mycad.core.drawing_blocks import BlockInstance, assign_new_curve_point_ids
from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef, expand_group_selection
from mycad.core.drawing_object_refs import copy_complete_groups, remap_group_members
from mycad.core.drawing_text import mirror_text, move_text, rotate_text, scale_text
from mycad.core.exceptions import ValidationError
from mycad.core.fillet_curves import tangent_on_curves
from mycad.core.geometric_tolerance import AnnotationAttachment, DatumAttachment, DatumIdentifier
from mycad.core.geometric_tolerance_copy import copy_geometric_annotations, translate_frame
from mycad.core.replay_proposal import ReplayAppend
from mycad.core.sketch import LineEntity, PolylineEntity, RectangleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import DIMENSION_KINDS, SketchConstraint
from mycad.core.sketch_edit import (
    copy_entities,
    mirror_entities,
    move_entities,
    rotate_entities,
    scale_entities,
)
from mycad.core.sketch_references import resolve_point_reference


def require_independent_geometry_edits(
    groups: tuple[DrawingGroup, ...], before: tuple[Sketch, ...], after: tuple[Sketch, ...]
) -> None:
    """Reject a solver edit that would independently change a selectable group member."""
    updated = {sketch.sketch_id: sketch for sketch in after}
    changed: set[DrawingObjectRef] = set()
    for source in before:
        target = updated.get(source.sketch_id)
        if target is None:
            continue
        entities = {item.entity_id: item for item in target.entities}
        changed.update(
            DrawingObjectRef("geometry", item.entity_id, source.sketch_id)
            for item in source.entities
            if entities.get(item.entity_id) != item
        )
    if any(group.selectable and not changed.isdisjoint(group.members) for group in groups):
        raise ValidationError("组选择已启用；请先关闭组选择再编辑单个成员。")


def prepare_grouped_sketch_replacements(
    before: tuple[Sketch, ...],
    after: tuple[Sketch, ...],
    groups: tuple[DrawingGroup, ...],
    mapping: dict[DrawingObjectRef, tuple[DrawingObjectRef, ...]],
    *,
    cross_tangencies: tuple[CrossSketchTangency, ...] = (),
) -> ReplayAppend:
    """Build a replayable batch with valid identities at every intermediate step."""
    if not before or len(before) != len(after):
        raise ValidationError("草图替换需要完整的来源和目标。")
    if len({item.sketch_id for item in before}) != len(before) or any(
        old.sketch_id != new.sketch_id for old, new in zip(before, after, strict=True)
    ):
        raise ValidationError("草图替换来源身份不一致。")
    if any(
        old.frame != new.frame or old.layers != new.layers or old.support_face != new.support_face
        for old, new in zip(before, after, strict=True)
    ):
        raise ValidationError("组成员替换不支持修改草图平面或图层表。")
    old_refs = {
        DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id)
        for sketch in before
        for entity in sketch.entities
    }
    new_refs = {
        DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id)
        for sketch in after
        for entity in sketch.entities
    }
    group_refs = {ref for group in groups for ref in group.members}
    if any(
        old not in old_refs
        or old not in group_refs
        or any(new not in new_refs for new in replacements)
        for old, replacements in mapping.items()
    ):
        raise ValidationError("组成员替换包含不存在的来源或目标。")
    mapping = {old: replacements for old, replacements in mapping.items() if replacements != (old,)}
    mapped = remap_group_members(groups, mapping)

    def revision(source: Sketch, target: Sketch) -> dict[str, object]:
        state = target.to_state_mapping()
        return {
            "sketch_id": source.sketch_id,
            "base_state_sha256": source.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }

    if not mapping:
        revisions = [
            revision(source, target)
            for source, target in zip(before, after, strict=True)
            if source != target
        ]
        if not revisions:
            raise ValidationError("组成员替换没有变化。")
        params: dict[str, object] = {"revisions": revisions}
        if cross_tangencies:
            params["cross_tangencies"] = [item.to_mapping() for item in cross_tangencies]
        return ReplayAppend(
            "drawing.objects.batch",
            1,
            {"operations": [{"id": "drawing.sketch.revise", "version": 79, "params": params}]},
            "local",
        )

    requires_atomic_revision = False
    for source, target in zip(before, after, strict=True):
        old_entities = {entity.entity_id: entity for entity in source.entities}
        new_entities = {entity.entity_id: entity for entity in target.entities}
        added_ids = new_entities.keys() - old_entities.keys()
        known_constraints = {constraint.constraint_id for constraint in source.constraints}
        if any(
            constraint.constraint_id not in known_constraints
            and constraint.source == "inferred"
            and any(ref.entity_id in added_ids for ref in constraint.references)
            and any(
                ref.entity_id in old_entities
                and old_entities[ref.entity_id] != new_entities.get(ref.entity_id)
                for ref in constraint.references
            )
            for constraint in target.constraints
        ):
            requires_atomic_revision = True
            break
    if requires_atomic_revision:
        affected = tuple(group for group in groups if any(ref in mapping for ref in group.members))
        affected_ids = {group.group_id for group in affected}
        atomic_operations: list[dict[str, object]] = [
            {"id": "drawing.group.remove", "version": 1, "params": {"group_id": group.group_id}}
            for group in affected
        ]
        params = {
            "revisions": [
                revision(source, target)
                for source, target in zip(before, after, strict=True)
                if source != target
            ]
        }
        if cross_tangencies:
            params["cross_tangencies"] = [item.to_mapping() for item in cross_tangencies]
        atomic_operations.append({"id": "drawing.sketch.revise", "version": 79, "params": params})
        atomic_operations.extend(
            {"id": "drawing.group.create", "version": 1, "params": group.to_mapping()}
            for group in mapped
            if group.group_id in affected_ids
        )
        return ReplayAppend("drawing.objects.batch", 1, {"operations": atomic_operations}, "local")

    intermediate: list[Sketch] = []
    for source, target in zip(before, after, strict=True):
        if not any(ref.sketch_id == source.sketch_id for ref in mapping):
            intermediate.append(target)
            continue
        known = {entity.entity_id for entity in source.entities}
        additions = tuple(entity for entity in target.entities if entity.entity_id not in known)
        new_entity_ids = {entity.entity_id for entity in additions}
        known_constraints = {constraint.constraint_id for constraint in source.constraints}
        inferred = tuple(
            constraint
            for constraint in target.constraints
            if constraint.constraint_id not in known_constraints
            and constraint.source == "inferred"
            and any(ref.entity_id in new_entity_ids for ref in constraint.references)
        )
        intermediate.append(
            replace(
                source,
                entities=(*source.entities, *additions),
                constraints=(*source.constraints, *inferred),
            )
        )
    operations: list[dict[str, object]] = []
    preliminary = [
        revision(source, target)
        for source, target in zip(before, intermediate, strict=True)
        if source != target
    ]
    if preliminary:
        operations.append(
            {"id": "drawing.sketch.revise", "version": 79, "params": {"revisions": preliminary}}
        )
    mapped_by_id = {group.group_id: group for group in mapped}
    for group in groups:
        updated = mapped_by_id.get(group.group_id)
        if updated is None:
            operations.append(
                {"id": "drawing.group.remove", "version": 1, "params": {"group_id": group.group_id}}
            )
        elif updated != group:
            operations.append(
                {"id": "drawing.group.update", "version": 1, "params": updated.to_mapping()}
            )
    final = [
        revision(source, target)
        for source, target in zip(intermediate, after, strict=True)
        if source != target
    ]
    if final:
        operations.append(
            {"id": "drawing.sketch.revise", "version": 79, "params": {"revisions": final}}
        )
    if cross_tangencies:
        revision_operation = next(
            (item for item in reversed(operations) if item["id"] == "drawing.sketch.revise"),
            None,
        )
        if revision_operation is None:
            raise ValidationError("相切关系需要对应的草图修改。")
        params = cast("dict[str, object]", revision_operation["params"])
        params["cross_tangencies"] = [item.to_mapping() for item in cross_tangencies]
    if not operations:
        raise ValidationError("组成员替换没有变化。")
    return ReplayAppend("drawing.objects.batch", 1, {"operations": operations}, "local")


def _simple_geometry_selection(
    snapshot: DrawingCollectionSnapshot,
    seeds: tuple[DrawingObjectRef, ...],
    *,
    allow_attached: bool = False,
    allow_complete_tangencies: bool = False,
    allow_partial_tangencies: bool = False,
    allow_partial_constraints: bool = False,
    check_related_dimension_layers: bool = True,
    allow_array_dependencies: bool = False,
) -> frozenset[DrawingObjectRef]:
    selected = expand_group_selection(seeds, snapshot.groups)
    if not selected or any(item.kind != "geometry" for item in selected):
        raise ValidationError("当前暂存移动仅支持几何；请先完成或调整混合对象。")
    selected_ids = {(item.sketch_id, item.object_id) for item in selected}
    for array in () if allow_array_dependencies else snapshot.associative_arrays:
        references = list(array.sources)
        for member in array.members:
            references.extend((member.source, member.target))
            if member.replacement is not None:
                references.append(member.replacement.source)
                if member.replacement.anchor_source is not None:
                    references.append(member.replacement.anchor_source)
        for output in array.extra_outputs:
            references.extend((output.source, output.target, output.anchor_source))
        if array.base_point is not None and array.base_point.source is not None:
            references.append(array.base_point.source)
        if any(
            (reference.sketch_id, reference.entity_id) in selected_ids for reference in references
        ):
            raise ValidationError("所选对象与关联阵列有关，暂不能执行此暂存移动。")
    for relation in snapshot.cross_tangencies:
        affected = tuple(
            (reference.sketch_id, reference.entity_id) in selected_ids
            for reference in (relation.first, relation.second)
        )
        if any(affected) and not (
            allow_partial_tangencies or (allow_complete_tangencies and all(affected))
        ):
            raise ValidationError("所选对象具有未完整选择的跨草图相切关系，暂不能执行此操作。")
    if not allow_attached:
        _require_free_annotations(snapshot)
    known = {
        DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id)
        for sketch in snapshot.sketches
        for entity in sketch.entities
    }
    if not selected <= known:
        raise ValidationError("选择的几何对象已变化。")
    for sketch in snapshot.sketches:
        identities = tuple(
            entity.entity_id
            for entity in sketch.entities
            if DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id) in selected
        )
        if not identities:
            continue
        for entity in sketch.entities:
            if entity.entity_id in identities:
                layer = snapshot.layers.get(entity.layer_name)
                if layer.locked or not layer.displayed:
                    raise ValidationError("所选成员位于锁定或隐藏图层；移动未应用。")
        for constraint in sketch.constraints:
            references = {reference.entity_id for reference in constraint.references}
            if not references.intersection(identities):
                continue
            if not allow_partial_constraints and (
                constraint.kind not in DIMENSION_KINDS
                and constraint.kind
                not in {
                    "horizontal",
                    "vertical",
                    "parallel",
                    "perpendicular",
                    "concentric",
                    "equal",
                    "coincident",
                    "tangent",
                }
                or not references.issubset(identities)
            ):
                raise ValidationError("所选成员存在尺寸或未整体选择的约束，暂不能执行此暂存移动。")
            if check_related_dimension_layers and constraint.kind in DIMENSION_KINDS:
                layer = snapshot.layers.get(constraint.layer_name or snapshot.dimension_layer)
                if layer.locked or not layer.displayed:
                    raise ValidationError("关联尺寸位于锁定或隐藏图层；移动未应用。")
    return selected


def _require_free_annotations(snapshot: DrawingCollectionSnapshot) -> None:
    if any(
        item.leader_attachment is not None or item.leader_annotation_attachment is not None
        for item in snapshot.frames
    ) or any(
        item.attachment is not None or item.annotation_attachment is not None
        for item in snapshot.datums
    ):
        raise ValidationError("存在附着公差或基准时，暂不能执行此暂存操作。")


def validate_collection_copy_geometry(
    snapshot: DrawingCollectionSnapshot,
    geometry: tuple[DrawingObjectRef, ...],
    *,
    allow_array_dependencies: bool = False,
) -> None:
    """Validate source identity and layers; optionally allow snapshotting array geometry."""
    if geometry:
        _simple_geometry_selection(
            replace(snapshot, groups=()),
            geometry,
            allow_attached=True,
            allow_partial_tangencies=True,
            allow_partial_constraints=True,
            check_related_dimension_layers=False,
            allow_array_dependencies=allow_array_dependencies,
        )


def prepare_simple_collection_move(
    snapshot: DrawingCollectionSnapshot,
    seeds: tuple[DrawingObjectRef, ...],
    frame: WorkPlaneFrame,
    delta: tuple[float, float],
    *,
    allow_attached: bool = False,
) -> ReplayAppend:
    """Prepare one safe geometry-only translation; reject unsupported dependencies."""
    selected = _simple_geometry_selection(
        snapshot, seeds, allow_attached=allow_attached, allow_complete_tangencies=True
    )
    revisions: list[dict[str, object]] = []
    for sketch in snapshot.sketches:
        identities = tuple(
            entity.entity_id
            for entity in sketch.entities
            if DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id) in selected
        )
        if not identities:
            continue
        try:
            local_delta = project_coplanar_vector(delta, frame, sketch.frame)
            entities = move_entities(
                sketch.entities, identities, local_delta, preserve_rectangle_order=True
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if entities == sketch.entities:
            continue
        constraints = tuple(
            replace(
                constraint,
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
            if any(ref.entity_id in identities for ref in constraint.references)
            else constraint
            for constraint in sketch.constraints
        )
        state = replace(sketch, entities=entities, constraints=constraints).to_state_mapping()
        revisions.append(
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        )
    if not revisions:
        raise ValidationError("移动未改变图元。")
    return ReplayAppend("drawing.sketch.revise", 79, {"revisions": revisions}, "local")


def prepare_collection_rotation(
    snapshot: DrawingCollectionSnapshot,
    seeds: tuple[DrawingObjectRef, ...],
    frame: WorkPlaneFrame,
    center: tuple[float, float],
    angle_deg: float,
) -> ReplayAppend:
    """Rotate an eligible geometry/text/image selection as one durable operation."""
    if not math.isfinite(angle_deg) or math.remainder(angle_deg, 360.0) == 0.0:
        raise ValidationError("旋转角度必须有限且不能为零。")
    return _prepare_collection_affine(snapshot, seeds, frame, center, angle_deg=angle_deg)


def prepare_collection_scale(
    snapshot: DrawingCollectionSnapshot,
    seeds: tuple[DrawingObjectRef, ...],
    frame: WorkPlaneFrame,
    center: tuple[float, float],
    factor: float,
) -> ReplayAppend:
    """Uniformly scale eligible group members in one durable operation."""
    if not math.isfinite(factor) or factor <= 0 or factor == 1.0:
        raise ValidationError("缩放比例必须为正数且不能为 1。")
    return _prepare_collection_affine(snapshot, seeds, frame, center, factor=factor)


def prepare_collection_mirror(
    snapshot: DrawingCollectionSnapshot,
    seeds: tuple[DrawingObjectRef, ...],
    frame: WorkPlaneFrame,
    start: tuple[float, float],
    end: tuple[float, float],
) -> ReplayAppend:
    """Reflect eligible group members in one durable operation."""
    if not all(math.isfinite(value) for value in (*start, *end)) or math.dist(start, end) <= 1e-10:
        raise ValidationError("镜像轴必须由两个不同的有限点确定。")
    return _prepare_collection_affine(snapshot, seeds, frame, start, mirror_end=end)


def prepare_collection_mirror_copy(
    snapshot: DrawingCollectionSnapshot,
    seeds: tuple[DrawingObjectRef, ...],
    frame: WorkPlaneFrame,
    start: tuple[float, float],
    end: tuple[float, float],
) -> ReplayAppend:
    """Freeze mirrored copies and their complete groups in one transaction."""
    if not all(math.isfinite(value) for value in (*start, *end)) or math.dist(start, end) <= 1e-10:
        raise ValidationError("镜像轴必须由两个不同的有限点确定。")
    return prepare_collection_copy(snapshot, seeds, frame, (0, 0), mirror_axis=(start, end))


def _prepare_collection_affine(
    snapshot: DrawingCollectionSnapshot,
    seeds: tuple[DrawingObjectRef, ...],
    frame: WorkPlaneFrame,
    center: tuple[float, float],
    *,
    angle_deg: float | None = None,
    factor: float | None = None,
    mirror_end: tuple[float, float] | None = None,
) -> ReplayAppend:
    operation_name = (
        "镜像" if mirror_end is not None else "旋转" if angle_deg is not None else "缩放"
    )
    selected = expand_group_selection(seeds, snapshot.groups)
    if not selected or any(
        item.kind not in {"geometry", "text", "raster", "block_instance"} for item in selected
    ):
        raise ValidationError(f"组包含尚不支持整体{operation_name}的成员。")
    instances = _selected_block_instances(snapshot, selected)
    if mirror_end is not None and instances:
        raise ValidationError("首期不支持镜像块实例。")
    geometry = tuple(item for item in selected if item.kind == "geometry")
    texts = tuple(
        item for item in snapshot.texts if DrawingObjectRef("text", item.text_id) in selected
    )
    rasters = tuple(
        item for item in snapshot.rasters if DrawingObjectRef("raster", item.image_id) in selected
    )
    if len(texts) != sum(item.kind == "text" for item in selected) or len(rasters) != sum(
        item.kind == "raster" for item in selected
    ):
        raise ValidationError("所选文字或图片不存在或身份不唯一。")
    for item in (*texts, *rasters):
        layer = snapshot.layers.get(item.layer_name)
        if layer.locked or not layer.displayed:
            raise ValidationError(f"所选成员位于锁定或隐藏图层；{operation_name}未应用。")
    operations: list[dict[str, object]] = []
    try:
        if instances:
            drawing_frame = WorkPlaneFrame.xy()
            projected_angle = project_coplanar_rotation(angle_deg or 0, frame, drawing_frame)
            origin = drawing_frame.world_to_local(frame.local_to_world(center))
            angle = projected_angle if angle_deg is not None else None
            for instance in instances:
                x, y = instance.insertion_mm[0] - origin[0], instance.insertion_mm[1] - origin[1]
                if angle is not None:
                    radians = math.radians(angle)
                    cosine, sine = math.cos(radians), math.sin(radians)
                    position = (
                        origin[0] + cosine * x - sine * y,
                        origin[1] + sine * x + cosine * y,
                    )
                    updated = replace(
                        instance, insertion_mm=position, rotation_deg=instance.rotation_deg + angle
                    )
                else:
                    assert factor is not None
                    updated = replace(
                        instance,
                        insertion_mm=(origin[0] + factor * x, origin[1] + factor * y),
                        scale=instance.scale * factor,
                    )
                operations.append(
                    {
                        "id": "drawing.block_instance.update",
                        "version": 1,
                        "params": updated.to_mapping(),
                    }
                )
        if geometry:
            _simple_geometry_selection(
                replace(snapshot, groups=()),
                geometry,
                allow_attached=True,
                allow_complete_tangencies=True,
                allow_partial_constraints=True,
            )
            geometry_ids = {(item.sketch_id, item.object_id) for item in geometry}
            attachments = (
                *(item.leader_attachment for item in snapshot.frames),
                *(item.attachment for item in snapshot.datums),
            )
            if any(
                attachment is not None
                and (attachment.sketch_id, attachment.reference.entity_id) in geometry_ids
                for attachment in attachments
            ):
                raise ValueError(f"存在附着到所选几何的标注，暂不能执行组{operation_name}。")
            revisions: list[dict[str, object]] = []
            updated_sketches: dict[str, Sketch] = {}
            rectangle_proofs: list[RectangleTransformEvidence] = []
            polyline_proofs: list[RectangleTransformEvidence] = []
            line_proofs: list[RectangleTransformEvidence] = []
            relation_refs = {
                (ref.sketch_id, ref.entity_id)
                for relation in snapshot.cross_tangencies
                for ref in (relation.first, relation.second)
            }
            for sketch in snapshot.sketches:
                identities = tuple(
                    item.object_id for item in geometry if item.sketch_id == sketch.sketch_id
                )
                if not identities:
                    continue
                if any(
                    any(ref.entity_id in identities for ref in constraint.references)
                    and not (
                        constraint.source == "inferred"
                        and constraint.kind in ("horizontal", "vertical", "coincident", "tangent")
                    )
                    for constraint in sketch.constraints
                ):
                    raise ValueError(f"有关联尺寸或约束的几何暂不支持组{operation_name}。")
                local_center = sketch.frame.world_to_local(frame.local_to_world(center))
                coefficients: tuple[float, float, float, float] | None = None
                if mirror_end is not None:
                    project_coplanar_rotation(0, frame, sketch.frame)
                    local_end = sketch.frame.world_to_local(frame.local_to_world(mirror_end))
                    entities = mirror_entities(sketch.entities, identities, local_center, local_end)
                    angle = math.atan2(
                        local_end[1] - local_center[1], local_end[0] - local_center[0]
                    )
                    a, b = math.cos(2 * angle), math.sin(2 * angle)
                    c, d = b, -a
                    coefficients = (a, b, c, d)
                elif angle_deg is not None:
                    local_angle = project_coplanar_rotation(angle_deg, frame, sketch.frame)
                    entities = rotate_entities(
                        sketch.entities, identities, local_center, local_angle
                    )
                    angle = math.radians(local_angle)
                    coefficients = (
                        math.cos(angle),
                        -math.sin(angle),
                        math.sin(angle),
                        math.cos(angle),
                    )
                else:
                    project_coplanar_rotation(0, frame, sketch.frame)
                    assert factor is not None
                    entities = scale_entities(sketch.entities, identities, local_center, factor)
                entities_by_id = {item.entity_id: item for item in entities}
                local_rectangle_proofs: list[RectangleTransformEvidence] = []
                if coefficients is not None:
                    a, b, c, d = coefficients
                    matrix = (
                        a,
                        b,
                        c,
                        d,
                        local_center[0] - a * local_center[0] - b * local_center[1],
                        local_center[1] - c * local_center[0] - d * local_center[1],
                    )
                    for entity in sketch.entities:
                        if entity.entity_id not in identities:
                            continue
                        proof = RectangleTransformEvidence(
                            CrossSketchRef(sketch.sketch_id, entity.entity_id), matrix
                        )
                        if (
                            isinstance(entity, RectangleEntity)
                            and entity != entities_by_id[entity.entity_id]
                        ):
                            local_rectangle_proofs.append(proof)
                            rectangle_proofs.append(proof)
                        elif (sketch.sketch_id, entity.entity_id) in relation_refs:
                            if isinstance(entity, PolylineEntity):
                                polyline_proofs.append(proof)
                            elif isinstance(entity, LineEntity):
                                line_proofs.append(proof)
                rebound_constraints = rebind_rectangle_constraints_for_sketch(
                    sketch,
                    replace(sketch, entities=entities),
                    tuple(local_rectangle_proofs),
                    adaptive_tolerance=True,
                )
                constraints: list[SketchConstraint] = []
                for constraint in rebound_constraints:
                    affected = any(ref.entity_id in identities for ref in constraint.references)
                    if constraint.source == "inferred" and affected:
                        if constraint.kind in ("horizontal", "vertical"):
                            entity = entities_by_id[constraint.references[0].entity_id]
                            if not isinstance(entity, LineEntity):
                                raise ValueError("推断方向约束的来源不再是直线。")
                            axis = 1 if constraint.kind == "horizontal" else 0
                            satisfied = abs(entity.start_mm[axis] - entity.end_mm[axis]) <= 1e-9
                        elif constraint.kind == "coincident":
                            first, second = (
                                resolve_point_reference(ref, entities_by_id)
                                for ref in constraint.references
                            )
                            satisfied = (
                                first is not None
                                and second is not None
                                and math.dist(first, second) <= 1e-9
                            )
                        else:
                            try:
                                first_curve, second_curve = (
                                    tangent_entity_curve(entities_by_id[ref.entity_id], ref.index)
                                    for ref in constraint.references
                                )
                                satisfied = tangent_on_curves(
                                    first_curve, second_curve
                                ) and tangent_endpoints_satisfied(
                                    first_curve,
                                    second_curve,
                                    constraint.first_endpoint,
                                    constraint.second_endpoint,
                                )
                            except (KeyError, ValueError, IndexError):
                                satisfied = False
                        if not satisfied:
                            continue
                    constraints.append(constraint)
                updated = replace(sketch, entities=entities, constraints=tuple(constraints))
                updated_sketches[sketch.sketch_id] = updated
                state = updated.to_state_mapping()
                revisions.append(
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                )
            params: dict[str, object] = {"revisions": revisions}
            if rectangle_proofs or polyline_proofs or line_proofs:
                affected = tuple(
                    relation
                    for relation in snapshot.cross_tangencies
                    if any(
                        (ref.sketch_id, ref.entity_id) in geometry_ids
                        for ref in (relation.first, relation.second)
                    )
                )
                updated_all = tuple(
                    updated_sketches.get(sketch.sketch_id, sketch) for sketch in snapshot.sketches
                )
                rebound, _version = rebind_committed_tangencies_for_edit(
                    snapshot.sketches,
                    updated_all,
                    affected,
                    tuple(rectangle_proofs),
                    tuple(polyline_proofs),
                    tuple(line_proofs),
                    adaptive_rectangle_tolerance=True,
                )
                changed_relations = tuple(
                    (old, new) for old, new in zip(affected, rebound, strict=True) if old != new
                )
                if changed_relations:
                    params["remove_tangencies"] = [
                        old.relation_id for old, _new in changed_relations
                    ]
                    params["cross_tangencies"] = [
                        new.to_mapping() for _old, new in changed_relations
                    ]
                if rectangle_proofs:
                    params["rectangle_transforms"] = [
                        item.to_mapping() for item in rectangle_proofs
                    ]
                if polyline_proofs:
                    params["polyline_transforms"] = [item.to_mapping() for item in polyline_proofs]
                if line_proofs:
                    params["line_transforms"] = [item.to_mapping() for item in line_proofs]
            operations.append(
                {
                    "id": "drawing.sketch.revise",
                    "version": 81 if rectangle_proofs else 79,
                    "params": params,
                }
            )
        drawing_angle = 0.0
        drawing_center = (0.0, 0.0)
        drawing_end = (0.0, 0.0)
        if texts or rasters:
            drawing_frame = WorkPlaneFrame.xy()
            drawing_angle = project_coplanar_rotation(angle_deg or 0, frame, drawing_frame)
            drawing_center = drawing_frame.world_to_local(frame.local_to_world(center))
            if mirror_end is not None:
                drawing_end = drawing_frame.world_to_local(frame.local_to_world(mirror_end))
        if texts:
            rotated = tuple(
                mirror_text(item, drawing_center, drawing_end)
                if mirror_end is not None
                else rotate_text(item, drawing_angle, drawing_center)
                if angle_deg is not None
                else scale_text(item, cast("float", factor), drawing_center, snapshot.text_styles)
                for item in texts
            )
            operations.append(
                {
                    "id": "drawing.text.batch",
                    "version": 1,
                    "params": {
                        "add": [],
                        "update": [item.to_mapping() for item in rotated],
                        "remove": [],
                    },
                }
            )
        if rasters:
            if mirror_end is not None:
                axis = math.atan2(
                    drawing_end[1] - drawing_center[1], drawing_end[0] - drawing_center[0]
                )
                cosine, sine = math.cos(2 * axis), math.sin(2 * axis)
                ox, oy = drawing_center
                images = tuple(
                    replace(
                        item,
                        origin_mm=(
                            ox
                            + cosine * (item.origin_mm[0] - ox)
                            + sine * (item.origin_mm[1] - oy),
                            oy
                            + sine * (item.origin_mm[0] - ox)
                            - cosine * (item.origin_mm[1] - oy),
                        ),
                        angle_deg=math.degrees(2 * axis) - item.angle_deg,
                        mirrored=not item.mirrored,
                    )
                    for item in rasters
                )
            else:
                radians = math.radians(drawing_angle)
                cosine, sine = math.cos(radians), math.sin(radians)
                ox, oy = drawing_center
                images = tuple(
                    replace(
                        item,
                        origin_mm=(
                            ox + cosine * (item.origin_mm[0] - ox) - sine * (item.origin_mm[1] - oy)
                            if angle_deg is not None
                            else ox + (item.origin_mm[0] - ox) * cast("float", factor),
                            oy + sine * (item.origin_mm[0] - ox) + cosine * (item.origin_mm[1] - oy)
                            if angle_deg is not None
                            else oy + (item.origin_mm[1] - oy) * cast("float", factor),
                        ),
                        angle_deg=item.angle_deg + drawing_angle
                        if angle_deg is not None
                        else item.angle_deg,
                        width_mm=item.width_mm * factor if factor is not None else item.width_mm,
                        height_mm=item.height_mm * factor if factor is not None else item.height_mm,
                    )
                    for item in rasters
                )
            operations.append(
                {
                    "id": "drawing.raster.batch",
                    "version": 2,
                    "params": {
                        "action": "update",
                        "images": [item.to_mapping(version=2) for item in images],
                    },
                }
            )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return ReplayAppend("drawing.objects.batch", 1, {"operations": operations}, "local")


def prepare_collection_delete(
    snapshot: DrawingCollectionSnapshot,
    seeds: tuple[DrawingObjectRef, ...],
    *,
    extra_constraints: tuple[tuple[str, str], ...] = (),
) -> ReplayAppend:
    """Delete eligible independent drawing objects in one durable step."""
    selected = expand_group_selection(seeds, snapshot.groups)
    if (not selected and not extra_constraints) or any(
        item.kind
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
        for item in selected
    ):
        raise ValidationError("组包含尚不支持整体删除的成员。")
    instances = _selected_block_instances(snapshot, selected)
    geometry = tuple(item for item in selected if item.kind == "geometry")
    dimensions = tuple(item for item in selected if item.kind == "dimension")
    if len(set(extra_constraints)) != len(extra_constraints):
        raise ValidationError("所选约束身份重复。")
    for sketch_id, constraint_id in extra_constraints:
        matches = [
            (sketch, constraint)
            for sketch in snapshot.sketches
            if sketch.sketch_id == sketch_id
            for constraint in sketch.constraints
            if constraint.constraint_id == constraint_id and constraint.kind not in DIMENSION_KINDS
        ]
        if len(matches) != 1:
            raise ValidationError("所选约束不存在或身份不唯一。")
        sketch, constraint = matches[0]
        first = next(
            (
                entity
                for entity in sketch.entities
                if entity.entity_id == constraint.references[0].entity_id
            ),
            None,
        )
        layer = snapshot.layers.get(constraint.layer_name or (first.layer_name if first else "0"))
        if layer.locked or not layer.displayed:
            raise ValidationError("所选约束位于锁定或隐藏图层；删除未应用。")
    for ref in dimensions:
        matches = [
            constraint
            for sketch in snapshot.sketches
            if sketch.sketch_id == ref.sketch_id
            for constraint in sketch.constraints
            if constraint.constraint_id == ref.object_id and constraint.kind in DIMENSION_KINDS
        ]
        if len(matches) != 1:
            raise ValidationError("所选尺寸不存在或身份不唯一。")
        layer = snapshot.layers.get(matches[0].layer_name or snapshot.dimension_layer)
        if layer.locked or not layer.displayed:
            raise ValidationError("所选尺寸位于锁定或隐藏图层；删除未应用。")
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
    if any(
        len(items) != sum(item.kind == kind for item in selected)
        for kind, items in (
            ("text", texts),
            ("raster", rasters),
            ("tolerance", frames),
            ("datum", datums),
            ("reference_dimension", references),
        )
    ):
        raise ValidationError("所选对象不存在或身份不唯一。")
    removed_geometry = {(item.sketch_id, item.object_id) for item in geometry}
    for sketch in snapshot.sketches:
        entities = {item.entity_id: item for item in sketch.entities}
        for constraint in sketch.constraints:
            if not any(
                (sketch.sketch_id, ref.entity_id) in removed_geometry
                for ref in constraint.references
            ):
                continue
            first = entities.get(constraint.references[0].entity_id)
            default_layer = (
                snapshot.dimension_layer
                if constraint.kind in DIMENSION_KINDS
                else first.layer_name
                if first is not None
                else "0"
            )
            layer = snapshot.layers.get(constraint.layer_name or default_layer)
            if layer.locked or not layer.displayed:
                raise ValidationError("相关约束位于锁定或隐藏图层；删除未应用。")
    removed_dimensions = {(item.sketch_id, item.object_id) for item in dimensions}
    removed_dimensions.update(
        (sketch.sketch_id, constraint.constraint_id)
        for sketch in snapshot.sketches
        for constraint in sketch.constraints
        if constraint.kind in DIMENSION_KINDS
        and any(
            (sketch.sketch_id, ref.entity_id) in removed_geometry for ref in constraint.references
        )
    )
    removed_frames = {item.frame_id for item in frames}
    removed_datums = {item.datum_id for item in datums}
    removed_references = {item.dimension_id for item in references}

    def geometry_is_removed(attachment: DatumAttachment | None) -> bool:
        return (
            attachment is not None
            and (attachment.sketch_id, attachment.reference.entity_id) in removed_geometry
        )

    def annotation_is_removed(attachment: AnnotationAttachment | None) -> bool:
        if attachment is None:
            return False
        if attachment.kind == "frame":
            return attachment.object_id in removed_frames
        if attachment.kind == "reference_dimension":
            return attachment.object_id in removed_references
        return (attachment.sketch_id, attachment.object_id) in removed_dimensions

    if any(
        item.frame_id not in removed_frames
        and (
            geometry_is_removed(item.leader_attachment)
            or annotation_is_removed(item.leader_annotation_attachment)
        )
        for item in snapshot.frames
    ) or any(
        item.datum_id not in removed_datums
        and (
            geometry_is_removed(item.attachment)
            or annotation_is_removed(item.annotation_attachment)
        )
        for item in snapshot.datums
    ):
        raise ValidationError("存在未选中的附着标注；请同时选择关联标注后删除。")
    for item in (*texts, *rasters, *frames, *datums, *references):
        layer = snapshot.layers.get(item.layer_name)
        if layer.locked or not layer.displayed:
            raise ValidationError("所选成员位于锁定或隐藏图层；删除未应用。")
    operations: list[dict[str, object]] = [
        {
            "id": "drawing.block_instance.remove",
            "version": 1,
            "params": {"instance_id": item.instance_id},
        }
        for item in instances
    ]
    if frames or datums:
        operations.append(
            {
                "id": "drawing.tolerance.batch",
                "version": 28,
                "params": {
                    "remove_frames": [item.frame_id for item in frames],
                    "remove_datums": [item.datum_id for item in datums],
                },
            }
        )
    if references:
        operations.append(
            {
                "id": "drawing.reference_dimensions.batch",
                "version": 10,
                "params": {"remove": [item.dimension_id for item in references]},
            }
        )
    if geometry or dimensions or extra_constraints:
        if geometry:
            _simple_geometry_selection(
                replace(snapshot, groups=()),
                geometry,
                allow_attached=True,
                allow_partial_tangencies=True,
                allow_partial_constraints=True,
            )
        revisions: list[dict[str, object]] = []
        for sketch in snapshot.sketches:
            identities = {item.object_id for item in geometry if item.sketch_id == sketch.sketch_id}
            dimension_ids = {
                item.object_id for item in dimensions if item.sketch_id == sketch.sketch_id
            }
            dimension_ids.update(
                constraint_id
                for sketch_id, constraint_id in extra_constraints
                if sketch_id == sketch.sketch_id
            )
            if not identities and not dimension_ids:
                continue
            modified = replace(
                sketch,
                entities=tuple(
                    item for item in sketch.entities if item.entity_id not in identities
                ),
                constraints=tuple(
                    item
                    for item in sketch.constraints
                    if item.constraint_id not in dimension_ids
                    and not any(ref.entity_id in identities for ref in item.references)
                ),
            )
            state = modified.to_state_mapping()
            revision: dict[str, object] = {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
            removed_local = [
                item.constraint_id
                for item in sketch.constraints
                if item.kind == "tangent"
                and item.source == "user"
                and item not in modified.constraints
            ]
            if removed_local:
                revision["removed_local_tangencies"] = removed_local
            revisions.append(revision)
        removed_tangencies = [
            relation.relation_id
            for relation in snapshot.cross_tangencies
            if any(
                (ref.sketch_id, ref.entity_id) in removed_geometry
                for ref in (relation.first, relation.second)
            )
        ]
        params: dict[str, object] = {"revisions": revisions}
        if removed_tangencies:
            params["remove_tangencies"] = removed_tangencies
        operations.append(
            {
                "id": "drawing.sketch.revise",
                "version": 80
                if any("removed_local_tangencies" in item for item in revisions)
                else 79,
                "params": params,
            }
        )
    if texts:
        operations.append(
            {
                "id": "drawing.text.batch",
                "version": 1,
                "params": {"add": [], "update": [], "remove": [item.text_id for item in texts]},
            }
        )
    if rasters:
        operations.append(
            {
                "id": "drawing.raster.batch",
                "version": 2,
                "params": {"action": "remove", "image_ids": [item.image_id for item in rasters]},
            }
        )
    return ReplayAppend("drawing.objects.batch", 1, {"operations": operations}, "local")


def prepare_simple_collection_copy(
    snapshot: DrawingCollectionSnapshot,
    seeds: tuple[DrawingObjectRef, ...],
    frame: WorkPlaneFrame,
    delta: tuple[float, float],
) -> ReplayAppend:
    """Freeze geometry copies and complete copied groups in one durable command."""
    selected = _simple_geometry_selection(
        snapshot,
        seeds,
        allow_partial_tangencies=True,
        allow_partial_constraints=True,
        check_related_dimension_layers=False,
    )
    revisions, mapping = _copy_geometry(snapshot, selected, frame, delta)
    groups = copy_complete_groups(
        snapshot.groups, mapping, {group.group_id: uuid4().hex for group in snapshot.groups}
    )
    params: dict[str, object] = {"revisions": revisions}
    copied_relations = _copied_cross_tangencies(snapshot, mapping)
    if copied_relations:
        params["cross_tangencies"] = [item.to_mapping() for item in copied_relations]
    operations: list[dict[str, object]] = [
        {"id": "drawing.sketch.revise", "version": 79, "params": params}
    ]
    operations.extend(
        {"id": "drawing.group.create", "version": 1, "params": group.to_mapping()}
        for group in groups
    )
    return ReplayAppend("drawing.objects.batch", 1, {"operations": operations}, "local")


def _copied_cross_tangencies(
    snapshot: DrawingCollectionSnapshot,
    mapping: dict[DrawingObjectRef, DrawingObjectRef],
) -> tuple[CrossSketchTangency, ...]:
    """Copy only relations for which both geometric owners were copied."""
    copied: list[CrossSketchTangency] = []
    for relation in snapshot.cross_tangencies:
        refs = tuple(
            DrawingObjectRef("geometry", item.entity_id, item.sketch_id)
            for item in (relation.first, relation.second)
        )
        if not all(item in mapping for item in refs):
            continue
        first, second = (mapping[item] for item in refs)
        assert first.sketch_id is not None and second.sketch_id is not None
        copied.append(
            replace(
                relation,
                relation_id=uuid4().hex,
                first=replace(relation.first, sketch_id=first.sketch_id, entity_id=first.object_id),
                second=replace(
                    relation.second, sketch_id=second.sketch_id, entity_id=second.object_id
                ),
            )
        )
    return tuple(copied)


def _copy_geometry(
    snapshot: DrawingCollectionSnapshot,
    selected: frozenset[DrawingObjectRef],
    frame: WorkPlaneFrame,
    delta: tuple[float, float],
    mirror_axis: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> tuple[list[dict[str, object]], dict[DrawingObjectRef, DrawingObjectRef]]:
    revisions: list[dict[str, object]] = []
    mapping: dict[DrawingObjectRef, DrawingObjectRef] = {}
    for sketch in snapshot.sketches:
        sources = tuple(
            entity
            for entity in sketch.entities
            if DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id) in selected
        )
        if not sources:
            continue
        try:
            local_delta = project_coplanar_vector(delta, frame, sketch.frame)
            entities = copy_entities(
                sketch.entities, tuple(entity.entity_id for entity in sources), local_delta
            )
            if mirror_axis is not None:
                start, end = mirror_axis
                project_coplanar_rotation(0, frame, sketch.frame)
                local_start = sketch.frame.world_to_local(frame.local_to_world(start))
                local_end = sketch.frame.world_to_local(frame.local_to_world(end))
                entities = mirror_entities(
                    entities,
                    tuple(item.entity_id for item in entities[len(sketch.entities) :]),
                    local_start,
                    local_end,
                )
            entities = (
                *entities[: len(sketch.entities)],
                *(assign_new_curve_point_ids(item) for item in entities[len(sketch.entities) :]),
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        for source, duplicate in zip(sources, entities[len(sketch.entities) :], strict=True):
            mapping[DrawingObjectRef("geometry", source.entity_id, sketch.sketch_id)] = (
                DrawingObjectRef("geometry", duplicate.entity_id, sketch.sketch_id)
            )
        state = replace(sketch, entities=entities).to_state_mapping()
        revisions.append(
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        )
    return revisions, mapping


def prepare_collection_copy(
    snapshot: DrawingCollectionSnapshot,
    seeds: tuple[DrawingObjectRef, ...],
    frame: WorkPlaneFrame,
    delta: tuple[float, float],
    *,
    mirror_axis: tuple[tuple[float, float], tuple[float, float]] | None = None,
    datum_relayout: Callable[[DatumIdentifier], DatumIdentifier] | None = None,
) -> ReplayAppend:
    """Freeze supported copied objects and complete groups in one transaction."""
    selected = expand_group_selection(seeds, snapshot.groups)
    if not selected or any(
        item.kind
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
        for item in selected
    ):
        raise ValidationError("组包含尚不支持整体复制的成员。")
    instances = _selected_block_instances(snapshot, selected)
    geometry = tuple(item for item in selected if item.kind == "geometry")
    if mirror_axis is not None and any(
        item.kind not in {"geometry", "text", "raster"} for item in selected
    ):
        raise ValidationError("组包含尚不支持镜像副本的成员。")
    dimensions = frozenset(item for item in selected if item.kind == "dimension")
    for reference in dimensions:
        matches = [
            constraint
            for sketch in snapshot.sketches
            if sketch.sketch_id == reference.sketch_id
            for constraint in sketch.constraints
            if constraint.constraint_id == reference.object_id
            and constraint.kind in DIMENSION_KINDS
        ]
        if len(matches) != 1:
            raise ValidationError("所选尺寸不存在或身份不唯一。")
        layer = snapshot.layers.get(matches[0].layer_name or snapshot.dimension_layer)
        if layer.locked or not layer.displayed:
            raise ValidationError("所选尺寸位于锁定或隐藏图层；复制未应用。")
    text_ids = {item.object_id for item in selected if item.kind == "text"}
    raster_ids = {item.object_id for item in selected if item.kind == "raster"}
    frame_ids = {item.object_id for item in selected if item.kind == "tolerance"}
    datum_ids = {item.object_id for item in selected if item.kind == "datum"}
    reference_ids = {item.object_id for item in selected if item.kind == "reference_dimension"}
    texts = tuple(item for item in snapshot.texts if item.text_id in text_ids)
    rasters = tuple(item for item in snapshot.rasters if item.image_id in raster_ids)
    frames = tuple(item for item in snapshot.frames if item.frame_id in frame_ids)
    datums = tuple(item for item in snapshot.datums if item.datum_id in datum_ids)
    references = tuple(
        item for item in snapshot.reference_dimensions if item.dimension_id in reference_ids
    )
    if any(
        len(items) != len(ids)
        for items, ids in (
            (texts, text_ids),
            (rasters, raster_ids),
            (frames, frame_ids),
            (datums, datum_ids),
            (references, reference_ids),
        )
    ):
        raise ValidationError("所选对象不存在或身份不唯一。")
    if datum_relayout is None and any(item.box_size_mm is not None for item in datums):
        raise ValidationError("复制带固定文字框的基准需要先重新计算文字布局。")
    for item in (*texts, *rasters, *frames, *datums, *references):
        layer = snapshot.layers.get(item.layer_name)
        if layer.locked or not layer.displayed:
            raise ValidationError("所选成员位于锁定或隐藏图层；复制未应用。")
    operations: list[dict[str, object]] = []
    mapping: dict[DrawingObjectRef, DrawingObjectRef] = {}
    if instances:
        try:
            drawing_delta = project_coplanar_vector(delta, frame, WorkPlaneFrame.xy())
            for instance in instances:
                duplicate = replace(
                    instance,
                    instance_id=uuid4().hex,
                    insertion_mm=(
                        instance.insertion_mm[0] + drawing_delta[0],
                        instance.insertion_mm[1] + drawing_delta[1],
                    ),
                )
                mapping[DrawingObjectRef("block_instance", instance.instance_id)] = (
                    DrawingObjectRef("block_instance", duplicate.instance_id)
                )
                operations.append(
                    {
                        "id": "drawing.block_instance.insert",
                        "version": 1,
                        "params": duplicate.to_mapping(),
                    }
                )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
    if geometry:
        selected_geometry = _simple_geometry_selection(
            replace(snapshot, groups=()),
            geometry,
            allow_attached=True,
            allow_partial_tangencies=mirror_axis is None,
            allow_partial_constraints=True,
            check_related_dimension_layers=False,
        )
        if dimensions:
            duplicate_sketches: list[Sketch] = []
            for sketch in snapshot.sketches:
                sources = tuple(
                    entity
                    for entity in sketch.entities
                    if DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id)
                    in selected_geometry
                )
                if not sources:
                    continue
                try:
                    local_delta = project_coplanar_vector(delta, frame, sketch.frame)
                    copied = copy_entities(
                        sketch.entities, tuple(item.entity_id for item in sources), local_delta
                    )[len(sketch.entities) :]
                    copied = tuple(assign_new_curve_point_ids(item) for item in copied)
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc
                sketch_id = uuid4().hex
                for source, duplicate in zip(sources, copied, strict=True):
                    mapping[DrawingObjectRef("geometry", source.entity_id, sketch.sketch_id)] = (
                        DrawingObjectRef("geometry", duplicate.entity_id, sketch_id)
                    )
                copied_dimensions: list[SketchConstraint] = []
                for item in sketch.constraints:
                    source_ref = DrawingObjectRef("dimension", item.constraint_id, sketch.sketch_id)
                    if source_ref not in dimensions:
                        continue
                    try:
                        copied_refs = tuple(
                            replace(
                                reference,
                                entity_id=mapping[
                                    DrawingObjectRef(
                                        "geometry", reference.entity_id, sketch.sketch_id
                                    )
                                ].object_id,
                            )
                            for reference in item.references
                        )
                    except KeyError as exc:
                        raise ValidationError("复制尺寸须同时选择其全部关联几何。") from exc
                    identity = uuid4().hex
                    copied_dimensions.append(
                        replace(
                            item,
                            constraint_id=identity,
                            references=copied_refs,
                            position_mm=(
                                item.position_mm[0] + local_delta[0],
                                item.position_mm[1] + local_delta[1],
                            )
                            if item.position_mm is not None
                            else None,
                            text_position_mm=(
                                item.text_position_mm[0] + local_delta[0],
                                item.text_position_mm[1] + local_delta[1],
                            )
                            if item.text_position_mm is not None
                            else None,
                        )
                    )
                    mapping[source_ref] = DrawingObjectRef("dimension", identity, sketch_id)
                duplicate = Sketch(
                    sketch_id, sketch.frame, copied, tuple(copied_dimensions), snapshot.layers
                )
                duplicate_sketches.append(duplicate)
                operations.append(
                    {"id": "sketch.create", "version": 58, "params": duplicate.to_state_mapping()}
                )
            if not dimensions.issubset(mapping):
                raise ValidationError("复制尺寸须同时选择其全部关联几何。")
            copied_relations = _copied_cross_tangencies(snapshot, mapping)
            if copied_relations:
                anchor = duplicate_sketches[0]
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
                            "cross_tangencies": [item.to_mapping() for item in copied_relations],
                        },
                    }
                )
        else:
            revisions, geometry_mapping = _copy_geometry(
                snapshot, selected_geometry, frame, delta, mirror_axis
            )
            mapping.update(geometry_mapping)
            params: dict[str, object] = {"revisions": revisions}
            copied_relations = _copied_cross_tangencies(snapshot, mapping)
            if copied_relations:
                params["cross_tangencies"] = [item.to_mapping() for item in copied_relations]
            operations.append({"id": "drawing.sketch.revise", "version": 79, "params": params})
    elif dimensions:
        raise ValidationError("复制尺寸须同时选择其全部关联几何。")
    if texts or rasters:
        try:
            drawing_delta = project_coplanar_vector(delta, frame, WorkPlaneFrame.xy())
            text_copies = tuple(
                replace(move_text(item, drawing_delta), text_id=uuid4().hex) for item in texts
            )
            raster_copies = tuple(
                replace(
                    item,
                    image_id=uuid4().hex,
                    origin_mm=(
                        item.origin_mm[0] + drawing_delta[0],
                        item.origin_mm[1] + drawing_delta[1],
                    ),
                )
                for item in rasters
            )
            if mirror_axis is not None:
                drawing_frame = WorkPlaneFrame.xy()
                project_coplanar_rotation(0, frame, drawing_frame)
                start = drawing_frame.world_to_local(frame.local_to_world(mirror_axis[0]))
                end = drawing_frame.world_to_local(frame.local_to_world(mirror_axis[1]))
                text_copies = tuple(mirror_text(item, start, end) for item in text_copies)
                axis = math.atan2(end[1] - start[1], end[0] - start[0])
                cosine, sine = math.cos(2 * axis), math.sin(2 * axis)
                raster_copies = tuple(
                    replace(
                        item,
                        origin_mm=(
                            start[0]
                            + cosine * (item.origin_mm[0] - start[0])
                            + sine * (item.origin_mm[1] - start[1]),
                            start[1]
                            + sine * (item.origin_mm[0] - start[0])
                            - cosine * (item.origin_mm[1] - start[1]),
                        ),
                        angle_deg=math.degrees(2 * axis) - item.angle_deg,
                        mirrored=not item.mirrored,
                    )
                    for item in raster_copies
                )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        for source, duplicate in zip(texts, text_copies, strict=True):
            mapping[DrawingObjectRef("text", source.text_id)] = DrawingObjectRef(
                "text", duplicate.text_id
            )
        for source, duplicate in zip(rasters, raster_copies, strict=True):
            mapping[DrawingObjectRef("raster", source.image_id)] = DrawingObjectRef(
                "raster", duplicate.image_id
            )
        if text_copies:
            operations.append(
                {
                    "id": "drawing.text.batch",
                    "version": 1,
                    "params": {
                        "add": [item.to_mapping() for item in text_copies],
                        "update": [],
                        "remove": [],
                    },
                }
            )
        if raster_copies:
            operations.append(
                {
                    "id": "drawing.raster.batch",
                    "version": 2,
                    "params": {
                        "action": "add",
                        "images": [item.to_mapping(version=2) for item in raster_copies],
                    },
                }
            )
    if frames or datums or references:
        try:
            drawing_delta = project_coplanar_vector(delta, frame, WorkPlaneFrame.xy())
            dx, dy = drawing_delta
            reference_copies = tuple(
                replace(
                    item,
                    dimension_id=uuid4().hex,
                    first_mm=(item.first_mm[0] + dx, item.first_mm[1] + dy),
                    second_mm=(item.second_mm[0] + dx, item.second_mm[1] + dy),
                    location_mm=(item.location_mm[0] + dx, item.location_mm[1] + dy),
                    vertex_mm=(item.vertex_mm[0] + dx, item.vertex_mm[1] + dy)
                    if item.vertex_mm is not None
                    else None,
                )
                for item in references
            )
            used = {item.label.casefold() for item in snapshot.datums}
            labels: dict[str, str] = {}
            for datum in datums:
                label = next(
                    (chr(value) for value in range(65, 91) if chr(value).casefold() not in used), ""
                )
                if not label:
                    raise ValueError("没有可用的基准字母；请先调整基准名称。")
                labels[datum.datum_id] = label
                used.add(label.casefold())
            entity_mapping = {
                (source.sketch_id, source.object_id): target.object_id
                for source, target in mapping.items()
                if source.kind == "geometry" and source.sketch_id is not None
            }
            entity_sketches = {
                (source.sketch_id, source.object_id): target.sketch_id
                for source, target in mapping.items()
                if source.kind == "geometry"
                and source.sketch_id is not None
                and target.sketch_id is not None
            }
            dimension_mapping = {
                (source.sketch_id, source.object_id): target.object_id
                for source, target in mapping.items()
                if source.kind == "dimension" and source.sketch_id is not None
            }
            dimension_sketches = {
                (source.sketch_id, source.object_id): target.sketch_id
                for source, target in mapping.items()
                if source.kind == "dimension"
                and source.sketch_id is not None
                and target.sketch_id is not None
            }
            frame_copies, datum_copies = copy_geometric_annotations(
                frames,
                datums,
                entity_mapping,
                "0" * 32,
                drawing_delta,
                labels,
                preserve_external=True,
                reference_mapping={
                    source.dimension_id: target.dimension_id
                    for source, target in zip(references, reference_copies, strict=True)
                },
                dimension_mapping=dimension_mapping,
                entity_sketch_mapping=entity_sketches,
                dimension_sketch_mapping=dimension_sketches,
            )
            if datum_relayout is not None:
                laid_out = tuple(
                    datum_relayout(item) if item.box_size_mm is not None else item
                    for item in datum_copies
                )
                if any(
                    replace(
                        original,
                        box_size_mm=updated.box_size_mm,
                        leader_offsets=updated.leader_offsets,
                    )
                    != updated
                    for original, updated in zip(datum_copies, laid_out, strict=True)
                ):
                    raise ValueError("基准文字布局不能修改对象身份或关联。")
                datum_copies = laid_out
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        for source, duplicate in zip(frames, frame_copies, strict=True):
            mapping[DrawingObjectRef("tolerance", source.frame_id)] = DrawingObjectRef(
                "tolerance", duplicate.frame_id
            )
        for source, duplicate in zip(datums, datum_copies, strict=True):
            mapping[DrawingObjectRef("datum", source.datum_id)] = DrawingObjectRef(
                "datum", duplicate.datum_id
            )
        for source, duplicate in zip(references, reference_copies, strict=True):
            mapping[DrawingObjectRef("reference_dimension", source.dimension_id)] = (
                DrawingObjectRef("reference_dimension", duplicate.dimension_id)
            )
        if reference_copies:
            operations.append(
                {
                    "id": "drawing.reference_dimensions.batch",
                    "version": 10,
                    "params": {"add": [item.to_mapping() for item in reference_copies]},
                }
            )
        if frame_copies or datum_copies:
            operations.append(
                {
                    "id": "drawing.tolerance.batch",
                    "version": 29
                    if any(item.arrow_style != "filled" for item in datum_copies)
                    else 28,
                    "params": {
                        "add_frames": [item.to_mapping() for item in frame_copies],
                        "add_datums": [item.to_mapping() for item in datum_copies],
                    },
                }
            )
    groups = copy_complete_groups(
        snapshot.groups, mapping, {group.group_id: uuid4().hex for group in snapshot.groups}
    )
    operations.extend(
        {"id": "drawing.group.create", "version": 1, "params": group.to_mapping()}
        for group in groups
    )
    return ReplayAppend("drawing.objects.batch", 1, {"operations": operations}, "local")


def _selected_block_instances(
    snapshot: DrawingCollectionSnapshot, selected: frozenset[DrawingObjectRef]
) -> tuple[BlockInstance, ...]:
    ids = {item.object_id for item in selected if item.kind == "block_instance"}
    instances = tuple(item for item in snapshot.block_instances if item.instance_id in ids)
    if len(instances) != len(ids):
        raise ValidationError("所选块实例不存在或身份不唯一。")
    definitions = {item.definition_id: item for item in snapshot.block_definitions}
    try:
        for instance in instances:
            definition = definitions[instance.definition_id]
            names = {instance.layer_name}
            names.update(
                instance.layer_name if item.layer_name.casefold() == "0" else item.layer_name
                for item in (*definition.entities, *definition.texts)
            )
            if any(
                snapshot.layers.get(name).locked or not snapshot.layers.get(name).displayed
                for name in names
            ):
                raise ValidationError("块实例或成员位于锁定、隐藏或冻结图层。")
    except KeyError as exc:
        raise ValidationError("块定义或图层不存在。") from exc
    return instances


def prepare_collection_translation(
    snapshot: DrawingCollectionSnapshot,
    seeds: tuple[DrawingObjectRef, ...],
    frame: WorkPlaneFrame,
    delta: tuple[float, float],
    *,
    allow_attached: bool = False,
) -> ReplayAppend:
    """Translate supported geometry, text and pictures in one atomic operation."""
    selected = expand_group_selection(seeds, snapshot.groups)
    if not selected or any(
        item.kind
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
        for item in selected
    ):
        raise ValidationError("组包含尚不支持整体移动的成员。")
    geometry = tuple(item for item in selected if item.kind == "geometry")
    dimensions = tuple(item for item in selected if item.kind == "dimension")
    for ref in dimensions:
        matches = [
            constraint
            for sketch in snapshot.sketches
            if sketch.sketch_id == ref.sketch_id
            for constraint in sketch.constraints
            if constraint.constraint_id == ref.object_id and constraint.kind in DIMENSION_KINDS
        ]
        if len(matches) != 1:
            raise ValidationError("所选尺寸不存在或身份不唯一。")
        if not all(
            DrawingObjectRef("geometry", item.entity_id, ref.sketch_id) in geometry
            for item in matches[0].references
        ):
            raise ValidationError("移动尺寸须同时选择其全部关联几何。")
    text_ids = {item.object_id for item in selected if item.kind == "text"}
    raster_ids = {item.object_id for item in selected if item.kind == "raster"}
    frame_ids = {item.object_id for item in selected if item.kind == "tolerance"}
    datum_ids = {item.object_id for item in selected if item.kind == "datum"}
    reference_ids = {item.object_id for item in selected if item.kind == "reference_dimension"}
    texts = tuple(item for item in snapshot.texts if item.text_id in text_ids)
    rasters = tuple(item for item in snapshot.rasters if item.image_id in raster_ids)
    frames = tuple(item for item in snapshot.frames if item.frame_id in frame_ids)
    datums = tuple(item for item in snapshot.datums if item.datum_id in datum_ids)
    references = tuple(
        item for item in snapshot.reference_dimensions if item.dimension_id in reference_ids
    )
    instances = _selected_block_instances(snapshot, selected)
    if any(
        (
            len(texts) != len(text_ids),
            len(rasters) != len(raster_ids),
            len(frames) != len(frame_ids),
            len(datums) != len(datum_ids),
            len(references) != len(reference_ids),
        )
    ):
        raise ValidationError("所选对象不存在或身份不唯一。")
    if (frames or datums or references) and not allow_attached:
        _require_free_annotations(snapshot)
    for item in (*texts, *rasters, *frames, *datums, *references):
        layer = snapshot.layers.get(item.layer_name)
        if layer.locked or not layer.displayed:
            raise ValidationError("所选成员位于锁定或隐藏图层；移动未应用。")
    operations: list[dict[str, object]] = []
    if geometry:
        revision = prepare_simple_collection_move(
            replace(snapshot, groups=()), geometry, frame, delta, allow_attached=allow_attached
        )
        operations.append(
            {"id": revision.command_id, "version": revision.version, "params": revision.params}
        )
    if instances:
        try:
            drawing_delta = project_coplanar_vector(delta, frame, WorkPlaneFrame.xy())
            for instance in instances:
                moved = replace(
                    instance,
                    insertion_mm=(
                        instance.insertion_mm[0] + drawing_delta[0],
                        instance.insertion_mm[1] + drawing_delta[1],
                    ),
                )
                if moved != instance:
                    operations.append(
                        {
                            "id": "drawing.block_instance.update",
                            "version": 1,
                            "params": moved.to_mapping(),
                        }
                    )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
    if texts or rasters or frames or datums or references:
        try:
            drawing_delta = project_coplanar_vector(delta, frame, WorkPlaneFrame.xy())
            moved_texts = tuple(move_text(item, drawing_delta) for item in texts)
            moved_rasters = tuple(
                replace(
                    item,
                    origin_mm=(
                        item.origin_mm[0] + drawing_delta[0],
                        item.origin_mm[1] + drawing_delta[1],
                    ),
                )
                for item in rasters
            )
            moved_frames = tuple(translate_frame(item, drawing_delta) for item in frames)
            moved_datums = tuple(
                replace(
                    item,
                    position_mm=(
                        item.position_mm[0] + drawing_delta[0],
                        item.position_mm[1] + drawing_delta[1],
                    ),
                    target_mm=(
                        item.target_mm[0] + drawing_delta[0],
                        item.target_mm[1] + drawing_delta[1],
                    ),
                )
                for item in datums
            )
            moved_references = tuple(
                replace(
                    item,
                    first_mm=(
                        item.first_mm[0] + drawing_delta[0],
                        item.first_mm[1] + drawing_delta[1],
                    ),
                    second_mm=(
                        item.second_mm[0] + drawing_delta[0],
                        item.second_mm[1] + drawing_delta[1],
                    ),
                    location_mm=(
                        item.location_mm[0] + drawing_delta[0],
                        item.location_mm[1] + drawing_delta[1],
                    ),
                    vertex_mm=(
                        item.vertex_mm[0] + drawing_delta[0],
                        item.vertex_mm[1] + drawing_delta[1],
                    )
                    if item.vertex_mm is not None
                    else None,
                )
                for item in references
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if moved_texts != texts:
            operations.append(
                {
                    "id": "drawing.text.batch",
                    "version": 1,
                    "params": {
                        "add": [],
                        "update": [item.to_mapping() for item in moved_texts],
                        "remove": [],
                    },
                }
            )
        if moved_rasters != rasters:
            operations.append(
                {
                    "id": "drawing.raster.batch",
                    "version": 2,
                    "params": {
                        "action": "update",
                        "images": [item.to_mapping(version=2) for item in moved_rasters],
                    },
                }
            )
        if moved_frames != frames or moved_datums != datums:
            tolerance_params: dict[str, object] = {}
            if moved_frames != frames:
                tolerance_params["update_frames"] = [item.to_mapping() for item in moved_frames]
            if moved_datums != datums:
                tolerance_params["update_datums"] = [item.to_mapping() for item in moved_datums]
            operations.append(
                {
                    "id": "drawing.tolerance.batch",
                    "version": 29
                    if any(item.arrow_style != "filled" for item in moved_datums)
                    else 28,
                    "params": tolerance_params,
                }
            )
        if moved_references != references:
            operations.append(
                {
                    "id": "drawing.reference_dimensions.batch",
                    "version": 10,
                    "params": {"update": [item.to_mapping() for item in moved_references]},
                }
            )
    if not operations:
        raise ValidationError("移动未改变对象。")
    if len(operations) == 1:
        operation = operations[0]
        return ReplayAppend(
            cast("str", operation["id"]),
            cast("int", operation["version"]),
            cast("dict[str, object]", operation["params"]),
            "local",
        )
    return ReplayAppend("drawing.objects.batch", 1, {"operations": operations}, "local")
