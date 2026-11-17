# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Command entry for splitting at an existing intersection."""

from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import LineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


@pytest.mark.parametrize("pick", ("mouse", "coordinate"))
def test_split_command_splits_at_intersection_and_undoes(qtbot: QtBot, pick: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    lines = (
        LineEntity(uuid4().hex, (0, 0), (20, 0)),
        LineEntity(uuid4().hex, (15, -5), (15, 5)),
    )
    assert canvas.replace_draft_entities(lines)
    bar = editor.drawing_command_bar.input
    bar.setText("SPLIT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.tool == "分割"
    if pick == "mouse":
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((13, 0)))
    else:
        bar.setText("13,0")
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(canvas.entities) == 3
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((15, 0))
    assert canvas.undo_last_operation()
    assert tuple(canvas.entities) == lines
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.tool == "分割"
