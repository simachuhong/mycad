# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Geometric tolerance frames keep editable rows and ordered datums."""

from typing import cast
from uuid import uuid4

import pytest

from mycad.core.geometric_tolerance import (
    DatumIdentifier,
    DatumReference,
    FeatureControlFrame,
    ToleranceRow,
)


def test_surface_indication_arrow_size_roundtrip_and_legacy_default() -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    legacy = SurfaceIndication((5, 5), (10, 5), 0.5)
    assert "arrow_size_mm" not in legacy.to_mapping()
    sized = SurfaceIndication((5, 5), (10, 5), 0.5, arrow_size_mm=5)
    assert SurfaceIndication.from_mapping(sized.to_mapping()) == sized
    with pytest.raises(ValueError):
        SurfaceIndication((5, 5), (10, 5), 0.5, arrow_size_mm=0)


def test_surface_indication_geometry_tracks_target() -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication
    from mycad.core.geometric_tolerance_geometry import surface_indication_geometry

    indication = SurfaceIndication((4, 6), (12, 6), 0.5, ((2, 3),))
    reference, leader, landing = surface_indication_geometry((10, 20), indication)
    assert reference == ((14, 26), (22, 26))
    assert leader == ((14, 26), (12, 23), (10, 20))
    assert landing == (18, 26)


def test_surface_indication_roundtrip_on_datum_and_frame() -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier, SurfaceIndication

    surface = SurfaceIndication((4, 6), (12, 6), 0.5, ((2, 3),))
    datum = DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), surface_indication=surface)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        surface_indication=surface,
    )
    assert DatumIdentifier.from_mapping(datum.to_mapping()) == datum
    assert FeatureControlFrame.from_mapping(frame.to_mapping()) == frame
    assert (
        "surface_indication" not in DatumIdentifier(uuid4().hex, "B", (0, 0), (1, 1)).to_mapping()
    )
    with pytest.raises(ValueError):
        SurfaceIndication((1, 1), (1, 1), 0.5)
    with pytest.raises(ValueError):
        SurfaceIndication((0, 0), (1, 0), 1.5)
    with pytest.raises(ValueError):
        SurfaceIndication((0, 0), (1, 0), 0.5)
    with pytest.raises(ValueError):
        SurfaceIndication((5, 5), (10, 5), 0.5, ((0, 0),))
    with pytest.raises(ValueError):
        SurfaceIndication((5, 5), (10, 5), 0.5, ((5, 5),))


def test_datum_leader_offsets_roundtrip_and_legacy_default() -> None:
    datum = DatumIdentifier(
        uuid4().hex, "A", (10, 20), (0, 0), leader_offsets=((-5, -5), (-5, -15))
    )
    assert DatumIdentifier.from_mapping(datum.to_mapping()) == datum
    legacy = datum.to_mapping()
    del legacy["leader_offsets"]
    assert DatumIdentifier.from_mapping(legacy).leader_offsets == ()
    with pytest.raises(ValueError):
        DatumIdentifier(uuid4().hex, "A", (0, 0), (0, 0), leader_offsets=((float("nan"), 1),))


def test_datum_without_leader_roundtrips_and_rejects_association() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 2), leader_visible=False)
    assert DatumIdentifier.from_mapping(datum.to_mapping()) == datum
    assert DatumIdentifier.from_mapping(
        DatumIdentifier(uuid4().hex, "A", (0, 0), (0, 1)).to_mapping()
    ).leader_visible
    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "start"))
    with pytest.raises(ValueError):
        DatumIdentifier(
            uuid4().hex, "B", (0, 0), (0, 0), attachment=attachment, leader_visible=False
        )
    with pytest.raises(ValueError):
        DatumIdentifier(
            uuid4().hex, "B", (0, 0), (0, 0), leader_offsets=((1, 1),), leader_visible=False
        )


def test_ellipse_attachment_resolves_parameter_and_normal() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import (
        resolve_attachment_local,
        resolve_attachment_normal,
    )
    from mycad.core.sketch import EllipseEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    ellipse = EllipseEntity(uuid4().hex, (2, 3), 8, 4, rotation_deg=30)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (ellipse,))
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(ellipse.entity_id, "geometry"),
        0.125,
        curve_kind="ellipse",
    )
    assert DatumAttachment.from_mapping(attachment.to_mapping()) == attachment
    point = resolve_attachment_local(attachment, {ellipse.entity_id: ellipse})
    assert point == pytest.approx(ellipse.point_at(0.125))
    normal = resolve_attachment_normal(attachment, sketch, ellipse.point_at(0.125))
    assert normal is not None
    dx = ellipse.point_at(0.12501)[0] - ellipse.point_at(0.12499)[0]
    dy = ellipse.point_at(0.12501)[1] - ellipse.point_at(0.12499)[1]
    assert normal[0] * dx + normal[1] * dy == pytest.approx(0, abs=1e-9)


def test_datum_leader_path_exits_box_through_first_vertex() -> None:
    from mycad.core.geometric_tolerance_geometry import datum_leader_path

    path = datum_leader_path((0, 0, 4, 4), (10, -5), ((8, 2),))
    assert path == ((4, 2), (8, 2), (10, -5))
    assert datum_leader_path((0, 0, 4, 4), (2, 2), ()) == ()


def test_frame_leader_roundtrip_and_legacy_default() -> None:
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (10, 10),
        leader_target_mm=(0, 0),
        leader_offsets=((-5, -5),),
        leader_anchor_offset=(0, -3),
    )
    assert FeatureControlFrame.from_mapping(frame.to_mapping()) == frame
    legacy = frame.to_mapping()
    del legacy["leader_target_mm"]
    del legacy["leader_offsets"]
    del legacy["leader_anchor_offset"]
    assert FeatureControlFrame.from_mapping(legacy).leader_target_mm is None
    with pytest.raises(ValueError):
        FeatureControlFrame(uuid4().hex, frame.rows, (0, 0), leader_offsets=((1, 2),))


def test_annotation_attachment_roundtrip_and_exclusive_targets() -> None:
    from mycad.core.geometric_tolerance import AnnotationAttachment, DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    identity, sketch_id = uuid4().hex, uuid4().hex
    frame_ref = AnnotationAttachment("frame", identity, (1, -2))
    dimension_ref = AnnotationAttachment("sketch_dimension", identity, (0, 1), sketch_id)
    assert AnnotationAttachment.from_mapping(frame_ref.to_mapping()) == frame_ref
    assert AnnotationAttachment.from_mapping(dimension_ref.to_mapping()) == dimension_ref
    datum = DatumIdentifier(uuid4().hex, "A", (5, 5), (0, 0), annotation_attachment=frame_ref)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (5, 5),
        leader_target_mm=(0, 0),
        leader_annotation_attachment=dimension_ref,
    )
    assert DatumIdentifier.from_mapping(datum.to_mapping()) == datum
    assert FeatureControlFrame.from_mapping(frame.to_mapping()) == frame
    geometry = DatumAttachment(sketch_id, SketchGeometryReference(uuid4().hex, "start"))
    with pytest.raises(ValueError):
        DatumIdentifier(
            uuid4().hex, "B", (0, 0), (0, 0), attachment=geometry, annotation_attachment=frame_ref
        )
    with pytest.raises(ValueError):
        DatumIdentifier(
            uuid4().hex, "B", (0, 0), (0, 0), annotation_attachment=frame_ref, leader_visible=False
        )
    with pytest.raises(ValueError):
        AnnotationAttachment("sketch_dimension", identity, (0, 0))
    with pytest.raises(ValueError):
        AnnotationAttachment("frame", identity, (0, 0), sketch_id)


def test_frame_roundtrip_preserves_order_and_unresolved_datums() -> None:
    datum = DatumIdentifier(uuid4().hex, "A", (1, 2), (1, 0))
    rows = (
        ToleranceRow(
            "position",
            0.05,
            2,
            True,
            "M",
            (DatumReference("A", datum.datum_id), DatumReference("B")),
        ),
        ToleranceRow("flatness", 0.01, 3),
    )
    frame = FeatureControlFrame(uuid4().hex, rows, (10, 20))
    assert FeatureControlFrame.from_mapping(frame.to_mapping()) == frame
    assert DatumIdentifier.from_mapping(datum.to_mapping()) == datum
    assert frame.rows[0].datums[1].datum_id is None


def test_frame_text_style_reference_roundtrip_and_legacy_default() -> None:
    frame = FeatureControlFrame(
        uuid4().hex, (ToleranceRow("position", 0.1, 2),), (0, 0), text_style_id="iso-font"
    )
    assert FeatureControlFrame.from_mapping(frame.to_mapping()) == frame
    legacy = frame.to_mapping()
    del legacy["text_style_id"]
    assert FeatureControlFrame.from_mapping(legacy).text_style_id is None
    for invalid in ("", " ", "bad\nname"):
        with pytest.raises(ValueError):
            FeatureControlFrame(uuid4().hex, frame.rows, (0, 0), text_style_id=invalid)


def test_datum_text_style_reference_roundtrip_and_legacy_default() -> None:
    datum = DatumIdentifier(uuid4().hex, "A", (0, 0), (0, -5), text_style_id="iso-font")
    assert DatumIdentifier.from_mapping(datum.to_mapping()) == datum
    legacy = datum.to_mapping()
    del legacy["text_style_id"]
    assert DatumIdentifier.from_mapping(legacy).text_style_id is None
    for invalid in ("", " ", "bad\nname"):
        with pytest.raises(ValueError):
            DatumIdentifier(uuid4().hex, "A", (0, 0), (0, 0), text_style_id=invalid)


@pytest.mark.parametrize("symbol", ["unknown", "", "M"])
def test_rejects_unrecognized_characteristic(symbol: str) -> None:
    with pytest.raises(ValueError):
        ToleranceRow(symbol, 0.01, 2)


def test_rejects_invalid_rows_and_coordinates() -> None:
    with pytest.raises(ValueError):
        FeatureControlFrame(uuid4().hex, (), (0, 0))
    with pytest.raises(ValueError):
        ToleranceRow("position", float("nan"), 2)
    with pytest.raises(ValueError):
        DatumIdentifier(uuid4().hex, "", (1, 2), (0, 0))


def test_curve_attachment_resolves_circle_and_clockwise_arc() -> None:
    from uuid import uuid4

    import pytest

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.sketch import ArcEntity, CircleEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    circle = CircleEntity(uuid4().hex, (2, 3), 4)
    arc = ArcEntity(uuid4().hex, (2, 3), 4, 90, -90)
    circle_attachment = DatumAttachment(
        uuid4().hex, SketchGeometryReference(circle.entity_id, "geometry"), 0.25
    )
    arc_attachment = DatumAttachment(
        uuid4().hex, SketchGeometryReference(arc.entity_id, "geometry"), 0.5
    )
    assert resolve_attachment_local(circle_attachment, {circle.entity_id: circle}) == pytest.approx(
        (2, 7)
    )
    assert resolve_attachment_local(arc_attachment, {arc.entity_id: arc}) == pytest.approx(
        (2 + 2**0.5 * 2, 3 + 2**0.5 * 2)
    )
    assert DatumAttachment.from_mapping(arc_attachment.to_mapping()) == arc_attachment


def test_datum_pointer_triangle_has_tip_at_target_and_tracks_leader_direction() -> None:
    import pytest

    from mycad.core.geometric_tolerance_geometry import datum_triangle

    points = datum_triangle((10, 0), (0, 0), 2)
    assert points[0] == (0, 0)
    assert points[1] == pytest.approx((2, 0.8))
    assert points[2] == pytest.approx((2, -0.8))
    assert datum_triangle((0, 0), (0, 0), 2) == ()


def test_polyline_segment_attachment_resolves_curved_segment() -> None:
    from uuid import uuid4

    import pytest

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    polyline = PolylineEntity(uuid4().hex, ((0, 0), (2, 0)), bulges=(1.0,))
    attachment = DatumAttachment(
        uuid4().hex, SketchGeometryReference(polyline.entity_id, "segment", 0), 0.5, 1
    )
    assert resolve_attachment_local(attachment, {polyline.entity_id: polyline}) == pytest.approx(
        (1, -1)
    )


def test_rectangle_edge_attachment_has_explicit_kind_and_stable_parameter() -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 6))
    attachment = DatumAttachment(
        uuid4().hex,
        SketchGeometryReference(rectangle.entity_id, "segment", 1),
        0.5,
        4,
        segment_kind="rectangle",
    )
    assert DatumAttachment.from_mapping(attachment.to_mapping()) == attachment
    assert resolve_attachment_local(attachment, {rectangle.entity_id: rectangle}) == (10, 3)
    replacement = PolylineEntity(
        rectangle.entity_id, ((0, 0), (10, 0), (10, 6), (0, 6)), closed=True
    )
    assert resolve_attachment_local(attachment, {rectangle.entity_id: replacement}) is None


def test_spline_attachment_keeps_parameter_and_detects_topology_change() -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_local
    from mycad.core.sketch import SplineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference

    spline = SplineEntity(uuid4().hex, ((0, 0), (2, 5), (8, 5), (10, 0)))
    attachment = DatumAttachment(
        uuid4().hex,
        SketchGeometryReference(spline.entity_id, "geometry"),
        0.5,
        curve_kind="spline",
        control_count=4,
    )
    assert DatumAttachment.from_mapping(attachment.to_mapping()) == attachment
    assert resolve_attachment_local(attachment, {spline.entity_id: spline}) == spline.point_at(0.5)
    changed = SplineEntity(spline.entity_id, (*spline.control_points_mm, (12, 0)))
    assert resolve_attachment_local(attachment, {spline.entity_id: changed}) is None


def test_curve_attachment_rejects_overflow_as_value_error() -> None:
    from uuid import uuid4

    import pytest

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    with pytest.raises(ValueError):
        DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "geometry"), 10**1000)


def test_frame_rotation_rejects_integer_overflow_as_value_error() -> None:
    from uuid import uuid4

    import pytest

    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow

    with pytest.raises(ValueError):
        FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 1),), (0, 0), 10**1000)


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ((10.0, 5.0), (4.0, 5.0)),
        ((-10.0, 5.0), (0.0, 5.0)),
        ((2.0, 20.0), (2.0, 10.0)),
        ((2.0, -20.0), (2.0, 0.0)),
        ((10.0, 25.0), (4.0, 10.0)),
    ],
)
def test_datum_leader_starts_at_box_boundary(
    target: tuple[float, float], expected: tuple[float, float]
) -> None:
    from mycad.core.geometric_tolerance_geometry import datum_leader

    line = datum_leader((0, 0, 4, 10), target)
    assert line is not None
    assert line[0] == pytest.approx(expected)
    assert line[1] == target


@pytest.mark.parametrize(
    ("parameter", "expected"),
    [(0.0, (0.0, 1.0)), (0.5, (-(2**-0.5), 2**-0.5)), (1.0, (0.0, 1.0))],
)
def test_spline_normal_is_opt_in_for_history_compatibility(
    parameter: float, expected: tuple[float, float]
) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_normal
    from mycad.core.sketch import Sketch, SplineEntity, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    spline = SplineEntity(uuid4().hex, ((0, 0), (1, 0), (1, 1), (2, 1)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(spline.entity_id, "geometry"),
        parameter,
        curve_kind="spline",
        control_count=4,
    )
    target = spline.point_at(parameter)
    assert resolve_attachment_normal(attachment, sketch, target) is None
    assert resolve_attachment_normal(
        attachment, sketch, target, enable_spline=True
    ) == pytest.approx(expected)


@pytest.mark.parametrize("parameter", [0.1, 0.4, 0.8])
def test_multispan_spline_normal_matches_curve_tangent(parameter: float) -> None:
    import math
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_normal
    from mycad.core.sketch import Sketch, SplineEntity, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    spline = SplineEntity(uuid4().hex, ((0, 0), (1, 2), (3, 1), (4, 4), (7, 2), (8, 5)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(spline.entity_id, "geometry"),
        parameter,
        curve_kind="spline",
        control_count=6,
    )
    normal = resolve_attachment_normal(
        attachment, sketch, spline.point_at(parameter), enable_spline=True
    )
    assert normal is not None
    a, b = spline.point_at(parameter - 1e-6), spline.point_at(parameter + 1e-6)
    tangent = (b[0] - a[0], b[1] - a[1])
    assert (normal[0] * tangent[0] + normal[1] * tangent[1]) / math.hypot(
        *tangent
    ) == pytest.approx(0, abs=1e-8)


def test_surface_normal_constraint_requires_vertex_and_roundtrips() -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    with pytest.raises(ValueError, match="normal"):
        SurfaceIndication((5, 5), (10, 5), 0.5, auto_normal=True)
    surface = SurfaceIndication((5, 5), (10, 5), 0.5, ((2, 2),), auto_normal=True)
    assert SurfaceIndication.from_mapping(surface.to_mapping()) == surface
    legacy = SurfaceIndication((5, 5), (10, 5), 0.5, ((2, 2),))
    assert "auto_normal" not in legacy.to_mapping()
    assert not SurfaceIndication.from_mapping(legacy.to_mapping()).auto_normal


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_surface_normal_requires_geometry_attachment(owner: str) -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import (
        DatumIdentifier,
        FeatureControlFrame,
        SurfaceIndication,
        ToleranceRow,
    )

    surface = SurfaceIndication((5, 8), (10, 8), 0.5, ((0, 3),), auto_normal=True)
    with pytest.raises(ValueError, match="geometry attachment"):
        if owner == "datum":
            DatumIdentifier(uuid4().hex, "A", (20, 20), (0, 0), surface_indication=surface)
        else:
            FeatureControlFrame(
                uuid4().hex,
                (ToleranceRow("position", 0.1, 2),),
                (20, 20),
                leader_target_mm=(0, 0),
                surface_indication=surface,
            )


def test_frame_primary_normal_roundtrip_and_requires_geometry() -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, FeatureControlFrame, ToleranceRow
    from mycad.core.sketch_constraints import SketchGeometryReference

    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "geometry"), 0.5)
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2),),
        (20, 20),
        leader_target_mm=(0, 0),
        leader_offsets=((-20, -17),),
        leader_attachment=attachment,
        leader_auto_normal=True,
    )
    assert FeatureControlFrame.from_mapping(frame.to_mapping()) == frame
    with pytest.raises(ValueError, match="normal"):
        FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (20, 20),
            leader_target_mm=(0, 0),
            leader_offsets=((-20, -17),),
            leader_auto_normal=True,
        )
    with pytest.raises(ValueError, match="segment must have length"):
        FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("position", 0.1, 2),),
            (20, 20),
            leader_target_mm=(0, 0),
            leader_offsets=((-20, -20),),
            leader_attachment=attachment,
            leader_auto_normal=True,
        )


def test_datum_rejects_normal_constraints_on_both_leaders() -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier, SurfaceIndication
    from mycad.core.sketch_constraints import SketchGeometryReference

    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "geometry"), 0.5)
    with pytest.raises(ValueError, match="both leaders"):
        DatumIdentifier(
            uuid4().hex,
            "A",
            (20, 20),
            (0, 0),
            attachment=attachment,
            leader_offsets=((0, -3),),
            leader_auto_normal=True,
            surface_indication=SurfaceIndication((5, 8), (10, 8), 0.5, ((0, 3),), auto_normal=True),
        )


def test_spline_normal_undefined_at_stationary_endpoint() -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_attachment import resolve_attachment_normal
    from mycad.core.sketch import Sketch, SplineEntity, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    spline = SplineEntity(uuid4().hex, ((0, 0), (0, 0), (1, 1), (2, 1)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (spline,))
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(spline.entity_id, "geometry"),
        0,
        curve_kind="spline",
        control_count=4,
    )
    assert resolve_attachment_normal(attachment, sketch, (0, 0), enable_spline=True) is None


def test_spline_normal_flag_roundtrip_and_legacy_default() -> None:
    from uuid import uuid4

    from mycad.core.geometric_tolerance import DatumIdentifier

    datum = DatumIdentifier(uuid4().hex, "A", (2, 3), (0, 0), spline_normal_enabled=True)
    assert DatumIdentifier.from_mapping(datum.to_mapping()) == datum
    legacy = DatumIdentifier(uuid4().hex, "B", (2, 3), (0, 0))
    assert "spline_normal_enabled" not in legacy.to_mapping()
    assert not DatumIdentifier.from_mapping(legacy.to_mapping()).spline_normal_enabled


def test_datum_leader_inside_box_has_no_visible_segment() -> None:
    from mycad.core.geometric_tolerance_geometry import datum_leader

    assert datum_leader((0, 0, 4, 10), (1, 1)) is None


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_auto_routed_leader_requires_normal_and_roundtrips(owner: str) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import (
        DatumAttachment,
        DatumIdentifier,
        FeatureControlFrame,
        ToleranceRow,
    )
    from mycad.core.sketch_constraints import SketchGeometryReference

    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "start"))
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (10, 10),
            (0, 0),
            attachment=attachment,
            leader_offsets=((-10, -5),),
            leader_auto_normal=True,
            leader_auto_route=True,
        )
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 10),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            leader_offsets=((-10, -5),),
            leader_auto_normal=True,
            leader_auto_route=True,
        )
    assert type(item).from_mapping(item.to_mapping()) == item
    with pytest.raises(ValueError, match="route"):
        replace(item, leader_auto_normal=False)
    legacy = replace(item, leader_auto_route=False)
    assert "leader_auto_route" not in legacy.to_mapping()
    assert type(legacy).from_mapping(legacy.to_mapping()) == legacy


def test_auto_route_avoids_retracing_normal_segment() -> None:
    from mycad.core.geometric_tolerance_geometry import reroute_orthogonal_leader

    offsets = reroute_orthogonal_leader((0, 0), ((-2, 5),), (-5, 0), (0, 0))
    assert offsets == ((-2, 5), (-5, 5), (-5, 0))


def test_auto_route_rejects_box_waypoint_on_normal_segment() -> None:
    from mycad.core.geometric_tolerance_geometry import reroute_orthogonal_leader

    with pytest.raises(ValueError, match="引线"):
        reroute_orthogonal_leader((0, 0), ((-2, 0),), (-5, 0), (0, 0))


def test_auto_routed_surface_requires_normal_and_roundtrips() -> None:
    from dataclasses import replace

    from mycad.core.geometric_tolerance import SurfaceIndication

    surface = SurfaceIndication((3, 8), (8, 8), 0.5, ((0, 5),), auto_normal=True, auto_route=True)
    assert SurfaceIndication.from_mapping(surface.to_mapping()) == surface
    with pytest.raises(ValueError, match="route"):
        replace(surface, auto_normal=False)
    legacy = replace(surface, auto_route=False)
    assert "auto_route" not in legacy.to_mapping()
    assert SurfaceIndication.from_mapping(legacy.to_mapping()) == legacy


def test_auto_route_avoids_crossing_diagonal_arrow_segment() -> None:
    from mycad.core.geometric_tolerance_geometry import reroute_orthogonal_leader

    offsets = reroute_orthogonal_leader((10, -2), ((-8, 0),), (5, 5), (0, 0))
    assert offsets == ((-8, 0), (-5, 0), (-5, 7))


def test_relocate_automatic_leader_avoids_arrow_crossing_from_box() -> None:
    from mycad.core.geometric_tolerance_geometry import relocate_automatic_leader

    route = relocate_automatic_leader((10, 5), ((-5, 0),), (4, 2), (0, 0))
    assert route == ((1, 0), (1, 3))


def test_surface_route_crossing_policy_roundtrips_and_is_strict() -> None:
    from mycad.core.geometric_tolerance import SurfaceIndication

    surface = SurfaceIndication(
        (3, 8),
        (8, 8),
        0.5,
        ((0, 5),),
        auto_normal=True,
        auto_route=True,
        route_avoid_crossing=True,
    )
    assert SurfaceIndication.from_mapping(surface.to_mapping()) == surface
    with pytest.raises(ValueError, match="route"):
        SurfaceIndication((3, 8), (8, 8), 0.5, route_avoid_crossing=cast("bool", "yes"))


@pytest.mark.parametrize("owner", ["datum", "frame"])
def test_box_safe_route_algorithm_requires_tracking_and_roundtrips(owner: str) -> None:
    from dataclasses import replace

    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.sketch_constraints import SketchGeometryReference

    attachment = DatumAttachment(uuid4().hex, SketchGeometryReference(uuid4().hex, "start"))
    if owner == "datum":
        item = DatumIdentifier(
            uuid4().hex,
            "A",
            (10, 5),
            (0, 0),
            attachment=attachment,
            leader_offsets=((-10, 0),),
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
            route_track_target=True,
            route_algorithm_version=2,
        )
    else:
        item = FeatureControlFrame(
            uuid4().hex,
            (ToleranceRow("flatness", 0.1, 2),),
            (10, 5),
            leader_target_mm=(0, 0),
            leader_attachment=attachment,
            leader_offsets=((-10, 0),),
            leader_auto_normal=True,
            leader_auto_route=True,
            route_avoid_crossing=True,
            route_track_target=True,
            route_algorithm_version=2,
        )
    assert type(item).from_mapping(item.to_mapping()) == item
    with pytest.raises(ValueError, match="algorithm"):
        replace(item, route_track_target=False)
    with pytest.raises(ValueError, match="algorithm"):
        replace(item, route_algorithm_version=5)
    legacy = replace(item, route_algorithm_version=1)
    assert "route_algorithm_version" not in legacy.to_mapping()


@pytest.mark.parametrize("width,height", [(5.212759544541193, 5.0), (12.0, 8.0)])
def test_box_aware_route_avoids_crossing_for_visible_clipped_segment(
    width: float, height: float
) -> None:
    from mycad.core.geometric_tolerance_geometry import (
        datum_leader_path,
        reroute_leader_around_box,
    )

    box = (0.0, 0.0, width, -height)
    target, normal = (13.0, 7.0), (2.0, 2.0)
    offsets = reroute_leader_around_box(
        (0.0, 0.0), ((10.0, 15.0), (2.0, 15.0), normal), normal, target, box
    )
    path = datum_leader_path(box, target, offsets)
    assert len(path) >= 3
    assert path[-2] == pytest.approx(normal)

    def cross(a: tuple[float, float], b: tuple[float, float]) -> float:
        return a[0] * b[1] - a[1] * b[0]

    arrow = (normal[0] - target[0], normal[1] - target[1])
    for start, end in zip(path[:-2], path[1:-1], strict=True):
        segment = (end[0] - start[0], end[1] - start[1])
        delta = (target[0] - start[0], target[1] - start[1])
        denominator = cross(segment, arrow)
        if abs(denominator) <= 1e-9:
            # Parallel segments must not lie on the arrow's supporting line.
            assert abs(cross(delta, arrow)) > 1e-9
        else:
            along = cross(delta, arrow) / denominator
            arrow_along = cross(delta, segment) / denominator
            assert not (-1e-9 <= along <= 1 + 1e-9 and -1e-9 <= arrow_along < 1 - 1e-9)
    assert all(
        abs(a[0] - b[0]) <= 1e-9 or abs(a[1] - b[1]) <= 1e-9
        for a, b in zip(path[1:-2], path[2:-1], strict=True)
    )


def test_box_aware_route_rejects_target_inside_label_box() -> None:
    from mycad.core.geometric_tolerance_geometry import reroute_leader_around_box

    with pytest.raises(ValueError, match="框"):
        reroute_leader_around_box((0, 0), ((8, 0),), (8, -2), (2, -2), (0, 0, 5, -5))


def test_box_aware_route_rejects_normal_vertex_inside_label_box() -> None:
    from mycad.core.geometric_tolerance_geometry import reroute_leader_around_box

    with pytest.raises(ValueError, match="框"):
        reroute_leader_around_box((0, 0), ((8, 0),), (2, -2), (10, -2), (0, 0, 5, -5))


def test_box_aware_route_does_not_reenter_label_box() -> None:
    from mycad.core.geometric_tolerance_geometry import datum_leader_path, reroute_leader_around_box

    box = (0.0, 0.0, 5.0, -5.0)
    target, normal = (12.0, 6.0), (-11.0, -3.0)
    offsets = reroute_leader_around_box((0, 0), ((12, -12), normal), normal, target, box)
    path = datum_leader_path(box, target, offsets)
    for start, end in zip(path, path[1:], strict=False):
        for index in range(1, 100):
            ratio = index / 100
            x = start[0] + (end[0] - start[0]) * ratio
            y = start[1] + (end[1] - start[1]) * ratio
            assert not (0 < x < 5 and -5 < y < 0)


def test_box_aware_route_rejects_arrow_crossing_label_box() -> None:
    from mycad.core.geometric_tolerance_geometry import reroute_leader_around_box

    with pytest.raises(ValueError, match="框"):
        reroute_leader_around_box(
            (0, 0),
            ((8, -9), (8, -3), (-7, -3)),
            (-7, -3),
            (9, 1),
            (0, 0, 5.212759544541193, -5),
        )


def test_box_aware_route_rejects_overflowing_geometry() -> None:
    from mycad.core.geometric_tolerance_geometry import reroute_leader_around_box

    with pytest.raises(ValueError, match="框|法向"):
        reroute_leader_around_box((0, 0), ((1, 0),), (1e308, 0), (-1e308, 0), (0, 0, 5, -5))


def test_datum_recorded_box_size_roundtrips_and_rejects_invalid_values() -> None:
    from dataclasses import replace

    datum = DatumIdentifier(
        uuid4().hex, "A", (2, 3), (10, 0), layout_mode="shared", box_size_mm=(8, 5)
    )
    assert DatumIdentifier.from_mapping(datum.to_mapping()) == datum
    assert "box_size_mm" not in replace(datum, box_size_mm=None).to_mapping()
    with pytest.raises(ValueError, match="box"):
        replace(datum, box_size_mm=(0, 5))
    with pytest.raises(ValueError, match="box"):
        replace(datum, box_size_mm=(float("nan"), 5))
    with pytest.raises(ValueError, match="box"):
        replace(datum, layout_mode="legacy")


def test_box_aware_leader_rejects_zero_length_arrow() -> None:
    from mycad.core.geometric_tolerance_geometry import box_aware_leader_is_safe

    assert not box_aware_leader_is_safe((0, 0), ((10, 0),), (10, 0), (0, 0, 5, -5))


def test_box_aware_route_makes_clipped_box_segment_orthogonal() -> None:
    from mycad.core.geometric_tolerance_geometry import datum_leader_path, reroute_leader_around_box

    box = (0.0, 0.0, 5.212759544541193, -5.0)
    target, normal = (13.0, 7.0), (2.0, 2.0)
    offsets = ((10.0, 15.0), (2.0, 15.0), normal)
    route = reroute_leader_around_box(
        (0.0, 0.0), offsets, normal, target, box, orthogonal_box_side=True
    )
    path = datum_leader_path(box, target, route)
    assert path[-2] == pytest.approx(normal)
    assert all(
        abs(a[0] - b[0]) <= 1e-9 or abs(a[1] - b[1]) <= 1e-9
        for a, b in zip(path[:-2], path[1:-1], strict=True)
    )


def test_strict_box_aware_leader_rejects_target_on_box_edge() -> None:
    from mycad.core.geometric_tolerance_geometry import box_aware_leader_is_safe

    assert not box_aware_leader_is_safe(
        (0, 0),
        ((2.5, 2), (10, 2), (10, -2.5)),
        (5, -2.5),
        (0, 0, 5, -5),
        orthogonal_box_side=True,
    )


def test_strict_box_aware_route_can_turn_near_box_to_avoid_arrow() -> None:
    from mycad.core.geometric_tolerance_geometry import datum_leader_path, reroute_leader_around_box

    box = (0.0, 0.0, 5.0, -5.0)
    normal, target = (-11.0, -3.0), (-2.0, 18.0)
    route = reroute_leader_around_box(
        (0, 0), ((10, 15), normal), normal, target, box, orthogonal_box_side=True
    )
    path = datum_leader_path(box, target, route)
    assert path[-2] == pytest.approx(normal)
    assert all(
        abs(a[0] - b[0]) <= 1e-9 or abs(a[1] - b[1]) <= 1e-9
        for a, b in zip(path[:-2], path[1:-1], strict=True)
    )


def test_closed_filled_frame_arrow_is_narrower_than_datum_triangle() -> None:
    from mycad.core.geometric_tolerance_geometry import datum_triangle, frame_leader_arrow

    start, target, size = (0.0, 10.0), (0.0, 0.0), 6.0
    datum = datum_triangle(start, target, size)
    arrow = frame_leader_arrow(start, target, size)
    assert arrow[0] == target
    assert arrow[1][1] == pytest.approx(6.0) and arrow[2][1] == pytest.approx(6.0)
    assert abs(arrow[1][0] - arrow[2][0]) == pytest.approx(2.0)
    assert abs(datum[1][0] - datum[2][0]) == pytest.approx(4.8)
    assert frame_leader_arrow(target, target, size) == ()


def test_frame_arrow_style_roundtrips_without_changing_legacy_records() -> None:
    from dataclasses import replace
    from uuid import uuid4

    from mycad.core.geometric_tolerance import FeatureControlFrame, ToleranceRow

    legacy = FeatureControlFrame(uuid4().hex, (ToleranceRow("flatness", 0.1, 2),), (0, 0))
    assert "leader_arrow_style" not in legacy.to_mapping()
    assert FeatureControlFrame.from_mapping(legacy.to_mapping()) == legacy
    modern = replace(legacy, leader_arrow_style="closed_filled")
    assert modern.to_mapping()["leader_arrow_style"] == "closed_filled"
    assert FeatureControlFrame.from_mapping(modern.to_mapping()) == modern
    with pytest.raises(ValueError):
        replace(legacy, leader_arrow_style="unknown")


def test_automatic_route_changes_if_hidden_first_waypoint_is_removed() -> None:
    from mycad.core.geometric_tolerance_geometry import reroute_orthogonal_leader

    position = (20.0, 20.0)
    original = ((1.0, -3.0), (-20.0, -15.0))
    normal, target = (-2.5, 5.5), (1.0, 2.0)
    with_hidden = reroute_orthogonal_leader(position, original, normal, target)
    without_hidden = reroute_orthogonal_leader(position, original[1:], normal, target)
    assert with_hidden[0] == original[0]
    assert without_hidden[0] == original[1]
    assert with_hidden != without_hidden
