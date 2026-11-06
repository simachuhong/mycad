# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Snap candidates come from exact model geometry, not display polylines."""

from uuid import uuid4

import pytest

from mycad import app
from mycad.core.sketch import ArcEntity, LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
from mycad.geom.kernel import BuildKernel


def test_box_snap_anchors_are_exact_and_stable_across_tessellation() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 20, "size_y": 10, "size_z": 6})
    anchors = kernel.snap_anchor_data()
    assert len([a for a in anchors if a.kind == "vertex"]) == 8
    assert len([a for a in anchors if a.kind == "midpoint"]) == 12
    assert all(a.topology_id is not None and a.body_id is not None for a in anchors)
    kernel.viewport_data(linear_tolerance_mm=0.05)
    assert kernel.snap_anchor_data() == anchors


def test_cylinder_snap_centers_are_analytic_and_closed_edges_have_no_midpoint() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.cylinder", {"radius": 5, "height": 10})
    anchors = kernel.snap_anchor_data()
    centers = [a.point for a in anchors if a.kind == "center"]
    assert len(centers) >= 2
    assert any(point == pytest.approx((0, 0, -5)) for point in centers)
    assert any(point == pytest.approx((0, 0, 5)) for point in centers)
    circular_ids = {a.topology_id for a in anchors if a.kind == "center"}
    assert not any(a.kind == "midpoint" and a.topology_id in circular_ids for a in anchors)


def test_sketch_snap_points_are_exact_even_without_a_solid() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    line = LineEntity(uuid4().hex, (1, 2), (9, 2))
    arc = ArcEntity(uuid4().hex, (0, 0), 10, 0, 90)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, arc))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), version=3)
    anchors = services.kernel.snap_anchor_data()
    assert any(a.kind == "vertex" and a.point == pytest.approx((1, 2, 0)) for a in anchors)
    assert any(a.kind == "midpoint" and a.point == pytest.approx((5, 2, 0)) for a in anchors)
    assert any(a.kind == "center" and a.point == pytest.approx((0, 0, 0)) for a in anchors)
    assert any(
        a.kind == "midpoint" and a.point == pytest.approx((2**0.5 * 5, 2**0.5 * 5, 0))
        for a in anchors
    )


def test_open_polyline_returning_to_first_point_keeps_endpoint() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    line = PolylineEntity(uuid4().hex, ((1, 2), (3, 4), (1, 2)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), version=3)
    anchors = services.kernel.snap_anchor_data()
    assert any(a.kind == "vertex" and a.point == pytest.approx((1, 2, 0)) for a in anchors)
