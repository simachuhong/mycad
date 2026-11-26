# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Special dimension symbols retain the live measurement and editing context."""

from dataclasses import replace
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolButton
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.dimension_tolerance import DimensionTolerance
from mycad.core.sketch import LineEntity
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.dimension_text import dimension_text
from mycad.ui.dimension_tolerance_layout import layout_dimension_tolerance
from mycad.ui.sketch_editor import SketchEditorDialog


def _symbol_action(editor: SketchEditorDialog, symbol: str) -> QAction:
    button = editor.dimensions.command_bar.findChild(QToolButton, "dimensionTextSymbols")
    assert button is not None, "Dimension text needs an accessible symbol insertion menu"
    menu = button.menu()
    assert menu is not None
    return next(action for action in menu.actions() if action.data() == symbol)


@pytest.mark.parametrize("symbol", ["⌀", "±", "°", "□", "R", "SR", "S⌀", "⌒", "×"])
def test_symbol_prefix_creates_live_dimension(qtbot: QtBot, symbol: str) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
    )
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    editor.canvas.entities = [line]
    editor.canvas.changed.emit()
    editor.dimensions.driving_check.setChecked(False)
    bar = editor.drawing_command_bar
    for text in ("DIMLINEAR", "0,0", "25,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    _symbol_action(editor, symbol).trigger()
    assert editor.dimensions.text_override.text() == f"{symbol}<> mm"
    bar.input.setText("10,10")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    dimension = editor.canvas.constraints[0]
    assert dimension_text(dimension) == f"{symbol}25.00 mm"
    assert dimension_text(replace(dimension, value=30)) == f"{symbol}30.00 mm"
    assert dimension.value == 25 and editor.canvas.entities == [line]


def test_symbols_insert_at_caret_and_replace_selection(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    field = editor.dimensions.text_override
    field.setText("4×<> mm")
    field.setCursorPosition(2)
    _symbol_action(editor, "⌀").trigger()
    assert field.text() == "4×⌀<> mm"
    field.setSelection(2, 1)
    _symbol_action(editor, "±").trigger()
    assert field.text() == "4×±<> mm"
    field.undo()
    assert field.text() == "4×⌀<> mm"


def test_symbol_before_angle_picking_keeps_degree_unit(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.dimensions.start("angle")
    _symbol_action(editor, "±").trigger()
    assert editor.dimensions.text_override.text() == "±<>°"


def test_symbol_edit_preserves_tolerance_and_measurement(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    tolerance = DimensionTolerance("symmetric", 0.1, -0.1, precision=2)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        driving=False,
        tolerance=tolerance,
    )
    editor.canvas.entities = [line]
    editor.canvas.constraints = [dimension]
    editor.canvas.changed.emit()
    sketch = next(s for s in editor.dimension_sources() if s.constraints)
    editor.dimensions.edit(sketch, dimension)
    _symbol_action(editor, "⌀").trigger()
    assert editor.dimensions.apply_button.isEnabled()
    editor.dimensions.apply_edit()
    updated = editor.canvas.constraints[0]
    assert updated == replace(dimension, text_override="⌀<> mm")
    layout = layout_dimension_tolerance(updated, tolerance, QFont(), 1)
    assert layout.main == "(⌀25.00 mm)"
    assert layout.lines == ("±0.10",)
