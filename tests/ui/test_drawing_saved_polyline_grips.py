# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Saved straight polyline grips remain editable and replayable."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.persistence import save_document
from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.main_window import MainWindow


def test_saved_straight_polyline_vertex_drag_undo_redo_and_reopen(
    qtbot: QtBot, tmp_path: Path
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    path = PolylineEntity(uuid4().hex, ((-10, 0), (10, 0), (10, 10)))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (path,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 5)))
    assert canvas.selected_entity_ids == {path.entity_id}
    assert canvas.control_point_at((10, 0)) is not None
    before = services.kernel.sketches
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    QTest.mouseMove(canvas, canvas.local_to_screen((12, -3)))
    qtbot.waitUntil(lambda: bool(canvas.saved_handle_preview), timeout=15000)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((12, -3)))
    qtbot.waitUntil(
        lambda: (
            services.kernel.sketches != before
            and not unit.is_busy
            and not unit.is_delivering_result
        ),
        timeout=15000,
    )
    moved = services.kernel.sketches[0].entities[0]
    assert isinstance(moved, PolylineEntity)
    assert moved.points_mm[1] == pytest.approx((12, -3), abs=0.15)
    assert moved.entity_id == path.entity_id and moved.bulges == ()
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches == before
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0] == moved
    file_path = tmp_path / "polyline-grip.my2d"
    save_document(loaded.document, file_path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, file_path)
    assert reopened.kernel.sketches[0].entities[0] == moved


def test_saved_straight_polyline_fixed_vertex_cannot_be_dragged(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    path = PolylineEntity(uuid4().hex, ((-10, 0), (10, 0), (10, 10)))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(path.entity_id, "vertex", 1),)
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (path,), (fixed,)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 5)))
    before = tuple(loaded.document.commands)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    QTest.mouseMove(canvas, canvas.local_to_screen((12, -3)))
    qtbot.waitUntil(lambda: "固定" in canvas.message, timeout=15000)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((12, -3)))
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert tuple(loaded.document.commands) == before
    assert services.kernel.sketches[0].entities == (path,)
    assert services.kernel.sketches[0].constraints == (fixed,)
