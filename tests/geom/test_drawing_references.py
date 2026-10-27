# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Bounded semantic identities survive size edits and reject competing sources."""

from uuid import uuid4

import pytest
from build123d import Box, Compound, Cylinder, Pos

from mycad.core.drawing_projection import ArcCurve, DrawingProjectionRequest, LineCurve, ViewBasis
from mycad.core.drawing_references import reference_for_curve, resolve_reference
from mycad.geom.drawing_projection import project_shape


def request() -> DrawingProjectionRequest:
    return DrawingProjectionRequest(
        uuid4(), "fixture", 1, ViewBasis.from_normal_up((0, 0, 1), (0, 1, 0))
    )


def test_length_and_hole_diameter_updates_keep_correct_anchor() -> None:
    before = project_shape(Box(80, 30, 8) - Pos(7, 4, 0) * Cylinder(2, 20), request())
    after = project_shape(Box(100, 30, 8) - Pos(7, 4, 0) * Cylinder(3, 20), request())
    circle = next(c for c in before.curves if isinstance(c.geometry, ArcCurve))
    ref = reference_for_curve(circle)
    resolved = resolve_reference(ref, after)
    assert resolved.status == "resolved"
    new_circle = next(c.geometry for c in after.curves if c.curve_id in resolved.curve_ids)
    assert isinstance(new_circle, ArcCurve)
    assert new_circle.center == pytest.approx((7, 4))
    assert new_circle.radius == pytest.approx(3)
    right = next(
        c
        for c in before.curves
        if isinstance(c.geometry, LineCurve)
        and c.geometry.start[0] == pytest.approx(40)
        and c.geometry.end[0] == pytest.approx(40)
    )
    resolved = resolve_reference(reference_for_curve(right, role="center"), after)
    assert resolved.status == "resolved"
    changed = next(c.geometry for c in after.curves if c.curve_id in resolved.curve_ids)
    assert isinstance(changed, LineCurve)
    assert changed.start[0] == pytest.approx(50)


def test_duplicate_holes_are_ambiguous_not_nearest() -> None:
    before = project_shape(Cylinder(2, 8), request())
    circle = next(c for c in before.curves if isinstance(c.geometry, ArcCurve))
    after = project_shape(
        Compound(children=[Pos(0, 0, 20) * Cylinder(2, 8), Cylinder(2, 8)]), request()
    )
    resolution = resolve_reference(reference_for_curve(circle), after)
    assert resolution.status == "ambiguous"
    assert not resolution.curve_ids


def test_deleted_anchor_is_orphaned() -> None:
    before = project_shape(Box(30, 30, 8) - Cylinder(2, 20), request())
    circle = next(c for c in before.curves if isinstance(c.geometry, ArcCurve))
    after = project_shape(Box(30, 30, 8), request())
    assert resolve_reference(reference_for_curve(circle), after).status == "orphaned"


def test_source_count_uses_same_tolerance_as_reference_matching() -> None:
    from mycad.core.drawing_references import DrawingGeometryReference
    from mycad.geom.drawing_references import source_key, source_multiplicities

    a = DrawingGeometryReference("cylindrical_face", (("x", 0.49e-6),))
    b = DrawingGeometryReference("cylindrical_face", (("x", 0.51e-6),))
    counts = source_multiplicities((a, b))
    assert counts[source_key(a)] == counts[source_key(b)] == 2
