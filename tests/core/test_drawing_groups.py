# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent drawing groups use typed, durable object references."""

from typing import cast
from uuid import uuid4

import pytest

from mycad.core.drawing_groups import (
    DrawingGroup,
    DrawingGroupTable,
    DrawingObjectRef,
    expand_group_selection,
)
from mycad.core.drawing_object_refs import (
    DrawingObjectCatalog,
    copy_complete_groups,
    remap_group_members,
    validate_group_members,
)


def test_selection_expands_only_direct_groups() -> None:
    sketch_id = uuid4().hex
    a = DrawingObjectRef("geometry", uuid4().hex, sketch_id)
    b = DrawingObjectRef("text", uuid4().hex)
    c = DrawingObjectRef("raster", uuid4().hex)
    first = DrawingGroup(uuid4().hex, (a, b), name="first")
    second = DrawingGroup(uuid4().hex, (b, c), name="second")
    assert expand_group_selection((a,), (first, second)) == frozenset((a, b))
    assert expand_group_selection((b,), (first, second)) == frozenset((a, b, c))
    assert DrawingGroup.from_mapping(first.to_mapping()) == first


def test_group_validation_and_disabled_selection() -> None:
    obj = DrawingObjectRef("text", uuid4().hex)
    other = DrawingObjectRef("raster", uuid4().hex)
    group = DrawingGroup(uuid4().hex, (obj, other), selectable=False)
    assert expand_group_selection((obj,), (group,)) == frozenset((obj,))
    with pytest.raises(ValueError):
        DrawingGroup(uuid4().hex, (obj, obj))
    with pytest.raises(ValueError):
        DrawingObjectRef("geometry", uuid4().hex)
    with pytest.raises(ValueError):
        DrawingObjectRef("text", uuid4().hex, uuid4().hex)
    with pytest.raises(ValueError):
        DrawingObjectRef("group", uuid4().hex)


def test_group_table_updates_and_removes_deleted_members_without_mutating_original() -> None:
    a = DrawingObjectRef("text", uuid4().hex)
    b = DrawingObjectRef("raster", uuid4().hex)
    group = DrawingGroup(uuid4().hex, (a, b), name="Detail")
    original = DrawingGroupTable().add(group)
    with pytest.raises(ValueError, match="name"):
        original.add(DrawingGroup(uuid4().hex, (a,), name="detail"))
    after = original.without_members((a,))
    assert original.groups == (group,)
    assert after.groups == (DrawingGroup(group.group_id, (b,), name="Detail"),)
    assert after.without_members((b,)).groups == ()
    assert original.remove(group.group_id).groups == ()
    with pytest.raises(ValueError, match="exist"):
        original.remove(uuid4().hex)


def test_mutable_inputs_are_frozen() -> None:
    obj = DrawingObjectRef("text", uuid4().hex)
    raw_members = [obj]
    group = DrawingGroup(uuid4().hex, cast("tuple[DrawingObjectRef, ...]", raw_members))
    raw_groups = [group]
    table = DrawingGroupTable(cast("tuple[DrawingGroup, ...]", raw_groups))
    raw_members.clear()
    raw_groups.clear()
    assert group.members == (obj,)
    assert table.groups == (group,)


def test_member_remap_expands_deduplicates_and_removes_empty_groups() -> None:
    a, b, c, d = (DrawingObjectRef("text", uuid4().hex) for _ in range(4))
    first = DrawingGroup(uuid4().hex, (a, b))
    second = DrawingGroup(uuid4().hex, (b,))
    result = remap_group_members((first, second), {a: (c, d, c), b: ()})
    assert result == (DrawingGroup(first.group_id, (c, d)),)


def test_copy_only_complete_groups_and_validate_identity_map() -> None:
    a, b, copied_a, copied_b = (DrawingObjectRef("text", uuid4().hex) for _ in range(4))
    first = DrawingGroup(uuid4().hex, (a, b), name="details")
    second = DrawingGroup(uuid4().hex, (a,), name="label")
    id_first, id_second = uuid4().hex, uuid4().hex
    copies = copy_complete_groups((first, second), {a: copied_a}, {second.group_id: id_second})
    assert copies == (DrawingGroup(id_second, (copied_a,), name="label 副本"),)
    copies = copy_complete_groups(
        (first, second),
        {a: copied_a, b: copied_b},
        {first.group_id: id_first, second.group_id: id_second},
    )
    assert tuple(group.members for group in copies) == ((copied_a, copied_b), (copied_a,))
    with pytest.raises(ValueError):
        copy_complete_groups((first,), {a: copied_a, b: copied_b}, {})


def test_catalog_rejects_missing_wrong_kind_and_wrong_owner() -> None:
    sketch_id, other_sketch = uuid4().hex, uuid4().hex
    entity_id = uuid4().hex
    ref = DrawingObjectRef("geometry", entity_id, sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    validate_group_members((group,), DrawingObjectCatalog((ref,)))
    for wrong in (
        DrawingObjectRef("geometry", entity_id, other_sketch),
        DrawingObjectRef("text", entity_id),
    ):
        with pytest.raises(ValueError, match="不存在"):
            validate_group_members((group,), DrawingObjectCatalog((wrong,)))


def test_copied_group_requires_new_hex_identity() -> None:
    obj = DrawingObjectRef("text", uuid4().hex)
    copy = DrawingObjectRef("text", uuid4().hex)
    group = DrawingGroup(uuid4().hex, (obj,))
    with pytest.raises(ValueError):
        copy_complete_groups((group,), {obj: copy}, {group.group_id: str(uuid4())})


def test_group_copy_rejects_hex_alias_of_legacy_group_identity() -> None:
    identity = uuid4()
    obj = DrawingObjectRef("text", uuid4().hex)
    copied_obj = DrawingObjectRef("text", uuid4().hex)
    group = DrawingGroup(str(identity), (obj,), name="Legacy")
    with pytest.raises(ValueError, match="身份"):
        copy_complete_groups((group,), {obj: copied_obj}, {group.group_id: identity.hex})
    assert group.group_id == str(identity)


def test_group_copy_requires_new_same_kind_member_identities() -> None:
    identity = uuid4()
    source = DrawingObjectRef("text", str(identity))
    group = DrawingGroup(uuid4().hex, (source,))
    new_group_id = uuid4().hex
    invalid = (
        DrawingObjectRef("text", identity.hex),
        DrawingObjectRef("raster", uuid4().hex),
        DrawingObjectRef("text", str(uuid4())),
    )
    for target in invalid:
        with pytest.raises(ValueError, match="身份|类型"):
            copy_complete_groups((group,), {source: target}, {group.group_id: new_group_id})


def test_group_copy_rejects_two_sources_sharing_one_target() -> None:
    first, second, target = (DrawingObjectRef("text", uuid4().hex) for _ in range(3))
    groups = (DrawingGroup(uuid4().hex, (first,)), DrawingGroup(uuid4().hex, (second,)))
    with pytest.raises(ValueError, match="身份"):
        copy_complete_groups(
            groups, {first: target, second: target}, {item.group_id: uuid4().hex for item in groups}
        )


def test_group_copy_keeps_cross_type_identity_namespaces_distinct() -> None:
    source_id, copy_id = str(uuid4()), uuid4().hex
    text = DrawingObjectRef("text", source_id)
    raster = DrawingObjectRef("raster", source_id)
    copied_text = DrawingObjectRef("text", copy_id)
    copied_raster = DrawingObjectRef("raster", copy_id)
    group = DrawingGroup(uuid4().hex, (text, raster))
    copy = copy_complete_groups(
        (group,), {text: copied_text, raster: copied_raster}, {group.group_id: uuid4().hex}
    )[0]
    assert copy.members == (copied_text, copied_raster)
    assert group.members == (text, raster)
