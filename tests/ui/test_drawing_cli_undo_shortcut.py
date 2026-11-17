# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The drawing command console forwards document undo and redo shortcuts."""

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow


def test_cli_focus_undo_and_redo_drawing_without_losing_input(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    command = editor.drawing_command_bar.input
    for text in ("POINT", "10,20"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1
    point = editor.canvas.entities[0]
    command.setText("LIN")
    command.setFocus()
    QTest.keyClick(command, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert not editor.canvas.entities
    assert command.text() == "LIN"
    QTest.keyClick(command, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert editor.canvas.entities == [point]
    assert command.text() == "LIN"


def test_cli_shortcut_undoes_and_redoes_committed_sketch(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    command = editor.drawing_command_bar.input
    for text in ("POINT", "10,20"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: bool(entry.services.kernel.sketches) and not unit.is_busy,
        timeout=20000,
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    command = editor.drawing_command_bar.input
    command.setFocus()
    QTest.keyClick(command, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=20000)
    assert not entry.services.kernel.sketches
    QTest.keyClick(
        command,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=20000)
    assert len(entry.services.kernel.sketches) == 1


def test_cli_undo_during_input_method_composition_preserves_drawing(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    command = editor.drawing_command_bar.input
    for text in ("POINT", "10,20"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    command.setFocus()
    QCoreApplication.sendEvent(command, QInputMethodEvent("拼", []))
    QTest.keyClick(command, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert len(editor.canvas.entities) == 1
