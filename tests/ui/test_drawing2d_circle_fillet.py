# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent drawing circle fillet interaction."""

import math
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.exceptions import TimeoutError as QtTimeoutError
from pytestqt.qtbot import QtBot

from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity
from mycad.ui.sketch_editor import SketchCanvas, SketchEditorDialog


def test_fillet_tool_button_starts_the_same_canvas_command(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    QTest.mouseClick(editor.tool_buttons["二维圆角"], Qt.MouseButton.LeftButton)
    assert editor.canvas.tool == "二维圆角"
    assert "不修剪" in editor.canvas.message
    assert "多段线" in editor.tool_buttons["二维圆角"].toolTip()
    assert "对象相切" in editor.tool_buttons["二维圆角"].toolTip()
    assert "跨草图" not in editor.tool_buttons["二维圆角"].toolTip()


def test_pending_segment_tangency_survives_opposite_frame_without_background_projection(
    qtbot: QtBot,
) -> None:
    from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.sketch_editor import MixedMoveState

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    frame = WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1))
    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -8)), bulges=(-0.5, 0))
    saved = Sketch(uuid4().hex, frame, (curved,))
    line = LineEntity(uuid4().hex, (-5, -2.5), (15, -2.5))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    canvas = editor.canvas
    canvas.entities = [line]
    canvas.background_entities = ()
    canvas.mixed_move = MixedMoveState(uuid4().hex, 1, draft, (saved,), (saved,), (), ())
    pair = (SketchGeometryReference(curved.entity_id, "segment", 0), line.entity_id)
    canvas.pending_cross_tangencies = [pair]
    extra = CircleEntity(uuid4().hex, (30, 30), 2)
    assert canvas.replace_draft_entities((line, extra))
    assert canvas.pending_cross_tangencies == [pair]
    editor.snap_check.setChecked(False)
    assert canvas.set_tool("选择元素")
    qtbot.waitExposed(editor)
    start = canvas.local_to_screen((15, -2.5))
    end = canvas.local_to_screen((17, -2.5))
    assert canvas.control_point_at((15, -2.5)) is not None
    QTest.mouseMove(canvas, start)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    assert "正在拖动" in canvas.message
    end_local = canvas.screen_to_local(QPointF(end))
    next_local = canvas.screen_to_local(QPointF(end) + QPointF(1, 1))
    precise_end = QPointF(
        end.x() + (17.0 - end_local[0]) / (next_local[0] - end_local[0]),
        end.y() + (-2.5 - end_local[1]) / (next_local[1] - end_local[1]),
    )
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            precise_end,
            QPointF(canvas.mapToGlobal(end)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert canvas.entities[0] != line, canvas.message
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.entities[0] != line
    assert canvas.pending_cross_tangencies == [pair]


def test_draft_handle_drag_preserves_pending_cross_sketch_tangency(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    editor.set_context_sketches((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)),))
    assert editor.canvas.replace_draft_entities((circle,))
    editor.canvas.pending_cross_tangencies = [(line.entity_id, circle.entity_id)]
    assert editor.canvas.set_tool("选择元素")
    QTest.mousePress(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 2))
    )
    QTest.mouseMove(editor.canvas, editor.canvas.local_to_screen((0, 3)))
    QTest.mouseRelease(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 3))
    )
    assert editor.canvas.entities == [circle]
    assert editor.canvas.pending_cross_tangencies == [(line.entity_id, circle.entity_id)]


def test_unrelated_draft_handle_still_moves_with_pending_tangency(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity, RectangleEntity, Sketch, WorkPlaneFrame

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    rectangle = RectangleEntity(uuid4().hex, (20, 20), (30, 30))
    editor.set_context_sketches((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)),))
    assert editor.canvas.replace_draft_entities((circle, rectangle))
    editor.canvas.pending_cross_tangencies = [(line.entity_id, circle.entity_id)]
    editor.canvas.mixed_handle_drag_enabled = True
    editor.snap_check.setChecked(False)
    assert editor.canvas.set_tool("选择元素")
    QTest.mousePress(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((20, 20))
    )
    QTest.mouseMove(editor.canvas, editor.canvas.local_to_screen((21, 21)))
    QTest.mouseRelease(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((21, 21))
    )
    assert editor.canvas.entities[0] == circle
    assert editor.canvas.entities[1] != rectangle
    assert editor.canvas.pending_cross_tangencies == [(line.entity_id, circle.entity_id)]


def test_fillet_toolbar_activation_updates_repeat_command(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    command.setText("CIRCLE")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(editor.tool_buttons["二维圆角"], Qt.MouseButton.LeftButton)
    assert editor.canvas.tool == "二维圆角"
    command.clear()
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.tool == "选择元素"
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.tool == "二维圆角"


def test_fillet_radius_continues_with_document_but_not_another_editor(qtbot: QtBot) -> None:
    previous = SketchEditorDialog(select_committed_entities=True)
    continued = SketchEditorDialog(select_committed_entities=True)
    unrelated = SketchEditorDialog(select_committed_entities=True)
    for editor in (previous, continued, unrelated):
        qtbot.addWidget(editor)
        editor.show()
    command = previous.drawing_command_bar.input
    for text in ("FILLET", "R", "4"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    continued.continue_workspace_from(previous)
    QTest.keyClick(continued.drawing_command_bar.input, Qt.Key.Key_Return)
    assert continued.canvas.tool == "二维圆角"
    assert continued.canvas.circle_fillet_radius == 4
    assert unrelated.canvas.circle_fillet_radius == 1


def test_filletrad_command_shares_fillet_radius_and_rejects_invalid_values(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for value in ("FILLET", "R", "4", "", "FILLETRAD"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "4" in bar.status.text()
    for value in ("-1", "nan", "inf", "FILLET"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
        assert "FILLETRAD" in bar.status.text()
        assert editor.canvas.circle_fillet_radius == 4
    bar.input.setText("0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.circle_fillet_radius == 0
    for value in ("FILLETRAD", ""):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.circle_fillet_radius == 0
    bar.input.setText("FILLET")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.tool == "二维圆角" and editor.canvas.circle_fillet_radius == 0


def test_filletrad_escape_clears_prompt_without_changing_radius(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    bar.input.setText("FILLETRAD")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    bar.input.setText("FILLET")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.tool == "二维圆角" and editor.canvas.circle_fillet_radius == 1


def test_filletrad_zero_produces_sharp_corner(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (2, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 2), (0, 20))
    assert canvas.replace_draft_entities((first, second))
    bar = editor.drawing_command_bar
    for value in ("FILLETRAD", "0", "FILLET"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    for point in ((10, 0), (0, 10)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 2 and all(
        isinstance(item, LineEntity) for item in canvas.entities
    )
    assert canvas.entities != [first, second]
    assert canvas.undo_last_operation() and canvas.entities == [first, second]


def test_fillet_radius_prompt_enter_accepts_current_value(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "R", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not canvas.circle_fillet_radius_pending
    assert canvas.circle_fillet_radius == 2
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 3
    assert isinstance(canvas.entities[-1], ArcEntity)
    assert canvas.entities[-1].radius_mm == pytest.approx(2)


def _test_curve_point(curve: LineEntity | ArcEntity, ratio: float) -> tuple[float, float]:
    if isinstance(curve, LineEntity):
        return (
            curve.start_mm[0] + ratio * (curve.end_mm[0] - curve.start_mm[0]),
            curve.start_mm[1] + ratio * (curve.end_mm[1] - curve.start_mm[1]),
        )
    angle = math.radians(curve.start_angle_deg + ratio * curve.sweep_angle_deg)
    return (
        curve.center_mm[0] + curve.radius_mm * math.cos(angle),
        curve.center_mm[1] + curve.radius_mm * math.sin(angle),
    )


def _zoom_for_short_segment(canvas: SketchCanvas) -> None:
    position = QPointF(canvas.width() / 2, canvas.height() / 2)
    global_position = QPointF(canvas.mapToGlobal(position.toPoint()))
    for _ in range(13):
        canvas.wheelEvent(
            QWheelEvent(
                position,
                global_position,
                QPoint(),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )
        )


@pytest.mark.parametrize("mouse", [False, True])
def test_fillet_radius_can_be_measured_with_two_points(qtbot: QtBot, mouse: bool) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    editor.snap_check.setChecked(False)
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 20))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    if mouse:
        for point in ((20, 20), (23, 24)):
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    else:
        for value in ("20,20", "@3,4"):
            command.setText(value)
            QTest.keyClick(command, Qt.Key.Key_Return)
    assert not canvas.circle_fillet_radius_pending
    assert canvas.circle_fillet_radius == pytest.approx(5, abs=0.2 if mouse else 1e-9)
    for point in ((15, 0), (0, 15)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert isinstance(canvas.entities[-1], ArcEntity)
    assert canvas.entities[-1].radius_mm == pytest.approx(5, abs=0.2 if mouse else 1e-9)
    assert canvas.undo_last_operation() and canvas.entities == [first, second]


def test_fillet_radius_measure_cancel_retains_previous_radius(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "3", "R", "5,5"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.circle_fillet_radius_pending
    QTest.keyClick(command, Qt.Key.Key_Escape)
    assert editor.canvas.circle_fillet_radius == 3
    assert not editor.canvas.circle_fillet_radius_pending
    for value in ("FILLET", "R", "0,0", "3,4"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.circle_fillet_radius == pytest.approx(5)


def test_fillet_zero_distance_and_enter_during_measurement(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "4", "R", "3,3", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.circle_fillet_radius_pending
    assert editor.canvas.circle_fillet_radius == 4
    command.setText("@0,0")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert not editor.canvas.circle_fillet_radius_pending
    assert editor.canvas.circle_fillet_radius == 0


@pytest.mark.parametrize("radius_input", [("5",), ("20,20", "@3,4")])
def test_fillet_measure_radius_after_first_object_retains_selection(
    qtbot: QtBot, radius_input: tuple[str, ...]
) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 20))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    command.setText("FILLET")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, 0)))
    assert canvas.has_active_edit_gesture
    for value in ("R", *radius_input):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.has_active_edit_gesture
    assert "第二" in canvas.message
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 15)))
    assert isinstance(canvas.entities[-1], ArcEntity)
    assert canvas.entities[-1].radius_mm == pytest.approx(5)


def test_fillet_radius_measure_uses_object_snaps(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((0.3, 0.3), (10.3, 0.3)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.circle_fillet_radius == pytest.approx(10)
    assert not canvas.circle_fillet_radius_pending
    assert canvas.entities == [line]


def test_fillet_radius_measurement_reset_on_tool_change_and_numeric_input(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "3", "R", "10,10"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.circle_fillet_radius_measuring
    assert canvas.set_tool("直线")
    assert not canvas.circle_fillet_radius_measuring
    assert canvas.circle_fillet_radius == 3
    for value in ("FILLET", "R", "0,0", "4"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not canvas.circle_fillet_radius_measuring
    assert not canvas.circle_fillet_radius_pending
    assert canvas.circle_fillet_radius == 4


def test_fillet_radius_measurement_keeps_first_source_revision_guard(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 20))
    assert canvas.replace_draft_entities((first, second))
    revision = [1]
    canvas.source_revision_provider = lambda: revision[0]
    command = editor.drawing_command_bar.input
    command.setText("FILLET")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, 0)))
    revision[0] = 2
    for value in ("R", "20,20", "@3,4"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 15)))
    assert canvas.entities == [first, second]
    assert "文档已变化" in canvas.message


@pytest.mark.parametrize("value", ["R", "T", "P", "M", "U", "TRIMMODE", "FILLETRAD"])
def test_fillet_radius_prompt_does_not_execute_other_options(qtbot: QtBot, value: str) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    for text in ("FILLET", "R", "5,5", value):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.circle_fillet_radius_pending
    assert canvas.circle_fillet_radius_measuring
    assert not canvas.circle_fillet_trim_pending
    assert not canvas.circle_fillet_multiple
    assert not canvas.circle_fillet_polyline_pending
    assert canvas.entities == [line]
    command.setText("@3,4")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.circle_fillet_radius == pytest.approx(5)


@pytest.mark.parametrize("trim", [False, True])
def test_fillet_trim_prompt_enter_accepts_current_mode(qtbot: QtBot, trim: bool) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    values = ["FILLET", "R", "2"] + ([] if trim else ["T", "N"]) + ["T", ""]
    for value in values:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not canvas.circle_fillet_trim_pending
    assert canvas.circle_fillet_trim is trim
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 3
    assert (canvas.entities[:2] == [first, second]) is not trim


@pytest.mark.parametrize("same_layer", [False, True])
@pytest.mark.parametrize("trim", [False, True])
def test_fillet_uses_sources_layer_when_they_match(
    qtbot: QtBot, same_layer: bool, trim: bool
) -> None:
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_layers import SketchLayer

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    layers = editor.layer_table.add(SketchLayer("source-a")).add(SketchLayer("source-b"))
    editor.layer_table = layers
    canvas.set_layer_table(layers, "0")
    first = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="source-a")
    second = LineEntity(
        uuid4().hex, (0, 0), (0, 10), layer_name="source-a" if same_layer else "source-b"
    )
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ["FILLET", "R", "2"] + ([] if trim else ["T", "N"]):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert isinstance(canvas.entities[-1], ArcEntity)
    assert canvas.entities[-1].layer_name == ("source-a" if same_layer else "0")


@pytest.mark.parametrize("source_locked", [False, True])
@pytest.mark.parametrize("trim", [False, True])
def test_fillet_uses_and_checks_actual_destination_layer(
    qtbot: QtBot, source_locked: bool, trim: bool
) -> None:
    from dataclasses import replace

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_layers import SketchLayer

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    layers = editor.layer_table.add(SketchLayer("source-a", locked=source_locked))
    if not source_locked:
        layers = layers.replace(replace(layers.get("0"), locked=True))
    editor.layer_table = layers
    canvas.set_layer_table(layers, "0")
    first = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="source-a")
    second = LineEntity(uuid4().hex, (0, 0), (0, 10), layer_name="source-a")
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ["FILLET", "R", "2"] + ([] if trim else ["T", "N"]):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if source_locked:
        assert canvas.entities == [first, second]
        assert "锁定" in canvas.message
    else:
        assert isinstance(canvas.entities[-1], ArcEntity)
        assert canvas.entities[-1].layer_name == "source-a"


@pytest.mark.parametrize("pair", ["circles", "line_circle"])
@pytest.mark.parametrize("trim", [False, True])
def test_fillet_circle_combinations_use_matching_layer(qtbot: QtBot, pair: str, trim: bool) -> None:
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_layers import SketchLayer

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    layers = editor.layer_table.add(SketchLayer("source-a"))
    editor.layer_table = layers
    canvas.set_layer_table(layers, "0")
    if pair == "circles":
        sources = (
            CircleEntity(uuid4().hex, (0, 0), 2, layer_name="source-a"),
            CircleEntity(uuid4().hex, (10, 0), 2, layer_name="source-a"),
        )
        picks = ((1.7, 1.1), (8.3, 1.1))
        radius = "4"
    else:
        sources = (
            LineEntity(uuid4().hex, (-20, 0), (20, 0), layer_name="source-a"),
            CircleEntity(uuid4().hex, (0, 5), 2, layer_name="source-a"),
        )
        picks = ((-3, 0), (-1.3, 3.5))
        radius = "2"
    assert canvas.replace_draft_entities(sources)
    command = editor.drawing_command_bar.input
    for value in ["FILLET", "R", radius] + ([] if trim else ["T", "N"]):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 3, canvas.message
    assert isinstance(canvas.entities[-1], ArcEntity)
    assert canvas.entities[-1].layer_name == "source-a"


def test_polyline_fillet_no_trim_uses_source_layer(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_layers import SketchLayer

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    layers = editor.layer_table.add(SketchLayer("source-a"))
    editor.layer_table = layers
    canvas.set_layer_table(layers, "0")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), layer_name="source-a")
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert len(canvas.entities) == 2, canvas.message
    assert isinstance(canvas.entities[-1], ArcEntity)
    assert canvas.entities[-1].layer_name == "source-a"


def test_fillet_rejects_locked_current_layer_for_different_sources(qtbot: QtBot) -> None:
    from dataclasses import replace

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_layers import SketchLayer

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    layers = editor.layer_table.add(SketchLayer("a")).add(SketchLayer("b"))
    layers = layers.replace(replace(layers.get("0"), locked=True))
    editor.layer_table = layers
    canvas.set_layer_table(layers, "0")
    first = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="a")
    second = LineEntity(uuid4().hex, (0, 0), (0, 10), layer_name="b")
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities == [first, second]
    assert "锁定" in canvas.message


def test_saved_fillet_source_layer_survives_save_and_reopen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    layers = editor.layer_table.add(SketchLayer("source-a"))
    editor.layer_table = layers
    editor.canvas.set_layer_table(layers, "0")
    first = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="source-a")
    second = LineEntity(uuid4().hex, (0, 0), (0, 10), layer_name="source-a")
    assert editor.canvas.replace_draft_entities((first, second))
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    arcs = [entity for entity in canvas.entities if isinstance(entity, ArcEntity)]
    assert len(arcs) == 1 and arcs[0].layer_name == "source-a"
    target = tmp_path / "fillet-layer.mc.json"

    def choose(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(target), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: target.exists() and not unit.is_busy, timeout=10000)
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not previous and not unit.is_busy)
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    saved_arcs = [
        entity
        for entity, _layer in reopened.canvas.background_entities
        if isinstance(entity, ArcEntity)
    ]
    assert len(saved_arcs) == 1 and saved_arcs[0].layer_name == "source-a"


def test_circle_fillet_command_creates_one_arc_without_trimming(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    canvas.entities = [first, second]
    command = editor.drawing_command_bar.input
    for text in ("FILLET", "R", "4"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1.7, 1.1)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8.3, 1.1)))
    assert canvas.entities[:2] == [first, second]
    assert len(canvas.entities) == 3
    arc = canvas.entities[2]
    assert isinstance(arc, ArcEntity)
    assert arc.radius_mm == pytest.approx(4)
    assert arc.center_mm[1] > 0
    assert canvas.undo_last_operation()
    assert canvas.entities == [first, second]


def test_saved_circles_fillet_creates_cross_sketch_tangencies(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert editor.canvas.replace_draft_entities(circles)
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "4"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.pending_cross_tangencies) == 2
    assert canvas.undo_last_operation() and not canvas.pending_cross_tangencies
    assert canvas.redo_last_operation() and len(canvas.pending_cross_tangencies) == 2
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    assert len(services.kernel.cross_sketch_tangencies) == 2
    loaded = window.loaded_document()
    assert loaded is not None
    loaded.bus.undo()
    assert len(services.kernel.sketches) == 1 and not services.kernel.cross_sketch_tangencies
    loaded.bus.redo()
    assert len(services.kernel.cross_sketch_tangencies) == 2


@pytest.mark.parametrize("mixed", (False, True))
def test_delete_saved_fillet_removes_cross_tangencies_atomically(
    qtbot: QtBot, tmp_path: Path, mixed: bool
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    assert editor.canvas.replace_draft_entities(circles)
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "4"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    arc = canvas.entities[0]
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    before = services.kernel.sketches
    selected = (arc.entity_id,)
    if mixed:
        draft_line = LineEntity(uuid4().hex, (20, 0), (30, 0))
        assert editor.canvas.replace_draft_entities((draft_line,))
        selected += (draft_line.entity_id,)
    editor.canvas.committed_delete_requested.emit(selected)
    qtbot.waitUntil(lambda: not unit.is_busy)
    if mixed:
        assert editor.canvas.mixed_move is not None, editor.status_label.text()
        editor.finish_button.click()
        qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    assert not services.kernel.cross_sketch_tangencies, editor.status_label.text()
    assert all(arc not in sketch.entities for sketch in services.kernel.sketches)
    loaded.bus.undo()
    assert all(sketch in services.kernel.sketches for sketch in before)
    assert len(services.kernel.cross_sketch_tangencies) == 2
    loaded.bus.redo()
    assert not services.kernel.cross_sketch_tangencies
    path = tmp_path / "delete-cross.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=[])
    reopened = app.open_app_document(reopened_services, path)
    assert not reopened_services.kernel.cross_sketch_tangencies
    reopened.bus.undo()
    assert len(reopened_services.kernel.cross_sketch_tangencies) == 2


@pytest.mark.parametrize("mode", ("move", "rotate", "mirror", "scale"))
def test_move_saved_entity_solves_cross_sketch_tangency(qtbot: QtBot, mode: str) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    unit = window.execution_unit
    assert unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    for entity in (line, circle):
        editor = window.active_sketch_dialog()
        assert editor is not None
        assert editor.canvas.replace_draft_entities((entity,))
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda previous=editor: (
                window.active_sketch_dialog() is not previous and not unit.is_busy
            )
        )
    loaded = window.loaded_document()
    editor = window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    first, second = services.kernel.sketches
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.canvas.source_revision_invalidated.emit()
    before = services.kernel.sketches
    if mode == "rotate":
        editor.canvas.committed_rotation_requested.emit((line.entity_id,), (0.0, 0.0), 90.0)
    elif mode == "scale":
        editor.canvas.committed_scale_requested.emit((line.entity_id,), (0.0, 2.0), 2.0)
    elif mode == "mirror":
        editor.canvas.committed_mirror_requested.emit((line.entity_id,), (0.0, 0.0), (0.0, 1.0))
    else:
        editor.canvas.committed_move_requested.emit((line.entity_id,), (0.0, 1.0))
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert services.kernel.sketches != before, editor.status_label.text()
    moved = next(s for s in services.kernel.sketches if s.sketch_id == first.sketch_id)
    moved_line = moved.entities[0]
    assert isinstance(moved_line, LineEntity)
    expected = {
        "move": ((-10, 1), (10, 1)),
        "rotate": ((0, -10), (0, 10)),
        "mirror": ((10, 0), (-10, 0)),
        "scale": ((-20, -2), (20, -2)),
    }[mode]
    assert moved_line.start_mm == pytest.approx(expected[0])
    assert moved_line.end_mm == pytest.approx(expected[1])
    validate_tangency_component(services.kernel.sketches, (relation,), first.sketch_id)
    loaded.bus.undo()
    assert services.kernel.sketches == before


def test_cross_sketch_dimension_preview_and_commit(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    unit = window.execution_unit
    assert unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    for entity in (line, circle):
        editor = window.active_sketch_dialog()
        assert editor is not None
        assert editor.canvas.replace_draft_entities((entity,))
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda previous=editor: (
                window.active_sketch_dialog() is not previous and not unit.is_busy
            )
        )
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    first, second = services.kernel.sketches
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    source = next(item for item in services.kernel.sketches if item.sketch_id == second.sketch_id)
    before = services.kernel.sketches
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["radius"].click()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 4))
    )
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((8, 8))
    )
    editor.dimensions.value_editor.setValue(3)
    first_dimension = editor.dimensions.candidate
    assert first_dimension is not None and editor.dimensions.original == source
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(source, first_dimension) is not None,
        timeout=15000,
    )
    preview = editor.dimensions.accepted_preview(source, first_dimension)
    assert preview is not None and preview.status == "success", editor.status_label.text()
    assert services.kernel.sketches == before
    assert editor.canvas.dimension_preview is not None
    assert editor.canvas.dimension_linked_previews
    QTest.keyClick(editor.dimensions.value_editor, Qt.Key.Key_Escape)
    assert editor.canvas.dimension_preview is None
    assert not editor.canvas.dimension_linked_previews
    assert services.kernel.sketches == before
    editor.dimensions.buttons["radius"].click()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 4))
    )
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((8, 8))
    )
    editor.dimensions.value_editor.setValue(3)
    dimension = editor.dimensions.candidate
    assert dimension is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(source, dimension) is not None, timeout=15000
    )
    editor.dimensions.apply_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    after = services.kernel.sketches
    validate_tangency_component(after, (relation,), first.sketch_id)
    target = next(item for item in after if item.sketch_id == second.sketch_id)
    assert isinstance(target.entities[0], CircleEntity)
    assert target.entities[0].radius_mm == pytest.approx(3)
    placed_dimension = next(
        item for item in target.constraints if item.constraint_id == dimension.constraint_id
    )
    editor.dimensions.edit(target, placed_dimension)
    editor.dimensions.value_editor.setValue(4)
    revised_dimension = editor.dimensions.candidate
    assert revised_dimension is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(target, revised_dimension) is not None,
        timeout=15000,
    )
    editor.dimensions.apply_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    updated = next(item for item in services.kernel.sketches if item.sketch_id == second.sketch_id)
    assert isinstance(updated.entities[0], CircleEntity)
    assert updated.entities[0].radius_mm == pytest.approx(4), editor.status_label.text()
    loaded.bus.undo()
    assert services.kernel.sketches == after
    loaded.bus.undo()
    assert services.kernel.sketches == before


def test_cross_sketch_dimension_preview_with_multiple_projection_axes(qtbot: QtBot) -> None:
    import math

    from mycad import app
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, editor, unit = (
        window.loaded_document(),
        window.active_sketch_dialog(),
        window.execution_unit,
    )
    assert loaded is not None and editor is not None and unit is not None
    c = math.sqrt(0.5)
    frame = WorkPlaneFrame((0, 0, 0), (c, c, 0), (-c, c, 0), (0, 0, 1))
    lower = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    upper = LineEntity(uuid4().hex, (-6 * c, 14 * c), (14 * c, -6 * c))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    lower_dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(lower.entity_id, "geometry"),),
        20,
        "mm",
        axis="horizontal",
    )
    upper_dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(upper.entity_id, "geometry"),),
        20 * c,
        "mm",
        axis="ordinate_x",
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (lower,), (lower_dim,))
    second = Sketch(uuid4().hex, frame, (upper,), (upper_dim,))
    third = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second, third):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relations = (
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(first.sketch_id, lower.entity_id),
            CrossSketchRef(third.sketch_id, circle.entity_id),
            "line_left",
        ),
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(second.sketch_id, upper.entity_id),
            CrossSketchRef(third.sketch_id, circle.entity_id),
            "line_right",
        ),
    )
    for relation in relations:
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    source = next(
        sketch for sketch in services.kernel.sketches if sketch.sketch_id == third.sketch_id
    )
    before = services.kernel.sketches
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["radius"].click()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((2, 2))
    )
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((8, 8))
    )
    editor.dimensions.value_editor.setValue(3)
    dimension = editor.dimensions.candidate
    assert dimension is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(source, dimension) is not None, timeout=15000
    )
    preview = editor.dimensions.accepted_preview(source, dimension)
    assert preview is not None and preview.status == "success", editor.status_label.text()
    assert services.kernel.sketches == before
    editor.dimensions.apply_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    after = services.kernel.sketches
    validate_tangency_component(after, relations, third.sketch_id)
    updated = next(sketch for sketch in after if sketch.sketch_id == third.sketch_id)
    assert isinstance(updated.entities[0], CircleEntity)
    assert updated.entities[0].radius_mm == pytest.approx(3)
    loaded.bus.undo()
    assert services.kernel.sketches == before


@pytest.mark.parametrize("small_window", (False, True))
def test_drag_saved_cross_sketch_line_handle(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, small_window: bool
) -> None:
    import threading

    from mycad import app
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, Sketch
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    if not small_window:
        window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    unit = window.execution_unit
    assert unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    for entity in (line, circle):
        editor = window.active_sketch_dialog()
        assert editor is not None and editor.canvas.replace_draft_entities((entity,))
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda previous=editor: (
                window.active_sketch_dialog() is not previous and not unit.is_busy
            )
        )
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    first, second = services.kernel.sketches
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before = services.kernel.sketches
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    assert line.entity_id in editor.canvas.selected_entity_ids
    start = editor.canvas.local_to_screen(line.start_mm)
    end = editor.canvas.local_to_screen((-10, 1))
    entered, gate = threading.Event(), threading.Event()
    actual_prepare = app.prepare_cross_sketch_drag

    def delayed_prepare(
        task_services: app.AppServices,
        sketch_id: str,
        reference: SketchGeometryReference,
        target: tuple[float, float],
    ) -> tuple[tuple[Sketch, ...], tuple[Sketch, ...], tuple[CrossSketchRef, ...]]:
        entered.set()
        if not gate.wait(10):
            raise TimeoutError("preview test did not release the worker")
        return actual_prepare(task_services, sketch_id, reference, target)

    monkeypatch.setattr(app, "prepare_cross_sketch_drag", delayed_prepare)
    QTest.mouseMove(editor.canvas, start)
    qtbot.wait(50)
    start = editor.canvas.local_to_screen(line.start_mm)
    end = editor.canvas.local_to_screen((-10, 1))
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    assert editor.canvas.saved_handle_drag_active, (
        start,
        end,
        editor.canvas.tool,
        editor.canvas.selected_entity_ids,
        editor.status_label.text(),
    )
    QTest.mouseMove(editor.canvas, end)
    qtbot.waitUntil(entered.is_set, timeout=10000)
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert not editor.canvas.saved_handle_drag_active, (
        editor.dimensions.mode,
        editor.status_label.text(),
    )
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    gate.set()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert services.kernel.sketches == before and not editor.canvas.saved_handle_preview
    entered.clear()
    gate.clear()
    QTest.mouseMove(editor.canvas, start)
    qtbot.wait(50)
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    assert editor.canvas.saved_handle_drag_active, (
        editor.canvas.tool,
        editor.canvas.selected_entity_ids,
        editor.status_label.text(),
    )
    QTest.mouseMove(editor.canvas, end)
    qtbot.waitUntil(entered.is_set, timeout=10000)
    extra = Sketch(uuid4().hex, first.frame, (LineEntity(uuid4().hex, (30, 30), (35, 30)),))
    loaded.bus.execute("sketch.create", extra.to_mapping(version=3), "local")
    changed = services.kernel.sketches
    gate.set()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert not editor.canvas.saved_handle_drag_active
    assert services.kernel.sketches == changed
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    before = changed
    entered.clear()
    gate.clear()
    QTest.mouseMove(editor.canvas, start)
    qtbot.wait(50)
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    qtbot.waitUntil(entered.is_set, timeout=10000)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert not editor.canvas.saved_handle_drag_active
    gate.set()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert services.kernel.sketches == before
    monkeypatch.setattr(app, "prepare_cross_sketch_drag", actual_prepare)
    QTest.mouseMove(editor.canvas, start)
    qtbot.wait(50)
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    qtbot.waitUntil(lambda: bool(editor.canvas.saved_handle_preview), timeout=15000)
    assert services.kernel.sketches == before
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert not editor.canvas.saved_handle_preview
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert services.kernel.sketches == before
    entered.clear()
    gate.clear()
    monkeypatch.setattr(app, "prepare_cross_sketch_drag", delayed_prepare)
    QTest.mouseMove(editor.canvas, start)
    qtbot.wait(50)
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, editor.canvas.local_to_screen((-10, 2)))
    qtbot.waitUntil(entered.is_set, timeout=10000)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    gate.set()
    qtbot.waitUntil(lambda: services.kernel.sketches != before and not unit.is_busy, timeout=15000)
    monkeypatch.setattr(app, "prepare_cross_sketch_drag", actual_prepare)
    moved = next(
        item for item in services.kernel.sketches if item.sketch_id == first.sketch_id
    ).entities[0]
    assert isinstance(moved, LineEntity)
    assert moved.start_mm == pytest.approx((-10, 1), abs=0.15)
    validate_tangency_component(services.kernel.sketches, (relation,), first.sketch_id)
    after = services.kernel.sketches
    path = tmp_path / "dragged-linked.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == before


@pytest.mark.parametrize("kind", ("circle", "arc"))
def test_drag_saved_cross_sketch_curve_handle(qtbot: QtBot, kind: str) -> None:
    import math

    from mycad import app
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )
    from mycad.core.sketch import ArcEntity, LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    unit = window.execution_unit
    assert unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    curve = (
        CircleEntity(uuid4().hex, (0, 2), 2)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (0, 2), 2, 180, 180)
    )
    for entity in (line, curve):
        editor = window.active_sketch_dialog()
        assert editor is not None and editor.canvas.replace_draft_entities((entity,))
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda previous=editor: (
                window.active_sketch_dialog() is not previous and not unit.is_busy
            )
        )
    loaded, editor = window.loaded_document(), window.active_sketch_dialog()
    assert loaded is not None and editor is not None
    first, second = services.kernel.sketches
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, curve.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before = services.kernel.sketches
    assert editor.canvas.set_tool("选择元素")
    hit = (0, 4) if kind == "circle" else (-2, 2)
    start = (0, 2) if kind == "circle" else (-2, 2)
    target = (0, 3) if kind == "circle" else (-1.5, 2)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(hit)
    )
    assert curve.entity_id in editor.canvas.selected_entity_ids
    QTest.mousePress(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(start)
    )
    QTest.mouseMove(editor.canvas, editor.canvas.local_to_screen(target))
    qtbot.waitUntil(lambda: bool(editor.canvas.saved_handle_preview), timeout=15000)
    QTest.mouseRelease(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(target)
    )
    qtbot.waitUntil(lambda: services.kernel.sketches != before and not unit.is_busy, timeout=15000)
    updated = next(
        item for item in services.kernel.sketches if item.sketch_id == second.sketch_id
    ).entities[0]
    if isinstance(updated, CircleEntity):
        dragged = updated.center_mm
    else:
        assert isinstance(updated, ArcEntity)
        angle = math.radians(updated.start_angle_deg)
        dragged = (
            updated.center_mm[0] + updated.radius_mm * math.cos(angle),
            updated.center_mm[1] + updated.radius_mm * math.sin(angle),
        )
    assert dragged == pytest.approx(target, abs=0.15)
    validate_tangency_component(services.kernel.sketches, (relation,), first.sketch_id)
    after = services.kernel.sketches
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after


def test_drag_saved_unlinked_line_handle(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    before = services.kernel.sketches
    assert canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert line.entity_id in canvas.selected_entity_ids
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(line.start_mm))
    QTest.mouseMove(canvas, canvas.local_to_screen((-10, 1)))
    qtbot.waitUntil(lambda: bool(canvas.saved_handle_preview), timeout=15000)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-10, 1)))
    qtbot.waitUntil(lambda: services.kernel.sketches != before and not unit.is_busy, timeout=15000)
    moved = services.kernel.sketches[0].entities[0]
    assert isinstance(moved, LineEntity) and moved.start_mm == pytest.approx((-10, 1), abs=0.15)
    assert not services.kernel.cross_sketch_tangencies
    loaded.bus.undo()
    assert services.kernel.sketches == before


def test_drag_saved_curved_polyline_vertex_preserves_bulge_and_history(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import PolylineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    polyline = PolylineEntity(uuid4().hex, ((-10, 0), (10, 0), (10, 10)), bulges=(1.0, 0.0))
    assert editor.canvas.replace_draft_entities((polyline,))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    before = services.kernel.sketches
    assert canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 5)))
    assert polyline.entity_id in canvas.selected_entity_ids
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    QTest.mouseMove(canvas, canvas.local_to_screen((12, -3)))
    qtbot.waitUntil(lambda: bool(canvas.saved_handle_preview), timeout=15000)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((12, -3)))
    qtbot.waitUntil(lambda: services.kernel.sketches != before and not unit.is_busy, timeout=15000)
    moved = services.kernel.sketches[0].entities[0]
    assert isinstance(moved, PolylineEntity)
    assert moved.points_mm[1] == pytest.approx((12, -3), abs=0.15)
    assert moved.bulges == polyline.bulges
    after = services.kernel.sketches
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after


def test_mixed_no_trim_fillet_preserves_local_and_cross_sketch_tangency(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    assert editor.canvas.replace_draft_entities((circle,))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (-20, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((-3, 0), (-1.3, 3.5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.pending_cross_tangencies) == 1
    assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 1
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    assert len(services.kernel.cross_sketch_tangencies) == 1
    draft = next(
        sketch
        for sketch in services.kernel.sketches
        if any(e.entity_id == line.entity_id for e in sketch.entities)
    )
    assert len([item for item in draft.constraints if item.kind == "tangent"]) == 1
    loaded = window.loaded_document()
    assert loaded is not None
    loaded.bus.undo()
    assert len(services.kernel.sketches) == 1 and not services.kernel.cross_sketch_tangencies
    loaded.bus.redo()
    assert len(services.kernel.cross_sketch_tangencies) == 1


def test_cross_sketch_segment_tangency_dialog_preview_commit_and_undo(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, validate_tangency_component
    from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -6), (15, -6))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curved,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    window.act_manage_tangencies.trigger()
    dialog = window.active_cross_sketch_tangency_dialog()
    assert dialog is not None
    first_ref = CrossSketchRef(first.sketch_id, curved.entity_id, 0)
    second_ref = CrossSketchRef(second.sketch_id, line.entity_id)
    dialog.first_combo.setCurrentIndex(
        next(
            i
            for i in range(dialog.first_combo.count())
            if dialog.first_combo.itemData(i) == first_ref
        )
    )
    dialog.second_combo.setCurrentIndex(
        next(
            i
            for i in range(dialog.second_combo.count())
            if dialog.second_combo.itemData(i) == second_ref
        )
    )
    dialog.branch_combo.setCurrentIndex(dialog.branch_combo.findData("line_left"))
    dialog.preview_button.click()
    preview_dialog = dialog
    qtbot.waitUntil(
        lambda: preview_dialog.preview_button.isEnabled() and not unit.is_busy, timeout=15000
    )
    assert dialog.commit_button.isEnabled(), dialog.status_label.text()
    assert "求解后" in dialog.status_label.text() and "半径" in dialog.status_label.text()
    assert services.kernel.sketches == before and tuple(loaded.document.commands) == history
    dialog.commit_button.click()
    qtbot.waitUntil(
        lambda: window.active_cross_sketch_tangency_dialog() is None and not unit.is_busy,
        timeout=15000,
    )
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == 1 and relations[0].first.segment_index == 0
    validate_tangency_component(services.kernel.sketches, relations, first.sketch_id)
    window.act_manage_tangencies.trigger()
    dialog = window.active_cross_sketch_tangency_dialog()
    assert dialog is not None
    dialog.existing_combo.setCurrentIndex(dialog.existing_combo.findData(relations[0].relation_id))
    dialog.remove_button.click()
    qtbot.waitUntil(
        lambda: window.active_cross_sketch_tangency_dialog() is None and not unit.is_busy,
        timeout=15000,
    )
    assert not services.kernel.cross_sketch_tangencies
    loaded.bus.undo()
    assert services.kernel.cross_sketch_tangencies == relations
    loaded.bus.undo()
    assert services.kernel.sketches == before and not services.kernel.cross_sketch_tangencies
    window.act_manage_tangencies.trigger()
    dialog = window.active_cross_sketch_tangency_dialog()
    assert dialog is not None
    dialog.first_combo.setCurrentIndex(
        next(
            i
            for i in range(dialog.first_combo.count())
            if dialog.first_combo.itemData(i) == first_ref
        )
    )
    dialog.second_combo.setCurrentIndex(
        next(
            i
            for i in range(dialog.second_combo.count())
            if dialog.second_combo.itemData(i) == second_ref
        )
    )
    dialog.branch_combo.setCurrentIndex(dialog.branch_combo.findData("line_left"))
    dialog.preview_button.click()
    qtbot.waitUntil(lambda: dialog.preview_button.isEnabled() and not unit.is_busy, timeout=15000)
    assert dialog.commit_button.isEnabled(), dialog.status_label.text()
    loaded.bus.undo()
    stale_history = tuple(loaded.document.commands)
    dialog.commit_button.click()
    assert not dialog.commit_button.isEnabled()
    assert "改变" in dialog.status_label.text()
    assert (
        tuple(loaded.document.commands) == stale_history
        and not services.kernel.cross_sketch_tangencies
    )
    dialog.reject()


@pytest.mark.parametrize("curve_in_draft", (False, True))
def test_cross_sketch_segment_tangency_with_draft_stages_and_replays(
    qtbot: QtBot, tmp_path: Path, curve_in_draft: bool
) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, validate_tangency_component
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(0.5, 0))
    line = LineEntity(uuid4().hex, (-5, -3.5), (15, -3.5))
    saved_entity = line if curve_in_draft else curved
    draft_entity = curved if curve_in_draft else line
    assert editor.canvas.replace_draft_entities((saved_entity,))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    saved = services.kernel.sketches[0]
    assert editor.canvas.replace_draft_entities((draft_entity,))
    commands = tuple(loaded.document.commands)
    window.act_manage_tangencies.trigger()
    dialog = window.active_cross_sketch_tangency_dialog()
    assert dialog is not None
    first = CrossSketchRef(saved.sketch_id, saved_entity.entity_id, None if curve_in_draft else 0)
    second = CrossSketchRef(
        editor.draft_sketch_id, draft_entity.entity_id, 0 if curve_in_draft else None
    )
    if curve_in_draft:
        first, second = second, first
    dialog.first_combo.setCurrentIndex(
        next(
            i for i in range(dialog.first_combo.count()) if dialog.first_combo.itemData(i) == first
        )
    )
    dialog.second_combo.setCurrentIndex(
        next(
            i
            for i in range(dialog.second_combo.count())
            if dialog.second_combo.itemData(i) == second
        )
    )
    dialog.branch_combo.setCurrentIndex(dialog.branch_combo.findData("line_left"))
    dialog.preview_button.click()
    qtbot.waitUntil(lambda: dialog.preview_button.isEnabled() and not unit.is_busy, timeout=15000)
    assert dialog.commit_button.isEnabled(), dialog.status_label.text()
    assert editor.canvas.entities == [draft_entity] and tuple(loaded.document.commands) == commands
    if not curve_in_draft:
        assert editor.canvas.replace_draft_entities((replace(line, end_mm=(16, -3.5)),))
        dialog.commit_button.click()
        assert "草稿" in dialog.status_label.text() and not editor.canvas.pending_cross_tangencies
        assert tuple(loaded.document.commands) == commands
        assert editor.canvas.undo_last_operation()
        dialog.preview_button.click()
        qtbot.waitUntil(
            lambda current=dialog: current.preview_button.isEnabled() and not unit.is_busy,
            timeout=15000,
        )
        assert dialog.commit_button.isEnabled(), dialog.status_label.text()
    dialog.commit_button.click()
    qtbot.waitUntil(
        lambda: window.active_cross_sketch_tangency_dialog() is None and not unit.is_busy,
        timeout=15000,
    )
    assert (
        tuple(loaded.document.commands) == commands and not services.kernel.cross_sketch_tangencies
    )
    assert editor.canvas.mixed_move is not None and len(editor.canvas.pending_cross_tangencies) == 1
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [draft_entity] and not editor.canvas.pending_cross_tangencies
    assert editor.canvas.redo_last_operation()
    assert len(editor.canvas.pending_cross_tangencies) == 1
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.set_snapping_enabled(False)
    current = editor.canvas.entities[0]
    assert isinstance(current, LineEntity | PolylineEntity)
    drag_start = current.points_mm[2] if isinstance(current, PolylineEntity) else current.start_mm
    drag_target = (drag_start[0], drag_start[1] + 1.0)
    QTest.mousePress(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(drag_start)
    )
    QTest.mouseMove(editor.canvas, editor.canvas.local_to_screen(drag_target))
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert editor.canvas.saved_handle_preview, editor.canvas.message
    QTest.mouseRelease(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(drag_target)
    )
    qtbot.waitUntil(
        lambda: not unit.is_busy and not editor.canvas.saved_handle_drag_active, timeout=15000
    )
    assert len(editor.canvas.pending_cross_tangencies) == 1
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == 1
    assert relations[0].first.segment_index == (None if curve_in_draft else 0)
    assert relations[0].second.segment_index == (0 if curve_in_draft else None)
    validate_tangency_component(services.kernel.sketches, relations, saved.sketch_id)
    after = services.kernel.sketches
    path = tmp_path / "draft-segment-dialog.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert len(services.kernel.cross_sketch_tangencies) == 1
    reopened.bus.undo()
    assert not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("remove_before_finish", (False, True))
def test_multiple_draft_segment_tangencies_preserve_history(
    qtbot: QtBot, remove_before_finish: bool
) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef
    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    curves = tuple(
        PolylineEntity(uuid4().hex, ((x, 0), (x + 10, 0), (x + 10, 8)), bulges=(1, 0))
        for x in (0, 20)
    )
    assert editor.canvas.replace_draft_entities(curves)
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    saved = services.kernel.sketches[0]
    line = LineEntity(uuid4().hex, (-5, -5), (35, -5))
    assert editor.canvas.replace_draft_entities((line,))
    commands = tuple(loaded.document.commands)
    for curve in curves:
        window.act_manage_tangencies.trigger()
        dialog = window.active_cross_sketch_tangency_dialog()
        assert dialog is not None
        source, target = (
            CrossSketchRef(saved.sketch_id, curve.entity_id, 0),
            CrossSketchRef(editor.draft_sketch_id, line.entity_id),
        )
        dialog.first_combo.setCurrentIndex(
            next(
                i
                for i in range(dialog.first_combo.count())
                if dialog.first_combo.itemData(i) == source
            )
        )
        dialog.second_combo.setCurrentIndex(
            next(
                i
                for i in range(dialog.second_combo.count())
                if dialog.second_combo.itemData(i) == target
            )
        )
        dialog.branch_combo.setCurrentIndex(dialog.branch_combo.findData("line_left"))
        dialog.preview_button.click()
        qtbot.waitUntil(
            lambda current=dialog: current.preview_button.isEnabled() and not unit.is_busy,
            timeout=15000,
        )
        assert dialog.commit_button.isEnabled(), dialog.status_label.text()
        dialog.commit_button.click()
        qtbot.waitUntil(
            lambda: window.active_cross_sketch_tangency_dialog() is None and not unit.is_busy,
            timeout=15000,
        )
    assert (
        len(editor.canvas.pending_cross_tangencies) == 2
        and tuple(loaded.document.commands) == commands
    )
    assert editor.canvas.undo_last_operation() and len(editor.canvas.pending_cross_tangencies) == 1
    assert editor.canvas.redo_last_operation() and len(editor.canvas.pending_cross_tangencies) == 2
    window.act_manage_tangencies.trigger()
    dialog = window.active_cross_sketch_tangency_dialog()
    assert dialog is not None
    first_relation = next(
        item
        for item in dialog.relations_by_id.values()
        if item.first.entity_id == curves[0].entity_id
    )
    dialog.existing_combo.setCurrentIndex(
        dialog.existing_combo.findData(first_relation.relation_id)
    )
    dialog.remove_button.click()
    assert window.active_cross_sketch_tangency_dialog() is None
    assert len(editor.canvas.pending_cross_tangencies) == 1
    assert editor.canvas.undo_last_operation() and len(editor.canvas.pending_cross_tangencies) == 2
    assert editor.canvas.redo_last_operation() and len(editor.canvas.pending_cross_tangencies) == 1
    if not remove_before_finish:
        assert (
            editor.canvas.undo_last_operation() and len(editor.canvas.pending_cross_tangencies) == 2
        )
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    assert len(services.kernel.cross_sketch_tangencies) == (1 if remove_before_finish else 2)
    if remove_before_finish:
        loaded.bus.undo()
        assert len(services.kernel.cross_sketch_tangencies) == 2
    loaded.bus.undo()
    assert len(services.kernel.cross_sketch_tangencies) == 1
    loaded.bus.undo()
    assert not services.kernel.cross_sketch_tangencies
    loaded.bus.redo()
    loaded.bus.redo()
    if remove_before_finish:
        loaded.bus.redo()
    assert len(services.kernel.cross_sketch_tangencies) == (1 if remove_before_finish else 2)


def test_cross_sketch_tangency_dialog_closes_when_document_changes(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    for y in (0, 5):
        sketch = Sketch(
            uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, y), (10, y)),)
        )
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    window.act_manage_tangencies.trigger()
    assert window.active_cross_sketch_tangency_dialog() is not None
    window.act_new_drawing.trigger()
    assert window.active_cross_sketch_tangency_dialog() is None
    assert window.loaded_document() is not loaded


def test_saved_constrained_curved_vertex_drag_with_cross_tangency(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    loaded = window.loaded_document()
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    curved = PolylineEntity(uuid4().hex, ((-20, 0), (-10, 0), (-10, 10)), bulges=(1, 0))
    joined = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(curved.entity_id, "vertex", 1),
            SketchGeometryReference(line.entity_id, "start"),
        ),
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, curved), (joined,))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-10, 5)))
    assert curved.entity_id in canvas.selected_entity_ids
    before = services.kernel.sketches
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-10, 0)))
    QTest.mouseMove(canvas, canvas.local_to_screen((-9, 1)))
    qtbot.waitUntil(lambda: bool(canvas.saved_handle_preview), timeout=15000)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-9, 1)))
    qtbot.waitUntil(lambda: services.kernel.sketches != before and not unit.is_busy, timeout=15000)
    updated = next(item for item in services.kernel.sketches if item.sketch_id == first.sketch_id)
    moved_line, moved_curve = updated.entities
    assert isinstance(moved_line, LineEntity) and isinstance(moved_curve, PolylineEntity)
    assert moved_curve.points_mm[1] == pytest.approx((-9, 1), abs=0.15)
    assert moved_line.start_mm == pytest.approx(moved_curve.points_mm[1])
    assert moved_curve.bulges == curved.bulges
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.undo()
    assert services.kernel.sketches == before


def test_saved_curved_vertex_drag_with_pending_draft_tangency(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    curved = PolylineEntity(uuid4().hex, ((20, 0), (30, 0), (30, 10)), bulges=(1, 0))
    assert editor.canvas.replace_draft_entities((line, curved))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    assert canvas.replace_draft_entities((circle,))
    from mycad.core.cross_sketch_tangency import DraftTangentPair

    pairs: list[DraftTangentPair] = [(line.entity_id, circle.entity_id)]
    canvas.pending_cross_tangencies = pairs.copy()
    editor.snap_check.setChecked(False)
    assert canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((30, 5)))
    assert curved.entity_id in canvas.selected_entity_ids
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((30, 0)))
    QTest.mouseMove(canvas, canvas.local_to_screen((32, -3)))
    qtbot.waitUntil(lambda: bool(canvas.saved_handle_preview), timeout=15000)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((32, -3)))
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert canvas.mixed_move is not None, editor.status_label.text()
    moved = next(
        entity for entity, _ in canvas.background_entities if entity.entity_id == curved.entity_id
    )
    assert isinstance(moved, PolylineEntity)
    assert moved.points_mm[1] == pytest.approx((32, -3), abs=0.15)
    assert moved.bulges == curved.bulges
    assert canvas.entities == [circle] and canvas.pending_cross_tangencies == pairs
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    assert len(services.kernel.cross_sketch_tangencies) == 1
    assert any(moved in sketch.entities for sketch in services.kernel.sketches)


@pytest.mark.parametrize("linked_count", (1, 2))
def test_drag_draft_handle_solves_and_saves_pending_tangency(
    qtbot: QtBot, tmp_path: Path, linked_count: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from mycad import app
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, Sketch
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    upper = LineEntity(uuid4().hex, (-10, 4), (10, 4))
    sources = (line,) if linked_count == 1 else (line, upper)
    assert editor.canvas.replace_draft_entities(sources)
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    assert canvas.replace_draft_entities((circle,))
    pairs = [(source.entity_id, circle.entity_id) for source in sources]
    canvas.pending_cross_tangencies = list(pairs)
    editor.snap_check.setChecked(False)
    assert canvas.set_tool("选择元素")
    if linked_count == 1:
        entered, gate = threading.Event(), threading.Event()
        actual_prepare = app.prepare_mixed_handle_drag

        def delayed_prepare(
            task_services: app.AppServices,
            saved: tuple[Sketch, ...],
            draft: Sketch,
            pending: tuple[tuple[str, str], ...],
            relations: tuple[CrossSketchTangency, ...],
            target: CrossSketchRef,
            reference: SketchGeometryReference,
            target_mm: tuple[float, float],
        ) -> tuple[tuple[Sketch, ...], Sketch, tuple[CrossSketchRef, ...]]:
            entered.set()
            if not gate.wait(10):
                raise TimeoutError("mixed preview test did not release the worker")
            return actual_prepare(
                task_services, saved, draft, pending, relations, target, reference, target_mm
            )

        monkeypatch.setattr(app, "prepare_mixed_handle_drag", delayed_prepare)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 2)))
        QTest.mouseMove(canvas, canvas.local_to_screen((0, 3)))
        qtbot.waitUntil(entered.is_set, timeout=10000)
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
        assert not canvas.saved_handle_drag_active
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 3)))
        gate.set()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
        assert canvas.entities == [circle] and canvas.pending_cross_tangencies == pairs
        assert canvas.mixed_move is None
        entered.clear()
        gate.clear()
        QTest.mouseMove(canvas, canvas.local_to_screen((0, 2)))
        qtbot.wait(50)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 2)))
        QTest.mouseMove(canvas, canvas.local_to_screen((0, 3)))
        qtbot.waitUntil(entered.is_set, timeout=10000)
        loaded = window.loaded_document()
        assert loaded is not None
        extra = Sketch(
            uuid4().hex, editor.current_frame(), (LineEntity(uuid4().hex, (30, 30), (35, 30)),)
        )
        loaded.bus.execute("sketch.create", extra.to_mapping(version=3), "local")
        changed = services.kernel.sketches
        gate.set()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
        assert not canvas.saved_handle_drag_active and canvas.mixed_move is None
        assert services.kernel.sketches == changed
        assert canvas.entities == [circle] and canvas.pending_cross_tangencies == pairs
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 3)))
        monkeypatch.setattr(app, "prepare_mixed_handle_drag", actual_prepare)
        QTest.mouseMove(canvas, canvas.local_to_screen((0, 2)))
        qtbot.wait(50)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 2)))
    QTest.mouseMove(canvas, canvas.local_to_screen((0, 3)))
    qtbot.waitUntil(lambda: bool(canvas.saved_handle_preview), timeout=15000)
    assert canvas.entities == [circle]
    assert canvas.pending_cross_tangencies == pairs
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 3)))
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert canvas.mixed_move is not None, editor.status_label.text()
    updated = canvas.entities[0]
    source = next(
        entity
        for entity, _layer in canvas.background_entities
        if entity.entity_id == line.entity_id
    )
    assert isinstance(updated, CircleEntity) and isinstance(source, LineEntity)
    assert updated.center_mm == pytest.approx((0, 3), abs=0.15)
    assert tangent_on_curves(source, updated)
    if linked_count == 2:
        upper_source = next(
            entity
            for entity, _layer in canvas.background_entities
            if entity.entity_id == upper.entity_id
        )
        assert isinstance(upper_source, LineEntity) and tangent_on_curves(upper_source, updated)
    assert canvas.pending_cross_tangencies == pairs
    assert canvas.undo_last_operation() and canvas.entities == [circle]
    assert canvas.pending_cross_tangencies == pairs
    assert canvas.redo_last_operation() and canvas.mixed_move is not None
    first_draft = canvas.entities[0]
    first_background = tuple(entity for entity, _layer in canvas.background_entities)
    assert isinstance(first_draft, CircleEntity)
    history_position = canvas.history_position
    QTest.mousePress(
        canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(first_draft.center_mm)
    )
    second_target = (1.0, first_draft.center_mm[1])
    QTest.mouseMove(canvas, canvas.local_to_screen(second_target))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(second_target))
    qtbot.waitUntil(
        lambda: canvas.history_position > history_position and not unit.is_busy, timeout=15000
    )
    assert isinstance(canvas.entities[0], CircleEntity)
    assert canvas.entities[0].center_mm == pytest.approx(second_target, abs=0.15)
    assert canvas.pending_cross_tangencies == pairs
    assert canvas.undo_last_operation() and canvas.entities == [first_draft]
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == linked_count
    validate_tangency_component(services.kernel.sketches, relations, relations[0].first.sketch_id)
    loaded = window.loaded_document()
    assert loaded is not None
    path = tmp_path / "mixed-handle.my2d"
    save_document(loaded.document, path)
    after = services.kernel.sketches
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    restored = services.kernel.sketches
    assert any(first_draft in sketch.entities for sketch in restored)
    assert all(any(entity in sketch.entities for sketch in restored) for entity in first_background)
    assert len(services.kernel.cross_sketch_tangencies) == linked_count
    reopened.bus.undo()
    restored = services.kernel.sketches
    assert any(all(source in sketch.entities for source in sources) for sketch in restored)
    assert any(circle in sketch.entities for sketch in restored)
    assert len(services.kernel.cross_sketch_tangencies) == linked_count
    reopened.bus.redo()
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_drag_and_save_mixed_draft_with_equal_constraint(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    other = CircleEntity(uuid4().hex, (8, 5), 2)
    assert canvas.replace_draft_entities((circle, other))
    relation = SketchConstraint(
        uuid4().hex,
        "equal",
        (
            SketchGeometryReference(circle.entity_id, "geometry"),
            SketchGeometryReference(other.entity_id, "geometry"),
        ),
    )
    canvas.constraints = [relation]
    canvas.pending_cross_tangencies = [(line.entity_id, circle.entity_id)]
    editor.snap_check.setChecked(False)
    assert canvas.set_tool("选择元素")
    QTest.mouseMove(canvas, canvas.local_to_screen((0, 2)))
    qtbot.wait(50)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 2)))
    QTest.mouseMove(canvas, canvas.local_to_screen((0, 3)))
    qtbot.waitUntil(
        lambda: bool(canvas.saved_handle_preview) or not canvas.saved_handle_drag_active,
        timeout=15000,
    )
    assert canvas.saved_handle_preview, (canvas.message, editor.status_label.text())
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 3)))
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert isinstance(canvas.entities[0], CircleEntity)
    assert canvas.entities[0].center_mm == pytest.approx((0, 3), abs=0.1), (
        canvas.message,
        editor.status_label.text(),
        canvas.mixed_move,
    )
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    assert services.kernel.sketches[-1].constraints == (relation,)
    assert len(services.kernel.cross_sketch_tangencies) == 1
    loaded = window.loaded_document()
    assert loaded is not None
    assert any(
        command.id == "sketch.create" and command.version == 9
        for command in loaded.document.commands
    )


def test_drag_saved_handle_with_pending_draft_tangency(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    assert canvas.replace_draft_entities((circle,))
    canvas.pending_cross_tangencies = [(line.entity_id, circle.entity_id)]
    editor.snap_check.setChecked(False)
    assert canvas.set_tool("选择元素")
    before = services.kernel.sketches
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert line.entity_id in canvas.selected_entity_ids
    start = canvas.local_to_screen(line.start_mm)
    end = canvas.local_to_screen((-10, 1))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    qtbot.waitUntil(lambda: bool(canvas.saved_handle_preview), timeout=15000)
    assert services.kernel.sketches == before and canvas.entities == [circle]
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=15000)
    changed_line = next(
        item for item, _layer in canvas.background_entities if item.entity_id == line.entity_id
    )
    changed_circle = canvas.entities[0]
    assert isinstance(changed_line, LineEntity) and isinstance(changed_circle, CircleEntity)
    assert changed_line.start_mm == pytest.approx((-10, 1), abs=0.15)
    assert tangent_on_curves(changed_line, changed_circle)
    assert canvas.pending_cross_tangencies == [(line.entity_id, circle.entity_id)]
    assert services.kernel.sketches == before
    assert canvas.undo_last_operation() and canvas.entities == [circle]
    assert canvas.redo_last_operation() and canvas.mixed_move is not None
    first_circle = canvas.entities[0]
    first_line = next(
        item for item, _layer in canvas.background_entities if item.entity_id == line.entity_id
    )
    assert isinstance(first_line, LineEntity) and isinstance(first_circle, CircleEntity)
    position = canvas.history_position
    QTest.mousePress(
        canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(first_line.start_mm)
    )
    QTest.mouseMove(canvas, canvas.local_to_screen((-10, 2)))
    qtbot.waitUntil(lambda: bool(canvas.saved_handle_preview), timeout=15000)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-10, 2)))
    qtbot.waitUntil(lambda: canvas.history_position > position and not unit.is_busy, timeout=15000)
    assert canvas.pending_cross_tangencies == [(line.entity_id, circle.entity_id)]
    assert canvas.undo_last_operation() and canvas.entities == [first_circle]
    assert any(item == first_line for item, _layer in canvas.background_entities)
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == 1
    validate_tangency_component(services.kernel.sketches, relations, relations[0].first.sketch_id)
    loaded = window.loaded_document()
    assert loaded is not None
    after = services.kernel.sketches
    path = tmp_path / "saved-handle-mixed.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert any(first_circle in sketch.entities for sketch in services.kernel.sketches)
    assert any(first_line in sketch.entities for sketch in services.kernel.sketches)
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_editing_fillet_arc_removes_invalid_pending_relations_and_undo_restores_them(
    qtbot: QtBot,
) -> None:
    from dataclasses import replace

    from mycad.core.sketch import Sketch, WorkPlaneFrame

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), circles)
    canvas.set_background_sketches((source,), WorkPlaneFrame.xy())
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "4"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.pending_cross_tangencies) == 2
    arc = canvas.entities[0]
    assert isinstance(arc, ArcEntity)
    assert canvas.replace_draft_entities((replace(arc, center_mm=(100, 100)),))
    assert not canvas.pending_cross_tangencies
    assert canvas.undo_last_operation() and len(canvas.pending_cross_tangencies) == 2
    canvas.selected_entity_ids = {arc.entity_id}
    assert canvas.delete_selected()
    assert not canvas.pending_cross_tangencies
    assert canvas.undo_last_operation() and len(canvas.pending_cross_tangencies) == 2


def test_cross_fillet_before_mixed_edit_survives_step_undo(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    lines = (LineEntity(uuid4().hex, (0, 0), (10, 0)), LineEntity(uuid4().hex, (0, 0), (0, 10)))
    circles = (CircleEntity(uuid4().hex, (30, 0), 2), CircleEntity(uuid4().hex, (40, 0), 2))
    assert editor.canvas.replace_draft_entities((*lines, *circles))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "4"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((31.7, 1.1), (38.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.pending_cross_tangencies) == 2
    arc = canvas.entities[0]
    before_draft = tuple(canvas.entities)
    before_relations = tuple(canvas.pending_cross_tangencies)
    canvas.committed_move_requested.emit((circles[0].entity_id, arc.entity_id), (0.0, 1.0))
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert tuple(canvas.entities) != before_draft, editor.status_label.text()
    assert tuple(canvas.pending_cross_tangencies) == before_relations
    assert canvas.mixed_move is not None
    assert canvas.undo_last_operation()
    assert tuple(canvas.entities) == before_draft and canvas.mixed_move is None
    assert canvas.redo_last_operation() and canvas.mixed_move is not None
    assert canvas.undo_last_operation() and canvas.mixed_move is None
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert len(canvas.pending_cross_tangencies) == 4
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert len(services.kernel.cross_sketch_tangencies) == 4
    loaded = window.loaded_document()
    assert loaded is not None
    loaded.bus.undo()
    assert len(services.kernel.cross_sketch_tangencies) == 2
    loaded.bus.redo()
    assert len(services.kernel.cross_sketch_tangencies) == 4


@pytest.mark.parametrize("mode", ("move", "rotate", "mirror"))
def test_mixed_tangent_move_saves_and_replays(qtbot: QtBot, tmp_path: Path, mode: str) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    unrelated = CircleEntity(uuid4().hex, (30, 30), 3)
    assert editor.canvas.replace_draft_entities((*circles, unrelated))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "4"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    arc = canvas.entities[0]
    selected = (circles[0].entity_id, arc.entity_id)
    if mode == "rotate":
        canvas.committed_rotation_requested.emit(selected, (0.0, 0.0), 10.0)
    elif mode == "mirror":
        canvas.committed_mirror_requested.emit(selected, (0.0, 0.0), (0.0, 1.0))
    else:
        canvas.committed_move_requested.emit(selected, (0.0, 1.0))
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.mixed_move is not None, editor.status_label.text()
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    loaded = window.loaded_document()
    assert loaded is not None
    assert len(services.kernel.cross_sketch_tangencies) == 2
    final = services.kernel.sketches
    assert any(unrelated in sketch.entities for sketch in final)
    relation = services.kernel.cross_sketch_tangencies[0]
    validate_tangency_component(
        final, services.kernel.cross_sketch_tangencies, relation.first.sketch_id
    )
    path = tmp_path / "mixed-tangent.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    loaded.bus.redo()
    assert services.kernel.sketches == final
    reopened_services = app.build_app(discoverers=[])
    reopened = app.open_app_document(reopened_services, path)
    assert reopened.document.commands
    assert reopened_services.kernel.sketches == final
    assert len(reopened_services.kernel.cross_sketch_tangencies) == 2


def test_cross_fillet_after_mixed_edit_replays_as_separate_history_step(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    lines = (LineEntity(uuid4().hex, (0, 0), (10, 0)), LineEntity(uuid4().hex, (0, 0), (0, 10)))
    circles = (CircleEntity(uuid4().hex, (30, 0), 2), CircleEntity(uuid4().hex, (40, 0), 2))
    assert editor.canvas.replace_draft_entities((*lines, *circles))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert len(canvas.pending_cross_tangencies) == 2
    for value in ("FILLET", "R", "4"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((31.7, 1.1), (38.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.pending_cross_tangencies) == 4
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert len(services.kernel.cross_sketch_tangencies) == 4
    loaded = window.loaded_document()
    assert loaded is not None
    loaded.bus.undo()
    assert len(services.kernel.cross_sketch_tangencies) == 2
    assert any(
        isinstance(e, ArcEntity) for sketch in services.kernel.sketches for e in sketch.entities
    )
    loaded.bus.redo()
    assert len(services.kernel.cross_sketch_tangencies) == 4


@pytest.mark.parametrize("multiple", [False, True])
def test_fillet_multiple_controls_completion_and_enter(qtbot: QtBot, multiple: bool) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    circles = tuple(CircleEntity(uuid4().hex, (x, 0), 2) for x in (0, 10, 30, 40))
    assert canvas.replace_draft_entities(circles)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "M", "R", "4") if multiple else ("FILLET", "R", "4"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 5
    assert canvas.tool == ("二维圆角" if multiple else "选择元素")
    if multiple:
        for point in ((31.7, 1.1), (38.3, 1.1)):
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
        assert len(canvas.entities) == 6
        command.clear()
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert canvas.tool == "选择元素"
    command.clear()
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.tool == "二维圆角"


@pytest.mark.parametrize("multiple", [False, True])
def test_fillet_saved_sources_complete_after_candidate(qtbot: QtBot, multiple: bool) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    assert editor.canvas.replace_draft_entities((first, second))
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "M", "R", "2") if multiple else ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert canvas.tool == ("二维圆角" if multiple else "选择元素")


def test_fillet_failed_saved_candidate_keeps_command_available_for_retry(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    lines = (LineEntity(uuid4().hex, (0, 0), (10, 0)), LineEntity(uuid4().hex, (0, 0), (0, 10)))
    assert editor.canvas.replace_draft_entities(lines)
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    original = app.stage_mixed_drawing_timeline

    def fail(*_args: object, **_kwargs: object) -> None:
        raise ValueError("candidate failure probe")

    monkeypatch.setattr(app, "stage_mixed_drawing_timeline", fail)
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(
        lambda: "失败" in editor.status_label.text() and not unit.is_busy, timeout=10000
    )
    assert canvas.tool == "二维圆角" and canvas.mixed_move is None and not canvas.entities
    monkeypatch.setattr(app, "stage_mixed_drawing_timeline", original)
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert canvas.tool == "选择元素"


@pytest.mark.parametrize("circle_first", [False, True])
def test_line_circle_fillet_trims_line_and_undoes(qtbot: QtBot, circle_first: bool) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (-20.0, 0.0), (20.0, 0.0))
    circle = CircleEntity(uuid4().hex, (0.0, 5.0), 2.0)
    assert canvas.replace_draft_entities((line, circle))
    command = editor.drawing_command_bar.input
    for text in ("FILLET", "R", "2"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    picks = ((-3.0, 0.0), (-1.3, 3.5))
    for pick in reversed(picks) if circle_first else picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(pick))
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].start_mm == line.start_mm
    assert canvas.entities[0].end_mm == pytest.approx((-(7.0**0.5), 0.0))
    assert canvas.entities[1] == circle
    assert len(canvas.entities) == 3 and isinstance(canvas.entities[2], ArcEntity), canvas.message
    assert canvas.entities[2].center_mm == pytest.approx((-(7.0**0.5), 2.0))
    assert canvas.undo_last_operation() and canvas.entities == [line, circle]
    assert canvas.redo_last_operation() and len(canvas.entities) == 3


def test_line_circle_internal_fillet_creates_tangency_constraints(qtbot: QtBot) -> None:
    import math

    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (-20.0, 0.0), (20.0, 0.0))
    circle = CircleEntity(uuid4().hex, (0.0, 4.0), 5.0)
    assert canvas.replace_draft_entities((line, circle))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((-5.0, 0.0), (-4.0, 1.0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 3 and isinstance(canvas.entities[2], ArcEntity), canvas.message
    arc = canvas.entities[2]
    assert math.dist(arc.center_mm, circle.center_mm) == pytest.approx(3.0)
    assert len([relation for relation in canvas.constraints if relation.kind == "tangent"]) == 2


@pytest.mark.parametrize("pair", ["line_arc", "arc_arc", "arc_circle"])
def test_arc_fillet_trims_arcs_and_undoes(qtbot: QtBot, pair: str) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    if pair == "line_arc":
        sources = (
            LineEntity(uuid4().hex, (-20.0, 0.0), (20.0, 0.0)),
            ArcEntity(uuid4().hex, (0.0, 5.0), 2.0, 180.0, 90.0),
        )
        radius, picks = 2, ((-3.0, 0.0), (-1.3, 3.5))
    else:
        sources = (
            ArcEntity(uuid4().hex, (0.0, 0.0), 2.0, 0.0, 90.0),
            ArcEntity(uuid4().hex, (10.0, 0.0), 2.0, 90.0, 90.0)
            if pair == "arc_arc"
            else CircleEntity(uuid4().hex, (10.0, 0.0), 2.0),
        )
        radius, picks = 4, ((1.7, 1.1), (8.3, 1.1))
    assert canvas.replace_draft_entities(sources)
    command = editor.drawing_command_bar.input
    for text in ("FILLET", "R", str(radius)):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for pick in picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(pick))
    if pair == "line_arc":
        assert isinstance(canvas.entities[0], LineEntity)
        assert canvas.entities[0].end_mm == pytest.approx((-(7.0**0.5), 0.0))
        assert isinstance(canvas.entities[1], ArcEntity)
        assert isinstance(sources[1], ArcEntity)
        assert abs(canvas.entities[1].sweep_angle_deg) < abs(sources[1].sweep_angle_deg)
    else:
        assert isinstance(canvas.entities[0], ArcEntity)
        assert isinstance(sources[0], ArcEntity)
        assert abs(canvas.entities[0].sweep_angle_deg) < abs(sources[0].sweep_angle_deg)
        if pair == "arc_arc":
            assert isinstance(canvas.entities[1], ArcEntity)
            assert isinstance(sources[1], ArcEntity)
            assert abs(canvas.entities[1].sweep_angle_deg) < abs(sources[1].sweep_angle_deg)
        else:
            assert canvas.entities[1] == sources[1]
    assert len(canvas.entities) == 3 and isinstance(canvas.entities[2], ArcEntity)
    assert canvas.undo_last_operation() and canvas.entities == list(sources)
    assert canvas.redo_last_operation() and len(canvas.entities) == 3


@pytest.mark.parametrize("extend_arc", [False, True])
def test_saved_line_arc_fillet_replays_and_reopens(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extend_arc: bool
) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    line = LineEntity(uuid4().hex, (-20.0, 0.0), (-5.0, 0.0))
    source_arc = ArcEntity(uuid4().hex, (0.0, 5.0), 2.0, 180.0, 30.0 if extend_arc else 90.0)
    assert editor.canvas.replace_draft_entities((line, source_arc))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((-10.0, 0.0), (-1.93, 4.48) if extend_arc else (-1.3, 3.5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(
        lambda: editor.canvas.mixed_move is not None and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "line-arc-fillet.mc.json"

    def choose(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: path.exists() and not unit.is_busy, timeout=10000)
    current = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not current and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    entities = {entity.entity_id: entity for entity, _layer in reopened.canvas.background_entities}
    result_line, result_arc = entities[line.entity_id], entities[source_arc.entity_id]
    assert isinstance(result_line, LineEntity) and isinstance(result_arc, ArcEntity)
    assert result_line.end_mm == pytest.approx((-(7.0**0.5), 0.0))
    if extend_arc:
        assert abs(result_arc.sweep_angle_deg) > abs(source_arc.sweep_angle_deg)
    else:
        assert abs(result_arc.sweep_angle_deg) < abs(source_arc.sweep_angle_deg)


def test_fillet_invalid_radius_and_cancel_leave_circles_unchanged(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    canvas.entities = [first, second]
    command = editor.drawing_command_bar.input
    for text in ("F", "R", "-1"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert "半径" in editor.drawing_command_bar.status.text()
    assert canvas.circle_fillet_radius_pending
    assert canvas.entities == [first, second]
    assert not canvas.has_active_edit_gesture
    command.setText("4")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1.7, 1.1)))
    assert canvas.has_active_edit_gesture
    command.clear()
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.has_active_edit_gesture
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.has_active_edit_gesture
    assert canvas.entities == [first, second]


@pytest.mark.parametrize("line_circle", [False, True])
def test_fillet_on_committed_circles_survives_save_and_reopen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line_circle: bool
) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    sources = (
        (LineEntity(uuid4().hex, (-20, 0), (20, 0)), CircleEntity(uuid4().hex, (0, 5), 2))
        if line_circle
        else (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    )
    assert draft.canvas.replace_draft_entities(sources)
    draft.finish_button.click()
    qtbot.waitUntil(
        lambda: (
            window.active_sketch_dialog() is not None
            and window.active_sketch_dialog() is not draft
            and not unit.is_busy
        ),
        timeout=10000,
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    command = editor.drawing_command_bar.input
    radius = 2 if line_circle else 4
    for text in ("FILLET", "R", str(radius)):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=editor.canvas.local_to_screen((-3.0, 0.0) if line_circle else (1.7, 1.1)),
    )
    assert editor.canvas.has_active_edit_gesture
    loaded = window.loaded_document()
    assert loaded is not None
    commands = loaded.document.commands
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert loaded.document.commands == commands
    assert editor.canvas.has_active_edit_gesture
    assert "取消" in window.status_command.text()
    window.request_redo()
    assert "取消" in window.status_command.text()
    assert loaded.document.commands == commands
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=editor.canvas.local_to_screen((-1.3, 3.5) if line_circle else (8.3, 1.1)),
    )
    if line_circle:
        qtbot.waitUntil(
            lambda: editor.canvas.mixed_move is not None and not unit.is_busy, timeout=10000
        )
    assert len(editor.canvas.entities) == 1
    arc = editor.canvas.entities[0]
    assert isinstance(arc, ArcEntity)
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: (
            window.active_sketch_dialog() is not None
            and window.active_sketch_dialog() is not editor
            and not unit.is_busy
        ),
        timeout=10000,
    )
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    assert submitted.canvas.circle_fillet_radius == radius
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    after_undo = window.active_sketch_dialog()
    assert after_undo is not None
    assert arc not in tuple(entity for entity, _layer in after_undo.canvas.background_entities)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    assert arc in tuple(entity for entity, _layer in submitted.canvas.background_entities)
    path = tmp_path / "fillet.mc.json"

    def choose_file(*_args: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose_file)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose_file)
    window.act_save.trigger()
    assert path.is_file()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: (
            window.active_sketch_dialog() is not None
            and window.active_sketch_dialog() is not submitted
            and not unit.is_busy
        ),
        timeout=10000,
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    entities = tuple(entity for entity, _layer in reopened.canvas.background_entities)
    if line_circle:
        result_line = next(
            entity for entity in entities if entity.entity_id == sources[0].entity_id
        )
        assert isinstance(result_line, LineEntity)
        assert result_line.end_mm == pytest.approx((-(7.0**0.5), 0.0))
        assert sources[1] in entities
    else:
        assert all(source in entities for source in sources)
    assert arc in entities


def test_fillet_no_solution_can_change_radius_without_reselecting_first(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    canvas.entities = list(circles)
    command = editor.drawing_command_bar.input
    command.setText("FILLET")
    QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities == list(circles)
    assert canvas.has_active_edit_gesture
    assert "无法" in canvas.message
    for text in ("R", "4"):
        command.setText(text)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8.3, 1.1)))
    assert isinstance(canvas.entities[-1], ArcEntity)
    assert not canvas.has_active_edit_gesture


def test_fillet_does_not_create_geometry_on_locked_active_layer(qtbot: QtBot) -> None:
    from dataclasses import replace

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    canvas.entities = list(circles)
    locked = editor.layer_table.replace(replace(editor.layer_table.get("0"), locked=True))
    canvas.set_layer_table(locked, "0")
    command = editor.drawing_command_bar.input
    command.setText("FILLET")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1.7, 1.1)))
    assert canvas.entities == list(circles)
    assert not canvas.has_active_edit_gesture
    assert "锁定" in canvas.message


def test_line_fillet_trims_two_draft_lines_as_one_undo(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (0.0, 0.0), (0.0, 10.0))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8.0, 0.0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 8.0)))
    assert len(canvas.entities) == 3
    first_trimmed, second_trimmed, arc = canvas.entities
    assert isinstance(first_trimmed, LineEntity) and isinstance(second_trimmed, LineEntity)
    assert first_trimmed.start_mm == pytest.approx((2.0, 0.0))
    assert second_trimmed.start_mm == pytest.approx((0.0, 2.0))
    assert isinstance(arc, ArcEntity) and arc.radius_mm == 2.0
    assert len([relation for relation in canvas.constraints if relation.kind == "tangent"]) == 2
    assert len([relation for relation in canvas.constraints if relation.kind == "coincident"]) == 2
    assert canvas.undo_last_operation() and canvas.entities == [first, second]
    assert not canvas.constraints
    assert canvas.redo_last_operation() and canvas.entities == [first_trimmed, second_trimmed, arc]
    assert len([relation for relation in canvas.constraints if relation.kind == "tangent"]) == 2


@pytest.mark.parametrize("trim", [False, True])
@pytest.mark.parametrize("radius", [0, 8])
def test_parallel_line_fillet_keeps_first_line_and_is_undoable(
    qtbot: QtBot, trim: bool, radius: int
) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (-5, 4), (15, 4))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    values = ["FILLET", "R", str(radius)] + ([] if trim else ["T", "N"])
    for value in values:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((9, 0), (5, 4)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 3
    assert canvas.entities[0] == first
    assert isinstance(canvas.entities[1], LineEntity)
    assert canvas.entities[1].end_mm == pytest.approx((10, 4) if trim else (15, 4))
    assert isinstance(canvas.entities[2], ArcEntity)
    assert canvas.entities[2].radius_mm == pytest.approx(2)
    assert canvas.entities[2].center_mm == pytest.approx((10, 2))
    assert canvas.undo_last_operation() and canvas.entities == [first, second]


def test_fillet_respects_disabled_automatic_relations(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(False)
    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (0.0, 0.0), (0.0, 10.0))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8.0, 0.0), (0.0, 8.0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 3
    assert not canvas.constraints


def test_fillet_trim_option_retains_sources(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (0.0, 0.0), (0.0, 10.0))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8.0, 0.0), (0.0, 8.0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities[:2] == [first, second]
    assert len(canvas.entities) == 3 and isinstance(canvas.entities[2], ArcEntity)
    assert canvas.undo_last_operation() and canvas.entities == [first, second]


def test_polyline_fillet_infeasible_replacement_keeps_existing_arc(qtbot: QtBot) -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    points, bulges = polyline_fillet_trimmed_segments(source, 2)
    rounded = PolylineEntity(source.entity_id, points, bulges=bulges)
    assert canvas.replace_draft_entities((rounded,))
    history = canvas.history_position
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "100", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((4, 0)))
    assert canvas.entities == [rounded]
    assert canvas.history_position == history


def test_polyline_fillet_same_radius_does_not_create_history(qtbot: QtBot) -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    points, bulges = polyline_fillet_trimmed_segments(source, 2)
    rounded = PolylineEntity(source.entity_id, points, bulges=bulges)
    assert canvas.replace_draft_entities((rounded,))
    history = canvas.history_position
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((4, 0)))
    assert canvas.entities == [rounded]
    assert canvas.history_position == history


def test_saved_polyline_fillet_infeasible_replacement_does_not_write(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments
    from mycad.core.sketch import PolylineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    points, bulges = polyline_fillet_trimmed_segments(source, 2)
    rounded = PolylineEntity(source.entity_id, points, bulges=bulges)
    assert editor.canvas.replace_draft_entities((rounded,))
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    before = loaded.document.commands
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "100", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    before = loaded.document.commands
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((4, 0))
    )
    assert loaded.document.commands == before
    assert services.kernel.sketches[0].entities == (rounded,)
    assert editor.canvas.mixed_move is None


@pytest.mark.parametrize("trim", [False, True])
def test_polyline_fillet_retains_existing_corner_when_shared_segment_is_short(
    qtbot: QtBot, trim: bool
) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 6), (20, 6)))
    points, bulges = polyline_fillet_trimmed_segments(source, 1)
    rounded = PolylineEntity(source.entity_id, points, bulges=bulges)
    assert canvas.replace_draft_entities((rounded,))
    command = editor.drawing_command_bar.input
    for value in ["FILLET", "R", "4"] + ([] if trim else ["T", "N"]) + ["P"]:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((4, 0)))
    if trim:
        result = canvas.entities[0]
        assert isinstance(result, PolylineEntity)
        segments = polyline_curve_segments(result.points_mm, result.bulges, False, result.entity_id)
        arcs = [segment for segment in segments if isinstance(segment, ArcEntity)]
        assert sorted(arc.radius_mm for arc in arcs) == pytest.approx([1, 4])
    else:
        assert canvas.entities[0] == rounded
        assert len(canvas.entities) == 2 and isinstance(canvas.entities[1], ArcEntity)
        assert canvas.entities[1].radius_mm == pytest.approx(4)
    assert canvas.undo_last_operation() and canvas.entities == [rounded]


def test_saved_polyline_fillet_partial_replacement_replays_and_undoes(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments
    from mycad.core.sketch import PolylineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 6), (20, 6)))
    points, bulges = polyline_fillet_trimmed_segments(source, 1)
    rounded = PolylineEntity(source.entity_id, points, bulges=bulges)
    assert editor.canvas.replace_draft_entities((rounded,))
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    before = loaded.document.commands
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "4", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    before = loaded.document.commands
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((4, 0))
    )
    qtbot.waitUntil(lambda: loaded.document.commands != before and not unit.is_busy, timeout=10000)
    changed = services.kernel.sketches[0].entities[0]
    assert isinstance(changed, PolylineEntity) and changed.entity_id == rounded.entity_id
    segments = polyline_curve_segments(changed.points_mm, changed.bulges, False, changed.entity_id)
    assert sorted(
        segment.radius_mm for segment in segments if isinstance(segment, ArcEntity)
    ) == pytest.approx([1, 4])
    path = tmp_path / "partial-polyline-fillet.mc.json"

    def choose(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: path.exists() and not unit.is_busy)
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not previous and not unit.is_busy)
    reopened = window.loaded_document()
    assert reopened is not None
    assert services.kernel.sketches[0].entities == (changed,)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.sketches[0].entities == (rounded,) and not unit.is_busy)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.sketches[0].entities == (changed,) and not unit.is_busy)


def test_polyline_no_trim_keeps_new_arc_on_existing_support(qtbot: QtBot) -> None:
    import math

    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    source = PolylineEntity(
        uuid4().hex,
        ((-2, 0), (0, 2), (2, 10), (2, -2), (-10, -2)),
        bulges=(1 - 2**0.5, 0, 0, 0),
    )
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-6, -2)))
    assert canvas.entities[0] == source
    arcs = [entity for entity in canvas.entities[1:] if isinstance(entity, ArcEntity)]
    assert len(arcs) == 2
    assert any(math.dist(arc.center_mm, (0, 0)) < 1e-8 for arc in arcs)
    assert canvas.undo_last_operation() and canvas.entities == [source]


def test_saved_polyline_no_trim_shared_support_replays_and_undoes(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import math

    from mycad import app
    from mycad.core.sketch import PolylineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    source = PolylineEntity(
        uuid4().hex,
        ((-2, 0), (0, 2), (2, 10), (2, -2), (-10, -2)),
        bulges=(1 - 2**0.5, 0, 0, 0),
    )
    assert editor.canvas.replace_draft_entities((source,))
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    before = loaded.document.commands
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    before = loaded.document.commands
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((-6, -2))
    )
    arcs = tuple(item for item in editor.canvas.entities if isinstance(item, ArcEntity))
    assert len(arcs) == 2 and any(math.dist(item.center_mm, (0, 0)) < 1e-8 for item in arcs)
    assert loaded.document.commands == before
    path = tmp_path / "shared-support-fillet.mc.json"

    def choose(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: path.exists() and not unit.is_busy)
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not previous and not unit.is_busy)
    entities = tuple(item for sketch in services.kernel.sketches for item in sketch.entities)
    assert source in entities and all(item in entities for item in arcs)
    window.request_undo()
    qtbot.waitUntil(lambda: len(services.kernel.sketches) == 1 and not unit.is_busy)
    assert services.kernel.sketches[0].entities == (source,)
    window.request_redo()
    qtbot.waitUntil(lambda: len(services.kernel.sketches) == 2 and not unit.is_busy)
    assert all(item in services.kernel.sketches[1].entities for item in arcs)


def test_polyline_fillet_no_trim_is_one_undoable_operation(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True)
    assert canvas.replace_draft_entities((polyline,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert canvas.entities[0] == polyline
    assert len(canvas.entities) == 5 and all(isinstance(e, ArcEntity) for e in canvas.entities[1:])
    assert canvas.undo_last_operation() and canvas.entities == [polyline]
    assert canvas.redo_last_operation() and len(canvas.entities) == 5


@pytest.mark.parametrize("trim", [True, False])
def test_whole_rectangle_fillet_is_one_undoable_operation(qtbot: QtBot, trim: bool) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    assert canvas.replace_draft_entities((rectangle,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "T" if trim else "N", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    if trim:
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity)
        assert canvas.entities[0].entity_id != rectangle.entity_id and canvas.entities[0].bulges
    else:
        assert canvas.entities[0] == rectangle
        assert len(canvas.entities) == 5 and all(
            isinstance(e, ArcEntity) for e in canvas.entities[1:]
        )
        assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 8
    assert canvas.undo_last_operation() and canvas.entities == [rectangle]
    assert canvas.redo_last_operation()


@pytest.mark.parametrize("whole", [True, False])
def test_saved_rectangle_fillet_replays(qtbot: QtBot, tmp_path: Path, whole: bool) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    assert editor.canvas.replace_draft_entities((rectangle,))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    for value in ("FILLET", "R", "2", *(["P"] if whole else [])):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    count = len(loaded.document.commands)
    for point in ((5, 0),) if whole else ((5, 0), (10, 5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    result = services.kernel.sketches[0].entities[0]
    assert isinstance(result, PolylineEntity) and result.entity_id != rectangle.entity_id
    path = tmp_path / "rectangle-fillet.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == (result,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0].entities == (rectangle,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches[0].entities == (result,)


@pytest.mark.parametrize("trim", [True, False])
def test_fillet_two_rectangle_edges(qtbot: QtBot, trim: bool) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    assert canvas.replace_draft_entities((rectangle,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "T" if trim else "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((5, 0), (10, 5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim:
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity)
        assert canvas.entities[0].entity_id != rectangle.entity_id and canvas.entities[0].bulges
    else:
        assert len(canvas.entities) == 2 and canvas.entities[0] == rectangle
        assert isinstance(canvas.entities[1], ArcEntity)
        assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
    assert canvas.undo_last_operation() and canvas.entities == [rectangle]


@pytest.mark.parametrize("trim", [True, False])
@pytest.mark.parametrize("rectangle_first", [True, False])
def test_fillet_rectangle_and_line(qtbot: QtBot, trim: bool, rectangle_first: bool) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    x = 15 if trim else 8
    line = LineEntity(uuid4().hex, (x, -10), (x, 5))
    assert canvas.replace_draft_entities((rectangle, line))
    for value in ("FILLET", "R", "2", "T", "T" if trim else "N"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    points = ((4, 0), (x, -5)) if rectangle_first else ((x, -5), (4, 0))
    for point in points:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim:
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity)
        assert canvas.entities[0].entity_id != rectangle.entity_id
    else:
        assert canvas.entities[:2] == [rectangle, line]
        assert len(canvas.entities) == 3 and isinstance(canvas.entities[2], ArcEntity)
        assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
    assert canvas.undo_last_operation() and canvas.entities == [rectangle, line]


@pytest.mark.parametrize("trim", [True, False])
@pytest.mark.parametrize("rectangle_first", [True, False])
@pytest.mark.parametrize("kind", ["circle", "arc"])
def test_fillet_rectangle_and_circular_curve(
    qtbot: QtBot, trim: bool, rectangle_first: bool, kind: str
) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (-20, 0), (20, -10))
    circular = (
        CircleEntity(uuid4().hex, (0, 5), 2)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (0, 5), 2, 180, 180)
    )
    assert canvas.replace_draft_entities((rectangle, circular))
    for value in ("FILLET", "R", "2", "T", "T" if trim else "N"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    points = ((-3, 0), (-1.3, 3.5))
    for point in points if rectangle_first else reversed(points):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 3, canvas.message
    if trim:
        assert isinstance(canvas.entities[0], PolylineEntity)
        assert canvas.entities[0].entity_id != rectangle.entity_id
        assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
        assert any(
            ref.entity_id == canvas.entities[0].entity_id
            for item in canvas.constraints
            for ref in item.references
        )
        if kind == "arc":
            assert canvas.entities[1] != circular
    else:
        assert canvas.entities[:2] == [rectangle, circular]
        assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
    assert isinstance(canvas.entities[2], ArcEntity)
    assert canvas.undo_last_operation() and canvas.entities == [rectangle, circular]


@pytest.mark.parametrize("shape", ["rectangle", "polyline"])
@pytest.mark.parametrize("kind", ["circle", "arc"])
@pytest.mark.parametrize("trim", [True, False])
@pytest.mark.parametrize("source_first", [True, False])
def test_fillet_circular_curve_preserves_case_insensitive_source_layer(
    qtbot: QtBot, shape: str, kind: str, trim: bool, source_first: bool
) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.core.sketch_layers import SketchLayer

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    layers = editor.layer_table.add(SketchLayer("Edges"))
    editor.layer_table = layers
    canvas.set_layer_table(layers, "0")
    source = (
        RectangleEntity(uuid4().hex, (-20, 0), (20, -10), layer_name="Edges")
        if shape == "rectangle"
        else PolylineEntity(uuid4().hex, ((-20, 0), (20, 0), (20, -5)), layer_name="Edges")
    )
    circular = (
        CircleEntity(uuid4().hex, (0, 5), 2, layer_name="edges")
        if kind == "circle"
        else ArcEntity(uuid4().hex, (0, 5), 2, 180, 180, layer_name="edges")
    )
    assert canvas.replace_draft_entities((source, circular))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "T" if trim else "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    points = ((-3, 0), (-1.3, 3.5))
    for point in points if source_first else reversed(points):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 3, canvas.message
    assert isinstance(canvas.entities[-1], ArcEntity)
    assert canvas.entities[-1].layer_name.casefold() == "edges"
    result = tuple(canvas.entities)
    assert canvas.undo_last_operation() and canvas.entities == [source, circular]
    assert canvas.redo_last_operation() and tuple(canvas.entities) == result


@pytest.mark.parametrize("trim", [True, False])
@pytest.mark.parametrize("rectangle_first", [True, False])
@pytest.mark.parametrize("other_kind", ["polyline", "rectangle"])
def test_fillet_rectangle_and_other_path(
    qtbot: QtBot, trim: bool, rectangle_first: bool, other_kind: str
) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    other = (
        PolylineEntity(uuid4().hex, ((8, -10), (8, 5), (18, 5)))
        if other_kind == "polyline"
        else RectangleEntity(uuid4().hex, (8, -10), (18, 5))
    )
    assert canvas.replace_draft_entities((rectangle, other))
    for value in ("FILLET", "R", "2", "T", "T" if trim else "N"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    points = ((4, 0), (8, -5))
    for point in points if rectangle_first else reversed(points):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim:
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity), (
            canvas.message
        )
    else:
        assert canvas.entities[:2] == [rectangle, other]
        assert len(canvas.entities) == 3 and isinstance(canvas.entities[2], ArcEntity), (
            canvas.message
        )
        assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
    assert canvas.undo_last_operation() and canvas.entities == [rectangle, other]


@pytest.mark.parametrize("other_kind", ["polyline", "line"])
def test_rectangle_path_notrim_rejects_contact_on_extension(qtbot: QtBot, other_kind: str) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    other = (
        PolylineEntity(uuid4().hex, ((15, -10), (15, 5), (20, 5)))
        if other_kind == "polyline"
        else LineEntity(uuid4().hex, (15, -10), (15, 5))
    )
    assert canvas.replace_draft_entities((rectangle, other))
    history = canvas.history_position
    for value in ("FILLET", "R", "2", "T", "N"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    for point in ((5, 0), (15, -5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities == [rectangle, other] and canvas.history_position == history
    assert "切点" in canvas.message


@pytest.mark.parametrize("other_kind", ["polyline", "rectangle"])
def test_saved_rectangle_and_other_path_fillet_replays(
    qtbot: QtBot, tmp_path: Path, other_kind: str
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    other = (
        PolylineEntity(uuid4().hex, ((8, -10), (8, 5), (18, 5)))
        if other_kind == "polyline"
        else RectangleEntity(uuid4().hex, (8, -10), (18, 5))
    )
    assert editor.canvas.replace_draft_entities((rectangle, other))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    for value in ("FILLET", "R", "2"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    count = len(loaded.document.commands)
    for point in ((4, 0), (8, -5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    result = services.kernel.sketches[0].entities[0]
    assert isinstance(result, PolylineEntity) and result.entity_id != rectangle.entity_id
    path = tmp_path / "rectangle-path-fillet.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == (result,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0].entities == (rectangle, other)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches[0].entities == (result,)


def test_saved_rectangle_circle_notrim_preserves_circle_tangency(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.persistence import save_document
    from mycad.core.sketch import RectangleEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    rectangle = RectangleEntity(uuid4().hex, (-20, 0), (20, -10))
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    for entity in (rectangle, circle):
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)),
            session_identity=0,
        )
    editor.set_context_sketches(services.kernel.sketches)
    for value in ("FILLET", "R", "2", "T", "N"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    for point in ((-3, 0), (-1.3, 3.5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert len(editor.canvas.entities) == 1 and len(editor.canvas.pending_cross_tangencies) == 2
    from mycad.core.cross_sketch_tangency import draft_tangent_reference, tangent_entity_curve
    from mycad.core.fillet_curves import tangent_on_curves

    arc = editor.canvas.entities[0]
    assert isinstance(arc, ArcEntity)
    for source, _target in editor.canvas.pending_cross_tangencies:
        ref = draft_tangent_reference(source)
        original = next(
            item
            for sketch in services.kernel.sketches
            for item in sketch.entities
            if item.entity_id == ref.entity_id
        )
        assert tangent_on_curves(tangent_entity_curve(original, ref.index), arc), (
            original,
            ref,
            arc,
        )
    editor.finish_sketch()
    try:
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    except QtTimeoutError:
        pytest.fail(f"完成草图失败：{editor.status_label.text()}；{editor.canvas.message}")
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert len(relations) == 2
    validate_tangency_component(after, relations, relations[0].first.sketch_id)
    assert any(rectangle in sketch.entities for sketch in after)
    assert any(circle in sketch.entities for sketch in after)
    current = window.active_sketch_dialog()
    assert current is not None
    count = len(loaded.document.commands)
    current.canvas.committed_move_requested.emit((rectangle.entity_id,), (0.0, 1.0))
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == count + 1, current.status_label.text()
    validate_tangency_component(services.kernel.sketches, relations, relations[0].first.sketch_id)
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count, timeout=10000
    )
    assert services.kernel.sketches == after
    assert current.canvas.set_tool("选择元素")
    current.canvas.selected_entity_ids = {rectangle.entity_id}
    for value in ("SCALE", "0,0", "1.1"):
        current.drawing_command_bar.input.setText(value)
        QTest.keyClick(current.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    assert len(loaded.document.commands) == count + 1, current.status_label.text()
    validate_tangency_component(services.kernel.sketches, relations, relations[0].first.sketch_id)
    scaled = next(
        entity
        for sketch in services.kernel.sketches
        for entity in sketch.entities
        if entity.entity_id == rectangle.entity_id
    )
    assert isinstance(scaled, RectangleEntity)
    assert scaled.first_corner_mm == pytest.approx((-22, 0))
    assert scaled.opposite_corner_mm == pytest.approx((22, -11))
    scaled_sketches = services.kernel.sketches
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count, timeout=10000
    )
    assert services.kernel.sketches == after
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    assert services.kernel.sketches == scaled_sketches
    validate_tangency_component(services.kernel.sketches, relations, relations[0].first.sketch_id)
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count, timeout=10000
    )
    assert services.kernel.sketches == after
    assert current.canvas.set_tool("选择元素")
    current.canvas.selected_entity_ids = {rectangle.entity_id}
    for value in ("ROTATE", "0,0", "90"):
        current.drawing_command_bar.input.setText(value)
        QTest.keyClick(current.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == count + 1, current.status_label.text()
    rotated_relations = services.kernel.cross_sketch_tangencies
    validate_tangency_component(
        services.kernel.sketches, rotated_relations, rotated_relations[0].first.sketch_id
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count, timeout=10000
    )
    assert services.kernel.sketches == after
    assert current.canvas.set_tool("选择元素")
    current.canvas.selected_entity_ids = {rectangle.entity_id}
    current.mirror_keep_source_check.setChecked(False)
    current.transform_buttons["mirror"].click()
    current.canvas.add_coordinate_point((0, 0), exact_point=True)
    current.canvas.add_coordinate_point((1, 0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == count + 1, current.status_label.text()
    mirrored_relations = services.kernel.cross_sketch_tangencies
    validate_tangency_component(
        services.kernel.sketches, mirrored_relations, mirrored_relations[0].first.sketch_id
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count, timeout=10000
    )
    assert services.kernel.sketches == after
    assert current.canvas.set_tool("选择元素")
    current.canvas.selected_entity_ids = {rectangle.entity_id}
    for value in ("ROTATE", "0,0", "45"):
        current.drawing_command_bar.input.setText(value)
        QTest.keyClick(current.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == count + 1, current.status_label.text()
    diagonal_relations = services.kernel.cross_sketch_tangencies
    validate_tangency_component(
        services.kernel.sketches, diagonal_relations, diagonal_relations[0].first.sketch_id
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count, timeout=10000
    )
    assert services.kernel.sketches == after
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    owner = next(sketch for sketch in after if rectangle in sketch.entities)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(rectangle.entity_id, "segment", 0),),
        42,
        "mm",
    )
    app.commit_cross_sketch_dimension(
        services, loaded, owner.sketch_id, dimension, session_identity=0
    )
    validate_tangency_component(services.kernel.sketches, relations, owner.sketch_id)
    resized = next(
        entity
        for sketch in services.kernel.sketches
        for entity in sketch.entities
        if entity.entity_id == rectangle.entity_id
    )
    assert isinstance(resized, RectangleEntity)
    assert abs(resized.opposite_corner_mm[0] - resized.first_corner_mm[0]) == pytest.approx(42)
    loaded.bus.undo()
    assert services.kernel.sketches == after
    path = tmp_path / "rectangle-circle-notrim.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert services.kernel.cross_sketch_tangencies == relations


@pytest.mark.parametrize("mode", ["both_saved", "rectangle_saved", "circular_saved"])
@pytest.mark.parametrize("kind", ["circle", "arc"])
def test_rectangle_circular_fillet_saved_sources_replay_tangencies(
    qtbot: QtBot, tmp_path: Path, mode: str, kind: str
) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, RectangleEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    rectangle = RectangleEntity(uuid4().hex, (-20, 0), (20, -10))
    circular = (
        CircleEntity(uuid4().hex, (0, 5), 2)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (0, 5), 2, 180, 180)
    )
    saved = (
        (rectangle, circular)
        if mode == "both_saved"
        else (rectangle,)
        if mode == "rectangle_saved"
        else (circular,)
    )
    for entity in saved:
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)),
            session_identity=0,
        )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    if mode == "rectangle_saved":
        assert canvas.replace_draft_entities((circular,))
    elif mode == "circular_saved":
        assert canvas.replace_draft_entities((rectangle,))
    for value in ("FILLET", "R", "2"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    for point in ((-3, 0), (-1.3, 3.5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if mode != "circular_saved" or kind == "arc":
        qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    else:
        assert canvas.pending_cross_tangencies, canvas.message
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    after = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == (2 if mode == "both_saved" else 1)
    for relation in relations:
        validate_tangency_component(after, relations, relation.first.sketch_id)
    assert any(isinstance(item, PolylineEntity) for sketch in after for item in sketch.entities)
    path = tmp_path / "rectangle-circular-fillet.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


@pytest.mark.parametrize("shape", ["rectangle", "polyline"])
@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("kind", ["circle", "arc"])
def test_saved_circular_fillet_keeps_case_insensitive_layer_on_replay(
    qtbot: QtBot, tmp_path: Path, shape: str, mixed: bool, kind: str
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, RectangleEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    editor.request_layer_update(editor.layer_table.add(SketchLayer("Edges")), ".")
    qtbot.waitUntil(lambda: not unit.is_busy and len(editor.layer_table.layers) > 1, timeout=10000)
    source = (
        RectangleEntity(uuid4().hex, (-20, 0), (20, -10), layer_name="Edges")
        if shape == "rectangle"
        else PolylineEntity(uuid4().hex, ((-20, 0), (20, 0), (20, -5)), layer_name="Edges")
    )
    circular = (
        CircleEntity(uuid4().hex, (0, 5), 2, layer_name="edges")
        if kind == "circle"
        else ArcEntity(uuid4().hex, (0, 5), 2, 180, 180, layer_name="edges")
    )
    layers = editor.layer_table
    for entity in (source,) if mixed else (source, circular):
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,), layers=layers),
            session_identity=0,
        )
    editor.set_context_sketches(services.kernel.sketches)
    if mixed:
        assert editor.canvas.replace_draft_entities((circular,))
    for value in ("FILLET", "R", "2"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    for point in ((-3, 0), (-1.3, 3.5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(
        lambda: editor.canvas.mixed_move is not None and not unit.is_busy, timeout=10000
    )
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    after = services.kernel.sketches
    fillets = [
        item
        for sketch in after
        for item in sketch.entities
        if isinstance(item, ArcEntity) and item.entity_id != circular.entity_id
    ]
    assert len(fillets) == 1 and fillets[0].layer_name.casefold() == "edges"
    path = tmp_path / "saved-fillet-layer.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_saved_rectangle_and_line_fillet_replays(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    line = LineEntity(uuid4().hex, (15, -10), (15, 5))
    assert editor.canvas.replace_draft_entities((rectangle, line))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    for value in ("FILLET", "R", "2"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    count = len(loaded.document.commands)
    for point in ((5, 0), (15, -5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    result = services.kernel.sketches[0].entities[0]
    assert isinstance(result, PolylineEntity) and result.entity_id != rectangle.entity_id
    path = tmp_path / "rectangle-line-fillet.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == (result,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0].entities == (rectangle, line)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches[0].entities == (result,)


def test_rectangle_zero_radius_keeps_identity(qtbot: QtBot) -> None:
    from mycad.core.sketch import RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    assert editor.canvas.replace_draft_entities((rectangle,))
    history = editor.canvas.history_position
    for value in ("FILLET", "R", "0", "P"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    assert editor.canvas.entities == [rectangle] and editor.canvas.history_position == history


def test_polyline_fillet_honors_switch_back_to_trim(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert canvas.replace_draft_entities((polyline,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "T", "N", "P", "T", "T"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    assert len(canvas.entities) == 1
    rounded = canvas.entities[0]
    assert isinstance(rounded, PolylineEntity) and rounded.bulges
    assert rounded.entity_id == polyline.entity_id


def test_polyline_fillet_empty_enter_repeats_the_polyline_prompt(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "T", "N", "P", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert "多段线" in editor.drawing_command_bar.status.text()


def test_saved_consecutive_arc_polyline_fillet_replays_and_undoes(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import math

    from mycad import app
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    source = PolylineEntity(
        uuid4().hex,
        ((5, -5), (10, 0), (15, 5), (20, 0)),
        True,
        bulges=(2**0.5 - 1,) * 4,
    )
    assert editor.canvas.replace_draft_entities((source,))
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    before = loaded.document.commands
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    first = polyline_curve_segments(source.points_mm, source.bulges, True, source.entity_id)[0]
    assert isinstance(first, ArcEntity)
    angle = math.radians(first.start_angle_deg + first.sweep_angle_deg / 2)
    point = (
        first.center_mm[0] + first.radius_mm * math.cos(angle),
        first.center_mm[1] + first.radius_mm * math.sin(angle),
    )
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
    )
    qtbot.waitUntil(lambda: loaded.document.commands != before and not unit.is_busy, timeout=10000)
    changed = services.kernel.sketches[0].entities[0]
    assert isinstance(changed, PolylineEntity) and len(changed.bulges) == 8
    path = tmp_path / "consecutive-arcs.mc.json"

    def choose(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: path.exists() and not unit.is_busy)
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not previous and not unit.is_busy)
    assert services.kernel.sketches[0].entities == (changed,)
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.sketches[0].entities == (source,) and not unit.is_busy)
    window.request_redo()
    qtbot.waitUntil(lambda: services.kernel.sketches[0].entities == (changed,) and not unit.is_busy)


def test_saved_polyline_fillet_survives_save_and_reopen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.core.sketch import PolylineEntity
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True)
    assert editor.canvas.replace_draft_entities((polyline,))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1", "T", "N", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    arcs = tuple(editor.canvas.entities)
    assert len(arcs) == 4 and all(isinstance(arc, ArcEntity) for arc in arcs)
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    path = tmp_path / "polyline-fillet.mc.json"

    def choose_file(*_args: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose_file)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose_file)
    window.act_save.trigger()
    assert path.is_file()
    window.act_open.trigger()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not submitted and not unit.is_busy)
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    entities = tuple(entity for entity, _layer in reopened.canvas.background_entities)
    assert polyline in entities and all(arc in entities for arc in arcs)


def test_fillet_waits_for_trim_option_before_selecting(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "T"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8.0, 0.0)))
    assert not canvas.selected_entity_ids
    assert "修剪" in canvas.message
    command.setText("N")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8.0, 0.0)))
    assert line.entity_id in canvas.selected_entity_ids


def test_fillet_no_trim_line_arc_keeps_both_sources(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (-20.0, 0.0), (20.0, 0.0))
    source_arc = ArcEntity(uuid4().hex, (0.0, 5.0), 2.0, 180.0, 90.0)
    assert canvas.replace_draft_entities((line, source_arc))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((-3.0, 0.0), (-1.3, 3.5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities[:2] == [line, source_arc]
    assert len(canvas.entities) == 3 and isinstance(canvas.entities[2], ArcEntity)
    assert len([relation for relation in canvas.constraints if relation.kind == "tangent"]) == 2


def test_fillet_zero_radius_creates_one_undoable_corner(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (15.0, 5.0), (15.0, 20.0))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((5.0, 0.0), (15.0, 10.0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 2
    a, b = canvas.entities
    assert isinstance(a, LineEntity) and isinstance(b, LineEntity)
    assert a.end_mm == pytest.approx((15.0, 0.0))
    assert b.start_mm == pytest.approx((15.0, 0.0))
    assert canvas.undo_last_operation() and canvas.entities == [first, second]


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("notrim", [False, True])
def test_fillet_two_selected_polyline_segments(qtbot: QtBot, reverse: bool, notrim: bool) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    values = ("FILLET", "R", "2", *(("T", "N") if notrim else ()))
    for value in values:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    picks = ((5, 0), (10, 5))
    for point in reversed(picks) if reverse else picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if notrim:
        assert canvas.entities[0] == source and len(canvas.entities) == 2, canvas.message
        assert isinstance(canvas.entities[1], ArcEntity)
    else:
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity)
        assert canvas.entities[0].points_mm[1] == pytest.approx((8, 0)), canvas.message
        assert canvas.entities[0].points_mm[2] == pytest.approx((10, 2))
    assert canvas.undo_last_operation() and canvas.entities == [source]


@pytest.mark.parametrize("polyline_first", [False, True])
@pytest.mark.parametrize("auto_inference", [False, True])
def test_notrim_fillet_polyline_segment_and_line(
    qtbot: QtBot, polyline_first: bool, auto_inference: bool
) -> None:
    from mycad.core.sketch import LineEntity, PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (15, 0)))
    line = LineEntity(uuid4().hex, (10, 0), (10, 10))
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(auto_inference)
    assert canvas.replace_draft_entities((polyline, line))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    picks = ((5, 0), (10, 8))
    for point in picks if polyline_first else reversed(picks):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities[:2] == [polyline, line] and len(canvas.entities) == 3, canvas.message
    arc = canvas.entities[2]
    assert isinstance(arc, ArcEntity) and arc.radius_mm == pytest.approx(2)
    tangent = tuple(item for item in canvas.constraints if item.kind == "tangent")
    assert len(tangent) == (2 if auto_inference else 0)
    if auto_inference:
        assert any(
            ref.entity_id == polyline.entity_id and ref.kind == "segment" and ref.index == 0
            for constraint in tangent
            for ref in constraint.references
        )
    assert canvas.undo_last_operation() and canvas.entities == [polyline, line]


@pytest.mark.parametrize("polyline_first", [False, True])
@pytest.mark.parametrize("radius", [0, 2])
def test_trim_fillet_polyline_segment_and_line_joins_path(
    qtbot: QtBot, polyline_first: bool, radius: int
) -> None:
    from mycad.core.sketch import LineEntity, PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -5)))
    line = LineEntity(uuid4().hex, (10, 0), (10, 10))
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((polyline, line))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", str(radius)):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    picks = ((5, 0), (10, 8))
    for point in picks if polyline_first else reversed(picks):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 1, canvas.message
    result = canvas.entities[0]
    assert isinstance(result, PolylineEntity) and result.entity_id == polyline.entity_id
    assert result.points_mm[0] == (0, 0) and result.points_mm[-1] == (10, 10)
    if radius:
        assert result.points_mm[1] == pytest.approx((8, 0))
        assert result.points_mm[2] == pytest.approx((10, 2))
    else:
        assert result.points_mm[1] == pytest.approx((10, 0)) and not result.bulges
    assert not canvas.constraints
    assert canvas.undo_last_operation() and canvas.entities == [polyline, line]


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("radius", [0, 2])
def test_trim_fillet_two_polyline_segments_joins_paths(
    qtbot: QtBot, reverse: bool, radius: int
) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    first = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -5)))
    second = PolylineEntity(uuid4().hex, ((10, 0), (10, 10), (15, 10)))
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", str(radius)):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    picks = ((5, 0), (10, 8))
    for point in reversed(picks) if reverse else picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 1, canvas.message
    result = canvas.entities[0]
    assert isinstance(result, PolylineEntity)
    assert result.entity_id == (second.entity_id if reverse else first.entity_id)
    points = tuple(reversed(result.points_mm)) if reverse else result.points_mm
    assert points[0] == (0, 0) and points[-2:] == ((10, 10), (15, 10))
    if radius:
        assert points[1] == pytest.approx((8, 0)) and points[2] == pytest.approx((10, 2))
    else:
        assert points[1] == pytest.approx((10, 0)) and not result.bulges
    assert not canvas.constraints
    assert canvas.undo_last_operation() and canvas.entities == [first, second]


@pytest.mark.parametrize("mode", ["same_sketch", "separate", "first_saved", "second_saved"])
def test_trim_two_polylines_saved_and_mixed_replay(qtbot: QtBot, tmp_path: Path, mode: str) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    first = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -5)))
    second = PolylineEntity(uuid4().hex, ((10, 0), (10, 10), (15, 10)))
    groups = (
        ((first, second),)
        if mode == "same_sketch"
        else ((first,), (second,))
        if mode == "separate"
        else ((first,),)
        if mode == "first_saved"
        else ((second,),)
    )
    for group in groups:
        app.commit_new_sketch(
            services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), group), session_identity=0
        )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    if mode == "first_saved":
        assert canvas.replace_draft_entities((second,))
    elif mode == "second_saved":
        assert canvas.replace_draft_entities((first,))
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    history = tuple(loaded.document.commands)
    for point in ((5, 0), (10, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if mode in ("first_saved", "second_saved"):
        qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
        assert services.kernel.sketches == before
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    else:
        qtbot.waitUntil(
            lambda: tuple(loaded.document.commands) != history and not unit.is_busy, timeout=10000
        )
    after = services.kernel.sketches
    all_entities = tuple(item for sketch in after for item in sketch.entities)
    assert len(all_entities) == 1 and isinstance(all_entities[0], PolylineEntity)
    assert all_entities[0].entity_id == first.entity_id
    assert all_entities[0].points_mm[1] == pytest.approx((8, 0))
    path = tmp_path / f"joined-polylines-{mode}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    undone = tuple(item for sketch in services.kernel.sketches for item in sketch.entities)
    assert first in undone and second in undone
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("kind", ["circle", "arc"])
@pytest.mark.parametrize("polyline_first", [False, True])
@pytest.mark.parametrize("radius", [0, 2])
def test_trim_polyline_segment_and_circular_curve(
    qtbot: QtBot, kind: str, polyline_first: bool, radius: int
) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    if radius:
        polyline = PolylineEntity(uuid4().hex, ((-20, 0), (20, 0), (20, -5)))
        other = (
            CircleEntity(uuid4().hex, (0, 5), 2)
            if kind == "circle"
            else ArcEntity(uuid4().hex, (0, 5), 2, 180, 180)
        )
        picks = ((-3, 0), (-1.3, 3.5))
    else:
        polyline = PolylineEntity(uuid4().hex, ((-10, 0), (0, 0), (0, -5)))
        other = (
            CircleEntity(uuid4().hex, (0, 0), 5)
            if kind == "circle"
            else ArcEntity(uuid4().hex, (0, 0), 5, 90, 180)
        )
        picks = ((-9, 0), (-3.54, 3.54))
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((polyline, other))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", str(radius)):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks if polyline_first else reversed(picks):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == (3 if radius else 2), canvas.message
    result = canvas.entities[0]
    assert isinstance(result, PolylineEntity) and result.entity_id == polyline.entity_id
    assert len(result.points_mm) == 2 and result.points_mm[0] == polyline.points_mm[0]
    if radius:
        assert isinstance(canvas.entities[2], ArcEntity)
        relations = tuple(item for item in canvas.constraints if item.kind == "tangent")
        assert len(relations) == 2
        assert any(
            ref.kind == "segment" and ref.entity_id == polyline.entity_id
            for c in relations
            for ref in c.references
        )
    else:
        assert result.points_mm[-1] == pytest.approx((-5, 0))
        assert not canvas.constraints
    if kind == "circle":
        assert canvas.entities[1] == other
    else:
        assert isinstance(canvas.entities[1], ArcEntity) and canvas.entities[1] != other
    assert canvas.undo_last_operation() and canvas.entities == [polyline, other]


def test_zero_radius_polyline_circle_existing_corner_finishes_without_history(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    polyline = PolylineEntity(uuid4().hex, ((-10, 0), (-5, 0)))
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((polyline, circle))
    position = canvas.history_position
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((-9, 0), (-3.54, 3.54)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities == [polyline, circle] and canvas.history_position == position
    assert canvas.tool == "选择元素" and "无需更改" in canvas.message


@pytest.mark.parametrize("kind", ["circle", "arc"])
@pytest.mark.parametrize("mode", ["both_saved", "polyline_saved", "circular_saved"])
def test_trim_polyline_circular_fillet_saved_sources_and_tangency_replay(
    qtbot: QtBot, tmp_path: Path, kind: str, mode: str
) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    polyline = PolylineEntity(uuid4().hex, ((-20, 0), (20, 0), (20, -5)))
    circular = (
        CircleEntity(uuid4().hex, (0, 5), 2)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (0, 5), 2, 180, 180)
    )
    saved = (
        (polyline, circular)
        if mode == "both_saved"
        else (polyline,)
        if mode == "polyline_saved"
        else (circular,)
    )
    for entity in saved:
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)),
            session_identity=0,
        )
    editor.set_context_sketches(services.kernel.sketches)
    before = services.kernel.sketches
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    if mode == "polyline_saved":
        assert canvas.replace_draft_entities((circular,))
    elif mode == "circular_saved":
        assert canvas.replace_draft_entities((polyline,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((-3, 0), (-1.3, 3.5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    mixed = mode != "circular_saved" or kind == "arc"
    if mixed:
        qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    else:
        assert len(canvas.entities) == 2 and canvas.pending_cross_tangencies, canvas.message
    assert services.kernel.sketches == before
    editor.finish_button.click()
    try:
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    except QtTimeoutError:
        pytest.fail(f"完成草图失败：{editor.status_label.text()}；{canvas.message}")
    after = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == (2 if mode == "both_saved" else 1)
    for relation in relations:
        validate_tangency_component(after, relations, relation.first.sketch_id)
    poly_result = next(
        item for sketch in after for item in sketch.entities if item.entity_id == polyline.entity_id
    )
    assert isinstance(poly_result, PolylineEntity) and len(poly_result.points_mm) == 2
    path = tmp_path / f"polyline-{kind}-{mode}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    if mixed:
        undone = tuple(item for sketch in services.kernel.sketches for item in sketch.entities)
        assert polyline in undone and circular in undone
    else:
        assert services.kernel.sketches == before
    assert not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    if kind == "circle" and mode == "both_saved":
        from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

        circle_owner = next(
            sketch
            for sketch in after
            if any(item.entity_id == circular.entity_id for item in sketch.entities)
        )
        dimension = SketchConstraint(
            uuid4().hex,
            "radius",
            (SketchGeometryReference(circular.entity_id, "geometry"),),
            2.5,
            "mm",
        )
        assert all(relation.second_endpoint is not None for relation in relations)
        assert sum(relation.first_endpoint is not None for relation in relations) == 1
        app.commit_cross_sketch_dimension(
            services, reopened, circle_owner.sketch_id, dimension, session_identity=0
        )
        linked = services.kernel.sketches
        validate_tangency_component(linked, relations, circle_owner.sketch_id)
        updated_circle = next(
            item
            for sketch in linked
            for item in sketch.entities
            if item.entity_id == circular.entity_id
        )
        assert isinstance(
            updated_circle, CircleEntity
        ) and updated_circle.radius_mm == pytest.approx(2.5)
        linked_polyline = next(
            item
            for sketch in linked
            for item in sketch.entities
            if item.entity_id == polyline.entity_id
        )
        linked_arc = next(
            item for sketch in linked for item in sketch.entities if isinstance(item, ArcEntity)
        )
        assert isinstance(linked_polyline, PolylineEntity)
        angle = math.radians(linked_arc.start_angle_deg)
        assert linked_polyline.points_mm[-1] == pytest.approx(
            (
                linked_arc.center_mm[0] + linked_arc.radius_mm * math.cos(angle),
                linked_arc.center_mm[1] + linked_arc.radius_mm * math.sin(angle),
            )
        )
        reopened.bus.undo()
        assert services.kernel.sketches == after
        reopened.bus.redo()
        assert services.kernel.sketches == linked
        save_document(reopened.document, path)
        app.open_app_document(services, path)
        assert services.kernel.sketches == linked
        assert services.kernel.cross_sketch_tangencies == relations
        validate_tangency_component(linked, relations, circle_owner.sketch_id)


def test_polyline_line_fillet_shift_overrides_notrim_temporarily(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity, PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -5)))
    line = LineEntity(uuid4().hex, (10, 0), (10, 10))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((polyline, line))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.local_to_screen((10, 8)),
    )
    assert len(canvas.entities) == 1, canvas.message
    joined = canvas.entities[0]
    assert isinstance(joined, PolylineEntity) and not joined.bulges
    assert joined.points_mm[1] == pytest.approx((10, 0))
    assert canvas.circle_fillet_radius == 2 and not canvas.circle_fillet_trim
    assert canvas.undo_last_operation() and canvas.entities == [polyline, line]


@pytest.mark.parametrize("mode", ["same_sketch", "separate", "polyline_saved", "line_saved"])
def test_trim_polyline_and_line_fillet_saved_and_mixed_replay(
    qtbot: QtBot, tmp_path: Path, mode: str
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -5)))
    line = LineEntity(uuid4().hex, (10, 0), (10, 10))
    if mode == "same_sketch":
        saved_groups = ((polyline, line),)
    elif mode == "separate":
        saved_groups = ((polyline,), (line,))
    elif mode == "polyline_saved":
        saved_groups = ((polyline,),)
    else:
        saved_groups = ((line,),)
    for group in saved_groups:
        app.commit_new_sketch(
            services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), group), session_identity=0
        )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    if mode == "polyline_saved":
        assert canvas.replace_draft_entities((line,))
    elif mode == "line_saved":
        assert canvas.replace_draft_entities((polyline,))
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    history = tuple(loaded.document.commands)
    for point in ((5, 0), (10, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if mode in ("polyline_saved", "line_saved"):
        qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
        assert services.kernel.sketches == before and tuple(loaded.document.commands) == history
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    else:
        qtbot.waitUntil(
            lambda: tuple(loaded.document.commands) != history and not unit.is_busy, timeout=10000
        )
    after = services.kernel.sketches
    all_entities = tuple(item for sketch in after for item in sketch.entities)
    assert len(all_entities) == 1 and isinstance(all_entities[0], PolylineEntity)
    assert all_entities[0].entity_id == polyline.entity_id
    assert all_entities[0].points_mm[1] == pytest.approx((8, 0))
    assert not services.kernel.cross_sketch_tangencies
    path = tmp_path / f"joined-{mode}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    undone = tuple(item for sketch in services.kernel.sketches for item in sketch.entities)
    assert polyline in undone and line in undone
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("constrained", ["line", "polyline"])
def test_trim_polyline_line_fillet_rejects_user_constraint(qtbot: QtBot, constrained: str) -> None:
    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -5)))
    line = LineEntity(uuid4().hex, (10, 0), (10, 10))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((polyline, line))
    ref = (
        SketchGeometryReference(line.entity_id, "start")
        if constrained == "line"
        else SketchGeometryReference(polyline.entity_id, "vertex", 0)
    )
    relation = SketchConstraint(uuid4().hex, "fixed", (ref,))
    canvas.constraints = [relation]
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((5, 0), (10, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities == [polyline, line] and canvas.constraints == [relation]
    assert "约束" in canvas.message


@pytest.mark.parametrize("locked_source", ["polyline", "line"])
def test_trim_polyline_line_fillet_rejects_locked_source(qtbot: QtBot, locked_source: str) -> None:
    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.core.sketch_layers import SketchLayer

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    layers = editor.layer_table.add(SketchLayer("locked", locked=True))
    editor.layer_table = layers
    canvas.layer_table = layers
    polyline = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, -5)),
        layer_name="locked" if locked_source == "polyline" else "0",
    )
    line = LineEntity(
        uuid4().hex, (10, 0), (10, 10), layer_name="locked" if locked_source == "line" else "0"
    )
    assert canvas.replace_draft_entities((polyline, line))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((5, 0), (10, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities == [polyline, line] and "锁定" in canvas.message


def test_trim_polyline_line_fillet_rejects_existing_cross_sketch_tangency(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -5)))
    line = LineEntity(uuid4().hex, (10, 0), (10, 10))
    circle = CircleEntity(uuid4().hex, (12, 5), 2)
    sketches = tuple(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (item,)) for item in (polyline, line, circle)
    )
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketches[1].sketch_id, line.entity_id),
        CrossSketchRef(sketches[2].sketch_id, circle.entity_id),
        "line_right",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    history = tuple(loaded.document.commands)
    for point in ((5, 0), (10, 8)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(lambda: "失败" in editor.status_label.text(), timeout=10000)
    assert not unit.is_busy
    assert services.kernel.sketches == before and tuple(loaded.document.commands) == history
    assert services.kernel.cross_sketch_tangencies == (relation,)


@pytest.mark.parametrize("kind", ["circle", "arc", "polyline"])
@pytest.mark.parametrize("polyline_first", [False, True])
def test_notrim_fillet_polyline_segment_and_other_curves(
    qtbot: QtBot, kind: str, polyline_first: bool
) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    polyline = PolylineEntity(uuid4().hex, ((-20, 0), (20, 0), (25, 0)))
    other = (
        PolylineEntity(uuid4().hex, ((10, 0), (10, 10), (10, 15)))
        if kind == "polyline"
        else CircleEntity(uuid4().hex, (0, 5), 2)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (0, 5), 2, 180, 180)
    )
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((polyline, other))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    picks = ((-3, 0), (10, 8)) if kind == "polyline" else ((-3, 0), (-1.3, 3.5))
    for point in picks if polyline_first else reversed(picks):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities[:2] == [polyline, other] and len(canvas.entities) == 3, canvas.message
    arc = canvas.entities[2]
    assert isinstance(arc, ArcEntity) and arc.radius_mm == pytest.approx(2)
    tangent = tuple(item for item in canvas.constraints if item.kind == "tangent")
    assert len(tangent) == 2
    assert sum(ref.kind == "segment" for c in tangent for ref in c.references) == (
        2 if kind == "polyline" else 1
    )
    assert canvas.undo_last_operation() and canvas.entities == [polyline, other]


def test_notrim_polyline_fillet_infers_endpoint_coincidence(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity, PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (8, 0), (12, 0)))
    line = LineEntity(uuid4().hex, (10, 2), (10, 10))
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((polyline, line))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((4, 0), (10, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 3, canvas.message
    relations = [item for item in canvas.constraints if item.kind == "coincident"]
    assert len(relations) == 2
    assert any(
        ref.entity_id == polyline.entity_id and ref.kind == "vertex" and ref.index == 1
        for relation in relations
        for ref in relation.references
    )
    assert any(
        ref.entity_id == line.entity_id and ref.kind == "start"
        for relation in relations
        for ref in relation.references
    )


def test_notrim_two_polyline_segments_inference_saves_and_replays(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    first = PolylineEntity(uuid4().hex, ((0, 0), (8, 0), (12, 0)))
    second = PolylineEntity(uuid4().hex, ((10, 2), (10, 10), (15, 10)))
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((4, 0), (10, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 3, canvas.message
    assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
    assert len([item for item in canvas.constraints if item.kind == "coincident"]) == 2
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    after = services.kernel.sketches
    assert len(after) == 1 and len(after[0].constraints) == 4
    path = tmp_path / "notrim-segment-inference.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert not services.kernel.sketches
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_notrim_fillet_saved_polyline_segment_retains_cross_sketch_tangency(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        tangent_endpoints_satisfied,
        validate_tangency_component,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (15, 0)))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    before = services.kernel.sketches
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    line = LineEntity(uuid4().hex, (10, 0), (10, 10))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((5, 0), (10, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 2 and len(canvas.pending_cross_tangencies) == 1, canvas.message
    source_ref, _ = canvas.pending_cross_tangencies[0]
    assert source_ref == SketchGeometryReference(polyline.entity_id, "segment", 0)
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    after = services.kernel.sketches
    assert len(services.kernel.cross_sketch_tangencies) == 1
    assert after[0].entities == (polyline,)
    path = tmp_path / "polyline-external-fillet.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after and len(services.kernel.cross_sketch_tangencies) == 1
    reopened.bus.undo()
    assert services.kernel.sketches == before and not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert services.kernel.sketches == after and len(services.kernel.cross_sketch_tangencies) == 1
    relation = services.kernel.cross_sketch_tangencies[0]
    assert relation.first_endpoint is None and relation.second_endpoint in ("start", "end")
    moved = replace(polyline, points_mm=tuple((x, y + 1) for x, y in polyline.points_mm))
    proposed = tuple(
        replace(sketch, entities=(moved,)) if sketch.sketch_id == after[0].sketch_id else sketch
        for sketch in after
    )
    app.commit_cross_sketch_edit(
        services,
        reopened,
        after,
        proposed,
        (CrossSketchRef(after[0].sketch_id, polyline.entity_id, 0),),
        session_identity=0,
    )
    changed = services.kernel.sketches
    validate_tangency_component(changed, (relation,), after[0].sketch_id)
    arc = next(
        entity for sketch in changed for entity in sketch.entities if isinstance(entity, ArcEntity)
    )
    source_line = LineEntity(uuid4().hex, moved.points_mm[0], moved.points_mm[1])
    assert tangent_endpoints_satisfied(source_line, arc, None, relation.second_endpoint)
    assert arc != next(
        entity for sketch in after for entity in sketch.entities if isinstance(entity, ArcEntity)
    )
    reopened.bus.undo()
    assert services.kernel.sketches == after
    reopened.bus.redo()
    assert services.kernel.sketches == changed
    moved_path = tmp_path / "polyline-interior-contact-moved.my2d"
    save_document(reopened.document, moved_path)
    restored = app.build_app(discoverers=[])
    app.open_app_document(restored, moved_path)
    assert restored.kernel.sketches == changed
    assert restored.kernel.cross_sketch_tangencies == (relation,)


@pytest.mark.parametrize("radius", [0.0, 1.0])
def test_fillet_selected_polyline_segments_replace_intervening_arc(
    qtbot: QtBot, radius: float
) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(
        uuid4().hex,
        ((0, 0), (8, 0), (10, 2), (10, 10), (20, 10)),
        bulges=(0, 2**0.5 - 1, 0, 0),
    )
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", str(radius)):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((4, 0), (10, 6)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    result = canvas.entities[0]
    assert isinstance(result, PolylineEntity) and result != source, canvas.message
    if radius:
        assert result.points_mm[1] == pytest.approx((9, 0))
        assert result.points_mm[2] == pytest.approx((10, 1))
    else:
        assert result.points_mm[1] == pytest.approx((10, 0))
        assert not any(result.bulges)
    assert result.points_mm[-2:] == ((10, 10), (20, 10))
    assert canvas.undo_last_operation() and canvas.entities == [source]


@pytest.mark.parametrize("temporary_zero", [False, True])
def test_selected_existing_polyline_fillet_noop_or_shift_remove(
    qtbot: QtBot, temporary_zero: bool
) -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    initial = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    points, bulges = polyline_fillet_trimmed_segments(initial, 2)
    source = PolylineEntity(initial.entity_id, points, bulges=bulges)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    position = canvas.history_position
    command = editor.drawing_command_bar.input
    values = ("FILLET", "R", "2", *(("T", "N") if temporary_zero else ()))
    for value in values:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((4, 0)))
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier if temporary_zero else Qt.KeyboardModifier.NoModifier,
        pos=canvas.local_to_screen((10, 6)),
    )
    if temporary_zero:
        result = canvas.entities[0]
        assert isinstance(result, PolylineEntity) and not result.bulges
        assert result.points_mm[1] == pytest.approx((10, 0))
        assert canvas.undo_last_operation() and canvas.entities == [source]
        assert not canvas.circle_fillet_trim
    else:
        assert canvas.entities == [source] and canvas.history_position == position
        assert "无需更改" in canvas.message


@pytest.mark.parametrize("notrim", [False, True])
def test_whole_polyline_fillet_shift_removes_old_rounds_temporarily(
    qtbot: QtBot, notrim: bool
) -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    initial = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    points, bulges = polyline_fillet_trimmed_segments(initial, 2)
    source = PolylineEntity(initial.entity_id, points, bulges=bulges)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    values = ("FILLET", "R", "1", *(("T", "N") if notrim else ()), "P")
    for value in values:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.local_to_screen((4, 0)),
    )
    result = canvas.entities[0]
    assert isinstance(result, PolylineEntity) and not result.bulges, canvas.message
    assert result.points_mm[1] == pytest.approx((10, 0))
    assert canvas.circle_fillet_radius == 1 and canvas.circle_fillet_trim is (not notrim)
    assert canvas.undo_last_operation() and canvas.entities == [source]


@pytest.mark.parametrize("kind", ["tangent", "non_tangent", "mixed"])
def test_saved_whole_polyline_shift_removal_replays(
    qtbot: QtBot, tmp_path: Path, kind: str
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    initial = (
        PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (5, 5)), bulges=(0, 2**0.5 - 1))
        if kind == "mixed"
        else PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    )
    points, bulges = polyline_fillet_trimmed_segments(initial, 1 if kind == "mixed" else 2)
    source = (
        PolylineEntity(initial.entity_id, ((0, 0), (8, 0), (10, 2), (10, 10)), bulges=(0, 0.2, 0))
        if kind == "non_tangent"
        else PolylineEntity(initial.entity_id, points, bulges=bulges)
    )
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    before, commands = services.kernel.sketches, loaded.document.commands
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1", "T", "N", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=editor.canvas.local_to_screen((4, 0)),
    )
    qtbot.waitUntil(
        lambda: loaded.document.commands != commands and not unit.is_busy, timeout=10000
    )
    after = services.kernel.sketches
    result = after[0].entities[0]
    assert isinstance(result, PolylineEntity)
    if kind == "mixed":
        assert result.bulges == pytest.approx(initial.bulges)
        for actual, expected in zip(result.points_mm, initial.points_mm, strict=True):
            assert actual == pytest.approx(expected)
    else:
        assert not result.bulges and result.points_mm == ((0, 0), (10, 0), (10, 10))
    assert editor.canvas.circle_fillet_radius == 1 and not editor.canvas.circle_fillet_trim
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after
    path = tmp_path / "whole-shift.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == before
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_fillet_selected_closed_polyline_segments_wrap_start(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((0, 5), (5, 0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    result = canvas.entities[0]
    assert isinstance(result, PolylineEntity) and result.closed and len(result.points_mm) == 5
    assert sum(value != 0 for value in result.bulges) == 1
    assert canvas.undo_last_operation() and canvas.entities == [source]


@pytest.mark.parametrize("radius", [0, 2])
def test_fillet_open_polyline_end_segments_closes_path(qtbot: QtBot, radius: int) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10), (0, 3)))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", str(radius)):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((5, 0), (0, 6)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    result = canvas.entities[0]
    assert isinstance(result, PolylineEntity) and result.closed, canvas.message
    assert result.points_mm[1:4] == ((10, 0), (10, 10), (0, 10))
    assert canvas.undo_last_operation() and canvas.entities == [source]


@pytest.mark.parametrize("middle_arc", [False, True])
def test_fillet_open_polyline_uses_picks_to_close_near_ends(qtbot: QtBot, middle_arc: bool) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = (
        PolylineEntity(
            uuid4().hex,
            ((0, 0), (8, 0), (10, 2), (10, 10)),
            bulges=(0, 2**0.5 - 1, 0),
        )
        if middle_arc
        else PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    )
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "5" if middle_arc else "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((1, 0), (10, 9)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    result = canvas.entities[0]
    assert isinstance(result, PolylineEntity) and result.closed, canvas.message
    if middle_arc:
        assert result.bulges[1] == source.bulges[1]
    else:
        assert result.points_mm[1] == (10, 0)
    assert canvas.undo_last_operation() and canvas.entities == [source]


@pytest.mark.parametrize("notrim", [False, True])
def test_fillet_parallel_open_polyline_end_segments(qtbot: QtBot, notrim: bool) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    values = ("FILLET", "R", "0", *(("T", "N") if notrim else ()))
    for value in values:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((5, 0), (5, 10)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if notrim:
        assert canvas.entities[0] == source and len(canvas.entities) == 2, canvas.message
        arc = canvas.entities[1]
        assert isinstance(arc, ArcEntity) and arc.radius_mm == pytest.approx(5)
    else:
        result = canvas.entities[0]
        assert isinstance(result, PolylineEntity) and result.closed, canvas.message
        assert abs(result.bulges[-1]) == pytest.approx(1)
    assert canvas.undo_last_operation() and canvas.entities == [source]


def test_fillet_selected_polyline_multiple_and_command_undo(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "M", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((5, 0), (10, 5), (10, 7), (15, 10)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    rounded = canvas.entities[0]
    assert isinstance(rounded, PolylineEntity) and len(rounded.points_mm) == 6, canvas.message
    assert canvas.tool == "二维圆角"
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    once = canvas.entities[0]
    assert isinstance(once, PolylineEntity) and len(once.points_mm) == 5
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [source]


@pytest.mark.parametrize("closing", [False, True])
def test_saved_selected_polyline_segment_fillet_replays_and_reopens(
    qtbot: QtBot, tmp_path: Path, closing: bool
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    points = (
        ((0, 0), (10, 0), (10, 10), (0, 10), (0, 3))
        if closing
        else ((0, 0), (10, 0), (10, 10), (20, 10))
    )
    source = PolylineEntity(uuid4().hex, points)
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    before, commands = services.kernel.sketches, loaded.document.commands
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    commands = loaded.document.commands
    for point in ((5, 0), (0, 6) if closing else (10, 5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(
        lambda: loaded.document.commands != commands and not unit.is_busy, timeout=10000
    )
    after = services.kernel.sketches
    result = after[0].entities[0]
    assert isinstance(result, PolylineEntity) and result.closed is closing
    if closing:
        assert result.points_mm[0] == pytest.approx((2, 0))
    else:
        assert result.points_mm[1] == pytest.approx((8, 0))
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after
    path = tmp_path / "selected-polyline.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == before
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_selected_polyline_segments_reject_existing_user_constraint(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(source.entity_id, "vertex", 1),)
    )
    canvas.constraints = [constraint]
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((5, 0), (10, 5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities == [source] and canvas.constraints == [constraint]
    assert "约束" in canvas.message


def test_selected_polyline_segments_reject_source_revision_change(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    revision = [1]
    canvas.source_revision_provider = lambda: revision[0]
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    revision[0] = 2
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 5)))
    assert canvas.entities == [source]
    assert "文档已变化" in canvas.message


def test_selected_polyline_rejects_diverging_arc_neighbours(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (5, 5), (5, 10)), bulges=(0, 0.4, 0))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((7, 0), (5, 6)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities == [source]
    assert "收敛" in canvas.message


def test_saved_polyline_segment_fillet_rejects_linked_topology_change(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    history = tuple(loaded.document.commands)
    for point in ((1, 0), (10, 5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(lambda: "失败" in editor.status_label.text(), timeout=10000)
    assert not unit.is_busy
    assert services.kernel.sketches == before and tuple(loaded.document.commands) == history
    assert services.kernel.cross_sketch_tangencies == (relation,)


@pytest.mark.parametrize(("shift", "notrim"), [(False, False), (True, False), (True, True)])
def test_fillet_zero_radius_line_circle_keeps_circle_and_undoes(
    qtbot: QtBot, shift: bool, notrim: bool
) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (-10, 0), (0, 0))
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    assert canvas.replace_draft_entities((line, circle))
    command = editor.drawing_command_bar.input
    values = ("FILLET", "R", "2" if shift else "0", *(("T", "N") if notrim else ()))
    for value in values:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-9, 0)))
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier,
        pos=canvas.local_to_screen((-3.54, 3.54)),
    )
    assert len(canvas.entities) == 2, canvas.message
    result = canvas.entities[0]
    assert isinstance(result, LineEntity) and result.end_mm == pytest.approx((-5, 0))
    assert canvas.entities[1] == circle and not canvas.constraints
    assert canvas.circle_fillet_trim is (not notrim)
    assert canvas.undo_last_operation() and canvas.entities == [line, circle]


def test_saved_zero_radius_line_circle_commits_and_reopens(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (0, 0))
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    for entity in (line, circle):
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)),
            session_identity=0,
        )
    editor.set_context_sketches(services.kernel.sketches)
    before = services.kernel.sketches
    commands = loaded.document.commands
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    commands = loaded.document.commands
    for point in ((-9, 0), (-3.54, 3.54)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(
        lambda: loaded.document.commands != commands and not unit.is_busy, timeout=10000
    )
    after = services.kernel.sketches
    result = after[0].entities[0]
    assert isinstance(result, LineEntity) and result.end_mm == pytest.approx((-5, 0))
    assert after[1].entities == (circle,)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after
    path = tmp_path / "zero-corner.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == before
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_mixed_zero_radius_line_circle_preserves_atomic_history(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (0, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    assert canvas.replace_draft_entities((circle,))
    before = services.kernel.sketches
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((-9, 0), (-3.54, 3.54)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert services.kernel.sketches == before and canvas.entities == [circle]
    assert canvas.undo_last_operation() and canvas.mixed_move is None
    assert canvas.redo_last_operation() and canvas.mixed_move is not None
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    result = services.kernel.sketches[0].entities[0]
    assert isinstance(result, LineEntity) and result.end_mm == pytest.approx((-5, 0))
    assert services.kernel.sketches[1].entities == (circle,)
    assert not services.kernel.cross_sketch_tangencies
    loaded = window.loaded_document()
    assert loaded is not None
    loaded.bus.undo()
    assert services.kernel.sketches[0] == before[0]
    assert services.kernel.sketches[1].entities == (circle,)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches[0] == before[0]
    assert services.kernel.sketches[1].entities == (circle,)
    loaded.bus.redo()
    assert services.kernel.sketches[1].entities == (circle,)


def test_zero_radius_line_arc_trims_both_and_undoes(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (-10, 0), (0, 0))
    arc = ArcEntity(uuid4().hex, (0, 0), 5, 90, 180)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((line, arc))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((-9, 0), (-3.54, 3.54)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    result_line, result_arc = canvas.entities
    assert isinstance(result_line, LineEntity) and result_line.end_mm == pytest.approx((-5, 0))
    assert isinstance(result_arc, ArcEntity)
    assert result_arc.start_angle_deg == pytest.approx(90)
    assert result_arc.sweep_angle_deg == pytest.approx(90)
    assert not canvas.constraints
    assert canvas.undo_last_operation() and canvas.entities == [line, arc]


def test_zero_radius_curve_notrim_rejects_without_changes(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (-10, 0), (0, 0))
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((line, circle))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((-9, 0), (-3.54, 3.54)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities == [line, circle]
    assert "需要修剪模式" in canvas.message


def test_zero_radius_curve_rejects_edits_to_user_constrained_geometry(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (-10, 0), (0, 0))
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((line, circle))
    relation = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "end"),)
    )
    canvas.constraints = [relation]
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((-9, 0), (-3.54, 3.54)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities == [line, circle] and canvas.constraints == [relation]
    assert "约束" in canvas.message


def test_zero_radius_two_arcs_trims_to_intersection(qtbot: QtBot) -> None:
    import math

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    first = ArcEntity(uuid4().hex, (0, 0), 5, 0, 180)
    second = ArcEntity(uuid4().hex, (6, 0), 5, 0, 180)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((0, 5), (6, 5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    a, b = canvas.entities
    assert isinstance(a, ArcEntity) and isinstance(b, ArcEntity)
    assert a.start_angle_deg == pytest.approx(math.degrees(math.atan2(4, 3)))
    assert b.sweep_angle_deg == pytest.approx(math.degrees(math.atan2(4, -3)))
    assert not canvas.constraints
    assert canvas.undo_last_operation() and canvas.entities == [first, second]


@pytest.mark.parametrize("notrim", [False, True])
def test_fillet_shift_second_pick_makes_corner_without_changing_settings(
    qtbot: QtBot, notrim: bool
) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (15.0, 5.0), (15.0, 20.0))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    values = ("FILLET", "R", "2", "T", "N") if notrim else ("FILLET", "R", "2")
    for value in values:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5.0, 0.0)))
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.local_to_screen((15.0, 10.0)),
    )
    assert len(canvas.entities) == 2
    a, b = canvas.entities
    assert isinstance(a, LineEntity) and isinstance(b, LineEntity)
    assert a.end_mm == pytest.approx((15.0, 0.0))
    assert b.start_mm == pytest.approx((15.0, 0.0))
    assert canvas.circle_fillet_radius == 2
    assert canvas.circle_fillet_trim is (not notrim)
    assert canvas.undo_last_operation() and canvas.entities == [first, second]


def test_fillet_undo_command_reverts_last_fillet(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (0.0, 0.0), (0.0, 10.0))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "M", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8.0, 0.0), (0.0, 8.0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 3
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [first, second]


def test_draft_fillet_tangencies_survive_save_and_reopen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (0.0, 0.0), (0.0, 10.0))
    assert editor.canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8.0, 0.0), (0.0, 8.0)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert len(editor.canvas.constraints) == 4
    path = tmp_path / "fillet-tangent.mc.json"

    def choose(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: path.exists() and not unit.is_busy, timeout=10000)
    loaded = window.loaded_document()
    assert loaded is not None
    assert loaded.document.commands[-1].version == 13
    constraints = services.kernel.sketches[-1].constraints
    assert len(constraints) == 4
    assert all(
        item.first_endpoint and item.second_endpoint
        for item in constraints
        if item.kind == "tangent"
    )
    current = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not current and not unit.is_busy, timeout=10000
    )
    assert services.kernel.sketches[-1].constraints == constraints


@pytest.mark.parametrize("mixed", ["none", "first_saved", "second_saved"])
@pytest.mark.parametrize("case", ["intersect", "disjoint", "parallel"])
@pytest.mark.parametrize("auto_inference", [False, True])
def test_line_fillet_with_saved_sources_replays_and_undoes(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mixed: str,
    case: str,
    auto_inference: bool,
) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    if case == "disjoint":
        second = LineEntity(uuid4().hex, (15.0, 5.0), (15.0, 20.0))
    elif case == "parallel":
        second = LineEntity(uuid4().hex, (-5.0, 4.0), (15.0, 4.0))
    else:
        second = LineEntity(uuid4().hex, (0.0, 0.0), (0.0, 10.0))
    saved = (
        (first,)
        if mixed == "first_saved"
        else (second,)
        if mixed == "second_saved"
        else (first, second)
    )
    assert editor.canvas.replace_draft_entities(saved)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(auto_inference)
    if mixed != "none":
        assert canvas.replace_draft_entities((second if mixed == "first_saved" else first,))
    before = loaded.document.commands
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    before = loaded.document.commands
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8.0, 0.0)))
    second_pick = {"disjoint": (15.0, 10.0), "parallel": (5.0, 4.0)}.get(case, (0.0, 8.0))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(second_pick))
    try:
        qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    except QtTimeoutError as exc:
        raise AssertionError(f"{canvas.message} / {editor.status_label.text()}") from exc
    assert loaded.document.commands == before
    assert canvas.tool == "选择元素"
    assert any(isinstance(entity, ArcEntity) for entity in canvas.entities)
    assert canvas.undo_last_operation()
    assert not any(isinstance(entity, ArcEntity) for entity in canvas.entities)
    assert canvas.redo_last_operation()
    target = tmp_path / "line-fillet.mc.json"

    def choose(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(target), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: target.exists() and not unit.is_busy, timeout=10000)
    current = window.active_sketch_dialog()
    assert current is not None
    after_save = loaded.document.commands
    window.request_undo()
    qtbot.waitUntil(
        lambda: loaded.document.commands != after_save and not unit.is_busy, timeout=10000
    )
    after_undo = tuple(entity for sketch in services.kernel.sketches for entity in sketch.entities)
    assert first in after_undo and second in after_undo
    assert not any(isinstance(entity, ArcEntity) for entity in after_undo)
    window.request_redo()
    qtbot.waitUntil(
        lambda: loaded.document.commands == after_save and not unit.is_busy, timeout=10000
    )
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not current and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    entities = {entity.entity_id: entity for entity, _layer in reopened.canvas.background_entities}
    first_result, second_result = entities[first.entity_id], entities[second.entity_id]
    assert isinstance(first_result, LineEntity) and isinstance(second_result, LineEntity)
    if case == "disjoint":
        assert first_result.end_mm == pytest.approx((13.0, 0.0))
        assert second_result.start_mm == pytest.approx((15.0, 2.0))
    elif case == "parallel":
        assert first_result == first
        assert second_result.end_mm == pytest.approx((10.0, 4.0))
    else:
        assert first_result.start_mm == pytest.approx((2.0, 0.0))
        assert second_result.start_mm == pytest.approx((0.0, 2.0))
    assert any(isinstance(entity, ArcEntity) for entity in entities.values())
    assert len(services.kernel.cross_sketch_tangencies) == (
        (1 if mixed != "none" else 2) if auto_inference else 0
    )


@pytest.mark.parametrize("blocked", ["constraint", "locked", "large-radius"])
def test_line_fillet_rejects_unsafe_changes_without_partial_edit(
    qtbot: QtBot, blocked: str
) -> None:
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    if blocked == "locked":
        layers = editor.layer_table.add(SketchLayer("locked", locked=True))
        editor.layer_table = layers
        canvas.layer_table = layers
    first = LineEntity(
        uuid4().hex, (0.0, 0.0), (10.0, 0.0), layer_name="locked" if blocked == "locked" else "0"
    )
    second = LineEntity(uuid4().hex, (0.0, 0.0), (0.0, 10.0))
    assert canvas.replace_draft_entities((first, second))
    if blocked == "constraint":
        canvas.constraints = [
            SketchConstraint(
                uuid4().hex, "fixed", (SketchGeometryReference(first.entity_id, "start"),)
            )
        ]
    before_constraints = tuple(canvas.constraints)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "20" if blocked == "large-radius" else "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8.0, 0.0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 8.0)))
    assert canvas.entities == [first, second]
    assert tuple(canvas.constraints) == before_constraints
    assert any(word in canvas.message for word in ("约束", "锁定", "半径"))


def test_parallel_fillet_preserves_constraint_on_unchanged_saved_line(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (-5, 4), (15, 4))
    relation = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(first.entity_id, "start"),)
    )
    assert editor.canvas.replace_draft_entities((first,))
    editor.canvas.constraints = [relation]
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    assert canvas.replace_draft_entities((second,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8, 0), (5, 4)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.message != "已保存图元有关联约束；请先处理约束。"
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert services.kernel.sketches[0].constraints == (relation,)
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    assert services.kernel.sketches[0].constraints == (relation,)
    assert len(services.kernel.cross_sketch_tangencies) == 1
    target = tmp_path / "parallel-constrained.mc.json"

    def choose(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(target), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: target.exists() and not unit.is_busy)
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not previous and not unit.is_busy)
    assert services.kernel.sketches[0].constraints == (relation,)
    assert len(services.kernel.cross_sketch_tangencies) == 1


def test_line_fillet_refuses_document_change_between_picks(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (0.0, 0.0), (0.0, 10.0))
    assert editor.canvas.replace_draft_entities((first, second))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    before = loaded.document.commands
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    before = loaded.document.commands
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8.0, 0.0)))
    assert canvas.has_active_edit_gesture
    loaded.document.set_metadata("notes", "changed while selecting")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 8.0)))
    assert "文档已变化" in canvas.message
    assert loaded.document.commands == before and not canvas.entities
    assert canvas.mixed_move is None


def test_line_fillet_save_failure_keeps_mixed_draft_and_redo_then_retries(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui import document_save
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    session = DocumentSession()
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    entry = window.new_session_document("sketch")
    target = tmp_path / "line-fillet.my2d"
    entry.path = target
    first = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    second = LineEntity(uuid4().hex, (0.0, 0.0), (0.0, 10.0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    entry.loaded.bus.execute("sketch.create", saved.to_state_mapping(), "local")
    before = entry.loaded.document.commands
    editor, unit, saver = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.document_saver,
    )
    assert editor is not None and unit is not None and saver is not None
    editor.set_context_sketches(entry.services.kernel.sketches)
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    before = entry.loaded.document.commands
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((8.0, 0.0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 8.0)))
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    extra = LineEntity(uuid4().hex, (20.0, 0.0), (25.0, 0.0))
    assert canvas.replace_draft_entities((*canvas.entities, extra))
    assert canvas.undo_last_operation() and canvas.can_redo
    original_save = document_save.save_document

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(document_save, "save_document", fail)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    assert saver.last_results[-1].status == "failed" and not target.exists()
    assert window.active_sketch_dialog() is editor and entry.loaded.document.commands == before
    assert canvas.mixed_move is not None and canvas.mixed_move_is_valid and canvas.can_redo
    assert canvas.redo_last_operation() and extra in canvas.entities
    assert canvas.undo_last_operation() and extra not in canvas.entities
    monkeypatch.setattr(document_save, "save_document", original_save)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    assert saver.last_results[-1].status == "saved" and target.is_file()
    services = app.fork_app_services(entry.services)
    reopened = app.open_app_document(services, target)
    assert reopened.document.document_kind == "sketch"
    assert any(
        isinstance(entity, ArcEntity)
        for sketch in services.kernel.sketches
        for entity in sketch.entities
    )


def test_local_fillet_radius_dimension_remains_connected_after_save(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (-20, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((line, circle))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((-3, 0), (-1.3, 3.5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    relations = tuple(item for item in canvas.constraints if item.kind == "tangent")
    assert len(relations) == 2
    assert all(item.second_endpoint is not None for item in relations)
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    source = services.kernel.sketches[0]
    assert loaded.document.commands[-1].version == 13
    new_editor = window.active_sketch_dialog()
    assert new_editor is not None
    new_editor.dimensions.driving_check.setChecked(True)
    new_editor.dimensions.buttons["radius"].click()
    QTest.mouseClick(
        new_editor.canvas, Qt.MouseButton.LeftButton, pos=new_editor.canvas.local_to_screen((0, 7))
    )
    QTest.mouseClick(
        new_editor.canvas, Qt.MouseButton.LeftButton, pos=new_editor.canvas.local_to_screen((8, 8))
    )
    new_editor.dimensions.value_editor.setValue(2.5)
    dimension = new_editor.dimensions.candidate
    assert dimension is not None
    qtbot.waitUntil(
        lambda: new_editor.dimensions.accepted_preview(source, dimension) is not None, timeout=15000
    )
    preview = new_editor.dimensions.accepted_preview(source, dimension)
    assert preview is not None and preview.status == "success", new_editor.status_label.text()
    new_editor.dimensions.apply_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    after = services.kernel.sketches
    updated_circle = next(
        item for sketch in after for item in sketch.entities if item.entity_id == circle.entity_id
    )
    assert isinstance(updated_circle, CircleEntity) and updated_circle.radius_mm == pytest.approx(
        2.5
    )
    loaded.bus.undo()
    assert services.kernel.sketches == (source,)
    loaded.bus.redo()
    assert services.kernel.sketches == after
    path = tmp_path / "local-fillet-dimension.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.sketches == after


def test_local_fillet_cross_sketch_radius_dimension_preview(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint
    from mycad.core.sketch_constraints import SketchGeometryReference as Ref
    from mycad.ui.main_window import MainWindow

    x = -math.sqrt(7)
    line = LineEntity(uuid4().hex, (-20, 0), (x, 0))
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    arc = ArcEntity(uuid4().hex, (x, 2), 2, -90, 138.59037789072914)
    other = CircleEntity(uuid4().hex, (4, 5), 2)
    local = (
        SketchConstraint(
            uuid4().hex,
            "tangent",
            (Ref(line.entity_id, "geometry"), Ref(arc.entity_id, "geometry")),
            source="inferred",
            first_endpoint="end",
            second_endpoint="start",
        ),
        SketchConstraint(
            uuid4().hex,
            "tangent",
            (Ref(circle.entity_id, "geometry"), Ref(arc.entity_id, "geometry")),
            source="inferred",
            second_endpoint="end",
        ),
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle, arc), local)
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other,))
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, circle.entity_id),
        CrossSketchRef(second.sketch_id, other.entity_id),
        "external",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    source = next(item for item in services.kernel.sketches if item.sketch_id == first.sketch_id)
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["radius"].click()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 7))
    )
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((-8, 8))
    )
    editor.dimensions.value_editor.setValue(2.5)
    dimension = editor.dimensions.candidate
    assert dimension is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(source, dimension) is not None, timeout=15000
    )
    preview = editor.dimensions.accepted_preview(source, dimension)
    assert preview is not None and preview.status == "success", editor.status_label.text()
    editor.dimensions.apply_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert loaded.document.commands[-1].version == 9
    updated = next(item for item in services.kernel.sketches if item.sketch_id == first.sketch_id)
    updated_circle = next(item for item in updated.entities if item.entity_id == circle.entity_id)
    assert isinstance(updated_circle, CircleEntity)
    assert updated_circle.radius_mm == pytest.approx(2.5)


@pytest.mark.parametrize("trim", [False, True])
@pytest.mark.parametrize("reverse_selection", [False, True])
@pytest.mark.parametrize("kind", ["circle", "arc"])
def test_polyline_arc_segment_fillet_with_circular_source(
    qtbot: QtBot, trim: bool, reverse_selection: bool, kind: str
) -> None:
    from mycad.core.cross_sketch_tangency import tangent_entity_curve
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((5, 0), (-5, 0)), bulges=(1,))
    circular = (
        CircleEntity(uuid4().hex, (0, 8), 2)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (0, 8), 2, 180, 180)
    )
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((source, circular))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1") if trim else ("FILLET", "R", "1", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    points = ((3, 4), (0, 6.05))
    if reverse_selection:
        points = tuple(reversed(points))
    for point in points:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 3, canvas.message
    result = next(item for item in canvas.entities if item.entity_id == source.entity_id)
    target = next(item for item in canvas.entities if item.entity_id == circular.entity_id)
    fillet = next(
        item
        for item in canvas.entities
        if item.entity_id not in (source.entity_id, circular.entity_id)
    )
    assert isinstance(result, PolylineEntity) and isinstance(target, CircleEntity | ArcEntity)
    assert isinstance(fillet, ArcEntity)
    assert tangent_on_curves(tangent_entity_curve(result, 0), fillet)
    assert tangent_on_curves(target, fillet)
    assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
    if not trim:
        assert result == source and target == circular
    assert canvas.undo_last_operation()
    assert canvas.entities == [source, circular]
    assert canvas.redo_last_operation()


@pytest.mark.parametrize("kind", ["circle", "arc"])
@pytest.mark.parametrize("trim", [False, True])
def test_saved_polyline_arc_segment_circular_fillet_replays(
    qtbot: QtBot, tmp_path: Path, kind: str, trim: bool
) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = PolylineEntity(uuid4().hex, ((5, 0), (-5, 0)), bulges=(1,))
    circular = (
        CircleEntity(uuid4().hex, (0, 8), 2)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (0, 8), 2, 180, 180)
    )
    for entity in (source, circular):
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)),
            session_identity=0,
        )
    editor.set_context_sketches(services.kernel.sketches)
    before = services.kernel.sketches
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1") if trim else ("FILLET", "R", "1", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((3, 4), (0, 6.05)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim:
        qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    else:
        assert len(canvas.pending_cross_tangencies) == 2, canvas.message
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    after = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == 2
    for relation in relations:
        validate_tangency_component(after, relations, relation.first.sketch_id)
    path = tmp_path / f"polyline-arc-{kind}-{trim}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    if trim:
        restored = {sketch.sketch_id: sketch for sketch in services.kernel.sketches}
        assert all(restored.get(sketch.sketch_id) == sketch for sketch in before)
        assert sum(bool(sketch.entities) for sketch in services.kernel.sketches) == len(before)
    else:
        assert services.kernel.sketches == before
    assert not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    if trim and kind == "circle":
        from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

        owner = next(
            sketch
            for sketch in after
            if any(entity.entity_id == circular.entity_id for entity in sketch.entities)
        )
        dimension = SketchConstraint(
            uuid4().hex,
            "radius",
            (SketchGeometryReference(circular.entity_id, "geometry"),),
            2.5,
            "mm",
        )
        app.commit_cross_sketch_dimension(
            services, reopened, owner.sketch_id, dimension, session_identity=0
        )
        linked = services.kernel.sketches
        validate_tangency_component(linked, relations, owner.sketch_id)
        reopened.bus.undo()
        assert services.kernel.sketches == after


@pytest.mark.parametrize("reverse_selection", [False, True])
@pytest.mark.parametrize("trim,radius", [(True, 0), (True, 1), (False, 1)])
def test_polyline_arc_segment_fillet_with_line(
    qtbot: QtBot, reverse_selection: bool, trim: bool, radius: int
) -> None:
    from mycad.core.sketch import LineEntity, PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((5, 0), (-5, 0)), bulges=(1,))
    line = LineEntity(uuid4().hex, (-10, 3 if radius == 0 else 7), (10, 3 if radius == 0 else 7))
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((source, line))
    command = editor.drawing_command_bar.input
    values = ["FILLET", "R", str(radius)] + ([] if trim else ["T", "N"])
    for value in values:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    points = ((4.9, 1), (8, 3)) if radius == 0 else ((3, 4), (8, 7))
    if reverse_selection:
        points = tuple(reversed(points))
    for point in points:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim:
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity), (
            canvas.message
        )
        assert canvas.entities[0].entity_id == source.entity_id
    else:
        assert len(canvas.entities) == 3 and canvas.entities[:2] == [source, line], canvas.message
        assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
    assert canvas.undo_last_operation()
    assert canvas.entities == [source, line]
    assert canvas.redo_last_operation()


@pytest.mark.parametrize("second_curved", [False, True])
@pytest.mark.parametrize("reverse_selection", [False, True])
@pytest.mark.parametrize("trim", [False, True])
def test_two_polyline_segments_fillet_with_arc(
    qtbot: QtBot, second_curved: bool, reverse_selection: bool, trim: bool
) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    first = PolylineEntity(uuid4().hex, ((5, 0), (-5, 0)), bulges=(1,))
    second = (
        PolylineEntity(uuid4().hex, ((-2, 8), (2, 8)), bulges=(1,))
        if second_curved
        else PolylineEntity(uuid4().hex, ((-10, 7), (10, 7)))
    )
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1") if trim else ("FILLET", "R", "1", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    points = ((3, 4), (0, 6.05) if second_curved else (8, 7))
    if reverse_selection:
        points = tuple(reversed(points))
    for point in points:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim:
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity), (
            canvas.message
        )
        assert canvas.entities[0].entity_id == (
            second.entity_id if reverse_selection else first.entity_id
        )
    else:
        assert len(canvas.entities) == 3 and canvas.entities[:2] == [first, second], canvas.message
        assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
    assert canvas.undo_last_operation() and canvas.entities == [first, second]
    assert canvas.redo_last_operation()


@pytest.mark.parametrize("mode", ["same_sketch", "separate", "first_saved", "second_saved"])
@pytest.mark.parametrize("second_polyline", [False, True])
def test_joined_polyline_arc_sources_saved_and_mixed_replay(
    qtbot: QtBot, tmp_path: Path, mode: str, second_polyline: bool
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    first = PolylineEntity(uuid4().hex, ((5, 0), (-5, 0)), bulges=(1,))
    second = (
        PolylineEntity(uuid4().hex, ((-2, 8), (2, 8)), bulges=(1,))
        if second_polyline
        else LineEntity(uuid4().hex, (-10, 7), (10, 7))
    )
    groups = (
        ((first, second),)
        if mode == "same_sketch"
        else ((first,), (second,))
        if mode == "separate"
        else ((first,),)
        if mode == "first_saved"
        else ((second,),)
    )
    for group in groups:
        app.commit_new_sketch(
            services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), group), session_identity=0
        )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    if mode == "first_saved":
        assert canvas.replace_draft_entities((second,))
    elif mode == "second_saved":
        assert canvas.replace_draft_entities((first,))
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((3, 4), (0, 6.05) if second_polyline else (8, 7)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if mode in ("first_saved", "second_saved"):
        qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
        assert services.kernel.sketches == before
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    else:
        qtbot.waitUntil(
            lambda: tuple(loaded.document.commands) != history and not unit.is_busy, timeout=10000
        )
    after = services.kernel.sketches
    entities = tuple(item for sketch in after for item in sketch.entities)
    assert len(entities) == 1 and isinstance(entities[0], PolylineEntity)
    assert entities[0].entity_id == first.entity_id
    path = tmp_path / f"arc-joined-{mode}-{second_polyline}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    undone = tuple(item for sketch in services.kernel.sketches for item in sketch.entities)
    assert first in undone and second in undone
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("both_arcs", [False, True])
@pytest.mark.parametrize("reverse_selection", [False, True])
@pytest.mark.parametrize("trim", [False, True])
def test_selected_same_polyline_mixed_segments_fillet(
    qtbot: QtBot, both_arcs: bool, reverse_selection: bool, trim: bool
) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import LineEntity, PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    quarter = 2**0.5 - 1
    points = (
        ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0))
        if both_arcs
        else ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0))
    )
    source = PolylineEntity(
        uuid4().hex, points, bulges=(quarter, quarter) if both_arcs else (0, quarter)
    )
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks: list[tuple[float, float]] = []
    for segment in segments:
        if isinstance(segment, LineEntity):
            picks.append(
                (
                    (segment.start_mm[0] + segment.end_mm[0]) / 2,
                    (segment.start_mm[1] + segment.end_mm[1]) / 2,
                )
            )
        else:
            angle = math.radians(segment.start_angle_deg + segment.sweep_angle_deg / 2)
            picks.append(
                (
                    segment.center_mm[0] + segment.radius_mm * math.cos(angle),
                    segment.center_mm[1] + segment.radius_mm * math.sin(angle),
                )
            )
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1") if trim else ("FILLET", "R", "1", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in reversed(picks) if reverse_selection else picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim:
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity), (
            canvas.message
        )
        assert len(canvas.entities[0].points_mm) == 4
    else:
        assert len(canvas.entities) == 2 and canvas.entities[0] == source, canvas.message
        assert isinstance(canvas.entities[1], ArcEntity)
        assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
    assert canvas.undo_last_operation() and canvas.entities == [source]
    assert canvas.redo_last_operation()


@pytest.mark.parametrize("both_arcs", [False, True])
@pytest.mark.parametrize("trim", [False, True])
def test_saved_same_polyline_mixed_segments_fillet_replays(
    qtbot: QtBot, tmp_path: Path, both_arcs: bool, trim: bool
) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    quarter = 2**0.5 - 1
    points = (
        ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0))
        if both_arcs
        else ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0))
    )
    source = PolylineEntity(
        uuid4().hex, points, bulges=(quarter, quarter) if both_arcs else (0, quarter)
    )
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks: list[tuple[float, float]] = []
    for segment in segments:
        if isinstance(segment, LineEntity):
            picks.append(
                (
                    (segment.start_mm[0] + segment.end_mm[0]) / 2,
                    (segment.start_mm[1] + segment.end_mm[1]) / 2,
                )
            )
        else:
            angle = math.radians(segment.start_angle_deg + segment.sweep_angle_deg / 2)
            picks.append(
                (
                    segment.center_mm[0] + segment.radius_mm * math.cos(angle),
                    segment.center_mm[1] + segment.radius_mm * math.sin(angle),
                )
            )
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1") if trim else ("FILLET", "R", "1", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim:
        qtbot.waitUntil(
            lambda: tuple(loaded.document.commands) != history and not unit.is_busy, timeout=10000
        )
    else:
        assert len(canvas.pending_cross_tangencies) == 2, canvas.message
        assert canvas.undo_last_operation() and not canvas.pending_cross_tangencies
        assert canvas.redo_last_operation() and len(canvas.pending_cross_tangencies) == 2
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    after = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == (0 if trim else 2)
    for relation in relations:
        validate_tangency_component(after, relations, relation.first.sketch_id)
    path = tmp_path / f"same-mixed-{both_arcs}-{trim}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.sketches == before and not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


@pytest.mark.parametrize("both_arcs", [False, True])
def test_draft_same_polyline_mixed_notrim_saves_and_solves_radius(
    qtbot: QtBot, tmp_path: Path, both_arcs: bool
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    quarter = 2**0.5 - 1
    points = (
        ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0))
        if both_arcs
        else ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0))
    )
    source = PolylineEntity(
        uuid4().hex, points, bulges=(quarter, quarter) if both_arcs else (0, quarter)
    )
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((source,))
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks: list[tuple[float, float]] = []
    for segment in segments:
        if isinstance(segment, LineEntity):
            picks.append(
                (
                    (segment.start_mm[0] + segment.end_mm[0]) / 2,
                    (segment.start_mm[1] + segment.end_mm[1]) / 2,
                )
            )
        else:
            angle = math.radians(segment.start_angle_deg + segment.sweep_angle_deg / 2)
            picks.append(
                (
                    segment.center_mm[0] + segment.radius_mm * math.cos(angle),
                    segment.center_mm[1] + segment.radius_mm * math.sin(angle),
                )
            )
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 2 and isinstance(canvas.entities[1], ArcEntity), canvas.message
    arc_id = canvas.entities[1].entity_id
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    base = services.kernel.sketches[0]
    assert len([item for item in base.constraints if item.kind == "tangent"]) == 2
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(arc_id, "geometry"),), 0.8, "mm"
    )
    solved = services.kernel.preview_sketch_constraint(base, dimension)
    assert solved.status == "success", solved.message
    loaded.bus.execute(
        "sketch.constraint.add",
        solved.command_params(base, dimension, local_frame=True),
        "local",
        version=4,
    )
    after = services.kernel.sketches
    path = tmp_path / f"same-mixed-local-{both_arcs}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == (base,)
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_same_polyline_mixed_segments_zero_radius_finishes_without_history(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (5, 5)), bulges=(0, 2**0.5 - 1))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    position = canvas.history_position
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((5, 0), (8.5355, 3.5355)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities == [source] and canvas.history_position == position
    assert canvas.tool == "选择元素" and "角点" in canvas.message


@pytest.mark.parametrize("trim", [False, True])
def test_closed_polyline_arc_segments_across_seam_fillet(qtbot: QtBot, trim: bool) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    points = ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0), (20.0, 0.0))
    source = PolylineEntity(uuid4().hex, points, True, bulges=(2**0.5 - 1,) * 4)
    segments = polyline_curve_segments(source.points_mm, source.bulges, True, source.entity_id)
    picks: list[tuple[float, float]] = []
    for index in (3, 0):
        segment = segments[index]
        assert isinstance(segment, ArcEntity)
        angle = math.radians(segment.start_angle_deg + segment.sweep_angle_deg / 2)
        picks.append(
            (
                segment.center_mm[0] + segment.radius_mm * math.cos(angle),
                segment.center_mm[1] + segment.radius_mm * math.sin(angle),
            )
        )
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1") if trim else ("FILLET", "R", "1", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim:
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity), (
            canvas.message
        )
        assert canvas.entities[0].closed and len(canvas.entities[0].points_mm) == 5
    else:
        assert len(canvas.entities) == 2 and canvas.entities[0] == source, canvas.message
    assert canvas.undo_last_operation() and canvas.entities == [source]


@pytest.mark.parametrize("first_bulge,last_bulge", [(0.2, 0), (0, 0.2), (0.2, 0.2)])
@pytest.mark.parametrize("reverse_selection", [False, True])
@pytest.mark.parametrize("trim", [False, True])
def test_open_polyline_mixed_end_segments_fillet(
    qtbot: QtBot, first_bulge: float, last_bulge: float, reverse_selection: bool, trim: bool
) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(
        uuid4().hex,
        ((-2, 0), (10, 0), (10, 10), (0, 10), (0, -2)),
        bulges=(first_bulge, 0, 0, last_bulge),
    )
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(segments[0], 0.3), _test_curve_point(segments[-1], 0.7))
    if reverse_selection:
        picks = tuple(reversed(picks))
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1") if trim else ("FILLET", "R", "1", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim:
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity), (
            canvas.message
        )
        assert canvas.entities[0].closed and canvas.entities[0].entity_id == source.entity_id
    else:
        assert len(canvas.entities) == 2 and canvas.entities[0] == source, canvas.message
        assert isinstance(canvas.entities[1], ArcEntity)
        assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
    assert canvas.undo_last_operation() and canvas.entities == [source]
    assert canvas.redo_last_operation()


@pytest.mark.parametrize("first_bulge,last_bulge", [(0.2, 0), (0, 0.2), (0.2, 0.2)])
@pytest.mark.parametrize("trim", [False, True])
def test_saved_open_polyline_mixed_end_fillet_replays(
    qtbot: QtBot, tmp_path: Path, first_bulge: float, last_bulge: float, trim: bool
) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = PolylineEntity(
        uuid4().hex,
        ((-2, 0), (10, 0), (10, 10), (0, 10), (0, -2)),
        bulges=(first_bulge, 0, 0, last_bulge),
    )
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(segments[0], 0.3), _test_curve_point(segments[-1], 0.7))
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1") if trim else ("FILLET", "R", "1", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim:
        qtbot.waitUntil(
            lambda: tuple(loaded.document.commands) != history and not unit.is_busy, timeout=10000
        )
    else:
        assert len(canvas.pending_cross_tangencies) == 2, canvas.message
        assert canvas.undo_last_operation() and not canvas.pending_cross_tangencies
        assert canvas.redo_last_operation() and len(canvas.pending_cross_tangencies) == 2
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    after = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == (0 if trim else 2)
    for relation in relations:
        validate_tangency_component(after, relations, relation.first.sketch_id)
    path = tmp_path / f"mixed-end-{first_bulge}-{last_bulge}-{trim}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.sketches == before and not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


@pytest.mark.parametrize("first_bulge,last_bulge", [(0.2, 0), (0, 0.2), (0.2, 0.2)])
@pytest.mark.parametrize("reverse_selection", [False, True])
@pytest.mark.parametrize("close_path", [False, True])
def test_open_two_mixed_segments_choose_corner_by_picks(
    qtbot: QtBot, first_bulge: float, last_bulge: float, reverse_selection: bool, close_path: bool
) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(
        uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(first_bulge, last_bulge)
    )
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    ratios = (0.1, 0.9) if close_path else (0.75, 0.25)
    picks = (_test_curve_point(segments[0], ratios[0]), _test_curve_point(segments[1], ratios[1]))
    if reverse_selection:
        picks = tuple(reversed(picks))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity), (
        canvas.message
    )
    assert canvas.entities[0].closed == close_path, canvas.message
    assert canvas.undo_last_operation() and canvas.entities == [source]


@pytest.mark.parametrize(
    "bulges,center,branch,old_index,new_index,tampered_contact",
    [
        ((0.2, 0), (12, 5), "line_right", 1, 2, (10, 8)),
        ((0, 0.2), (5, 2), "line_left", 0, 0, (1, 0)),
    ],
)
@pytest.mark.parametrize("mixed", [False, True])
def test_zero_radius_two_mixed_segments_rebinds_extended_tangent_and_replays(
    qtbot: QtBot,
    tmp_path: Path,
    bulges: tuple[float, float],
    center: tuple[float, float],
    branch: str,
    old_index: int,
    new_index: int,
    tampered_contact: tuple[float, float],
    mixed: bool,
) -> None:
    from copy import deepcopy
    from typing import cast

    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency, TangencyBranch
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=bulges)
    circle = CircleEntity(uuid4().hex, center, 2)
    sketches = tuple(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (item,)) for item in (source, circle))
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketches[0].sketch_id, source.entity_id, old_index),
        CrossSketchRef(sketches[1].sketch_id, circle.entity_id),
        cast("TangencyBranch", branch),
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    if mixed:
        draft = CircleEntity(uuid4().hex, (30, 30), 1)
        assert editor.canvas.replace_draft_entities((draft,))
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(segments[0], 0.1), _test_curve_point(segments[1], 0.9))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    if mixed:
        qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
        assert editor.canvas.mixed_move is not None, editor.status_label.text()
        assert tuple(loaded.document.commands) == history
        assert editor.canvas.undo_last_operation()
        assert editor.canvas.mixed_move is None
        assert editor.canvas.redo_last_operation()
        assert editor.canvas.mixed_move is not None
        assert tuple(loaded.document.commands) == history
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
        )
    else:
        qtbot.waitUntil(
            lambda: tuple(loaded.document.commands) != history and not unit.is_busy, timeout=10000
        )
    after = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == 1 and relations[0].relation_id == relation.relation_id
    assert relations[0].first.segment_index == new_index
    command_record = loaded.document.commands[-1]
    assert command_record.version == 35
    path = tmp_path / "tangent-closure.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    undone = services.kernel.sketches
    assert all(sketch in undone for sketch in before)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    with pytest.raises(ValidationError):
        reopened.bus.execute(command_record.id, command_record.params, "local", version=34)
    assert services.kernel.sketches == undone and services.kernel.cross_sketch_tangencies == (
        relation,
    )
    tampered = deepcopy(command_record.params)
    revisions = cast("list[dict[str, object]]", tampered["revisions"])
    revision = next(item for item in revisions if item["sketch_id"] == sketches[0].sketch_id)
    entities = cast("list[dict[str, object]]", revision["entities"])
    changed = next(item for item in entities if item["entity_id"] == source.entity_id)
    points = cast("list[list[float]]", changed["points_mm"])
    points[0] = list(tampered_contact)
    with pytest.raises(ValidationError):
        reopened.bus.execute(command_record.id, tampered, "local", version=35)
    assert services.kernel.sketches == undone and services.kernel.cross_sketch_tangencies == (
        relation,
    )
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


@pytest.mark.parametrize(
    "bulges,center,old_index,new_index",
    [((0.2, 0), (12, 5), 1, 2), ((0, 0.2), (5, 2), 0, 0)],
)
def test_zero_radius_closure_keeps_pending_cross_sketch_tangency(
    qtbot: QtBot,
    tmp_path: Path,
    bulges: tuple[float, float],
    center: tuple[float, float],
    old_index: int,
    new_index: int,
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=bulges)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    circle = CircleEntity(uuid4().hex, center, 2)
    assert editor.canvas.replace_draft_entities((circle,))
    pair = (SketchGeometryReference(source.entity_id, "segment", old_index), circle.entity_id)
    editor.canvas.pending_cross_tangencies = [pair]
    draft = Sketch(editor.draft_sketch_id, WorkPlaneFrame.xy(), (circle,))
    relation_id = app.draft_cross_relations((saved,), draft, (pair,))[0].relation_id
    history = tuple(loaded.document.commands)
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(segments[0], 0.1), _test_curve_point(segments[1], 0.9))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert editor.canvas.mixed_move is not None, editor.status_label.text()
    assert len(editor.canvas.pending_cross_tangencies) == 1
    assert editor.canvas.pending_cross_tangencies[0][0] == SketchGeometryReference(
        source.entity_id, "segment", new_index
    )
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.pending_cross_tangencies == [pair]
    assert editor.canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == 1 and relations[0].relation_id == relation_id
    assert relations[0].first.segment_index == new_index
    assert loaded.document.commands[-1].version == 35
    after = services.kernel.sketches
    path = tmp_path / "pending-tangent.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.cross_sketch_tangencies[0].first.segment_index == old_index
    assert services.kernel.cross_sketch_tangencies[0].relation_id == relation_id
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


@pytest.mark.parametrize(
    "bulges,center,old_index,new_index",
    [((0.2, 0), (12, 5), 1, 2), ((0, 0.2), (5, 2), 0, 0), ((0.2, 0), (5, -3), 0, 1)],
)
def test_zero_radius_draft_closure_keeps_pending_tangent_to_saved_circle(
    qtbot: QtBot,
    tmp_path: Path,
    bulges: tuple[float, float],
    center: tuple[float, float],
    old_index: int,
    new_index: int,
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    circle = CircleEntity(uuid4().hex, center, 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=bulges)
    assert editor.canvas.replace_draft_entities((source,))
    pair = (circle.entity_id, SketchGeometryReference(source.entity_id, "segment", old_index))
    editor.canvas.pending_cross_tangencies = [pair]
    history = tuple(loaded.document.commands)
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(segments[0], 0.1), _test_curve_point(segments[1], 0.9))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert editor.canvas.entities != [source], editor.canvas.message
    assert editor.canvas.pending_cross_tangencies == [
        (circle.entity_id, SketchGeometryReference(source.entity_id, "segment", new_index))
    ]
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation() and editor.canvas.pending_cross_tangencies == [pair]
    assert editor.canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert len(relations) == 1 and relations[0].second.segment_index == new_index
    path = tmp_path / "pending-draft.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.sketches == (saved,) and not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


@pytest.mark.parametrize("contact_case", ["removed", "split"])
def test_zero_radius_trimmed_arc_rejects_unavailable_tangent_contact(
    qtbot: QtBot, contact_case: str
) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    editor.snap_check.setChecked(False)
    _zoom_for_short_segment(editor.canvas)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (9.12, -0.04)), bulges=(0.6, 0))
    curves = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    arc = curves[0]
    assert isinstance(arc, ArcEntity)
    closed, _ = polyline_segment_fillet(
        source, 0, 1, 0, first_pick=_test_curve_point(arc, 0.05), second_pick=source.points_mm[-1]
    )
    contact = _test_curve_point(arc, 0.01) if contact_case == "removed" else closed.points_mm[1]
    scale = (arc.radius_mm + 1) / arc.radius_mm
    center = tuple(c + (p - c) * scale for c, p in zip(arc.center_mm, contact, strict=True))
    circle = CircleEntity(uuid4().hex, (center[0], center[1]), 1)
    first, second = tuple(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (item,)) for item in (source, circle)
    )
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "external",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    ratio = 0.5 if contact_case == "removed" else 0.05
    for point in (_test_curve_point(curves[0], ratio), _test_curve_point(curves[1], 0.95)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert "失败" in editor.status_label.text()
    assert tuple(loaded.document.commands) == history
    assert services.kernel.sketches == before and services.kernel.cross_sketch_tangencies == (
        relation,
    )


def test_mixed_trim_reports_removed_pending_tangent_and_can_undo(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    editor.snap_check.setChecked(False)
    _zoom_for_short_segment(editor.canvas)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (9.12, -0.04)), bulges=(0.6, 0))
    curves = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    arc = curves[0]
    assert isinstance(arc, ArcEntity)
    contact = _test_curve_point(arc, 0.01)
    scale = (arc.radius_mm + 1) / arc.radius_mm
    center = tuple(c + (p - c) * scale for c, p in zip(arc.center_mm, contact, strict=True))
    circle = CircleEntity(uuid4().hex, (center[0], center[1]), 1)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    assert editor.canvas.replace_draft_entities((circle,))
    pair = (SketchGeometryReference(source.entity_id, "segment", 0), circle.entity_id)
    editor.canvas.pending_cross_tangencies = [pair]
    history = tuple(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "M", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in (_test_curve_point(arc, 0.5), _test_curve_point(curves[1], 0.95)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert editor.canvas.mixed_move is not None, editor.status_label.text()
    assert not editor.canvas.pending_cross_tangencies
    assert "已移除 1 条失效的暂存相切关系" in editor.status_label.text()
    assert tuple(loaded.document.commands) == history
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert "已撤销" in editor.canvas.message
    assert editor.canvas.pending_cross_tangencies == [pair]
    assert "已移除 1 条失效的暂存相切关系" not in editor.status_label.text()
    assert editor.canvas.redo_last_operation()
    assert not editor.canvas.pending_cross_tangencies
    assert "已移除 1 条失效的暂存相切关系" in editor.status_label.text()


@pytest.mark.parametrize("saved_source", [False, True])
@pytest.mark.parametrize("command_undo", [False, True])
def test_zero_radius_trimmed_arc_keeps_pending_tangent(
    qtbot: QtBot, tmp_path: Path, saved_source: bool, command_undo: bool
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    editor.snap_check.setChecked(False)
    _zoom_for_short_segment(editor.canvas)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (9.12, -0.04)), bulges=(0.6, 0))
    curves = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    arc = curves[0]
    assert isinstance(arc, ArcEntity)
    tangent = _test_curve_point(arc, 0.1)
    scale = (arc.radius_mm + 1) / arc.radius_mm
    center = tuple(c + (p - c) * scale for c, p in zip(arc.center_mm, tangent, strict=True))
    circle = CircleEntity(uuid4().hex, (center[0], center[1]), 1)
    saved_entity, draft_entity = (source, circle) if saved_source else (circle, source)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_entity,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    assert editor.canvas.replace_draft_entities((draft_entity,))
    arc_ref = SketchGeometryReference(source.entity_id, "segment", 0)
    pair = (arc_ref, circle.entity_id) if saved_source else (circle.entity_id, arc_ref)
    editor.canvas.pending_cross_tangencies = [pair]
    initial_draft = Sketch(editor.draft_sketch_id, WorkPlaneFrame.xy(), (draft_entity,))
    relation_id = app.draft_cross_relations((saved,), initial_draft, (pair,))[0].relation_id
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "M", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in (_test_curve_point(curves[0], 0.05), _test_curve_point(curves[1], 0.95)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    if saved_source:
        assert editor.canvas.mixed_move is not None, editor.status_label.text()
    else:
        assert editor.canvas.entities != [source], editor.canvas.message
    assert editor.canvas.pending_cross_tangencies == [pair]
    if command_undo:
        command.setText("U")
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert "已撤销" in editor.canvas.message
        assert editor.canvas.pending_cross_tangencies == [pair]
        assert editor.canvas.redo_last_operation()
    else:
        assert editor.canvas.undo_last_operation() and editor.canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert len(relations) == 1
    if saved_source:
        assert relations[0].relation_id == relation_id
        assert loaded.document.commands[-1].version == 37
    path = tmp_path / "trimmed-pending.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("branch", ["external", "first_contains_second", "second_contains_first"])
def test_zero_radius_trimmed_arc_keeps_unique_tangent_contact(
    qtbot: QtBot, tmp_path: Path, mixed: bool, branch: str
) -> None:
    from copy import deepcopy
    from typing import cast

    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency, TangencyBranch
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    editor.snap_check.setChecked(False)
    _zoom_for_short_segment(editor.canvas)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (9.12, -0.04)), bulges=(0.6, 0))
    curves = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    arc = curves[0]
    assert isinstance(arc, ArcEntity)
    tangent = _test_curve_point(arc, 0.1)
    radius = arc.radius_mm + 2 if branch == "second_contains_first" else 1.0
    distance = arc.radius_mm + radius if branch == "external" else arc.radius_mm - radius
    scale = distance / arc.radius_mm
    center = tuple(c + (p - c) * scale for c, p in zip(arc.center_mm, tangent, strict=True))
    circle = CircleEntity(uuid4().hex, (center[0], center[1]), radius)
    first, second = tuple(
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (item,)) for item in (source, circle)
    )
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        cast("TangencyBranch", branch),
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    if mixed:
        assert editor.canvas.replace_draft_entities((CircleEntity(uuid4().hex, (30, 30), 1),))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "M", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    first_ratio = 0.5 if branch == "second_contains_first" else 0.05
    for point in (_test_curve_point(curves[0], first_ratio), _test_curve_point(curves[1], 0.95)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    if mixed:
        assert editor.canvas.mixed_move is not None, editor.status_label.text()
        command.setText("U")
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert editor.canvas.mixed_move is None
        assert editor.canvas.redo_last_operation()
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
        )
    else:
        assert tuple(loaded.document.commands) != history, editor.status_label.text()
        edited = services.kernel.sketches
        command.setText("U")
        QTest.keyClick(command, Qt.Key.Key_Return)
        qtbot.waitUntil(
            lambda: (
                services.kernel.sketches == before
                and not unit.is_busy
                and not unit.is_delivering_result
            ),
            timeout=15000,
        )
        assert services.kernel.cross_sketch_tangencies == (relation,)
        window.act_redo.trigger()
        qtbot.waitUntil(
            lambda: (
                services.kernel.sketches == edited
                and not unit.is_busy
                and not unit.is_delivering_result
            ),
            timeout=15000,
        )
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert relations == (relation,)
    record = loaded.document.commands[-1]
    assert record.version == 37
    path = tmp_path / "trimmed-arc.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    undone = services.kernel.sketches
    assert all(sketch in undone for sketch in before)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    with pytest.raises(ValidationError):
        reopened.bus.execute(record.id, record.params, "local", version=36)
    assert services.kernel.sketches == undone and services.kernel.cross_sketch_tangencies == (
        relation,
    )
    tampered = deepcopy(record.params)
    revisions = cast("list[dict[str, object]]", tampered["revisions"])
    revision = next(item for item in revisions if item["sketch_id"] == first.sketch_id)
    entities = cast("list[dict[str, object]]", revision["entities"])
    changed = next(item for item in entities if item["entity_id"] == source.entity_id)
    changed_bulges = cast("list[float]", changed["bulges"])
    changed_bulges[0] *= 0.5
    with pytest.raises(ValidationError):
        reopened.bus.execute(record.id, tampered, "local", version=37)
    assert services.kernel.sketches == undone and services.kernel.cross_sketch_tangencies == (
        relation,
    )
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


def test_zero_radius_closure_preserves_two_original_arc_tangencies(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (3.7376, 9.017)), bulges=(0.6, 0.9))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    arcs = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    relations: list[CrossSketchTangency] = []
    for index, arc in enumerate(arcs):
        assert isinstance(arc, ArcEntity)
        point = _test_curve_point(arc, 0.5)
        scale = (arc.radius_mm + 0.5) / arc.radius_mm
        center = tuple(c + (p - c) * scale for c, p in zip(arc.center_mm, point, strict=True))
        circle = CircleEntity(uuid4().hex, (center[0], center[1]), 0.5)
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(saved.sketch_id, source.entity_id, index),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "external",
        )
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
        relations.append(relation)
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    before_relations = services.kernel.cross_sketch_tangencies
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in (_test_curve_point(arcs[0], 0.05), _test_curve_point(arcs[1], 0.95)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    assert tuple(loaded.document.commands) != history, editor.status_label.text()
    after = services.kernel.sketches
    rebound = services.kernel.cross_sketch_tangencies
    assert {item.relation_id for item in rebound} == {item.relation_id for item in relations}
    assert {item.first.segment_index for item in rebound} == {1, 2}
    path = tmp_path / "two-arcs.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == rebound
    reopened.bus.undo()
    assert (
        services.kernel.sketches == before
        and services.kernel.cross_sketch_tangencies == before_relations
    )
    reopened.bus.redo()
    assert services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == rebound


def test_zero_radius_closure_rejects_discarding_picked_arc(qtbot: QtBot) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    editor.snap_check.setChecked(False)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (5.7147, 6.573)), bulges=(-0.6, 0))
    assert editor.canvas.replace_draft_entities((source,))
    before = editor.canvas.history_position
    curves = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(curves[0], 0.05), _test_curve_point(curves[1], 0.95))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert editor.canvas.entities == [source]
    assert editor.canvas.history_position == before
    assert "保留" in editor.canvas.message


@pytest.mark.parametrize("mode", ["committed", "mixed", "pending"])
def test_zero_radius_split_arc_preserves_tangent_and_replays(
    qtbot: QtBot, tmp_path: Path, mode: str
) -> None:
    from copy import deepcopy
    from typing import cast

    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(0.2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    circle = CircleEntity(uuid4().hex, (5, -3), 2)
    if mode == "pending":
        editor.set_context_sketches(services.kernel.sketches)
        assert editor.canvas.replace_draft_entities((circle,))
        pair = (SketchGeometryReference(source.entity_id, "segment", 0), circle.entity_id)
        editor.canvas.pending_cross_tangencies = [pair]
        draft = Sketch(editor.draft_sketch_id, WorkPlaneFrame.xy(), (circle,))
        relation_id = app.draft_cross_relations((saved,), draft, (pair,))[0].relation_id
    else:
        other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, other, session_identity=0)
        relation = CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(saved.sketch_id, source.entity_id, 0),
            CrossSketchRef(other.sketch_id, circle.entity_id),
            "external",
        )
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
        relation_id = relation.relation_id
        editor.set_context_sketches(services.kernel.sketches)
        if mode == "mixed":
            assert editor.canvas.replace_draft_entities((CircleEntity(uuid4().hex, (30, 30), 1),))
    history = tuple(loaded.document.commands)
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(segments[0], 0.1), _test_curve_point(segments[1], 0.9))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=15000)
    if mode == "committed":
        assert tuple(loaded.document.commands) != history, editor.status_label.text()
    else:
        assert editor.canvas.mixed_move is not None, editor.status_label.text()
        if mode == "pending":
            assert editor.canvas.pending_cross_tangencies == [
                (SketchGeometryReference(source.entity_id, "segment", 1), circle.entity_id)
            ]
        assert editor.canvas.undo_last_operation()
        assert editor.canvas.redo_last_operation()
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
        )
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert len(relations) == 1 and relations[0].relation_id == relation_id
    assert relations[0].first.segment_index == 1
    record = loaded.document.commands[-1]
    assert record.version == 36
    path = tmp_path / "arc-rebind.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    undone, old_relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert old_relations[0].relation_id == relation_id and old_relations[0].first.segment_index == 0
    with pytest.raises(ValidationError):
        reopened.bus.execute(record.id, record.params, "local", version=35)
    assert (
        services.kernel.sketches == undone
        and services.kernel.cross_sketch_tangencies == old_relations
    )
    tampered = deepcopy(record.params)
    revisions = cast("list[dict[str, object]]", tampered["revisions"])
    revision = next(item for item in revisions if item["sketch_id"] == saved.sketch_id)
    entities = cast("list[dict[str, object]]", revision["entities"])
    changed = next(item for item in entities if item["entity_id"] == source.entity_id)
    changed_bulges = cast("list[float]", changed["bulges"])
    changed_bulges[1] *= 0.5
    with pytest.raises(ValidationError):
        reopened.bus.execute(record.id, tampered, "local", version=36)
    assert (
        services.kernel.sketches == undone
        and services.kernel.cross_sketch_tangencies == old_relations
    )
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


@pytest.mark.parametrize("first_bulge,last_bulge", [(0.2, 0), (0, 0.2), (0.2, 0.2)])
def test_saved_zero_radius_closes_two_mixed_segments_and_replays(
    qtbot: QtBot, tmp_path: Path, first_bulge: float, last_bulge: float
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = PolylineEntity(
        uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(first_bulge, last_bulge)
    )
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(segments[0], 0.1), _test_curve_point(segments[1], 0.9))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(
        lambda: tuple(loaded.document.commands) != history and not unit.is_busy, timeout=10000
    )
    after = services.kernel.sketches
    updated = next(
        item for sketch in after for item in sketch.entities if item.entity_id == source.entity_id
    )
    assert isinstance(updated, PolylineEntity) and updated.closed and len(updated.points_mm) == 3
    path = tmp_path / "closed.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == before
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("first_bulge,last_bulge", [(0.2, 0), (0, 0.2), (0.2, 0.2)])
@pytest.mark.parametrize("trim", [False, True])
def test_saved_open_two_mixed_segments_major_fillet_replays(
    qtbot: QtBot, tmp_path: Path, first_bulge: float, last_bulge: float, trim: bool
) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = PolylineEntity(
        uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(first_bulge, last_bulge)
    )
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(segments[0], 0.1), _test_curve_point(segments[1], 0.9))
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1") if trim else ("FILLET", "R", "1", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim:
        qtbot.waitUntil(
            lambda: tuple(loaded.document.commands) != history and not unit.is_busy, timeout=10000
        )
    else:
        assert len(canvas.pending_cross_tangencies) == 2, canvas.message
        assert (
            isinstance(canvas.entities[0], ArcEntity)
            and abs(canvas.entities[0].sweep_angle_deg) > 180
        )
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    after = services.kernel.sketches
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == (0 if trim else 2)
    if trim:
        updated = next(
            item
            for sketch in after
            for item in sketch.entities
            if item.entity_id == source.entity_id
        )
        assert (
            isinstance(updated, PolylineEntity) and updated.closed and abs(updated.bulges[-1]) > 1
        )
    else:
        for relation in relations:
            validate_tangency_component(after, relations, relation.first.sketch_id)
    path = tmp_path / f"major-end-{first_bulge}-{last_bulge}-{trim}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.sketches == before and not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    if not trim and first_bulge and last_bulge:
        fillet_owner = next(
            sketch
            for sketch in after
            if any(isinstance(item, ArcEntity) for item in sketch.entities)
        )
        fillet = next(item for item in fillet_owner.entities if isinstance(item, ArcEntity))
        dimension = SketchConstraint(
            uuid4().hex,
            "radius",
            (SketchGeometryReference(fillet.entity_id, "geometry"),),
            0.8,
            "mm",
        )
        app.commit_cross_sketch_dimension(
            services, reopened, fillet_owner.sketch_id, dimension, session_identity=0
        )
        validate_tangency_component(services.kernel.sketches, relations, fillet_owner.sketch_id)
        reopened.bus.undo()
        assert services.kernel.sketches == after


@pytest.mark.parametrize("both_arcs", [False, True])
@pytest.mark.parametrize("reverse_selection", [False, True])
@pytest.mark.parametrize("radius,trim", [(0, True), (0.5, True), (1, True), (1.5, False)])
def test_selected_mixed_segments_replace_existing_fillet(
    qtbot: QtBot, both_arcs: bool, reverse_selection: bool, radius: float, trim: bool
) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    quarter = 2**0.5 - 1
    points = ((5, -5), (10, 0), (15, 5)) if both_arcs else ((0, 0), (10, 0), (5, 5))
    original = PolylineEntity(
        uuid4().hex, points, bulges=(quarter, quarter) if both_arcs else (0, quarter)
    )
    vertices, bulges = polyline_fillet_trimmed_segments(original, 1)
    source = PolylineEntity(original.entity_id, vertices, bulges=bulges)
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(segments[0], 0.5), _test_curve_point(segments[2], 0.5))
    if reverse_selection:
        picks = (picks[1], picks[0])
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((source,))
    history = canvas.history_position
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", str(radius)) if trim else ("FILLET", "R", str(radius), "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim and radius == 1:
        assert canvas.entities == [source] and canvas.history_position == history, canvas.message
        return
    if trim:
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity), (
            canvas.message
        )
        assert len(canvas.entities[0].points_mm) == (3 if radius == 0 else 4)
    else:
        assert len(canvas.entities) == 2 and canvas.entities[0] == source, canvas.message
        assert isinstance(canvas.entities[1], ArcEntity) and canvas.entities[
            1
        ].radius_mm == pytest.approx(radius)
        assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
    assert canvas.undo_last_operation() and canvas.entities == [source]
    assert canvas.redo_last_operation()


@pytest.mark.parametrize("both_arcs", [False, True])
@pytest.mark.parametrize("radius,trim", [(0, True), (0.5, True), (1.0, False), (1.5, False)])
def test_saved_selected_mixed_segments_replace_existing_fillet_replays(
    qtbot: QtBot, tmp_path: Path, both_arcs: bool, radius: float, trim: bool
) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    quarter = 2**0.5 - 1
    points = ((5, -5), (10, 0), (15, 5)) if both_arcs else ((0, 0), (10, 0), (5, 5))
    original = PolylineEntity(
        uuid4().hex, points, bulges=(quarter, quarter) if both_arcs else (0, quarter)
    )
    vertices, bulges = polyline_fillet_trimmed_segments(original, 1)
    source = PolylineEntity(original.entity_id, vertices, bulges=bulges)
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(segments[0], 0.5), _test_curve_point(segments[2], 0.5))
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", str(radius)) if trim else ("FILLET", "R", str(radius), "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    history = tuple(loaded.document.commands)
    for point in picks:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if trim:
        qtbot.waitUntil(
            lambda: tuple(loaded.document.commands) != history and not unit.is_busy, timeout=10000
        )
    else:
        assert len(canvas.pending_cross_tangencies) == 2, canvas.message
        assert canvas.undo_last_operation() and not canvas.pending_cross_tangencies
        assert canvas.redo_last_operation() and len(canvas.pending_cross_tangencies) == 2
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert len(relations) == (0 if trim else 2)
    if not trim and radius == 1:
        for relation in relations:
            source_endpoint = (
                relation.first_endpoint
                if relation.first.entity_id == source.entity_id
                else relation.second_endpoint
            )
            assert source_endpoint is not None
            assert relation.first_endpoint is not None and relation.second_endpoint is not None
    for relation in relations:
        validate_tangency_component(after, relations, relation.first.sketch_id)
    path = tmp_path / f"replace-mixed-{both_arcs}-{radius}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.sketches == before and not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    if not trim and radius == 1:
        from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

        owner = next(
            sketch
            for sketch in after
            if any(isinstance(item, ArcEntity) for item in sketch.entities)
        )
        fillet = next(item for item in owner.entities if isinstance(item, ArcEntity))
        dimension = SketchConstraint(
            uuid4().hex,
            "radius",
            (SketchGeometryReference(fillet.entity_id, "geometry"),),
            0.8,
            "mm",
        )
        app.commit_cross_sketch_dimension(
            services, reopened, owner.sketch_id, dimension, session_identity=0
        )
        linked = services.kernel.sketches
        validate_tangency_component(linked, relations, owner.sketch_id)
        updated = next(
            item
            for sketch in linked
            for item in sketch.entities
            if item.entity_id == fillet.entity_id
        )
        assert isinstance(updated, ArcEntity) and updated.radius_mm == pytest.approx(0.8)
        reopened.bus.undo()
        assert services.kernel.sketches == after
        reopened.bus.redo()
        assert services.kernel.sketches == linked
        save_document(reopened.document, path)
        app.open_app_document(services, path)
        assert services.kernel.sketches == linked
        validate_tangency_component(
            linked, services.kernel.cross_sketch_tangencies, owner.sketch_id
        )


def test_replace_selected_mixed_fillet_preserves_existing_cross_sketch_tangency(
    qtbot: QtBot,
) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    original = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (5, 5)), bulges=(0, 2**0.5 - 1))
    points, bulges = polyline_fillet_trimmed_segments(original, 1)
    source = PolylineEntity(original.entity_id, points, bulges=bulges)
    circle = CircleEntity(uuid4().hex, (1, -2), 2)
    sketches = tuple(Sketch(uuid4().hex, WorkPlaneFrame.xy(), (item,)) for item in (source, circle))
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(sketches[0].sketch_id, source.entity_id, 0),
        CrossSketchRef(sketches[1].sketch_id, circle.entity_id),
        "line_right",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "0.5"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    history = tuple(loaded.document.commands)
    for part in (segments[0], segments[2]):
        QTest.mouseClick(
            editor.canvas,
            Qt.MouseButton.LeftButton,
            pos=editor.canvas.local_to_screen(_test_curve_point(part, 0.5)),
        )
    qtbot.waitUntil(
        lambda: tuple(loaded.document.commands) != history and not unit.is_busy, timeout=10000
    )
    assert services.kernel.sketches != before
    updated = next(
        item for item in services.kernel.sketches if item.sketch_id == sketches[0].sketch_id
    )
    result = updated.entities[0]
    assert isinstance(result, PolylineEntity)
    parts = polyline_curve_segments(result.points_mm, result.bulges, False, result.entity_id)
    assert isinstance(parts[1], ArcEntity) and parts[1].radius_mm == pytest.approx(0.5)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    validate_tangency_component(services.kernel.sketches, (relation,), sketches[0].sketch_id)
    loaded.bus.undo()
    assert services.kernel.sketches == before and services.kernel.cross_sketch_tangencies == (
        relation,
    )
    loaded.bus.redo()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    validate_tangency_component(services.kernel.sketches, (relation,), sketches[0].sketch_id)


@pytest.mark.parametrize("radius", [0.0, 1.0])
@pytest.mark.parametrize("reverse_selection", [False, True])
def test_saved_polyline_lines_replace_intervening_straight_segment(
    qtbot: QtBot, tmp_path: Path, radius: float, reverse_selection: bool
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (8, 0), (10, 2), (10, 10), (15, 10)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", str(radius)):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    history = tuple(loaded.document.commands)
    picks = ((4, 0), (10, 6))
    for point in reversed(picks) if reverse_selection else picks:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(
        lambda: tuple(loaded.document.commands) != history and not unit.is_busy, timeout=10000
    )
    after = services.kernel.sketches
    result = next(item for item in after if item.sketch_id == sketch.sketch_id).entities[0]
    assert isinstance(result, PolylineEntity) and result.entity_id == source.entity_id
    assert len(result.points_mm) == (4 if radius == 0 else 5)
    assert result.points_mm[-1] == source.points_mm[-1]
    path = tmp_path / f"straight-middle-{radius}-{reverse_selection}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == before
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_unrelated_fillet_preserves_inferred_polyline_segment_tangency(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((-20, 0), (-10, 0), (-10, 5)))
    circle = CircleEntity(uuid4().hex, (-15, 2), 2)
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (10, 0), (10, 10))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source, circle, first, second))
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(source.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
        source="inferred",
    )
    canvas.constraints = [relation]
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((5, 0), (10, 5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert relation in canvas.constraints, canvas.message
    assert canvas.undo_last_operation() and relation in canvas.constraints
    assert canvas.redo_last_operation() and relation in canvas.constraints


def test_inferred_tangency_drops_disconnected_endpoint_on_draft_edit(qtbot: QtBot) -> None:
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (-5, 0), (0, 0))
    arc = ArcEntity(uuid4().hex, (0, 1), 1, -90, 180)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((line, arc))
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(arc.entity_id, "geometry"),
        ),
        source="inferred",
        first_endpoint="end",
        second_endpoint="start",
    )
    canvas.constraints = [relation]
    moved_end = LineEntity(line.entity_id, line.start_mm, (1, 0))
    assert canvas.replace_draft_entities((moved_end, arc))
    assert relation not in canvas.constraints
    assert canvas.undo_last_operation() and relation in canvas.constraints
    assert canvas.redo_last_operation() and relation not in canvas.constraints


def test_inferred_tangency_drops_changed_segment_during_topology_edit(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source, circle))
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(source.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
        source="inferred",
    )
    canvas.constraints = [relation]
    extended = PolylineEntity(source.entity_id, ((-1, 0), (10, 0), (10, 5), (15, 5)))
    assert canvas.replace_draft_entities((extended, circle))
    assert relation in canvas.constraints
    assert canvas.undo_last_operation() and relation in canvas.constraints
    changed = PolylineEntity(source.entity_id, ((-1, 1), (10, 0), (10, 5), (15, 5)))
    assert canvas.replace_draft_entities((changed, circle))
    assert relation not in canvas.constraints
    assert canvas.undo_last_operation() and relation in canvas.constraints
    assert canvas.redo_last_operation() and relation not in canvas.constraints


def test_polyline_fillet_inference_survives_later_fillet_and_replay(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (8, 0), (12, 0)))
    line = LineEntity(uuid4().hex, (10, 2), (10, 10))
    first = LineEntity(uuid4().hex, (25, 0), (35, 0))
    second = LineEntity(uuid4().hex, (35, 0), (35, 10))
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((polyline, line, first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((4, 0), (10, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    first_relations = tuple(canvas.constraints)
    assert len(first_relations) == 4, canvas.message
    for value in ("FILLET", "T", "T"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((30, 0), (35, 5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert all(item in canvas.constraints for item in first_relations), canvas.message
    assert canvas.undo_last_operation() and tuple(canvas.constraints) == first_relations
    assert canvas.redo_last_operation() and all(
        item in canvas.constraints for item in first_relations
    )
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    after = services.kernel.sketches
    assert all(item in after[0].constraints for item in first_relations)
    path = tmp_path / "inferred-polyline-fillet.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert not services.kernel.sketches
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_inferred_tangency_preserves_edited_polyline_segment_when_still_tangent(
    qtbot: QtBot,
) -> None:
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source, circle))
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(source.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
        source="inferred",
    )
    canvas.constraints = [relation]
    changed = PolylineEntity(source.entity_id, ((-1, 0), (10, 0), (10, 5)))
    assert canvas.replace_draft_entities((changed, circle))
    assert relation in canvas.constraints
    assert canvas.undo_last_operation() and relation in canvas.constraints
    assert canvas.redo_last_operation() and relation in canvas.constraints


@pytest.mark.parametrize("connected", [False, True])
def test_pending_tangency_checks_draft_connected_endpoint_after_edit(
    qtbot: QtBot, connected: bool
) -> None:
    from mycad.core.cross_sketch_tangency import DraftConnectedEndpoint
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (-5, 0), (0, 0))
    arc = ArcEntity(uuid4().hex, (0, 1), 1, -90, 180)
    editor.set_context_sketches((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)),))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((arc,))
    source_ref = SketchGeometryReference(line.entity_id, "geometry")
    target_ref = SketchGeometryReference(arc.entity_id, "geometry")
    pair = (
        DraftConnectedEndpoint(source_ref, "end") if connected else source_ref,
        DraftConnectedEndpoint(target_ref, "start") if connected else target_ref,
    )
    canvas.pending_cross_tangencies = [pair]
    changed = ArcEntity(arc.entity_id, arc.center_mm, arc.radius_mm, -120, 210)
    assert canvas.replace_draft_entities((changed,))
    assert canvas.pending_cross_tangencies == ([] if connected else [pair])
    assert canvas.undo_last_operation() and canvas.pending_cross_tangencies == [pair]
    assert canvas.redo_last_operation()
    assert canvas.pending_cross_tangencies == ([] if connected else [pair])


@pytest.mark.parametrize("detached", [False, True])
def test_pending_tangency_checks_saved_connected_endpoint_in_mixed_candidate(
    qtbot: QtBot, detached: bool
) -> None:
    from mycad.core.cross_sketch_tangency import DraftConnectedEndpoint
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.sketch_editor import MixedMoveState

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (-5, 0), (0, 0))
    moved = LineEntity(line.entity_id, line.start_mm, (1, 0)) if detached else line
    arc = ArcEntity(uuid4().hex, (0, 1), 1, -90, 180)
    frame = WorkPlaneFrame.xy()
    saved = Sketch(uuid4().hex, frame, (line,))
    current = Sketch(saved.sketch_id, frame, (moved,))
    draft = Sketch(uuid4().hex, frame, (arc,))
    canvas = editor.canvas
    canvas.entities = [arc]
    canvas.mixed_move = MixedMoveState(uuid4().hex, 1, draft, (saved,), (current,), (), ())
    pair = (
        DraftConnectedEndpoint(SketchGeometryReference(line.entity_id, "geometry"), "end"),
        DraftConnectedEndpoint(SketchGeometryReference(arc.entity_id, "geometry"), "start"),
    )
    canvas.pending_cross_tangencies = [pair]
    extra = CircleEntity(uuid4().hex, (20, 20), 1)
    assert canvas.replace_draft_entities((arc, extra))
    assert canvas.pending_cross_tangencies == ([] if detached else [pair])
    assert canvas.undo_last_operation() and canvas.pending_cross_tangencies == [pair]
    assert canvas.redo_last_operation()
    assert canvas.pending_cross_tangencies == ([] if detached else [pair])


def test_pending_tangency_drops_changed_segment_during_topology_edit(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)))
    editor.set_context_sketches((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,)),))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    pair = (circle.entity_id, SketchGeometryReference(source.entity_id, "segment", 0))
    canvas.pending_cross_tangencies = [pair]
    extended = PolylineEntity(source.entity_id, ((-1, 0), (10, 0), (10, 5), (15, 5)))
    assert canvas.replace_draft_entities((extended,))
    assert canvas.pending_cross_tangencies == [pair]
    assert canvas.undo_last_operation() and canvas.pending_cross_tangencies == [pair]
    changed = PolylineEntity(source.entity_id, ((-1, 1), (10, 0), (10, 5), (15, 5)))
    assert canvas.replace_draft_entities((changed,))
    assert not canvas.pending_cross_tangencies
    assert canvas.undo_last_operation() and canvas.pending_cross_tangencies == [pair]
    assert canvas.redo_last_operation() and not canvas.pending_cross_tangencies


def test_detached_pending_fillet_endpoint_does_not_block_save(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import DraftConnectedEndpoint
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (-5, 0), (0, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before = services.kernel.sketches
    arc = ArcEntity(uuid4().hex, (0, 1), 1, -90, 180)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((arc,))
    pair = (
        DraftConnectedEndpoint(SketchGeometryReference(line.entity_id, "geometry"), "end"),
        DraftConnectedEndpoint(SketchGeometryReference(arc.entity_id, "geometry"), "start"),
    )
    canvas.pending_cross_tangencies = [pair]
    changed = ArcEntity(arc.entity_id, arc.center_mm, arc.radius_mm, -120, 210)
    assert canvas.replace_draft_entities((changed,)) and not canvas.pending_cross_tangencies
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    after = services.kernel.sketches
    assert len(after) == 2 and not services.kernel.cross_sketch_tangencies
    path = tmp_path / "detached-pending.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after and not services.kernel.cross_sketch_tangencies
    reopened.bus.undo()
    assert services.kernel.sketches == before
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("existing_mixed", [False, True])
@pytest.mark.parametrize("change_topology", [False, True])
def test_pending_tangency_checks_saved_polyline_topology_during_mixed_edit(
    qtbot: QtBot, existing_mixed: bool, change_topology: bool
) -> None:
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.sketch_editor import MixedMoveState

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    frame = WorkPlaneFrame.xy()
    original = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)))
    previous = PolylineEntity(original.entity_id, ((-1, 0), (10, 0), (10, 5)))
    updated = PolylineEntity(
        original.entity_id,
        ((-2, 1), (10, 0), (10, 5), (15, 5)) if change_topology else ((-2, 0), (10, 0), (10, 5)),
    )
    sketch_id = uuid4().hex
    saved = Sketch(sketch_id, frame, (original,))
    prior = Sketch(sketch_id, frame, (previous,))
    candidate = Sketch(sketch_id, frame, (updated,))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    draft = Sketch(uuid4().hex, frame, (circle,))
    canvas = editor.canvas
    canvas.entities = [circle]
    if existing_mixed:
        canvas.mixed_move = MixedMoveState(uuid4().hex, 1, draft, (saved,), (prior,), (), ())
    pair = (SketchGeometryReference(original.entity_id, "segment", 0), circle.entity_id)
    canvas.pending_cross_tangencies = [pair]
    state = MixedMoveState(uuid4().hex, 1, draft, (saved,), (candidate,), (), ())
    canvas.apply_mixed_move(state, (circle,))
    assert canvas.pending_cross_tangencies == ([] if change_topology else [pair])
    assert ("暂存相切" in editor.status_label.text()) is change_topology
    assert canvas.undo_last_operation() and canvas.pending_cross_tangencies == [pair]
    assert canvas.redo_last_operation()
    assert canvas.pending_cross_tangencies == ([] if change_topology else [pair])


def test_pending_tangency_uses_latest_mixed_source_as_topology_baseline(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.sketch_editor import MixedMoveState

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    frame = WorkPlaneFrame.xy()
    original = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)))
    previous = PolylineEntity(original.entity_id, ((0, 0), (10, 0), (10, 5), (15, 5)))
    updated = PolylineEntity(original.entity_id, ((-1, 0), (10, 0), (10, 5), (15, 5)))
    sketch_id = uuid4().hex
    saved = Sketch(sketch_id, frame, (original,))
    prior = Sketch(sketch_id, frame, (previous,))
    candidate = Sketch(sketch_id, frame, (updated,))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    draft = Sketch(uuid4().hex, frame, (circle,))
    canvas = editor.canvas
    canvas.entities = [circle]
    canvas.mixed_move = MixedMoveState(uuid4().hex, 1, draft, (saved,), (prior,), (), ())
    pair = (SketchGeometryReference(original.entity_id, "segment", 0), circle.entity_id)
    canvas.pending_cross_tangencies = [pair]
    state = MixedMoveState(uuid4().hex, 1, draft, (saved,), (candidate,), (), ())
    canvas.apply_mixed_move(state, (circle,))
    assert canvas.pending_cross_tangencies == [pair]
    assert canvas.undo_last_operation() and canvas.pending_cross_tangencies == [pair]
    assert canvas.redo_last_operation() and canvas.pending_cross_tangencies == [pair]


def test_removed_pending_tangency_notice_survives_message_and_tracks_history(qtbot: QtBot) -> None:
    from mycad.core.cross_sketch_tangency import DraftConnectedEndpoint
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (-5, 0), (0, 0))
    arc = ArcEntity(uuid4().hex, (0, 1), 1, -90, 180)
    editor.set_context_sketches((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)),))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((arc,))
    pair = (
        DraftConnectedEndpoint(SketchGeometryReference(line.entity_id, "geometry"), "end"),
        DraftConnectedEndpoint(SketchGeometryReference(arc.entity_id, "geometry"), "start"),
    )
    canvas.pending_cross_tangencies = [pair]
    changed = ArcEntity(arc.entity_id, arc.center_mm, arc.radius_mm, -120, 210)
    assert canvas.replace_draft_entities((changed,))
    canvas.message = "操作完成。"
    canvas.changed.emit()
    assert "1 条" in editor.status_label.text() and "暂存相切" in editor.status_label.text()
    assert "撤销" in editor.status_label.text()
    assert canvas.undo_last_operation()
    assert "暂存相切" not in editor.status_label.text()
    assert canvas.redo_last_operation()
    assert "暂存相切" in editor.status_label.text()


def test_pending_tangency_notice_counts_all_and_clears_on_next_history_step(qtbot: QtBot) -> None:
    from mycad.core.cross_sketch_tangency import DraftConnectedEndpoint
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    lines = (LineEntity(uuid4().hex, (-5, 0), (0, 0)), LineEntity(uuid4().hex, (-10, 0), (0, 0)))
    arc = ArcEntity(uuid4().hex, (0, 1), 1, -90, 180)
    editor.set_context_sketches((Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines),))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((arc,))
    target = DraftConnectedEndpoint(SketchGeometryReference(arc.entity_id, "geometry"), "start")
    canvas.pending_cross_tangencies = [
        (DraftConnectedEndpoint(SketchGeometryReference(line.entity_id, "geometry"), "end"), target)
        for line in lines
    ]
    changed = ArcEntity(arc.entity_id, arc.center_mm, arc.radius_mm, -120, 210)
    assert canvas.replace_draft_entities((changed,))
    assert "2 条" in editor.status_label.text() and "暂存相切" in editor.status_label.text()
    extra = CircleEntity(uuid4().hex, (20, 20), 1)
    assert canvas.replace_draft_entities((changed, extra))
    assert "暂存相切" not in editor.status_label.text()
    assert canvas.undo_last_operation()
    assert "2 条" in editor.status_label.text() and "暂存相切" in editor.status_label.text()


@pytest.mark.parametrize("pending", [False, True])
def test_inferred_tangency_rebinds_unique_unchanged_draft_segment(
    qtbot: QtBot, pending: bool
) -> None:
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    canvas = editor.canvas
    if pending:
        editor.set_context_sketches((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,)),))
    assert canvas.replace_draft_entities((source,) if pending else (source, circle))
    old_ref = SketchGeometryReference(source.entity_id, "segment", 0)
    new_ref = SketchGeometryReference(source.entity_id, "segment", 1)
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (old_ref, SketchGeometryReference(circle.entity_id, "geometry")),
        source="inferred",
    )
    if pending:
        canvas.pending_cross_tangencies = [(circle.entity_id, old_ref)]
    else:
        canvas.constraints = [relation]
    changed = PolylineEntity(source.entity_id, ((-5, 0), (0, 0), (10, 0), (10, 5)))
    assert canvas.replace_draft_entities((changed,) if pending else (changed, circle))
    if pending:
        assert canvas.pending_cross_tangencies == [(circle.entity_id, new_ref)]
    else:
        assert (
            len(canvas.constraints) == 1
            and canvas.constraints[0].constraint_id == relation.constraint_id
        )
        assert canvas.constraints[0].references[0] == new_ref
    assert canvas.undo_last_operation()
    if pending:
        assert canvas.pending_cross_tangencies == [(circle.entity_id, old_ref)]
    else:
        assert canvas.constraints == [relation]
    assert canvas.redo_last_operation()
    if pending:
        assert canvas.pending_cross_tangencies == [(circle.entity_id, new_ref)]
    else:
        assert canvas.constraints[0].references[0] == new_ref


@pytest.mark.parametrize("pending", [False, True])
def test_rebound_curved_segment_keeps_connected_endpoint(qtbot: QtBot, pending: bool) -> None:
    from mycad.core.cross_sketch_tangency import DraftConnectedEndpoint
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (0, -5), (0, 0))
    canvas = editor.canvas
    if pending:
        editor.set_context_sketches((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)),))
    assert canvas.replace_draft_entities((source,) if pending else (source, line))
    line_ref = SketchGeometryReference(line.entity_id, "geometry")
    old_ref = SketchGeometryReference(source.entity_id, "segment", 0)
    new_ref = SketchGeometryReference(source.entity_id, "segment", 1)
    if pending:
        canvas.pending_cross_tangencies = [
            (DraftConnectedEndpoint(line_ref, "end"), DraftConnectedEndpoint(old_ref, "start"))
        ]
    else:
        relation = SketchConstraint(
            uuid4().hex,
            "tangent",
            (line_ref, old_ref),
            source="inferred",
            first_endpoint="end",
            second_endpoint="start",
        )
        canvas.constraints = [relation]
    changed = PolylineEntity(source.entity_id, ((0, 5), (0, 0), (10, 0), (10, 5)), bulges=(0, 1, 0))
    assert canvas.replace_draft_entities((changed,) if pending else (changed, line))
    if pending:
        assert canvas.pending_cross_tangencies == [
            (DraftConnectedEndpoint(line_ref, "end"), DraftConnectedEndpoint(new_ref, "start"))
        ]
    else:
        assert len(canvas.constraints) == 1 and canvas.constraints[0].references == (
            line_ref,
            new_ref,
        )
        assert (
            canvas.constraints[0].first_endpoint == "end"
            and canvas.constraints[0].second_endpoint == "start"
        )


@pytest.mark.parametrize("pending", [False, True])
def test_rebinding_rejects_duplicate_matching_segments(qtbot: QtBot, pending: bool) -> None:
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    canvas = editor.canvas
    if pending:
        editor.set_context_sketches((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,)),))
    assert canvas.replace_draft_entities((source,) if pending else (source, circle))
    ref = SketchGeometryReference(source.entity_id, "segment", 0)
    if pending:
        canvas.pending_cross_tangencies = [(circle.entity_id, ref)]
    else:
        canvas.constraints = [
            SketchConstraint(
                uuid4().hex,
                "tangent",
                (ref, SketchGeometryReference(circle.entity_id, "geometry")),
                source="inferred",
            )
        ]
    changed = PolylineEntity(source.entity_id, ((0, 0), (10, 0), (0, 0), (10, 0), (10, 5)))
    assert canvas.replace_draft_entities((changed,) if pending else (changed, circle))
    assert not (canvas.pending_cross_tangencies if pending else canvas.constraints)
    assert canvas.undo_last_operation()
    assert canvas.pending_cross_tangencies if pending else canvas.constraints


def test_rebound_pending_curved_segment_commits_and_replays(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import DraftConnectedEndpoint, validate_tangency_component
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, -5), (0, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before = services.kernel.sketches
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)), bulges=(1, 0))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    line_ref = SketchGeometryReference(line.entity_id, "geometry")
    old_ref = SketchGeometryReference(source.entity_id, "segment", 0)
    canvas.pending_cross_tangencies = [
        (DraftConnectedEndpoint(line_ref, "end"), DraftConnectedEndpoint(old_ref, "start"))
    ]
    changed = PolylineEntity(source.entity_id, ((0, 5), (0, 0), (10, 0), (10, 5)), bulges=(0, 1, 0))
    assert canvas.replace_draft_entities((changed,))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert len(relations) == 1
    relation = relations[0]
    ref = relation.first if relation.first.entity_id == source.entity_id else relation.second
    assert ref.segment_index == 1
    assert relation.first_endpoint is not None and relation.second_endpoint is not None
    validate_tangency_component(after, relations, saved.sketch_id)
    path = tmp_path / "rebound-draft-segment.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.sketches == before and not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


def test_rebound_local_curved_segment_saves_and_replays(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, -5), (0, 0))
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)), bulges=(1, 0))
    line_ref = SketchGeometryReference(line.entity_id, "geometry")
    old_ref = SketchGeometryReference(source.entity_id, "segment", 0)
    new_ref = SketchGeometryReference(source.entity_id, "segment", 1)
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source, line))
    canvas.constraints = [
        SketchConstraint(
            uuid4().hex,
            "tangent",
            (line_ref, old_ref),
            source="inferred",
            first_endpoint="end",
            second_endpoint="start",
        )
    ]
    changed = PolylineEntity(source.entity_id, ((0, 5), (0, 0), (10, 0), (10, 5)), bulges=(0, 1, 0))
    assert canvas.replace_draft_entities((changed, line))
    assert len(canvas.constraints) == 1 and canvas.constraints[0].references == (line_ref, new_ref)
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    after = services.kernel.sketches
    assert len(after) == 1 and after[0].constraints[0].references == (line_ref, new_ref)
    path = tmp_path / "rebound-local-segment.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert not services.kernel.sketches
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("shift_index", [False, True])
def test_pending_saved_source_segment_rebinds_during_mixed_edit(
    qtbot: QtBot, shift_index: bool
) -> None:
    from mycad.core.cross_sketch_tangency import DraftConnectedEndpoint
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.sketch_editor import MixedMoveState

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    frame = WorkPlaneFrame.xy()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)), bulges=(1, 0))
    changed = PolylineEntity(
        source.entity_id,
        ((0, 5), (0, 0), (10, 0), (10, 5)) if shift_index else ((0, 0), (10, 0), (10, 5), (15, 5)),
        bulges=(0, 1, 0) if shift_index else (1, 0, 0),
    )
    line = LineEntity(uuid4().hex, (0, -5), (0, 0))
    saved = Sketch(uuid4().hex, frame, (source,))
    revised = Sketch(saved.sketch_id, frame, (changed,))
    draft = Sketch(uuid4().hex, frame, (line,))
    old_ref = SketchGeometryReference(source.entity_id, "segment", 0)
    new_ref = SketchGeometryReference(source.entity_id, "segment", 1 if shift_index else 0)
    target = DraftConnectedEndpoint(SketchGeometryReference(line.entity_id, "geometry"), "end")
    old_pair = (DraftConnectedEndpoint(old_ref, "start"), target)
    new_pair = (DraftConnectedEndpoint(new_ref, "start"), target)
    canvas = editor.canvas
    canvas.entities = [line]
    canvas.pending_cross_tangencies = [old_pair]
    state = MixedMoveState(uuid4().hex, 1, draft, (saved,), (revised,), (), ())
    canvas.apply_mixed_move(state, (line,))
    assert canvas.pending_cross_tangencies == [new_pair]
    assert canvas.undo_last_operation() and canvas.pending_cross_tangencies == [old_pair]
    assert canvas.redo_last_operation() and canvas.pending_cross_tangencies == [new_pair]


@pytest.mark.parametrize("shift_index", [False, True])
def test_mixed_preview_rebinds_saved_source_and_commits(
    qtbot: QtBot, tmp_path: Path, shift_index: bool
) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import DraftConnectedEndpoint
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)), bulges=(1, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    line = LineEntity(uuid4().hex, (0, -5), (0, 0))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((line,))
    old_ref = SketchGeometryReference(source.entity_id, "segment", 0)
    new_ref = SketchGeometryReference(source.entity_id, "segment", 1 if shift_index else 0)
    target = DraftConnectedEndpoint(SketchGeometryReference(line.entity_id, "geometry"), "end")
    old_pair = (DraftConnectedEndpoint(old_ref, "start"), target)
    new_pair = (DraftConnectedEndpoint(new_ref, "start"), target)
    canvas.pending_cross_tangencies = [old_pair]
    changed = PolylineEntity(
        source.entity_id,
        ((0, 5), (0, 0), (10, 0), (10, 5)) if shift_index else ((0, 0), (10, 0), (10, 5), (15, 5)),
        bulges=(0, 1, 0) if shift_index else (1, 0, 0),
    )
    overlay = tuple(
        (changed if entity.entity_id == source.entity_id else entity, layer)
        for entity, layer in canvas.background_entities
    )
    canvas.committed_drag_trim_requested.emit(
        ((source.entity_id, (changed,)),),
        tuple(canvas.entities),
        tuple(canvas.constraints),
        overlay,
        loaded.document.revision,
    )
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert canvas.mixed_move is not None, editor.status_label.text()
    assert canvas.pending_cross_tangencies == [new_pair]
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert len(relations) == 1 and relations[0].first.segment_index == (1 if shift_index else 0)
    path = tmp_path / f"mixed-source-rebind-{shift_index}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.cross_sketch_tangencies[0].first.segment_index == 0
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


def test_saved_edit_rebinds_committed_tangency_and_replays(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, line.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    current = next(sketch for sketch in before if sketch.sketch_id == first.sketch_id)
    original = current.entities[0]
    assert isinstance(original, PolylineEntity)
    changed = PolylineEntity(
        original.entity_id, ((-5, 0), *original.points_mm), bulges=(0, *original.bulges)
    )
    canvas = editor.canvas
    overlay = tuple(
        (changed if entity.entity_id == source.entity_id else entity, layer)
        for entity, layer in canvas.background_entities
    )
    canvas.committed_drag_trim_requested.emit(
        ((source.entity_id, (changed,)),), (), (), overlay, loaded.document.revision
    )
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert tuple(loaded.document.commands) != history, editor.status_label.text()
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert len(relations) == 1 and relations[0].relation_id == relation.relation_id
    assert relations[0].first.segment_index == 1
    path = tmp_path / "saved-committed-rebind.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.sketches == before and services.kernel.cross_sketch_tangencies == (
        relation,
    )
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


def test_mixed_edit_rebinds_committed_tangency_and_replays(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, line.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before = services.kernel.sketches
    current = next(sketch for sketch in before if sketch.sketch_id == first.sketch_id)
    original = current.entities[0]
    assert isinstance(original, PolylineEntity)
    changed = PolylineEntity(
        original.entity_id, ((-5, 0), *original.points_mm), bulges=(0, *original.bulges)
    )
    canvas = editor.canvas
    draft = CircleEntity(uuid4().hex, (30, 30), 1)
    assert canvas.replace_draft_entities((draft,))
    overlay = tuple(
        (changed if entity.entity_id == source.entity_id else entity, layer)
        for entity, layer in canvas.background_entities
    )
    canvas.committed_drag_trim_requested.emit(
        ((source.entity_id, (changed,)),),
        tuple(canvas.entities),
        (),
        overlay,
        loaded.document.revision,
    )
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert canvas.mixed_move is not None, editor.status_label.text()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert len(relations) == 1 and relations[0].relation_id == relation.relation_id
    assert relations[0].first.segment_index == 1
    path = tmp_path / "mixed-committed-rebind.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("other_arc_changed", [False, True])
def test_closed_polyline_rotated_start_rebinds_tangent_segment(
    qtbot: QtBot, pending: bool, other_arc_changed: bool
) -> None:
    from dataclasses import replace

    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    polyline = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, 10), (0, 10)),
        True,
        bulges=(0, 0, 0.2, 0) if other_arc_changed else (),
    )
    circle = CircleEntity(uuid4().hex, (5, 5), 5)
    canvas = editor.canvas
    if pending:
        editor.set_context_sketches((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,)),))
    assert canvas.replace_draft_entities((polyline,) if pending else (polyline, circle))
    old_ref = SketchGeometryReference(polyline.entity_id, "segment", 0)
    new_ref = SketchGeometryReference(polyline.entity_id, "segment", 3)
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (old_ref, SketchGeometryReference(circle.entity_id, "geometry")),
        source="inferred",
    )
    if pending:
        canvas.pending_cross_tangencies = [(circle.entity_id, old_ref)]
    else:
        canvas.constraints = [relation]
    rotated = replace(
        polyline,
        points_mm=(*polyline.points_mm[1:], polyline.points_mm[0]),
        bulges=(0, 0.3, 0, 0) if other_arc_changed else (),
    )
    assert canvas.replace_draft_entities((rotated,) if pending else (rotated, circle))
    if pending:
        assert canvas.pending_cross_tangencies == [(circle.entity_id, new_ref)]
    else:
        assert len(canvas.constraints) == 1 and canvas.constraints[0].references[0] == new_ref
    assert canvas.undo_last_operation()
    if pending:
        assert canvas.pending_cross_tangencies == [(circle.entity_id, old_ref)]
    else:
        assert canvas.constraints == [relation]
    assert canvas.redo_last_operation()
    if pending:
        assert canvas.pending_cross_tangencies == [(circle.entity_id, new_ref)]
    else:
        assert canvas.constraints[0].references[0] == new_ref


def test_saved_closed_polyline_rotation_rebinds_committed_relation(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True)
    circle = CircleEntity(uuid4().hex, (5, 5), 5)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, polyline.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    current = next(item for item in before if item.sketch_id == first.sketch_id)
    source = current.entities[0]
    assert isinstance(source, PolylineEntity)
    rotated = replace(
        source,
        points_mm=(*source.points_mm[1:], source.points_mm[0]),
        bulges=(*source.bulges[1:], source.bulges[0]) if source.bulges else (),
    )
    canvas = editor.canvas
    overlay = tuple(
        (rotated if entity.entity_id == source.entity_id else entity, layer)
        for entity, layer in canvas.background_entities
    )
    canvas.committed_drag_trim_requested.emit(
        ((source.entity_id, (rotated,)),), (), (), overlay, loaded.document.revision
    )
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert tuple(loaded.document.commands) != history, editor.status_label.text()
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert (
        len(relations) == 1
        and relations[0].relation_id == relation.relation_id
        and relations[0].first.segment_index == 3
    )
    path = tmp_path / "rotated-closed-committed.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.sketches == before and services.kernel.cross_sketch_tangencies == (
        relation,
    )
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


@pytest.mark.parametrize("rotate", [False, True])
def test_inferred_polyline_vertex_coincidence_rebinds_after_reindex(
    qtbot: QtBot, rotate: bool
) -> None:
    from dataclasses import replace

    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    source = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, 10), (0, 10)) if rotate else ((0, 0), (10, 0), (10, 10)),
        rotate,
    )
    line = LineEntity(uuid4().hex, (0, 0), (-5, 0))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source, line))
    old_ref = SketchGeometryReference(source.entity_id, "vertex", 0)
    new_ref = SketchGeometryReference(source.entity_id, "vertex", 3 if rotate else 1)
    other = SketchGeometryReference(line.entity_id, "start")
    relation = SketchConstraint(uuid4().hex, "coincident", (old_ref, other), source="inferred")
    canvas.constraints = [relation]
    changed = replace(
        source,
        points_mm=(*source.points_mm[1:], source.points_mm[0])
        if rotate
        else ((-5, -5), *source.points_mm),
    )
    assert canvas.replace_draft_entities((changed, line))
    assert (
        len(canvas.constraints) == 1
        and canvas.constraints[0].constraint_id == relation.constraint_id
    )
    assert canvas.constraints[0].references == (new_ref, other)
    assert canvas.undo_last_operation() and canvas.constraints == [relation]
    assert canvas.redo_last_operation() and canvas.constraints[0].references == (new_ref, other)


@pytest.mark.parametrize("case", ["duplicate", "moved"])
def test_inferred_polyline_vertex_rebinding_rejects_ambiguous_or_changed_vertex(
    qtbot: QtBot, case: str
) -> None:
    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    line = LineEntity(uuid4().hex, (0, 0), (-5, 0))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source, line))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(source.entity_id, "vertex", 0),
            SketchGeometryReference(line.entity_id, "start"),
        ),
        source="inferred",
    )
    canvas.constraints = [relation]
    points = (
        ((-5, -5), (0, 0), (10, 0), (0, 0), (10, 10))
        if case == "duplicate"
        else ((-5, -5), (1, 0), (10, 0), (10, 10))
    )
    changed = PolylineEntity(source.entity_id, points)
    assert canvas.replace_draft_entities((changed, line))
    assert not canvas.constraints
    assert canvas.undo_last_operation() and canvas.constraints == [relation]


def test_mixed_draft_vertex_rebinding_saves_and_replays(qtbot: QtBot, tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved_line = LineEntity(uuid4().hex, (20, 0), (30, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    line = LineEntity(uuid4().hex, (0, 0), (-5, 0))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source, line))
    old_ref = SketchGeometryReference(source.entity_id, "vertex", 0)
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (old_ref, SketchGeometryReference(line.entity_id, "start")),
        source="inferred",
    )
    canvas.constraints = [relation]
    moved = replace(saved_line, start_mm=(21, 0), end_mm=(31, 0))
    overlay = tuple(
        (moved if entity.entity_id == saved_line.entity_id else entity, layer)
        for entity, layer in canvas.background_entities
    )
    canvas.committed_drag_trim_requested.emit(
        ((saved_line.entity_id, (moved,)),),
        tuple(canvas.entities),
        tuple(canvas.constraints),
        overlay,
        loaded.document.revision,
    )
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert canvas.mixed_move is not None, editor.status_label.text()
    changed = replace(source, points_mm=((-5, -5), *source.points_mm))
    assert canvas.replace_draft_entities((changed, line))
    new_ref = SketchGeometryReference(source.entity_id, "vertex", 1)
    assert canvas.constraints[0].references[0] == new_ref
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    after = services.kernel.sketches
    draft = next(
        sketch
        for sketch in after
        if any(entity.entity_id == source.entity_id for entity in sketch.entities)
    )
    assert draft.constraints[0].references[0] == new_ref
    assert any(
        command.id == "drawing.sketch.revise" and command.version == 10
        for command in loaded.document.commands
    )
    path = tmp_path / "mixed-vertex-rebound.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    restored = next(
        sketch for sketch in services.kernel.sketches if sketch.sketch_id == draft.sketch_id
    )
    assert restored.constraints[0].references[0] == old_ref
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_draft_rectangle_circle_notrim_tangencies_replay(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import RectangleEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    rectangle = RectangleEntity(uuid4().hex, (-20, 0), (20, -10))
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    assert editor.canvas.replace_draft_entities((rectangle, circle))
    for value in ("FILLET", "R", "2", "T", "N"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    for point in ((-3, 0), (-1.3, 3.5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert len([item for item in editor.canvas.constraints if item.kind == "tangent"]) == 2
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    loaded = window.loaded_document()
    assert loaded is not None and loaded.document.commands[-1].version == 27
    result = services.kernel.sketches
    assert result[0].entities[:2] == (rectangle, circle)
    path = tmp_path / "rectangle-circle-tangency.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == result
    reopened.bus.undo()
    assert not reopened_services.kernel.sketches
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == result


def test_saved_rectangle_whole_notrim_tangencies_replay(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.persistence import save_document
    from mycad.core.sketch import RectangleEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    rectangle = RectangleEntity(uuid4().hex, (-10, 0), (10, -10))
    assert editor.canvas.replace_draft_entities((rectangle,))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    for value in ("FILLET", "R", "2", "T", "N", "P"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 0))
    )
    assert len(editor.canvas.entities) == 4
    assert len(editor.canvas.pending_cross_tangencies) == 8
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    loaded = window.loaded_document()
    assert loaded is not None and loaded.document.commands[-1].version == 27
    result, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert len(relations) == 8
    validate_tangency_component(result, relations, relations[0].first.sketch_id)
    current = window.active_sketch_dialog()
    assert current is not None
    count = len(loaded.document.commands)
    current.canvas.committed_move_requested.emit((rectangle.entity_id,), (0.0, 1.0))
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == count + 1, current.status_label.text()
    validate_tangency_component(services.kernel.sketches, relations, relations[0].first.sketch_id)
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count, timeout=10000
    )
    assert services.kernel.sketches == result
    path = tmp_path / "rectangle-whole-notrim.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == result
    assert reopened_services.kernel.cross_sketch_tangencies == relations
    reopened.bus.undo()
    assert not reopened_services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert reopened_services.kernel.cross_sketch_tangencies == relations


@pytest.mark.parametrize("saved_rectangle", [False, True])
@pytest.mark.parametrize("operation", ["rotate90", "rotate45", "mirror"])
def test_mixed_rectangle_circle_notrim_tangencies_replay(
    qtbot: QtBot, tmp_path: Path, saved_rectangle: bool, operation: str
) -> None:
    from copy import deepcopy
    from typing import cast

    from mycad import app
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import RectangleEntity, Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    rectangle = RectangleEntity(uuid4().hex, (-20, 0), (20, -10))
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    saved, draft = (rectangle, circle) if saved_rectangle else (circle, rectangle)
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    assert editor.canvas.replace_draft_entities((draft,))
    for value in ("FILLET", "R", "2", "T", "N"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    for point in ((-3, 0), (-1.3, 3.5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert len(editor.canvas.pending_cross_tangencies) == 1
    assert len([item for item in editor.canvas.constraints if item.kind == "tangent"]) == 1
    initial_draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        tuple(editor.canvas.entities),
        tuple(editor.canvas.constraints),
        editor.canvas.layer_table,
    )
    initial_relation_id = app.draft_cross_relations(
        services.kernel.sketches, initial_draft, tuple(editor.canvas.pending_cross_tangencies)
    )[0].relation_id
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {rectangle.entity_id, circle.entity_id}
    if operation == "mirror":
        editor.mirror_keep_source_check.setChecked(False)
        editor.transform_buttons["mirror"].click()
        editor.canvas.add_coordinate_point((0, 0), exact_point=True)
        editor.canvas.add_coordinate_point((1, 0), exact_point=True)
    else:
        for value in ("ROTATE", "0,0", "45" if operation == "rotate45" else "90"):
            editor.drawing_command_bar.input.setText(value)
            QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.mixed_move is not None, editor.status_label.text()
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.redo_last_operation()
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {rectangle.entity_id, circle.entity_id}
    for value in ("MOVE", "0,0", "1,2"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(editor.canvas.mixed_move_timeline()) == 2, editor.status_label.text()
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert any(command.version in (29, 30) for command in loaded.document.commands[-2:])
    result, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    transform_params = loaded.document.commands[-2].params
    assert len(relations) == 1
    assert relations[0].relation_id == initial_relation_id
    validate_tangency_component(result, relations, relations[0].first.sketch_id)
    path = tmp_path / "mixed-rectangle-notrim.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == result
    reopened.bus.undo()
    assert len(reopened_services.kernel.cross_sketch_tangencies) == 1
    reopened.bus.undo()
    assert len(reopened_services.kernel.cross_sketch_tangencies) == 1
    if not saved_rectangle:
        with pytest.raises(ValidationError):
            reopened.bus.execute("drawing.sketch.revise", transform_params, "local", version=29)
        altered = deepcopy(transform_params)
        proofs = cast("list[dict[str, object]]", altered["rectangle_transforms"])
        proofs[0]["matrix"] = [1, 0, 0, 1, 0, 0]
        with pytest.raises(ValidationError):
            reopened.bus.execute("drawing.sketch.revise", altered, "local", version=30)
    reopened.bus.undo()
    assert not reopened_services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    reopened.bus.redo()
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == result
    assert reopened_services.kernel.cross_sketch_tangencies == relations
