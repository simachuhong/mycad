# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""CAD drafting gestures must preview before a reversible geometry edit."""

from uuid import uuid4

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.core.sketch import LineEntity
from mycad.ui.sketch_editor import SketchCanvas, SketchEditorDialog


def _editor(qtbot: QtBot) -> tuple[SketchEditorDialog, LineEntity]:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    editor.canvas.set_snapping_enabled(False)
    line = LineEntity(uuid4().hex, (20.0, 10.0), (30.0, 10.0))
    editor.canvas.replace_draft_entities((line,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    return editor, line


def _hover(canvas: SketchCanvas, point: tuple[float, float]) -> None:
    position = QPointF(canvas.local_to_screen(point))
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            position,
            canvas.mapToGlobal(position),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def test_rotation_uses_picked_center_preview_cancel_and_undo(qtbot: QtBot) -> None:
    editor, line = _editor(qtbot)
    canvas = editor.canvas
    editor.transform_buttons["rotate"].click()
    assert tuple(canvas.entities) == (line,)
    assert canvas.has_active_edit_gesture
    canvas.add_coordinate_point((10.0, 10.0), exact_point=True)
    _hover(canvas, (10.0, 30.0))
    assert tuple(canvas.entities) == (line,)
    preview = canvas.transform_preview_entities[0]
    assert isinstance(preview, LineEntity)
    assert preview.start_mm == pytest.approx((10.0, 20.0))
    assert preview.end_mm == pytest.approx((10.0, 30.0))
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert tuple(canvas.entities) == (line,)
    assert not canvas.has_active_edit_gesture
    editor.transform_buttons["rotate"].click()
    canvas.add_coordinate_point((10.0, 10.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 30.0), exact_point=True)
    rotated = canvas.entities[0]
    assert rotated == preview
    assert canvas.undo_last_operation()
    assert tuple(canvas.entities) == (line,)
    assert canvas.redo_last_operation()
    assert canvas.entities == [rotated]


def test_rotation_accepts_typed_angle_after_center(qtbot: QtBot) -> None:
    editor, line = _editor(qtbot)
    canvas = editor.canvas
    editor.transform_buttons["rotate"].click()
    canvas.add_coordinate_point((10.0, 10.0), exact_point=True)
    QTest.keyClicks(canvas, "-90")
    assert tuple(canvas.entities) == (line,)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    rotated = canvas.entities[0]
    assert isinstance(rotated, LineEntity)
    assert rotated.start_mm == pytest.approx((10.0, 0.0))
    assert rotated.end_mm == pytest.approx((10.0, -10.0))


def test_reference_rotation_uses_from_and_to_rays(qtbot: QtBot) -> None:
    editor, line = _editor(qtbot)
    canvas = editor.canvas
    editor.rotation_reference_check.setChecked(True)
    editor.transform_buttons["rotate"].click()
    for point in ((10.0, 10.0), (10.0, 30.0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert tuple(canvas.entities) == (line,)
    assert canvas.has_active_edit_gesture
    _hover(canvas, (-10.0, 10.0))
    assert tuple(canvas.entities) == (line,)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-10.0, 10.0)))
    rotated = canvas.entities[0]
    assert isinstance(rotated, LineEntity)
    assert rotated.start_mm == pytest.approx((10.0, 20.0))
    assert rotated.end_mm == pytest.approx((10.0, 30.0))


@pytest.mark.parametrize("keep_source", [True, False])
def test_mirror_arbitrary_axis_keeps_or_replaces_source(qtbot: QtBot, keep_source: bool) -> None:
    editor, line = _editor(qtbot)
    canvas = editor.canvas
    editor.mirror_keep_source_check.setChecked(keep_source)
    editor.transform_buttons["mirror"].click()
    assert tuple(canvas.entities) == (line,)
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    assert tuple(canvas.entities) == (line,)
    assert canvas.has_active_edit_gesture
    _hover(canvas, (30.0, 30.0))
    assert tuple(canvas.entities) == (line,)
    assert len(canvas.transform_preview_entities) == 1
    canvas.add_coordinate_point((30.0, 30.0), exact_point=True)
    assert len(canvas.entities) == (2 if keep_source else 1)
    mirrored = canvas.entities[-1]
    assert isinstance(mirrored, LineEntity)
    assert mirrored.start_mm == pytest.approx((10.0, 20.0))
    assert mirrored.end_mm == pytest.approx((10.0, 30.0))
    assert (mirrored.entity_id != line.entity_id) == keep_source
    assert canvas.undo_last_operation()
    assert tuple(canvas.entities) == (line,)
    assert canvas.redo_last_operation()
    assert canvas.entities[-1] == mirrored


@pytest.mark.parametrize("operation", ["rotate", "mirror"])
def test_command_first_transform_selection(qtbot: QtBot, operation: str) -> None:
    editor, line = _editor(qtbot)
    canvas = editor.canvas
    canvas.selected_entity_ids.clear()
    canvas.changed.emit()
    assert editor.transform_buttons[operation].isEnabled()
    editor.transform_buttons[operation].click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((25.0, 10.0)))
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas.selected_entity_ids == {line.entity_id}
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((0.0, 30.0), exact_point=True)
    assert not canvas.has_active_edit_gesture
    assert tuple(canvas.entities) != (line,)


@pytest.mark.parametrize("operation", ["rotate", "mirror"])
def test_transform_cancel_preserves_history_and_user_constraints(
    qtbot: QtBot, operation: str
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor, line = _editor(qtbot)
    canvas = editor.canvas
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    canvas.constraints = [constraint]
    position = canvas.history_position
    editor.mirror_keep_source_check.setChecked(False)
    editor.transform_buttons[operation].click()
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((0.0, 30.0), exact_point=True)
    assert tuple(canvas.entities) == (line,)
    assert canvas.constraints == [constraint]
    assert not canvas.transform_preview_entities
    assert "用户约束" in canvas.message
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.history_position == position
    assert not canvas.has_active_edit_gesture


@pytest.mark.parametrize("operation", ["rotate", "mirror"])
def test_transform_refuses_locked_selection(qtbot: QtBot, operation: str) -> None:
    from mycad.core.sketch_layers import SketchLayer

    editor, line = _editor(qtbot)
    canvas = editor.canvas
    canvas.set_layer_table(canvas.layer_table.replace(SketchLayer("0", locked=True)), "0")
    editor.transform_buttons[operation].click()
    assert tuple(canvas.entities) == (line,)
    assert not canvas.has_active_edit_gesture
    assert "已锁定" in canvas.message


def test_mirror_cancel_discards_preview_without_creating_copy(qtbot: QtBot) -> None:
    editor, line = _editor(qtbot)
    canvas = editor.canvas
    position = canvas.history_position
    editor.transform_buttons["mirror"].click()
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    _hover(canvas, (10.0, 10.0))
    assert canvas.transform_preview_entities
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert tuple(canvas.entities) == (line,)
    assert not canvas.transform_preview_entities
    assert canvas.history_position == position


def test_numeric_rotation_before_picking_uses_entered_center(qtbot: QtBot) -> None:
    editor, _line = _editor(qtbot)
    editor.center_u_field.setValue(10.0)
    editor.center_v_field.setValue(10.0)
    editor.angle_field.setValue(90.0)
    editor.transform_buttons["rotate"].click()
    editor.numeric_rotate_button.click()
    assert not editor.canvas.has_active_edit_gesture
    rotated = editor.canvas.entities[0]
    assert isinstance(rotated, LineEntity)
    assert rotated.start_mm == pytest.approx((10.0, 20.0))
    assert rotated.end_mm == pytest.approx((10.0, 30.0))


def test_mirror_option_changed_during_preview_controls_commit(qtbot: QtBot) -> None:
    editor, line = _editor(qtbot)
    canvas = editor.canvas
    editor.transform_buttons["mirror"].click()
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    _hover(canvas, (30.0, 30.0))
    editor.mirror_keep_source_check.setChecked(False)
    assert tuple(canvas.entities) == (line,)
    canvas.add_coordinate_point((30.0, 30.0), exact_point=True)
    assert len(canvas.entities) == 1
    assert canvas.entities[0].entity_id == line.entity_id


def test_reference_option_can_change_after_starting_rotation(qtbot: QtBot) -> None:
    editor, line = _editor(qtbot)
    canvas = editor.canvas
    editor.transform_buttons["rotate"].click()
    editor.rotation_reference_check.setChecked(True)
    canvas.add_coordinate_point((10.0, 10.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 30.0), exact_point=True)
    assert tuple(canvas.entities) == (line,)
    canvas.add_coordinate_point((-10.0, 10.0), exact_point=True)
    rotated = canvas.entities[0]
    assert isinstance(rotated, LineEntity)
    assert rotated.start_mm == pytest.approx((10.0, 20.0))
