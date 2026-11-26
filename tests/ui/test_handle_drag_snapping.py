# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Endpoint grip previews and release use the same object snap for draft and saved geometry."""

from uuid import uuid4

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.sketch import ArcEntity, LineEntity, RectangleEntity, Sketch, WorkPlaneFrame
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("saved", [False, True], ids=["draft", "saved"])
@pytest.mark.parametrize("snapping", [True, False], ids=["snap-on", "snap-off"])
def test_endpoint_drag_snaps_preview_and_commit(qtbot: QtBot, saved: bool, snapping: bool) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    canvas.setFixedSize(900, 600)
    QApplication.processEvents()
    line = LineEntity(uuid4().hex, (0, 0), (20, 15))
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (50, 30))
    arc = ArcEntity(uuid4().hex, (50, 15), 15, -90, 180)
    geometry = (line, rectangle, arc)
    if saved:
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), geometry),
            session_identity=0,
        )
        editor.set_context_sketches(services.kernel.sketches)
    else:
        assert canvas.replace_draft_entities(geometry)
    assert canvas.set_tool("选择元素")
    canvas.set_snapping_enabled(snapping)
    canvas.selected_entity_ids = {line.entity_id}
    canvas.changed.emit()
    start = canvas.local_to_screen(line.end_mm)
    near_end = canvas.local_to_screen((50, 30)) + QPoint(-4, 3)
    raw = canvas.screen_to_local(QPointF(near_end))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    assert canvas.saved_handle_drag_active if saved else canvas.draft_handle_drag_active
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(near_end),
            QPointF(canvas.mapToGlobal(near_end)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert canvas.current_snap_kind == ("端点" if snapping else "")
    if saved:
        qtbot.waitUntil(lambda: bool(canvas.saved_handle_preview), timeout=15000)
        preview = next(
            item for item, _layer in canvas.saved_handle_preview if item.entity_id == line.entity_id
        )
    else:
        preview = next(item for item in canvas.entities if item.entity_id == line.entity_id)
    assert isinstance(preview, LineEntity)
    assert preview.end_mm == pytest.approx((50, 30) if snapping else raw)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=near_end)
    if saved:
        qtbot.waitUntil(
            lambda: not unit.is_busy and not canvas.saved_handle_drag_active, timeout=15000
        )
        result = services.kernel.sketches[0].entities
    else:
        result = tuple(canvas.entities)
    moved = next(item for item in result if item.entity_id == line.entity_id)
    assert isinstance(moved, LineEntity)
    assert moved.end_mm == pytest.approx((50, 30) if snapping else raw)
    assert rectangle in result and arc in result
    if saved:
        window.request_undo()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert services.kernel.sketches[0].entities == geometry
        window.request_redo()
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
        assert services.kernel.sketches[0].entities == result
    else:
        assert canvas.undo_last_operation()
        assert tuple(canvas.entities) == geometry
        assert canvas.redo_last_operation()
        assert tuple(canvas.entities) == result
