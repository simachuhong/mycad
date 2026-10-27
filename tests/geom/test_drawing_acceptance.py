# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Production projection acceptance for directional steps and blind/coaxial holes."""

from uuid import uuid4

import pytest
from build123d import Box, Cylinder, Pos

from mycad.core.drawing_projection import ArcCurve, DrawingProjectionRequest, LineCurve, ViewBasis
from mycad.core.drawing_references import reference_for_curve, resolve_reference
from mycad.geom.drawing_projection import project_shape


@pytest.mark.parametrize(
    "normal,up,bounds",
    [
        ((0, -1, 0), (0, 0, 1), (-20, 30, -4, 12)),
        ((0, 1, 0), (0, 0, 1), (-30, 20, -4, 12)),
        ((-1, 0, 0), (0, 0, 1), (-15, 10, -4, 12)),
        ((1, 0, 0), (0, 0, 1), (-10, 15, -4, 12)),
        ((0, 0, 1), (0, 1, 0), (-20, 30, -10, 15)),
    ],
)
def test_asymmetric_step_production_views(
    normal: tuple[float, float, float],
    up: tuple[float, float, float],
    bounds: tuple[float, float, float, float],
) -> None:
    shape = Box(40, 20, 8) + Pos(20, 5, 4) * Box(20, 20, 16)
    result = project_shape(
        shape, DrawingProjectionRequest(uuid4(), "step", 1, ViewBasis.from_normal_up(normal, up))
    )
    assert not result.diagnostics
    points = [
        p
        for c in result.curves
        if isinstance(c.geometry, LineCurve)
        for p in (c.geometry.start, c.geometry.end)
    ]
    assert (
        min(p[0] for p in points),
        max(p[0] for p in points),
        min(p[1] for p in points),
        max(p[1] for p in points),
    ) == pytest.approx(bounds)


def test_blind_hole_and_counterbore_keep_geometry_and_reject_ambiguous_reference() -> None:
    # Body top z=10; a blind r3 bore ends at z=2; r6 counterbore ends at z=6.
    blind = Box(40, 30, 20) - Pos(5, 4, 8) * Cylinder(3, 12)
    stepped = blind - Pos(5, 4, 10) * Cylinder(6, 8)
    req = DrawingProjectionRequest(
        uuid4(), "blind", 1, ViewBasis.from_normal_up((0, 0, 1), (0, 1, 0))
    )
    before, after = project_shape(blind, req), project_shape(stepped, req)
    assert not before.diagnostics and not after.diagnostics
    rim = next(
        c
        for c in before.curves
        if isinstance(c.geometry, ArcCurve) and c.geometry.radius == pytest.approx(3)
    )
    assert resolve_reference(reference_for_curve(rim), before).status == "resolved"
    circles = [c for c in after.curves if isinstance(c.geometry, ArcCurve)]
    assert {round(c.geometry.radius) for c in circles if isinstance(c.geometry, ArcCurve)} == {3, 6}
    assert resolve_reference(reference_for_curve(rim), after).status == "ambiguous"
    side = project_shape(stepped, DrawingProjectionRequest(uuid4(), "blind", 1))
    assert any(c.visibility == "hidden" and isinstance(c.geometry, LineCurve) for c in side.curves)
