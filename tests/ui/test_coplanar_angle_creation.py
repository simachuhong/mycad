# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Angle dimensions preserve orientation between coplanar sketch frames."""

import math
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.cross_sketch_tangency import project_coplanar_entity
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("opposite", [False, True])
def test_create_angle_in_rotated_frame(qtbot: QtBot, tmp_path: Path, opposite: bool) -> None:
    q = math.sqrt(0.5)
    frame = WorkPlaneFrame(
        (5, 7, 0),
        (q, q, 0),
        (q, -q, 0) if opposite else (-q, q, 0),
        (0, 0, -1) if opposite else (0, 0, 1),
    )
    view = (
        LineEntity(uuid4().hex, (0, 0), (20, 0)),
        LineEntity(uuid4().hex, (0, 0), (0, 20)),
    )
    entities = tuple(project_coplanar_entity(item, WorkPlaneFrame.xy(), frame) for item in view)
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, frame, entities), session_identity=0
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["angle"].click()
    canvas = editor.canvas
    for point in ((10, 0), (0, 10)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert editor.dimensions.candidate is not None
    QTest.mouseMove(canvas, canvas.local_to_screen((8, 8)))
    shown = canvas.dimension_candidate
    assert shown is not None
    layout = canvas.dimension_layout(shown, canvas.dimension_entities())
    assert layout is not None
    start, end = layout.lines[-1]
    assert end.y() < start.y() and abs(end.x() - start.x()) < 1
    count = len(loaded.document.commands)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8, 8)))
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    dimension = services.kernel.sketches[0].constraints[0]
    assert dimension.value == pytest.approx(-90 if opposite else 90)
    path = tmp_path / "angle.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert not services.kernel.sketches[0].constraints
    loaded.bus.redo()
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches[0].constraints == (dimension,)


@pytest.mark.parametrize("opposite", [False, True])
def test_create_driving_angle_in_rotated_frame(qtbot: QtBot, opposite: bool) -> None:
    q = math.sqrt(0.5)
    frame = WorkPlaneFrame(
        (5, 7, 0),
        (q, q, 0),
        (q, -q, 0) if opposite else (-q, q, 0),
        (0, 0, -1) if opposite else (0, 0, 1),
    )
    view = (
        LineEntity(uuid4().hex, (0, 0), (20, 0)),
        LineEntity(uuid4().hex, (0, 0), (0, 20)),
    )
    entities = tuple(project_coplanar_entity(item, WorkPlaneFrame.xy(), frame) for item in view)
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, frame, entities), session_identity=0
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["angle"].click()
    canvas = editor.canvas
    for point in ((10, 0), (0, 10), (8, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    editor.dimensions.value_editor.setValue(-60 if opposite else 60)
    candidate, original = editor.dimensions.candidate, editor.dimensions.original
    assert candidate is not None and original is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, candidate) is not None, timeout=10000
    )
    preview = editor.dimensions.accepted_preview(original, candidate)
    assert preview is not None and preview.status == "success"
    assert canvas.dimension_preview is not None
    count = len(loaded.document.commands)
    editor.dimensions.apply_button.click()
    if preview.branch_changes:
        editor.dimensions.apply_button.click()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    result = services.kernel.sketches[0]
    assert result.constraints[0].value == pytest.approx(-60 if opposite else 60)
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == entities
    assert not services.kernel.sketches[0].constraints
