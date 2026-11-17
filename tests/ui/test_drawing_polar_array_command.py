# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Interactive polar array command shares canvas selection and undo."""

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog


def submit(editor: SketchEditorDialog, text: str) -> None:
    editor.drawing_command_bar.input.setText(text)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)


def test_polar_array_preselection_preview_and_undo(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (5, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    for text in ("ARRAYPOLAR", "0,0", "4", "360"):
        submit(editor, text)
    assert editor.canvas.active_transform == "polar_array_preview", (
        editor.drawing_command_bar.status.text()
    )
    assert len(editor.canvas.transform_preview_entities) == 3
    assert editor.canvas.entities == [line]
    submit(editor, "")
    assert len(editor.canvas.entities) == 4
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [line]


def test_polar_array_command_first_mouse_selection_and_center(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    line = LineEntity(uuid4().hex, (5, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    submit(editor, "ARRAYPOLAR")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((7, 0))
    )
    assert editor.canvas.selected_entity_ids == {line.entity_id}
    QTest.keyClick(editor.canvas, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    submit(editor, "4")
    submit(editor, "180")
    assert len(editor.canvas.transform_preview_entities) == 3
    submit(editor, "")
    assert len(editor.canvas.entities) == 4


def test_polar_array_retries_invalid_values_and_rejects_changed_selection(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (5, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    for text in ("ARRAYPOLAR", "0,0", "1"):
        submit(editor, text)
    assert "2–1000" in editor.drawing_command_bar.status.text()
    submit(editor, "4")
    submit(editor, "nan")
    assert "有限角度" in editor.drawing_command_bar.status.text()
    submit(editor, "360")
    assert editor.canvas.active_transform == "polar_array_preview"
    editor.canvas.selected_entity_ids.clear()
    submit(editor, "")
    assert editor.canvas.entities == [line]
    assert editor.canvas.active_transform is None
    assert "已变化" in editor.drawing_command_bar.status.text()


def test_polar_array_of_saved_object_survives_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    line = LineEntity(uuid4().hex, (5, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: (
            window.active_sketch_dialog() is not None
            and window.active_sketch_dialog() is not editor
            and not unit.is_busy
        ),
        timeout=20000,
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.canvas.selected_entity_ids = {line.entity_id}
    for text in ("ARRAYPOLAR", "0,0", "4", "360", ""):
        submit(editor, text)
    assert len(editor.canvas.entities) == 3
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: len(entry.services.kernel.sketches) == 2 and not unit.is_busy, timeout=20000
    )
    path = tmp_path / "polar.my2d"
    save_document(entry.loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert sum(len(sketch.entities) for sketch in reopened.kernel.sketches) == 4


def test_switching_tool_cancels_polar_array_preview(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (5, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    for text in ("ARRAYPOLAR", "0,0", "4", "360"):
        submit(editor, text)
    assert editor.canvas.active_transform == "polar_array_preview"
    editor.tool_buttons["直线"].click()
    assert editor.canvas.active_transform is None
    for text in ("0,0", "10,0"):
        submit(editor, text)
    assert len(editor.canvas.entities) == 2


def test_polar_array_preview_edits_count_and_angle_then_cancels(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (5, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    for text in ("ARRAYPOLAR", "0,0", "4", "360", "I", "6"):
        submit(editor, text)
    assert len(editor.canvas.transform_preview_entities) == 5
    for text in ("A", "-180"):
        submit(editor, text)
    assert len(editor.canvas.transform_preview_entities) == 5
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Escape)
    assert editor.canvas.active_transform is None
    assert editor.canvas.entities == [line]


def test_array_command_selects_polar_type(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (5, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    for text in ("ARRAY", "PO", "0,0", "4", "360", ""):
        submit(editor, text)
    assert len(editor.canvas.entities) == 4, editor.drawing_command_bar.status.text()


def test_array_command_selects_rectangular_after_mouse_selection(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    submit(editor, "AR")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    QTest.keyClick(editor.canvas, Qt.Key.Key_Return)
    for text in ("R", "2", "2", "4", "5", ""):
        submit(editor, text)
    assert len(editor.canvas.entities) == 4, editor.drawing_command_bar.status.text()


def test_array_path_reports_deferred_without_mutation(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    submit(editor, "ARRAY")
    submit(editor, "PA")
    assert "路径阵列尚未实现" in editor.drawing_command_bar.status.text()
    assert editor.canvas.entities == [line]


def test_polar_count_limits_total_copies(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    lines = tuple(LineEntity(uuid4().hex, (i, 0), (i, 1)) for i in range(11))
    assert editor.canvas.replace_draft_entities(lines)
    editor.canvas.selected_entity_ids = {line.entity_id for line in lines}
    for value in ("ARRAYPOLAR", "0,0", "1000"):
        submit(editor, value)
    assert "10000" in editor.drawing_command_bar.status.text()
    for value in ("4", "360"):
        submit(editor, value)
    assert len(editor.canvas.transform_preview_entities) == 33


def test_polar_center_accepts_typing_from_canvas(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (5, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    submit(editor, "ARRAYPOLAR")
    editor.canvas.setFocus()
    QTest.keyClick(editor.canvas, Qt.Key.Key_0)
    QTest.keyClicks(editor.drawing_command_bar.input, ",0")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    for value in ("4", "360"):
        submit(editor, value)
    assert len(editor.canvas.transform_preview_entities) == 3


def test_array_escape_from_canvas_cancels_type_prompt(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (5, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    submit(editor, "ARRAY")
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    submit(editor, "POINT")
    assert editor.canvas.tool == "点"
