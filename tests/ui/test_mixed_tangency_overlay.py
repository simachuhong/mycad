# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Mixed edits display the geometry produced by the tangency solver."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
from mycad.core.persistence import save_document
from mycad.core.sketch import (
    CircleEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    WorkPlaneFrame,
)
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("polyline", [False, True])
def test_mixed_move_displays_solved_rectangle_follower(
    qtbot: QtBot, tmp_path: Path, polyline: bool
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = (
        PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -10), (0, -10)), closed=True)
        if polyline
        else RectangleEntity(uuid4().hex, (0, 0), (10, -10))
    )
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    app.commit_cross_sketch_tangency(
        services,
        loaded,
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(first.sketch_id, rectangle.entity_id, 0),
            CrossSketchRef(second.sketch_id, circle.entity_id),
            "line_left",
        ),
        session_identity=0,
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    line = LineEntity(uuid4().hex, (20, 0), (25, 0))
    assert editor.canvas.replace_draft_entities((line,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {circle.entity_id, line.entity_id}
    for value in ("MOVE", "0,0", "0,3"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    mixed = editor.canvas.mixed_move
    assert mixed is not None, editor.status_label.text()
    solved = next(
        item
        for sketch in mixed.current_saved
        for item in sketch.entities
        if item.entity_id == rectangle.entity_id
    )
    shown = next(
        item for item, _ in mixed.overlay_background if item.entity_id == rectangle.entity_id
    )
    assert solved != rectangle
    assert shown == solved
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.mixed_move is None
    assert editor.canvas.redo_last_operation()
    restored = editor.canvas.mixed_move
    assert restored is not None and restored.overlay_background == mixed.overlay_background
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
    )
    assert services.kernel.sketches[0].entities[0] == solved
    path = tmp_path / "mixed.my2d"
    save_document(loaded.document, path)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert services.kernel.sketches[0].entities[0] == rectangle
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities[0] == solved
