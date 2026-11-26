# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Repeated DXF imports need independent curve identities and intact references."""

from uuid import uuid4

import pytest

from mycad.core.geometric_tolerance import (
    DatumAttachment,
    DatumIdentifier,
    DatumReference,
    FeatureControlFrame,
    ToleranceRow,
)
from mycad.core.geometric_tolerance_topology import new_curve_point_identities
from mycad.core.sketch import PolylineEntity, Sketch, SplineEntity, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_repeated_curve_identity_remaps_constraints_and_annotations() -> None:
    from mycad.ui.dxf_import_identity import remap_colliding_curves

    identity = uuid4().hex
    ids = new_curve_point_identities(identity, "polyline", 3)
    curve = PolylineEntity(identity, ((0, 0), (10, 0), (10, 10)), point_ids=ids)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(identity, "segment", 0),),
        value=10,
        unit="mm",
        position_mm=(5, 2),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,), (dimension,))
    attachment = DatumAttachment(sketch.sketch_id, SketchGeometryReference(identity, "vertex", 0))
    datum = DatumIdentifier(uuid4().hex, "A", (4, 4), (0, 0), attachment=attachment)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (5, 5),
        leader_target_mm=(0, 0),
        leader_anchor_offset=(0, -2),
        leader_attachment=attachment,
    )
    new_sketch, datums, frames, count = remap_colliding_curves(
        sketch, (datum,), (frame,), (sketch,)
    )
    copied = new_sketch.entities[0]
    assert isinstance(copied, PolylineEntity)
    assert count == 1 and copied.entity_id != identity and set(copied.point_ids).isdisjoint(ids)
    assert copied.points_mm == curve.points_mm
    assert new_sketch.constraints[0].references[0].entity_id == copied.entity_id
    assert datums[0].attachment is not None
    assert datums[0].attachment.reference.entity_id == copied.entity_id
    assert frames[0].leader_attachment is not None
    assert frames[0].leader_attachment.reference.entity_id == copied.entity_id
    assert sketch.entities == (curve,) and datum.attachment == attachment


def test_repeated_datum_names_rebind_only_identified_references() -> None:
    from mycad.ui.dxf_import_identity import remap_datum_labels

    old = DatumIdentifier(uuid4().hex, "A", (0, 1), (0, 0))
    imported = DatumIdentifier(uuid4().hex, "A", (2, 1), (2, 0))
    another = DatumIdentifier(uuid4().hex, "A-2", (3, 1), (3, 0))
    rows = (
        ToleranceRow(
            "position",
            0.1,
            2,
            datums=(DatumReference("A", datum_id=imported.datum_id), DatumReference("A")),
        ),
    )
    frame = FeatureControlFrame(uuid4().hex, rows, (5, 5))
    datums, frames, changes = remap_datum_labels((imported, another), (frame,), (old,))
    assert [item.label for item in datums] == ["A-3", "A-2"]
    assert frames[0].rows[0].datums[0].label == "A-3"
    assert frames[0].rows[0].datums[0].datum_id == imported.datum_id
    assert frames[0].rows[0].datums[1].label == "A"
    assert changes == (("A", "A-3"),)


def test_repeated_spline_preserves_unrelated_curves_and_no_conflict_is_noop() -> None:
    from mycad.ui.dxf_import_identity import remap_colliding_curves

    identity = uuid4().hex
    spline = SplineEntity(
        identity,
        ((0, 0), (1, 0), (2, 1), (3, 1)),
        point_ids=new_curve_point_identities(identity, "spline", 4),
    )
    other_id = uuid4().hex
    other = PolylineEntity(
        other_id,
        ((0, 5), (1, 5)),
        point_ids=new_curve_point_identities(other_id, "polyline", 2),
    )
    incoming = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline, other))
    existing = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    result, _, _, count = remap_colliding_curves(incoming, (), (), (existing,))
    changed = result.entities[0]
    assert isinstance(changed, SplineEntity)
    assert (
        count == 1
        and changed.entity_id != identity
        and changed.control_points_mm == spline.control_points_mm
    )
    assert set(changed.point_ids).isdisjoint(spline.point_ids)
    assert result.entities[1] == other
    assert remap_colliding_curves(incoming, (), (), ()) == (incoming, (), (), 0)


def test_repeated_long_datum_name_is_valid_and_unique() -> None:
    from mycad.ui.dxf_import_identity import remap_datum_labels

    label = "基准" * 40
    existing = DatumIdentifier(uuid4().hex, label, (0, 1), (0, 0))
    incoming = DatumIdentifier(uuid4().hex, label, (0, 1), (0, 0))
    datums, _, changes = remap_datum_labels((incoming,), (), (existing,))
    assert len(datums[0].label) == 80 and datums[0].label.endswith("-2")
    assert changes == ((label, datums[0].label),)


def test_datum_rename_does_not_rewrite_inconsistent_reference() -> None:
    from mycad.ui.dxf_import_identity import remap_datum_labels

    existing = DatumIdentifier(uuid4().hex, "A", (0, 1), (0, 0))
    imported = DatumIdentifier(uuid4().hex, "A", (2, 1), (2, 0))
    invalid = DatumReference("A-2", datum_id=imported.datum_id)
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 2, datums=(invalid,)),), (5, 5)
    )
    with pytest.raises(ValueError, match="标签"):
        remap_datum_labels((imported,), (frame,), (existing,))
