# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Interactive object snap tracking for independent drawings."""

from uuid import uuid4

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.core.sketch import LineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def move(editor: SketchEditorDialog, point: tuple[float, float]) -> None:
    canvas = editor.canvas
    pixel = canvas.local_to_screen(point)
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(pixel),
            QPointF(canvas.mapToGlobal(pixel)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def test_f11_tracks_two_acquired_object_points_and_commits(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    sources = (
        LineEntity(uuid4().hex, (0, 0), (0, 10)),
        LineEntity(uuid4().hex, (20, 20), (30, 20)),
    )
    assert canvas.replace_draft_entities(sources)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((-10, -10), exact_point=True)
    editor.activateWindow()
    editor.drawing_command_bar.input.setFocus()
    qtbot.waitUntil(editor.drawing_command_bar.input.hasFocus)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_F11)
    assert editor.object_tracking_check.isChecked()
    move(editor, (0, 0))
    move(editor, (20, 20))
    assert canvas.acquired_tracking_points == ((0, 0), (20, 20))
    move(editor, (20.2, 0.2))
    assert canvas.current_snap_kind == "对象追踪交点"
    assert canvas.object_tracking_paths == (((0, 0), (20, 0)), ((20, 20), (20, 0)))
    image = canvas.grab().toImage()
    marker = canvas.local_to_screen((20, 20))
    assert any(
        (color := image.pixelColor(marker.x() + dx, marker.y() + dy)).green() > 100
        and color.green() > color.red() * 1.5
        and color.green() > color.blue() * 1.1
        for dx in range(-5, 6)
        for dy in range(-5, 6)
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20.2, 0.2)))
    assert isinstance(canvas.entities[-1], LineEntity)
    assert canvas.entities[-1].end_mm == pytest.approx((20, 0))
    assert canvas.undo_last_operation()
    assert tuple(canvas.entities) == sources


def test_object_tracking_disabled_when_object_snap_is_off(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (0, 10)),))
    editor.object_tracking_check.setChecked(True)
    editor.snap_check.setChecked(False)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((-10, -10), exact_point=True)
    move(editor, (0, 0))
    assert canvas.acquired_tracking_points == ()


def test_object_tracking_single_axis_and_exact_coordinate(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    source = LineEntity(uuid4().hex, (0, 0), (0, 10))
    assert canvas.replace_draft_entities((source,))
    editor.object_tracking_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((-10, -10), exact_point=True)
    move(editor, (0, 0))
    move(editor, (20, 0.8))
    assert canvas.current_snap_kind == "对象追踪"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20, 0.8)))
    assert isinstance(canvas.entities[-1], LineEntity)
    expected_x = canvas.screen_to_local(QPointF(canvas.local_to_screen((20, 0.8))))[0]
    assert canvas.entities[-1].end_mm == pytest.approx((expected_x, 0))
    assert canvas.acquired_tracking_points == ()
    move(editor, (0, 0))
    canvas.add_coordinate_point((30, 0.8), exact_point=True)
    assert isinstance(canvas.entities[-1], LineEntity)
    assert canvas.entities[-1].end_mm == pytest.approx((30, 0.8))


def test_object_tracking_discards_removed_source_and_f11_disable(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (0, 10))
    assert canvas.replace_draft_entities((source,))
    editor.object_tracking_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((-10, -10), exact_point=True)
    move(editor, (0, 0))
    assert canvas.acquired_tracking_points == ((0, 0),)
    assert canvas.replace_draft_entities(())
    assert canvas.acquired_tracking_points == ()
    assert canvas.replace_draft_entities((source,))
    move(editor, (0, 0))
    assert canvas.acquired_tracking_points == ((0, 0),)
    editor.object_tracking_check.setChecked(False)
    assert canvas.acquired_tracking_points == ()


def test_object_tracking_preference_is_document_local(qtbot: QtBot) -> None:
    first = SketchEditorDialog(select_committed_entities=True)
    continued = SketchEditorDialog(select_committed_entities=True)
    other = SketchEditorDialog(select_committed_entities=True)
    for editor in (first, continued, other):
        qtbot.addWidget(editor)
    first.object_tracking_check.setChecked(True)
    continued.continue_workspace_from(first)
    assert continued.object_tracking_check.isChecked()
    assert not other.object_tracking_check.isChecked()
    assert continued.canvas.acquired_tracking_points == ()


@pytest.mark.parametrize("command_focus", [False, True])
def test_shift_temporarily_disables_object_tracking(qtbot: QtBot, command_focus: bool) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (0, 10)),))
    editor.object_tracking_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((-10, -10), exact_point=True)
    move(editor, (0, 0))
    move(editor, (20, 0.8))
    assert canvas.current_snap_kind == "对象追踪"
    target = editor.drawing_command_bar.input if command_focus else canvas
    QTest.keyPress(target, Qt.Key.Key_Shift)
    assert canvas.current_snap_kind == "临时关闭捕捉"
    assert canvas.object_tracking_paths == ()
    QTest.keyRelease(target, Qt.Key.Key_Shift)
    assert canvas.current_snap_kind == "对象追踪"
    assert canvas.object_tracking_paths


def test_object_tracking_moves_draft_and_undoes(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    reference = LineEntity(uuid4().hex, (20, 20), (30, 20))
    assert canvas.replace_draft_entities((source, reference))
    canvas.selected_entity_ids = {source.entity_id}
    editor.object_tracking_check.setChecked(True)
    command = editor.drawing_command_bar.input
    for value in ("MOVE", "0,0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    move(editor, (20, 20))
    move(editor, (40, 20.8))
    assert canvas.current_snap_kind == "对象追踪"
    pixel = canvas.local_to_screen((40, 20.8))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=pixel)
    expected_x = canvas.screen_to_local(QPointF(pixel))[0]
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].start_mm == pytest.approx((expected_x, 20))
    assert canvas.entities[1] == reference
    assert canvas.undo_last_operation()
    assert tuple(canvas.entities) == (source, reference)


def test_object_tracking_discards_points_after_source_revision_changes(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (0, 10)),))
    revision = [1]
    canvas.source_revision_provider = lambda: revision[0]
    canvas.set_source_context_revision(1)
    editor.object_tracking_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((-10, -10), exact_point=True)
    move(editor, (0, 0))
    assert canvas.acquired_tracking_points == ((0, 0),)
    revision[0] = 2
    assert canvas.acquired_tracking_points == ()


def test_tracking_status_fits_narrow_window_and_settings_are_accessible(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    qtbot.waitExposed(editor)
    assert editor.drawing_status_bar.minimumSizeHint().width() <= 700
    for control in (
        editor.grid_snap_check,
        editor.polar_check,
        editor.object_tracking_check,
        editor.snap_check,
        editor.dynamic_input_check,
    ):
        assert control.isVisible()
    menu = editor.tracking_settings_button.menu()
    assert menu is not None
    menu.popup(editor.mapToGlobal(QPoint(0, 0)))
    qtbot.waitUntil(menu.isVisible)
    assert editor.polar_angle_field.isVisible()
    assert editor.snap_type_combo.isVisible()
    assert editor.polar_additional_button.isVisible()
    assert editor.object_tracking_angle_combo.isVisible()
    assert editor.object_tracking_acquisition_combo.isVisible()
    editor.polar_angle_field.setValue(30)
    menu.close()
    menu.popup(editor.mapToGlobal(QPoint(0, 0)))
    qtbot.waitUntil(menu.isVisible)
    assert editor.polar_angle_field.value() == pytest.approx(30)
    menu.close()


def test_object_tracking_uses_polar_angles_and_distance_snap(qtbot: QtBot) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    source = LineEntity(uuid4().hex, (0, 0), (-10, 0))
    assert canvas.replace_draft_entities((source,))
    editor.object_tracking_check.setChecked(True)
    editor.object_tracking_angle_combo.setCurrentText("使用极轴角度")
    editor.polar_angle_field.setValue(30)
    editor.snap_type_combo.setCurrentText("极轴距离")
    editor.polar_spacing_field.setValue(4)
    editor.grid_snap_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((-20, -20), exact_point=True)
    move(editor, (0, 0))
    target = (10.5 * math.cos(math.radians(31)), 10.5 * math.sin(math.radians(31)))
    move(editor, target)
    assert canvas.current_snap_kind == "对象追踪"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(target))
    assert isinstance(canvas.entities[-1], LineEntity)
    assert canvas.entities[-1].end_mm == pytest.approx(
        (12 * math.cos(math.radians(30)), 6), abs=1e-8
    )


def test_object_tracking_intersects_two_polar_rays(qtbot: QtBot) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    sources = (
        LineEntity(uuid4().hex, (0, 0), (-10, 0)),
        LineEntity(uuid4().hex, (20, 0), (30, 0)),
    )
    assert canvas.replace_draft_entities(sources)
    editor.object_tracking_check.setChecked(True)
    editor.object_tracking_angle_combo.setCurrentText("使用极轴角度")
    editor.polar_angle_field.setValue(30)
    assert canvas.set_tool("圆")
    move(editor, (0, 0))
    move(editor, (20, 0))
    target = (10.0, 10 / math.sqrt(3))
    move(editor, target)
    assert canvas.current_snap_kind == "对象追踪交点"
    expected = (10.0, 10 / math.sqrt(3))
    assert canvas.object_tracking_paths[0][1] == pytest.approx(expected)
    assert canvas.object_tracking_paths[1][1] == pytest.approx(expected)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(target))
    canvas.add_coordinate_point((15, expected[1]), exact_point=True)
    from mycad.core.sketch import CircleEntity

    assert isinstance(canvas.entities[-1], CircleEntity)
    assert canvas.entities[-1].center_mm == pytest.approx(expected)


def test_object_tracking_angle_mode_follows_same_document(qtbot: QtBot) -> None:
    first = SketchEditorDialog(select_committed_entities=True)
    continued = SketchEditorDialog(select_committed_entities=True)
    other = SketchEditorDialog(select_committed_entities=True)
    for editor in (first, continued, other):
        qtbot.addWidget(editor)
    first.object_tracking_angle_combo.setCurrentText("使用极轴角度")
    continued.continue_workspace_from(first)
    assert continued.object_tracking_angle_combo.currentText() == "使用极轴角度"
    assert other.object_tracking_angle_combo.currentText() == "仅正交"


def test_object_tracking_orthogonal_respects_polar_snap_distance(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (-10, 0)),))
    editor.object_tracking_check.setChecked(True)
    editor.snap_type_combo.setCurrentText("极轴距离")
    editor.polar_spacing_field.setValue(4)
    editor.grid_snap_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((-20, -20), exact_point=True)
    move(editor, (0, 0))
    move(editor, (10.5, 0.6))
    assert canvas.current_snap_kind == "对象追踪"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10.5, 0.6)))
    assert isinstance(canvas.entities[-1], LineEntity)
    assert canvas.entities[-1].end_mm == pytest.approx((12, 0))


def test_object_tracking_uses_additional_absolute_angle(qtbot: QtBot) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (-10, 0)),))
    canvas.set_polar_additional_angles((37.0,))
    editor.object_tracking_check.setChecked(True)
    editor.object_tracking_angle_combo.setCurrentText("使用极轴角度")
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((-20, -20), exact_point=True)
    move(editor, (0, 0))
    target = (10 * math.cos(math.radians(38)), 10 * math.sin(math.radians(38)))
    move(editor, target)
    assert canvas.current_snap_kind == "对象追踪"
    start, end = canvas.object_tracking_paths[0]
    assert start == pytest.approx((0, 0))
    assert math.degrees(math.atan2(end[1], end[0])) == pytest.approx(37)


def test_object_tracking_uses_relative_polar_reference(qtbot: QtBot) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10 * math.cos(math.radians(30)), 5), exact_point=True)
    canvas.end_line_chain()
    reference = LineEntity(uuid4().hex, (20, 20), (30, 20))
    assert canvas.replace_draft_entities((*canvas.entities, reference))
    canvas.set_snapping_enabled(True)
    editor.polar_reference_combo.setCurrentText("相对上一段")
    editor.object_tracking_check.setChecked(True)
    editor.object_tracking_angle_combo.setCurrentText("使用极轴角度")
    assert canvas.set_tool("圆")
    move(editor, (20, 20))
    target = (20 + 10 * math.cos(math.radians(121)), 20 + 10 * math.sin(math.radians(121)))
    move(editor, target)
    assert canvas.current_snap_kind == "对象追踪"
    start, end = canvas.object_tracking_paths[0]
    assert start == pytest.approx((20, 20))
    assert math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])) == pytest.approx(120)


@pytest.mark.parametrize("tool", ["直线", "圆"])
def test_object_tracking_numeric_distance_uses_reference_direction(qtbot: QtBot, tool: str) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (-10, 0)),))
    editor.object_tracking_check.setChecked(True)
    editor.object_tracking_angle_combo.setCurrentText("使用极轴角度")
    editor.polar_angle_field.setValue(30)
    editor.snap_type_combo.setCurrentText("极轴距离")
    editor.polar_spacing_field.setValue(100)
    editor.grid_snap_check.setChecked(True)
    assert canvas.set_tool(tool)
    if tool == "直线":
        canvas.add_coordinate_point((-20, -20), exact_point=True)
    move(editor, (0, 0))
    move(editor, (10 * math.cos(math.radians(30)), 5))
    assert canvas.current_snap_kind == "对象追踪"
    command = editor.drawing_command_bar.input
    command.setText("20")
    QTest.keyClick(command, Qt.Key.Key_Return)
    expected = (20 * math.cos(math.radians(30)), 10)
    if tool == "直线":
        assert isinstance(canvas.entities[-1], LineEntity)
        assert canvas.entities[-1].end_mm == pytest.approx(expected)
    else:
        assert canvas.pending_last_point == pytest.approx(expected)


def test_object_tracking_numeric_distance_moves_from_base(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    reference = LineEntity(uuid4().hex, (20, 20), (30, 20))
    assert canvas.replace_draft_entities((source, reference))
    canvas.selected_entity_ids = {source.entity_id}
    editor.object_tracking_check.setChecked(True)
    command = editor.drawing_command_bar.input
    for value in ("MOVE", "0,0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    move(editor, (20, 20))
    move(editor, (40, 20.8))
    assert canvas.current_snap_kind == "对象追踪"
    command.setText("15")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].start_mm == pytest.approx((35, 20))
    assert canvas.undo_last_operation()
    assert tuple(canvas.entities) == (source, reference)


def test_object_tracking_numeric_distance_rejects_invalid_or_stale_input(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (-10, 0)),))
    revision = [1]
    canvas.source_revision_provider = lambda: revision[0]
    canvas.set_source_context_revision(1)
    editor.object_tracking_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((-20, -20), exact_point=True)
    move(editor, (0, 0))
    move(editor, (20, 0.8))
    command = editor.drawing_command_bar.input
    command.setText("-5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert "大于零" in editor.drawing_command_bar.status.text()
    assert len(canvas.entities) == 1
    revision[0] = 2
    assert not canvas.object_tracking_distance_available
    command.setText("15")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1


@pytest.mark.parametrize("command_focus", [False, True])
def test_shift_acquisition_mode_requires_shift(qtbot: QtBot, command_focus: bool) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (-10, 0)),))
    editor.object_tracking_check.setChecked(True)
    editor.object_tracking_acquisition_combo.setCurrentText("按 Shift 获取")
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((-20, -20), exact_point=True)
    move(editor, (0, 0))
    assert canvas.acquired_tracking_points == ()
    target = editor.drawing_command_bar.input if command_focus else canvas
    QTest.keyPress(target, Qt.Key.Key_Shift)
    assert canvas.acquired_tracking_points == ((0, 0),)
    QTest.keyRelease(target, Qt.Key.Key_Shift)
    move(editor, (20, 0.8))
    assert canvas.current_snap_kind == "对象追踪"


def test_shift_acquisition_setting_is_document_local(qtbot: QtBot) -> None:
    first = SketchEditorDialog(select_committed_entities=True)
    continued = SketchEditorDialog(select_committed_entities=True)
    other = SketchEditorDialog(select_committed_entities=True)
    for editor in (first, continued, other):
        qtbot.addWidget(editor)
    first.object_tracking_acquisition_combo.setCurrentText("按 Shift 获取")
    continued.continue_workspace_from(first)
    assert continued.object_tracking_acquisition_combo.currentText() == "按 Shift 获取"
    assert other.object_tracking_acquisition_combo.currentText() == "自动获取"


def test_shift_acquisition_while_pointer_moves(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (-10, 0)),))
    editor.object_tracking_check.setChecked(True)
    editor.object_tracking_acquisition_combo.setCurrentText("按 Shift 获取")
    assert canvas.set_tool("圆")
    pixel = canvas.local_to_screen((0, 0))
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(pixel),
            QPointF(canvas.mapToGlobal(pixel)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ShiftModifier,
        ),
    )
    assert canvas.acquired_tracking_points == ((0, 0),)
    editor.snap_check.setChecked(False)
    assert canvas.acquired_tracking_points == ()


@pytest.mark.parametrize("angle", [123.456, -0.014])
def test_object_tracking_small_polar_increment_wraps(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, angle: float
) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (-10, 0)),))
    editor.object_tracking_check.setChecked(True)
    editor.object_tracking_angle_combo.setCurrentText("使用极轴角度")
    canvas.set_polar_angle_increment(0.01)
    assert canvas.set_tool("圆")
    move(editor, (0, 0))
    raw = (100 * math.cos(math.radians(angle)), 100 * math.sin(math.radians(angle)))

    def exact_position(_position: QPointF) -> tuple[float, float]:
        return raw

    monkeypatch.setattr(canvas, "screen_to_local", exact_position)
    move(editor, (10, 10))
    assert canvas.current_snap_kind == "对象追踪"
    _, result = canvas.object_tracking_paths[0]
    actual = math.degrees(math.atan2(result[1], result[0])) % 360
    assert actual == pytest.approx(round(angle % 360, 2), abs=1e-7)


def test_object_tracking_reenter_acquired_point_removes_it(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (-10, 0)),))
    editor.object_tracking_check.setChecked(True)
    assert canvas.set_tool("圆")
    move(editor, (0, 0))
    assert canvas.acquired_tracking_points == ((0, 0),)
    move(editor, (0, 0))
    assert canvas.acquired_tracking_points == ((0, 0),)
    move(editor, (20, 20))
    move(editor, (0, 0))
    assert canvas.acquired_tracking_points == ()


def test_shift_acquisition_reenter_requires_shift_to_remove(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (-10, 0)),))
    editor.object_tracking_check.setChecked(True)
    editor.object_tracking_acquisition_combo.setCurrentText("按 Shift 获取")
    assert canvas.set_tool("圆")
    move(editor, (0, 0))
    QTest.keyPress(canvas, Qt.Key.Key_Shift)
    QTest.keyRelease(canvas, Qt.Key.Key_Shift)
    assert canvas.acquired_tracking_points == ((0, 0),)
    move(editor, (20, 20))
    move(editor, (0, 0))
    assert canvas.acquired_tracking_points == ((0, 0),)
    QTest.keyPress(canvas, Qt.Key.Key_Shift)
    QTest.keyRelease(canvas, Qt.Key.Key_Shift)
    assert canvas.acquired_tracking_points == ()


def test_removing_one_tracking_point_preserves_other(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    assert canvas.replace_draft_entities(
        (
            LineEntity(uuid4().hex, (0, 0), (-10, 0)),
            LineEntity(uuid4().hex, (20, 20), (30, 20)),
        )
    )
    editor.object_tracking_check.setChecked(True)
    assert canvas.set_tool("圆")
    move(editor, (0, 0))
    move(editor, (20, 20))
    move(editor, (0, 0))
    assert canvas.acquired_tracking_points == ((20, 20),)
    move(editor, (40, 20.8))
    assert canvas.current_snap_kind == "对象追踪"
    assert canvas.object_tracking_paths[0][0] == (20, 20)
