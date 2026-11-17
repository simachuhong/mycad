# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Command discovery in the drawing console."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.ui.sketch_editor import SketchEditorDialog


def test_help_and_tab_completion(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    bar.input.setText("HELP")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "LINE" in bar.input.toPlainText()
    assert "SPLIT" in bar.input.toPlainText()
    bar.input.setText("DIMAL")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "DIMALIGNED"
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.dimensions.mode == "aligned"


def test_tab_cycles_candidates_and_does_not_complete_during_drawing(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    bar.input.setText("DIM")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    first = bar.input.text()
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    second = bar.input.text()
    assert first.startswith("DIM") and second.startswith("DIM") and first != second
    bar.input.setText("LINE")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("0,0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.has_pending_geometry
    bar.input.setText("D")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "D"


def test_tab_completes_linear_dimension_option(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    bar.input.setText("DIMLINEAR")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("ROT")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "ROTATED"
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "角度" in bar.status.text()


def test_tab_completes_polygon_options_without_touching_coordinates(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for value in ("POLYGON", "4"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("ED")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "EDGE"
    bar.input.setText("0,0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("CIR")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "CIRCUMSCRIBED"
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("10")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "10"


def test_tab_completes_measurement_and_zoom_options(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    bar.input.setText("MEASUREGEOM")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("AR")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "AREA"
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("OB")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "OBJECT"
    bar.input.setText("0,0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("UN")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "UNDO"
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    bar.input.setText("ZOOM")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("EX")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "EXTENTS"
    bar.input.setText("2X")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "2X"


def test_tab_completes_fillet_and_chamfer_options(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for value in ("FILLET", "TRIM"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("NOT")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "NOTRIM"
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("RAD")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "RADIUS"
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("2")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "2"
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    bar.input.setText("CHAMFER")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("METH")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "METHOD"
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("AN")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "ANGLE"


def test_tab_uses_circle_and_arc_options_not_global_commands(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    bar.input.setText("CIRCLE")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("T")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "TTR"
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.circle_ttr_active
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    bar.input.setText("ARC")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("CE")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "CENTER"


def test_tab_uses_trim_mode_and_projection_options(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for value in ("TRIM", "MODE"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("Q")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "QUICK"
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("PROJECT")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("U")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "UCS"


def test_tab_uses_line_tangent_option(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    bar.input.setText("LINE")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("TAN")
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "TANGENT"
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.line_tangent_awaiting_pick


def test_tab_completes_array_options_at_each_stage(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (5, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input

    def submit(value: str) -> None:
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)

    def complete(prefix: str, expected: str) -> None:
        bar.setText(prefix)
        QTest.keyClick(bar, Qt.Key.Key_Tab)
        assert bar.text() == expected

    submit("ARRAY")
    complete("PO", "POLAR")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    submit("0,0")
    complete("4", "4")
    submit("4")
    submit("360")
    complete("IT", "ITEMS")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    submit("6")
    complete("EX", "EXIT")
    QTest.keyClick(bar, Qt.Key.Key_Escape)

    canvas.selected_entity_ids = {line.entity_id}
    for value in ("ARRAYRECT", "", "2", "2", "4", "5"):
        submit(value)
    complete("AS", "ASSOCIATIVE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    complete("Y", "YES")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    complete("BA", "BASE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    complete("DE", "DEFAULT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    complete("SP", "SPACING")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    complete("UN", "UNIT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    complete("0,0", "0,0")


def test_tab_during_ime_composition_preserves_command_input(qtbot: QtBot) -> None:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QSignalSpy

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    bar.input.setText("DIMAL")
    completions = QSignalSpy(bar.input.completion_requested)
    QCoreApplication.sendEvent(bar.input, QInputMethodEvent("中", []))
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert completions.count() == 0
    assert bar.input.text() == "DIMAL"
    QCoreApplication.sendEvent(bar.input, QInputMethodEvent("", []))
    QTest.keyClick(bar.input, Qt.Key.Key_Tab)
    assert bar.input.text() == "DIMALIGNED"
