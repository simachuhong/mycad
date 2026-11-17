# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Drawing settings controls occupy distinct layout cells."""

from typing import cast

from PySide6.QtWidgets import QGridLayout, QGroupBox
from pytestqt.qtbot import QtBot

from mycad.ui.sketch_editor import SketchEditorDialog


def test_drawing_options_do_not_overlap(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    group = next(group for group in editor.findChildren(QGroupBox) if group.title() == "绘图设置")
    layout = group.layout()
    assert isinstance(layout, QGridLayout)
    occupied: set[tuple[int, int]] = set()
    for index in range(layout.count()):
        row, column, row_span, column_span = cast(
            "tuple[int, int, int, int]", layout.getItemPosition(index)
        )
        cells = {
            (r, c) for r in range(row, row + row_span) for c in range(column, column + column_span)
        }
        assert occupied.isdisjoint(cells)
        occupied.update(cells)
