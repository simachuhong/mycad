# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Interactive 2D commands share the bottom console with CLI."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPlainTextEdit
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow


def test_drawing_console_is_single_editable_command_transcript(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("sketch")
    editor, cli = window.active_sketch_dialog(), window.cli_tab
    assert editor is not None and cli is not None
    command = editor.drawing_command_bar.input
    assert isinstance(command, QPlainTextEdit)
    assert not cli.output.isVisible()
    window.activateWindow()
    command.setFocus()
    QTest.keyClicks(command, "LINE")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert "LINE" in command.toPlainText()
    assert editor.canvas.tool == "直线"
    history = command.toPlainText()
    QTest.keyClick(command, Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(command, Qt.Key.Key_Backspace)
    assert command.toPlainText() == history
    QTest.keyClick(command, Qt.Key.Key_Up)
    assert command.text() == "LINE"
    QTest.keyClick(command, Qt.Key.Key_Down)
    assert command.text() == ""
    QTest.keyClicks(command, "0,0")
    QTest.keyClick(command, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(command, Qt.Key.Key_Backspace)
    assert command.toPlainText() == history


def test_two_object_tangent_entry_in_main_window(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    window.activateWindow()
    assert canvas.replace_draft_entities(
        (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    )
    editor.tool_buttons["圆"].click()
    assert editor.tangent_capture_button.isVisible()
    editor.tangent_capture_button.click()
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseMove(canvas, canvas.local_to_screen(point))
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    canvas.setFocus()
    qtbot.waitUntil(canvas.hasFocus, timeout=10000)
    QTest.keyClicks(canvas, "4")
    focused = QApplication.focusWidget()
    assert focused is not None
    QTest.keyClick(focused, Qt.Key.Key_Return)
    assert len(canvas.entities) == 3
    assert isinstance(canvas.entities[-1], CircleEntity)


def test_canvas_keyboard_starts_command_without_clicking_console(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    tabs = window.bottom_tabs
    assert editor is not None and tabs is not None
    canvas, bar = editor.canvas, editor.drawing_command_bar
    window.activateWindow()
    canvas.set_tool("选择元素")
    tabs.set_expanded(False)
    canvas.setFocus()
    qtbot.waitUntil(canvas.hasFocus, timeout=10000)
    QTest.keyClick(canvas, Qt.Key.Key_L)
    assert tabs.expanded
    assert QApplication.focusWidget() is bar.input
    assert bar.input.text().lower() == "l"
    QTest.keyClicks(bar.input, "ine")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.tool == "直线"
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_0)
    assert QApplication.focusWidget() is bar.input
    QTest.keyClicks(bar.input, ",0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClicks(bar.input, "10,0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1
    canvas.set_tool("选择元素")
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_Space)
    assert canvas.tool == "直线"


def test_bottom_console_uses_active_drawing_command_input(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    first = window.new_session_document("sketch")
    editor, cli, tabs = window.active_sketch_dialog(), window.cli_tab, window.bottom_tabs
    assert editor is not None and cli is not None and tabs is not None
    assert cli.drawing_bar is editor.drawing_command_bar
    assert not cli.input.isVisible()
    assert editor.drawing_command_bar.isVisible()
    for entry in ("LINE", "0,0", "10,0"):
        editor.drawing_command_bar.input.setText(entry)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1
    assert "LINE" in cli.output.toPlainText()
    second = window.new_session_document("sketch")
    other = window.active_sketch_dialog()
    assert other is not None and cli.drawing_bar is other.drawing_command_bar
    assert not other.canvas.entities
    assert "命令: LINE" not in cli.output.toPlainText()
    window.activate_session_document(first.loaded.document.document_id)
    assert cli.drawing_bar is editor.drawing_command_bar
    assert len(editor.canvas.entities) == 1
    assert "命令: LINE" in cli.output.toPlainText()
    window.activate_session_document(second.loaded.document.document_id)
    assert cli.drawing_bar is other.drawing_command_bar
    window.new_session_document("part")
    tabs.show_page(cli)
    assert cli.drawing_bar is None
    assert cli.input.isVisible()
    cli.input.setText("quit")
    QTest.keyClick(cli.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: "hint: use File" in cli.output.toPlainText(), timeout=10000)


def test_command_history_survives_finishing_drawing(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("sketch")
    editor, cli, unit = window.active_sketch_dialog(), window.cli_tab, window.execution_unit
    assert editor is not None and cli is not None and unit is not None
    for entry in ("LINE", "0,0", "10,0", ""):
        editor.drawing_command_bar.input.setText(entry)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: (
            window.active_sketch_dialog() is not None
            and window.active_sketch_dialog() is not editor
            and not unit.is_busy
        ),
        timeout=20000,
    )
    current = window.active_sketch_dialog()
    assert current is not None and cli.drawing_bar is current.drawing_command_bar
    assert "命令: LINE" in cli.output.toPlainText()


def test_canvas_keyboard_routes_trim_option_to_console(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    window.activateWindow()
    editor.canvas.set_line_edit_standard_mode(False)
    assert editor.canvas.set_tool("修剪")
    editor.canvas.setFocus()
    qtbot.waitUntil(editor.canvas.hasFocus, timeout=10000)
    assert not editor.canvas.has_active_edit_gesture, editor.canvas.message
    QTest.keyClick(editor.canvas, Qt.Key.Key_F)
    assert editor.drawing_command_bar.input.text().lower() == "f"
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert editor.canvas.trim_fence_active
