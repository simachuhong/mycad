# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Drawing object catalogue and explicit group member identity mappings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast
from uuid import UUID

from mycad.core.associative_array import AssociativeRectArray
from mycad.core.drawing_groups import DrawingGroup, DrawingGroupTable, DrawingObjectRef
from mycad.core.exceptions import ValidationError

if TYPE_CHECKING:
    from mycad.core.sketch import Sketch


@dataclass(frozen=True, slots=True)
class DrawingObjectCatalog:
    """Exact identities of objects available in the current drawing state."""

    objects: tuple[DrawingObjectRef, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "objects", tuple(self.objects))
        if len(self.objects) != len(set(self.objects)):
            raise ValueError("对象目录包含重复引用。")


def validate_group_members(groups: Sequence[DrawingGroup], catalog: DrawingObjectCatalog) -> None:
    """Require each group member to exist with the exact kind and owner."""
    DrawingGroupTable(tuple(groups))
    known = frozenset(catalog.objects)
    if any(member not in known for group in groups for member in group.members):
        raise ValueError("组成员不存在或对象类型、所属草图不匹配。")


def validate_new_group_array_members(
    members: Sequence[DrawingObjectRef], arrays: Sequence[AssociativeRectArray]
) -> None:
    """Reject array sources and generated geometry for a newly created group."""
    references = {
        (ref.sketch_id, ref.entity_id)
        for array in arrays
        for ref in (
            *array.sources,
            *(item.target for item in array.members),
            *(item.replacement.source for item in array.members if item.replacement is not None),
            *(item.source for item in array.extra_outputs),
            *(item.target for item in array.extra_outputs),
        )
    }
    if any(
        member.kind == "geometry" and (member.sketch_id, member.object_id) in references
        for member in members
    ):
        raise ValidationError("关联阵列来源或成员暂不支持编组。")


def unmapped_group_memberships(
    before_sketches: Sequence[Sketch],
    before_groups: Sequence[DrawingGroup],
    after_sketches: Sequence[Sketch],
    command_id: str,
    params: Mapping[str, object],
) -> tuple[tuple[str, DrawingObjectRef], ...]:
    """Find each group membership removed without an explicit replacement mapping."""
    operations: tuple[Mapping[str, object], ...]
    if command_id in {"sketch.revise", "drawing.sketch.revise"}:
        operations = ({"id": command_id, "params": params},)
    elif command_id == "drawing.objects.batch":
        raw = params.get("operations")
        if not isinstance(raw, list):
            return ()
        operations = tuple(
            cast("Mapping[str, object]", item)
            for item in cast("list[object]", raw)
            if isinstance(item, Mapping)
        )
    else:
        return ()
    revisions_ids = {"sketch.revise", "drawing.sketch.revise"}
    if not any(item.get("id") in revisions_ids for item in operations):
        return ()
    old_entities = {
        (sketch.sketch_id, entity.entity_id): entity
        for sketch in before_sketches
        for entity in sketch.entities
    }
    new_entities = {
        (sketch.sketch_id, entity.entity_id): entity
        for sketch in after_sketches
        for entity in sketch.entities
    }
    old, new = old_entities.keys(), new_entities.keys()
    added = new - old
    modified_sketches = {
        sketch_id
        for sketch_id, entity_id in old & new
        if old_entities[(sketch_id, entity_id)] != new_entities[(sketch_id, entity_id)]
    }
    if not added and not modified_sketches:
        return ()
    explicit_members: dict[str, list[tuple[int, frozenset[DrawingObjectRef] | None]]] = {}
    removal_index: dict[tuple[str, str], int] = {}
    first_revision = next(
        index for index, item in enumerate(operations) if item.get("id") in revisions_ids
    )
    for index, item in enumerate(operations):
        action = item.get("id")
        if action in revisions_ids:
            revision_params = item.get("params")
            if isinstance(revision_params, Mapping):
                revision_data = cast("Mapping[str, object]", revision_params)
                revisions: object = (
                    [revision_data] if action == "sketch.revise" else revision_data.get("revisions")
                )
                if isinstance(revisions, list):
                    for value in cast("list[object]", revisions):
                        if not isinstance(value, Mapping):
                            continue
                        revision = cast("Mapping[str, object]", value)
                        sketch_id, entities = revision.get("sketch_id"), revision.get("entities")
                        if not isinstance(sketch_id, str) or not isinstance(entities, list):
                            continue
                        present = {
                            cast("Mapping[str, object]", entity).get("entity_id")
                            for entity in cast("list[object]", entities)
                            if isinstance(entity, Mapping)
                        }
                        for old_sketch, old_id in old:
                            if old_sketch == sketch_id and old_id not in present:
                                removal_index.setdefault((old_sketch, old_id), index)
        if action not in {
            "drawing.group.create",
            "drawing.group.update",
            "drawing.group.remove",
        }:
            continue
        group_params = item.get("params")
        if isinstance(group_params, Mapping):
            group_data = cast("Mapping[str, object]", group_params)
            identity = group_data.get("group_id")
            if not isinstance(identity, str):
                continue
            if action == "drawing.group.remove":
                explicit_members.setdefault(identity, []).append((index, None))
                continue
            members = group_data.get("members")
            if isinstance(members, list):
                try:
                    explicit_members.setdefault(identity, []).append(
                        (
                            index,
                            frozenset(
                                DrawingObjectRef.from_mapping(member)
                                for member in cast("list[object]", members)
                            ),
                        )
                    )
                except (TypeError, ValueError):
                    explicit_members.pop(identity, None)

    def explicitly_handled(group: DrawingGroup, member: DrawingObjectRef) -> bool:
        updates = explicit_members.get(group.group_id)
        if not updates:
            return False
        removed = removal_index.get((member.sketch_id or "", member.object_id), first_revision)
        before_removal = [members for index, members in updates if index < removed]
        if before_removal and (before_removal[-1] is None or member not in before_removal[-1]):
            return True
        after_removal = [members for index, members in updates if index > removed]
        if not after_removal:
            return False
        if after_removal[-1] is None:
            return True
        members_before_removal = before_removal[-1] if before_removal else frozenset(group.members)
        assert members_before_removal is not None
        removed_at_same_step = sum(
            item.kind == "geometry"
            and item in members_before_removal
            and (item.sketch_id, item.object_id) not in new
            and removal_index.get((item.sketch_id or "", item.object_id), first_revision) == removed
            for item in group.members
        )
        if removed_at_same_step > 1:
            # One later group update cannot establish which new object replaces
            # each of several members removed by the same sketch revision.
            return False
        return any(
            (item.sketch_id, item.object_id) in added
            for item in after_removal[-1]
            if item.kind == "geometry"
        )

    return tuple(
        (group.group_id, member)
        for group in before_groups
        for member in group.members
        if member.kind == "geometry"
        and (member.sketch_id, member.object_id) not in new
        and (added or member.sketch_id in modified_sketches)
        and not explicitly_handled(group, member)
    )


def unmapped_group_replacements(
    before_sketches: Sequence[Sketch],
    before_groups: Sequence[DrawingGroup],
    after_sketches: Sequence[Sketch],
    command_id: str,
    params: Mapping[str, object],
) -> tuple[DrawingObjectRef, ...]:
    """Return distinct source objects with at least one unmapped group membership."""
    memberships = unmapped_group_memberships(
        before_sketches, before_groups, after_sketches, command_id, params
    )
    return tuple(dict.fromkeys(member for _group_id, member in memberships))


def remap_group_members(
    groups: Sequence[DrawingGroup],
    mapping: Mapping[DrawingObjectRef, Sequence[DrawingObjectRef]],
) -> tuple[DrawingGroup, ...]:
    """Replace mapped members in order; an empty replacement deletes a member."""
    result: list[DrawingGroup] = []
    for group in groups:
        members: dict[DrawingObjectRef, None] = {}
        for member in group.members:
            for replacement in mapping.get(member, (member,)):
                members[replacement] = None
        if members:
            result.append(replace(group, members=tuple(members)))
    return tuple(result)


def copy_complete_groups(
    groups: Sequence[DrawingGroup],
    mapping: Mapping[DrawingObjectRef, DrawingObjectRef],
    new_group_ids: Mapping[str, str],
) -> tuple[DrawingGroup, ...]:
    """Copy only groups whose entire membership has a corresponding copy."""
    existing = DrawingGroupTable(tuple(groups))
    names = {group.name.casefold() for group in existing.groups if group.name is not None}
    reserved_ids = {UUID(group.group_id).hex for group in existing.groups}
    reserved_members = {
        (member.kind, UUID(member.object_id).hex)
        for group in existing.groups
        for member in group.members
    }
    copied_owners: dict[tuple[str, str], DrawingObjectRef] = {}
    result: list[DrawingGroup] = []
    for group in groups:
        if not all(member in mapping for member in group.members):
            continue
        for member in group.members:
            target = mapping[member]
            target_identity = UUID(target.object_id).hex
            key = (target.kind, target_identity)
            if target.kind != member.kind:
                raise ValueError("副本成员类型与来源不一致。")
            if target.object_id != target_identity or key in reserved_members:
                raise ValueError("副本成员必须使用新的 UUID hex 身份。")
            if key in copied_owners and copied_owners[key] != member:
                raise ValueError("不同来源不能共用副本成员身份。")
            copied_owners[key] = member
        identity = new_group_ids.get(group.group_id)
        try:
            if identity is None or identity != UUID(identity).hex:
                raise ValueError("副本组身份必须是 UUID hex。")
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("副本组身份必须是 UUID hex。") from exc
        if identity in reserved_ids:
            raise ValueError("副本组身份与现有组重复。")
        reserved_ids.add(identity)
        name = None
        if group.name is not None:
            base = f"{group.name} 副本"
            name = base
            index = 2
            while name.casefold() in names:
                name = f"{base} {index}"
                index += 1
            names.add(name.casefold())
        result.append(
            replace(
                group,
                group_id=identity,
                name=name,
                members=tuple(mapping[m] for m in group.members),
            )
        )
    DrawingGroupTable((*existing.groups, *result))
    return tuple(result)
