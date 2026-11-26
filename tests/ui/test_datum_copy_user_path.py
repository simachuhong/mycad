# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exercise copying a complete datum through drawing controls."""

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.geometric_tolerance import DatumIdentifier
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("method", ["command", "clipboard"])
def test_copy_datum_with_actual_controls(
    qtbot: QtBot, monkeypatch: MonkeyPatch, method: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier("4" * 32, "A", (10, 10), (0, 0), layout_mode="shared")
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    assert tools.selected_id == datum.datum_id

    def label_b(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "B", True

    monkeypatch.setattr(QInputDialog, "getText", label_b)
    if method == "command":
        for command in ("COPY", "0,0", "5,3"):
            editor.drawing_command_bar.input.setText(command)
            QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    else:
        canvas.setFocus()
        QTest.keyClick(canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, 13)))
    assert len(services.kernel.drawing_datum_identifiers) == 2
    copied = services.kernel.drawing_datum_identifiers[1]
    assert copied.datum_id != datum.datum_id and copied.label == "B"
    assert copied.position_mm == pytest.approx((15, 13))


@pytest.mark.parametrize("method", ["command", "clipboard"])
def test_copy_datum_suggests_unique_name_in_actual_dialog(qtbot: QtBot, method: str) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    datum = DatumIdentifier("5" * 32, "A", (10, 10), (0, 0), layout_mode="shared")
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(datum).center().toPoint()
    )
    defaults: list[str] = []

    def accept_default() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        defaults.append(dialog.textValue())
        dialog.accept()

    if method == "command":
        for command in ("COPY", "0,0"):
            editor.drawing_command_bar.input.setText(command)
            QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
        QTimer.singleShot(50, accept_default)
        editor.drawing_command_bar.input.setText("5,3")
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    else:
        canvas.setFocus()
        QTest.keyClick(canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        QTimer.singleShot(50, accept_default)
        QTest.keyClick(canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, 13)))
    assert defaults == ["B"]
    assert len(services.kernel.drawing_datum_identifiers) == 2
    assert services.kernel.drawing_datum_identifiers[1].label == "B"


def test_copy_multiple_datums_suggests_distinct_names(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    first = DatumIdentifier("6" * 32, "A", (10, 10), (0, 0), layout_mode="shared")
    second = DatumIdentifier("7" * 32, "B", (30, 10), (25, 0), layout_mode="shared")
    assert tools.execute(
        "drawing.tolerance.batch", {"add_datums": [first.to_mapping(), second.to_mapping()]}
    )
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=tools.datum_screen_bounds(first).center().toPoint()
    )
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        tools.datum_screen_bounds(second).center().toPoint(),
    )
    assert tools.selected_ids == {first.datum_id, second.datum_id}
    defaults: list[str] = []

    def accept_next() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        defaults.append(dialog.textValue())
        dialog.accept()
        if len(defaults) < 2:
            QTimer.singleShot(50, accept_next)

    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    QTimer.singleShot(50, accept_next)
    QTest.keyClick(canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((40, 20)))
    assert defaults == ["C", "D"]
    assert {item.label for item in services.kernel.drawing_datum_identifiers} == {
        "A",
        "B",
        "C",
        "D",
    }
