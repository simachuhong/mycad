# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Common aliases use the corresponding existing interactive operation."""

from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import LineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def test_cp_alias_copies_preselected_geometry(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("CP", "0,0", "0,5"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 2, bar.status.text()
    copy = editor.canvas.entities[1]
    assert isinstance(copy, LineEntity) and copy.start_mm == (0, 5)
    bar.input.setText("")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [line]
