# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Polygon CLI creates the same geometry as the drawing tool."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import PolylineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def submit(editor: SketchEditorDialog, value: str) -> None:
    editor.drawing_command_bar.input.setText(value)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)


def test_polygon_sides_center_mode_and_radius(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    for value in ("POLYGON", "4", "0,0", "I", "10"):
        submit(editor, value)
    assert len(editor.canvas.entities) == 1
    polygon = editor.canvas.entities[0]
    assert isinstance(polygon, PolylineEntity)
    assert len(polygon.points_mm) == 4
    assert polygon.points_mm[0] == pytest.approx((10, 0))
    assert editor.canvas.undo_last_operation()
    assert not editor.canvas.entities


def test_polygon_mouse_center_circumscribed_and_repeat(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    submit(editor, "POL")
    submit(editor, "4")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    submit(editor, "C")
    submit(editor, "10")
    polygon = editor.canvas.entities[0]
    assert isinstance(polygon, PolylineEntity)
    assert polygon.points_mm[0] == pytest.approx((10, 10))
    assert editor.polygon_mode_combo.currentText() == "外切圆"
    submit(editor, "")
    assert "边数" in editor.drawing_command_bar.status.text()
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert editor.canvas.tool == "选择元素"


def test_polygon_rejects_invalid_parameters(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    for value in ("POLYGON", "2"):
        submit(editor, value)
    assert "3–128" in editor.drawing_command_bar.status.text()
    for value in ("4", "0,0", "X"):
        submit(editor, value)
    assert "内接" in editor.drawing_command_bar.status.text()
    for value in ("I", "0"):
        submit(editor, value)
    assert "大于零" in editor.drawing_command_bar.status.text()
    assert not editor.canvas.entities


def test_polygon_canvas_keyboard_defaults(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    submit(editor, "POLYGON")
    QTest.keyClick(editor.canvas, Qt.Key.Key_Return)
    QTest.keyClick(editor.canvas, Qt.Key.Key_0)
    QTest.keyClicks(editor.drawing_command_bar.input, ",0")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    QTest.keyClick(editor.canvas, Qt.Key.Key_Return)
    QTest.keyClick(editor.canvas, Qt.Key.Key_1)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_0)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    polygon = editor.canvas.entities[0]
    assert isinstance(polygon, PolylineEntity)
    assert len(polygon.points_mm) == 6


def test_polygon_edge_option_uses_the_specified_edge(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    for value in ("POLYGON", "4", "E", "0,0", "10,0"):
        submit(editor, value)
    polygon = editor.canvas.entities[0]
    assert isinstance(polygon, PolylineEntity)
    assert polygon.points_mm[0] == pytest.approx((0, 0))
    assert polygon.points_mm[1] == pytest.approx((10, 0))


def test_polygon_edge_mouse_and_relative_second_point(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    for value in ("POLYGON", "4", "E"):
        submit(editor, value)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    submit(editor, "@0,0")
    assert "必须不同" in editor.drawing_command_bar.status.text()
    submit(editor, "@10,0")
    polygon = editor.canvas.entities[0]
    assert isinstance(polygon, PolylineEntity)
    assert polygon.points_mm[1] == pytest.approx((10, 0))
    assert editor.canvas.undo_last_operation()
