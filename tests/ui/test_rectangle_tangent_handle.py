# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Dragging a tangent circle updates the rectangle follower preview."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
from mycad.core.persistence import save_document
from mycad.core.sketch import CircleEntity, LineEntity, RectangleEntity, Sketch, WorkPlaneFrame
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("with_draft", [False, True])
def test_circle_handle_previews_and_commits_rectangle_follower(
    qtbot: QtBot, tmp_path: Path, with_draft: bool
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, -10))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    if with_draft:
        unrelated = Sketch(
            uuid4().hex,
            WorkPlaneFrame.xz(),
            (LineEntity(uuid4().hex, (30, 0), (35, 0)),),
        )
        app.commit_new_sketch(services, loaded, unrelated, session_identity=0)
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
    canvas = editor.canvas
    if with_draft:
        draft_circle = CircleEntity(uuid4().hex, (9, 2), 2)
        assert canvas.replace_draft_entities((draft_circle,))
        canvas.pending_cross_tangencies = [(circle.entity_id, draft_circle.entity_id)]
    editor.snap_check.setChecked(False)
    assert canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    assert circle.entity_id in canvas.selected_entity_ids
    before = services.kernel.sketches
    start, end = canvas.local_to_screen((5, 2)), canvas.local_to_screen((5, 3))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    qtbot.waitUntil(lambda: bool(canvas.saved_handle_preview), timeout=15000)
    preview = canvas.saved_handle_preview
    assert any(entity.entity_id == rectangle.entity_id for entity, _layer in preview)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    if with_draft:
        qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=15000)
        mixed = canvas.mixed_move
        assert mixed is not None and mixed.current_saved[0].entities[0] != rectangle
        assert services.kernel.sketches == before
        assert canvas.undo_last_operation() and canvas.mixed_move is None
        assert canvas.redo_last_operation() and canvas.mixed_move is not None
        editor.finish_sketch()
        qtbot.waitUntil(
            lambda: not unit.is_busy and window.active_sketch_dialog() is not editor,
            timeout=15000,
        )
        assert services.kernel.sketches[0].entities[0] != rectangle
        assert services.kernel.sketches[2] == before[2]
    else:
        qtbot.waitUntil(
            lambda: not unit.is_busy and services.kernel.sketches != before, timeout=15000
        )
        assert services.kernel.sketches[0].entities[0] != rectangle
        loaded.bus.undo()
        assert services.kernel.sketches == before
        loaded.bus.redo()
        assert services.kernel.sketches[0].entities[0] != rectangle
    final = services.kernel.sketches
    path = tmp_path / "rectangle-handle.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == final
