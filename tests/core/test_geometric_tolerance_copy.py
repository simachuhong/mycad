# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Copying a selection remaps internal geometric annotation references."""

from uuid import uuid4

import pytest

from mycad.core.geometric_tolerance import (
    DatumAttachment,
    DatumIdentifier,
    DatumReference,
    FeatureControlFrame,
    ToleranceRow,
)
from mycad.core.geometric_tolerance_copy import copy_geometric_annotations
from mycad.core.sketch_constraints import SketchGeometryReference


def test_copy_surface_indication_follows_mapped_and_external_target() -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication
    from mycad.core.geometric_tolerance_geometry import surface_indication_geometry

    source_sketch, source_entity, target_sketch, target_entity = (uuid4().hex for _ in range(4))
    attachment = DatumAttachment(
        source_sketch, SketchGeometryReference(source_entity, "geometry"), 0.5
    )
    indication = SurfaceIndication((5, 5), (10, 5), 0.5, ((3, 3),))
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 20), (0, 0), attachment=attachment, surface_indication=indication
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_attachment=attachment,
        surface_indication=indication,
    )
    for mapping, preserve, expected_target in (
        ({(source_sketch, source_entity): target_entity}, False, (3, 4)),
        ({}, True, (0, 0)),
        ({}, False, (3, 4)),
    ):
        frames, datums = copy_geometric_annotations(
            (frame,),
            (datum,),
            mapping,
            target_sketch,
            (3, 4),
            {datum.datum_id: "B"},
            preserve_external=preserve,
        )
        assert frames[0].leader_target_mm == expected_target
        assert datums[0].target_mm == expected_target
        assert frames[0].surface_indication == datums[0].surface_indication == indication
        reference, _, _ = surface_indication_geometry(expected_target, indication)
        assert reference[0] == (expected_target[0] + 5, expected_target[1] + 5)
        if mapping:
            assert (
                datums[0].attachment is not None
                and datums[0].attachment.reference.entity_id == target_entity
            )
        elif preserve:
            assert datums[0].attachment == attachment
        else:
            assert datums[0].attachment is None


@pytest.mark.parametrize("mode", ["external", "mapped", "detached"])
def test_copy_normal_datum_tracks_copied_or_stationary_target(mode: str) -> None:
    source_sketch, source_entity, target_sketch, target_entity = (uuid4().hex for _ in range(4))
    attachment = DatumAttachment(
        source_sketch, SketchGeometryReference(source_entity, "geometry"), 0.5
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (10, 0),
        attachment=attachment,
        leader_offsets=((-3, -4), (-10, -17)),
        leader_auto_normal=True,
    )
    mapping = {(source_sketch, source_entity): target_entity} if mode == "mapped" else {}
    _, datums = copy_geometric_annotations(
        (),
        (datum,),
        mapping,
        target_sketch,
        (0, -30),
        {datum.datum_id: "B"},
        preserve_external=mode == "external",
    )
    copied = datums[0]
    expected = ((17, 16), (10, 3)) if mode == "external" else ((17, -14), (10, -27))
    vertices = tuple(
        (copied.position_mm[0] + x, copied.position_mm[1] + y) for x, y in copied.leader_offsets
    )
    assert vertices == expected
    assert copied.leader_auto_normal == (mode != "detached")
    assert copied.target_mm == ((10, 0) if mode == "external" else (10, -30))


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_cross_document_copy_releases_surface_normal_if_target_not_copied(owner: str) -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    source_sketch, source_entity, target_sketch = (uuid4().hex for _ in range(3))
    attachment = DatumAttachment(
        source_sketch, SketchGeometryReference(source_entity, "geometry"), 0.5
    )
    surface = SurfaceIndication((5, 8), (10, 8), 0.5, ((0, 3),), auto_normal=True)
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 20), (10, 0), attachment=attachment, surface_indication=surface
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(10, 0),
        leader_attachment=attachment,
        surface_indication=surface,
    )
    frames, datums = copy_geometric_annotations(
        (frame,) if owner == "frame" else (),
        (datum,) if owner == "datum" else (),
        {},
        target_sketch,
        (3, 4),
        {datum.datum_id: "B"} if owner == "datum" else {},
        preserve_external=False,
    )
    copied = datums[0] if owner == "datum" else frames[0]
    assert copied.surface_indication is not None
    assert not copied.surface_indication.auto_normal
    assert copied.surface_indication.leader_offsets_mm == ((0, 3),)


@pytest.mark.parametrize("mode", ["external", "mapped", "detached"])
def test_copy_frame_normal_tracks_copied_or_stationary_target(mode: str) -> None:
    source_sketch, source_entity, target_sketch, target_entity = (uuid4().hex for _ in range(4))
    attachment = DatumAttachment(
        source_sketch, SketchGeometryReference(source_entity, "geometry"), 0.5
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(10, 0),
        leader_offsets=((-3, -4), (-10, -17)),
        leader_attachment=attachment,
        leader_auto_normal=True,
    )
    mapping = {(source_sketch, source_entity): target_entity} if mode == "mapped" else {}
    frames, _ = copy_geometric_annotations(
        (frame,), (), mapping, target_sketch, (0, -30), {}, preserve_external=mode == "external"
    )
    copied = frames[0]
    vertices = tuple(
        (copied.position_mm[0] + x, copied.position_mm[1] + y) for x, y in copied.leader_offsets
    )
    assert vertices == (((17, 16), (10, 3)) if mode == "external" else ((17, -14), (10, -27)))
    assert copied.leader_auto_normal == (mode != "detached")
    assert copied.leader_target_mm == ((10, 0) if mode == "external" else (10, -30))


def test_copy_frame_translates_its_leader_with_it() -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_offsets=((-5, -5),),
    )
    frames, _ = copy_geometric_annotations(
        (frame,), (), {}, uuid4().hex, (2, 3), {}, preserve_external=True
    )
    assert frames[0].position_mm == (12, 13)
    assert frames[0].leader_target_mm == (2, 3)
    assert frames[0].leader_offsets == frame.leader_offsets


def test_copy_annotation_attachment_does_not_retain_unmapped_target() -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment

    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_annotation_attachment=AnnotationAttachment("frame", uuid4().hex, (0, 0)),
    )
    foreign, _ = copy_geometric_annotations(
        (frame,), (), {}, uuid4().hex, (2, 3), {}, preserve_external=False
    )
    assert foreign[0].leader_annotation_attachment is None
    assert foreign[0].leader_target_mm == (2, 3)
    local, _ = copy_geometric_annotations(
        (frame,), (), {}, uuid4().hex, (2, 3), {}, preserve_external=True
    )
    assert local[0].leader_annotation_attachment == frame.leader_annotation_attachment
    assert local[0].leader_target_mm == frame.leader_target_mm


def test_copy_annotation_links_to_copied_frame_and_dimensions() -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment

    source = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0))
    child = FeatureControlFrame(
        uuid4().hex,
        source.rows,
        (10, 10),
        leader_target_mm=(0, 0),
        leader_annotation_attachment=AnnotationAttachment("frame", source.frame_id, (0, 0)),
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (15, 15),
        (0, 0),
        annotation_attachment=AnnotationAttachment("frame", source.frame_id, (0, 0)),
    )
    copied_frames, copied_datums = copy_geometric_annotations(
        (source, child),
        (datum,),
        {},
        uuid4().hex,
        (2, 3),
        {datum.datum_id: "B"},
        preserve_external=False,
    )
    assert copied_frames[1].leader_annotation_attachment is not None
    assert copied_frames[1].leader_annotation_attachment.object_id == copied_frames[0].frame_id
    assert copied_datums[0].annotation_attachment is not None
    assert copied_datums[0].annotation_attachment.object_id == copied_frames[0].frame_id
    assert copied_datums[0].target_mm == (2, 3)


def test_copy_annotation_remaps_copied_dimensions() -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment

    old_sketch, new_sketch, old_dim, new_dim, old_ref, new_ref = (uuid4().hex for _ in range(6))
    first = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        annotation_attachment=AnnotationAttachment(
            "sketch_dimension", old_dim, (1, 2), old_sketch, anchor="text"
        ),
    )
    second = DatumIdentifier(
        uuid4().hex,
        "B",
        (10, 10),
        (0, 0),
        annotation_attachment=AnnotationAttachment("reference_dimension", old_ref, (0, 0)),
    )
    _, copied = copy_geometric_annotations(
        (),
        (first, second),
        {},
        new_sketch,
        (3, 4),
        {first.datum_id: "C", second.datum_id: "D"},
        preserve_external=False,
        dimension_mapping={(old_sketch, old_dim): new_dim},
        reference_mapping={old_ref: new_ref},
    )
    assert copied[0].annotation_attachment == AnnotationAttachment(
        "sketch_dimension", new_dim, (1, 2), new_sketch, anchor="text"
    )
    assert copied[1].annotation_attachment == AnnotationAttachment(
        "reference_dimension", new_ref, (0, 0)
    )
    assert all(item.target_mm == (3, 4) for item in copied)


def test_copy_dimension_attachment_uses_its_mapped_destination_sketch() -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment

    old_sketch, new_sketch, fallback_sketch, old_dim, new_dim = (uuid4().hex for _ in range(5))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (10, 10),
        (0, 0),
        annotation_attachment=AnnotationAttachment("sketch_dimension", old_dim, (1, 2), old_sketch),
    )
    _, copied = copy_geometric_annotations(
        (),
        (datum,),
        {},
        fallback_sketch,
        (3, 4),
        {datum.datum_id: "B"},
        preserve_external=False,
        dimension_mapping={(old_sketch, old_dim): new_dim},
        dimension_sketch_mapping={(old_sketch, old_dim): new_sketch},
    )
    assert copied[0].annotation_attachment == AnnotationAttachment(
        "sketch_dimension", new_dim, (1, 2), new_sketch
    )


def test_copy_frame_preserves_or_remaps_leader_attachment() -> None:
    sketch_id, entity_id, target_sketch, target_entity = (uuid4().hex for _ in range(4))
    attachment = DatumAttachment(sketch_id, SketchGeometryReference(entity_id, "start"))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_attachment=attachment,
    )
    local, _ = copy_geometric_annotations(
        (frame,), (), {}, target_sketch, (2, 3), {}, preserve_external=True
    )
    assert local[0].leader_target_mm == (0, 0)
    assert local[0].leader_attachment == attachment
    copied, _ = copy_geometric_annotations(
        (frame,),
        (),
        {(sketch_id, entity_id): target_entity},
        target_sketch,
        (2, 3),
        {},
        preserve_external=True,
    )
    assert copied[0].leader_target_mm == (2, 3)
    assert copied[0].leader_attachment is not None
    assert copied[0].leader_attachment.sketch_id == target_sketch
    assert copied[0].leader_attachment.reference.entity_id == target_entity
    foreign, _ = copy_geometric_annotations(
        (frame,), (), {}, target_sketch, (2, 3), {}, preserve_external=False
    )
    assert foreign[0].leader_target_mm == (2, 3)
    assert foreign[0].leader_attachment is None


def test_copy_geometry_datum_and_frame_remaps_all_internal_references() -> None:
    sketch_id, entity_id, target_sketch, target_entity = (uuid4().hex for _ in range(4))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 5),
        (2, 0),
        attachment=DatumAttachment(sketch_id, SketchGeometryReference(entity_id, "start")),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("A", datum.datum_id),)),),
        (4, 5),
    )
    frames, datums = copy_geometric_annotations(
        (frame,),
        (datum,),
        {(sketch_id, entity_id): target_entity},
        target_sketch,
        (10, 20),
        {datum.datum_id: "B"},
        preserve_external=True,
    )
    assert datums[0].datum_id != datum.datum_id
    assert datums[0].label == "B" and datums[0].target_mm == (12, 20)
    assert datums[0].attachment is not None
    assert datums[0].attachment.sketch_id == target_sketch
    assert datums[0].attachment.reference.entity_id == target_entity
    assert frames[0].rows[0].datums[0].datum_id == datums[0].datum_id
    assert frames[0].rows[0].datums[0].label == "B"
    assert frames[0].position_mm == (14, 25)


def test_copy_external_references_stay_local_or_detach_without_guessing() -> None:
    sketch_id, entity_id = uuid4().hex, uuid4().hex
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 5),
        (2, 0),
        attachment=DatumAttachment(sketch_id, SketchGeometryReference(entity_id, "start")),
    )
    external_id = uuid4().hex
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 1, datums=(DatumReference("C", external_id),)),),
        (4, 5),
    )
    local_frames, local_datums = copy_geometric_annotations(
        (frame,), (datum,), {}, uuid4().hex, (10, 20), {datum.datum_id: "B"}, preserve_external=True
    )
    assert local_datums[0].attachment == datum.attachment
    assert local_datums[0].target_mm == datum.target_mm
    assert local_frames[0].rows[0].datums[0].datum_id == external_id
    foreign_frames, foreign_datums = copy_geometric_annotations(
        (frame,),
        (datum,),
        {},
        uuid4().hex,
        (10, 20),
        {datum.datum_id: "B"},
        preserve_external=False,
    )
    assert foreign_datums[0].attachment is None
    assert foreign_datums[0].target_mm == (12, 20)
    assert foreign_frames[0].rows[0].datums[0].datum_id is None


def test_copy_detaches_normal_constraint_if_geometry_is_not_copied() -> None:
    sketch_id, entity_id = uuid4().hex, uuid4().hex
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (0, 5),
        (2, 0),
        attachment=DatumAttachment(sketch_id, SketchGeometryReference(entity_id, "start")),
        leader_offsets=((2, -3),),
        leader_auto_normal=True,
    )
    _, copied = copy_geometric_annotations(
        (), (datum,), {}, uuid4().hex, (10, 20), {datum.datum_id: "B"}, preserve_external=False
    )
    assert copied[0].attachment is None
    assert not copied[0].leader_auto_normal
    assert copied[0].leader_offsets == datum.leader_offsets


@pytest.mark.parametrize("mode", ["external", "mapped", "detached"])
def test_auto_route_copy_only_follows_copied_geometry(mode: str) -> None:
    source_sketch, source_entity, target_sketch, target_entity = (uuid4().hex for _ in range(4))
    attachment = DatumAttachment(source_sketch, SketchGeometryReference(source_entity, "start"))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 20),
        (0, 0),
        attachment=attachment,
        leader_offsets=((-20, -15),),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=2,
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_attachment=attachment,
        leader_offsets=((-20, -15),),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=2,
    )
    mapping = {(source_sketch, source_entity): target_entity} if mode == "mapped" else {}
    frames, datums = copy_geometric_annotations(
        (frame,),
        (datum,),
        mapping,
        target_sketch,
        (3, 4),
        {datum.datum_id: "B"},
        preserve_external=mode == "external",
    )
    assert frames[0].leader_auto_route == (mode != "detached")
    assert datums[0].leader_auto_route == (mode != "detached")
    assert frames[0].route_avoid_crossing == datums[0].route_avoid_crossing == (mode != "detached")
    assert frames[0].route_track_target == datums[0].route_track_target == (mode != "detached")
    assert (
        frames[0].route_algorithm_version
        == datums[0].route_algorithm_version
        == (1 if mode == "detached" else 2)
    )


@pytest.mark.parametrize("mode", ["external", "mapped", "detached"])
def test_surface_auto_route_copy_preserves_only_with_geometry(mode: str) -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    source_sketch, source_entity, target_sketch, target_entity = (uuid4().hex for _ in range(4))
    attachment = DatumAttachment(source_sketch, SketchGeometryReference(source_entity, "start"))
    surface = SurfaceIndication(
        (5, 8),
        (10, 8),
        0.5,
        ((0, 3),),
        auto_normal=True,
        auto_route=True,
        route_avoid_crossing=True,
    )
    datum = DatumIdentifier(
        uuid4().hex, "A", (20, 20), (0, 0), attachment=attachment, surface_indication=surface
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("flatness", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_attachment=attachment,
        surface_indication=surface,
    )
    mapping = {(source_sketch, source_entity): target_entity} if mode == "mapped" else {}
    frames, datums = copy_geometric_annotations(
        (frame,),
        (datum,),
        mapping,
        target_sketch,
        (3, 4),
        {datum.datum_id: "B"},
        preserve_external=mode == "external",
    )
    for copied in (frames[0], datums[0]):
        assert copied.surface_indication is not None
        assert copied.surface_indication.auto_route == (mode != "detached")
        assert copied.surface_indication.auto_normal == (mode != "detached")
        assert copied.surface_indication.route_avoid_crossing == (mode != "detached")


@pytest.mark.parametrize("mode", ["external", "mapped", "detached"])
def test_box_aware_datum_copy_rebinds_or_detaches(mode: str) -> None:
    from mycad.core.geometric_tolerance_geometry import datum_leader_path

    source_sketch, source_entity, target_sketch, target_entity = (uuid4().hex for _ in range(4))
    attachment = DatumAttachment(source_sketch, SketchGeometryReference(source_entity, "start"))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (-4, -3),
        (13, 7),
        attachment=attachment,
        leader_offsets=((10, 15), (6, 5)),
        leader_auto_normal=True,
        leader_auto_route=True,
        route_avoid_crossing=True,
        route_track_target=True,
        route_algorithm_version=3,
        layout_mode="shared",
        box_size_mm=(5.212759544541193, 5),
    )
    mapping = {(source_sketch, source_entity): target_entity} if mode == "mapped" else {}
    _, copied = copy_geometric_annotations(
        (),
        (datum,),
        mapping,
        target_sketch,
        (4, 3),
        {datum.datum_id: "B"},
        preserve_external=mode == "external",
    )
    item = copied[0]
    assert item.box_size_mm == datum.box_size_mm
    assert item.route_algorithm_version == (1 if mode == "detached" else 3)
    if mode == "external":
        path = datum_leader_path((0, 0, 5.212759544541193, -5), item.target_mm, item.leader_offsets)
        assert path[0][1] == pytest.approx(0)
        assert path[1] == pytest.approx((2, 2))
    elif mode == "mapped":
        assert item.leader_offsets == datum.leader_offsets
        assert item.target_mm == pytest.approx((17, 10))
    else:
        assert item.attachment is None and not item.leader_auto_route
