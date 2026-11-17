# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Flat paper geometry preserves authored curves and durable sketch references."""

from dataclasses import replace
from uuid import uuid4

from mycad.core.drawing import (
    DrawingAnnotation,
    DrawingSheet,
    DrawingState,
    DrawingView,
    SourceBinding,
)
from mycad.core.drawing_projection import (
    ArcCurve,
    DrawingProjectionRequest,
    LineCurve,
    SplineCurve,
    build_drawing_scene,
)
from mycad.core.drawing_references import reference_for_curve, resolve_reference
from mycad.core.drawing_sketch import project_sketch
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable


def test_all_six_entities_are_exact_local_uv_geometry() -> None:
    spline = SplineEntity(str(uuid4()), ((0, 0), (5, 9), (10, -3), (20, 6), (30, 0)))
    sketch = Sketch(
        str(uuid4()),
        WorkPlaneFrame.yz(),
        (
            LineEntity(str(uuid4()), (0, 0), (40, 0)),
            PolylineEntity(str(uuid4()), ((0, 0), (5, 0), (5, 5)), closed=True),
            RectangleEntity(str(uuid4()), (4, 6), (12, 20)),
            CircleEntity(str(uuid4()), (30, 20), 4),
            ArcEntity(str(uuid4()), (40, 20), 5, 30, -120),
            spline,
        ),
    )
    request = DrawingProjectionRequest(
        uuid4(), "source", 1, source="sketch", sketch_id=sketch.sketch_id
    )
    result = project_sketch(sketch, request)
    assert not result.diagnostics
    assert len(result.curves) == 11
    assert result.curves[0].geometry == LineCurve((0, 0), (40, 0))
    assert result.curves[8].geometry == ArcCurve((30, 20), 4)
    assert result.curves[9].geometry == ArcCurve((40, 20), 5, 30, -120)
    assert result.curves[10].geometry == SplineCurve(
        spline.control_points_mm, 3, (0, 0.5, 1), (4, 1, 4), (1,) * 5
    )
    for curve in result.curves:
        assert resolve_reference(reference_for_curve(curve), result).curve_ids == (curve.curve_id,)


def test_polyline_arc_projects_as_exact_arc_with_same_source_identity() -> None:
    entity = PolylineEntity(str(uuid4()), ((0, 0), (2, 0), (2, 2)), bulges=(1, 0))
    sketch = Sketch(str(uuid4()), WorkPlaneFrame.xy(), (entity,))
    request = DrawingProjectionRequest(
        uuid4(), "source", 1, source="sketch", sketch_id=sketch.sketch_id
    )
    result = project_sketch(sketch, request)
    assert len(result.curves) == 2
    assert result.curves[0].geometry == ArcCurve((1, 0), 1, 180, 180)
    assert result.curves[1].geometry == LineCurve((2, 0), (2, 2))
    assert all(
        curve.source is not None and curve.source.entity_id == entity.entity_id
        for curve in result.curves
    )


def test_hidden_frozen_and_construction_are_absent_but_locked_is_visible() -> None:
    layers = SketchLayerTable(
        (
            SketchLayer("0"),
            SketchLayer("hidden", visible=False),
            SketchLayer("frozen", frozen=True),
            SketchLayer("locked", locked=True),
        )
    )
    sketch = Sketch(
        str(uuid4()),
        WorkPlaneFrame.xy(),
        tuple(
            LineEntity(str(uuid4()), (0, 0), (10, 0), layer_name=name)
            for name in ("0", "hidden", "frozen", "locked")
        )
        + (LineEntity(str(uuid4()), (0, 2), (10, 2), construction=True),),
        layers=layers,
    )
    request = DrawingProjectionRequest(
        uuid4(), "source", 1, source="sketch", sketch_id=sketch.sketch_id
    )
    assert len(project_sketch(sketch, request).curves) == 2
    hidden = replace(
        sketch,
        layers=SketchLayerTable(tuple(replace(layer, visible=False) for layer in layers.layers)),
    )
    result = project_sketch(hidden, request)
    assert result.curves == ()
    assert result.diagnostics == ("草图没有可显示的非构造曲线，请检查图元与图层可见性",)


def test_annotation_tracks_length_and_rotation_by_entity_identity() -> None:
    line = LineEntity(str(uuid4()), (0, 0), (40, 0))
    sketch = Sketch(str(uuid4()), WorkPlaneFrame.xy(), (line,))
    sheet = DrawingSheet(uuid4())
    view = DrawingView(
        uuid4(),
        sheet.sheet_id,
        SourceBinding("sketch", sketch.sketch_id),
        anchor_mm=(80, 100),
        scale=0.5,
    )
    request = DrawingProjectionRequest(
        view.view_id, "first", 1, source="sketch", sketch_id=sketch.sketch_id
    )
    projection = project_sketch(sketch, request)
    annotation = DrawingAnnotation(
        uuid4(),
        view.view_id,
        "aligned",
        (
            reference_for_curve(projection.curves[0], role="start"),
            reference_for_curve(projection.curves[0], role="end"),
        ),
        (100, 120),
    )
    changed = replace(sketch, entities=(replace(line, end_mm=(0, 60)),))
    result = project_sketch(changed, replace(request, source_fingerprint="second", generation=2))
    scene = build_drawing_scene(
        DrawingState((sheet,), (view,), (annotation,)), sheet.sheet_id, {view.view_id: result}
    )
    assert scene.resolved_annotations[0].value == 60
    assert scene.resolved_annotations[0].anchors == ((80, 100), (80, 130))
    assert not scene.issues
    wrong = project_sketch(replace(sketch, sketch_id=str(uuid4())), request)
    assert wrong.diagnostics
    assert not wrong.curves
