# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Point creation from the drawing command window."""

from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.persistence import save_document
from mycad.core.sketch import PointEntity
from mycad.core.sketch_layers import SketchLayer
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog


def test_point_command_creates_undoes_and_reopens(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    bar = editor.drawing_command_bar
    for text in ("POINT", "10,20"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1, bar.status.text()
    point = editor.canvas.entities[0]
    assert isinstance(point, PointEntity) and point.position_mm == (10, 20)
    window.request_undo()
    assert not editor.canvas.entities
    window.request_redo()
    assert editor.canvas.entities == [point]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: bool(entry.services.kernel.sketches) and not unit.is_busy, timeout=20000
    )
    path = tmp_path / "point.my2d"
    save_document(entry.loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches[0].entities == (point,)


def test_point_button_places_one_point_and_returns_to_selection(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    editor.snap_check.setChecked(False)
    editor.tool_buttons["点"].click()
    pixel = editor.canvas.local_to_screen((10, 20))
    expected = editor.canvas.screen_to_local(QPointF(pixel))
    QTest.mouseClick(editor.canvas, Qt.MouseButton.LeftButton, pos=pixel)
    assert len(editor.canvas.entities) == 1
    point = editor.canvas.entities[0]
    assert isinstance(point, PointEntity) and point.position_mm == expected
    assert editor.canvas.tool == "选择元素"


def test_point_command_rejects_locked_current_layer(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    layers = editor.layer_table.add(SketchLayer("锁定", locked=True))
    editor.set_document_layers(layers, "DIM")
    editor.layer_combo.setCurrentText("锁定")
    bar = editor.drawing_command_bar
    for text in ("PO", "10,20"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert not editor.canvas.entities
    assert "锁定" in bar.status.text()
