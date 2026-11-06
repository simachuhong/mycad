# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent drawing circle fillet interaction."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import ArcEntity, CircleEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def test_fillet_tool_button_starts_the_same_canvas_command(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    QTest.mouseClick(editor.tool_buttons["二维圆角"], Qt.MouseButton.LeftButton)
    assert editor.canvas.tool == "二维圆角"
    assert "不修剪" in editor.canvas.message


def test_fillet_toolbar_activation_updates_repeat_command(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    command.setText("CIRCLE")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(editor.tool_buttons["二维圆角"], Qt.MouseButton.LeftButton)
    assert editor.canvas.tool == "二维圆角"
    command.clear()
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.tool == "二维圆角"


def test_fillet_radius_continues_with_document_but_not_another_editor(qtbot: QtBot) -> None:
    previous = SketchEditorDialog(select_committed_entities=True)
    continued = SketchEditorDialog(select_committed_entities=True)
    unrelated = SketchEditorDialog(select_committed_entities=True)
    for editor in (previous, continued, unrelated):
        qtbot.addWidget(editor)
        editor.show()
    command = previous.drawing_command_bar.input
    for text in ("FILLET", "R", "4"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    continued.continue_workspace_from(previous)
    QTest.keyClick(continued.drawing_command_bar.input, Qt.Key.Key_Return)
    assert continued.canvas.tool == "二维圆角"
    assert continued.canvas.circle_fillet_radius == 4
    assert unrelated.canvas.circle_fillet_radius == 1


def test_circle_fillet_command_creates_one_arc_without_trimming(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    canvas.entities = [first, second]
    command = editor.drawing_command_bar.input
    for text in ("FILLET", "R", "4"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1.7, 1.1)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8.3, 1.1)))
    assert canvas.entities[:2] == [first, second]
    assert len(canvas.entities) == 3
    arc = canvas.entities[2]
    assert isinstance(arc, ArcEntity)
    assert arc.radius_mm == pytest.approx(4)
    assert arc.center_mm[1] > 0
    assert canvas.undo_last_operation()
    assert canvas.entities == [first, second]


def test_fillet_invalid_radius_and_cancel_leave_circles_unchanged(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    canvas.entities = [first, second]
    command = editor.drawing_command_bar.input
    for text in ("F", "R", "0"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    command.clear()
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert "半径" in editor.drawing_command_bar.status.text()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1.7, 1.1)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8.3, 1.1)))
    assert canvas.entities == [first, second]
    assert not canvas.has_active_edit_gesture
    command.setText("4")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1.7, 1.1)))
    assert canvas.has_active_edit_gesture
    command.clear()
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.has_active_edit_gesture
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.has_active_edit_gesture
    assert canvas.entities == [first, second]


def test_fillet_on_committed_circles_survives_save_and_reopen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert draft.canvas.replace_draft_entities(circles)
    draft.finish_button.click()
    qtbot.waitUntil(
        lambda: (
            window.active_sketch_dialog() is not None
            and window.active_sketch_dialog() is not draft
            and not unit.is_busy
        ),
        timeout=10000,
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    command = editor.drawing_command_bar.input
    for text in ("FILLET", "R", "4"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((1.7, 1.1))
    )
    assert editor.canvas.has_active_edit_gesture
    loaded = window.loaded_document()
    assert loaded is not None
    commands = loaded.document.commands
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert loaded.document.commands == commands
    assert editor.canvas.has_active_edit_gesture
    assert "取消" in window.status_command.text()
    window.request_redo()
    assert "取消" in window.status_command.text()
    assert loaded.document.commands == commands
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((8.3, 1.1))
    )
    assert len(editor.canvas.entities) == 1
    arc = editor.canvas.entities[0]
    assert isinstance(arc, ArcEntity)
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: (
            window.active_sketch_dialog() is not None
            and window.active_sketch_dialog() is not editor
            and not unit.is_busy
        ),
        timeout=10000,
    )
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    assert submitted.canvas.circle_fillet_radius == 4
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    after_undo = window.active_sketch_dialog()
    assert after_undo is not None
    assert arc not in tuple(entity for entity, _layer in after_undo.canvas.background_entities)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    assert arc in tuple(entity for entity, _layer in submitted.canvas.background_entities)
    path = tmp_path / "fillet.mc.json"

    def choose_file(*_args: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose_file)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose_file)
    window.act_save.trigger()
    assert path.is_file()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: (
            window.active_sketch_dialog() is not None
            and window.active_sketch_dialog() is not submitted
            and not unit.is_busy
        ),
        timeout=10000,
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    entities = tuple(entity for entity, _layer in reopened.canvas.background_entities)
    assert all(circle in entities for circle in circles)
    assert arc in entities


def test_fillet_no_solution_can_change_radius_without_reselecting_first(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    canvas.entities = list(circles)
    command = editor.drawing_command_bar.input
    command.setText("FILLET")
    QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities == list(circles)
    assert canvas.has_active_edit_gesture
    assert "无法" in canvas.message
    for text in ("R", "4"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8.3, 1.1)))
    assert isinstance(canvas.entities[-1], ArcEntity)
    assert not canvas.has_active_edit_gesture


def test_fillet_does_not_create_geometry_on_locked_active_layer(qtbot: QtBot) -> None:
    from dataclasses import replace

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    canvas.entities = list(circles)
    locked = editor.layer_table.replace(replace(editor.layer_table.get("0"), locked=True))
    canvas.set_layer_table(locked, "0")
    command = editor.drawing_command_bar.input
    command.setText("FILLET")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1.7, 1.1)))
    assert canvas.entities == list(circles)
    assert not canvas.has_active_edit_gesture
    assert "锁定" in canvas.message
