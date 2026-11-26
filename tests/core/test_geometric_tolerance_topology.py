# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Explicit topology mappings preserve annotation attachment identity."""

from dataclasses import replace
from uuid import uuid4

import pytest

from mycad.core.geometric_tolerance import DatumAttachment
from mycad.core.sketch_constraints import SketchGeometryReference


def test_legacy_curve_point_identities_are_stable_and_domain_separated() -> None:
    from mycad.core.geometric_tolerance_topology import legacy_curve_point_identities

    identity = uuid4().hex
    vertices = legacy_curve_point_identities(identity, "polyline", 4)
    assert vertices == legacy_curve_point_identities(identity, "polyline", 4)
    assert len(set(vertices)) == 4
    assert set(vertices).isdisjoint(legacy_curve_point_identities(identity, "spline", 4))
    assert set(vertices).isdisjoint(legacy_curve_point_identities(uuid4().hex, "polyline", 4))
    assert legacy_curve_point_identities("00000000000000000000000000000001", "polyline", 2) == (
        "dc965ff6d0d65dba967d5676f1361e35",
        "d2657d21fa2b51c198e2a664d2a2e203",
    )


@pytest.mark.parametrize(
    ("entity", "kind", "count"),
    [
        ("bad-id", "polyline", 2),
        (uuid4().hex, "other", 2),
        (uuid4().hex, "polyline", True),
        (uuid4().hex, "spline", 3),
    ],
)
def test_legacy_curve_point_identities_reject_invalid_input(
    entity: str, kind: str, count: int
) -> None:
    from mycad.core.geometric_tolerance_topology import legacy_curve_point_identities

    with pytest.raises(ValueError):
        legacy_curve_point_identities(entity, kind, count)


def test_curve_point_identity_record_roundtrip_and_polyline_remap() -> None:
    from mycad.core.geometric_tolerance_topology import CurvePointIdentities

    entity = uuid4().hex
    before = CurvePointIdentities.from_legacy(entity, "polyline", 3)
    restored = CurvePointIdentities.from_mapping(before.to_mapping())
    assert restored == before
    after = CurvePointIdentities(entity, "polyline", (*reversed(before.point_ids), uuid4().hex))
    mapping = before.polyline_map_to(after, closed=False)
    assert mapping.old_to_new == (2, 1, 0)
    assert mapping.new_count == 4


@pytest.mark.parametrize(
    "problem",
    ["duplicate", "invalid", "extra", "missing", "wrong_entity", "bool_version", "future_version"],
)
def test_curve_point_identity_record_rejects_invalid_data(problem: str) -> None:
    from mycad.core.geometric_tolerance_topology import CurvePointIdentities

    before = CurvePointIdentities.from_legacy(uuid4().hex, "polyline", 3)
    payload = before.to_mapping()
    if problem == "duplicate":
        payload["point_ids"] = [before.point_ids[0], before.point_ids[0], before.point_ids[2]]
    elif problem == "invalid":
        payload["point_ids"] = ["invalid", *before.point_ids[1:]]
    elif problem == "extra":
        payload["unexpected"] = True
    elif problem == "missing":
        del payload["point_ids"]
    elif problem == "bool_version":
        payload["version"] = True
    elif problem == "future_version":
        payload["version"] = 2
    else:
        other = CurvePointIdentities.from_legacy(uuid4().hex, "polyline", 3)
        with pytest.raises(ValueError):
            before.polyline_map_to(other, closed=False)
        return
    with pytest.raises(ValueError):
        CurvePointIdentities.from_mapping(payload)


def test_curve_point_identity_record_checks_actual_curve() -> None:
    from mycad.core.geometric_tolerance_topology import CurvePointIdentities
    from mycad.core.sketch import PolylineEntity, SplineEntity

    identity = uuid4().hex
    record = CurvePointIdentities.from_legacy(identity, "polyline", 3)
    record.validate_entity(PolylineEntity(identity, ((0, 0), (1, 0), (2, 0))))
    with pytest.raises(ValueError):
        record.validate_entity(PolylineEntity(identity, ((0, 0), (1, 0))))
    with pytest.raises(ValueError):
        record.validate_entity(PolylineEntity(uuid4().hex, ((0, 0), (1, 0), (2, 0))))
    with pytest.raises(ValueError):
        record.validate_entity(SplineEntity(identity, ((0, 0), (1, 0), (2, 0), (3, 0))))


def test_legacy_identity_upgrade_is_deterministic_and_preserves_geometry() -> None:
    from mycad.core.geometric_tolerance_topology import (
        apply_curve_identity_upgrade,
        prepare_curve_identity_upgrade,
    )
    from mycad.core.sketch import PolylineEntity, Sketch, SplineEntity, WorkPlaneFrame

    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    spline = SplineEntity(uuid4().hex, ((0, 0), (1, 0), (2, 1), (3, 1)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline, spline))
    records = prepare_curve_identity_upgrade(sketch, (polyline.entity_id, spline.entity_id))
    assert records == prepare_curve_identity_upgrade(sketch, (polyline.entity_id, spline.entity_id))
    upgraded = apply_curve_identity_upgrade(sketch, sketch.local_state_digest(), records)
    assert upgraded.entities[0] == replace(polyline, point_ids=records[0].point_ids)
    assert upgraded.entities[1] == replace(spline, point_ids=records[1].point_ids)
    assert upgraded.constraints == sketch.constraints
    assert Sketch.from_mapping(upgraded.to_state_mapping()) == upgraded
    assert sketch.entities == (polyline, spline)


def test_legacy_identity_upgrade_rejects_stale_forged_and_duplicate_records() -> None:
    from mycad.core.geometric_tolerance_topology import (
        apply_curve_identity_upgrade,
        prepare_curve_identity_upgrade,
    )
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    records = prepare_curve_identity_upgrade(sketch, (polyline.entity_id,))
    with pytest.raises(ValueError):
        apply_curve_identity_upgrade(sketch, "0" * 64, records)
    with pytest.raises(ValueError):
        apply_curve_identity_upgrade(sketch, sketch.local_state_digest(), records * 2)
    forged = replace(records[0], point_ids=(uuid4().hex, *records[0].point_ids[1:]))
    with pytest.raises(ValueError):
        apply_curve_identity_upgrade(sketch, sketch.local_state_digest(), (forged,))
    upgraded = apply_curve_identity_upgrade(sketch, sketch.local_state_digest(), records)
    with pytest.raises(ValueError):
        prepare_curve_identity_upgrade(upgraded, (polyline.entity_id,))


def test_unverified_revisions_cannot_lose_or_reassign_curve_identities() -> None:
    from mycad.core.geometric_tolerance_topology import (
        CurvePointIdentities,
        validate_curve_identity_preservation,
    )
    from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, WorkPlaneFrame

    identity = uuid4().hex
    ids = CurvePointIdentities.from_legacy(identity, "polyline", 3).point_ids
    curve = PolylineEntity(identity, ((0, 0), (10, 0), (10, 10)), point_ids=ids)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    moved = replace(sketch, entities=(replace(curve, points_mm=((1, 0), (11, 0), (11, 10))),))
    validate_curve_identity_preservation(sketch, moved)
    for bad_entity in (
        replace(curve, point_ids=()),
        replace(curve, point_ids=tuple(reversed(ids))),
        LineEntity(identity, (0, 0), (10, 0)),
    ):
        with pytest.raises(ValueError):
            validate_curve_identity_preservation(sketch, replace(sketch, entities=(bad_entity,)))
    validate_curve_identity_preservation(sketch, replace(sketch, entities=()))
    legacy = replace(sketch, entities=(replace(curve, point_ids=()),))
    with pytest.raises(ValueError):
        validate_curve_identity_preservation(legacy, sketch)


def test_new_curve_accepts_derived_identities_but_rejects_copied_or_forged_ids() -> None:
    from mycad.core.geometric_tolerance_topology import (
        new_curve_point_identities,
        validate_curve_identity_preservation,
    )
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    source_id, copy_id = uuid4().hex, uuid4().hex
    source_ids = new_curve_point_identities(source_id, "polyline", 3)
    source = PolylineEntity(source_id, ((0, 0), (1, 0), (1, 1)), point_ids=source_ids)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    copy_ids = new_curve_point_identities(copy_id, "polyline", 3)
    copied = PolylineEntity(copy_id, ((2, 0), (3, 0), (3, 1)), point_ids=copy_ids)
    validate_curve_identity_preservation(sketch, replace(sketch, entities=(source, copied)))
    forged = replace(copied, point_ids=(uuid4().hex, *copy_ids[1:]))
    with pytest.raises(ValueError):
        validate_curve_identity_preservation(sketch, replace(sketch, entities=(source, forged)))
    with pytest.raises(ValueError):
        validate_curve_identity_preservation(
            sketch, replace(sketch, entities=(copied, replace(source, point_ids=())))
        )


def test_explicit_mapping_tracks_vertex_across_reorder_and_insertion() -> None:
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap

    entity = uuid4().hex
    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(entity, "vertex", 1))
    mapping = PolylineTopologyMap(entity, (2, 0, 3), 4, False)
    assert mapping.remap(attachment).reference == SketchGeometryReference(entity, "vertex", 0)


def test_explicit_mapping_preserves_reversed_segment_position() -> None:
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap

    entity = uuid4().hex
    attachment = DatumAttachment(
        uuid4().hex, SketchGeometryReference(entity, "segment", 0), 0.25, 2
    )
    mapping = PolylineTopologyMap(entity, (2, 1, 0), 3, False)
    updated = mapping.remap(attachment)
    assert updated.reference == SketchGeometryReference(entity, "segment", 1)
    assert updated.parameter == 0.75
    assert updated.segment_count == 2


def test_explicit_mapping_handles_closed_wrap_and_rejects_lost_segment() -> None:
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap

    entity = uuid4().hex
    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(entity, "segment", 2), 0.4, 3)
    rotated = PolylineTopologyMap(entity, (1, 2, 0), 3, True).remap(attachment)
    assert rotated.reference.index == 0 and rotated.parameter == 0.4
    with pytest.raises(ValueError, match="线段"):
        PolylineTopologyMap(entity, (1, 2, None), 3, True).remap(attachment)
    with pytest.raises(ValueError, match="身份"):
        PolylineTopologyMap(entity, (0, 0, 2), 3, True)


@pytest.mark.parametrize("bulge", [0.0, 0.4, -0.4])
def test_explicit_reverse_preserves_line_and_arc_attachment_position(bulge: float) -> None:
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity

    entity = uuid4().hex
    old = PolylineEntity(entity, ((0, 0), (10, 0), (10, 10)), bulges=(bulge, 0))
    new = PolylineEntity(entity, tuple(reversed(old.points_mm)), bulges=(0, -bulge))
    attachment = DatumAttachment(
        uuid4().hex, SketchGeometryReference(entity, "segment", 0), 0.25, 2
    )
    mapped = PolylineTopologyMap(entity, (2, 1, 0), 3, False).remap(attachment)
    assert resolve_attachment_local(mapped, {entity: new}) == pytest.approx(
        resolve_attachment_local(attachment, {entity: old})
    )


def test_explicit_mapping_refuses_split_edge_and_converts_moved_endpoint() -> None:
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap

    entity = uuid4().hex
    sketch = uuid4().hex
    mapping = PolylineTopologyMap(entity, (1, 3, 4), 5, False)
    endpoint = mapping.remap(DatumAttachment(sketch, SketchGeometryReference(entity, "start")))
    assert endpoint.reference == SketchGeometryReference(entity, "vertex", 1)
    segment = DatumAttachment(sketch, SketchGeometryReference(entity, "segment", 0), 0.5, 2)
    with pytest.raises(ValueError, match="拆分"):
        mapping.remap(segment)


def test_checked_mapping_rejects_mismatched_polyline_and_arc_direction() -> None:
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity

    entity = uuid4().hex
    old = PolylineEntity(entity, ((0, 0), (10, 0), (10, 10)), bulges=(0.4, 0))
    reversed_points = tuple(reversed(old.points_mm))
    good = PolylineEntity(entity, reversed_points, bulges=(0, -0.4))
    wrong_curve = PolylineEntity(entity, reversed_points, bulges=(0, 0.4))
    wrong_closed = PolylineEntity(entity, reversed_points, closed=True)
    wrong_id = PolylineEntity(uuid4().hex, reversed_points)
    mapping = PolylineTopologyMap(entity, (2, 1, 0), 3, False)
    attachment = DatumAttachment(
        uuid4().hex, SketchGeometryReference(entity, "segment", 0), 0.25, 2
    )
    assert mapping.remap_checked(attachment, old, good).parameter == 0.75
    for invalid in (wrong_curve, wrong_closed, wrong_id):
        with pytest.raises(ValueError):
            mapping.remap_checked(attachment, old, invalid)


def test_topology_mapping_roundtrips_as_strict_command_data() -> None:
    import json

    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap

    mapping = PolylineTopologyMap(uuid4().hex, (2, None, 0), 4, False)
    payload = json.loads(json.dumps(mapping.to_mapping()))
    assert PolylineTopologyMap.from_mapping(payload) == mapping
    payload["unexpected"] = 1
    with pytest.raises(ValueError):
        PolylineTopologyMap.from_mapping(payload)


def test_mapping_prepares_datum_and_frame_together_without_mutating_inputs() -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap, remap_annotations
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    sketch_id, entity = uuid4().hex, uuid4().hex
    old = PolylineEntity(entity, ((0, 0), (10, 0), (10, 10)), bulges=(0.4, 0))
    new = PolylineEntity(entity, tuple(reversed(old.points_mm)), bulges=(0, -0.4))
    before = Sketch(sketch_id, WorkPlaneFrame.xy(), (old,))
    after = Sketch(sketch_id, WorkPlaneFrame.xy(), (new,))
    attachment = DatumAttachment(sketch_id, SketchGeometryReference(entity, "segment", 0), 0.25, 2)
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (5, 0), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (20, 10),
        leader_target_mm=(5, 0),
        leader_attachment=attachment,
    )
    mapping = PolylineTopologyMap(entity, (2, 1, 0), 3, False)
    datums, frames = remap_annotations(before, after, (mapping,), (datum,), (frame,))
    assert datums[0].attachment is not None and datums[0].attachment.parameter == 0.75
    assert frames[0].leader_attachment == datums[0].attachment
    assert datum.attachment == attachment and frame.leader_attachment == attachment
    with pytest.raises(ValueError, match="身份"):
        remap_annotations(before, after, (mapping, mapping), (datum,), (frame,))


def test_exact_reorder_evidence_verifies_points_connectivity_and_curvature() -> None:
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity

    entity = uuid4().hex
    old = PolylineEntity(entity, ((0, 0), (10, 0), (10, 10)), bulges=(0.4, 0))
    reverse = PolylineEntity(entity, tuple(reversed(old.points_mm)), bulges=(0, -0.4))
    mapping = PolylineTopologyMap(entity, (2, 1, 0), 3, False)
    mapping.validate_exact_reorder(old, reverse)
    moved = PolylineEntity(entity, ((10, 10), (10, 1), (0, 0)), bulges=(0, -0.4))
    wrong_bulge = PolylineEntity(entity, tuple(reversed(old.points_mm)), bulges=(0, 0.4))
    with pytest.raises(ValueError):
        mapping.validate_exact_reorder(old, moved)
    with pytest.raises(ValueError):
        mapping.validate_exact_reorder(old, wrong_bulge)
    with pytest.raises(ValueError):
        PolylineTopologyMap(entity, (1, 2, 0), 3, False).validate_exact_reorder(old, reverse)


def test_exact_reorder_evidence_rejects_duplicate_vertices() -> None:
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity

    entity = uuid4().hex
    points = ((0, 0), (10, 0), (0, 0), (10, 10))
    old = PolylineEntity(entity, points)
    new = PolylineEntity(entity, tuple(reversed(points)))
    with pytest.raises(ValueError, match="身份"):
        PolylineTopologyMap(entity, (3, 2, 1, 0), 4, False).validate_exact_reorder(old, new)


@pytest.mark.parametrize("reverse", [False, True])
def test_exact_closed_reorder_keeps_arc_attachment_position(reverse: bool) -> None:
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity

    entity = uuid4().hex
    old = PolylineEntity(entity, ((0, 0), (10, 0), (10, 10)), closed=True, bulges=(0.3, 0, 0))
    if reverse:
        new = PolylineEntity(entity, ((0, 0), (10, 10), (10, 0)), closed=True, bulges=(0, 0, -0.3))
        mapping = PolylineTopologyMap(entity, (0, 2, 1), 3, True)
    else:
        new = PolylineEntity(entity, ((10, 0), (10, 10), (0, 0)), closed=True, bulges=(0, 0, 0.3))
        mapping = PolylineTopologyMap(entity, (2, 0, 1), 3, True)
    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(entity, "segment", 0), 0.3, 3)
    mapping.validate_exact_reorder(old, new)
    updated = mapping.remap_checked(attachment, old, new)
    assert resolve_attachment_local(updated, {entity: new}) == pytest.approx(
        resolve_attachment_local(attachment, {entity: old})
    )


def test_associative_topology_protection_includes_all_reference_roles() -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance_topology import associative_topology_entities
    from mycad.core.sketch import WorkPlaneFrame

    sketch_a, sketch_b = uuid4().hex, uuid4().hex
    refs = tuple(ArrayEntityRef(sketch_a, uuid4().hex) for _ in range(5))
    source, target, replacement, extra_source, extra_target = refs
    array = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        5,
        (source,),
        (ArrayMember(source, target, 0, 1, replacement=ArrayReplacement(replacement)),),
        base_point=ArrayBasePoint(
            source=source, reference=SketchGeometryReference(source.entity_id, "start")
        ),
        extra_outputs=(ArrayExtraOutput(extra_source, extra_target, source, 0, 1),),
    )
    cross = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketch_a, uuid4().hex),
        CrossSketchRef(sketch_b, uuid4().hex),
        "external",
    )
    expected = {(ref.sketch_id, ref.entity_id) for ref in refs}
    expected |= {
        (cross.first.sketch_id, cross.first.entity_id),
        (cross.second.sketch_id, cross.second.entity_id),
    }
    assert associative_topology_entities((array,), (cross,)) == expected


def test_array_reorder_proof_rejects_unproven_array_roles() -> None:
    from dataclasses import replace

    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_members
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    source, target, third = tuple(ArrayEntityRef(sketch, uuid4().hex) for _ in range(3))
    member = ArrayMember(source, target, 0, 1)
    array = AssociativeRectArray(
        uuid4().hex, WorkPlaneFrame.xy(), 1, 2, 0, 10, (source,), (member,)
    )
    selected = frozenset(((source.sketch_id, source.entity_id),))
    assert simple_array_reorder_members((array,), selected) == ((source, target),)
    variants = (
        replace(array, members=(replace(member, rotation_deg=90),)),
        replace(array, members=(replace(member, replacement=ArrayReplacement(third)),)),
        replace(
            array,
            base_point=ArrayBasePoint(
                source=source, reference=SketchGeometryReference(source.entity_id, "start")
            ),
        ),
        replace(array, extra_outputs=(ArrayExtraOutput(source, third, source, 0, 1),)),
    )
    for item in variants:
        with pytest.raises(ValueError):
            simple_array_reorder_members((item,), selected)
    chained = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (target,),
        (ArrayMember(target, third, 0, 1),),
    )
    with pytest.raises(ValueError):
        simple_array_reorder_members((array, chained), selected)
    with pytest.raises(ValueError):
        simple_array_reorder_members((array,), frozenset(((target.sketch_id, target.entity_id),)))


def test_dynamic_array_base_proof_requires_stable_identity_and_coordinate() -> None:
    from dataclasses import replace

    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap, stable_array_base_ids
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    entity = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    source = ArrayEntityRef(sketch.sketch_id, entity.entity_id)
    target = ArrayEntityRef(uuid4().hex, uuid4().hex)
    base = ArrayBasePoint(
        source=source, reference=SketchGeometryReference(entity.entity_id, "vertex", 0)
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        10,
        (source,),
        (ArrayMember(source, target, 0, 1),),
        base_point=base,
    )
    reverse = replace(entity, points_mm=(entity.points_mm[0], *reversed(entity.points_mm[1:])))
    after = replace(sketch, entities=(reverse,))
    mapping = PolylineTopologyMap(entity.entity_id, (0, 3, 2, 1), 4, True)
    key = (sketch.sketch_id, entity.entity_id)
    assert stable_array_base_ids((array,), (sketch,), (after,), {key: mapping}) == {array.array_id}
    assert not stable_array_base_ids((array,), (sketch,), (after,), {})
    moved_base = replace(
        array,
        base_point=ArrayBasePoint(
            source=source, reference=SketchGeometryReference(entity.entity_id, "vertex", 1)
        ),
    )
    assert not stable_array_base_ids((moved_base,), (sketch,), (after,), {key: mapping})
    assert stable_array_base_ids((moved_base,), (sketch,), (sketch,), {}) == {array.array_id}


def test_array_base_rebinding_tracks_same_vertex_and_rejects_unproven_mapping() -> None:
    from dataclasses import replace

    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
        propagate_array_changes,
    )
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap, rebind_array_base
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_references import resolve_point_reference

    entity = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    before = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    source = ArrayEntityRef(before.sketch_id, entity.entity_id)
    target = ArrayEntityRef(uuid4().hex, uuid4().hex)
    ref = SketchGeometryReference(entity.entity_id, "vertex", 1)
    array = AssociativeRectArray(
        uuid4().hex,
        before.frame,
        1,
        2,
        0,
        10,
        (source,),
        (ArrayMember(source, target, 0, 1),),
        base_point=ArrayBasePoint(source=source, reference=ref),
    )
    reverse = replace(entity, points_mm=(entity.points_mm[0], *reversed(entity.points_mm[1:])))
    after = replace(before, entities=(reverse,))
    mapping = PolylineTopologyMap(entity.entity_id, (0, 3, 2, 1), 4, True)
    rebound = rebind_array_base(array, before, after, mapping)
    assert rebound.base_point is not None and rebound.base_point.reference is not None
    assert rebound.base_point.reference.index == 3
    assert resolve_point_reference(ref, {entity.entity_id: entity}) == resolve_point_reference(
        rebound.base_point.reference, {entity.entity_id: reverse}
    )
    assert array.base_point is not None and array.base_point.reference == ref
    bad = replace(reverse, points_mm=(reverse.points_mm[0], (1, 9), *reverse.points_mm[2:]))
    with pytest.raises(ValueError):
        rebind_array_base(array, before, replace(before, entities=(bad,)), mapping)
    target_entity = PolylineEntity(
        target.entity_id, tuple((x + 10, y) for x, y in entity.points_mm), closed=True
    )
    target_sketch = Sketch(target.sketch_id, WorkPlaneFrame.xy(), (target_entity,))
    key = (source.sketch_id, source.entity_id)
    updated = propagate_array_changes(
        (before, target_sketch),
        (after, target_sketch),
        (array,),
        resulting_arrays=(rebound,),
        base_rebind_maps={key: mapping},
    )
    assert updated[1].entities[0] == replace(
        target_entity, points_mm=tuple((x + 10, y) for x, y in reverse.points_mm)
    )
    with pytest.raises(ValueError, match="其他修改"):
        propagate_array_changes(
            (before, target_sketch),
            (after, target_sketch),
            (array,),
            resulting_arrays=(replace(rebound, column_spacing=11),),
            base_rebind_maps={key: mapping},
        )
    with pytest.raises(ValueError, match="拓扑证明"):
        propagate_array_changes(
            (before, target_sketch),
            (after, target_sketch),
            (array,),
            resulting_arrays=(rebound,),
            base_rebind_maps={},
        )


def test_simple_array_chain_follows_topological_order_independent_of_input_order() -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    first, second, third, fourth = (ArrayEntityRef(sketch, uuid4().hex) for _ in range(4))

    def array(source: ArrayEntityRef, target: ArrayEntityRef) -> AssociativeRectArray:
        return AssociativeRectArray(
            uuid4().hex,
            WorkPlaneFrame.xy(),
            1,
            2,
            0,
            10,
            (source,),
            (ArrayMember(source, target, 0, 1),),
        )

    arrays = (array(third, fourth), array(second, third), array(first, second))
    assert simple_array_reorder_chain(arrays, frozenset(((sketch, first.entity_id),))) == (
        (first, second),
        (second, third),
        (third, fourth),
    )


def test_simple_array_chain_rejects_cycles_and_unproven_member_roles() -> None:
    from dataclasses import replace

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    first, second, third = (ArrayEntityRef(sketch, uuid4().hex) for _ in range(3))

    def array(source: ArrayEntityRef, target: ArrayEntityRef) -> AssociativeRectArray:
        return AssociativeRectArray(
            uuid4().hex,
            WorkPlaneFrame.xy(),
            1,
            2,
            0,
            10,
            (source,),
            (ArrayMember(source, target, 0, 1),),
        )

    a, b = array(first, second), array(second, third)
    selected = frozenset(((sketch, first.entity_id),))
    with pytest.raises(ValueError, match="环"):
        simple_array_reorder_chain((a, b, array(third, first)), selected)
    with pytest.raises(ValueError, match="成员"):
        simple_array_reorder_chain((a, b), frozenset(((sketch, second.entity_id),)))
    rotated = replace(b, members=(replace(b.members[0], rotation_deg=90),))
    with pytest.raises(ValueError, match="重绑定"):
        simple_array_reorder_chain((a, rotated), selected)
    with pytest.raises(ValueError, match="目标重复"):
        simple_array_reorder_chain((a, b, array(first, third)), selected)


def test_simple_array_chain_rejects_unrelated_replacement_dependency() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    first, second, third, fourth = (ArrayEntityRef(sketch, uuid4().hex) for _ in range(4))
    a = AssociativeRectArray(
        uuid4().hex, WorkPlaneFrame.xy(), 1, 2, 0, 10, (first,), (ArrayMember(first, second, 0, 1),)
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (third,),
        (ArrayMember(third, fourth, 0, 1, replacement=ArrayReplacement(first)),),
    )
    with pytest.raises(ValueError, match="替换|关联"):
        simple_array_reorder_chain((a, b), frozenset(((sketch, first.entity_id),)))


def test_simple_array_chain_allows_rotations_only_with_proven_stable_anchor() -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    first, second, third = (ArrayEntityRef(sketch, uuid4().hex) for _ in range(3))
    a = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (first,),
        (ArrayMember(first, second, 0, 1, rotation_deg=90),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (second,),
        (ArrayMember(second, third, 0, 1, rotation_deg=180),),
    )
    sources = frozenset(((sketch, first.entity_id),))
    with pytest.raises(ValueError, match="重绑定"):
        simple_array_reorder_chain((a, b), sources)
    assert simple_array_reorder_chain((b, a), sources, stable_anchor_sources=sources) == (
        (first, second),
        (second, third),
    )


def test_simple_array_chain_accepts_only_proven_stable_vertex_zero_base() -> None:
    from dataclasses import replace

    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    first, second, third = (ArrayEntityRef(sketch, uuid4().hex) for _ in range(3))
    a = AssociativeRectArray(
        uuid4().hex, WorkPlaneFrame.xy(), 1, 2, 0, 10, (first,), (ArrayMember(first, second, 0, 1),)
    )
    base = ArrayBasePoint(
        source=second, reference=SketchGeometryReference(second.entity_id, "vertex", 0)
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (second,),
        (ArrayMember(second, third, 0, 1, rotation_deg=90),),
        base_point=base,
    )
    sources = frozenset(((sketch, first.entity_id),))
    with pytest.raises(ValueError, match="基点|关联"):
        simple_array_reorder_chain((a, b), sources, stable_anchor_sources=sources)
    assert simple_array_reorder_chain(
        (a, b), sources, stable_anchor_sources=sources, allow_stable_bases=True
    ) == ((first, second), (second, third))
    with pytest.raises(ValueError, match="基点|关联"):
        simple_array_reorder_chain((a, b), sources, allow_stable_bases=True)
    changed = replace(
        b,
        base_point=replace(base, reference=SketchGeometryReference(second.entity_id, "vertex", 1)),
    )
    with pytest.raises(ValueError, match="基点|关联"):
        simple_array_reorder_chain(
            (a, changed), sources, stable_anchor_sources=sources, allow_stable_bases=True
        )


def test_array_chain_stable_dynamic_base_uses_proven_vertex_identity() -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    first, second, third = (ArrayEntityRef(sketch, uuid4().hex) for _ in range(3))
    a = AssociativeRectArray(
        uuid4().hex, WorkPlaneFrame.xy(), 1, 2, 0, 10, (first,), (ArrayMember(first, second, 0, 1),)
    )
    base = ArrayBasePoint(
        source=second, reference=SketchGeometryReference(second.entity_id, "vertex", 2)
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (second,),
        (ArrayMember(second, third, 0, 1, rotation_deg=90),),
        base_point=base,
    )
    source = (sketch, first.entity_id)
    sources = frozenset((source,))
    with pytest.raises(ValueError, match="基点|关联"):
        simple_array_reorder_chain(
            (a, b), sources, stable_anchor_sources=sources, allow_stable_bases=True
        )
    assert simple_array_reorder_chain(
        (a, b),
        sources,
        stable_anchor_sources=sources,
        allow_stable_bases=True,
        stable_base_vertices={source: frozenset((0, 2))},
    ) == ((first, second), (second, third))
    with pytest.raises(ValueError, match="基点|关联"):
        simple_array_reorder_chain(
            (a, b),
            sources,
            stable_anchor_sources=sources,
            allow_stable_bases=True,
            stable_base_vertices={source: frozenset((0, 1))},
        )


def test_predict_chain_reorder_verifies_each_member_and_preserves_point_identities() -> None:
    from dataclasses import replace

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
        predict_chain_reorder,
    )
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
    )
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    entities = tuple(
        PolylineEntity(
            identity,
            ((0, y), (10, y), (10, y + 10)),
            point_ids=new_curve_point_identities(identity, "polyline", 3),
        )
        for identity, y in ((uuid4().hex, 0), (uuid4().hex, 20), (uuid4().hex, 40))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, entity.entity_id) for entity in entities)
    arrays = tuple(
        AssociativeRectArray(
            uuid4().hex, sketch.frame, 2, 1, 20, 0, (a,), (ArrayMember(a, b, 1, 0),)
        )
        for a, b in zip(refs[:-1], refs[1:], strict=True)
    )
    source = replace(
        entities[0],
        points_mm=tuple(reversed(entities[0].points_mm)),
        point_ids=tuple(reversed(entities[0].point_ids)),
    )
    proposed = replace(sketch, entities=(source, *entities[1:]))
    mapping = PolylineTopologyMap(source.entity_id, (2, 1, 0), 3, False)
    edges = ((refs[0], refs[1]), (refs[1], refs[2]))
    predicted, maps = predict_chain_reorder(
        (sketch,), (proposed,), arrays, edges, {(sketch.sketch_id, source.entity_id): mapping}
    )
    for before, after in zip(entities, predicted[0].entities, strict=True):
        assert isinstance(after, PolylineEntity)
        assert after.points_mm == tuple(reversed(before.points_mm))
        assert after.point_ids == tuple(reversed(before.point_ids))
        assert maps[(sketch.sketch_id, before.entity_id)].old_to_new == (2, 1, 0)
    assert sketch.entities == entities
    with pytest.raises(ValueError, match="映射|拓扑|顺序"):
        predict_chain_reorder(
            (sketch,),
            (proposed,),
            arrays,
            tuple(reversed(edges)),
            {(sketch.sketch_id, source.entity_id): mapping},
        )

    with pytest.raises(ValueError, match="重复|映射|拓扑"):
        predict_chain_reorder(
            (sketch,),
            (proposed,),
            arrays,
            (edges[0], edges[0]),
            {(sketch.sketch_id, source.entity_id): mapping},
        )

    plain = replace(sketch, entities=tuple(replace(item, point_ids=()) for item in entities))
    plain_proposed = replace(plain, entities=(replace(source, point_ids=()), *plain.entities[1:]))
    with pytest.raises(ValueError, match="重复|映射|拓扑"):
        predict_chain_reorder(
            (plain,),
            (plain_proposed,),
            arrays,
            (edges[0], edges[0]),
            {(sketch.sketch_id, source.entity_id): mapping},
        )


@pytest.mark.parametrize(("kind", "index"), [("vertex", 1), ("start", None), ("end", None)])
def test_array_chain_can_plan_dynamic_base_rebinding_without_assuming_stability(
    kind: str, index: int | None
) -> None:
    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    first, second, third = (ArrayEntityRef(sketch, uuid4().hex) for _ in range(3))
    a = AssociativeRectArray(
        uuid4().hex, WorkPlaneFrame.xy(), 1, 2, 0, 10, (first,), (ArrayMember(first, second, 0, 1),)
    )
    base = ArrayBasePoint(
        source=second, reference=SketchGeometryReference(second.entity_id, kind, index)
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (second,),
        (ArrayMember(second, third, 0, 1, rotation_deg=90),),
        base_point=base,
    )
    sources = frozenset(((sketch, first.entity_id),))
    with pytest.raises(ValueError, match="基点|关联"):
        simple_array_reorder_chain(
            (a, b), sources, stable_anchor_sources=sources, allow_stable_bases=True
        )
    assert simple_array_reorder_chain(
        (a, b), sources, stable_anchor_sources=sources, allow_base_rebinding=True
    ) == ((first, second), (second, third))


def test_chain_base_rebinding_checks_predicted_members_against_actual_propagation() -> None:
    from dataclasses import replace

    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
        predict_chain_reorder,
        propagate_array_changes,
    )
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        new_curve_point_identities,
        rebind_array_base,
    )
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    entities = tuple(
        PolylineEntity(
            identity,
            ((0, y), (10, y), (10, y + 10)),
            point_ids=new_curve_point_identities(identity, "polyline", 3),
        )
        for identity, y in ((uuid4().hex, 0), (uuid4().hex, 20), (uuid4().hex, 40))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    a = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[0],), (ArrayMember(refs[0], refs[1], 1, 0),)
    )
    b = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[1],),
        (ArrayMember(refs[1], refs[2], 1, 0),),
        base_point=ArrayBasePoint(
            source=refs[1], reference=SketchGeometryReference(refs[1].entity_id, "vertex", 0)
        ),
    )
    source = replace(
        entities[0],
        points_mm=tuple(reversed(entities[0].points_mm)),
        point_ids=tuple(reversed(entities[0].point_ids)),
    )
    proposed = replace(sketch, entities=(source, *entities[1:]))
    root = PolylineTopologyMap(source.entity_id, (2, 1, 0), 3, False)
    predicted, maps = predict_chain_reorder(
        (sketch,),
        (proposed,),
        (a, b),
        ((refs[0], refs[1]), (refs[1], refs[2])),
        {(sketch.sketch_id, source.entity_id): root},
    )
    rebound = rebind_array_base(
        b, sketch, predicted[0], maps[(sketch.sketch_id, refs[1].entity_id)]
    )
    assert rebound.base_point is not None and rebound.base_point.reference is not None
    assert rebound.base_point.reference.index == 2
    actual = propagate_array_changes(
        (sketch,),
        (proposed,),
        (a, b),
        resulting_arrays=(a, rebound),
        base_rebind_maps=maps,
        base_rebind_proofs=predicted,
    )
    assert actual[0].entities[1].points_mm == predicted[0].entities[1].points_mm
    forged_entity = replace(
        predicted[0].entities[1], points_mm=((50, 50), *predicted[0].entities[1].points_mm[1:])
    )
    forged = (
        replace(
            predicted[0],
            entities=(predicted[0].entities[0], forged_entity, predicted[0].entities[2]),
        ),
    )
    with pytest.raises(ValueError, match="拓扑|证明|坐标"):
        propagate_array_changes(
            (sketch,),
            (proposed,),
            (a, b),
            resulting_arrays=(a, rebound),
            base_rebind_maps=maps,
            base_rebind_proofs=forged,
        )


def test_chain_base_proof_rejects_valid_reorder_that_is_not_actual_propagation() -> None:
    from dataclasses import replace

    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
        propagate_array_changes,
    )
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap, rebind_array_base
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_edit import move_entities, rotate_entities

    first = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    rotated = rotate_entities((first,), (first.entity_id,), (0, 0), 90)[0]
    moved = move_entities((rotated,), (first.entity_id,), (0, 20))[0]
    assert isinstance(moved, PolylineEntity)
    second = replace(moved, entity_id=uuid4().hex)
    third_moved = move_entities((second,), (second.entity_id,), (0, 20))[0]
    assert isinstance(third_moved, PolylineEntity)
    third = replace(third_moved, entity_id=uuid4().hex)
    original = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second, third))
    a, b, c = (
        ArrayEntityRef(original.sketch_id, item.entity_id) for item in (first, second, third)
    )
    one = AssociativeRectArray(
        uuid4().hex, original.frame, 2, 1, 20, 0, (a,), (ArrayMember(a, b, 1, 0, rotation_deg=90),)
    )
    two = AssociativeRectArray(
        uuid4().hex,
        original.frame,
        2,
        1,
        20,
        0,
        (b,),
        (ArrayMember(b, c, 1, 0),),
        base_point=ArrayBasePoint(
            source=b, reference=SketchGeometryReference(second.entity_id, "vertex", 1)
        ),
    )

    def shifted(item: PolylineEntity) -> PolylineEntity:
        return replace(item, points_mm=(item.points_mm[-1], *item.points_mm[:-1]))

    proposed = replace(original, entities=(shifted(first), second, third))
    forged = replace(original, entities=(shifted(first), shifted(second), shifted(third)))
    mapping = PolylineTopologyMap(second.entity_id, (1, 2, 3, 0), 4, True)
    rebound = rebind_array_base(two, original, forged, mapping)
    with pytest.raises(ValueError, match="额外变化|证明"):
        propagate_array_changes(
            (original,),
            (proposed,),
            (one, two),
            resulting_arrays=(one, rebound),
            base_rebind_maps={(original.sketch_id, second.entity_id): mapping},
            base_rebind_proofs=(forged,),
        )


def test_predict_chain_reorder_tracks_mappings_across_sketches() -> None:
    from dataclasses import replace

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        AssociativeRectArray,
        predict_chain_reorder,
    )
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    entities = tuple(
        PolylineEntity(uuid4().hex, ((0, y), (10, y), (10, y + 10))) for y in (0, 20, 40)
    )
    sketches = tuple(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)) for entity in entities)
    refs = tuple(
        ArrayEntityRef(sketch.sketch_id, entity.entity_id)
        for sketch, entity in zip(sketches, entities, strict=True)
    )
    arrays = tuple(
        AssociativeRectArray(
            uuid4().hex, sketches[0].frame, 2, 1, 20, 0, (a,), (ArrayMember(a, b, 1, 0),)
        )
        for a, b in zip(refs[:-1], refs[1:], strict=True)
    )
    source = replace(entities[0], points_mm=tuple(reversed(entities[0].points_mm)))
    proposed = (replace(sketches[0], entities=(source,)), *sketches[1:])
    root = PolylineTopologyMap(source.entity_id, (2, 1, 0), 3, False)
    predicted, maps = predict_chain_reorder(
        sketches,
        proposed,
        tuple(reversed(arrays)),
        ((refs[0], refs[1]), (refs[1], refs[2])),
        {(refs[0].sketch_id, refs[0].entity_id): root},
    )
    for sketch, old, ref in zip(predicted, entities, refs, strict=True):
        assert isinstance(sketch.entities[0], PolylineEntity)
        assert sketch.entities[0].points_mm == tuple(reversed(old.points_mm))
        assert maps[(ref.sketch_id, ref.entity_id)].old_to_new == (2, 1, 0)


def test_chain_plans_unchanged_replacement_only_when_anchor_is_proven() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    source, replacement, target, descendant = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(4)
    )
    a = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (source,),
        (ArrayMember(source, target, 0, 1, replacement=ArrayReplacement(replacement)),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (target,),
        (ArrayMember(target, descendant, 0, 1),),
    )
    sources = frozenset(((sketch, source.entity_id),))
    with pytest.raises(ValueError, match="替换|关联|重绑定"):
        simple_array_reorder_chain((a, b), sources, stable_anchor_sources=sources)
    assert simple_array_reorder_chain(
        (b, a), sources, stable_anchor_sources=sources, allow_unchanged_replacements=True
    ) == ((source, target), (target, descendant))
    with pytest.raises(ValueError, match="替换|关联|重绑定"):
        simple_array_reorder_chain((a, b), sources, allow_unchanged_replacements=True)


def test_predict_chain_validates_unchanged_replacement_and_descendant() -> None:
    from dataclasses import replace

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
        predict_chain_reorder,
    )
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    entities = tuple(
        PolylineEntity(
            uuid4().hex, ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)), closed=True
        )
        for x, y in ((0, 0), (30, 0), (0, 20), (0, 40))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    b = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[2],), (ArrayMember(refs[2], refs[3], 1, 0),)
    )
    changed = replace(
        entities[0], points_mm=(entities[0].points_mm[0], *reversed(entities[0].points_mm[1:]))
    )
    revised = replace(sketch, entities=(changed, *entities[1:]))
    mapping = PolylineTopologyMap(entities[0].entity_id, (0, 3, 2, 1), 4, True)
    predicted, maps = predict_chain_reorder(
        (sketch,),
        (revised,),
        (a, b),
        ((refs[0], refs[2]), (refs[2], refs[3])),
        {(sketch.sketch_id, changed.entity_id): mapping},
        allow_unchanged_replacements=True,
    )
    assert predicted == (revised,)
    assert set(maps) == {(sketch.sketch_id, changed.entity_id)}
    altered = replace(
        entities[1], points_mm=(entities[1].points_mm[0], (41, 0), *entities[1].points_mm[2:])
    )
    untrusted = replace(revised, entities=(changed, altered, *entities[2:]))
    with pytest.raises(ValueError, match="保持不变"):
        predict_chain_reorder(
            (sketch,),
            (untrusted,),
            (a, b),
            ((refs[0], refs[2]), (refs[2], refs[3])),
            {(sketch.sketch_id, changed.entity_id): mapping},
            allow_unchanged_replacements=True,
        )


def test_chain_plans_reordered_replacement_source_and_descendant() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    anchor, replacement, target, descendant = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(4)
    )
    a = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (anchor,),
        (ArrayMember(anchor, target, 0, 1, replacement=ArrayReplacement(replacement)),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (target,),
        (ArrayMember(target, descendant, 0, 1),),
    )
    source = frozenset(((sketch, replacement.entity_id),))
    with pytest.raises(ValueError, match="来源|替换|关联"):
        simple_array_reorder_chain(
            (a, b), source, stable_anchor_sources=source, allow_unchanged_replacements=True
        )
    assert simple_array_reorder_chain(
        (b, a),
        source,
        stable_anchor_sources=source,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
    ) == ((replacement, target), (target, descendant))
    with pytest.raises(ValueError, match="重绑定|替换"):
        simple_array_reorder_chain(
            (a, b), source, allow_unchanged_replacements=True, allow_reordered_replacements=True
        )


def test_chain_plans_generated_replacement_source_after_its_parent() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    root, replacement, anchor, target, descendant = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(5)
    )
    one = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (root,),
        (ArrayMember(root, replacement, 0, 1),),
    )
    two = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (anchor,),
        (ArrayMember(anchor, target, 0, 1, replacement=ArrayReplacement(replacement)),),
    )
    three = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (target,),
        (ArrayMember(target, descendant, 0, 1),),
    )
    sources = frozenset(((sketch, root.entity_id),))
    assert simple_array_reorder_chain(
        (three, two, one),
        sources,
        stable_anchor_sources=sources,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
    ) == ((root, replacement), (replacement, target), (target, descendant))


def test_predict_chain_uses_replacement_source_mapping_for_changed_output() -> None:
    from dataclasses import replace

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
        predict_chain_reorder,
    )
    from mycad.core.geometric_tolerance_topology import PolylineTopologyMap
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    entities = tuple(
        PolylineEntity(
            uuid4().hex, ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)), closed=True
        )
        for x, y in ((0, 0), (30, 0), (0, 20), (0, 40))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[2], 1, 0, replacement=ArrayReplacement(refs[1])),),
    )
    b = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[2],), (ArrayMember(refs[2], refs[3], 1, 0),)
    )
    replacement = replace(
        entities[1], points_mm=(entities[1].points_mm[0], *reversed(entities[1].points_mm[1:]))
    )
    revised = replace(sketch, entities=(entities[0], replacement, *entities[2:]))
    mapping = PolylineTopologyMap(replacement.entity_id, (0, 3, 2, 1), 4, True)
    predicted, maps = predict_chain_reorder(
        (sketch,),
        (revised,),
        (a, b),
        ((refs[1], refs[2]), (refs[2], refs[3])),
        {(sketch.sketch_id, replacement.entity_id): mapping},
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
    )
    for index in (2, 3):
        old, new = entities[index], predicted[0].entities[index]
        assert isinstance(new, PolylineEntity)
        assert new.points_mm == (old.points_mm[0], *reversed(old.points_mm[1:]))
        assert maps[(sketch.sketch_id, old.entity_id)].old_to_new == (0, 3, 2, 1)


def test_chain_plans_extra_output_and_its_descendant_with_stable_anchor() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    root, member, extra_source, extra, descendant = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(5)
    )
    a = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (root,),
        (ArrayMember(root, member, 0, 1),),
        extra_outputs=(ArrayExtraOutput(extra_source, extra, root, 0, 1),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (extra,),
        (ArrayMember(extra, descendant, 0, 1),),
    )
    sources = frozenset(((sketch, root.entity_id),))
    with pytest.raises(ValueError, match="额外|关联|重绑定"):
        simple_array_reorder_chain(
            (a, b),
            sources,
            stable_anchor_sources=sources,
            allow_unchanged_replacements=True,
            allow_reordered_replacements=True,
        )
    edges = simple_array_reorder_chain(
        (b, a),
        sources,
        stable_anchor_sources=sources,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
    )
    assert set(edges) == {(root, member), (root, extra), (extra, descendant)}
    assert edges.index((root, extra)) < edges.index((extra, descendant))
    with pytest.raises(ValueError, match="重绑定|关联"):
        simple_array_reorder_chain(
            (a, b),
            sources,
            allow_unchanged_replacements=True,
            allow_reordered_replacements=True,
            allow_extra_outputs=True,
        )


def test_chain_plans_extra_output_from_independent_geometry_source() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    root, member, extra_source, extra, descendant = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(5)
    )
    a = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (root,),
        (ArrayMember(root, member, 0, 1),),
        extra_outputs=(ArrayExtraOutput(extra_source, extra, root, 0, 1),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (extra,),
        (ArrayMember(extra, descendant, 0, 1),),
    )
    source = frozenset(((sketch, extra_source.entity_id),))
    edges = simple_array_reorder_chain(
        (b, a),
        source,
        stable_anchor_sources=source,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
    )
    assert edges == ((extra_source, extra), (extra, descendant))


@pytest.mark.parametrize("source_kind", ["anchor", "geometry"])
def test_predict_chain_distinguishes_extra_geometry_from_anchor(source_kind: str) -> None:
    from dataclasses import replace

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
        predict_chain_reorder,
    )
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        simple_array_reorder_chain,
    )
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    entities = tuple(
        PolylineEntity(
            uuid4().hex, ((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)), closed=True
        )
        for x, y in ((0, 0), (0, 20), (30, 0), (0, 20), (0, 40))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in entities)
    a = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        2,
        1,
        20,
        0,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 1, 0),),
        extra_outputs=(ArrayExtraOutput(refs[2], refs[3], refs[0], 1, 0),),
    )
    b = AssociativeRectArray(
        uuid4().hex, sketch.frame, 2, 1, 20, 0, (refs[3],), (ArrayMember(refs[3], refs[4], 1, 0),)
    )
    root_index = 0 if source_kind == "anchor" else 2
    old = entities[root_index]
    changed = replace(old, points_mm=(old.points_mm[0], *reversed(old.points_mm[1:])))
    revised = replace(
        sketch,
        entities=tuple(changed if item.entity_id == old.entity_id else item for item in entities),
    )
    mapping = PolylineTopologyMap(old.entity_id, (0, 3, 2, 1), 4, True)
    source = frozenset(((sketch.sketch_id, old.entity_id),))
    edges = simple_array_reorder_chain(
        (b, a),
        source,
        stable_anchor_sources=source,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
    )
    predicted, maps = predict_chain_reorder(
        (sketch,),
        (revised,),
        (a, b),
        edges,
        {(sketch.sketch_id, old.entity_id): mapping},
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
    )
    for index in (3, 4):
        result = predicted[0].entities[index]
        assert isinstance(result, PolylineEntity)
        if source_kind == "anchor":
            assert result == entities[index]
            assert (sketch.sketch_id, result.entity_id) not in maps
        else:
            assert result.points_mm == (
                entities[index].points_mm[0],
                *reversed(entities[index].points_mm[1:]),
            )
            assert maps[(sketch.sketch_id, result.entity_id)].old_to_new == mapping.old_to_new


def test_chain_does_not_bind_unrelated_extra_outputs_to_selected_source() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    anchor, member, source_a, target_a, source_b, target_b = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(6)
    )
    array = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (anchor,),
        (ArrayMember(anchor, member, 0, 1),),
        extra_outputs=(
            ArrayExtraOutput(source_a, target_a, anchor, 0, 1),
            ArrayExtraOutput(source_b, target_b, anchor, 0, 1),
        ),
    )
    source = frozenset(((sketch, source_a.entity_id),))
    assert simple_array_reorder_chain(
        (array,),
        source,
        stable_anchor_sources=source,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
    ) == ((source_a, target_a),)


def test_chain_plans_simultaneous_stable_anchor_and_replacement_reorders() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    anchor, replacement, target, descendant = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(4)
    )
    a = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (anchor,),
        (ArrayMember(anchor, target, 0, 1, replacement=ArrayReplacement(replacement)),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (target,),
        (ArrayMember(target, descendant, 0, 1),),
    )
    sources = frozenset(((sketch, anchor.entity_id), (sketch, replacement.entity_id)))
    with pytest.raises(ValueError, match="重绑定|替换|关联"):
        simple_array_reorder_chain(
            (a, b),
            sources,
            stable_anchor_sources=sources,
            allow_unchanged_replacements=True,
            allow_reordered_replacements=True,
            allow_extra_outputs=True,
        )
    assert simple_array_reorder_chain(
        (b, a),
        sources,
        stable_anchor_sources=sources,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
        allow_simultaneous_replacements=True,
    ) == ((replacement, target), (target, descendant))
    with pytest.raises(ValueError, match="重绑定|替换|关联"):
        simple_array_reorder_chain(
            (a, b),
            sources,
            stable_anchor_sources=frozenset(((sketch, anchor.entity_id),)),
            allow_unchanged_replacements=True,
            allow_reordered_replacements=True,
            allow_extra_outputs=True,
            allow_simultaneous_replacements=True,
        )


def test_chain_defers_simultaneously_changed_anchor_until_generated_replacement_is_ready() -> None:
    from itertools import permutations

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    root, replacement, anchor, target, descendant = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(5)
    )
    first = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (root,),
        (ArrayMember(root, replacement, 0, 1),),
    )
    second = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (anchor,),
        (ArrayMember(anchor, target, 0, 1, replacement=ArrayReplacement(replacement)),),
    )
    third = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (target,),
        (ArrayMember(target, descendant, 0, 1),),
    )
    sources = frozenset(((sketch, root.entity_id), (sketch, anchor.entity_id)))
    with pytest.raises(ValueError, match="重复|顺序"):
        simple_array_reorder_chain(
            (second, third, first),
            sources,
            stable_anchor_sources=sources,
            allow_unchanged_replacements=True,
            allow_reordered_replacements=True,
            allow_extra_outputs=True,
            allow_simultaneous_replacements=True,
        )
    edges = simple_array_reorder_chain(
        (second, third, first),
        sources,
        stable_anchor_sources=sources,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
        allow_simultaneous_replacements=True,
        defer_affected_dependencies=True,
    )
    assert edges == ((root, replacement), (replacement, target), (target, descendant))
    for arrays in permutations((first, second, third)):
        ordered = simple_array_reorder_chain(
            arrays,
            sources,
            stable_anchor_sources=sources,
            allow_unchanged_replacements=True,
            allow_reordered_replacements=True,
            allow_extra_outputs=True,
            allow_simultaneous_replacements=True,
            defer_affected_dependencies=True,
        )
        assert ordered == ((root, replacement), (replacement, target), (target, descendant))


def test_chain_plans_extra_output_using_member_of_same_array() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    root, member, extra, descendant = (ArrayEntityRef(sketch, uuid4().hex) for _ in range(4))
    a = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (root,),
        (ArrayMember(root, member, 0, 1),),
        extra_outputs=(ArrayExtraOutput(member, extra, root, 0, 1),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (extra,),
        (ArrayMember(extra, descendant, 0, 1),),
    )
    sources = frozenset(((sketch, root.entity_id),))
    edges = simple_array_reorder_chain(
        (b, a),
        sources,
        stable_anchor_sources=sources,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
        allow_simultaneous_replacements=True,
        defer_affected_dependencies=True,
    )
    assert edges == ((root, member), (member, extra), (extra, descendant))


def test_chain_plans_replacement_using_member_of_same_array() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    root, anchor, replacement, target, descendant = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(5)
    )
    a = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (root, anchor),
        (
            ArrayMember(root, replacement, 0, 1),
            ArrayMember(anchor, target, 0, 1, replacement=ArrayReplacement(replacement)),
        ),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (target,),
        (ArrayMember(target, descendant, 0, 1),),
    )
    sources = frozenset(((sketch, root.entity_id),))
    edges = simple_array_reorder_chain(
        (b, a),
        sources,
        stable_anchor_sources=sources,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
        allow_simultaneous_replacements=True,
        defer_affected_dependencies=True,
    )
    assert edges == ((root, replacement), (replacement, target), (target, descendant))


def test_internal_reorder_dependency_detects_extra_output_as_source() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import has_internal_reorder_dependents
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    root, member, extra, second_extra = (ArrayEntityRef(sketch, uuid4().hex) for _ in range(4))
    array = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (root,),
        (ArrayMember(root, member, 0, 1),),
        extra_outputs=(
            ArrayExtraOutput(root, extra, root, 0, 1),
            ArrayExtraOutput(extra, second_extra, root, 0, 1),
        ),
    )
    assert has_internal_reorder_dependents((array,), ((root, extra),))


def test_chain_plans_extra_output_derived_from_extra_output_in_same_array() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    root, member, first_extra, second_extra, descendant = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(5)
    )
    a = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (root,),
        (ArrayMember(root, member, 0, 1),),
        extra_outputs=(
            ArrayExtraOutput(root, first_extra, root, 0, 1),
            ArrayExtraOutput(first_extra, second_extra, root, 0, 1),
        ),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (second_extra,),
        (ArrayMember(second_extra, descendant, 0, 1),),
    )
    sources = frozenset(((sketch, root.entity_id),))
    edges = simple_array_reorder_chain(
        (b, a),
        sources,
        stable_anchor_sources=sources,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
        allow_simultaneous_replacements=True,
        defer_affected_dependencies=True,
    )
    assert edges == (
        (root, member),
        (root, first_extra),
        (first_extra, second_extra),
        (second_extra, descendant),
    )


def test_chain_can_reorder_replacement_when_unrelated_extra_output_exists() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    anchor, replacement, target, extra_source, extra, descendant = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(6)
    )
    a = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (anchor,),
        (ArrayMember(anchor, target, 0, 1, replacement=ArrayReplacement(replacement)),),
        extra_outputs=(ArrayExtraOutput(extra_source, extra, anchor, 0, 1),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (target,),
        (ArrayMember(target, descendant, 0, 1),),
    )
    sources = frozenset(((sketch, replacement.entity_id),))
    with pytest.raises(ValueError, match="替换|关联|重绑定"):
        simple_array_reorder_chain(
            (a, b),
            sources,
            stable_anchor_sources=sources,
            allow_unchanged_replacements=True,
            allow_reordered_replacements=True,
            allow_extra_outputs=True,
            allow_simultaneous_replacements=True,
            defer_affected_dependencies=True,
        )
    assert simple_array_reorder_chain(
        (b, a),
        sources,
        stable_anchor_sources=sources,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
        allow_simultaneous_replacements=True,
        defer_affected_dependencies=True,
        allow_mixed_replacement_extras=True,
    ) == ((replacement, target), (target, descendant))


def test_chain_uses_same_geometry_source_for_replacement_and_extra_output() -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    anchor, source, member, extra, descendant = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(5)
    )
    a = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (anchor,),
        (ArrayMember(anchor, member, 0, 1, replacement=ArrayReplacement(source)),),
        extra_outputs=(ArrayExtraOutput(source, extra, anchor, 0, 1),),
    )
    b = AssociativeRectArray(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        1,
        2,
        0,
        10,
        (member,),
        (ArrayMember(member, descendant, 0, 1),),
    )
    sources = frozenset(((sketch, source.entity_id),))
    edges = simple_array_reorder_chain(
        (b, a),
        sources,
        stable_anchor_sources=sources,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
        allow_simultaneous_replacements=True,
        defer_affected_dependencies=True,
        allow_mixed_replacement_extras=True,
    )
    assert set(edges) == {(source, member), (source, extra), (member, descendant)}


def test_chain_orders_converging_generated_anchor_and_replacement_branches() -> None:
    from itertools import permutations

    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    root_a, middle, anchor, root_b, replacement, target, descendant = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(7)
    )

    def array(
        source: ArrayEntityRef,
        destination: ArrayEntityRef,
        *,
        geometry: ArrayEntityRef | None = None,
    ) -> AssociativeRectArray:
        return AssociativeRectArray(
            uuid4().hex,
            WorkPlaneFrame.xy(),
            1,
            2,
            0,
            10,
            (source,),
            (
                ArrayMember(
                    source,
                    destination,
                    0,
                    1,
                    replacement=ArrayReplacement(geometry) if geometry is not None else None,
                ),
            ),
        )

    arrays = (
        array(root_a, middle),
        array(middle, anchor),
        array(root_b, replacement),
        array(anchor, target, geometry=replacement),
        array(target, descendant),
    )
    sources = frozenset(((sketch, root_a.entity_id), (sketch, root_b.entity_id)))
    expected = {
        (root_a, middle),
        (middle, anchor),
        (root_b, replacement),
        (replacement, target),
        (target, descendant),
    }
    for ordered in permutations(arrays):
        edges = simple_array_reorder_chain(
            ordered,
            sources,
            stable_anchor_sources=sources,
            allow_stable_bases=True,
            allow_base_rebinding=True,
            allow_unchanged_replacements=True,
            allow_reordered_replacements=True,
            allow_extra_outputs=True,
            allow_simultaneous_replacements=True,
            defer_affected_dependencies=True,
            allow_mixed_replacement_extras=True,
        )
        assert set(edges) == expected
        assert (
            edges.index((root_a, middle))
            < edges.index((middle, anchor))
            < edges.index((replacement, target))
        )
        assert (
            edges.index((root_b, replacement))
            < edges.index((replacement, target))
            < edges.index((target, descendant))
        )


def test_converging_chain_defers_dynamic_base_and_accepts_proven_unaffected_base() -> None:
    from itertools import permutations

    from mycad.core.associative_array import (
        ArrayBasePoint,
        ArrayEntityRef,
        ArrayMember,
        ArrayReplacement,
        AssociativeRectArray,
    )
    from mycad.core.geometric_tolerance_topology import simple_array_reorder_chain
    from mycad.core.sketch import WorkPlaneFrame

    sketch = uuid4().hex
    root_a, middle, anchor, root_b, replacement, target, descendant = (
        ArrayEntityRef(sketch, uuid4().hex) for _ in range(7)
    )

    def array(
        source: ArrayEntityRef,
        destination: ArrayEntityRef,
        *,
        geometry: ArrayEntityRef | None = None,
        base: ArrayBasePoint | None = None,
    ) -> AssociativeRectArray:
        return AssociativeRectArray(
            uuid4().hex,
            WorkPlaneFrame.xy(),
            1,
            2,
            0,
            10,
            (source,),
            (
                ArrayMember(
                    source,
                    destination,
                    0,
                    1,
                    replacement=ArrayReplacement(geometry) if geometry is not None else None,
                ),
            ),
            base_point=base,
        )

    dynamic = ArrayBasePoint(
        source=anchor, reference=SketchGeometryReference(anchor.entity_id, "vertex", 1)
    )
    first, second, third = array(root_a, middle), array(middle, anchor), array(root_b, replacement)
    joined, last = (
        array(anchor, target, geometry=replacement, base=dynamic),
        array(target, descendant),
    )
    arrays = (first, second, third, joined, last)
    sources = frozenset(((sketch, root_a.entity_id), (sketch, root_b.entity_id)))
    options = {
        "stable_anchor_sources": sources,
        "allow_stable_bases": True,
        "allow_base_rebinding": True,
        "allow_unchanged_replacements": True,
        "allow_reordered_replacements": True,
        "allow_extra_outputs": True,
        "allow_simultaneous_replacements": True,
        "defer_affected_dependencies": True,
        "allow_mixed_replacement_extras": True,
    }
    for ordered in permutations(arrays):
        edges = simple_array_reorder_chain(
            ordered, sources, known_stable_base_arrays=frozenset(), **options
        )
        assert edges.index((middle, anchor)) < edges.index((replacement, target))
        assert edges.index((root_b, replacement)) < edges.index((replacement, target))
    one_source = frozenset(((sketch, root_b.entity_id),))
    with pytest.raises(ValueError, match="基点|关联|重绑定"):
        simple_array_reorder_chain(
            arrays,
            one_source,
            stable_anchor_sources=one_source,
            allow_stable_bases=True,
            allow_base_rebinding=True,
            allow_unchanged_replacements=True,
            allow_reordered_replacements=True,
            allow_extra_outputs=True,
            allow_simultaneous_replacements=True,
            defer_affected_dependencies=True,
        )
    edges = simple_array_reorder_chain(
        arrays,
        one_source,
        stable_anchor_sources=one_source,
        known_stable_base_arrays=frozenset((joined.array_id,)),
        allow_stable_bases=True,
        allow_base_rebinding=True,
        allow_unchanged_replacements=True,
        allow_reordered_replacements=True,
        allow_extra_outputs=True,
        allow_simultaneous_replacements=True,
        defer_affected_dependencies=True,
    )
    assert edges == ((root_b, replacement), (replacement, target), (target, descendant))
    # A proof for an unchanged base cannot stand in for an affected, moving anchor.
    with pytest.raises(ValueError, match="锚点|关联|重绑定"):
        simple_array_reorder_chain(
            arrays,
            sources,
            stable_anchor_sources=one_source,
            known_stable_base_arrays=frozenset((joined.array_id,)),
            allow_stable_bases=True,
            allow_base_rebinding=True,
            allow_unchanged_replacements=True,
            allow_reordered_replacements=True,
            allow_extra_outputs=True,
            allow_simultaneous_replacements=True,
            defer_affected_dependencies=True,
        )


def test_array_tangency_rebinding_requires_proven_same_oriented_segment() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        rebind_proven_array_tangencies,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity, Sketch, WorkPlaneFrame

    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(source.sketch_id, polyline.entity_id, 0),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    reordered = replace(polyline, points_mm=(*polyline.points_mm[1:], polyline.points_mm[0]))
    revised = replace(source, entities=(reordered,))
    mapping = PolylineTopologyMap(polyline.entity_id, (3, 0, 1, 2), 4, True)
    rebound = rebind_proven_array_tangencies(
        (source, other),
        (revised, other),
        (relation,),
        {(source.sketch_id, polyline.entity_id): mapping},
    )
    assert rebound == (replace(relation, first=replace(relation.first, segment_index=3)),)

    reversed_curve = replace(polyline, points_mm=tuple(reversed(polyline.points_mm)))
    reverse_map = PolylineTopologyMap(polyline.entity_id, (3, 2, 1, 0), 4, True)
    with pytest.raises(ValueError, match="相切"):
        rebind_proven_array_tangencies(
            (source, other),
            (replace(source, entities=(reversed_curve,)), other),
            (relation,),
            {(source.sketch_id, polyline.entity_id): reverse_map},
        )
    with pytest.raises(ValueError):
        rebind_proven_array_tangencies(
            (source, other),
            (revised, other),
            (relation,),
            {(source.sketch_id, polyline.entity_id): reverse_map},
        )
    with pytest.raises(ValueError, match="相切"):
        rebind_proven_array_tangencies(
            (source, other),
            (replace(source, entities=(replace(reordered, construction=True),)), other),
            (relation,),
            {(source.sketch_id, polyline.entity_id): mapping},
        )
    with pytest.raises(ValueError, match="相切"):
        rebind_proven_array_tangencies(
            (source, other),
            (revised, replace(other, entities=(replace(circle, radius_mm=3),))),
            (relation,),
            {(source.sketch_id, polyline.entity_id): mapping},
        )


def test_array_tangency_reverse_preserves_contact_branch_and_endpoint() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        rebind_proven_array_tangencies,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity, Sketch, WorkPlaneFrame

    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), closed=False)
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(source.sketch_id, curve.entity_id, 0),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
        first_endpoint="start",
    )
    reversed_curve = replace(curve, points_mm=tuple(reversed(curve.points_mm)))
    revised = replace(source, entities=(reversed_curve,))
    mapping = PolylineTopologyMap(curve.entity_id, (2, 1, 0), 3, False)
    rebound = rebind_proven_array_tangencies(
        (source, other),
        (revised, other),
        (relation,),
        {(source.sketch_id, curve.entity_id): mapping},
        allow_reversed_segments=True,
    )
    assert rebound == (
        replace(
            relation,
            first=replace(relation.first, segment_index=1),
            first_endpoint="end",
            branch="line_right",
        ),
    )


def test_array_tangency_reverse_arc_keeps_branch_and_changes_endpoint() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        rebind_proven_array_tangencies,
    )
    from mycad.core.sketch import CircleEntity, PolylineEntity, Sketch, WorkPlaneFrame

    curve = PolylineEntity(uuid4().hex, ((0, 0), (10, 0)), bulges=(1.0,))
    circle = CircleEntity(uuid4().hex, (5, 10), 5)
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(source.sketch_id, curve.entity_id, 0),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "external",
        first_endpoint="start",
    )
    revised = replace(
        source,
        entities=(replace(curve, points_mm=tuple(reversed(curve.points_mm)), bulges=(-1.0,)),),
    )
    mapping = PolylineTopologyMap(curve.entity_id, (1, 0), 2, False)
    rebound = rebind_proven_array_tangencies(
        (source, other),
        (revised, other),
        (relation,),
        {(source.sketch_id, curve.entity_id): mapping},
        allow_reversed_segments=True,
    )
    assert rebound == (replace(relation, first_endpoint="end"),)
    incorrect = replace(
        source, entities=(replace(curve, points_mm=tuple(reversed(curve.points_mm))),)
    )
    with pytest.raises(ValueError, match="曲率"):
        rebind_proven_array_tangencies(
            (source, other),
            (incorrect, other),
            (relation,),
            {(source.sketch_id, curve.entity_id): mapping},
            allow_reversed_segments=True,
        )


def test_array_tangency_reverse_both_segments_toggles_only_line_side() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        rebind_proven_array_tangencies,
    )
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    line = PolylineEntity(uuid4().hex, ((0, 0), (0, 10)))
    arc = PolylineEntity(uuid4().hex, ((0, 0), (10, 0)), bulges=(1.0,))
    a, b = (
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)),
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,)),
    )
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(a.sketch_id, line.entity_id, 0),
        CrossSketchRef(b.sketch_id, arc.entity_id, 0),
        "line_left",
        first_endpoint="start",
        second_endpoint="start",
    )
    new_line = replace(line, points_mm=tuple(reversed(line.points_mm)))
    new_arc = replace(arc, points_mm=tuple(reversed(arc.points_mm)), bulges=(-1.0,))
    maps = {
        (a.sketch_id, line.entity_id): PolylineTopologyMap(line.entity_id, (1, 0), 2, False),
        (b.sketch_id, arc.entity_id): PolylineTopologyMap(arc.entity_id, (1, 0), 2, False),
    }
    rebound = rebind_proven_array_tangencies(
        (a, b),
        (replace(a, entities=(new_line,)), replace(b, entities=(new_arc,))),
        (relation,),
        maps,
        allow_reversed_segments=True,
    )
    assert rebound == (
        replace(relation, first_endpoint="end", second_endpoint="end", branch="line_right"),
    )
