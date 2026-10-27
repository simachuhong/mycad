# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Paper annotations measure local model millimetres and never edit the model."""

from dataclasses import replace
from uuid import uuid4

import pytest
from pytestqt.qtbot import QtBot

from mycad.core.drawing import DrawingAnnotation, DrawingSheet, DrawingState, DrawingView
from mycad.core.drawing_annotations import resolve_annotation
from mycad.core.drawing_projection import (
    ArcCurve,
    EllipseCurve,
    LineCurve,
    ProjectedCurve,
    ProjectionResult,
    build_drawing_scene,
)
from mycad.core.drawing_references import DrawingGeometryReference, reference_for_curve


def test_dimension_value_ignores_paper_scale() -> None:
    sheet = DrawingSheet(uuid4())
    view = DrawingView(uuid4(), sheet.sheet_id, anchor_mm=(70, 100), scale=0.5)
    edge = ProjectedCurve(
        "edge",
        LineCurve((0, 0), (80, 0)),
        source=DrawingGeometryReference("edge", (("fixture", 1),)),
    )
    annotation = DrawingAnnotation(
        uuid4(),
        view.view_id,
        "horizontal",
        (reference_for_curve(edge, role="start"), reference_for_curve(edge, role="end")),
        (90, 90),
    )
    projection = ProjectionResult(view.view_id, "source", 1, (edge,))
    state = DrawingState((sheet,), (view,), (annotation,))
    scene = build_drawing_scene(state, sheet.sheet_id, {view.view_id: projection})
    measured = scene.resolved_annotations[0]
    assert measured.value == 80
    assert measured.text == "80.00 mm"
    assert measured.anchors == ((70, 100), (110, 100))
    assert not scene.issues
    changed = replace(projection, curves=(replace(edge, geometry=LineCurve((0, 0), (100, 0))),))
    assert resolve_annotation(annotation, changed, scene.views[0]).value == 100


def test_ellipse_rejects_circle_dimension() -> None:
    source = DrawingGeometryReference("cylindrical_face", (("x", 0),))
    edge = ProjectedCurve("ellipse", EllipseCurve((0, 0), 5, 3), source=source)
    view = DrawingView(uuid4(), uuid4())
    annotation = DrawingAnnotation(
        uuid4(), view.view_id, "diameter", (reference_for_curve(edge),), (20, 20)
    )
    from mycad.core.drawing_projection import SceneView

    result = resolve_annotation(
        annotation,
        ProjectionResult(view.view_id, "s", 1, (edge,)),
        SceneView(view.view_id, (0, 0), 1, (edge,)),
    )
    assert result.status == "orphaned"
    assert result.value is None
    assert "圆" in result.message


def test_orphan_keeps_text_position_and_blocks_scene() -> None:
    sheet = DrawingSheet(uuid4())
    view = DrawingView(uuid4(), sheet.sheet_id)
    edge = ProjectedCurve(
        "circle", ArcCurve((0, 0), 3), source=DrawingGeometryReference("cylindrical_face")
    )
    annotation = DrawingAnnotation(
        uuid4(), view.view_id, "diameter", (reference_for_curve(edge),), (30, 40)
    )
    scene = build_drawing_scene(
        DrawingState((sheet,), (view,), (annotation,)),
        sheet.sheet_id,
        {view.view_id: ProjectionResult(view.view_id, "s", 1, ())},
    )
    assert scene.resolved_annotations[0].position_mm == (30, 40)
    assert scene.resolved_annotations[0].status == "orphaned"
    assert str(annotation.annotation_id) in " ".join(scene.issues)


def test_canvas_annotation_placement_and_text_drag_are_bus_commands(
    qtbot: "QtBot", monkeypatch: "pytest.MonkeyPatch"
) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest

    from mycad.app import build_app, new_document
    from mycad.core.drawing_codec import drawing_object_mapping
    from mycad.core.drawing_projection import ViewBasis
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.cylinder", {"radius": 5, "height": 8})
    sheet = DrawingSheet(uuid4())
    view = DrawingView(
        uuid4(),
        sheet.sheet_id,
        anchor_mm=(100, 100),
        basis=ViewBasis.from_normal_up((0, 0, 1), (0, 1, 0)),
    )
    loaded.bus.execute("drawing.sheet.create", drawing_object_mapping(sheet))
    loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.bind_document(loaded)
    bench.updates.sync(
        bench.session_id, services.kernel.drawing_source_fingerprint, {view.view_id: view.basis}
    )
    batch = bench.updates.begin()
    assert batch is not None
    bench.updates.finish(batch, (services.kernel.project_drawing(batch.requests[0]),))
    window.resize(1200, 800)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench.canvas.fit_view()
    bench.annotations.begin("diameter")
    before = len(loaded.document.commands)
    rim = bench.canvas.mapFromScene(QPointF(105, -100))
    QTest.mouseClick(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=rim)
    text = bench.canvas.mapFromScene(QPointF(125, -115))
    QTest.mouseMove(bench.canvas.viewport(), text)
    assert len(loaded.document.commands) == before
    QTest.mouseClick(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=text)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_state.annotations) == 1 and not unit.is_busy
    )
    scene = bench.canvas.drawing_scene
    assert scene is not None
    assert scene.resolved_annotations[0].value == 10
    annotation = services.kernel.drawing_state.annotations[0]
    point = bench.canvas.annotation_text_position(annotation.annotation_id)
    QTest.mousePress(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(bench.canvas.viewport(), point + QPoint(35, 20))
    assert len(loaded.document.commands) == before + 1
    QTest.mouseRelease(
        bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point + QPoint(35, 20)
    )
    qtbot.waitUntil(lambda: len(loaded.document.commands) == before + 2 and not unit.is_busy)
    assert services.kernel.drawing_state.annotations[0].position_mm != annotation.position_mm
    point = bench.canvas.annotation_text_position(annotation.annotation_id)
    QTest.mouseDClick(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
    bench.annotations.precision.setValue(1)
    bench.annotations.apply_expression()
    qtbot.waitUntil(
        lambda: services.kernel.drawing_state.annotations[0].precision == 1 and not unit.is_busy
    )
    assert services.kernel.drawing_source_fingerprint == batch.requests[0].source_fingerprint
    import os

    capture = os.environ.get("MYCAD_ANNOTATION_CAPTURE")
    if capture:
        assert window.grab().save(capture)


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("horizontal", 3),
        ("vertical", 4),
        ("aligned", 5),
        ("radius", 6),
        ("diameter", 12),
        ("angle", 90),
        ("center", None),
    ],
)
def test_supported_annotation_kinds(kind: str, expected: float | None) -> None:
    from typing import cast

    from mycad.core.drawing import AnnotationKind
    from mycad.core.drawing_projection import SceneView

    identity = uuid4()
    a = ProjectedCurve(
        "a", LineCurve((0, 0), (3, 4)), source=DrawingGeometryReference("edge", (("id", 1),))
    )
    b = ProjectedCurve(
        "b", LineCurve((0, 0), (-4, 3)), source=DrawingGeometryReference("edge", (("id", 2),))
    )
    c = ProjectedCurve(
        "c", ArcCurve((0, 0), 6), source=DrawingGeometryReference("cylindrical_face", (("x", 0),))
    )
    refs = (reference_for_curve(c),)
    if kind in ("horizontal", "vertical", "aligned"):
        refs = (reference_for_curve(a, role="start"), reference_for_curve(a, role="end"))
    elif kind == "angle":
        refs = (reference_for_curve(a), reference_for_curve(b))
    annotation = DrawingAnnotation(uuid4(), identity, cast("AnnotationKind", kind), refs, (-10, 10))
    projection = ProjectionResult(identity, "s", 1, (a, b, c))
    item = resolve_annotation(annotation, projection, SceneView(identity, (0, 0), 0.5, (a, b, c)))
    assert item.status == "resolved"
    assert item.value == pytest.approx(expected) if expected is not None else item.value is None
    assert item.curves


def test_reattach_preserves_identity_and_expression(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QToolBar

    from mycad.core.drawing_codec import apply_drawing_command
    from mycad.ui.drawing_annotation_tools import DrawingAnnotationTools
    from mycad.ui.drawing_canvas import DrawingCanvas

    sheet = DrawingSheet(uuid4())
    view = DrawingView(uuid4(), sheet.sheet_id)
    old = ProjectedCurve(
        "old", ArcCurve((0, 0), 3), source=DrawingGeometryReference("cylindrical_face", (("x", 0),))
    )
    new = ProjectedCurve(
        "new",
        ArcCurve((10, 0), 4),
        source=DrawingGeometryReference("cylindrical_face", (("x", 10),)),
    )
    annotation = DrawingAnnotation(
        uuid4(),
        view.view_id,
        "diameter",
        (reference_for_curve(old),),
        (20, 30),
        precision=1,
        prefix="孔 ",
    )
    states = [DrawingState((sheet,), (view,), (annotation,))]
    calls: list[str] = []

    def execute(command: str, params: dict[str, object]) -> None:
        calls.append(command)
        states[0] = apply_drawing_command(states[0], command, params)

    canvas = DrawingCanvas()
    toolbar = QToolBar()
    projections = {view.view_id: ProjectionResult(view.view_id, "new", 2, (new,))}
    tools = DrawingAnnotationTools(
        canvas,
        toolbar,
        lambda: states[0],
        projections,
        execute,
        lambda: None,
        lambda _text: None,
        lambda _identity: True,
    )
    for widget in (canvas, toolbar, tools):
        qtbot.addWidget(widget)
    tools.select(annotation.annotation_id)
    tools.reattach()
    tools.choose(view.view_id, "new", (14, 0))
    assert not calls
    tools.commit((25, 30))
    assert calls == ["drawing.annotation.update"]
    rebound = states[0].annotations[0]
    assert rebound.annotation_id == annotation.annotation_id
    assert rebound.precision == 1 and rebound.prefix == "孔 "
    scene = build_drawing_scene(states[0], sheet.sheet_id, projections)
    assert scene.resolved_annotations[0].text == "孔 ⌀8.0 mm"


def test_angle_wedge_follows_text_quadrant() -> None:
    from math import sqrt

    from mycad.core.drawing_projection import SceneView

    identity = uuid4()
    a = ProjectedCurve(
        "a", LineCurve((0, 0), (10, 0)), source=DrawingGeometryReference("edge", (("id", 1),))
    )
    b = ProjectedCurve(
        "b",
        LineCurve((0, 0), (sqrt(3) * 5, 5)),
        source=DrawingGeometryReference("edge", (("id", 2),)),
    )
    annotation = DrawingAnnotation(
        uuid4(), identity, "angle", (reference_for_curve(a), reference_for_curve(b)), (-10, 10)
    )
    item = resolve_annotation(
        annotation,
        ProjectionResult(identity, "s", 1, (a, b)),
        SceneView(identity, (0, 0), 1, (a, b)),
    )
    assert item.value == pytest.approx(150)


def test_radius_leader_terminates_on_the_trimmed_arc() -> None:
    from mycad.core.drawing_projection import SceneView

    identity = uuid4()
    curve = ProjectedCurve(
        "arc", ArcCurve((0, 0), 5, 0, 90), source=DrawingGeometryReference("edge", (("id", 1),))
    )
    annotation = DrawingAnnotation(
        uuid4(), identity, "radius", (reference_for_curve(curve),), (-10, 0)
    )
    item = resolve_annotation(
        annotation,
        ProjectionResult(identity, "s", 1, (curve,)),
        SceneView(identity, (0, 0), 1, (curve,)),
    )
    radial = item.curves[0]
    assert isinstance(radial, LineCurve)
    assert radial.end == pytest.approx((0, 5))


def test_missing_projection_retains_annotation_warning_position() -> None:
    sheet = DrawingSheet(uuid4())
    view = DrawingView(uuid4(), sheet.sheet_id)
    annotation = DrawingAnnotation(
        uuid4(), view.view_id, "diameter", (DrawingGeometryReference("cylindrical_face"),), (33, 44)
    )
    scene = build_drawing_scene(DrawingState((sheet,), (view,), (annotation,)), sheet.sheet_id, {})
    assert scene.resolved_annotations[0].position_mm == (33, 44)
    assert scene.issues


def test_model_change_during_annotation_draft_prevents_commit(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QToolBar

    from mycad.ui.drawing_annotation_tools import DrawingAnnotationTools
    from mycad.ui.drawing_canvas import DrawingCanvas

    sheet = DrawingSheet(uuid4())
    view = DrawingView(uuid4(), sheet.sheet_id)
    curve = ProjectedCurve(
        "circle", ArcCurve((0, 0), 5), source=DrawingGeometryReference("cylindrical_face")
    )
    state = DrawingState((sheet,), (view,))
    canvas, toolbar = DrawingCanvas(), QToolBar()
    calls: list[str] = []
    clean = [True]
    tool = DrawingAnnotationTools(
        canvas,
        toolbar,
        lambda: state,
        {view.view_id: ProjectionResult(view.view_id, "old", 1, (curve,))},
        lambda command, _params: calls.append(command),
        lambda: None,
        lambda _text: None,
        lambda _view: clean[0],
    )
    for widget in (canvas, toolbar, tool):
        qtbot.addWidget(widget)
    tool.begin("diameter")
    tool.choose(view.view_id, "circle", (5, 0))
    assert tool.pending
    clean[0] = False
    tool.commit((20, 20))
    assert not calls
    assert tool.pending
    tool.cancel()
    assert not tool.pending


@pytest.mark.parametrize("zoom", [1.0, 2.3, 4.0])
def test_hollow_circle_picks_nearest_stroke_with_pixel_tolerance(qtbot: QtBot, zoom: float) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest

    from mycad.core.drawing_projection import ArcCurve, DrawingScene, ProjectedCurve, SceneView
    from mycad.ui.drawing_canvas import DrawingCanvas

    canvas = DrawingCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    identity = uuid4()
    canvas.set_scene(
        DrawingScene(
            uuid4(),
            (297, 210),
            10,
            (),
            (
                SceneView(
                    identity,
                    (90, 75),
                    0.5,
                    (
                        ProjectedCurve("hole", ArcCurve((25, 0), 3)),
                        ProjectedCurve("outer", ArcCurve((0, 0), 40)),
                    ),
                ),
            ),
        )
    )
    canvas.show()
    canvas.resetTransform()
    canvas.scale(zoom, zoom)
    canvas.annotation_mode = True
    picked: list[str] = []

    def on_pick(_view: object, curve: str, _point: object) -> None:
        picked.append(curve)

    canvas.geometry_clicked.connect(on_pick)
    # Two pixels outside the thin hole stroke, well inside the unfilled outer circle.
    point = canvas.mapFromScene(QPointF(104, -75)) + QPoint(2, 0)
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert picked == ["hole"]
    picked.clear()
    QTest.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(QPointF(90, -75))
    )
    assert not picked  # Interior of an unfilled circle is not a geometry hit.
