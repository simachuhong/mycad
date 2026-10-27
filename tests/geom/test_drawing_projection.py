# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Production exact projection, neutral curves and geometry-only cache identity."""

from uuid import uuid4

import pytest
from build123d import Box, Compound, Cylinder, Pos, fillet

from mycad.app import build_app, new_document
from mycad.core.drawing_projection import (
    ArcCurve,
    DrawingProjectionRequest,
    EllipseCurve,
    LineCurve,
    ViewBasis,
)
from mycad.geom.drawing_projection import project_shape


def request(
    normal: tuple[float, float, float] = (0, 0, 1), up: tuple[float, float, float] = (0, 1, 0)
) -> DrawingProjectionRequest:
    return DrawingProjectionRequest(uuid4(), "fixture", 1, ViewBasis.from_normal_up(normal, up))


def test_asymmetric_three_views_have_expected_coordinates() -> None:
    shape = Pos(6, 9, 13) * Box(40, 24, 8) - Pos(7, 4, 13) * Cylinder(2, 20)
    for normal, up, bounds in [
        ((0, 0, 1), (0, 1, 0), (-14, 26, -3, 21)),
        ((0, -1, 0), (0, 0, 1), (-14, 26, 9, 17)),
        ((-1, 0, 0), (0, 0, 1), (-21, 3, 9, 17)),
    ]:
        result = project_shape(shape, request(normal, up))
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
        assert not result.diagnostics
    circles = [
        c.geometry
        for c in project_shape(shape, request()).curves
        if isinstance(c.geometry, ArcCurve)
    ]
    assert any(c.center == pytest.approx((7, 4)) and c.radius == pytest.approx(2) for c in circles)


def test_two_solids_occlude_each_other() -> None:
    shape = Compound(children=[Pos(0, 0, 5) * Box(30, 30, 2), Pos(0, 0, -5) * Box(8, 6, 2)])
    result = project_shape(shape, request())
    assert any(
        c.visibility == "hidden"
        and isinstance(c.geometry, LineCurve)
        and c.geometry.length == pytest.approx(8)
        for c in result.curves
    )
    assert not any(
        c.visibility == "visible"
        and isinstance(c.geometry, LineCurve)
        and c.geometry.length == pytest.approx(8)
        for c in result.curves
    )


def test_hole_occlusion_and_cylinder_silhouettes() -> None:
    result = project_shape(Cylinder(5, 12), request((0, -1, 0), (0, 0, 1)))
    sides = [
        c
        for c in result.curves
        if isinstance(c.geometry, LineCurve) and c.geometry.length == pytest.approx(12)
    ]
    assert len(sides) == 2
    assert all(c.source is not None for c in sides)


def test_ellipse_and_tangent_policy() -> None:
    ellipse = project_shape(Cylinder(5, 12), request((0, -1, 1), (0, 1, 1)))
    assert any(isinstance(c.geometry, EllipseCurve) for c in ellipse.curves)
    box = Box(20, 30, 10)
    result = project_shape(fillet(box.edges(), 2), request((0, -1, 1), (0, 1, 1)))
    assert any(c.visibility == "tangent" for c in result.curves)
    assert any(c.visibility == "visible" for c in result.curves)
    assert not result.diagnostics


def test_layout_does_not_change_source_fingerprint() -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 24, "size_z": 8})
    fingerprint = services.kernel.drawing_source_fingerprint
    req = DrawingProjectionRequest(uuid4(), fingerprint, 1)
    result = services.kernel.project_drawing(req)
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(uuid4())})
    assert services.kernel.drawing_source_fingerprint == fingerprint
    assert services.kernel.project_drawing(req).curves is result.curves
    loaded.bus.execute("feature.cylinder", {"radius": 2, "height": 3})
    assert services.kernel.drawing_source_fingerprint != fingerprint
    with pytest.raises(ValueError, match="source"):
        services.kernel.project_drawing(req)


def test_rational_curve_not_flattened() -> None:
    from build123d import Edge
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.Geom import Geom_BSplineCurve
    from OCP.gp import gp_Pnt
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal

    from mycad.core.drawing_projection import SplineCurve

    poles = TColgp_Array1OfPnt(1, 4)
    weights = TColStd_Array1OfReal(1, 4)
    for i, (point, weight) in enumerate(
        zip(((0, 0, 2), (10, 20, 3), (20, -10, 4), (30, 5, 5)), (1, 2, 3, 1), strict=True), 1
    ):
        poles.SetValue(i, gp_Pnt(*point))
        weights.SetValue(i, weight)
    knots = TColStd_Array1OfReal(1, 2)
    mults = TColStd_Array1OfInteger(1, 2)
    for i, knot in enumerate((0, 1), 1):
        knots.SetValue(i, knot)
        mults.SetValue(i, 4)
    curve = Geom_BSplineCurve(poles, weights, knots, mults, 3)
    result = project_shape(Edge(BRepBuilderAPI_MakeEdge(curve).Edge()), request())
    assert not result.diagnostics
    projected = result.curves[0].geometry
    assert isinstance(projected, SplineCurve)
    assert projected.weights == pytest.approx((1, 2, 3, 1))
    assert projected.poles == ((0, 0), (10, 20), (20, -10), (30, 5))
    assert projected.degree == 3
    assert projected.knots == (0, 1)
    assert projected.multiplicities == (4, 4)


def test_distinct_splines_with_same_five_samples_are_not_merged() -> None:
    from math import comb

    from build123d import Edge
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.Geom import Geom_BSplineCurve
    from OCP.gp import gp_Pnt
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal

    # y=t(t-.25)(t-.5)(t-.75)(t-1), represented exactly as degree-5 Bezier.
    power = [0, 0.09375, -0.78125, 2.1875, -2.5, 1]
    bernstein = [sum(power[k] * comb(i, k) / comb(5, k) for k in range(i + 1)) for i in range(6)]
    edges: list[Edge] = []
    for factor in (1, 2):
        poles = TColgp_Array1OfPnt(1, 6)
        weights = TColStd_Array1OfReal(1, 6)
        for i, y in enumerate(bernstein, 1):
            poles.SetValue(i, gp_Pnt((i - 1) * 2, factor * y * 100, 0))
            weights.SetValue(i, 1)
        knots = TColStd_Array1OfReal(1, 2)
        mults = TColStd_Array1OfInteger(1, 2)
        for i, knot in enumerate((0, 1), 1):
            knots.SetValue(i, knot)
            mults.SetValue(i, 6)
        curve = Geom_BSplineCurve(poles, weights, knots, mults, 5)
        edges.append(Edge(BRepBuilderAPI_MakeEdge(curve).Edge()))
    result = project_shape(Compound(edges), request())
    assert len(result.curves) == 2


def test_edge_on_circular_boundaries_are_exact_line_segments() -> None:
    result = project_shape(Cylinder(5, 12), request((0, -1, 0), (0, 0, 1)))
    assert len(result.curves) == 4
    assert all(isinstance(c.geometry, LineCurve) for c in result.curves)
