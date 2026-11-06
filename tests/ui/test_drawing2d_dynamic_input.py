# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Dynamic dimensions operate on the same independent drawing canvas."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import CircleEntity, LineEntity, RectangleEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def test_cursor_dimension_entry_locks_length_and_angle_for_mouse_commit(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QLineEdit

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.snap_check.setChecked(False)
    editor.auto_relation_check.setChecked(False)
    editor.dynamic_input_check.setChecked(True)
    canvas = editor.canvas
    canvas.add_coordinate_point((0, 0), exact_point=True)
    point = canvas.local_to_screen((5, 4))
    QTest.mouseMove(canvas, point)
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_1)
    entry = canvas.findChild(QLineEdit, "drawingCursorEntry")
    assert entry is not None and entry.isVisible()
    QTest.keyClicks(entry, "0")
    QTest.keyClick(entry, Qt.Key.Key_Tab)
    QTest.keyClicks(entry, "90")
    QTest.keyClick(entry, Qt.Key.Key_Return)
    assert not entry.isVisible()
    assert editor.dynamic_input.first_lock.isChecked()
    assert editor.dynamic_input.second_lock.isChecked()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    line = canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert (line.end_mm[0] - line.start_mm[0], line.end_mm[1] - line.start_mm[1]) == pytest.approx(
        (0, 10), abs=1e-9
    )


def test_invalid_cursor_dimension_cannot_commit_geometry(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QLineEdit

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.dynamic_input_check.setChecked(True)
    editor.tool_combo.setCurrentText("圆")
    canvas = editor.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    point = canvas.local_to_screen((5, 0))
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_0)
    entry = canvas.findChild(QLineEdit, "drawingCursorEntry")
    assert entry is not None and entry.isVisible()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    assert not canvas.entities and canvas.has_pending_geometry and entry.isVisible()
    canvas.add_coordinate_point((5, 0), exact_point=True)
    assert not canvas.entities and canvas.has_pending_geometry and entry.isVisible()
    QTest.keyClick(entry, Qt.Key.Key_Escape)
    assert not canvas.has_pending_geometry and not canvas.entities


def test_circle_cursor_radius_accepts_mouse_point_and_disabled_mode_does_not_capture_keys(
    qtbot: QtBot,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.dynamic_input_check.setChecked(True)
    editor.tool_combo.setCurrentText("圆")
    canvas = editor.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    point = canvas.local_to_screen((5, 0))
    QTest.mouseMove(canvas, point)
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_8)
    entry = canvas.findChild(QLineEdit, "drawingCursorEntry")
    assert entry is not None and entry.isVisible()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    circle = canvas.entities[0]
    assert isinstance(circle, CircleEntity) and circle.radius_mm == pytest.approx(8)
    canvas.add_coordinate_point((20, 0), exact_point=True)
    editor.dynamic_input_check.setChecked(False)
    QTest.mouseMove(canvas, point)
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_4)
    assert not entry.isVisible() and canvas.has_pending_geometry


def test_cursor_input_does_not_keep_lock_after_continuous_line_ends(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QLineEdit

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.dynamic_input_check.setChecked(True)
    canvas = editor.canvas
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    QTest.mouseMove(canvas, canvas.local_to_screen((10, 5)))
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_8)
    entry = canvas.findChild(QLineEdit, "drawingCursorEntry")
    assert entry is not None and entry.isVisible()
    QTest.keyClick(entry, Qt.Key.Key_Return)
    assert editor.dynamic_input.first_lock.isChecked()
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not editor.dynamic_input.first_lock.isChecked()
    assert len(canvas.entities) == 1


def test_cursor_entry_near_canvas_edge_does_not_cover_pointer(qtbot: QtBot) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QLineEdit

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(800, 600)
    editor.show()
    editor.dynamic_input_check.setChecked(True)
    canvas = editor.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    pointer = QPoint(canvas.width() - 2, canvas.height() - 2)
    QTest.mouseMove(canvas, pointer)
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_8)
    entry = canvas.findChild(QLineEdit, "drawingCursorEntry")
    assert entry is not None and entry.isVisible()
    assert canvas.rect().contains(entry.geometry())
    assert not entry.geometry().contains(pointer)


def test_cursor_entry_drives_rectangle_width_and_height(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QLineEdit

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.snap_check.setChecked(False)
    editor.dynamic_input_check.setChecked(True)
    editor.tool_combo.setCurrentText("矩形")
    canvas = editor.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    point = canvas.local_to_screen((5, 4))
    QTest.mouseMove(canvas, point)
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_2)
    entry = canvas.findChild(QLineEdit, "drawingCursorEntry")
    assert entry is not None and entry.isVisible()
    QTest.keyClick(entry, Qt.Key.Key_Tab)
    QTest.keyClick(entry, Qt.Key.Key_3)
    QTest.keyClick(entry, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    rectangle = canvas.entities[0]
    assert isinstance(rectangle, RectangleEntity)
    assert tuple(
        end - start
        for start, end in zip(rectangle.first_corner_mm, rectangle.opposite_corner_mm, strict=True)
    ) == pytest.approx((2, 3))


def test_cursor_entry_drives_circle_diameter(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QLineEdit

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.snap_check.setChecked(False)
    editor.dynamic_input_check.setChecked(True)
    editor.tool_combo.setCurrentText("圆")
    editor.dynamic_input.circle_mode.setCurrentText("直径")
    canvas = editor.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    point = canvas.local_to_screen((5, 0))
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_2)
    entry = canvas.findChild(QLineEdit, "drawingCursorEntry")
    assert entry is not None and entry.isVisible()
    QTest.keyClick(entry, Qt.Key.Key_0)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    circle = canvas.entities[0]
    assert isinstance(circle, CircleEntity)
    assert circle.radius_mm == pytest.approx(10)


def test_command_input_keeps_focus_and_accepts_coordinates_during_drawing(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QLineEdit

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    qtbot.waitExposed(editor)
    editor.activateWindow()
    editor.dynamic_input_check.setChecked(True)
    canvas = editor.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    command = editor.drawing_command_bar.input
    command.setFocus()
    qtbot.waitUntil(command.hasFocus)
    QTest.keyClicks(command, "10,20")
    entry = canvas.findChild(QLineEdit, "drawingCursorEntry")
    assert entry is not None and not entry.isVisible()
    QTest.keyClick(command, Qt.Key.Key_Return)
    line = canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.end_mm == pytest.approx((10, 20))


def test_disabling_dynamic_input_during_entry_preserves_draft(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QLineEdit

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    qtbot.waitExposed(editor)
    editor.activateWindow()
    editor.dynamic_input_check.setChecked(True)
    canvas = editor.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_8)
    entry = canvas.findChild(QLineEdit, "drawingCursorEntry")
    assert entry is not None and entry.isVisible()
    qtbot.waitUntil(entry.hasFocus)
    QTest.keyClick(entry, Qt.Key.Key_F12)
    assert not editor.dynamic_input_check.isChecked()
    assert not entry.isVisible() and canvas.has_pending_geometry and not canvas.entities
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert isinstance(canvas.entities[0], LineEntity)


def test_cursor_dimensions_follow_pointer_and_do_not_intercept_clicks(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QLabel

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    editor.snap_check.setChecked(False)
    editor.auto_relation_check.setChecked(False)
    editor.dynamic_input_check.setChecked(True)
    editor.tool_combo.setCurrentText("直线")
    canvas = editor.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    pointer = canvas.local_to_screen((5, 3))
    QTest.mouseMove(canvas, pointer)
    hint = canvas.findChild(QLabel, "drawingCursorDimensions")
    assert hint is not None
    qtbot.waitUntil(hint.isVisible)
    assert canvas.rect().contains(hint.geometry())
    assert hint.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    editor.dynamic_input.first_lock.setChecked(True)
    editor.dynamic_input.first_value.setValue(10)
    assert "10" in hint.text()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=pointer)
    assert not hint.isVisible()
    line = canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert (
        (line.end_mm[0] - line.start_mm[0]) ** 2 + (line.end_mm[1] - line.start_mm[1]) ** 2
    ) ** 0.5 == pytest.approx(10)


def test_cursor_dimensions_stay_inside_canvas_and_hide_on_disable_or_cancel(qtbot: QtBot) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent, QPoint
    from PySide6.QtWidgets import QLabel

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(800, 600)
    editor.show()
    editor.dynamic_input_check.setChecked(True)
    editor.tool_combo.setCurrentText("矩形")
    canvas = editor.canvas
    canvas.add_coordinate_point((0, 0), exact_point=True)
    QTest.mouseMove(canvas, QPoint(canvas.width() - 2, canvas.height() - 2))
    hint = canvas.findChild(QLabel, "drawingCursorDimensions")
    assert hint is not None
    qtbot.waitUntil(hint.isVisible)
    assert canvas.rect().contains(hint.geometry())
    QCoreApplication.sendEvent(canvas, QEvent(QEvent.Type.Leave))
    assert not hint.isVisible()
    QTest.mouseMove(canvas, QPoint(40, 40))
    qtbot.waitUntil(hint.isVisible)
    editor.dynamic_input_check.setChecked(False)
    assert not hint.isVisible()
    editor.dynamic_input_check.setChecked(True)
    QTest.mouseMove(canvas, QPoint(40, 40))
    qtbot.waitUntil(hint.isVisible)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not hint.isVisible()


def test_cursor_dimensions_remain_visible_for_next_continuous_line_segment(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QLabel

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.dynamic_input_check.setChecked(True)
    canvas = editor.canvas
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    QTest.mouseMove(canvas, canvas.local_to_screen((10, 5)))
    hint = canvas.findChild(QLabel, "drawingCursorDimensions")
    assert hint is not None
    qtbot.waitUntil(hint.isVisible)
    assert "长度" in hint.text()


def test_dynamic_line_dimensions_resolve_mouse_commit(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.snap_check.setChecked(False)
    editor.auto_relation_check.setChecked(False)
    editor.dynamic_input_check.setChecked(True)
    editor.tool_combo.setCurrentText("直线")
    canvas = editor.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    editor.dynamic_input.first_lock.setChecked(True)
    editor.dynamic_input.first_value.setValue(10)
    editor.dynamic_input.second_lock.setChecked(True)
    editor.dynamic_input.second_value.setValue(90)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    line = canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert (line.end_mm[0] - line.start_mm[0], line.end_mm[1] - line.start_mm[1]) == pytest.approx(
        (0, 10), abs=1e-9
    )


def test_dynamic_rectangle_invalid_dimension_preserves_draft(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.snap_check.setChecked(False)
    editor.dynamic_input_check.setChecked(True)
    editor.tool_combo.setCurrentText("矩形")
    canvas = editor.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    editor.dynamic_input.first_value.setValue(0)
    editor.dynamic_input.first_lock.setChecked(True)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    assert not canvas.entities and canvas.has_pending_geometry
    assert "大于零" in canvas.message
    editor.dynamic_input.first_value.setValue(8)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    assert isinstance(canvas.entities[0], RectangleEntity)


def test_dynamic_circle_diameter_and_explicit_coordinates(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.snap_check.setChecked(False)
    editor.dynamic_input_check.setChecked(True)
    editor.tool_combo.setCurrentText("圆")
    canvas = editor.canvas
    canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.dynamic_input.circle_mode.setCurrentText("直径")
    editor.dynamic_input.first_value.setValue(20)
    editor.dynamic_input.first_lock.setChecked(True)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    circle = canvas.entities[0]
    assert isinstance(circle, CircleEntity)
    assert circle.radius_mm == pytest.approx(10)
    canvas.add_coordinate_point((20, 0), exact_point=True)
    editor.dynamic_input.first_value.setValue(40)
    editor.dynamic_input.first_lock.setChecked(True)
    canvas.add_coordinate_point((23, 0), exact_point=True)
    second = canvas.entities[1]
    assert isinstance(second, CircleEntity)
    assert second.radius_mm == pytest.approx(3)


def test_editing_locked_dimensions_updates_the_current_preview(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.snap_check.setChecked(False)
    editor.auto_relation_check.setChecked(False)
    editor.dynamic_input_check.setChecked(True)
    canvas = editor.canvas
    canvas.add_coordinate_point((0, 0), exact_point=True)
    seen: list[tuple[float, float]] = []

    def record_cursor(x: float, y: float, _kind: str) -> None:
        seen.append((x, y))

    canvas.cursor_changed.connect(record_cursor)
    QTest.mouseMove(canvas, canvas.local_to_screen((4, 3)))
    qtbot.waitUntil(lambda: bool(seen))
    editor.dynamic_input.first_lock.setChecked(True)
    editor.dynamic_input.first_value.setValue(10)
    editor.dynamic_input.second_lock.setChecked(True)
    editor.dynamic_input.second_value.setValue(90)
    assert seen[-1] == pytest.approx((0, 10), abs=1e-9)


def test_escape_and_disabling_dynamic_input_clear_old_locks(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.dynamic_input_check.setChecked(True)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.dynamic_input.first_value.setValue(10)
    editor.dynamic_input.first_lock.setChecked(True)
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert not editor.dynamic_input.first_lock.isChecked()
    editor.dynamic_input.first_lock.setChecked(True)
    editor.dynamic_input_check.setChecked(False)
    assert not editor.dynamic_input.first_lock.isChecked()


def test_typing_a_dimension_locks_the_entered_value(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.dynamic_input_check.setChecked(True)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    QTest.mouseMove(editor.canvas, editor.canvas.local_to_screen((4, 3)))
    field = editor.dynamic_input.first_value
    field.lineEdit().selectAll()
    QTest.keyClicks(field.lineEdit(), "12")
    assert editor.dynamic_input.first_lock.isChecked()
    assert field.value() == pytest.approx(12)


def test_dynamic_input_state_is_isolated_between_editors(qtbot: QtBot) -> None:
    first = SketchEditorDialog(select_committed_entities=True)
    second = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(first)
    qtbot.addWidget(second)
    first.dynamic_input_check.setChecked(True)
    first.canvas.add_coordinate_point((0, 0), exact_point=True)
    first.dynamic_input.first_lock.setChecked(True)
    first.dynamic_input.first_value.setValue(15)
    assert not second.dynamic_input_check.isChecked()
    assert not second.dynamic_input.first_lock.isChecked()
    second.dynamic_input_check.setChecked(True)
    assert not second.dynamic_input.first_lock.isChecked()
    assert first.dynamic_input.first_value.value() == pytest.approx(15)


def test_continuing_editor_keeps_dynamic_preference_without_dimension_locks(qtbot: QtBot) -> None:
    previous = SketchEditorDialog(select_committed_entities=True)
    continued = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(previous)
    qtbot.addWidget(continued)
    previous.dynamic_input_check.setChecked(True)
    previous.dynamic_input.first_lock.setChecked(True)
    continued.continue_workspace_from(previous)
    assert continued.dynamic_input_check.isChecked()
    assert not continued.dynamic_input.first_lock.isChecked()
