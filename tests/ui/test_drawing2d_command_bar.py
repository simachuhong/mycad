# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent 2D command input uses explicit, replayable coordinates."""

import pytest
from pytestqt.qtbot import QtBot

from mycad.ui.drawing2d_command_bar import parse_coordinate


def test_coordinate_input_supports_absolute_relative_and_polar() -> None:
    assert parse_coordinate("10,20", None) == (10, 20)
    assert parse_coordinate("@3,-4", (10, 20)) == (13, 16)
    assert parse_coordinate("@10<90", (10, 20)) == pytest.approx((10, 30))
    assert parse_coordinate("10<90", None) == pytest.approx((0, 10), abs=1e-12)
    assert parse_coordinate("  -2.5 , 4e1 ", None) == (-2.5, 40)


@pytest.mark.parametrize("mode", ["preselected", "enter", "right_click"])
def test_erase_command_deletes_selected_draft_geometry(qtbot: QtBot, mode: str) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    canvas.replace_draft_entities((line,))
    if mode == "preselected":
        canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    bar.input.setText("E")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    if mode != "preselected":
        assert canvas.transform_selecting
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5.0, 0.0)))
        if mode == "right_click":
            QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
        else:
            QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert not canvas.entities
    assert canvas.active_transform is None
    canvas.undo_last_operation()
    assert canvas.entities == [line]


def test_erase_command_cancel_and_repeat(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    canvas.replace_draft_entities((line,))
    bar = editor.drawing_command_bar
    bar.input.setText("ERASE")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.entities == [line] and canvas.active_transform is None
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.transform_selecting
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5.0, 0.0)))
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert not canvas.entities


@pytest.mark.parametrize(
    "text,base",
    [
        ("@1,2", None),
        ("@10<0", None),
        ("nan,1", None),
        ("1", None),
        ("@-2<30", (0, 0)),
        ("1,2,3", None),
    ],
)
def test_coordinate_input_rejects_invalid_without_guessing(
    text: str, base: tuple[float, float] | None
) -> None:
    with pytest.raises(ValueError):
        parse_coordinate(text, base)


def test_command_line_drives_canvas_with_absolute_and_relative_points(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar
    assert command.isVisible()
    for text in ("L", "10,20", "@3,4"):
        command.input.setText(text)
        QTest.keyClick(command.input, Qt.Key.Key_Return)
    assert editor.canvas.tool == "直线"
    assert len(editor.canvas.entities) == 1
    line = editor.canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == (10, 20) and line.end_mm == (13, 24)
    QTest.keyClick(command.input, Qt.Key.Key_Return)
    assert not editor.canvas.has_pending_geometry


def test_reference_exercise_builds_profile_and_two_circles(qtbot: QtBot) -> None:
    """Reproduce the dimensioned profile in the supplied exercise 09 recording."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import CircleEntity, LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for text in (
        "L",
        "0,0",
        "@60,0",
        "@0,22",
        "@-22,16",
        "@-22,0",
        "@-16,-16",
        "CLOSE",
        "C",
        "18,18",
        "D",
        "18",
        "C",
        "42,10",
        "D",
        "10",
    ):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    lines = [entity for entity in editor.canvas.entities if isinstance(entity, LineEntity)]
    circles = [entity for entity in editor.canvas.entities if isinstance(entity, CircleEntity)]
    assert [(line.start_mm, line.end_mm) for line in lines] == [
        ((0, 0), (60, 0)),
        ((60, 0), (60, 22)),
        ((60, 22), (38, 38)),
        ((38, 38), (16, 38)),
        ((16, 38), (0, 22)),
        ((0, 22), (0, 0)),
    ]
    assert [(circle.center_mm, circle.radius_mm) for circle in circles] == [
        ((18, 18), 9),
        ((42, 10), 5),
    ]


@pytest.mark.parametrize(("option", "value", "radius"), [("D", "24", 12.0), ("", "7", 7.0)])
def test_circle_command_accepts_diameter_or_radius(
    qtbot: QtBot, option: str, value: str, radius: float
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import CircleEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar
    for text in ("C", "10,20", option, value):
        if text:
            command.input.setText(text)
            QTest.keyClick(command.input, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1
    circle = editor.canvas.entities[0]
    assert isinstance(circle, CircleEntity)
    assert circle.center_mm == (10, 20) and circle.radius_mm == pytest.approx(radius)


@pytest.mark.parametrize("invalid", ["0", "-1", "nan", "1e309"])
def test_circle_numeric_input_rejects_invalid_and_preserves_center(
    qtbot: QtBot, invalid: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import CircleEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar
    for text in ("C", "1,2", "D", invalid):
        command.input.setText(text)
        QTest.keyClick(command.input, Qt.Key.Key_Return)
    assert not editor.canvas.entities and editor.canvas.has_pending_geometry
    assert "大于零" in command.status.text()
    command.input.setText("20")
    QTest.keyClick(command.input, Qt.Key.Key_Return)
    circle = editor.canvas.entities[0]
    assert isinstance(circle, CircleEntity)
    assert circle.center_mm == (1, 2) and circle.radius_mm == pytest.approx(10)


def test_circle_diameter_option_resets_after_cancel(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import CircleEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar
    for text in ("C", "0,0", "D"):
        command.input.setText(text)
        QTest.keyClick(command.input, Qt.Key.Key_Return)
    QTest.keyClick(command.input, Qt.Key.Key_Escape)
    for text in ("C", "3,4", "10"):
        command.input.setText(text)
        QTest.keyClick(command.input, Qt.Key.Key_Return)
    circle = editor.canvas.entities[0]
    assert isinstance(circle, CircleEntity)
    assert circle.center_mm == (3, 4) and circle.radius_mm == pytest.approx(10)


def test_circle_mouse_center_then_numeric_diameter_uses_actual_center(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import CircleEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.tool_combo.setCurrentText("圆")
    accepted: list[tuple[float, float]] = []
    editor.canvas.point_accepted.connect(accepted.append)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((3, 4))
    )
    center = accepted[-1]
    command = editor.drawing_command_bar
    for text in ("D", "24"):
        command.input.setText(text)
        QTest.keyClick(command.input, Qt.Key.Key_Return)
    circle = editor.canvas.entities[0]
    assert isinstance(circle, CircleEntity)
    assert circle.center_mm == center and circle.radius_mm == pytest.approx(12)


def test_circle_diameter_then_move_and_undo(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import CircleEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar
    for text in ("C", "10,20", "D", "24"):
        command.input.setText(text)
        QTest.keyClick(command.input, Qt.Key.Key_Return)
    original = editor.canvas.entities[0]
    editor.canvas.selected_entity_ids = {original.entity_id}
    for text in ("M", "10,20", "@5,-2"):
        command.input.setText(text)
        QTest.keyClick(command.input, Qt.Key.Key_Return)
    moved = editor.canvas.entities[0]
    assert isinstance(moved, CircleEntity)
    assert moved.center_mm == (15, 18) and moved.radius_mm == pytest.approx(12)
    editor.canvas.undo_last_operation()
    assert editor.canvas.entities[0] == original


def test_command_line_preserves_draft_on_invalid_input_and_escape(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar
    command.input.setText("L")
    QTest.keyClick(command.input, Qt.Key.Key_Return)
    command.input.setText("@1,2")
    QTest.keyClick(command.input, Qt.Key.Key_Return)
    assert not editor.canvas.entities and not editor.canvas.has_pending_geometry
    assert "基点" in command.status.text()
    command.input.setText("1,2")
    QTest.keyClick(command.input, Qt.Key.Key_Return)
    assert editor.canvas.has_pending_geometry
    QTest.keyClick(command.input, Qt.Key.Key_Escape)
    assert not editor.canvas.has_pending_geometry and not editor.canvas.entities


def test_canvas_mouse_then_relative_command_uses_actual_accepted_point(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.tool_combo.setCurrentText("直线")
    accepted_points: list[tuple[float, float]] = []
    editor.canvas.point_accepted.connect(accepted_points.append)
    point = editor.canvas.local_to_screen((3, 4))
    QTest.mouseClick(editor.canvas, Qt.MouseButton.LeftButton, pos=point)
    accepted = accepted_points[-1]
    command = editor.drawing_command_bar
    command.input.setText("@10,0")
    QTest.keyClick(command.input, Qt.Key.Key_Return)
    line = editor.canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == accepted
    assert line.end_mm == pytest.approx((accepted[0] + 10, accepted[1]))


def test_command_line_uses_canvas_tool_selected_by_toolbar(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import RectangleEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.tool_combo.setCurrentText("矩形")
    command = editor.drawing_command_bar
    for text in ("2,3", "@8,5"):
        command.input.setText(text)
        QTest.keyClick(command.input, Qt.Key.Key_Return)
    rectangle = editor.canvas.entities[0]
    assert isinstance(rectangle, RectangleEntity)
    assert rectangle.first_corner_mm == (2, 3)
    assert rectangle.opposite_corner_mm == (10, 8)


def test_command_line_space_repeats_last_command(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar
    command.input.setText("REC")
    QTest.keyClick(command.input, Qt.Key.Key_Space)
    assert editor.canvas.tool == "矩形"
    command.input.clear()
    QTest.keyClick(command.input, Qt.Key.Key_Space)
    assert editor.canvas.tool == "矩形"


def test_invalid_geometry_does_not_replace_relative_base(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar
    for text in ("L", "2,3", "2,3"):
        command.input.setText(text)
        QTest.keyClick(command.input, Qt.Key.Key_Return)
    assert not editor.canvas.entities
    command.input.setText("@4,0")
    QTest.keyClick(command.input, Qt.Key.Key_Return)
    line = editor.canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == (2, 3) and line.end_mm == (6, 3)


def test_command_state_stays_with_its_document_when_switching(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad import app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    first = window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    bar = editor.drawing_command_bar
    for text in ("L", "2,3", "@4,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    second = window.new_session_document("sketch")
    second_editor = window.active_sketch_dialog()
    assert second_editor is not None and second_editor is not editor
    second_bar = second_editor.drawing_command_bar
    second_bar.input.setText("L")
    QTest.keyClick(second_bar.input, Qt.Key.Key_Return)
    second_bar.input.setText("@1,0")
    QTest.keyClick(second_bar.input, Qt.Key.Key_Return)
    assert "基点" in second_bar.status.text()
    window.activate_session_document(first.loaded.document.document_id)
    assert window.active_sketch_dialog() is editor
    accepted_points: list[tuple[float, float]] = []
    editor.canvas.point_accepted.connect(accepted_points.append)
    bar.input.setText("@1,0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert accepted_points == [(7, 3)]
    assert second.loaded.document.document_id != first.loaded.document.document_id


def test_space_during_input_method_composition_does_not_run_command(qtbot: QtBot) -> None:
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    previous = editor.canvas.tool
    bar.input.setText("REC")
    QCoreApplication.sendEvent(bar.input, QInputMethodEvent("中", []))
    QTest.keyClick(bar.input, Qt.Key.Key_Space)
    assert editor.canvas.tool == previous


def test_escape_during_input_method_composition_preserves_pending_line(qtbot: QtBot) -> None:
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.activateWindow()
    bar = editor.drawing_command_bar
    bar.input.setFocus()
    qtbot.waitUntil(bar.input.hasFocus)
    editor.canvas.set_tool("直线")
    editor.canvas.add_coordinate_point((0, 0))
    assert editor.canvas.has_pending_geometry
    QCoreApplication.sendEvent(bar.input, QInputMethodEvent("中", []))
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert editor.canvas.has_pending_geometry
    assert editor.canvas.tool == "直线"
    QCoreApplication.sendEvent(bar.input, QInputMethodEvent("", []))
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert not editor.canvas.has_pending_geometry
    assert editor.canvas.tool == "选择元素"


def test_escape_during_composition_keeps_copymode_prompt(qtbot: QtBot) -> None:
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.activateWindow()
    bar = editor.drawing_command_bar
    bar.input.setFocus()
    qtbot.waitUntil(bar.input.hasFocus)
    bar.input.setText("COPYMODE")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QCoreApplication.sendEvent(bar.input, QInputMethodEvent("中", []))
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    QCoreApplication.sendEvent(bar.input, QInputMethodEvent("", []))
    bar.input.setText("1")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.copy_mode == 1


def test_return_during_input_method_composition_does_not_run_command(qtbot: QtBot) -> None:
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.activateWindow()
    bar = editor.drawing_command_bar
    bar.input.setFocus()
    qtbot.waitUntil(bar.input.hasFocus)
    editor.canvas.set_tool("直线")
    editor.canvas.add_coordinate_point((0, 0))
    bar.input.setText("REC")
    QCoreApplication.sendEvent(bar.input, QInputMethodEvent("中", []))
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.has_pending_geometry
    assert editor.canvas.tool == "直线"
    assert bar.input.text() == "REC"


def test_move_command_uses_preselection_and_relative_coordinates(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for text in ("L", "0,0", "10,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    line = editor.canvas.entities[0]
    editor.canvas.selected_entity_ids = {line.entity_id}
    for text in ("M", "0,0", "@5,2"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    moved = editor.canvas.entities[0]
    assert isinstance(moved, LineEntity)
    assert moved.start_mm == (5, 2) and moved.end_mm == (15, 2)
    editor.canvas.undo_last_operation()
    assert editor.canvas.entities[0] == line


def test_move_command_can_select_after_command_without_changing_last_point(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for text in ("L", "0,0", "10,0", "M", "5,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert bar.input.text() == ""
    for text in ("", "@0,1", "@2,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    moved = editor.canvas.entities[0]
    assert isinstance(moved, LineEntity)
    assert moved.start_mm == (2, 0) and moved.end_mm == (12, 0)


def test_drawing_status_controls_are_real_and_document_local(qtbot: QtBot) -> None:
    from mycad.ui.sketch_editor import SketchEditorDialog

    first = SketchEditorDialog(select_committed_entities=True)
    second = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    first.show()
    second.show()
    assert first.drawing_status_bar.isAncestorOf(first.grid_visible_check)
    assert first.drawing_status_bar.isAncestorOf(first.grid_snap_check)
    assert first.drawing_status_bar.isAncestorOf(first.orthogonal_check)
    assert first.drawing_status_bar.isAncestorOf(first.snap_check)
    first.grid_visible_check.setChecked(False)
    first.grid_snap_check.setChecked(True)
    first.orthogonal_check.setChecked(True)
    first.snap_check.setChecked(False)
    assert not first.canvas.grid_visible
    assert second.grid_visible_check.isChecked()
    assert not second.grid_snap_check.isChecked()
    assert not second.orthogonal_check.isChecked()
    assert second.snap_check.isChecked()


def test_status_shortcuts_work_while_command_input_has_focus(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    qtbot.waitExposed(editor)
    editor.activateWindow()
    editor.drawing_command_bar.input.setFocus()
    qtbot.waitUntil(editor.drawing_command_bar.input.hasFocus)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_F8)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_F9)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_F3)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_F12)
    assert editor.orthogonal_check.isChecked()
    assert editor.grid_snap_check.isChecked()
    assert not editor.snap_check.isChecked()
    assert editor.dynamic_input_check.isChecked()


def test_continued_editor_retains_document_command_history(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    previous = SketchEditorDialog(select_committed_entities=True)
    continued = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(previous)
    qtbot.addWidget(continued)
    previous.show()
    continued.show()
    for text in ("L", "2,3", "6,3"):
        previous.drawing_command_bar.input.setText(text)
        QTest.keyClick(previous.drawing_command_bar.input, Qt.Key.Key_Return)
    continued.continue_workspace_from(previous)
    bar = continued.drawing_command_bar
    for text in ("", "@1,0", "@2,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    line = continued.canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == (7, 3) and line.end_mm == (9, 3)


def test_committed_drawing_retains_command_history_in_new_editor(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    previous = window.active_sketch_dialog()
    unit = window.execution_unit
    assert previous is not None and unit is not None
    previous.dynamic_input_check.setChecked(True)
    for text in ("L", "2,3", "6,3", ""):
        previous.drawing_command_bar.input.setText(text)
        QTest.keyClick(previous.drawing_command_bar.input, Qt.Key.Key_Return)
    previous.finish_button.click()
    qtbot.waitUntil(
        lambda: (
            window.active_sketch_dialog() is not None
            and window.active_sketch_dialog() is not previous
            and not unit.is_busy
        ),
        timeout=10000,
    )
    continued = window.active_sketch_dialog()
    assert continued is not None and continued.dynamic_input_check.isChecked()
    for text in ("", "@1,0", "@2,0"):
        continued.drawing_command_bar.input.setText(text)
        QTest.keyClick(continued.drawing_command_bar.input, Qt.Key.Key_Return)
    line = continued.canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == (7, 3) and line.end_mm == (9, 3)


def test_polygon_command_uses_current_polygon_options(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import PolylineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.polygon_sides_field.setValue(5)
    for text in ("POL", "0,0", "10,0"):
        editor.drawing_command_bar.input.setText(text)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    polygon = editor.canvas.entities[0]
    assert isinstance(polygon, PolylineEntity)
    assert polygon.closed and len(polygon.points_mm) == 5


def test_command_options_close_polyline_and_undo_last_line_segment(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for text in ("L", "0,0", "10,0", "10,10", "U"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1
    bar.input.setText("@0,5")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    last_line = editor.canvas.entities[-1]
    assert isinstance(last_line, LineEntity)
    assert last_line.end_mm == (10, 5)
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    for text in ("PL", "0,0", "10,0", "10,10", "CLOSE"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    polygon = editor.canvas.entities[-1]
    assert isinstance(polygon, PolylineEntity) and polygon.closed


@pytest.mark.parametrize(
    "command,points,expected,count",
    [
        ("CO", ("0,0", "@0,3"), ((0, 3), (10, 3)), 2),
        ("RO", ("0,0", "90"), ((0, 0), (0, 10)), 1),
        ("MI", ("0,0", "0,1"), ((0, 0), (-10, 0)), 2),
    ],
)
def test_transform_commands_use_existing_canvas_operations(
    qtbot: QtBot,
    command: str,
    points: tuple[str, str],
    expected: tuple[tuple[int, int], tuple[int, int]],
    count: int,
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for text in ("L", "0,0", "10,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    original = editor.canvas.entities[0]
    editor.canvas.selected_entity_ids = {original.entity_id}
    for text in (command, *points):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == count
    result = editor.canvas.entities[-1]
    assert isinstance(result, LineEntity)
    assert result.start_mm == pytest.approx(expected[0])
    assert result.end_mm == pytest.approx(expected[1])
    if command == "CO":
        assert editor.canvas.active_transform == "copy"
        bar.input.clear()
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [original]
