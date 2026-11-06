# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Pointer placement must preview atomically, then support cancel and undo."""

from uuid import uuid4

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.core.sketch import LineEntity
from mycad.core.sketch_edit import trim_curve_at
from mycad.ui.sketch_editor import SketchEditorDialog


def test_trim_both_ends_keeps_remaining_line_connected() -> None:
    line = LineEntity(uuid4().hex, (-20.0, 0.0), (40.0, 0.0))
    cutters = tuple(LineEntity(uuid4().hex, (x, -10.0), (x, 10.0)) for x in (0.0, 20.0))
    first = trim_curve_at((line, *cutters), (-10.0, 0.0), hit_tolerance_mm=0.2)
    assert len(first) == 3
    second = trim_curve_at(first, (30.0, 0.0), hit_tolerance_mm=0.2)
    assert second == (LineEntity(line.entity_id, (0.0, 0.0), (20.0, 0.0)), *cutters)


@pytest.mark.parametrize("operation", ["move", "copy"])
def test_pointer_transform_preview_cancel_confirm_undo(qtbot: QtBot, operation: str) -> None:
    draft = SketchEditorDialog()
    qtbot.addWidget(draft)
    draft.resize(1400, 900)
    draft.show()
    qtbot.waitExposed(draft)
    canvas = draft.canvas
    canvas.set_snapping_enabled(False)
    line = LineEntity(uuid4().hex, (-20.0, 0.0), (20.0, 0.0))
    canvas.replace_draft_entities((line,))
    canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {line.entity_id}
    canvas.changed.emit()
    draft.transform_buttons[operation].click()
    assert tuple(canvas.entities) == (line,)
    assert canvas.has_active_edit_gesture
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    position = QPointF(canvas.local_to_screen((20.0, 20.0)))
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
    assert tuple(canvas.entities) == (line,)
    qtbot.waitUntil(lambda: bool(canvas.transform_preview_entities), timeout=1000)
    assert canvas.transform_preview_entities
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert tuple(canvas.entities) == (line,)
    assert not canvas.has_active_edit_gesture
    draft.transform_buttons[operation].click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20.0, 20.0)))
    assert len(canvas.entities) == (2 if operation == "copy" else 1)
    moved = canvas.entities[-1]
    assert isinstance(moved, LineEntity)
    assert moved.start_mm == pytest.approx((0.0, 20.0))
    assert moved.end_mm == pytest.approx((40.0, 20.0))
    assert (moved.entity_id != line.entity_id) == (operation == "copy")
    assert canvas.undo_last_operation()
    assert tuple(canvas.entities) == (line,)
    assert canvas.redo_last_operation()
    assert canvas.entities[-1] == moved


def test_command_first_selection_and_zero_delta_do_not_duplicate(qtbot: QtBot) -> None:
    draft = SketchEditorDialog()
    qtbot.addWidget(draft)
    draft.show()
    canvas = draft.canvas
    line = LineEntity(uuid4().hex, (-20.0, 0.0), (20.0, 0.0))
    canvas.replace_draft_entities((line,))
    draft.transform_buttons["copy"].click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5.0, 0.0)))
    assert canvas.selected_entity_ids == {line.entity_id}
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    assert tuple(canvas.entities) == (line,)
    assert canvas.has_active_edit_gesture
    canvas.add_coordinate_point((30.0, 20.0), exact_point=True)
    assert len(canvas.entities) == 2
    assert not canvas.has_active_edit_gesture


@pytest.mark.parametrize("confirmation", ["enter", "space", "right_click"])
def test_move_uses_first_point_as_displacement(qtbot: QtBot, confirmation: str) -> None:
    draft = SketchEditorDialog()
    qtbot.addWidget(draft)
    draft.show()
    canvas = draft.canvas
    line = LineEntity(uuid4().hex, (10.0, 20.0), (20.0, 20.0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((2.0, 3.0), exact_point=True)
    if confirmation == "enter":
        QTest.keyClick(canvas, Qt.Key.Key_Return)
    elif confirmation == "space":
        QTest.keyClick(canvas, Qt.Key.Key_Space)
    else:
        QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
    assert canvas.entities == [LineEntity(line.entity_id, (12.0, 23.0), (22.0, 23.0))]
    assert not canvas.has_active_edit_gesture
    assert canvas.undo_last_operation()
    assert canvas.entities == [line]


def test_move_command_first_space_finishes_selection(qtbot: QtBot) -> None:
    draft = SketchEditorDialog()
    qtbot.addWidget(draft)
    draft.show()
    canvas = draft.canvas
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    canvas.replace_draft_entities((line,))
    canvas.begin_transform("move")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5.0, 0.0)))
    QTest.keyClick(canvas, Qt.Key.Key_Space)
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((2.0, 3.0), exact_point=True)
    assert canvas.entities == [LineEntity(line.entity_id, (2.0, 3.0), (12.0, 3.0))]


def test_move_pointer_obeys_ortho_but_typed_coordinates_do_not(qtbot: QtBot) -> None:
    draft = SketchEditorDialog()
    qtbot.addWidget(draft)
    draft.resize(1200, 800)
    draft.show()
    canvas = draft.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_orthogonal_enabled(True)
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    target = canvas.local_to_screen((20.0, 5.0))
    position = QPointF(target)
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
    preview = canvas.transform_preview_entities[0]
    assert isinstance(preview, LineEntity)
    assert preview.start_mm[1] == 0.0
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=target)
    moved = canvas.entities[0]
    assert isinstance(moved, LineEntity)
    assert moved.start_mm[0] == pytest.approx(canvas.screen_to_local(QPointF(target))[0])
    assert moved.start_mm[1] == 0.0
    assert canvas.undo_last_operation()
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((20.0, 5.0), exact_point=True)
    assert canvas.entities[0] == LineEntity(line.entity_id, (20.0, 5.0), (30.0, 5.0))


def test_move_object_snap_takes_precedence_over_ortho(qtbot: QtBot) -> None:
    draft = SketchEditorDialog()
    qtbot.addWidget(draft)
    draft.resize(1200, 800)
    draft.show()
    canvas = draft.canvas
    canvas.set_orthogonal_enabled(True)
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    target = LineEntity(uuid4().hex, (30.0, 20.0), (40.0, 20.0))
    canvas.replace_draft_entities((line, target))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((30.0, 20.0)))
    assert canvas.entities == [LineEntity(line.entity_id, (30.0, 20.0), (40.0, 20.0)), target]


def test_spline_control_point_drawing_finishes_and_undoes(qtbot: QtBot) -> None:
    from mycad.core.sketch import SplineEntity

    draft = SketchEditorDialog()
    qtbot.addWidget(draft)
    draft.show()
    draft.tool_buttons["样条曲线"].click()
    canvas = draft.canvas
    points = ((0.0, 0.0), (0.0, 20.0), (30.0, 20.0), (30.0, 0.0))
    for point in points[:3]:
        canvas.add_coordinate_point(point, exact_point=True)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert not canvas.entities
    assert canvas.has_pending_geometry
    canvas.add_coordinate_point(points[3], exact_point=True)
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
    assert len(canvas.entities) == 1
    curve = canvas.entities[0]
    assert isinstance(curve, SplineEntity)
    assert curve.control_points_mm == points
    assert not canvas.has_pending_geometry
    assert not canvas.grab().isNull()
    canvas.set_tool("选择元素")
    QTest.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(curve.point_at(0.5))
    )
    assert canvas.selected_entity_ids == {curve.entity_id}
    assert canvas.undo_last_operation()
    assert not canvas.entities
    assert canvas.redo_last_operation()
    assert canvas.entities == [curve]
