# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Direct planar placement works in a standalone drawing without HLR or dialogs."""

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
