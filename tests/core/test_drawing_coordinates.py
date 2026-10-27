# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Model millimetres, paper millimetres and camera direction stay distinct."""

from uuid import uuid4

import pytest

from mycad.core.drawing import DrawingSheet, DrawingState, DrawingView
from mycad.core.drawing_projection import (
    LineCurve,
    ProjectedCurve,
    ProjectionResult,
    ViewBasis,
    build_drawing_scene,
    projected_basis,
)


def test_scale_does_not_change_measurement() -> None:
    sheet = DrawingSheet(uuid4())
    view = DrawingView(uuid4(), sheet.sheet_id, anchor_mm=(10, 20), scale=0.5)
    line = LineCurve((0, 0), (80, 0))
    result = ProjectionResult(view.view_id, "model-A", 1, (ProjectedCurve("edge-1", line),))
    scene = build_drawing_scene(
        DrawingState((sheet,), (view,)), sheet.sheet_id, {view.view_id: result}
    )
    assert scene.views[0].to_paper((80, 0)) == (50, 20)
    assert scene.views[0].to_paper((0, 0)) == (10, 20)
    assert line.length == 80
    assert not scene.issues


def test_paper_dimensions_and_orientation() -> None:
    assert DrawingSheet.for_paper(uuid4(), "A4", landscape=False).size_mm == (210, 297)
    assert DrawingSheet.for_paper(uuid4(), "A4", landscape=True).size_mm == (297, 210)
    assert DrawingSheet.for_paper(uuid4(), "A3", landscape=False).size_mm == (297, 420)


def test_explicit_right_handed_basis_and_relative_views() -> None:
    front = ViewBasis()
    assert front.project((7, 4, 3)) == (7, 3)
    assert projected_basis(front, "top").project((7, 4, 3)) == (7, 4)
    assert projected_basis(front, "left").project((7, 4, 3)) == (-4, 3)
    assert projected_basis(front, "right").project((7, 4, 3)) == (4, 3)


@pytest.mark.parametrize("normal,up", [((0, 0, 0), (0, 0, 1)), ((0, 0, 1), (0, 0, 1))])
def test_invalid_basis_rejected(normal: tuple[int, int, int], up: tuple[int, int, int]) -> None:
    with pytest.raises(ValueError):
        ViewBasis.from_normal_up(normal, up)


def test_missing_projection_blocks_output_without_hiding_view() -> None:
    sheet = DrawingSheet(uuid4())
    view = DrawingView(uuid4(), sheet.sheet_id)
    scene = build_drawing_scene(DrawingState((sheet,), (view,)), sheet.sheet_id, {})
    assert scene.issues
    assert str(view.view_id) in scene.issues[0]


def test_exact_curve_data_rejects_invalid_radii_and_spline_weights() -> None:
    from mycad.core.drawing_projection import ArcCurve, EllipseCurve, SplineCurve

    with pytest.raises(ValueError):
        ArcCurve((0, 0), -3)
    with pytest.raises(ValueError):
        EllipseCurve((0, 0), 2, 3)
    with pytest.raises(ValueError):
        SplineCurve(((0, 0), (1, 2), (3, 0)), 2, (0, 1), (3, 3), (1, -1, 1))
    spline = SplineCurve(((0, 0), (1, 2), (3, 0)), 2, (0, 1), (3, 3), (1, 2, 1))
    assert spline.weights == (1, 2, 1)
    assert spline.multiplicities == (3, 3)


def test_mixed_source_versions_cannot_produce_clean_sheet() -> None:
    sheet = DrawingSheet(uuid4())
    first = DrawingView(uuid4(), sheet.sheet_id)
    second = DrawingView(uuid4(), sheet.sheet_id)
    projections = {
        first.view_id: ProjectionResult(first.view_id, "old", 1, ()),
        second.view_id: ProjectionResult(second.view_id, "new", 2, ()),
    }
    scene = build_drawing_scene(
        DrawingState((sheet,), (first, second)), sheet.sheet_id, projections
    )
    assert scene.issues
