# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Direct planar placement works in a standalone drawing without HLR or dialogs."""

import math
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.core.drawing_projection import ProjectionResult, ViewBasis
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.drawing_updates import ProjectionUpdates
from mycad.ui.main_window import MainWindow


def test_sketch_entry_preview_commit_cancel_and_document_switch(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    sketches = tuple(
        Sketch(
            str(uuid4()),
            WorkPlaneFrame.xy(),
            (LineEntity(str(uuid4()), (0, 0), (40 + index * 10, 0)),),
        )
        for index in range(2)
    )
    for sketch in sketches:
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3))

    def no_hlr() -> None:
        pytest.fail("a planar view must not start a solid projection worker")

    monkeypatch.setattr("mycad.app.create_drawing_worker", no_hlr)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench = window.drawing_workbench
    assert bench.sketch_view_button.isEnabled()
    assert not bench.base_action.isEnabled()
    assert bench.sketch_source.count() == 2
    bench.sketch_source.setCurrentIndex(1)
    QTest.mouseClick(bench.sketch_view_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bench.canvas.placing)
    assert bench.canvas.isVisible()
    canvas = bench.canvas
    position = canvas.mapFromScene(QPointF(100, -100))
    QTest.mouseMove(canvas.viewport(), position)
    assert canvas.drawing_scene is not None and canvas.drawing_scene.views
    assert bench.placement is not None
    assert bench.placement.source.sketch_id == sketches[1].sketch_id
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=position)
    assert bench.placement is not None and len(bench.placement.pending) == 1
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=position)
    assert len(bench.placement.pending) == 1
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_state.views) == 1 and bench.placement is None
    )
    assert bench.output_scene().views[0].curves
    bench.sketch_view_action.trigger()
    assert bench.canvas.placing
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert bench.placement is None
    assert len(services.kernel.drawing_state.views) == 1
    replacement = new_document(services, document_type="drawing2d")
    window.bind_document(replacement)
    assert bench.sketch_source.count() == 0
    assert not bench.sketch_view_button.isEnabled()
    assert not bench.projections


def test_pending_preview_pauses_when_source_changes(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    sketch = Sketch(str(uuid4()), WorkPlaneFrame.xy(), (LineEntity(str(uuid4()), (0, 0), (40, 0)),))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    bench = window.drawing_workbench
    bench.begin_sketch_placement()
    qtbot.waitUntil(lambda: bench.canvas.placing)
    bench.canvas.paper_clicked.emit((100, 100))
    loaded.bus.execute(
        "sketch.create",
        Sketch(str(uuid4()), WorkPlaneFrame.xy(), sketch.entities).to_mapping(version=3),
    )
    bench.refresh()
    assert not bench.canvas.placing
    bench.commit_placement()
    assert not services.kernel.drawing_state.views
    bench.update_requested()
    assert bench.canvas.placing
    bench.commit_placement()
    qtbot.waitUntil(lambda: len(services.kernel.drawing_state.views) == 1)


def test_source_changes_invalidate_even_when_fingerprint_and_basis_match() -> None:
    updates = ProjectionUpdates()
    view = uuid4()
    sketch = str(uuid4())
    updates.sync(1, "fp", {view: ViewBasis()}, sketch_ids={view: sketch})
    batch = updates.begin(source="sketch")
    assert batch is not None
    updates.finish(batch, (ProjectionResult(view, "fp", batch.requests[0].generation, ()),))
    assert updates.status(view) == "clean"
    updates.sync(1, "fp", {view: ViewBasis()}, sketch_ids={view: str(uuid4())})
    assert updates.status(view) == "stale"
    updates.retry()
    retried = updates.begin(source="sketch")
    assert retried is not None
    assert retried.requests[0].source == "sketch"
    assert retried.requests[0].sketch_id != sketch


def test_driven_source_updates_annotation_archive_and_exports(
    qtbot: QtBot, tmp_path: "Path"
) -> None:
    from PySide6.QtPdf import QPdfDocument

    from mycad.app import open_app_document
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.formats.drawing_export import export_drawing_dxf
    from mycad.ui.drawing_pdf import export_drawing_pdf
    from tests.formats.test_drawing_export import tags

    services = build_app(discoverers=[])
    loaded = new_document(services, document_type="drawing2d")
    line = LineEntity(str(uuid4()), (0, 0), (40, 0))
    sketch = Sketch(str(uuid4()), WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3))
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    bench = window.drawing_workbench
    bench.scale.setValue(0.5)
    bench.begin_sketch_placement()
    qtbot.waitUntil(lambda: bench.canvas.placing)
    bench.canvas.paper_clicked.emit((100, 100))
    bench.commit_placement()
    qtbot.waitUntil(lambda: bench.placement is None)
    view = services.kernel.drawing_state.views[0]
    curve = bench.projections[view.view_id].curves[0]
    bench.annotations.begin("aligned")
    bench.annotations.choose(view.view_id, curve.curve_id, (110, 100))
    bench.canvas.paper_clicked.emit((110, 115))
    qtbot.waitUntil(lambda: len(services.kernel.drawing_state.annotations) == 1)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert bench.output_scene().resolved_annotations[0].value == 40
    constraint = SketchConstraint(
        str(uuid4()),
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value=60,
        unit="mm",
        anchor_mode="start",
    )
    solved = services.kernel.preview_sketch_constraint(sketch, constraint)
    assert solved.status == "success", solved.message
    loaded.bus.execute("sketch.constraint.add", solved.command_params(sketch, constraint))
    # The pure 2D update may finish synchronously in the Bus event callback.
    try:
        updated = bench.output_scene()
    except ValueError:
        pass
    else:
        assert updated.resolved_annotations[0].value == pytest.approx(60)
    bench.refresh()
    qtbot.waitUntil(lambda: not unit.is_busy and bench.updates.status(view.view_id) == "clean")
    scene = bench.output_scene()
    assert scene.resolved_annotations[0].value == pytest.approx(60)
    a, b = scene.resolved_annotations[0].anchors
    assert math.dist(a, b) == pytest.approx(30)
    native = tmp_path / "flat.my2d"
    save_document(loaded.document, native)
    window.bind_document(open_app_document(services, native))
    qtbot.waitUntil(lambda: not unit.is_busy and bench.updates.status(view.view_id) == "clean")
    scene = bench.output_scene()
    assert scene.resolved_annotations[0].text == "60.00 mm"
    dxf, pdf = tmp_path / "flat.dxf", tmp_path / "flat.pdf"
    export_drawing_dxf(scene, dxf)
    export_drawing_pdf(scene, pdf)
    data = tags(dxf)
    assert (1, "60.00 mm") in data
    assert (41, "0.5") in data
    document = QPdfDocument()
    assert document.load(str(pdf)) == QPdfDocument.Error.None_
    assert "60.00 mm" in document.getAllText(0).text()
    assert b"/Subtype /Image" not in pdf.read_bytes()


def test_mixed_sources_and_layer_visibility_update_without_stale_export(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import Future
    from dataclasses import replace

    from mycad.core.drawing_projection import DrawingProjectionRequest, DrawingSourceSnapshot
    from mycad.core.sketch_layers import SketchLayerTable

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10})
    sketch = Sketch(str(uuid4()), WorkPlaneFrame.xy(), (LineEntity(str(uuid4()), (0, 0), (40, 0)),))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3))
    sheet, solid, flat = (str(uuid4()) for _ in range(3))
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": sheet})
    loaded.bus.execute(
        "drawing.view.create",
        {
            "views": [
                {"sheet_id": sheet, "view_id": solid, "anchor_mm": [60, 100]},
                {
                    "sheet_id": sheet,
                    "view_id": flat,
                    "anchor_mm": [130, 100],
                    "source": {"kind": "sketch", "sketch_id": sketch.sketch_id},
                },
            ]
        },
    )
    requests_seen: list[DrawingProjectionRequest] = []

    class Worker:
        def submit(
            self, snapshot: DrawingSourceSnapshot, requests: tuple[DrawingProjectionRequest, ...]
        ) -> Future[tuple[ProjectionResult, ...]]:
            requests_seen.extend(requests)
            assert all(request.source == "current_part" for request in requests)
            assert all(
                request.source_fingerprint == snapshot.source_fingerprint for request in requests
            )
            future: Future[tuple[ProjectionResult, ...]] = Future()
            future.set_result(
                tuple(services.kernel.project_drawing(request) for request in requests)
            )
            return future

        def close(self) -> None:
            pass

        def restart(self) -> None:
            pass

    monkeypatch.setattr("mycad.app.create_drawing_worker", Worker)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    bench = window.drawing_workbench
    qtbot.waitUntil(
        lambda: (
            bool(requests_seen)
            and all(
                bench.updates.status(view.view_id) == "clean"
                for view in services.kernel.drawing_state.views
            )
        )
    )
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert len(bench.output_scene().views) == 2
    layers = SketchLayerTable(
        tuple(replace(layer, frozen=True) for layer in services.kernel.drawing_layers.layers)
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}
    )
    with pytest.raises(ValueError, match="过期|尚未就绪"):
        bench.output_scene()
    bench.refresh()
    qtbot.waitUntil(
        lambda: all(
            bench.updates.status(view.view_id) == "clean"
            for view in services.kernel.drawing_state.views
        )
    )
    qtbot.waitUntil(lambda: not unit.is_busy)
    scene = bench.output_scene()
    assert scene.views[0].curves
    assert not scene.views[1].curves
