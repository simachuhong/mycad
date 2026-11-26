# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Stable identities and validation for associative rectangular arrays."""

from dataclasses import replace
from uuid import uuid4

import pytest

from mycad.core.associative_array import (
    ArrayEntityRef,
    ArrayMember,
    AssociativeRectArray,
    propagate_array_changes,
    validate_array_network,
)
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame


def _ref() -> ArrayEntityRef:
    return ArrayEntityRef(uuid4().hex, uuid4().hex)


def _array(
    source: ArrayEntityRef | None = None, target: ArrayEntityRef | None = None
) -> AssociativeRectArray:
    source = source or _ref()
    target = target or _ref()
    return AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        5,
        (source,),
        (ArrayMember(source, target, 0, 1),),
    )


@pytest.mark.parametrize("kind", ["polyline", "spline"])
def test_array_spacing_preserves_independent_curve_point_identities(kind: str) -> None:
    from mycad.core.associative_array import update_array_spacing
    from mycad.core.geometric_tolerance_topology import new_curve_point_identities
    from mycad.core.sketch import PolylineEntity, SplineEntity

    source_id, target_id, sketch_id = uuid4().hex, uuid4().hex, uuid4().hex
    points = ((0, 0), (1, 0), (1, 1), (2, 1))
    shifted = tuple((x + 5, y) for x, y in points)
    source_ids = new_curve_point_identities(source_id, kind, 4)
    target_ids = new_curve_point_identities(target_id, kind, 4)
    source = (
        PolylineEntity(source_id, points, point_ids=source_ids)
        if kind == "polyline"
        else SplineEntity(source_id, points, point_ids=source_ids)
    )
    target = (
        PolylineEntity(target_id, shifted, point_ids=target_ids)
        if kind == "polyline"
        else SplineEntity(target_id, shifted, point_ids=target_ids)
    )
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (source, target))
    origin, member = ArrayEntityRef(sketch_id, source_id), ArrayEntityRef(sketch_id, target_id)
    array = _array(origin, member)
    (updated,), _ = update_array_spacing((sketch,), (array,), array.array_id, 0, 8)
    assert isinstance(updated.entities[1], PolylineEntity | SplineEntity)
    assert updated.entities[1].point_ids == target_ids
    assert updated.entities[0] == source


def test_array_resize_assigns_new_curve_member_independent_identities() -> None:
    from mycad.core.associative_array import resize_array
    from mycad.core.geometric_tolerance_topology import new_curve_point_identities
    from mycad.core.sketch import PolylineEntity

    source_id, target_id, sketch_id = uuid4().hex, uuid4().hex, uuid4().hex
    points = ((0, 0), (1, 0), (1, 1))
    source = PolylineEntity(
        source_id, points, point_ids=new_curve_point_identities(source_id, "polyline", 3)
    )
    target = PolylineEntity(
        target_id,
        ((5, 0), (6, 0), (6, 1)),
        point_ids=new_curve_point_identities(target_id, "polyline", 3),
    )
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (source, target))
    origin, member = ArrayEntityRef(sketch_id, source_id), ArrayEntityRef(sketch_id, target_id)
    array = _array(origin, member)
    new_id = uuid4().hex
    new_member = ArrayEntityRef(sketch_id, new_id)
    expanded = replace(
        array, columns=3, members=(*array.members, ArrayMember(origin, new_member, 0, 2))
    )
    (updated,) = resize_array((sketch,), (array,), expanded)
    addition = updated.entities[-1]
    assert isinstance(addition, PolylineEntity)
    assert addition.point_ids == new_curve_point_identities(new_id, "polyline", 3)
    assert set(addition.point_ids).isdisjoint(source.point_ids + target.point_ids)


def test_array_extra_outputs_have_stable_identity_and_valid_dependencies() -> None:
    from mycad.core.associative_array import ArrayExtraOutput

    array = _array()
    extra_target, replacement = _ref(), _ref()
    extra = ArrayExtraOutput(replacement, extra_target, array.sources[0], 0, 1, (2, 3))
    expanded = replace(array, extra_outputs=(extra,))
    assert AssociativeRectArray.from_mapping(expanded.to_mapping()) == expanded
    assert "extra_outputs" not in array.to_mapping()
    validate_array_network((expanded,))
    with pytest.raises(ValueError):
        replace(expanded, extra_outputs=(replace(extra, target=array.members[0].target),))
    with pytest.raises(ValueError):
        replace(expanded, extra_outputs=(replace(extra, column=2),))
    with pytest.raises(ValueError):
        replace(expanded, extra_outputs=(replace(extra, anchor_source=_ref()),))
    downstream_target = _ref()
    downstream = _array(extra_target, downstream_target)
    cycle = replace(expanded, extra_outputs=(replace(extra, source=downstream_target),))
    with pytest.raises(ValueError, match="环"):
        validate_array_network((cycle, downstream))


def test_extra_output_offset_preserves_base_and_propagates_downstream() -> None:
    from mycad.core.associative_array import ArrayExtraOutput, set_array_member_offsets

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    replacement = LineEntity(uuid4().hex, (20, 20), (22, 20))
    extra = LineEntity(uuid4().hex, (3, -3), (5, -3))
    downstream_target = LineEntity(uuid4().hex, (8, -3), (10, -3))
    sketch = Sketch(
        identity, WorkPlaneFrame.xy(), (source, target, replacement, extra, downstream_target)
    )
    origin, member, replacement_ref, extra_ref, downstream_ref = tuple(
        ArrayEntityRef(identity, entity.entity_id) for entity in sketch.entities
    )
    output = ArrayExtraOutput(replacement_ref, extra_ref, origin, 0, 1, (2, 3))
    upstream = replace(_array(origin, member), extra_outputs=(output,))
    downstream = _array(extra_ref, downstream_ref)
    assert "offset_mm" not in output.to_mapping()
    changed, updated = set_array_member_offsets(
        (sketch,), (upstream, downstream), upstream.array_id, {extra_ref: (4, 2)}
    )
    assert updated.extra_outputs[0].base_offset_mm == (2, 3)
    assert updated.extra_outputs[0].offset_mm == (4, 2)
    assert AssociativeRectArray.from_mapping(updated.to_mapping()) == updated
    assert changed[0].entities[3:] == (
        replace(extra, start_mm=(7, -1), end_mm=(9, -1)),
        replace(downstream_target, start_mm=(12, -1), end_mm=(14, -1)),
    )
    restored, original = set_array_member_offsets(
        changed, (updated, downstream), upstream.array_id, {}, reset_all=True
    )
    assert restored == (sketch,) and original == upstream


def test_extra_output_rotation_preserves_offset_and_propagates_downstream() -> None:
    from mycad.core.associative_array import ArrayExtraOutput, set_array_member_rotations

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    replacement = LineEntity(uuid4().hex, (20, 20), (22, 20))
    extra = LineEntity(uuid4().hex, (8, 4), (10, 4))
    dependent = LineEntity(uuid4().hex, (13, 4), (15, 4))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target, replacement, extra, dependent))
    origin, member, replacement_ref, extra_ref, dependent_ref = tuple(
        ArrayEntityRef(identity, item.entity_id) for item in sketch.entities
    )
    output = ArrayExtraOutput(replacement_ref, extra_ref, origin, 0, 1, offset_mm=(3, 4))
    upstream = replace(_array(origin, member), extra_outputs=(output,))
    downstream = _array(extra_ref, dependent_ref)
    assert "rotation_deg" not in output.to_mapping()
    changed, updated = set_array_member_rotations(
        (sketch,), (upstream, downstream), upstream.array_id, {extra_ref: (90, (0, 0))}
    )
    assert updated.extra_outputs[0].offset_mm == (3, 4)
    assert updated.extra_outputs[0].rotation_deg == 90
    assert AssociativeRectArray.from_mapping(updated.to_mapping()) == updated
    for result, start, end in zip(
        changed[0].entities[3:], ((8, 4), (13, 4)), ((8, 6), (13, 6)), strict=True
    ):
        assert isinstance(result, LineEntity)
        assert result.start_mm == pytest.approx(start) and result.end_mm == pytest.approx(end)
    restored, original = set_array_member_rotations(
        changed, (updated, downstream), upstream.array_id, {extra_ref: (0, (0, 0))}
    )
    assert restored == (sketch,) and original == upstream


@pytest.mark.parametrize("angle", [float("nan"), float("inf"), True])
def test_extra_output_rejects_invalid_rotation(angle: object) -> None:
    from typing import cast

    from mycad.core.associative_array import ArrayExtraOutput

    with pytest.raises(ValueError):
        ArrayExtraOutput(_ref(), _ref(), _ref(), 0, 1, rotation_deg=cast("float", angle))


def test_extra_output_rotation_rejects_fixed_constraint() -> None:
    from mycad.core.associative_array import ArrayExtraOutput, set_array_member_rotations
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y)) for x, y in ((0, 0), (5, 0), (20, 20), (5, 0))
    )
    refs = tuple(ArrayEntityRef(identity, item.entity_id) for item in lines)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(lines[3].entity_id, "end"),)
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines, (fixed,))
    output = ArrayExtraOutput(refs[2], refs[3], refs[0], 0, 1)
    array = replace(_array(refs[0], refs[1]), extra_outputs=(output,))
    with pytest.raises(ValueError, match="约束"):
        set_array_member_rotations((sketch,), (array,), array.array_id, {refs[3]: (90, (0, 0))})
    assert sketch.entities == lines and array.extra_outputs == (output,)


@pytest.mark.parametrize("value", [(float("nan"), 0), (float("inf"), 0), (True, 0)])
def test_extra_output_rejects_invalid_position_offset(value: tuple[object, object]) -> None:
    from typing import cast

    from mycad.core.associative_array import ArrayExtraOutput
    from mycad.core.sketch import Point2D

    with pytest.raises(ValueError):
        ArrayExtraOutput(_ref(), _ref(), _ref(), 0, 1, offset_mm=cast("Point2D", value))


@pytest.mark.parametrize("fixed", [False, True])
def test_extra_output_offset_preserves_or_rejects_constraints(fixed: bool) -> None:
    from mycad.core.associative_array import ArrayExtraOutput, set_array_member_offsets
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y)) for x, y in ((0, 0), (5, 0), (20, 20), (5, 0))
    )
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    constraint = (
        SketchConstraint(
            uuid4().hex, "fixed", (SketchGeometryReference(lines[3].entity_id, "start"),)
        )
        if fixed
        else SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(lines[3].entity_id, "geometry"),),
            2,
            "mm",
            position_mm=(6, 2),
            text_position_mm=(6, 3),
        )
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines, (constraint,))
    output = ArrayExtraOutput(refs[2], refs[3], refs[0], 0, 1)
    array = replace(_array(refs[0], refs[1]), extra_outputs=(output,))
    if fixed:
        with pytest.raises(ValueError, match="约束"):
            set_array_member_offsets((sketch,), (array,), array.array_id, {refs[3]: (2, 3)})
        assert array.extra_outputs == (output,) and sketch.entities == lines
        return
    result, updated = set_array_member_offsets(
        (sketch,), (array,), array.array_id, {refs[3]: (2, 3)}
    )
    assert result[0].constraints[0].position_mm == (8, 5)
    assert result[0].constraints[0].text_position_mm == (8, 6)
    restored, _ = set_array_member_offsets(result, (updated,), updated.array_id, {}, reset_all=True)
    assert restored == (sketch,)


@pytest.mark.parametrize("locked,visible", [(True, True), (False, False)])
def test_extra_output_offset_rejects_unavailable_target_layer(locked: bool, visible: bool) -> None:
    from mycad.core.associative_array import (
        ArrayExtraOutput,
        set_array_member_offsets,
        set_array_member_rotations,
    )
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    identity = uuid4().hex
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y)) for x, y in ((0, 0), (5, 0), (20, 20), (5, 0))
    )
    layers = SketchLayerTable((SketchLayer("0", locked=locked, visible=visible),))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines, layers=layers)
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    output = ArrayExtraOutput(refs[2], refs[3], refs[0], 0, 1)
    array = replace(_array(refs[0], refs[1]), extra_outputs=(output,))
    with pytest.raises(ValueError, match="锁定|隐藏"):
        set_array_member_offsets((sketch,), (array,), array.array_id, {refs[3]: (2, 3)})
    with pytest.raises(ValueError, match="锁定|隐藏"):
        set_array_member_rotations((sketch,), (array,), array.array_id, {refs[3]: (90, (0, 0))})
    assert sketch.entities == lines and array.extra_outputs == (output,)


def test_extra_output_follows_anchor_across_translated_sketch_frames() -> None:
    from mycad.core.associative_array import (
        ArrayExtraOutput,
        array_member_rotation_anchor,
        set_array_member_offsets,
        set_array_member_rotations,
    )

    frame = WorkPlaneFrame.xy()
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (15, 0), (17, 0))
    replacement = LineEntity(uuid4().hex, (40, 20), (42, 20))
    extra_entity = LineEntity(uuid4().hex, (15, 0), (17, 0))
    source_sketch = Sketch(uuid4().hex, replace(frame, origin_mm=(100, 0, 0)), (source,))
    target_sketch = Sketch(
        uuid4().hex, replace(frame, origin_mm=(90, 0, 0)), (target, extra_entity)
    )
    replacement_sketch = Sketch(uuid4().hex, replace(frame, origin_mm=(80, 0, 0)), (replacement,))
    origin = ArrayEntityRef(source_sketch.sketch_id, source.entity_id)
    copy = ArrayEntityRef(target_sketch.sketch_id, target.entity_id)
    output = ArrayExtraOutput(
        ArrayEntityRef(replacement_sketch.sketch_id, replacement.entity_id),
        ArrayEntityRef(target_sketch.sketch_id, extra_entity.entity_id),
        origin,
        0,
        1,
    )
    array = replace(_array(origin, copy), frame=source_sketch.frame, extra_outputs=(output,))
    moved = replace(source_sketch, entities=(replace(source, start_mm=(2, 0), end_mm=(4, 0)),))
    result = propagate_array_changes(
        (source_sketch, target_sketch, replacement_sketch),
        (moved, target_sketch, replacement_sketch),
        (array,),
    )
    assert result[1].entities == (
        replace(target, start_mm=(17, 0), end_mm=(19, 0)),
        replace(extra_entity, start_mm=(17, 0), end_mm=(19, 0)),
    )
    shifted, updated = set_array_member_offsets(
        result, (array,), array.array_id, {output.target: (3, 4)}
    )
    assert shifted[1].entities[1] == replace(extra_entity, start_mm=(20, 4), end_mm=(22, 4))
    assert array_member_rotation_anchor(updated, updated.extra_outputs[0], shifted) == (20, 4)
    rotated, rotated_array = set_array_member_rotations(
        shifted, (updated,), updated.array_id, {output.target: (90, (2, 0))}
    )
    rotated_extra = rotated[1].entities[1]
    assert isinstance(rotated_extra, LineEntity)
    assert rotated_extra.start_mm == pytest.approx((22, 2))
    assert rotated_extra.end_mm == pytest.approx((22, 4))
    shifted_again, _ = set_array_member_rotations(
        rotated, (rotated_array,), rotated_array.array_id, {output.target: (0, (0, 0))}
    )
    assert shifted_again == shifted
    restored, _ = set_array_member_offsets(
        shifted, (updated,), updated.array_id, {}, reset_all=True
    )
    assert restored == result


@pytest.mark.parametrize("offset", [(0, 0), (3, 4)])
@pytest.mark.parametrize("rotated", [False, True])
def test_resize_removes_extra_outputs_only_with_their_cells(
    offset: tuple[int, int], rotated: bool
) -> None:
    from mycad.core.associative_array import ArrayExtraOutput, resize_array

    identity = uuid4().hex
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y))
        for x, y in ((0, 0), (5, 0), (10, 0), (20, 20), (10 + offset[0], offset[1]))
    )
    if rotated:
        lines = (*lines[:4], replace(lines[4], end_mm=(10 + offset[0], offset[1] + 2)))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(identity, item.entity_id) for item in lines)
    extra = ArrayExtraOutput(
        refs[3], refs[4], refs[0], 0, 2, offset_mm=offset, rotation_deg=90 if rotated else 0
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
        extra_outputs=(extra,),
    )
    smaller = replace(array, columns=2, members=(array.members[0],), extra_outputs=())
    result = resize_array((sketch,), (array,), smaller)
    assert result[0].entities == (lines[0], lines[1], lines[3])
    downstream_entity = LineEntity(
        uuid4().hex,
        (15 + offset[0], offset[1]),
        (15 + offset[0], offset[1] + 2) if rotated else (17 + offset[0], offset[1]),
    )
    dependent = replace(sketch, entities=(*sketch.entities, downstream_entity))
    downstream = _array(refs[4], ArrayEntityRef(identity, downstream_entity.entity_id))
    with pytest.raises(ValueError, match="来源|引用"):
        resize_array((dependent,), (array, downstream), smaller)


def test_array_extra_output_tracks_anchor_and_replacement_source() -> None:
    from mycad.core.associative_array import ArrayExtraOutput

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    replacement = LineEntity(uuid4().hex, (20, 20), (22, 20))
    extra_entity = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target, replacement, extra_entity))
    origin, copy, replacement_ref, extra_ref = tuple(
        ArrayEntityRef(identity, item.entity_id) for item in sketch.entities
    )
    array = replace(
        _array(origin, copy),
        extra_outputs=(ArrayExtraOutput(replacement_ref, extra_ref, origin, 0, 1),),
    )
    revised = replace(
        sketch,
        entities=(
            replace(source, start_mm=(2, 0), end_mm=(4, 0)),
            target,
            replacement,
            extra_entity,
        ),
    )
    changed = propagate_array_changes((sketch,), (revised,), (array,))
    assert changed[0].entities[1] == replace(target, start_mm=(7, 0), end_mm=(9, 0))
    assert changed[0].entities[3] == replace(extra_entity, start_mm=(7, 0), end_mm=(9, 0))
    altered = replace(
        changed[0],
        entities=tuple(
            replace(replacement, end_mm=(23, 20))
            if item.entity_id == replacement.entity_id
            else item
            for item in changed[0].entities
        ),
    )
    updated = propagate_array_changes(changed, (altered,), (array,))
    assert updated[0].entities[3] == replace(extra_entity, start_mm=(7, 0), end_mm=(10, 0))
    direct = replace(
        updated[0],
        entities=tuple(
            replace(extra_entity, start_mm=(100, 0), end_mm=(102, 0))
            if item.entity_id == extra_entity.entity_id
            else item
            for item in updated[0].entities
        ),
    )
    with pytest.raises(ValueError, match="副本不能直接修改"):
        propagate_array_changes(updated, (direct,), (array,))


def test_cell_replacement_creates_and_resets_extra_output() -> None:
    from mycad.core.associative_array import (
        ArrayExtraOutput,
        ArrayReplacement,
        replace_array_cell_with_extra_outputs,
        reset_array_member_overrides,
        set_array_member_rotations,
    )

    identity = uuid4().hex
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y))
        for x, y in ((0, 0), (0, 4), (5, 0), (5, 4), (20, 20), (20, 25), (20, 30))
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(identity, entity.entity_id) for entity in lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        refs[:2],
        (ArrayMember(refs[0], refs[2], 0, 1), ArrayMember(refs[1], refs[3], 0, 1)),
    )
    extra_target = ArrayEntityRef(identity, uuid4().hex)
    extra = ArrayExtraOutput(refs[6], extra_target, refs[0], 0, 1, (0, -10))
    changed, updated = replace_array_cell_with_extra_outputs(
        (sketch,),
        (array,),
        array.array_id,
        {
            refs[2]: ArrayReplacement(refs[4], (0, 0), refs[0]),
            refs[3]: ArrayReplacement(refs[5], (0, -5), refs[0]),
        },
        (extra,),
    )
    output = next(
        entity for entity in changed[0].entities if entity.entity_id == extra_target.entity_id
    )
    assert isinstance(output, LineEntity) and output.start_mm == pytest.approx((5, 10))
    assert updated.extra_outputs == (extra,)
    rotated, rotated_array = set_array_member_rotations(
        changed, (updated,), updated.array_id, {extra_target: (90, (1, 0))}
    )
    reset_rotated, reset_array = reset_array_member_overrides(
        rotated, (rotated_array,), array.array_id
    )
    assert reset_rotated == (sketch,) and reset_array == array
    downstream_entity = LineEntity(uuid4().hex, (10, 10), (12, 10))
    dependent = replace(changed[0], entities=(*changed[0].entities, downstream_entity))
    downstream = _array(extra_target, ArrayEntityRef(identity, downstream_entity.entity_id))
    from mycad.core.associative_array import (
        move_associative_array_with_offsets,
        set_array_member_offsets,
    )

    shifted, shifted_array = set_array_member_offsets(
        (dependent,), (updated, downstream), updated.array_id, {extra_target: (3, 4)}
    )
    shifted_move, shifted_arrays = move_associative_array_with_offsets(
        shifted, (shifted_array, downstream), downstream.array_id, (2, 0)
    )
    assert shifted_arrays[0].extra_outputs[0].base_offset_mm == pytest.approx((-2, -10))
    assert shifted_arrays[0].extra_outputs[0].offset_mm == (3, 4)
    shifted_extra = next(
        item for item in shifted_move[0].entities if item.entity_id == extra_target.entity_id
    )
    assert isinstance(shifted_extra, LineEntity) and shifted_extra.start_mm == pytest.approx(
        (10, 14)
    )

    moved_downstream, moved_arrays = move_associative_array_with_offsets(
        (dependent,), (updated, downstream), downstream.array_id, (2, 0)
    )
    moved_extra = next(
        item for item in moved_downstream[0].entities if item.entity_id == extra_target.entity_id
    )
    moved_copy = next(
        item
        for item in moved_downstream[0].entities
        if item.entity_id == downstream_entity.entity_id
    )
    assert isinstance(moved_extra, LineEntity) and moved_extra.start_mm == pytest.approx((7, 10))
    assert isinstance(moved_copy, LineEntity) and moved_copy.start_mm == pytest.approx((12, 10))
    assert moved_arrays[0].extra_outputs[0].base_offset_mm == pytest.approx((-2, -10))
    moved_source = replace(lines[0], start_mm=(2, 0), end_mm=(4, 0))
    proposed = replace(
        dependent,
        entities=tuple(
            moved_source if entity.entity_id == moved_source.entity_id else entity
            for entity in dependent.entities
        ),
    )
    propagated = propagate_array_changes((dependent,), (proposed,), (updated, downstream))
    propagated_extra = next(
        item for item in propagated[0].entities if item.entity_id == extra_target.entity_id
    )
    propagated_downstream = next(
        item for item in propagated[0].entities if item.entity_id == downstream_entity.entity_id
    )
    assert isinstance(propagated_extra, LineEntity) and propagated_extra.start_mm == pytest.approx(
        (7, 10)
    )
    assert isinstance(
        propagated_downstream, LineEntity
    ) and propagated_downstream.start_mm == pytest.approx((12, 10))
    with pytest.raises(ValueError, match="引用"):
        reset_array_member_overrides((dependent,), (updated, downstream), array.array_id)
    from mycad.core.associative_array import erase_drawing_entities

    with pytest.raises(ValueError, match="引用|来源"):
        erase_drawing_entities((dependent,), (updated, downstream), (extra_target,))
    erased, erased_arrays = erase_drawing_entities(changed, (updated,), (extra_target,))
    assert extra_target.entity_id not in {entity.entity_id for entity in erased[0].entities}
    assert not erased_arrays[0].extra_outputs
    after_erase_reset, _ = reset_array_member_overrides(erased, erased_arrays, array.array_id)
    assert after_erase_reset == (sketch,)
    restored, reset = reset_array_member_overrides(changed, (updated,), array.array_id)
    assert restored == (sketch,) and reset == array


def test_cell_replacement_with_fewer_entities_restores_original_members() -> None:
    from mycad.core.associative_array import (
        ArrayReplacement,
        replace_and_erase_array_members,
        reset_array_member_overrides,
        set_array_member_replacements,
    )

    identity = uuid4().hex
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y))
        for x, y in ((0, 0), (0, 4), (5, 0), (5, 4), (20, 20))
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        refs[:2],
        (ArrayMember(refs[0], refs[2], 0, 1), ArrayMember(refs[1], refs[3], 0, 1)),
    )
    changed, updated = replace_and_erase_array_members(
        (sketch,),
        (array,),
        array.array_id,
        {refs[2]: ArrayReplacement(refs[4], anchor_source=refs[0])},
        (refs[3],),
    )
    assert refs[3].entity_id not in {entity.entity_id for entity in changed[0].entities}
    assert updated.members[1].erased_index is not None
    restored, reset = reset_array_member_overrides(changed, (updated,), array.array_id)
    assert restored == (sketch,) and reset == array
    prior, prior_array = set_array_member_replacements(
        (sketch,),
        (array,),
        array.array_id,
        {refs[2]: ArrayReplacement(refs[4], anchor_source=refs[0])},
    )
    after, _ = replace_and_erase_array_members(
        prior,
        (prior_array,),
        array.array_id,
        {refs[2]: ArrayReplacement(refs[4], anchor_source=refs[0])},
        (refs[3],),
    )
    assert refs[3].entity_id not in {entity.entity_id for entity in after[0].entities}
    downstream_entity = LineEntity(uuid4().hex, (10, 4), (12, 4))
    with_downstream = replace(sketch, entities=(*sketch.entities, downstream_entity))
    downstream = _array(refs[3], ArrayEntityRef(identity, downstream_entity.entity_id))
    with pytest.raises(ValueError, match="来源|引用"):
        replace_and_erase_array_members(
            (with_downstream,),
            (array, downstream),
            array.array_id,
            {refs[2]: ArrayReplacement(refs[4], anchor_source=refs[0])},
            (refs[3],),
        )
    assert (
        with_downstream.entities[-1] == downstream_entity and array.members[1].erased_index is None
    )


def test_multi_entity_replacement_follows_shared_anchor_when_sources_move() -> None:
    from mycad.core.associative_array import ArrayReplacement, set_array_member_replacements

    identity = uuid4().hex
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y))
        for x, y in ((0, 0), (0, 4), (5, 0), (5, 4), (20, 20), (20, 25))
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        refs[:2],
        (ArrayMember(refs[0], refs[2], 0, 1), ArrayMember(refs[1], refs[3], 0, 1)),
    )
    result, updated = set_array_member_replacements(
        (sketch,),
        (array,),
        array.array_id,
        {
            refs[2]: ArrayReplacement(refs[4], (0, 0), anchor_source=refs[0]),
            refs[3]: ArrayReplacement(refs[5], (0, -5), anchor_source=refs[0]),
        },
    )
    first, second = result[0].entities[2:4]
    assert isinstance(first, LineEntity) and isinstance(second, LineEntity)
    assert first.start_mm == pytest.approx((5, 0))
    assert second.start_mm == pytest.approx((5, 5))
    moved_secondary = replace(
        result[0],
        entities=tuple(
            replace(line, start_mm=(0, 10), end_mm=(2, 10))
            if line.entity_id == refs[1].entity_id
            else line
            for line in result[0].entities
        ),
    )
    unchanged = propagate_array_changes(result, (moved_secondary,), (updated,))
    assert unchanged[0].entities[2:4] == result[0].entities[2:4]
    moved_primary = replace(
        unchanged[0],
        entities=tuple(
            replace(line, start_mm=(2, 0), end_mm=(4, 0))
            if line.entity_id == refs[0].entity_id
            else line
            for line in unchanged[0].entities
        ),
    )
    shifted = propagate_array_changes(unchanged, (moved_primary,), (updated,))
    first, second = shifted[0].entities[2:4]
    assert isinstance(first, LineEntity) and isinstance(second, LineEntity)
    assert first.start_mm == pytest.approx((7, 0))
    assert second.start_mm == pytest.approx((7, 5))


def test_shared_replacement_anchor_across_translated_sketch_frames() -> None:
    from mycad.core.associative_array import ArrayReplacement, set_array_member_replacements

    frame = WorkPlaneFrame.xy()
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (10, 4), (12, 4))
    target_a = LineEntity(uuid4().hex, (5, 0), (7, 0))
    target_b = LineEntity(uuid4().hex, (5, 4), (7, 4))
    replacement_a = LineEntity(uuid4().hex, (40, 20), (42, 20))
    replacement_b = LineEntity(uuid4().hex, (40, 25), (42, 25))
    first_sketch = Sketch(uuid4().hex, replace(frame, origin_mm=(100, 0, 0)), (first,))
    second_sketch = Sketch(uuid4().hex, replace(frame, origin_mm=(90, 0, 0)), (second,))
    target_sketch = Sketch(uuid4().hex, first_sketch.frame, (target_a, target_b))
    replacement_sketch = Sketch(
        uuid4().hex, replace(frame, origin_mm=(80, 0, 0)), (replacement_a, replacement_b)
    )
    origin_a = ArrayEntityRef(first_sketch.sketch_id, first.entity_id)
    origin_b = ArrayEntityRef(second_sketch.sketch_id, second.entity_id)
    copy_a = ArrayEntityRef(target_sketch.sketch_id, target_a.entity_id)
    copy_b = ArrayEntityRef(target_sketch.sketch_id, target_b.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        first_sketch.frame,
        1,
        2,
        0,
        5,
        (origin_a, origin_b),
        (ArrayMember(origin_a, copy_a, 0, 1), ArrayMember(origin_b, copy_b, 0, 1)),
    )
    result, _ = set_array_member_replacements(
        (first_sketch, second_sketch, target_sketch, replacement_sketch),
        (array,),
        array.array_id,
        {
            copy_a: ArrayReplacement(
                ArrayEntityRef(replacement_sketch.sketch_id, replacement_a.entity_id),
                (0, 0),
                origin_a,
            ),
            copy_b: ArrayReplacement(
                ArrayEntityRef(replacement_sketch.sketch_id, replacement_b.entity_id),
                (0, -5),
                origin_a,
            ),
        },
    )
    first_result, second_result = result[2].entities
    assert isinstance(first_result, LineEntity) and isinstance(second_result, LineEntity)
    assert first_result.start_mm == pytest.approx((5, 0))
    assert second_result.start_mm == pytest.approx((5, 5))


def test_mixed_erase_removes_ordinary_entities_and_multiple_array_members() -> None:
    from mycad.core.associative_array import erase_drawing_entities, reset_array_member_overrides

    identity = uuid4().hex
    lines = (
        LineEntity(uuid4().hex, (0, 0), (2, 0)),
        LineEntity(uuid4().hex, (5, 0), (7, 0)),
        LineEntity(uuid4().hex, (0, 5), (2, 5)),
        LineEntity(uuid4().hex, (5, 5), (7, 5)),
        LineEntity(uuid4().hex, (20, 0), (22, 0)),
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    first, second = _array(refs[0], refs[1]), _array(refs[2], refs[3])
    result, arrays = erase_drawing_entities((sketch,), (first, second), (refs[1], refs[3], refs[4]))
    assert result[0].entities == (lines[0], lines[2])
    assert all(array.members[0].erased_index is not None for array in arrays)
    result, restored_first = reset_array_member_overrides(result, arrays, first.array_id)
    result, restored_second = reset_array_member_overrides(
        result, (restored_first, arrays[1]), second.array_id
    )
    assert result[0].entities == lines[:4]
    assert restored_first == first and restored_second == second


def test_mixed_erase_removes_related_constraint_but_rejects_locked_layer_or_source() -> None:
    from mycad.core.associative_array import erase_drawing_entities
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    ordinary = LineEntity(uuid4().hex, (10, 0), (12, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(ordinary.entity_id, "geometry"),),
        2,
        "mm",
        layer_name="DIM",
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target, ordinary), (dimension,))
    refs = tuple(ArrayEntityRef(identity, entity.entity_id) for entity in sketch.entities)
    array = _array(refs[0], refs[1])
    changed, _ = erase_drawing_entities((sketch,), (array,), (refs[1], refs[2]))
    assert changed[0].entities == (source,) and not changed[0].constraints
    locked_layers = sketch.layers.replace(SketchLayer("DIM", locked=True))
    locked = replace(sketch, layers=locked_layers)
    with pytest.raises(ValueError, match="约束.*锁定"):
        erase_drawing_entities((locked,), (array,), (refs[1], refs[2]))
    with pytest.raises(ValueError, match="来源"):
        erase_drawing_entities((sketch,), (array,), (refs[0], refs[1]))
    assert sketch.entities == (source, target, ordinary) and sketch.constraints == (dimension,)


def test_replaced_member_follows_replacement_source_and_reset() -> None:
    from mycad.core.associative_array import (
        ArrayReplacement,
        reset_array_member_overrides,
        set_array_member_replacements,
    )
    from mycad.core.sketch import CircleEntity

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    replacement = CircleEntity(uuid4().hex, (20, 4), 2)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target, replacement))
    ref = ArrayEntityRef(identity, source.entity_id)
    copy = ArrayEntityRef(identity, target.entity_id)
    replacement_ref = ArrayEntityRef(identity, replacement.entity_id)
    array = _array(ref, copy)
    changed, updated = set_array_member_replacements(
        (sketch,), (array,), array.array_id, {copy: ArrayReplacement(replacement_ref, (0, 0))}
    )
    circle = changed[0].entities[1]
    assert isinstance(circle, CircleEntity)
    assert circle.entity_id == target.entity_id and circle.center_mm == (5, 0)
    assert AssociativeRectArray.from_mapping(updated.to_mapping()) == updated
    proposed = replace(changed[0], entities=(source, circle, replace(replacement, radius_mm=3)))
    propagated = propagate_array_changes(changed, (proposed,), (updated,))
    result = propagated[0].entities[1]
    assert isinstance(result, CircleEntity) and result.radius_mm == 3
    restored, reset = reset_array_member_overrides(propagated, (updated,), array.array_id)
    assert restored[0].entities[1] == target and reset == array


def test_replacement_source_from_upstream_array_propagates_before_dependent() -> None:
    from mycad.core.associative_array import ArrayReplacement, set_array_member_replacements

    identity = uuid4().hex
    upstream_source = LineEntity(uuid4().hex, (0, 0), (3, 0))
    upstream_member = LineEntity(uuid4().hex, (5, 0), (8, 0))
    source = LineEntity(uuid4().hex, (0, 5), (2, 5))
    target = LineEntity(uuid4().hex, (5, 5), (7, 5))
    sketch = Sketch(
        identity, WorkPlaneFrame.xy(), (upstream_source, upstream_member, source, target)
    )
    refs = tuple(ArrayEntityRef(identity, entity.entity_id) for entity in sketch.entities)
    upstream, downstream = _array(refs[0], refs[1]), _array(refs[2], refs[3])
    changed, replaced = set_array_member_replacements(
        (sketch,),
        (downstream, upstream),
        downstream.array_id,
        {refs[3]: ArrayReplacement(refs[1])},
    )
    assert isinstance(changed[0].entities[3], LineEntity)
    assert changed[0].entities[3].end_mm == (8, 5)
    updated_source = replace(upstream_source, end_mm=(4, 0))
    proposed = replace(changed[0], entities=(updated_source, *changed[0].entities[1:]))
    result = propagate_array_changes(changed, (proposed,), (replaced, upstream))
    assert isinstance(result[0].entities[3], LineEntity)
    assert result[0].entities[3].end_mm == (9, 5)


def test_replacement_from_later_member_tracks_source_change_and_spacing() -> None:
    from mycad.core.associative_array import (
        ArrayReplacement,
        set_array_member_replacements,
        update_array_spacing,
    )

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    changed, updated = set_array_member_replacements(
        (sketch,), (array,), array.array_id, {refs[1]: ArrayReplacement(refs[2])}
    )
    source = replace(lines[0], end_mm=(3, 0))
    proposed = replace(changed[0], entities=(source, *changed[0].entities[1:]))
    result = propagate_array_changes(changed, (proposed,), (updated,))
    assert all(isinstance(entity, LineEntity) for entity in result[0].entities)
    first, second = result[0].entities[1:]
    assert isinstance(first, LineEntity) and isinstance(second, LineEntity)
    assert first.end_mm == (8, 0) and second.end_mm == (13, 0)
    spaced, _ = update_array_spacing(result, (updated,), updated.array_id, 0, 8)
    assert isinstance(spaced[0].entities[1], LineEntity)
    assert spaced[0].entities[1].end_mm == (11, 0)


def test_same_array_replacement_follows_rotation_and_rejects_cycles_or_erasure() -> None:
    from mycad.core.associative_array import (
        ArrayReplacement,
        erase_array_members,
        set_array_member_replacements,
        set_array_member_rotations,
    )

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    changed, updated = set_array_member_replacements(
        (sketch,), (array,), array.array_id, {refs[1]: ArrayReplacement(refs[2])}
    )
    rotated, updated = set_array_member_rotations(
        changed, (updated,), array.array_id, {refs[2]: (90, (0, 0))}
    )
    member = rotated[0].entities[1]
    assert isinstance(member, LineEntity) and member.end_mm == pytest.approx((5, 2))
    with pytest.raises(ValueError, match="环"):
        set_array_member_replacements(
            rotated, (updated,), array.array_id, {refs[2]: ArrayReplacement(refs[1])}
        )
    with pytest.raises(ValueError, match="来源"):
        erase_array_members(rotated, (updated,), array.array_id, (refs[2],))


def test_resize_creates_new_members_in_dependency_order_with_stable_entity_order() -> None:
    from mycad.core.associative_array import ArrayReplacement, resize_array

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    first = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, first))
    refs = tuple(
        ArrayEntityRef(identity, item)
        for item in (source.entity_id, first.entity_id, uuid4().hex, uuid4().hex)
    )
    array = _array(refs[0], refs[1])
    resized = replace(
        array,
        columns=4,
        members=(
            array.members[0],
            ArrayMember(refs[0], refs[2], 0, 2, replacement=ArrayReplacement(refs[3])),
            ArrayMember(refs[0], refs[3], 0, 3, rotation_deg=90),
        ),
    )
    (result,) = resize_array((sketch,), (array,), resized)
    assert tuple(entity.entity_id for entity in result.entities) == tuple(
        ref.entity_id for ref in refs
    )
    second, third = result.entities[2:]
    assert isinstance(second, LineEntity) and isinstance(third, LineEntity)
    assert second.end_mm == pytest.approx((10, 2))
    assert third.end_mm == pytest.approx((15, 2))


def test_resize_rejects_removing_source_of_surviving_internal_replacement() -> None:
    from mycad.core.associative_array import (
        ArrayReplacement,
        resize_array,
        set_array_member_replacements,
    )

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    changed, updated = set_array_member_replacements(
        (sketch,), (array,), array.array_id, {refs[1]: ArrayReplacement(refs[2])}
    )
    reduced = replace(updated, columns=2, members=(updated.members[0],))
    with pytest.raises(ValueError, match="来源"):
        resize_array(changed, (updated,), reduced)
    assert changed[0].entities == sketch.entities


def test_replacement_base_offset_combines_with_member_rotation_and_position() -> None:
    from mycad.core.associative_array import (
        ArrayReplacement,
        set_array_member_offsets,
        set_array_member_replacements,
        set_array_member_rotations,
    )
    from mycad.core.sketch import CircleEntity

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    replacement = CircleEntity(uuid4().hex, (20, 4), 2)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target, replacement))
    ref, copy, other = tuple(ArrayEntityRef(identity, e.entity_id) for e in sketch.entities)
    array = _array(ref, copy)
    moved, array1 = set_array_member_offsets((sketch,), (array,), array.array_id, {copy: (2, 3)})
    rotated, array2 = set_array_member_rotations(
        moved, (array1,), array.array_id, {copy: (90, (0, 0))}
    )
    changed, _ = set_array_member_replacements(
        rotated, (array2,), array.array_id, {copy: ArrayReplacement(other, (1, 0))}
    )
    circle = changed[0].entities[1]
    assert isinstance(circle, CircleEntity)
    assert circle.center_mm == pytest.approx((7, 2))


def test_replacement_from_aligned_sketch_with_different_origin() -> None:
    from mycad.core.associative_array import ArrayReplacement, set_array_member_replacements
    from mycad.core.sketch import CircleEntity

    source_id, replacement_id = uuid4().hex, uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    circle = CircleEntity(uuid4().hex, (20, 4), 2)
    sketch = Sketch(source_id, WorkPlaneFrame.xy(), (source, target))
    frame = replace(WorkPlaneFrame.xy(), origin_mm=(100, 20, 0))
    other = Sketch(replacement_id, frame, (circle,))
    ref, copy = (
        ArrayEntityRef(source_id, source.entity_id),
        ArrayEntityRef(source_id, target.entity_id),
    )
    array = _array(ref, copy)
    changed, _ = set_array_member_replacements(
        (sketch, other),
        (array,),
        array.array_id,
        {copy: ArrayReplacement(ArrayEntityRef(replacement_id, circle.entity_id))},
    )
    member = changed[0].entities[1]
    assert isinstance(member, CircleEntity) and member.center_mm == (5, 0)


def test_replacement_cycle_and_locked_source_are_rejected() -> None:
    from mycad.core.associative_array import ArrayReplacement, set_array_member_replacements
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    replacement = LineEntity(uuid4().hex, (20, 0), (22, 0), layer_name="locked")
    layers = SketchLayerTable().add(SketchLayer("locked", locked=True))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target, replacement), layers=layers)
    ref, copy, other = tuple(ArrayEntityRef(identity, e.entity_id) for e in sketch.entities)
    array = _array(ref, copy)
    with pytest.raises(ValueError, match="替换来源"):
        set_array_member_replacements(
            (sketch,), (array,), array.array_id, {copy: ArrayReplacement(copy)}
        )
    with pytest.raises(ValueError, match="锁定"):
        set_array_member_replacements(
            (sketch,), (array,), array.array_id, {copy: ArrayReplacement(other)}
        )
    assert sketch.entities == (source, target, replacement)


def test_replacement_cycle_between_arrays_is_rejected_atomically() -> None:
    from mycad.core.associative_array import ArrayReplacement, set_array_member_replacements

    identity = uuid4().hex
    lines = (
        LineEntity(uuid4().hex, (0, 0), (2, 0)),
        LineEntity(uuid4().hex, (5, 0), (7, 0)),
        LineEntity(uuid4().hex, (0, 5), (2, 5)),
        LineEntity(uuid4().hex, (5, 5), (7, 5)),
    )
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    first, second = _array(refs[0], refs[1]), _array(refs[2], refs[3])
    changed, first_updated = set_array_member_replacements(
        (sketch,), (first, second), first.array_id, {refs[1]: ArrayReplacement(refs[3])}
    )
    with pytest.raises(ValueError, match="环"):
        set_array_member_replacements(
            changed, (first_updated, second), second.array_id, {refs[3]: ArrayReplacement(refs[1])}
        )
    assert second.members[0].replacement is None


def test_interleaved_array_dependencies_recompute_without_false_cycle() -> None:
    from mycad.core.associative_array import (
        ArrayReplacement,
        set_array_member_replacements,
        set_array_member_rotations,
        update_array_spacing,
    )

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, y), (x + 2, y)) for y in (0, 5) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    first = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    second = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[3],),
        (ArrayMember(refs[3], refs[4], 0, 1), ArrayMember(refs[3], refs[5], 0, 2)),
    )
    changed, first = set_array_member_replacements(
        (sketch,), (first, second), first.array_id, {refs[1]: ArrayReplacement(refs[4])}
    )
    changed, second = set_array_member_replacements(
        changed, (first, second), second.array_id, {refs[5]: ArrayReplacement(refs[2])}
    )
    changed, first = set_array_member_rotations(
        changed, (first, second), first.array_id, {refs[2]: (90, (0, 0))}
    )
    dependent = changed[0].entities[5]
    assert isinstance(dependent, LineEntity) and dependent.end_mm == pytest.approx((10, 7))
    result, first = update_array_spacing(changed, (first, second), first.array_id, 0, 8)
    moved = result[0].entities[2]
    assert isinstance(moved, LineEntity) and moved.start_mm == (16, 0)
    assert isinstance(result[0].entities[5], LineEntity)
    assert result[0].entities[5].end_mm == pytest.approx((10, 7))


def test_interleaved_arrays_recompute_bound_base_after_source_moves() -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayReplacement,
        resolve_array_base_point,
        set_array_member_replacements,
        update_array_spacing,
    )
    from mycad.core.sketch_constraints import SketchGeometryReference

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10, 10, 15))
    refs = tuple(ArrayEntityRef(identity, item.entity_id) for item in lines)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    upstream = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    downstream = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[1],),
        (ArrayMember(refs[1], refs[3], 0, 1), ArrayMember(refs[1], refs[4], 0, 2)),
        base_point=ArrayBasePoint(
            source=refs[1], reference=SketchGeometryReference(refs[1].entity_id, "start")
        ),
    )
    changed, upstream = set_array_member_replacements(
        (sketch,), (upstream, downstream), upstream.array_id, {refs[2]: ArrayReplacement(refs[4])}
    )
    result, upstream = update_array_spacing(
        changed, (upstream, downstream), upstream.array_id, 0, 8
    )
    assert resolve_array_base_point(downstream, result) == (8, 0)
    updated = result[0].entities
    assert isinstance(updated[3], LineEntity) and updated[3].start_mm == (13, 0)
    assert isinstance(updated[4], LineEntity) and updated[4].start_mm == (18, 0)
    assert isinstance(updated[2], LineEntity) and updated[2].start_mm == (16, 0)


def test_interleaved_dependency_constraint_conflict_is_atomic() -> None:
    from mycad.core.associative_array import (
        ArrayReplacement,
        set_array_member_replacements,
        set_array_member_rotations,
    )
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, y), (x + 2, y)) for y in (0, 5) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    first = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    second = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[3],),
        (ArrayMember(refs[3], refs[4], 0, 1), ArrayMember(refs[3], refs[5], 0, 2)),
    )
    changed, first = set_array_member_replacements(
        (sketch,), (first, second), first.array_id, {refs[1]: ArrayReplacement(refs[4])}
    )
    changed, second = set_array_member_replacements(
        changed, (first, second), second.array_id, {refs[5]: ArrayReplacement(refs[2])}
    )
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(refs[5].entity_id, "start"),)
    )
    constrained = (replace(changed[0], constraints=(constraint,)),)
    with pytest.raises(ValueError, match="约束"):
        set_array_member_rotations(
            constrained, (first, second), first.array_id, {refs[2]: (90, (0, 0))}
        )
    assert constrained[0].entities == changed[0].entities and first.members[1].rotation_deg == 0


def test_spacing_change_rejects_locked_replacement_source() -> None:
    from mycad.core.associative_array import (
        ArrayReplacement,
        set_array_member_replacements,
        update_array_spacing,
    )
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_layers import SketchLayer

    identity, other_id = uuid4().hex, uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    replacement = CircleEntity(uuid4().hex, (20, 0), 2)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target))
    other = Sketch(other_id, WorkPlaneFrame.xy(), (replacement,))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    changed, replaced = set_array_member_replacements(
        (sketch, other),
        (array,),
        array.array_id,
        {copy: ArrayReplacement(ArrayEntityRef(other_id, replacement.entity_id))},
    )
    locked = replace(changed[1], layers=changed[1].layers.replace(SketchLayer("0", locked=True)))
    with pytest.raises(ValueError, match="锁定"):
        update_array_spacing((changed[0], locked), (replaced,), array.array_id, 0, 8)


def test_replacement_rejects_locked_source_even_if_geometry_is_identical() -> None:
    from mycad.core.associative_array import ArrayReplacement, set_array_member_replacements
    from mycad.core.sketch_layers import SketchLayer

    identity, other_id = uuid4().hex, uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    replacement = LineEntity(uuid4().hex, (20, 0), (22, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target))
    other = Sketch(other_id, WorkPlaneFrame.xy(), (replacement,))
    other = replace(other, layers=other.layers.replace(SketchLayer("0", locked=True)))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    with pytest.raises(ValueError, match="锁定"):
        set_array_member_replacements(
            (sketch, other),
            (array,),
            array.array_id,
            {copy: ArrayReplacement(ArrayEntityRef(other_id, replacement.entity_id))},
        )


def test_reset_erased_replaced_member_restores_original_source() -> None:
    from mycad.core.associative_array import (
        ArrayReplacement,
        erase_array_members,
        reset_array_member_overrides,
        set_array_member_replacements,
    )
    from mycad.core.sketch import CircleEntity

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    replacement = CircleEntity(uuid4().hex, (20, 0), 2)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target, replacement))
    ref, copy, other = tuple(ArrayEntityRef(identity, e.entity_id) for e in sketch.entities)
    array = _array(ref, copy)
    changed, replaced = set_array_member_replacements(
        (sketch,), (array,), array.array_id, {copy: ArrayReplacement(other)}
    )
    erased, replaced = erase_array_members(changed, (replaced,), array.array_id, (copy,))
    restored, reset = reset_array_member_overrides(erased, (replaced,), array.array_id)
    assert restored == (sketch,) and reset == array


def test_erased_array_member_restores_current_source_and_identity() -> None:
    from mycad.core.associative_array import erase_array_members, reset_array_member_overrides

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    erased, changed = erase_array_members((sketch,), (array,), array.array_id, (refs[1],))
    assert erased[0].entities == (lines[0], lines[2])
    assert changed.members[0].erased_index == 1
    assert AssociativeRectArray.from_mapping(changed.to_mapping()) == changed
    source = replace(lines[0], end_mm=(3, 0))
    proposed = replace(erased[0], entities=(source, lines[2]))
    propagated = propagate_array_changes(erased, (proposed,), (changed,))
    restored, reset = reset_array_member_overrides(propagated, (changed,), changed.array_id)
    assert reset == array
    assert tuple(entity.entity_id for entity in restored[0].entities) == tuple(
        line.entity_id for line in lines
    )
    assert isinstance(restored[0].entities[1], LineEntity)
    assert restored[0].entities[1].end_mm == (8, 0)
    assert isinstance(restored[0].entities[2], LineEntity)
    assert restored[0].entities[2].end_mm == (13, 0)


def test_separately_erased_members_restore_original_order() -> None:
    from mycad.core.associative_array import erase_array_members, reset_array_member_overrides

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10, 15))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        4,
        0,
        5,
        (refs[0],),
        tuple(ArrayMember(refs[0], refs[i], 0, i) for i in range(1, 4)),
    )
    first, changed = erase_array_members((sketch,), (array,), array.array_id, (refs[1],))
    second, changed = erase_array_members(first, (changed,), array.array_id, (refs[2],))
    restored, _ = reset_array_member_overrides(second, (changed,), array.array_id)
    assert restored == (sketch,)


def test_erased_member_restores_relative_order_after_new_entity_insertion() -> None:
    from mycad.core.associative_array import erase_array_members, reset_array_member_overrides

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    other = LineEntity(uuid4().hex, (30, 0), (32, 0))
    inserted = LineEntity(uuid4().hex, (-10, 0), (-8, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target, other))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    erased, changed = erase_array_members((sketch,), (array,), array.array_id, (copy,))
    proposed = replace(erased[0], entities=(inserted, source, other))
    changed_sketch = propagate_array_changes(erased, (proposed,), (changed,))
    restored, _ = reset_array_member_overrides(changed_sketch, (changed,), array.array_id)
    assert restored[0].entities == (inserted, source, target, other)


def test_erased_member_rejects_reversed_neighbor_order() -> None:
    from mycad.core.associative_array import erase_array_members, reset_array_member_overrides

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    other = LineEntity(uuid4().hex, (30, 0), (32, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target, other))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    erased, changed = erase_array_members((sketch,), (array,), array.array_id, (copy,))
    proposed = replace(erased[0], entities=(other, source))
    changed_sketch = propagate_array_changes(erased, (proposed,), (changed,))
    with pytest.raises(ValueError, match="邻接顺序"):
        reset_array_member_overrides(changed_sketch, (changed,), array.array_id)


def test_erased_member_rejects_when_both_recorded_neighbors_are_missing() -> None:
    from mycad.core.associative_array import erase_array_members, reset_array_member_overrides

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    before = LineEntity(uuid4().hex, (20, 0), (22, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    after = LineEntity(uuid4().hex, (30, 0), (32, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, before, target, after))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    erased, changed = erase_array_members((sketch,), (array,), array.array_id, (copy,))
    proposed = replace(erased[0], entities=(source,))
    changed_sketch = propagate_array_changes(erased, (proposed,), (changed,))
    with pytest.raises(ValueError, match="邻接图元已缺失"):
        reset_array_member_overrides(changed_sketch, (changed,), array.array_id)


def test_erased_member_rejects_cyclic_neighbor_references() -> None:
    from mycad.core.associative_array import erase_array_members, reset_array_member_overrides

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    erased, changed = erase_array_members((sketch,), (array,), array.array_id, (refs[1], refs[2]))
    cyclic = replace(
        changed,
        members=(
            replace(changed.members[0], erased_neighbors=(refs[2].entity_id, None)),
            replace(changed.members[1], erased_neighbors=(refs[1].entity_id, None)),
        ),
    )
    with pytest.raises(ValueError, match="邻接关系存在环"):
        reset_array_member_overrides(erased, (cyclic,), array.array_id)


def test_legacy_erasure_uses_original_slot_without_neighbors() -> None:
    from mycad.core.associative_array import erase_array_members, reset_array_member_overrides

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    erased, changed = erase_array_members(
        (sketch,), (array,), array.array_id, (copy,), preserve_order=False
    )
    assert changed.members[0].erased_neighbors is None
    assert "erased_neighbors" not in changed.members[0].to_mapping()
    restored, _ = reset_array_member_overrides(erased, (changed,), array.array_id)
    assert restored == (sketch,)


def test_erased_members_of_different_arrays_restore_in_either_order() -> None:
    from mycad.core.associative_array import erase_array_members, reset_array_member_overrides

    identity = uuid4().hex
    lines = (
        LineEntity(uuid4().hex, (0, 0), (2, 0)),
        LineEntity(uuid4().hex, (5, 0), (7, 0)),
        LineEntity(uuid4().hex, (0, 3), (2, 3)),
        LineEntity(uuid4().hex, (5, 3), (7, 3)),
    )
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    first, second = _array(refs[0], refs[1]), _array(refs[2], refs[3])
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    left, first_erased = erase_array_members((sketch,), (first, second), first.array_id, (refs[1],))
    both, second_erased = erase_array_members(
        left, (first_erased, second), second.array_id, (refs[3],)
    )
    partial, second_reset = reset_array_member_overrides(
        both, (first_erased, second_erased), second.array_id
    )
    restored, first_reset = reset_array_member_overrides(
        partial, (first_erased, second_reset), first.array_id
    )
    assert restored == (sketch,) and first_reset == first and second_reset == second


def test_erasing_constrained_or_downstream_member_is_rejected() -> None:
    from mycad.core.associative_array import erase_array_members
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    array, downstream = _array(refs[0], refs[1]), _array(refs[1], refs[2])
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    with pytest.raises(ValueError, match="下游"):
        erase_array_members((sketch,), (array, downstream), array.array_id, (refs[1],))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(lines[1].entity_id, "start"),)
    )
    constrained = replace(sketch, constraints=(constraint,))
    with pytest.raises(ValueError, match="约束"):
        erase_array_members((constrained,), (array,), array.array_id, (refs[1],))
    assert sketch.entities == lines and array.members[0].erased_index is None


def test_erased_identity_cannot_be_reused_in_another_sketch() -> None:
    from mycad.core.associative_array import erase_array_members

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    erased, changed = erase_array_members((sketch,), (array,), array.array_id, (copy,))
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (target,))
    with pytest.raises(ValueError, match="身份被占用"):
        propagate_array_changes(erased, (*erased, other), (changed,))


def test_erased_member_cannot_gain_a_dangling_local_constraint() -> None:
    from mycad.core.associative_array import erase_array_members
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    erased, changed = erase_array_members((sketch,), (array,), array.array_id, (copy,))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(target.entity_id, "start"),)
    )
    proposed = replace(erased[0], constraints=(constraint,))
    with pytest.raises(ValueError, match="约束"):
        propagate_array_changes(erased, (proposed,), (changed,))


def test_erased_member_survives_spacing_and_resize_and_can_be_removed_by_resize() -> None:
    from mycad.core.associative_array import erase_array_members, resize_array, update_array_spacing

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    erased, changed = erase_array_members((sketch,), (array,), array.array_id, (refs[2],))
    spaced, changed = update_array_spacing(erased, (changed,), array.array_id, 0, 6)
    assert changed.members[1].erased_index == 2
    resized = replace(changed, columns=2, members=(changed.members[0],))
    result = resize_array(spaced, (changed,), resized)
    assert len(result[0].entities) == 2
    assert isinstance(result[0].entities[1], LineEntity)
    assert result[0].entities[1].start_mm == (6, 0)


def test_erased_member_restores_at_moved_array_position() -> None:
    from mycad.core.associative_array import (
        erase_array_members,
        move_associative_array,
        reset_array_member_overrides,
    )

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    erased, changed = erase_array_members((sketch,), (array,), array.array_id, (copy,))
    moved, changed = move_associative_array(erased, (changed,), array.array_id, (3, 2))
    restored, _ = reset_array_member_overrides(moved, (changed,), array.array_id)
    member = restored[0].entities[1]
    assert isinstance(member, LineEntity)
    assert member.start_mm == (8, 2) and member.end_mm == (10, 2)


def test_reset_erased_member_clears_its_position_and_rotation_overrides() -> None:
    from mycad.core.associative_array import (
        erase_array_members,
        reset_array_member_overrides,
        set_array_member_offsets,
        set_array_member_rotations,
    )

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    moved, array1 = set_array_member_offsets((sketch,), (array,), array.array_id, {copy: (2, 3)})
    rotated, array2 = set_array_member_rotations(
        moved, (array1,), array.array_id, {copy: (90, (1, 0))}
    )
    erased, array3 = erase_array_members(rotated, (array2,), array.array_id, (copy,))
    restored, result = reset_array_member_overrides(erased, (array3,), array.array_id)
    assert restored == (sketch,) and result == array


def test_rotated_member_roundtrips_and_regenerates_from_source() -> None:
    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (5, 2))
    source_ref = ArrayEntityRef(identity, source.entity_id)
    target_ref = ArrayEntityRef(identity, target.entity_id)
    member = ArrayMember(source_ref, target_ref, 0, 1, rotation_deg=90)
    array = AssociativeRectArray(
        uuid4().hex, WorkPlaneFrame.xy(), 1, 2, 0, 5, (source_ref,), (member,)
    )
    assert AssociativeRectArray.from_mapping(array.to_mapping()) == array
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target))
    changed_source = replace(source, start_mm=(1, 2), end_mm=(4, 2))
    proposed = replace(sketch, entities=(changed_source, target))
    (result,) = propagate_array_changes((sketch,), (proposed,), (array,))
    assert isinstance(result.entities[1], LineEntity)
    assert result.entities[1].start_mm == pytest.approx((6, 2))
    assert result.entities[1].end_mm == pytest.approx((6, 5))


def test_rotating_member_updates_downstream_and_resets() -> None:
    from mycad.core.associative_array import set_array_member_rotations

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    upstream, downstream = _array(refs[0], refs[1]), _array(refs[1], refs[2])
    changed, updated = set_array_member_rotations(
        (sketch,), (upstream, downstream), upstream.array_id, {refs[1]: (90, (1, 0))}
    )
    for entity, start, end in zip(
        changed[0].entities[1:], ((6, -1), (11, -1)), ((6, 1), (11, 1)), strict=True
    ):
        assert isinstance(entity, LineEntity)
        assert entity.start_mm == pytest.approx(start)
        assert entity.end_mm == pytest.approx(end)
    restored, original = set_array_member_rotations(
        changed, (updated, downstream), upstream.array_id, {refs[1]: (0, (0, 0))}
    )
    restored_first, restored_second = restored[0].entities[1:]
    assert isinstance(restored_first, LineEntity) and isinstance(restored_second, LineEntity)
    assert restored_first.start_mm == pytest.approx(lines[1].start_mm)
    assert restored_second.end_mm == pytest.approx(lines[2].end_mm)
    assert original == upstream


def test_member_rotation_anchor_uses_target_frame_grid_and_offset() -> None:
    from mycad.core.associative_array import array_member_rotation_anchor

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (3, 4), (5, 4))
    target = LineEntity(uuid4().hex, (10, 7), (12, 7))
    source_ref = ArrayEntityRef(identity, source.entity_id)
    target_ref = ArrayEntityRef(identity, target.entity_id)
    member = ArrayMember(source_ref, target_ref, 0, 1, offset_mm=(2, 3))
    array = AssociativeRectArray(
        uuid4().hex, WorkPlaneFrame.xy(), 1, 2, 0, 5, (source_ref,), (member,)
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target))
    assert array_member_rotation_anchor(array, member, (sketch,)) == pytest.approx((10, 7))


def test_member_rotation_anchor_converts_between_parallel_sketch_frames() -> None:
    from mycad.core.associative_array import array_member_rotation_anchor

    source_id, target_id = uuid4().hex, uuid4().hex
    source = LineEntity(uuid4().hex, (3, 4), (5, 4))
    target = LineEntity(uuid4().hex, (20, 7), (22, 7))
    source_ref = ArrayEntityRef(source_id, source.entity_id)
    target_ref = ArrayEntityRef(target_id, target.entity_id)
    member = ArrayMember(source_ref, target_ref, 0, 1, offset_mm=(2, 3))
    array = AssociativeRectArray(
        uuid4().hex, WorkPlaneFrame.xy(), 1, 2, 0, 5, (source_ref,), (member,)
    )
    source_frame = replace(WorkPlaneFrame.xy(), origin_mm=(100, 10, 0))
    target_frame = replace(WorkPlaneFrame.xy(), origin_mm=(90, 10, 0))
    sketches = (
        Sketch(source_id, source_frame, (source,)),
        Sketch(target_id, target_frame, (target,)),
    )
    assert array_member_rotation_anchor(array, member, sketches) == pytest.approx((20, 7))


def test_reset_rotated_array_preserves_unrelated_translated_dimension() -> None:
    from mycad.core.associative_array import (
        reset_array_member_overrides,
        set_array_member_offsets,
        set_array_member_rotations,
    )
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(lines[1].entity_id, "geometry"),),
        2.0,
        "mm",
        position_mm=(6, 2),
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines, (dimension,))
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    moved, with_offset = set_array_member_offsets(
        (sketch,), (array,), array.array_id, {refs[1]: (2, 3)}
    )
    rotated, with_rotation = set_array_member_rotations(
        moved, (with_offset,), array.array_id, {refs[2]: (90, (0, 0))}
    )
    restored, updated = reset_array_member_overrides(rotated, (with_rotation,), array.array_id)
    assert restored == (sketch,) and updated == array


def test_rotation_rejects_constrained_member_without_changing_array() -> None:
    from mycad.core.associative_array import set_array_member_rotations
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(target.entity_id, "start"),)
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target), (constraint,))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    with pytest.raises(ValueError, match="约束"):
        set_array_member_rotations((sketch,), (array,), array.array_id, {copy: (90, (0, 0))})
    assert sketch.entities == (source, target) and array.members[0].rotation_deg == 0


def test_move_array_with_rotated_member_preserves_relative_rotation() -> None:
    from mycad.core.associative_array import move_associative_array, set_array_member_rotations

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    rotated, changed = set_array_member_rotations(
        (sketch,), (array,), array.array_id, {copy: (90, (1, 0))}
    )
    moved, moved_array = move_associative_array(rotated, (changed,), changed.array_id, (3, 2))
    member = moved[0].entities[1]
    assert isinstance(member, LineEntity)
    assert member.start_mm == pytest.approx((9, 1))
    assert member.end_mm == pytest.approx((9, 3))
    assert moved_array == changed


def test_member_rotation_transforms_arc_center_and_angle() -> None:
    from mycad.core.associative_array import set_array_member_rotations
    from mycad.core.sketch import ArcEntity

    identity = uuid4().hex
    source = ArcEntity(uuid4().hex, (0, 0), 2, 0, 90)
    target = replace(source, entity_id=uuid4().hex, center_mm=(5, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    changed, _ = set_array_member_rotations(
        (sketch,), (array,), array.array_id, {copy: (90, (1, 0))}
    )
    result = changed[0].entities[1]
    assert isinstance(result, ArcEntity)
    assert result.entity_id == target.entity_id and result.center_mm == pytest.approx((6, -1))
    assert result.radius_mm == 2 and result.start_angle_deg == 90 and result.sweep_angle_deg == 90


@pytest.mark.parametrize("angle", [float("nan"), float("inf"), True])
def test_member_rotation_rejects_nonfinite_or_boolean_angle(angle: object) -> None:
    data = _array().members[0].to_mapping()
    data["rotation_deg"] = angle
    with pytest.raises(ValueError):
        ArrayMember.from_mapping(data)


@pytest.mark.parametrize("angle", [0.0, 37.0, 90.0, -90.0])
@pytest.mark.parametrize("axis", ["row", "column"])
def test_array_spacing_grip_projection_preserves_signed_spacing(angle: float, axis: str) -> None:
    import math

    from mycad.core.associative_array import array_spacing_from_grip, array_spacing_grip

    source = _ref()
    members = tuple(
        ArrayMember(source, _ref(), row, column)
        for row in range(3)
        for column in range(2)
        if row or column
    )
    array = AssociativeRectArray(
        uuid4().hex, WorkPlaneFrame.xy(), 3, 2, -4, 5, (source,), members, angle
    )
    anchor = (123.5, -27.25)
    point = array_spacing_grip(array, anchor, axis)
    expected = array.row_spacing if axis == "row" else array.column_spacing
    assert array_spacing_from_grip(array, anchor, axis, point) == pytest.approx(expected)
    radians = math.radians(angle)
    perpendicular = (
        (math.cos(radians), math.sin(radians))
        if axis == "row"
        else (-math.sin(radians), math.cos(radians))
    )
    off_axis = (point[0] + 13 * perpendicular[0], point[1] + 13 * perpendicular[1])
    assert array_spacing_from_grip(array, anchor, axis, off_axis) == pytest.approx(expected)
    reflected = (2 * anchor[0] - point[0], 2 * anchor[1] - point[1])
    assert array_spacing_from_grip(array, anchor, axis, reflected) == pytest.approx(-expected)


def test_array_spacing_grips_reject_inactive_axis_and_degenerate_drag() -> None:
    from mycad.core.associative_array import array_spacing_from_grip, array_spacing_grip

    array = _array()
    with pytest.raises(ValueError, match="行"):
        array_spacing_grip(array, (0, 0), "row")
    with pytest.raises(ValueError, match="非零"):
        array_spacing_from_grip(array, (0, 0), "column", (0, 5))
    with pytest.raises(ValueError):
        array_spacing_from_grip(array, (0, 0), "column", (float("inf"), 0))
    with pytest.raises(ValueError):
        array_spacing_grip(array, (0, 0), "invalid")
    with pytest.raises(ValueError):
        array_spacing_grip(array, (float("nan"), 0), "column")


@pytest.mark.parametrize("angle", [0.0, 37.0, 90.0, -90.0])
def test_array_count_grip_projects_both_signed_axes(angle: float) -> None:
    from mycad.core.associative_array import array_counts_from_grip
    from mycad.core.sketch_edit import rectangular_array_displacement

    source = _ref()
    members = tuple(
        ArrayMember(source, _ref(), row, column)
        for row in range(2)
        for column in range(2)
        if row or column
    )
    array = AssociativeRectArray(
        uuid4().hex, WorkPlaneFrame.xy(), 2, 2, -4, 5, (source,), members, angle
    )
    anchor = (12.0, 23.0)
    shift = rectangular_array_displacement(3, 2, -4, 5, angle)
    point = (anchor[0] + shift[0], anchor[1] + shift[1])
    assert array_counts_from_grip(array, anchor, point) == (4, 3, -4, 5)


def test_array_count_grip_enables_missing_axis_and_rejects_limits() -> None:
    from mycad.core.associative_array import array_counts_from_grip

    array = _array()
    assert array_counts_from_grip(array, (0, 0), (10, 5)) == (2, 3, 5, 5)
    with pytest.raises(ValueError, match="位置"):
        array_counts_from_grip(array, (0, 0), (0, 0))
    with pytest.raises(ValueError, match="1000"):
        array_counts_from_grip(array, (0, 0), (5000, 5000))
    with pytest.raises(ValueError):
        array_counts_from_grip(array, (0, 0), (float("inf"), 0))


def test_array_count_grip_checks_member_cap_and_half_step() -> None:
    from mycad.core.associative_array import array_counts_from_grip

    sources = tuple(_ref() for _ in range(11))
    members = tuple(ArrayMember(source, _ref(), 0, 1) for source in sources)
    array = AssociativeRectArray(uuid4().hex, WorkPlaneFrame.xy(), 1, 2, 0, 5, sources, members)
    assert array_counts_from_grip(array, (0, 0), (7.5, 0)) == (1, 3, 0, 5)
    with pytest.raises(ValueError, match="10000"):
        array_counts_from_grip(array, (0, 0), (4995, 0))


def test_array_relation_roundtrips_and_has_stable_member_references() -> None:
    array = _array()
    assert AssociativeRectArray.from_mapping(array.to_mapping()) == array
    assert array.members[0].source == array.sources[0]
    assert array.members[0].target != array.sources[0]


def test_array_member_offset_roundtrip_and_source_propagation() -> None:
    from mycad.core.associative_array import resize_array, update_array_spacing

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = replace(source, entity_id=uuid4().hex, start_mm=(8, -2), end_mm=(10, -2))
    downstream_target = replace(source, entity_id=uuid4().hex, start_mm=(13, -2), end_mm=(15, -2))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target, downstream_target))
    origin, copy, final = (ArrayEntityRef(identity, entity.entity_id) for entity in sketch.entities)
    upstream = _array(origin, copy)
    member = replace(upstream.members[0], offset_mm=(3, -2))
    upstream = replace(upstream, members=(member,))
    downstream = _array(copy, final)
    assert "offset_mm" not in _array().members[0].to_mapping()
    assert AssociativeRectArray.from_mapping(upstream.to_mapping()) == upstream
    edited = replace(source, end_mm=(3, 1))
    proposed = replace(sketch, entities=(edited, target, downstream_target))
    result = propagate_array_changes((sketch,), (proposed,), (upstream, downstream))
    assert result[0].entities[1] == replace(target, end_mm=(11, -1))
    assert result[0].entities[2] == replace(downstream_target, end_mm=(16, -1))
    spaced, changed = update_array_spacing(
        (sketch,), (upstream, downstream), upstream.array_id, 0, 7
    )
    assert changed.members[0].offset_mm == (3, -2)
    assert isinstance(spaced[0].entities[1], LineEntity)
    assert spaced[0].entities[1].start_mm == (10, -2)
    new_ref = ArrayEntityRef(identity, uuid4().hex)
    resized = replace(
        changed, columns=3, members=(*changed.members, ArrayMember(origin, new_ref, 0, 2))
    )
    result = resize_array(spaced, (changed, downstream), resized)
    assert result[0].entities[1] == spaced[0].entities[1]
    tampered = replace(
        resized, members=(replace(resized.members[0], offset_mm=(0, 0)), resized.members[1])
    )
    with pytest.raises(ValueError, match="覆盖"):
        resize_array(spaced, (changed, downstream), tampered)


def test_array_member_offset_update_and_reset_propagate_downstream() -> None:
    from mycad.core.associative_array import set_array_member_offsets

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(identity, item.entity_id) for item in lines)
    upstream, downstream = _array(refs[0], refs[1]), _array(refs[1], refs[2])
    changed, array = set_array_member_offsets(
        (sketch,), (upstream, downstream), upstream.array_id, {refs[1]: (2, 3)}
    )
    assert array.members[0].offset_mm == (2, 3)
    assert changed[0].entities == (
        lines[0],
        replace(lines[1], start_mm=(7, 3), end_mm=(9, 3)),
        replace(lines[2], start_mm=(12, 3), end_mm=(14, 3)),
    )
    reset, restored = set_array_member_offsets(
        changed, (array, downstream), array.array_id, {}, reset_all=True
    )
    assert reset == (sketch,) and restored == upstream
    with pytest.raises(ValueError, match="未变化"):
        set_array_member_offsets(
            (sketch,), (upstream, downstream), upstream.array_id, {}, reset_all=True
        )
    with pytest.raises(ValueError):
        set_array_member_offsets(
            (sketch,), (upstream, downstream), upstream.array_id, {refs[0]: (1, 0)}
        )


def test_array_member_offset_rejects_constrained_member_without_changes() -> None:
    from mycad.core.associative_array import set_array_member_offsets
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = replace(source, entity_id=uuid4().hex, start_mm=(5, 0), end_mm=(7, 0))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(target.entity_id, "start"),)
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target), (constraint,))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    with pytest.raises(ValueError, match="约束"):
        set_array_member_offsets((sketch,), (array,), array.array_id, {copy: (1, 2)})
    assert sketch.entities == (source, target) and array.members[0].offset_mm == (0, 0)


def test_cross_array_offsets_preserve_shared_dimension_atomically() -> None:
    from mycad.core.associative_array import set_array_offsets_batch
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, item.entity_id) for item in lines)
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        tuple(SketchGeometryReference(line.entity_id, "start") for line in lines[1:]),
        5,
        "mm",
        position_mm=(7, 2),
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines, (dimension,))
    first = _array(refs[0], refs[1])
    second = replace(_array(refs[0], refs[2]), column_spacing=10)
    changed, arrays = set_array_offsets_batch(
        (sketch,),
        (first, second),
        {first.array_id: {refs[1]: (2, 3)}, second.array_id: {refs[2]: (2, 3)}},
    )
    assert changed[0].constraints[0].position_mm == (9, 5)
    assert isinstance(changed[0].entities[1], LineEntity)
    assert isinstance(changed[0].entities[2], LineEntity)
    assert changed[0].entities[1].start_mm == (7, 3)
    assert changed[0].entities[2].start_mm == (12, 3)
    assert arrays[0].members[0].offset_mm == arrays[1].members[0].offset_mm == (2, 3)
    with pytest.raises(ValueError, match="约束"):
        set_array_offsets_batch(
            (sketch,),
            (first, second),
            {first.array_id: {refs[1]: (2, 3)}, second.array_id: {refs[2]: (1, 3)}},
        )
    assert sketch.entities == lines and first.members[0].offset_mm == (0, 0)


def test_cross_array_rotations_update_both_networks() -> None:
    from mycad.core.associative_array import set_array_rotations_batch

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, item.entity_id) for item in lines)
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    first, second = _array(refs[0], refs[1]), replace(_array(refs[0], refs[2]), column_spacing=10)
    changed, arrays = set_array_rotations_batch(
        (sketch,),
        (first, second),
        {first.array_id: {refs[1]: (90, (0, 0))}, second.array_id: {refs[2]: (90, (0, 0))}},
    )
    assert arrays[0].members[0].rotation_deg == arrays[1].members[0].rotation_deg == 90
    assert isinstance(changed[0].entities[1], LineEntity)
    assert isinstance(changed[0].entities[2], LineEntity)
    assert changed[0].entities[1].end_mm == pytest.approx((5, 2))
    assert changed[0].entities[2].end_mm == pytest.approx((10, 2))


def test_array_member_offset_moves_length_dimension_and_resets() -> None:
    from mycad.core.associative_array import set_array_member_offsets
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = replace(source, entity_id=uuid4().hex, start_mm=(5, 0), end_mm=(7, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(target.entity_id, "geometry"),),
        2.0,
        "mm",
        position_mm=(6, 2),
        text_position_mm=(6, 3),
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target), (dimension,))
    ref, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = _array(ref, copy)
    moved, changed = set_array_member_offsets((sketch,), (array,), array.array_id, {copy: (2, 3)})
    assert moved[0].constraints[0].position_mm == (8, 5)
    assert moved[0].constraints[0].text_position_mm == (8, 6)
    assert moved[0].constraints[0].value == 2
    restored, _updated = set_array_member_offsets(
        moved, (changed,), array.array_id, {}, reset_all=True
    )
    assert restored == (sketch,)


def test_array_member_offsets_preserve_shared_distance_only_when_moved_together() -> None:
    from mycad.core.associative_array import set_array_member_offsets
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        tuple(SketchGeometryReference(line.entity_id, "start") for line in lines[1:]),
        5.0,
        "mm",
        position_mm=(7, 2),
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines, (dimension,))
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    moved, updated = set_array_member_offsets(
        (sketch,), (array,), array.array_id, {refs[1]: (2, 3), refs[2]: (2, 3)}
    )
    assert moved[0].constraints[0].position_mm == (9, 5)
    restored, _ = set_array_member_offsets(moved, (updated,), array.array_id, {}, reset_all=True)
    assert restored == (sketch,)
    with pytest.raises(ValueError, match="约束"):
        set_array_member_offsets((sketch,), (array,), array.array_id, {refs[1]: (2, 3)})


def test_reset_different_offsets_moves_each_dimension_independently() -> None:
    from mycad.core.associative_array import set_array_member_offsets
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    dimensions = tuple(
        SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(line.entity_id, "geometry"),),
            2.0,
            "mm",
            position_mm=(line.start_mm[0], 2),
        )
        for line in lines[1:]
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines, dimensions)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    moved, changed = set_array_member_offsets(
        (sketch,), (array,), array.array_id, {refs[1]: (2, 3), refs[2]: (-1, 4)}
    )
    assert tuple(c.position_mm for c in moved[0].constraints) == ((7, 5), (9, 6))
    restored, _ = set_array_member_offsets(moved, (changed,), array.array_id, {}, reset_all=True)
    assert restored == (sketch,)


def test_offset_propagates_translation_to_downstream_dimension() -> None:
    from mycad.core.associative_array import set_array_member_offsets
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(lines[2].entity_id, "geometry"),),
        2.0,
        "mm",
        position_mm=(11, 2),
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines, (dimension,))
    upstream, downstream = _array(refs[0], refs[1]), _array(refs[1], refs[2])
    moved, updated = set_array_member_offsets(
        (sketch,), (upstream, downstream), upstream.array_id, {refs[1]: (2, 3)}
    )
    assert moved[0].constraints[0].position_mm == (13, 5)
    restored, _ = set_array_member_offsets(
        moved, (updated, downstream), upstream.array_id, {}, reset_all=True
    )
    assert restored == (sketch,)


@pytest.mark.parametrize(("locked", "visible"), [(True, True), (False, False)])
def test_offset_rejects_dimension_on_unavailable_layer(locked: bool, visible: bool) -> None:
    from mycad.core.associative_array import set_array_member_offsets
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = replace(source, entity_id=uuid4().hex, start_mm=(5, 0), end_mm=(7, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(target.entity_id, "geometry"),),
        2.0,
        "mm",
        position_mm=(6, 2),
        layer_name="dimensions",
    )
    layers = SketchLayerTable().add(SketchLayer("dimensions", locked=locked, visible=visible))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target), (dimension,), layers=layers)
    origin = ArrayEntityRef(identity, source.entity_id)
    copy = ArrayEntityRef(identity, target.entity_id)
    array = _array(origin, copy)
    with pytest.raises(ValueError, match="尺寸图层"):
        set_array_member_offsets((sketch,), (array,), array.array_id, {copy: (2, 3)})
    assert sketch.constraints == (dimension,) and array.members[0].offset_mm == (0, 0)


def test_rotating_array_preserves_member_offset_in_workplane() -> None:
    from mycad.core.associative_array import update_array_spacing

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = replace(source, entity_id=uuid4().hex, start_mm=(3, 3), end_mm=(5, 3))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target))
    origin, copy = (
        ArrayEntityRef(identity, source.entity_id),
        ArrayEntityRef(identity, target.entity_id),
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (origin,),
        (ArrayMember(origin, copy, 0, 1, (3, -2)),),
        90,
    )
    result, updated = update_array_spacing((sketch,), (array,), array.array_id, 0, 5, angle_deg=0)
    assert updated.members[0].offset_mm == (3, -2)
    assert isinstance(result[0].entities[1], LineEntity)
    assert result[0].entities[1].start_mm == pytest.approx((8, -2))


@pytest.mark.parametrize("offset", [(float("nan"), 0), (float("inf"), 0), (True, 0)])
def test_array_member_offset_rejects_nonfinite_values(offset: tuple[object, object]) -> None:
    data = _array().members[0].to_mapping()
    with pytest.raises(ValueError):
        ArrayMember.from_mapping({**data, "offset_mm": list(offset)})


@pytest.mark.parametrize("base_kind", ["default", "fixed", "key"])
def test_move_array_moves_all_sources_members_and_downstream(base_kind: str) -> None:
    from mycad.core.associative_array import ArrayBasePoint, move_associative_array
    from mycad.core.sketch_constraints import SketchGeometryReference

    identity = uuid4().hex
    source_a = LineEntity(uuid4().hex, (0, 0), (2, 0))
    source_b = LineEntity(uuid4().hex, (0, 3), (2, 3))
    copy_a = replace(source_a, entity_id=uuid4().hex, start_mm=(5, 0), end_mm=(7, 0))
    copy_b = replace(source_b, entity_id=uuid4().hex, start_mm=(5, 3), end_mm=(7, 3))
    downstream_copy = replace(copy_a, entity_id=uuid4().hex, start_mm=(10, 0), end_mm=(12, 0))
    sketch = Sketch(
        identity, WorkPlaneFrame.xy(), (source_a, source_b, copy_a, copy_b, downstream_copy)
    )
    refs = tuple(ArrayEntityRef(identity, entity.entity_id) for entity in sketch.entities)
    base = (
        ArrayBasePoint(point_mm=(3, 4))
        if base_kind == "fixed"
        else ArrayBasePoint(
            source=refs[0], reference=SketchGeometryReference(refs[0].entity_id, "end")
        )
        if base_kind == "key"
        else None
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        refs[:2],
        (ArrayMember(refs[0], refs[2], 0, 1), ArrayMember(refs[1], refs[3], 0, 1)),
        base_point=base,
    )
    downstream = _array(refs[2], refs[4])
    updated, moved_array = move_associative_array(
        (sketch,), (array, downstream), array.array_id, (3, -2)
    )
    for old, new in zip(sketch.entities, updated[0].entities, strict=True):
        assert isinstance(old, LineEntity) and isinstance(new, LineEntity)
        assert new.entity_id == old.entity_id
        assert new.start_mm == pytest.approx((old.start_mm[0] + 3, old.start_mm[1] - 2))
    if base_kind == "fixed":
        assert moved_array.base_point == ArrayBasePoint(point_mm=(6, 2))
    else:
        assert moved_array.base_point == base
    assert sketch.entities == (source_a, source_b, copy_a, copy_b, downstream_copy)


def test_move_array_rejects_generated_source_and_zero_or_invalid_delta() -> None:
    from mycad.core.associative_array import move_associative_array

    identity = uuid4().hex
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = replace(first, entity_id=uuid4().hex, start_mm=(5, 0), end_mm=(7, 0))
    third = replace(first, entity_id=uuid4().hex, start_mm=(10, 0), end_mm=(12, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (first, second, third))
    refs = tuple(ArrayEntityRef(identity, entity.entity_id) for entity in sketch.entities)
    upstream, downstream = _array(refs[0], refs[1]), _array(refs[1], refs[2])
    with pytest.raises(ValueError, match="来源|源"):
        move_associative_array((sketch,), (upstream, downstream), downstream.array_id, (1, 0))
    for delta in ((0, 0), (float("nan"), 0)):
        with pytest.raises(ValueError):
            move_associative_array((sketch,), (upstream, downstream), upstream.array_id, delta)


def test_move_downstream_array_creates_upstream_member_offset_atomically() -> None:
    from mycad.core.associative_array import move_associative_array_with_offsets

    identity = uuid4().hex
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = replace(first, entity_id=uuid4().hex, start_mm=(5, 0), end_mm=(7, 0))
    third = replace(first, entity_id=uuid4().hex, start_mm=(10, 0), end_mm=(12, 0))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (first, second, third))
    refs = tuple(ArrayEntityRef(identity, entity.entity_id) for entity in sketch.entities)
    upstream, downstream = _array(refs[0], refs[1]), _array(refs[1], refs[2])
    moved, arrays = move_associative_array_with_offsets(
        (sketch,), (upstream, downstream), downstream.array_id, (2, 3)
    )
    assert moved[0].entities == (
        first,
        replace(second, start_mm=(7, 3), end_mm=(9, 3)),
        replace(third, start_mm=(12, 3), end_mm=(14, 3)),
    )
    assert arrays[0].members[0].offset_mm == (2, 3)
    assert arrays[1] == downstream
    moved_again, arrays_again = move_associative_array_with_offsets(
        moved, arrays, downstream.array_id, (-1, 1)
    )
    assert arrays_again[0].members[0].offset_mm == (1, 4)
    assert moved_again[0].entities[0] == first
    assert isinstance(moved_again[0].entities[2], LineEntity)
    assert moved_again[0].entities[2].start_mm == (11, 4)


def test_move_array_with_source_and_its_generated_descendant_moves_once() -> None:
    from mycad.core.associative_array import move_associative_array_with_offsets

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10, 15))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(identity, entity.entity_id) for entity in lines)
    upstream = _array(refs[0], refs[1])
    downstream = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        10,
        refs[:2],
        (ArrayMember(refs[0], refs[2], 0, 1), ArrayMember(refs[1], refs[3], 0, 1)),
    )
    result, arrays = move_associative_array_with_offsets(
        (sketch,), (upstream, downstream), downstream.array_id, (2, 3)
    )
    assert arrays[0].members[0].offset_mm == (0, 0)
    for before, after in zip(lines, result[0].entities, strict=True):
        assert isinstance(after, LineEntity)
        assert after.start_mm == (before.start_mm[0] + 2, before.start_mm[1] + 3)


def test_move_array_polyline_key_point_survives_translation_matching_another_vertex() -> None:
    from mycad.core.associative_array import ArrayBasePoint, move_associative_array
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    identity = uuid4().hex
    source = PolylineEntity(uuid4().hex, ((0, 0), (5, 0), (10, 0)))
    target = replace(source, entity_id=uuid4().hex, points_mm=((0, 5), (5, 5), (10, 5)))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(identity, source.entity_id)
    copy = ArrayEntityRef(identity, target.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        5,
        0,
        (origin,),
        (ArrayMember(origin, copy, 1, 0),),
        base_point=ArrayBasePoint(
            source=origin, reference=SketchGeometryReference(origin.entity_id, "vertex", 1)
        ),
    )
    moved, updated = move_associative_array((sketch,), (array,), array.array_id, (5, 0))
    assert isinstance(moved[0].entities[0], PolylineEntity)
    assert moved[0].entities[0].points_mm == ((5, 0), (10, 0), (15, 0))
    assert updated.base_point == array.base_point


@pytest.mark.parametrize("locked", [False, True])
def test_move_array_rejects_constrained_or_locked_sources(locked: bool) -> None:
    from mycad.core.associative_array import move_associative_array
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    identity = uuid4().hex
    first = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="L")
    second = replace(first, entity_id=uuid4().hex, start_mm=(5, 0), end_mm=(7, 0))
    constraints = (
        ()
        if locked
        else (
            SketchConstraint(
                uuid4().hex,
                "fixed",
                (SketchGeometryReference(first.entity_id, "start"),),
            ),
        )
    )
    layers = SketchLayerTable().add(SketchLayer("L", locked=locked))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (first, second), constraints, layers)
    array = _array(
        ArrayEntityRef(identity, first.entity_id), ArrayEntityRef(identity, second.entity_id)
    )
    with pytest.raises(ValueError, match="锁定|约束"):
        move_associative_array((sketch,), (array,), array.array_id, (2, 0))
    assert sketch.entities == (first, second)


def test_move_array_preserves_translated_source_and_member_dimensions() -> None:
    from mycad.core.associative_array import move_associative_array
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = replace(first, entity_id=uuid4().hex, start_mm=(5, 0), end_mm=(7, 0))
    dimensions = tuple(
        SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(entity.entity_id, "geometry"),),
            2.0,
            "mm",
            position_mm=(0, 3),
            text_position_mm=(1, 4),
        )
        for entity in (first, second)
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (first, second), dimensions)
    array = _array(
        ArrayEntityRef(identity, first.entity_id), ArrayEntityRef(identity, second.entity_id)
    )
    moved, _updated = move_associative_array((sketch,), (array,), array.array_id, (3, 2))
    assert all(constraint.position_mm == (3, 5) for constraint in moved[0].constraints)
    assert all(constraint.text_position_mm == (4, 6) for constraint in moved[0].constraints)
    assert all(constraint.value == 2 for constraint in moved[0].constraints)
    assert sketch.constraints == dimensions


def test_move_array_rejects_partial_distance_constraint() -> None:
    from mycad.core.associative_array import move_associative_array
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = replace(source, entity_id=uuid4().hex, start_mm=(5, 0), end_mm=(7, 0))
    other = LineEntity(uuid4().hex, (0, 4), (2, 4))
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(source.entity_id, "start"),
            SketchGeometryReference(other.entity_id, "start"),
        ),
        4.0,
        "mm",
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target, other), (dimension,))
    array = _array(
        ArrayEntityRef(identity, source.entity_id), ArrayEntityRef(identity, target.entity_id)
    )
    with pytest.raises(ValueError, match="约束"):
        move_associative_array((sketch,), (array,), array.array_id, (0, 1))


def test_move_array_preserves_partial_parallel_relation_and_respects_dimension_layer() -> None:
    from mycad.core.associative_array import move_associative_array
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    identity = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = replace(source, entity_id=uuid4().hex, start_mm=(5, 0), end_mm=(7, 0))
    other = LineEntity(uuid4().hex, (0, 4), (2, 4))
    relation = SketchConstraint(
        uuid4().hex,
        "parallel",
        (
            SketchGeometryReference(source.entity_id, "geometry"),
            SketchGeometryReference(other.entity_id, "geometry"),
        ),
    )
    array = _array(
        ArrayEntityRef(identity, source.entity_id), ArrayEntityRef(identity, target.entity_id)
    )
    sketch = Sketch(identity, WorkPlaneFrame.xy(), (source, target, other), (relation,))
    moved, _updated = move_associative_array((sketch,), (array,), array.array_id, (0, 1))
    assert moved[0].constraints == (relation,) and moved[0].entities[2] == other
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(source.entity_id, "geometry"),),
        2.0,
        "mm",
        position_mm=(1, 2),
        layer_name="locked-dim",
    )
    layers = SketchLayerTable().add(SketchLayer("locked-dim", locked=True))
    constrained = replace(sketch, constraints=(dimension,), layers=layers)
    with pytest.raises(ValueError, match="尺寸图层"):
        move_associative_array((constrained,), (array,), array.array_id, (0, 1))


def test_array_angle_roundtrip_and_old_record_defaults_to_zero() -> None:
    old = _array()
    assert "angle_deg" not in old.to_mapping()
    assert AssociativeRectArray.from_mapping(old.to_mapping()).angle_deg == 0
    rotated = replace(old, angle_deg=-45)
    assert rotated.to_mapping()["angle_deg"] == -45
    assert AssociativeRectArray.from_mapping(rotated.to_mapping()) == rotated


def test_array_base_point_roundtrip_and_validation() -> None:
    from mycad.core.associative_array import ArrayBasePoint
    from mycad.core.sketch_constraints import SketchGeometryReference

    old = _array()
    assert "base_point" not in old.to_mapping()
    fixed = replace(old, base_point=ArrayBasePoint(point_mm=(3.5, -2)))
    assert AssociativeRectArray.from_mapping(fixed.to_mapping()) == fixed
    source = old.sources[0]
    key = ArrayBasePoint(source=source, reference=SketchGeometryReference(source.entity_id, "end"))
    linked = replace(old, base_point=key)
    assert AssociativeRectArray.from_mapping(linked.to_mapping()) == linked
    with pytest.raises(ValueError):
        replace(old, base_point=ArrayBasePoint(source=_ref(), reference=key.reference))
    with pytest.raises(ValueError):
        ArrayBasePoint(point_mm=(float("nan"), 0))
    with pytest.raises(ValueError):
        ArrayBasePoint(point_mm=(0, 0), source=source, reference=key.reference)


def test_array_key_point_tracks_source_across_shifted_xz_frames() -> None:
    from mycad.core.associative_array import ArrayBasePoint, resolve_array_base_point
    from mycad.core.sketch_constraints import SketchGeometryReference

    source_frame = replace(WorkPlaneFrame.xz(), origin_mm=(10, 0, 20))
    source = LineEntity(uuid4().hex, (1, 2), (3, 4))
    sketch = Sketch(uuid4().hex, source_frame, (source,))
    ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    array = _array(ref)
    array = replace(
        array,
        frame=WorkPlaneFrame.xz(),
        base_point=ArrayBasePoint(
            source=ref, reference=SketchGeometryReference(ref.entity_id, "end")
        ),
    )
    assert resolve_array_base_point(array, (sketch,)) == pytest.approx((13, -16))
    changed = replace(sketch, entities=(replace(source, end_mm=(5, 6)),))
    assert resolve_array_base_point(array, (changed,)) == pytest.approx((15, -14))
    assert resolve_array_base_point(
        replace(array, base_point=ArrayBasePoint(point_mm=(9, 8))), (changed,)
    ) == (9, 8)
    with pytest.raises(ValueError, match="基点"):
        resolve_array_base_point(array, (replace(sketch, entities=()),))


def test_array_key_point_rejects_invalidated_source_reference() -> None:
    from mycad.core.associative_array import ArrayBasePoint
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    source = PolylineEntity(uuid4().hex, ((0, 0), (1, 1), (2, 0)))
    target = replace(source, entity_id=uuid4().hex, points_mm=((5, 0), (6, 1), (7, 0)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    array = replace(
        _array(ref, ArrayEntityRef(sketch.sketch_id, target.entity_id)),
        base_point=ArrayBasePoint(
            source=ref, reference=SketchGeometryReference(ref.entity_id, "vertex", 2)
        ),
    )
    proposed = replace(sketch, entities=(replace(source, points_mm=((0, 0), (1, 1))), target))
    with pytest.raises(ValueError, match="基点"):
        propagate_array_changes((sketch,), (proposed,), (array,))


def test_array_key_point_rejects_reordered_polyline_vertex() -> None:
    from mycad.core.associative_array import ArrayBasePoint
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    source = PolylineEntity(uuid4().hex, ((0, 0), (1, 1), (2, 0)), closed=True)
    target = replace(source, entity_id=uuid4().hex, points_mm=((5, 0), (6, 1), (7, 0)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    array = replace(
        _array(ref, ArrayEntityRef(sketch.sketch_id, target.entity_id)),
        base_point=ArrayBasePoint(
            source=ref, reference=SketchGeometryReference(ref.entity_id, "vertex", 0)
        ),
    )
    rotated = replace(source, points_mm=((1, 1), (2, 0), (0, 0)))
    proposed = replace(sketch, entities=(rotated, target))
    with pytest.raises(ValueError, match="基点"):
        propagate_array_changes((sketch,), (proposed,), (array,))


def test_array_key_point_rejects_open_polyline_reordering() -> None:
    from mycad.core.associative_array import ArrayBasePoint
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    source = PolylineEntity(uuid4().hex, ((0, 0), (1, 1), (2, 0)))
    target = replace(source, entity_id=uuid4().hex, points_mm=((5, 0), (6, 1), (7, 0)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target))
    ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    array = replace(
        _array(ref, ArrayEntityRef(sketch.sketch_id, target.entity_id)),
        base_point=ArrayBasePoint(
            source=ref, reference=SketchGeometryReference(ref.entity_id, "vertex", 0)
        ),
    )
    reversed_source = replace(source, points_mm=tuple(reversed(source.points_mm)))
    with pytest.raises(ValueError, match="基点"):
        propagate_array_changes(
            (sketch,), (replace(sketch, entities=(reversed_source, target)),), (array,)
        )


def test_array_key_point_rejects_topology_changed_through_upstream_array() -> None:
    from mycad.core.associative_array import ArrayBasePoint
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    first = PolylineEntity(uuid4().hex, ((0, 0), (1, 1), (2, 0)))
    second = replace(first, entity_id=uuid4().hex, points_mm=((5, 0), (6, 1), (7, 0)))
    third = replace(first, entity_id=uuid4().hex, points_mm=((10, 0), (11, 1), (12, 0)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second, third))
    refs = tuple(
        ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in (first, second, third)
    )
    upstream = _array(refs[0], refs[1])
    downstream = replace(
        _array(refs[1], refs[2]),
        base_point=ArrayBasePoint(
            source=refs[1], reference=SketchGeometryReference(refs[1].entity_id, "vertex", 2)
        ),
    )
    changed = replace(first, points_mm=((0, 0), (1, 1)))
    proposed = replace(sketch, entities=(changed, second, third))
    with pytest.raises(ValueError, match="基点"):
        propagate_array_changes((sketch,), (proposed,), (upstream, downstream))


@pytest.mark.parametrize("value", [True, float("inf"), float("nan"), 10**1000])
def test_array_rejects_invalid_angle(value: object) -> None:
    with pytest.raises(ValueError):
        AssociativeRectArray.from_mapping({**_array().to_mapping(), "angle_deg": value})


@pytest.mark.parametrize("angle", [-45.0, 45.0, 180.0])
def test_rotated_array_handles_rows_columns_and_multiple_sources(angle: float) -> None:
    import math

    sketch_id = uuid4().hex
    sources = (LineEntity(uuid4().hex, (1, 2), (3, 2)), LineEntity(uuid4().hex, (5, 1), (5, 4)))
    refs = tuple(ArrayEntityRef(sketch_id, item.entity_id) for item in sources)
    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    cells = ((0, 1), (1, 0), (1, 1))
    members: list[ArrayMember] = []
    copies: list[LineEntity] = []
    for source, ref in zip(sources, refs, strict=True):
        for row, column in cells:
            dx, dy = column * 3 * cosine + row * 4 * sine, column * 3 * sine - row * 4 * cosine
            copy = replace(
                source,
                entity_id=uuid4().hex,
                start_mm=(source.start_mm[0] + dx, source.start_mm[1] + dy),
                end_mm=(source.end_mm[0] + dx, source.end_mm[1] + dy),
            )
            copies.append(copy)
            members.append(ArrayMember(ref, ArrayEntityRef(sketch_id, copy.entity_id), row, column))
    sketch = Sketch(sketch_id, WorkPlaneFrame.xz(), (*sources, *copies))
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 2, -4, 3, refs, tuple(members), angle
    )
    assert propagate_array_changes((sketch,), (sketch,), (array,)) == (sketch,)
    edited = replace(sources[1], end_mm=(6, 4))
    changed = replace(sketch, entities=(sources[0], edited, *copies))
    result = propagate_array_changes((sketch,), (changed,), (array,))[0]
    for copy in result.entities[-3:]:
        assert isinstance(copy, LineEntity)
        assert copy.end_mm[0] - copy.start_mm[0] == pytest.approx(1)


def test_rotated_array_propagates_spacing_and_resize_without_changing_angle() -> None:
    from mycad.core.associative_array import resize_array, update_array_spacing

    sketch_id = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (0, 5), (2, 5))
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch_id, source.entity_id)
    existing = ArrayEntityRef(sketch_id, target.entity_id)
    array = replace(_array(origin, existing), angle_deg=90)
    edited = replace(source, end_mm=(3, 1))
    propagated = propagate_array_changes(
        (sketch,), (replace(sketch, entities=(edited, target)),), (array,)
    )
    propagated_target = propagated[0].entities[1]
    assert isinstance(propagated_target, LineEntity)
    assert propagated_target.entity_id == target.entity_id
    assert propagated_target.end_mm == pytest.approx((3, 6))
    changed, updated = update_array_spacing((sketch,), (array,), array.array_id, 0, 8)
    moved = changed[0].entities[1]
    assert isinstance(moved, LineEntity)
    assert moved.start_mm == pytest.approx((0, 8))
    new_ref = ArrayEntityRef(sketch_id, uuid4().hex)
    resized = replace(
        updated, columns=3, members=(*updated.members, ArrayMember(origin, new_ref, 0, 2))
    )
    larger = resize_array(changed, (updated,), resized)
    new = larger[0].entities[-1]
    assert isinstance(new, LineEntity) and new.entity_id == new_ref.entity_id
    assert new.start_mm == pytest.approx((0, 16))
    with pytest.raises(ValueError, match="方向"):
        resize_array(changed, (updated,), replace(resized, angle_deg=0))


@pytest.mark.parametrize("change", ["missing", "duplicate", "bad_cell", "self", "spacing"])
def test_array_relation_rejects_invalid_members_and_spacing(change: str) -> None:
    array = _array()
    member = array.members[0]
    with pytest.raises(ValueError):
        if change == "missing":
            replace(array, members=())
        elif change == "duplicate":
            replace(array, members=(member, member))
        elif change == "bad_cell":
            replace(array, members=(replace(member, row=1),))
        elif change == "self":
            replace(array, members=(replace(member, target=member.source),))
        else:
            replace(array, column_spacing=0)


def test_array_network_accepts_dag_and_rejects_cycle_and_duplicate_target() -> None:
    first, second, third = _ref(), _ref(), _ref()
    a = _array(first, second)
    b = _array(second, third)
    validate_array_network((a, b))
    with pytest.raises(ValueError, match="环"):
        validate_array_network((a, b, _array(third, first)))
    with pytest.raises(ValueError, match="重复"):
        validate_array_network((a, _array(third, second)))


def test_array_network_handles_long_acyclic_chain_without_recursion() -> None:
    references = tuple(_ref() for _ in range(1201))
    arrays = tuple(_array(references[index], references[index + 1]) for index in range(1200))
    validate_array_network(arrays)


def test_array_relation_requires_complete_multi_source_grid() -> None:
    first, second = _ref(), _ref()
    members = tuple(
        ArrayMember(source, _ref(), row, column)
        for source in (first, second)
        for row, column in ((0, 1), (1, 0), (1, 1))
    )
    array = AssociativeRectArray(
        uuid4().hex, WorkPlaneFrame.xy(), 2, 2, -3, 4, (first, second), members
    )
    assert AssociativeRectArray.from_mapping(array.to_mapping()) == array
    with pytest.raises(ValueError, match="缺失"):
        replace(array, members=members[:-1])
    with pytest.raises(ValueError, match="重复"):
        replace(array, members=(*members[:-1], replace(members[-1], target=members[0].target)))


@pytest.mark.parametrize("value", [True, float("inf"), float("nan"), 10**1000])
def test_array_relation_rejects_nonfinite_or_non_numeric_spacing(value: object) -> None:
    data = _array().to_mapping()
    with pytest.raises(ValueError):
        AssociativeRectArray.from_mapping({**data, "column_spacing": value})


def test_array_mapping_rejects_unknown_fields_and_bad_cell_types() -> None:
    array = _array()
    data = array.to_mapping()
    with pytest.raises(ValueError):
        AssociativeRectArray.from_mapping({**data, "unknown": True})
    members = [array.members[0].to_mapping()]
    members[0] = {**members[0], "row": True}
    with pytest.raises(ValueError):
        AssociativeRectArray.from_mapping({**data, "members": members})


def test_source_edit_regenerates_member_with_stable_identity() -> None:
    sketch_id = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (source, target))
    source_ref = ArrayEntityRef(sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(sketch_id, target.entity_id)
    array = _array(source_ref, target_ref)
    edited = replace(source, end_mm=(3, 1))
    proposed = replace(sketch, entities=(edited, target))
    result = propagate_array_changes((sketch,), (proposed,), (array,))
    assert result[0].entities == (edited, replace(target, end_mm=(8, 1)))
    assert sketch.entities == (source, target) and proposed.entities == (edited, target)


def test_array_angle_update_propagates_downstream_and_preserves_ids() -> None:
    from mycad.core.associative_array import update_array_spacing

    sketch_id = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    first = LineEntity(uuid4().hex, (5, 0), (7, 0))
    second = LineEntity(uuid4().hex, (10, 0), (12, 0))
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (source, first, second))
    refs = tuple(ArrayEntityRef(sketch_id, item.entity_id) for item in (source, first, second))
    upstream, downstream = _array(refs[0], refs[1]), _array(refs[1], refs[2])
    revised, updated = update_array_spacing(
        (sketch,), (upstream, downstream), upstream.array_id, 0, 5, angle_deg=90
    )
    assert updated.angle_deg == 90
    first_result, second_result = revised[0].entities[1:]
    assert isinstance(first_result, LineEntity) and isinstance(second_result, LineEntity)
    assert first_result.entity_id == first.entity_id and first_result.start_mm == pytest.approx(
        (0, 5)
    )
    assert second_result.entity_id == second.entity_id and second_result.start_mm == pytest.approx(
        (5, 5)
    )


def test_array_spacing_update_preserves_ids_and_propagates_downstream() -> None:
    from mycad.core.associative_array import update_array_spacing

    sketch_id = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    first = LineEntity(uuid4().hex, (5, 0), (7, 0))
    second = LineEntity(uuid4().hex, (10, 0), (12, 0))
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (source, first, second))
    refs = tuple(ArrayEntityRef(sketch_id, entity.entity_id) for entity in (source, first, second))
    upstream, downstream = _array(refs[0], refs[1]), _array(refs[1], refs[2])
    revised, updated = update_array_spacing(
        (sketch,), (upstream, downstream), upstream.array_id, 0, 8
    )
    assert updated == replace(upstream, column_spacing=8)
    assert revised[0].entities == (
        source,
        replace(first, start_mm=(8, 0), end_mm=(10, 0)),
        replace(second, start_mm=(13, 0), end_mm=(15, 0)),
    )
    assert sketch.entities == (source, first, second)


@pytest.mark.parametrize("angle", [None, 90.0])
def test_array_spacing_update_rejects_locked_layers_without_changes(angle: float | None) -> None:
    from mycad.core.associative_array import update_array_spacing
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    sketch_id = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="L")
    target = LineEntity(uuid4().hex, (5, 0), (7, 0), layer_name="L")
    layers = SketchLayerTable().add(SketchLayer("L", locked=True))
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (source, target), layers=layers)
    array = _array(
        ArrayEntityRef(sketch_id, source.entity_id), ArrayEntityRef(sketch_id, target.entity_id)
    )
    with pytest.raises(ValueError, match="锁定"):
        update_array_spacing((sketch,), (array,), array.array_id, 0, 8, angle_deg=angle)
    assert sketch.entities == (source, target) and array.column_spacing == 5


def test_array_resize_preserves_existing_cells_and_adds_or_removes_stable_members() -> None:
    from mycad.core.associative_array import resize_array

    sketch_id = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (source, target))
    origin = ArrayEntityRef(sketch_id, source.entity_id)
    old_ref = ArrayEntityRef(sketch_id, target.entity_id)
    array = _array(origin, old_ref)
    new_ref = ArrayEntityRef(sketch_id, uuid4().hex)
    larger = replace(array, columns=3, members=(*array.members, ArrayMember(origin, new_ref, 0, 2)))
    expanded = resize_array((sketch,), (array,), larger)
    assert expanded[0].entities == (
        source,
        target,
        replace(target, entity_id=new_ref.entity_id, start_mm=(10, 0), end_mm=(12, 0)),
    )
    smaller = replace(larger, columns=2, members=array.members)
    assert resize_array(expanded, (larger,), smaller) == (sketch,)
    assert sketch.entities == (source, target)


def test_array_resize_rejects_removing_source_of_downstream_array() -> None:
    from mycad.core.associative_array import resize_array

    sketch_id = uuid4().hex
    entities = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10, 15))
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch_id, entity.entity_id) for entity in entities)
    first = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        3,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1), ArrayMember(refs[0], refs[2], 0, 2)),
    )
    downstream = _array(refs[2], refs[3])
    smaller = replace(first, columns=2, members=first.members[:1])
    with pytest.raises(ValueError, match="下游"):
        resize_array((sketch,), (first, downstream), smaller)
    assert sketch.entities == entities


def test_array_resize_can_set_spacing_on_newly_enabled_axis() -> None:
    from mycad.core.associative_array import resize_array

    sketch_id = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (source, target))
    origin, existing = (
        ArrayEntityRef(sketch_id, source.entity_id),
        ArrayEntityRef(sketch_id, target.entity_id),
    )
    array = _array(origin, existing)
    lower = ArrayEntityRef(sketch_id, uuid4().hex)
    lower_right = ArrayEntityRef(sketch_id, uuid4().hex)
    enlarged = replace(
        array,
        rows=2,
        row_spacing=-4,
        members=(
            *array.members,
            ArrayMember(origin, lower, 1, 0),
            ArrayMember(origin, lower_right, 1, 1),
        ),
    )
    result = resize_array((sketch,), (array,), enlarged)
    assert [entity.start_mm for entity in result[0].entities if isinstance(entity, LineEntity)] == [
        (0, 0),
        (5, 0),
        (0, -4),
        (5, -4),
    ]


@pytest.mark.parametrize("change", ["target_edit", "target_delete", "source_delete"])
def test_array_propagation_rejects_direct_member_edit_or_missing_reference(change: str) -> None:
    sketch_id = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (source, target))
    array = _array(
        ArrayEntityRef(sketch_id, source.entity_id), ArrayEntityRef(sketch_id, target.entity_id)
    )
    entities = (
        (source, replace(target, end_mm=(9, 0)))
        if change == "target_edit"
        else (source,)
        if change == "target_delete"
        else (target,)
    )
    with pytest.raises(ValueError):
        propagate_array_changes((sketch,), (replace(sketch, entities=entities),), (array,))
    assert sketch.entities == (source, target)


def test_array_propagation_rejects_locked_target_and_inconsistent_snapshot() -> None:
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    sketch_id = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="locked")
    target = LineEntity(uuid4().hex, (5, 0), (7, 0), layer_name="locked")
    layers = SketchLayerTable().add(SketchLayer("locked", locked=True))
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (source, target), layers=layers)
    array = _array(
        ArrayEntityRef(sketch_id, source.entity_id), ArrayEntityRef(sketch_id, target.entity_id)
    )
    proposed = replace(sketch, entities=(replace(source, end_mm=(3, 0)), target))
    with pytest.raises(ValueError, match="锁定"):
        propagate_array_changes((sketch,), (proposed,), (array,))
    inconsistent = replace(sketch, entities=(source, replace(target, end_mm=(8, 0))))
    with pytest.raises(ValueError, match="不一致"):
        propagate_array_changes((inconsistent,), (inconsistent,), (array,))


def test_array_propagation_preserves_coordinates_across_shifted_sketch_frames() -> None:
    first_id, second_id = uuid4().hex, uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (-5, 0), (-3, 0))
    first = Sketch(first_id, WorkPlaneFrame.xy(), (source,))
    shifted_frame = replace(WorkPlaneFrame.xy(), origin_mm=(10, 0, 0))
    second = Sketch(second_id, shifted_frame, (target,))
    array = _array(
        ArrayEntityRef(first_id, source.entity_id), ArrayEntityRef(second_id, target.entity_id)
    )
    edited = replace(source, end_mm=(3, 1))
    result = propagate_array_changes(
        (first, second), (replace(first, entities=(edited,)), second), (array,)
    )
    assert result[1].entities == (replace(target, end_mm=(-2, 1)),)


def test_array_propagation_rejects_incompatible_frame() -> None:
    first_id, second_id = uuid4().hex, uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    first = Sketch(first_id, WorkPlaneFrame.xy(), (source,))
    rotated = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    second = Sketch(second_id, rotated, (target,))
    array = _array(
        ArrayEntityRef(first_id, source.entity_id), ArrayEntityRef(second_id, target.entity_id)
    )
    with pytest.raises(ValueError, match="轴向"):
        propagate_array_changes((first, second), (first, second), (array,))


def test_array_propagation_rejects_locked_destination_layer() -> None:
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    first_id, second_id = uuid4().hex, uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    source_layers = SketchLayerTable().add(SketchLayer("new"))
    target_layers = SketchLayerTable().add(SketchLayer("new", locked=True))
    first = Sketch(first_id, WorkPlaneFrame.xy(), (source,), layers=source_layers)
    second = Sketch(second_id, WorkPlaneFrame.xy(), (target,), layers=target_layers)
    array = _array(
        ArrayEntityRef(first_id, source.entity_id), ArrayEntityRef(second_id, target.entity_id)
    )
    proposed = replace(first, entities=(replace(source, layer_name="new"),))
    with pytest.raises(ValueError, match="锁定"):
        propagate_array_changes((first, second), (proposed, second), (array,))
    assert second.entities == (target,)


def test_array_propagation_failure_does_not_modify_other_targets() -> None:
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    first_id, second_id, third_id = uuid4().hex, uuid4().hex, uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="L")
    target1 = LineEntity(uuid4().hex, (5, 0), (7, 0), layer_name="L")
    target2 = LineEntity(uuid4().hex, (10, 0), (12, 0), layer_name="L")
    unlocked = SketchLayerTable().add(SketchLayer("L"))
    locked = SketchLayerTable().add(SketchLayer("L", locked=True))
    first = Sketch(first_id, WorkPlaneFrame.xy(), (source,), layers=unlocked)
    second = Sketch(second_id, WorkPlaneFrame.xy(), (target1,), layers=unlocked)
    third = Sketch(third_id, WorkPlaneFrame.xy(), (target2,), layers=locked)
    source_ref = ArrayEntityRef(first_id, source.entity_id)
    members = (
        ArrayMember(source_ref, ArrayEntityRef(second_id, target1.entity_id), 0, 1),
        ArrayMember(source_ref, ArrayEntityRef(third_id, target2.entity_id), 0, 2),
    )
    array = AssociativeRectArray(
        uuid4().hex, WorkPlaneFrame.xy(), 1, 3, 0, 5, (source_ref,), members
    )
    proposed = (replace(first, entities=(replace(source, end_mm=(3, 1)),)), second, third)
    with pytest.raises(ValueError, match="锁定"):
        propagate_array_changes((first, second, third), proposed, (array,))
    assert second.entities == (target1,) and third.entities == (target2,)
    assert proposed[1:] == (second, third)


def test_array_propagation_updates_dependency_chain_in_topological_order() -> None:
    sketch_id = uuid4().hex
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (5, 0), (7, 0))
    third = LineEntity(uuid4().hex, (10, 0), (12, 0))
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (first, second, third))
    refs = tuple(ArrayEntityRef(sketch_id, item.entity_id) for item in (first, second, third))
    arrays = (_array(refs[1], refs[2]), _array(refs[0], refs[1]))
    edited = replace(first, end_mm=(4, 1))
    result = propagate_array_changes(
        (sketch,), (replace(sketch, entities=(edited, second, third)),), arrays
    )
    assert result[0].entities == (
        edited,
        replace(second, end_mm=(9, 1)),
        replace(third, end_mm=(14, 1)),
    )


def test_array_propagation_handles_large_grid_without_changing_member_ids() -> None:
    sketch_id = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    source_ref = ArrayEntityRef(sketch_id, source.entity_id)
    copies = tuple(
        LineEntity(uuid4().hex, (index * 2, 0), (index * 2 + 1, 0)) for index in range(1, 1000)
    )
    members = tuple(
        ArrayMember(source_ref, ArrayEntityRef(sketch_id, copy.entity_id), 0, index)
        for index, copy in enumerate(copies, start=1)
    )
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (source, *copies))
    array = AssociativeRectArray(
        uuid4().hex, WorkPlaneFrame.xy(), 1, 1000, 0, 2, (source_ref,), members
    )
    edited = replace(source, end_mm=(1, 1))
    result = propagate_array_changes(
        (sketch,), (replace(sketch, entities=(edited, *copies)),), (array,)
    )
    assert len(result[0].entities) == 1000
    assert tuple(entity.entity_id for entity in result[0].entities) == tuple(
        entity.entity_id for entity in sketch.entities
    )
    assert isinstance(result[0].entities[-1], LineEntity)
    assert result[0].entities[-1].end_mm == (1999, 1)


def test_array_propagation_rejects_constrained_member_without_partial_changes() -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    sketch_id = uuid4().hex
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(target.entity_id, "start"),)
    )
    sketch = Sketch(sketch_id, WorkPlaneFrame.xy(), (source, target), constraints=(constraint,))
    array = _array(
        ArrayEntityRef(sketch_id, source.entity_id), ArrayEntityRef(sketch_id, target.entity_id)
    )
    proposed = replace(sketch, entities=(replace(source, end_mm=(3, 1)), target))
    with pytest.raises(ValueError, match="约束"):
        propagate_array_changes((sketch,), (proposed,), (array,))
    assert sketch.entities == (source, target) and proposed.entities[-1] == target


def test_cross_array_batch_offsets_propagate_through_dependency_chain() -> None:
    from mycad.core.associative_array import set_array_offsets_batch

    identity = uuid4().hex
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    sketch = Sketch(identity, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(identity, line.entity_id) for line in lines)
    upstream, downstream = _array(refs[0], refs[1]), _array(refs[1], refs[2])
    changed, arrays = set_array_offsets_batch(
        (sketch,),
        (upstream, downstream),
        {upstream.array_id: {refs[1]: (2, 3)}, downstream.array_id: {refs[2]: (1, 1)}},
    )
    first, second = changed[0].entities[1:]
    assert isinstance(first, LineEntity) and isinstance(second, LineEntity)
    assert first.start_mm == pytest.approx((7, 3))
    assert second.start_mm == pytest.approx((13, 4))
    assert arrays[0].members[0].offset_mm == (2, 3)
    assert arrays[1].members[0].offset_mm == (1, 1)


@pytest.mark.parametrize("hidden", [False, True])
def test_member_dimension_erasure_rejects_protected_layer(hidden: bool) -> None:
    from mycad.core.associative_array import strip_erased_member_dimensions
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        2.0,
        "mm",
        driving=False,
        layer_name="protected",
    )
    layers = SketchLayerTable().add(SketchLayer("protected", locked=not hidden, visible=not hidden))
    before = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,), layers=layers)
    after = replace(before, entities=(), constraints=())
    target = ArrayEntityRef(before.sketch_id, line.entity_id)
    with pytest.raises(ValueError, match="锁定或隐藏"):
        strip_erased_member_dimensions((before,), (after,), (target,))
    assert before.constraints == (dimension,)
