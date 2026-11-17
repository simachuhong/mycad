# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent 2D polar tracking and status controls."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import ArcEntity, LineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


@pytest.mark.parametrize("tool", ["直线", "多段线"])
def test_relative_polar_tracks_last_segment_during_drawing(qtbot: QtBot, tool: str) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.polar_reference_combo.setCurrentText("相对上一段")
    editor.polar_check.setChecked(True)
    assert canvas.set_tool(tool)
    canvas.add_coordinate_point((0, 0), exact_point=True)
    first = (10 * math.cos(math.radians(30)), 5.0)
    canvas.add_coordinate_point(first, exact_point=True)
    raw = (first[0] + 10 * math.cos(math.radians(121)), first[1] + 10 * math.sin(math.radians(121)))
    canvas.add_coordinate_point(raw)
    assert canvas.current_snap_kind == "极轴 120°"
    if tool == "多段线":
        canvas.finish_polyline()
        from mycad.core.sketch import PolylineEntity

        assert isinstance(canvas.entities[0], PolylineEntity)
        end = canvas.entities[0].points_mm[-1]
    else:
        assert isinstance(canvas.entities[-1], LineEntity)
        end = canvas.entities[-1].end_mm
    delta = (end[0] - first[0], end[1] - first[1])
    assert math.degrees(math.atan2(delta[1], delta[0])) == pytest.approx(120)


def test_three_point_arc_relative_polar_direct_distance_uses_last_point(qtbot: QtBot) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    editor.polar_reference_combo.setCurrentText("相对上一段")
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("圆弧")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10 * math.cos(math.radians(30)), 5), exact_point=True)
    previous = canvas.pending_last_point
    assert previous is not None
    target = (previous[0] - 5, previous[1] + 8.66)
    QTest.mouseMove(canvas, canvas.local_to_screen((20, 20)))
    QTest.mouseMove(canvas, canvas.local_to_screen(target))
    assert canvas.current_snap_kind == "极轴 120°"
    bar = editor.drawing_command_bar.input
    bar.setText("10")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], ArcEntity)
    arc = canvas.entities[0]
    end = math.radians(arc.start_angle_deg + arc.sweep_angle_deg)
    assert (
        arc.center_mm[0] + arc.radius_mm * math.cos(end),
        arc.center_mm[1] + arc.radius_mm * math.sin(end),
    ) == pytest.approx((previous[0] - 5, previous[1] + 5 * math.sqrt(3)))


def test_center_arc_relative_polar_direct_distance_uses_last_point(qtbot: QtBot) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    editor.polar_reference_combo.setCurrentText("相对上一段")
    editor.polar_check.setChecked(True)
    editor.arc_center_button.click()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10 * math.cos(math.radians(30)), 5), exact_point=True)
    previous = canvas.pending_last_point
    assert previous is not None
    QTest.mouseMove(canvas, canvas.local_to_screen((20, 20)))
    QTest.mouseMove(canvas, canvas.local_to_screen((previous[0] - 5, previous[1] + 8.66)))
    assert canvas.current_snap_kind == "极轴 120°"
    bar = editor.drawing_command_bar.input
    bar.setText("10")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], ArcEntity)
    assert canvas.entities[0].sweep_angle_deg == pytest.approx(45)


def test_relative_polar_reference_follows_undo_redo(qtbot: QtBot) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.polar_reference_combo.setCurrentText("相对上一段")
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((15, 5 / math.sqrt(3)), exact_point=True)
    assert canvas.undo_last_operation()
    assert canvas.redo_last_operation()
    canvas.add_coordinate_point((10.1, 5 / math.sqrt(3) + 8.66))
    assert canvas.current_snap_kind == "极轴 120°"


def test_relative_polar_keeps_additional_angles_absolute(qtbot: QtBot) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.polar_reference_combo.setCurrentText("相对上一段")
    canvas.set_polar_additional_angles((37.0,))
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    start = (10 * math.cos(math.radians(30)), 5.0)
    canvas.add_coordinate_point(start, exact_point=True)
    canvas.add_coordinate_point(
        (start[0] + 10 * math.cos(math.radians(38)), start[1] + 10 * math.sin(math.radians(38)))
    )
    assert canvas.current_snap_kind == "极轴 37°"


def test_relative_polar_uses_completed_polyline_last_segment(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.polar_reference_combo.setCurrentText("相对上一段")
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("多段线")
    for point in ((0, 0), (10, 0), (15, 5)):
        canvas.add_coordinate_point(point, exact_point=True)
    canvas.finish_polyline()
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((30, 0), exact_point=True)
    canvas.add_coordinate_point((25, 5.1))
    assert canvas.current_snap_kind == "极轴 135°"


def test_relative_polar_uses_tangent_line_after_chain_ends(qtbot: QtBot) -> None:
    import math
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    assert canvas.replace_draft_entities((circle,))
    editor.polar_reference_combo.setCurrentText("相对上一段")
    editor.polar_check.setChecked(True)
    command = editor.drawing_command_bar.input
    for value in ("LINE", "10,0", "TAN", "2.5,4.33"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    line = canvas.entities[-1]
    assert isinstance(line, LineEntity)
    direction = math.degrees(
        math.atan2(line.end_mm[1] - line.start_mm[1], line.end_mm[0] - line.start_mm[0])
    )
    canvas.end_line_chain()
    canvas.add_coordinate_point((30, 30), exact_point=True)
    target_angle = direction + 90
    canvas.add_coordinate_point(
        (
            30 + 10 * math.cos(math.radians(target_angle + 1)),
            30 + 10 * math.sin(math.radians(target_angle + 1)),
        )
    )
    assert isinstance(canvas.entities[-1], LineEntity)
    delta = (canvas.entities[-1].end_mm[0] - 30, canvas.entities[-1].end_mm[1] - 30)
    difference = (math.degrees(math.atan2(delta[1], delta[0])) - target_angle + 180) % 360 - 180
    assert difference == pytest.approx(0, abs=1e-8)


def test_relative_polar_reference_survives_commit_and_falls_back_after_undo(qtbot: QtBot) -> None:
    import math

    from mycad.app import build_app
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.canvas.set_snapping_enabled(False)
    editor.canvas.set_auto_inference_enabled(False)
    editor.polar_reference_combo.setCurrentText("相对上一段")
    editor.polar_check.setChecked(True)
    assert editor.canvas.set_tool("直线")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((10 * math.cos(math.radians(30)), 5), exact_point=True)
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    continued = window.active_sketch_dialog()
    assert continued is not None
    assert continued.polar_reference_combo.currentText() == "相对上一段"
    continued.canvas.set_snapping_enabled(False)
    continued.canvas.set_auto_inference_enabled(False)
    assert continued.canvas.set_tool("直线")
    continued.canvas.add_coordinate_point((30, 0), exact_point=True)
    continued.canvas.add_coordinate_point((25, 8.66))
    assert continued.canvas.current_snap_kind == "极轴 120°"
    continued.canvas.end_line_chain()
    assert continued.canvas.undo_last_operation()
    continued.canvas.end_line_chain()
    continued.canvas.discard_redo_history()
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and not continued.canvas.background_entities, timeout=15000
    )
    assert continued.canvas.set_tool("直线")
    continued.canvas.add_coordinate_point((30, 0), exact_point=True)
    continued.canvas.add_coordinate_point((25, 8.66))
    assert "极轴" not in continued.canvas.current_snap_kind


def _set_angle_responses(
    monkeypatch: pytest.MonkeyPatch, responses: tuple[tuple[str, bool], ...]
) -> None:
    entries = iter(responses)

    def answer(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return next(entries)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", answer)


def test_additional_polar_angles_are_individual_directions(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    _set_angle_responses(monkeypatch, (("37", True),))
    editor.polar_additional_button.click()
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    raw = (10 * math.cos(math.radians(39)), 10 * math.sin(math.radians(39)))
    canvas.add_coordinate_point(raw)
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.current_snap_kind == "极轴 37°"
    assert math.degrees(math.atan2(canvas.entities[0].end_mm[1], canvas.entities[0].end_mm[0])) == (
        pytest.approx(37)
    )
    next_point = (
        canvas.entities[0].end_mm[0] + 10 * math.cos(math.radians(74)),
        canvas.entities[0].end_mm[1] + 10 * math.sin(math.radians(74)),
    )
    canvas.add_coordinate_point(next_point)
    assert isinstance(canvas.entities[1], LineEntity)
    assert canvas.entities[1].end_mm == pytest.approx(next_point)


def test_additional_polar_angles_reject_invalid_and_follow_workspace(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = SketchEditorDialog(select_committed_entities=True)
    continued = SketchEditorDialog(select_committed_entities=True)
    other = SketchEditorDialog(select_committed_entities=True)
    for editor in (source, continued, other):
        qtbot.addWidget(editor)
    _set_angle_responses(monkeypatch, (("37， 112.5", True), ("37, nan", True)))
    source.polar_additional_button.click()
    source.polar_additional_button.click()
    assert source.canvas.polar_additional_angles == (37, 112.5)
    continued.continue_workspace_from(source)
    assert continued.canvas.polar_additional_angles == (37, 112.5)
    assert other.canvas.polar_additional_angles == ()


@pytest.mark.parametrize(
    "angles", [(-1.0,), (360.0,), (float("inf"),), (float("nan"),), tuple(range(11))]
)
def test_additional_polar_angles_validate_atomically(
    qtbot: QtBot, angles: tuple[float, ...]
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.canvas.set_polar_additional_angles((37.0,))
    with pytest.raises(ValueError, match="附加角度"):
        editor.canvas.set_polar_additional_angles(angles)
    assert editor.canvas.polar_additional_angles == (37.0,)


def test_additional_polar_angles_cancel_clear_and_apply_distance_snap(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    _set_angle_responses(monkeypatch, (("37", True), ("77", False), ("", True)))
    editor.polar_additional_button.click()
    editor.polar_additional_button.click()
    assert canvas.polar_additional_angles == (37.0,)
    editor.snap_type_combo.setCurrentText("极轴距离")
    editor.polar_spacing_field.setValue(4)
    editor.grid_snap_check.setChecked(True)
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point(
        (10.5 * math.cos(math.radians(38)), 10.5 * math.sin(math.radians(38)))
    )
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx(
        (12 * math.cos(math.radians(37)), 12 * math.sin(math.radians(37)))
    )
    editor.polar_additional_button.click()
    assert canvas.polar_additional_angles == ()


def test_polar_angle_change_refreshes_stationary_drawing_preview(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QSignalSpy
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    pixel = canvas.local_to_screen((10, 10.5))
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
    assert not canvas.current_snap_kind
    cursor_updates = QSignalSpy(canvas.cursor_changed)
    editor.polar_angle_field.setValue(45)
    assert canvas.current_snap_kind == "极轴 45°"
    assert cursor_updates.count() == 1
    editor.orthogonal_check.setChecked(True)
    updated = cursor_updates.at(cursor_updates.count() - 1)
    assert updated[0] == pytest.approx(0)


@pytest.mark.parametrize("shift", [False, True])
def test_polar_angle_change_refreshes_stationary_move_preview(qtbot: QtBot, shift: bool) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    editor.polar_check.setChecked(True)
    command = editor.drawing_command_bar.input
    for value in ("MOVE", "0,0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    pixel = canvas.local_to_screen((10, 10.5))
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(pixel),
            QPointF(canvas.mapToGlobal(pixel)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert not canvas.current_snap_kind
    editor.polar_angle_field.setValue(45)
    assert canvas.current_snap_kind == ("" if shift else "极轴 45°")
    preview = canvas.transform_preview_entities
    assert len(preview) == 1 and isinstance(preview[0], LineEntity)
    raw = canvas.screen_to_local(QPointF(pixel))
    expected = raw if shift else ((raw[0] + raw[1]) / 2,) * 2
    assert preview[0].start_mm == pytest.approx(expected)


@pytest.mark.parametrize("operation", ["LINE", "MOVE"])
@pytest.mark.parametrize("command_focus", [False, True])
def test_shift_recomputes_stationary_polar_preview(
    qtbot: QtBot, operation: str, command_focus: bool
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QSignalSpy
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    if operation == "MOVE":
        source = LineEntity(uuid4().hex, (0, 0), (2, 0))
        assert canvas.replace_draft_entities((source,))
        canvas.selected_entity_ids = {source.entity_id}
    editor.polar_angle_field.setValue(45)
    editor.polar_check.setChecked(True)
    command = editor.drawing_command_bar.input
    for value in (operation, "0,0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    pixel = canvas.local_to_screen((10, 10.5))
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
    assert canvas.current_snap_kind == "极轴 45°"
    updates = QSignalSpy(canvas.cursor_changed)
    target = command if command_focus else canvas
    QTest.keyPress(target, Qt.Key.Key_Shift)
    assert "极轴" not in canvas.current_snap_kind
    raw = canvas.screen_to_local(QPointF(pixel))
    released_snap = updates.at(updates.count() - 1)
    assert (released_snap[0], released_snap[1]) == pytest.approx(raw)
    QTest.keyRelease(target, Qt.Key.Key_Shift)
    assert canvas.current_snap_kind == "极轴 45°"
    restored_snap = updates.at(updates.count() - 1)
    assert restored_snap[0] == pytest.approx(restored_snap[1])


@pytest.mark.parametrize("operation", ["LINE", "MOVE", "PLINE", "CIRCLE"])
@pytest.mark.parametrize("command_focus", [False, True])
@pytest.mark.parametrize("snap_mode", ["grid", "object"])
def test_shift_recomputes_stationary_snap_preview_without_polar(
    qtbot: QtBot, operation: str, command_focus: bool, snap_mode: str
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(snap_mode == "object")
    canvas.set_auto_inference_enabled(False)
    if snap_mode == "object":
        boundary = LineEntity(uuid4().hex, (10, 10), (15, 10))
        assert canvas.replace_draft_entities((boundary,))
    if operation == "MOVE":
        source = LineEntity(uuid4().hex, (0, 0), (2, 0))
        assert canvas.replace_draft_entities((*canvas.entities, source))
        canvas.selected_entity_ids = {source.entity_id}
    editor.grid_snap_check.setChecked(snap_mode == "grid")
    command = editor.drawing_command_bar.input
    for value in (operation, "0,0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    step = canvas.grid_spacing_mm()
    raw = (2 * step + 0.4, step + 0.4) if snap_mode == "grid" else (10.4, 10.4)
    pixel = canvas.local_to_screen(raw)
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
    expected = "栅格" if snap_mode == "grid" else "端点"
    assert canvas.current_snap_kind == expected
    target = command if command_focus else canvas
    QTest.keyPress(target, Qt.Key.Key_Shift)
    assert canvas.current_snap_kind != expected
    QTest.keyRelease(target, Qt.Key.Key_Shift)
    assert canvas.current_snap_kind == expected


def test_polar_snap_quantizes_distance_and_exact_input_bypasses_it(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.snap_type_combo.setCurrentText("极轴距离")
    editor.polar_spacing_field.setValue(4.0)
    editor.grid_snap_check.setChecked(True)
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10.2, 0.2))
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((12, 0))
    canvas.add_coordinate_point((17.3, 0), exact_point=True)
    assert isinstance(canvas.entities[1], LineEntity)
    assert canvas.entities[1].end_mm == pytest.approx((17.3, 0))


def test_polar_snap_preferences_follow_same_workspace(qtbot: QtBot) -> None:
    source = SketchEditorDialog(select_committed_entities=True)
    other = SketchEditorDialog(select_committed_entities=True)
    continued = SketchEditorDialog(select_committed_entities=True)
    for editor in (source, other, continued):
        qtbot.addWidget(editor)
    source.snap_type_combo.setCurrentText("极轴距离")
    source.polar_spacing_field.setValue(7.5)
    continued.continue_workspace_from(source)
    assert continued.snap_type_combo.currentText() == "极轴距离"
    assert continued.polar_spacing_field.value() == pytest.approx(7.5)
    assert other.snap_type_combo.currentText() == "矩形栅格"


@pytest.mark.parametrize(
    "snap_on,tracking_on,expected", [(False, True, 10.0), (True, False, 10.0), (True, True, 12.0)]
)
def test_polar_snap_requires_snap_mode_and_tracking(
    qtbot: QtBot, snap_on: bool, tracking_on: bool, expected: float
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.snap_type_combo.setCurrentText("极轴距离")
    editor.polar_spacing_field.setValue(4.0)
    editor.grid_snap_check.setChecked(snap_on)
    editor.polar_check.setChecked(tracking_on)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0))
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((expected, 0))


def test_polar_snap_zero_spacing_uses_grid_interval(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.snap_type_combo.setCurrentText("极轴距离")
    editor.grid_snap_check.setChecked(True)
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    step = canvas.grid_spacing_mm()
    canvas.add_coordinate_point((step * 2.7, 0))
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((step * 3, 0))


@pytest.mark.parametrize("invalid", [-1.0, float("nan"), float("inf")])
def test_polar_snap_spacing_rejects_invalid_values(qtbot: QtBot, invalid: float) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    with pytest.raises(ValueError, match="极轴捕捉距离"):
        editor.canvas.set_polar_snap_spacing(invalid)


def test_polar_snap_gives_objects_priority(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    editor.snap_type_combo.setCurrentText("极轴距离")
    editor.polar_spacing_field.setValue(4.0)
    editor.grid_snap_check.setChecked(True)
    editor.polar_check.setChecked(True)
    canvas.entities = [LineEntity("a" * 32, (10, 0), (10, 10))]
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10.1, 0.1))
    assert isinstance(canvas.entities[-1], LineEntity)
    assert canvas.entities[-1].end_mm == pytest.approx((10, 0))
    assert canvas.current_snap_kind == "端点"


def test_polar_snap_move_mouse_commit_and_undo(qtbot: QtBot) -> None:
    from uuid import uuid4

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    editor.snap_type_combo.setCurrentText("极轴距离")
    editor.polar_spacing_field.setValue(4)
    editor.grid_snap_check.setChecked(True)
    editor.polar_check.setChecked(True)
    command = editor.drawing_command_bar.input
    for text in ("MOVE", "0,0"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].start_mm == pytest.approx((12, 0))
    assert canvas.undo_last_operation() and canvas.entities == [source]


def test_polar_tracking_snaps_near_increment_and_preserves_exact_input(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.polar_angle_field.setValue(45)
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 10.5))
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((10.25, 10.25))
    assert "极轴" in canvas.current_snap_kind
    canvas.add_coordinate_point((20, 22.25), exact_point=True)
    assert isinstance(canvas.entities[1], LineEntity)
    assert canvas.entities[1].end_mm == pytest.approx((20, 22.25))


def test_f10_and_f8_are_mutually_exclusive(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    qtbot.waitExposed(editor)
    command = editor.drawing_command_bar.input
    editor.activateWindow()
    command.setFocus()
    qtbot.waitUntil(command.hasFocus)
    QTest.keyClick(command, Qt.Key.Key_F10)
    assert editor.polar_check.isChecked() and not editor.orthogonal_check.isChecked()
    editor.snap_type_combo.setCurrentText("极轴距离")
    QTest.keyClick(command, Qt.Key.Key_F9)
    assert editor.grid_snap_check.isChecked()
    QTest.keyClick(command, Qt.Key.Key_F9)
    assert not editor.grid_snap_check.isChecked()
    QTest.keyClick(command, Qt.Key.Key_F8)
    assert editor.orthogonal_check.isChecked() and not editor.polar_check.isChecked()
    QTest.keyClick(command, Qt.Key.Key_F10)
    assert editor.polar_check.isChecked() and not editor.orthogonal_check.isChecked()


def test_polar_tracking_state_follows_only_same_workspace(qtbot: QtBot) -> None:
    first = SketchEditorDialog(select_committed_entities=True)
    second = SketchEditorDialog(select_committed_entities=True)
    continued = SketchEditorDialog(select_committed_entities=True)
    for editor in (first, second, continued):
        qtbot.addWidget(editor)
    first.polar_angle_field.setValue(22.5)
    first.polar_reference_combo.setCurrentText("相对上一段")
    first.polar_check.setChecked(True)
    continued.continue_workspace_from(first)
    assert (
        continued.polar_check.isChecked()
        and continued.polar_angle_field.value() == pytest.approx(22.5)
    )
    assert continued.polar_reference_combo.currentText() == "相对上一段"
    assert second.polar_reference_combo.currentText() == "UCS角度"
    assert not second.polar_check.isChecked() and second.polar_angle_field.value() == pytest.approx(
        90
    )


def test_polar_tracking_skips_angles_outside_acquisition_window(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.polar_angle_field.setValue(45)
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 12))
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((10, 12))
    assert "极轴" not in canvas.current_snap_kind


def test_object_snap_takes_precedence_over_polar_tracking(qtbot: QtBot) -> None:
    from uuid import uuid4

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    source = LineEntity(uuid4().hex, (10, 10.5), (12, 10.5))
    assert canvas.replace_draft_entities((source,))
    editor.polar_angle_field.setValue(45)
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10.05, 10.45))
    assert len(canvas.entities) == 2 and isinstance(canvas.entities[-1], LineEntity)
    assert canvas.entities[-1].end_mm == pytest.approx((10, 10.5))
    assert canvas.current_snap_kind == "端点"


def test_polar_tracking_uses_current_polyline_vertex(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    editor.polar_angle_field.setValue(45)
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("多段线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 10.5))
    canvas.add_coordinate_point((20.5, 20.25))
    canvas.finish_polyline()
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity)
    assert canvas.entities[0].points_mm[1] == pytest.approx((10.25, 10.25))
    assert canvas.entities[0].points_mm[2] == pytest.approx((20.375, 20.375))


def test_shift_temporarily_disables_polar_tracking(qtbot: QtBot) -> None:
    from PySide6.QtCore import QPointF

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.polar_angle_field.setValue(45)
    editor.snap_type_combo.setCurrentText("极轴距离")
    editor.polar_spacing_field.setValue(4)
    editor.grid_snap_check.setChecked(True)
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    pixel = canvas.local_to_screen((10, 10.5))
    expected = canvas.screen_to_local(QPointF(pixel))
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, pos=pixel
    )
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx(expected)
    assert canvas.current_snap_kind == "临时关闭捕捉"


def test_polar_tracking_accepts_direct_distance_in_command_bar(qtbot: QtBot) -> None:
    import math

    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.polar_angle_field.setValue(45)
    editor.snap_type_combo.setCurrentText("极轴距离")
    editor.polar_spacing_field.setValue(7)
    editor.grid_snap_check.setChecked(True)
    editor.polar_check.setChecked(True)
    command = editor.drawing_command_bar.input
    for value in ("LINE", "0,0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    pixel = canvas.local_to_screen((10, 10.5))
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
    assert "极轴" in canvas.current_snap_kind
    command.setText("20")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((10 * math.sqrt(2), 10 * math.sqrt(2)))
    assert command.text() == ""


@pytest.mark.parametrize("operation", ["LINE", "MOVE"])
@pytest.mark.parametrize("sign", [1, -1])
def test_polar_direct_distance_keeps_direction_at_zero_snap(
    qtbot: QtBot, operation: str, sign: int
) -> None:
    import math
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    if operation == "MOVE":
        source = LineEntity(uuid4().hex, (0, 0), (2, 0))
        assert canvas.replace_draft_entities((source,))
        canvas.selected_entity_ids = {source.entity_id}
    editor.polar_angle_field.setValue(45)
    editor.snap_type_combo.setCurrentText("极轴距离")
    editor.polar_spacing_field.setValue(100)
    editor.grid_snap_check.setChecked(True)
    editor.polar_check.setChecked(True)
    command = editor.drawing_command_bar.input
    for value in (operation, "0,0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    pixel = canvas.local_to_screen((sign * 10, sign * 10.5))
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
    assert "极轴" in canvas.current_snap_kind
    command.setText("20")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
    expected = (sign * 10 * math.sqrt(2), sign * 10 * math.sqrt(2))
    actual = canvas.entities[0].end_mm if operation == "LINE" else canvas.entities[0].start_mm
    assert actual == pytest.approx(expected)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_polar_direct_distance_rejects_invalid_values(qtbot: QtBot, value: str) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.polar_check.setChecked(True)
    command = editor.drawing_command_bar.input
    for text in ("LINE", "0,0"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    pixel = canvas.local_to_screen((10, 0))
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
    assert "极轴" in canvas.current_snap_kind
    command.setText(value)
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert not canvas.entities and canvas.pending_last_point == (0, 0)
    assert command.text() == value
    assert "距离" in editor.drawing_command_bar.status.text()


def test_polar_state_survives_real_sketch_commit(qtbot: QtBot) -> None:
    import math

    from mycad.app import build_app
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.resize(1200, 800)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.polar_angle_field.setValue(30)
    editor.polar_check.setChecked(True)
    editor.canvas.set_snapping_enabled(False)
    editor.canvas.set_auto_inference_enabled(False)
    assert editor.canvas.set_tool("直线")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((10, 5.9))
    assert len(editor.canvas.entities) == 1 and isinstance(editor.canvas.entities[0], LineEntity)
    line = editor.canvas.entities[0]
    distance = 10 * math.cos(math.radians(30)) + 5.9 * math.sin(math.radians(30))
    assert line.end_mm == pytest.approx((distance * math.cos(math.radians(30)), distance / 2))
    editor.snap_type_combo.setCurrentText("极轴距离")
    editor.polar_spacing_field.setValue(2.5)
    editor.grid_snap_check.setChecked(True)
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    continued = window.active_sketch_dialog()
    assert continued is not None
    assert (
        continued.polar_check.isChecked()
        and continued.polar_angle_field.value() == pytest.approx(30)
    )
    assert not continued.orthogonal_check.isChecked()
    assert continued.grid_snap_check.isChecked()
    assert continued.snap_type_combo.currentText() == "极轴距离"
    assert continued.polar_spacing_field.value() == pytest.approx(2.5)
    assert any(entity == line for entity, _ in continued.canvas.background_entities)


@pytest.mark.parametrize("invalid", [0.0, -1.0, 360.01, float("nan"), float("inf")])
def test_polar_increment_rejects_invalid_values(qtbot: QtBot, invalid: float) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    with pytest.raises(ValueError, match="角度增量"):
        editor.canvas.set_polar_angle_increment(invalid)


def test_polar_tracking_wraps_around_zero_degrees(qtbot: QtBot) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_auto_inference_enabled(False)
    editor.polar_angle_field.setValue(22.5)
    editor.polar_check.setChecked(True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10 * math.cos(math.radians(-2)), 10 * math.sin(math.radians(-2))))
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm[1] == pytest.approx(0, abs=1e-12)
    assert canvas.current_snap_kind == "极轴 0°"


def test_polar_tracking_applies_to_move_preview_and_direct_distance(qtbot: QtBot) -> None:
    import math
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    editor.polar_angle_field.setValue(45)
    editor.polar_check.setChecked(True)
    command = editor.drawing_command_bar.input
    for text in ("MOVE", "0,0"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    pixel = canvas.local_to_screen((10, 10.5))
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
    assert "极轴" in canvas.current_snap_kind
    assert len(canvas.transform_preview_entities) == 1
    command.setText("20")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].start_mm == pytest.approx((10 * math.sqrt(2), 10 * math.sqrt(2)))
    assert canvas.undo_last_operation() and canvas.entities == [source]


def test_polar_tracking_copy_direct_distance_and_command_undo(qtbot: QtBot) -> None:
    import math
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    editor.polar_angle_field.setValue(45)
    editor.polar_check.setChecked(True)
    command = editor.drawing_command_bar.input
    for text in ("COPY", "0,0"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    pixel = canvas.local_to_screen((10, 10.5))
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
    command.setText("20")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2 and isinstance(canvas.entities[-1], LineEntity)
    assert canvas.entities[-1].start_mm == pytest.approx((10 * math.sqrt(2), 10 * math.sqrt(2)))
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [source]
