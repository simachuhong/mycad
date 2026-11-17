# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent 2D command input uses explicit, replayable coordinates."""

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from mycad.ui.drawing2d_command_bar import parse_coordinate


def test_scale_toolbar_and_canvas_keyboard_reference_copy(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    editor.transform_buttons["scale"].click()
    assert canvas.active_transform == "scale"
    bar = editor.drawing_command_bar.input
    bar.setText("0,0")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.keyClick(canvas, Qt.Key.Key_C)
    QTest.keyClick(canvas, Qt.Key.Key_R)
    QTest.keyClicks(canvas, "2")
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    QTest.keyClicks(canvas, "6")
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2 and canvas.entities[0] == line
    copied = canvas.entities[1]
    assert isinstance(copied, LineEntity)
    assert copied.start_mm == (3, 0) and copied.end_mm == (9, 0)


def test_scale_command_scales_preselected_draft_and_undoes(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("SC", "0,0", "2"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.entities == [LineEntity(line.entity_id, (2, 0), (6, 0))]
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == [line]


def test_scale_reference_target_points_from_canvas_keyboard(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("SCALE", "0,0", "R", "2"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.keyClick(canvas, Qt.Key.Key_P)
    assert canvas.scale_target_points_active
    for value in ("10,10", "16,10"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.entities == [LineEntity(line.entity_id, (3, 0), (9, 0))]


def test_scale_reference_mouse_preview_cancel_preserves_geometry(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("SCALE", "0,0", "R", "10"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    point = canvas.local_to_screen((20, 0))
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(point),
            QPointF(canvas.mapToGlobal(point)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    qtbot.waitUntil(lambda: bool(canvas.transform_preview_entities), timeout=5000)
    preview = canvas.transform_preview_entities
    assert len(preview) == 1 and isinstance(preview[0], LineEntity)
    assert preview[0].end_mm == pytest.approx((6, 0), abs=0.1)
    assert "参考缩放" in canvas.message and "目标长度" in canvas.message
    assert canvas.entities == [line]
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.entities == [line] and not canvas.transform_preview_entities


def test_scale_copy_keeps_original_and_undoes_as_one_step(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("SCALE", "0,0", "C", "2"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 2 and editor.canvas.entities[0] == line
    copied = editor.canvas.entities[1]
    assert isinstance(copied, LineEntity) and copied.start_mm == (2, 0) and copied.end_mm == (6, 0)
    assert copied.entity_id != line.entity_id
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == [line]


@pytest.mark.parametrize("first_factor", ["2", "2,0"])
def test_scale_enter_reuses_last_factor_and_cancel_keeps_it(
    qtbot: QtBot, first_factor: str
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("SC", "0,0", first_factor, "SC", "0,0"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.keyClick(bar, Qt.Key.Key_Escape)
    assert canvas.scale_default_factor == 2
    for value in ("SC", "0,0", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.entities == [LineEntity(line.entity_id, (4, 0), (12, 0))]


def test_scale_enter_default_copy_and_editor_continuation(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("SC", "0,0", "C"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2 and canvas.entities[0] == line
    copied = canvas.entities[1]
    assert isinstance(copied, LineEntity) and copied.entity_id != line.entity_id
    assert copied.start_mm == line.start_mm and copied.end_mm == line.end_mm
    canvas.scale_default_factor = 2.5
    next_editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(next_editor)
    next_editor.continue_workspace_from(editor)
    assert next_editor.canvas.scale_default_factor == 2.5


def test_scale_canvas_invalid_factor_can_be_corrected(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("SC", "0,0"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.keyClicks(canvas, "0")
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas.entities == [line] and canvas.scale_center == (0, 0)
    assert "正数" in canvas.message
    QTest.keyClick(canvas, Qt.Key.Key_Backspace)
    QTest.keyClicks(canvas, "2")
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas.entities == [LineEntity(line.entity_id, (2, 0), (6, 0))]


def test_scale_reference_numeric_lengths_and_copy(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("SCALE", "0,0", "C", "R", "2", "6"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 2 and editor.canvas.entities[0] == line
    copied = editor.canvas.entities[1]
    assert isinstance(copied, LineEntity) and copied.start_mm == (3, 0) and copied.end_mm == (9, 0)


def test_scale_reference_two_points_and_numeric_target(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("SCALE", "0,0", "R", "10,10", "12,10", "6"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.entities == [LineEntity(line.entity_id, (3, 0), (9, 0))]


def test_scale_reference_accepts_target_point(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("SCALE", "0,0", "R", "2", "6,0"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.entities == [LineEntity(line.entity_id, (3, 0), (9, 0))]


def test_scale_reference_target_two_points(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("SCALE", "0,0", "R", "2", "P", "10,10", "16,10"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.entities == [LineEntity(line.entity_id, (3, 0), (9, 0))]


@pytest.mark.parametrize("invalid", ["0", "-1", "nan", "inf"])
def test_scale_invalid_factor_preserves_selection_and_allows_retry(
    qtbot: QtBot, invalid: str
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("SCALE", "0,0", invalid):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.entities == [line] and editor.canvas.scale_center == (0, 0)
    assert editor.canvas.selected_entity_ids == {line.entity_id}
    bar.setText("2")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.entities == [LineEntity(line.entity_id, (2, 0), (6, 0))]


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
    assert bar.input.text() == "REC"
    commit = QInputMethodEvent()
    commit.setCommitString("中")
    QCoreApplication.sendEvent(bar.input, commit)
    assert bar.input.text() == "REC中"


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
    if command == "MI":
        assert editor.canvas.awaiting_mirror_erase
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


def test_offset_command_distance_side_repeat_and_escape(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar
    for text in ("O", "0"):
        command.input.setText(text)
        QTest.keyClick(command.input, Qt.Key.Key_Return)
    assert canvas.interactive_offset_needs_distance
    assert canvas.entities == [line]
    command.input.setText("2")
    QTest.keyClick(command.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    command.input.setText("10,4")
    QTest.keyClick(command.input, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2
    copy = canvas.entities[1]
    assert isinstance(copy, LineEntity) and copy.start_mm == pytest.approx((0, 2))
    QTest.keyClick(command.input, Qt.Key.Key_Escape)
    assert canvas.active_transform is None
    assert canvas.entities == [line, copy]
    QTest.keyClick(command.input, Qt.Key.Key_Return)
    assert canvas.interactive_offset_needs_distance


def test_offset_through_point_creates_preview_and_undo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "T"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not canvas.interactive_offset_needs_distance
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    QTest.mouseMove(canvas, canvas.local_to_screen((10, 5)))
    qtbot.wait(50)
    pixel = canvas.local_to_screen((10, 3))
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

    def latest_preview_ready() -> bool:
        entities = canvas.transform_preview_entities
        return (
            len(entities) == 1
            and isinstance(entities[0], LineEntity)
            and entities[0].start_mm[1] == pytest.approx(3, abs=0.2)
        )

    qtbot.waitUntil(latest_preview_ready)
    preview = canvas.transform_preview_entities[0]
    assert isinstance(preview, LineEntity) and preview.start_mm == pytest.approx((0, 3), abs=0.2)
    command.setText("10,3")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2 and isinstance(canvas.entities[1], LineEntity)
    assert canvas.entities[1].start_mm == pytest.approx((0, 3))
    QTest.keyClick(command, Qt.Key.Key_Escape)
    assert canvas.undo_last_operation() and canvas.entities == [line]


def test_offset_through_point_polyline_uses_finite_result(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import PolylineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "T"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    command.setText("5,2")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2 and isinstance(canvas.entities[1], PolylineEntity)
    assert canvas.entities[1].points_mm[0] == pytest.approx((0, 2))


def test_offset_distance_from_two_explicit_points(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "0,0", "@3,4"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not canvas.interactive_offset_needs_distance
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    command.setText("10,8")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2 and isinstance(canvas.entities[1], LineEntity)
    assert canvas.entities[1].start_mm == pytest.approx((0, 5))


def test_offset_distance_points_reject_zero_and_allow_retry(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    command.setText("OFFSET")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    assert canvas.interactive_offset_needs_distance
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.interactive_offset_needs_distance
    assert "量距第二点" in editor.drawing_command_bar.status.text()
    command.setText("@0,0")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.interactive_offset_needs_distance and canvas.entities == [line]
    command.setText("@0,5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert not canvas.interactive_offset_needs_distance
    assert canvas.offset_default_distance == pytest.approx(5)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    command.setText("10,8")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2 and isinstance(canvas.entities[1], LineEntity)
    assert canvas.entities[1].start_mm == pytest.approx((0, 5))


@pytest.mark.parametrize("mode", ("source", "current"))
@pytest.mark.parametrize("saved", (False, True))
def test_offset_layer_option_uses_selected_destination(
    qtbot: QtBot, mode: str, saved: bool
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    layers = editor.layer_table.add(SketchLayer("source")).add(SketchLayer("destination"))
    editor.layer_table = layers
    editor.canvas.set_layer_table(layers, "destination")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0), layer_name="source")
    if saved:
        editor.set_context_sketches(
            (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), layers=layers),)
        )
        editor.canvas.set_layer_table(layers, "destination")
    else:
        assert editor.canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "L", "C" if mode == "current" else "S", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    position = editor.canvas.local_to_screen((10, 5))
    QApplication.sendEvent(
        editor.canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(position),
            QPointF(editor.canvas.mapToGlobal(position)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert len(editor.canvas.transform_preview_entities) == 1
    expected = "destination" if mode == "current" else "source"
    assert editor.canvas.transform_preview_entities[0].layer_name == expected
    command.setText("10,5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    result = editor.canvas.entities[-1]
    assert isinstance(result, LineEntity) and result.layer_name == expected
    QTest.keyClick(command, Qt.Key.Key_Escape)
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == ([] if saved else [line])
    assert editor.canvas.redo_last_operation() and editor.canvas.entities[-1] == result


def test_offset_current_layer_locked_rejects_without_changing_geometry(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    layers = editor.layer_table.add(SketchLayer("source")).add(SketchLayer("locked", locked=True))
    editor.layer_table = layers
    editor.canvas.set_layer_table(layers, "locked")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0), layer_name="source")
    assert editor.canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "L", "C", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    command.setText("10,5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.entities == [line]
    assert "锁定" in editor.canvas.message


def test_offset_layer_option_retry_default_and_workspace_continuity(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "L", "C"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.offset_layer_current
    QTest.keyClick(command, Qt.Key.Key_Escape)
    command.setText("OFFSET")
    QTest.keyClick(command, Qt.Key.Key_Return)
    command.setText("L")
    QTest.keyClick(command, Qt.Key.Key_Return)
    command.setText("invalid")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.offset_layer_pending and editor.canvas.offset_layer_current
    command.clear()
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert not editor.canvas.offset_layer_pending and editor.canvas.offset_layer_current
    QTest.keyClick(command, Qt.Key.Key_Escape)
    next_editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(next_editor)
    next_editor.continue_workspace_from(editor)
    assert next_editor.canvas.offset_layer_current


@pytest.mark.parametrize("through", [False, True])
@pytest.mark.parametrize("erase", [False, True])
def test_offset_multiple_and_command_undo(qtbot: QtBot, through: bool, erase: bool) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input

    def send(value: str) -> None:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)

    send("OFFSET")
    if erase:
        send("E")
        send("Y")
    send("T" if through else "2")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    send("M")
    send("10,2")
    first = tuple(canvas.entities)
    send("10,4")
    assert isinstance(canvas.entities[-1], LineEntity)
    assert canvas.entities[-1].start_mm == pytest.approx((0, 4))
    send("U")
    assert tuple(canvas.entities) == first
    send("U")
    assert canvas.entities == [line]
    send("U")
    assert canvas.entities == [line]
    assert canvas.active_transform == "offset"


@pytest.mark.parametrize("exit_option", ["X", "EXIT"])
def test_offset_exit_option_keeps_completed_offsets(qtbot: QtBot, exit_option: str) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    for value in ("M", "10,2", exit_option):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.active_transform is None
    assert len(canvas.entities) == 2
    assert canvas.undo_last_operation() and canvas.entities == [line]


def test_offset_erase_enter_keeps_current_choice(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "E", "Y", "E", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not editor.canvas.offset_erase_pending
    assert editor.canvas.offset_erase_source


def test_offset_enter_reuses_session_distance_or_through(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input

    def send(value: str) -> None:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)

    send("OFFSET")
    send("")
    assert not editor.canvas.interactive_offset_needs_distance
    assert "通过点偏移" in editor.canvas.message
    QTest.keyClick(command, Qt.Key.Key_Escape)
    send("OFFSET")
    send("3")
    QTest.keyClick(command, Qt.Key.Key_Escape)
    next_editor = SketchEditorDialog()
    qtbot.addWidget(next_editor)
    next_editor.continue_workspace_from(editor)
    next_editor.show()
    next_command = next_editor.drawing_command_bar.input
    for value in ("OFFSET", ""):
        next_command.setText(value)
        QTest.keyClick(next_command, Qt.Key.Key_Return)
    assert next_editor.canvas.offset_default_distance == 3
    assert not next_editor.canvas.interactive_offset_needs_distance
    QTest.keyClick(next_command, Qt.Key.Key_Escape)
    for value in ("OFFSET", "T"):
        next_command.setText(value)
        QTest.keyClick(next_command, Qt.Key.Key_Return)
    QTest.keyClick(next_command, Qt.Key.Key_Escape)
    for value in ("OFFSET", ""):
        next_command.setText(value)
        QTest.keyClick(next_command, Qt.Key.Key_Return)
    assert "通过点偏移" in next_editor.canvas.message


@pytest.mark.parametrize("gap_type", [0, 1, 2])
@pytest.mark.parametrize("through", [False, True])
def test_offsetgaptype_changes_polyline_preview_and_result(
    qtbot: QtBot, gap_type: int, through: bool
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad.core.sketch import PolylineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert editor.canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSETGAPTYPE", str(gap_type), "OFFSET", "T" if through else "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    pixel = editor.canvas.local_to_screen((5, -2))
    QApplication.sendEvent(
        editor.canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(pixel),
            QPointF(editor.canvas.mapToGlobal(pixel)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    preview = editor.canvas.transform_preview_entities
    assert len(preview) == 1 and isinstance(preview[0], PolylineEntity)
    assert len(preview[0].points_mm) == (3 if gap_type == 0 else 4)
    command.setText("5,-2" if through else "5,-5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    result = editor.canvas.entities[-1]
    assert isinstance(result, PolylineEntity)
    assert len(result.points_mm) == (3 if gap_type == 0 else 4)
    assert bool(result.bulges) == (gap_type == 1)


@pytest.mark.parametrize("gap_type", [1, 2])
def test_offsetgaptype_multiple_repeats_generated_polyline(qtbot: QtBot, gap_type: int) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import PolylineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert editor.canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSETGAPTYPE", str(gap_type), "OFFSET", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    for value in ("M", "5,-3", "5,-6"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 3, editor.canvas.message
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 2


@pytest.mark.parametrize("through", [False, True])
@pytest.mark.parametrize("gap_type", [1, 2])
def test_offsetgaptype_joins_non_smooth_line_arc_path(
    qtbot: QtBot, through: bool, gap_type: int
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import ArcEntity, LineEntity, PolylineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (5, 5)), bulges=(0, 2**0.5 - 1))
    assert editor.canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSETGAPTYPE", str(gap_type), "OFFSET", "T" if through else "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    command.setText("5,-1" if through else "5,-3")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 2, editor.canvas.message
    result = editor.canvas.entities[-1]
    assert isinstance(result, PolylineEntity)
    segments = polyline_curve_segments(result.points_mm, result.bulges, False, result.entity_id)
    assert len(segments) == 3
    if gap_type == 1:
        assert isinstance(segments[1], ArcEntity)
        assert segments[1].radius_mm == pytest.approx(1)
    else:
        assert isinstance(segments[1], LineEntity)


@pytest.mark.parametrize("gap_type", [1, 2])
def test_offsetgaptype_saved_source_roundtrips_and_undoes(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gap_type: int
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

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
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert editor.canvas.replace_draft_entities((source,))
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    editor = window.active_sketch_dialog()
    assert editor is not None
    command = editor.drawing_command_bar.input
    for value in ("OFFSETGAPTYPE", str(gap_type), "OFFSET", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    command.setText("5,-5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    result = editor.canvas.entities[0]
    assert isinstance(result, PolylineEntity) and len(result.points_mm) == 4
    QTest.keyClick(command, Qt.Key.Key_Escape)
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    path = tmp_path / f"offset-gap-{gap_type}.mc.json"

    def choose(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getOpenFileName", choose)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: path.exists() and not unit.is_busy)
    before_open = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not before_open and not unit.is_busy)
    assert any(result in sketch.entities for sketch in services.kernel.sketches)
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            all(result not in sketch.entities for sketch in services.kernel.sketches)
            and not unit.is_busy
        )
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            any(result in sketch.entities for sketch in services.kernel.sketches)
            and not unit.is_busy
        )
    )


@pytest.mark.parametrize("gap_type", [1, 2])
def test_offsetgaptype_numeric_panel_uses_same_geometry(qtbot: QtBot, gap_type: int) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import PolylineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.set_offset_gap_type(gap_type)
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    editor.offset_distance_field.setValue(-2)
    editor.transform_buttons["offset"].click()
    result = editor.canvas.entities[-1]
    assert isinstance(result, PolylineEntity) and len(result.points_mm) == 4
    assert bool(result.bulges) == (gap_type == 1)


def test_offsetgaptype_change_invalidates_existing_preview(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad.core.sketch import PolylineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    pixel = canvas.local_to_screen((5, -2))
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
    assert len(canvas.transform_preview_entities) == 1
    canvas.set_offset_gap_type(1)
    assert not canvas.transform_preview_entities
    command.setText("5,-2")
    QTest.keyClick(command, Qt.Key.Key_Return)
    result = canvas.entities[-1]
    assert isinstance(result, PolylineEntity) and result.bulges


def test_offsetgaptype_setting_persists_and_rejects_invalid(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad import app
    from mycad.ui import main_window
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    bar = editor.drawing_command_bar
    for value in ("OFFSETGAPTYPE", "9", "2"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.offset_gap_type == 2
    settings = main_window.QSettings(main_window.ORG_NAME, main_window.APP_NAME)
    assert settings.value(main_window.SETTINGS_KEY_OFFSET_GAP_TYPE, -1) in (2, "2")
    window.act_new_drawing.trigger()
    reopened = window.active_sketch_dialog()
    assert reopened is not None and reopened.canvas.offset_gap_type == 2


@pytest.mark.parametrize("preselect", [False, True])
def test_arrayrect_command_selects_objects_and_creates_grid(qtbot: QtBot, preselect: bool) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (5, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    command = editor.drawing_command_bar.input

    def send(value: str) -> None:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)

    if preselect:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((2, 0)))
    send("ARRAYRECT")
    if not preselect:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((2, 0)))
    for value in ("", "2", "3", "-4", "10"):
        send(value)
    assert canvas.entities == [source]
    preview = canvas.transform_preview_entities
    assert len(preview) == 5
    send("")
    assert len(canvas.entities) == 6
    assert tuple(canvas.entities[1:]) == preview
    assert canvas.undo_last_operation() and canvas.entities == [source]
    assert canvas.redo_last_operation() and len(canvas.entities) == 6
    send("")
    assert "选择对象" in editor.drawing_command_bar.status.text()


@pytest.mark.parametrize(("rows", "columns", "spacing"), [(1, 3, "7"), (3, 1, "-4")])
def test_arrayrect_command_single_axis_skips_unused_spacing(
    qtbot: QtBot, rows: int, columns: int, spacing: str
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (5, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", str(rows), str(columns), spacing):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [source]
    assert len(canvas.transform_preview_entities) == 2
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 3
    assert canvas.undo_last_operation() and canvas.entities == [source]


def test_arrayrect_retries_invalid_values_and_rejects_stale_source(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (5, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar

    def send(value: str) -> None:
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)

    for value in ("ARRAYRECT", "", "0"):
        send(value)
    assert "整数" in bar.status.text() and canvas.entities == [source]
    for value in ("2", "3", "0"):
        send(value)
    assert "非零" in bar.status.text() and canvas.entities == [source]
    send("-4")
    extra = LineEntity(uuid4().hex, (10, 10), (20, 10))
    assert canvas.replace_draft_entities((source, extra))
    send("10")
    assert "已变化" in bar.status.text()
    assert canvas.entities == [source, extra]


@pytest.mark.parametrize("confirm_with_right_click", [False, True])
def test_arrayrect_canvas_can_confirm_selection(
    qtbot: QtBot, confirm_with_right_click: bool
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    qtbot.waitExposed(editor)
    editor.activateWindow()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (5, 0))
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    command.setText("ARRAYRECT")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((2, 0)))
    if confirm_with_right_click:
        QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=canvas.local_to_screen((2, 0)))
    else:
        QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert "行数" in editor.drawing_command_bar.status.text()
    qtbot.waitUntil(command.hasFocus)


def test_arrayrect_switching_tool_does_not_capture_next_command(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar.input
    bar.setText("ARRAYRECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    editor.tool_buttons["直线"].click()
    for value in ("0,0", "5,0"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1 and isinstance(editor.canvas.entities[0], LineEntity)


@pytest.mark.parametrize("confirm_with_right_click", [False, True])
def test_arrayrect_preview_canvas_confirmation_uses_preview(
    qtbot: QtBot, confirm_with_right_click: bool
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (5, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "2", "2", "4", "5"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    preview = canvas.transform_preview_entities
    assert len(preview) == 3
    if confirm_with_right_click:
        QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=canvas.local_to_screen((2, 0)))
    else:
        QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert tuple(canvas.entities[1:]) == preview
    assert not canvas.transform_preview_entities


@pytest.mark.parametrize("angle_input", [("90",), ("10,10", "@0,10")])
def test_arrayrect_angle_preview_and_confirm(qtbot: QtBot, angle_input: tuple[str, ...]) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "2", "2", "4", "5", "AN", *angle_input):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    preview = canvas.transform_preview_entities
    assert len(preview) == 3
    positions = [entity.start_mm for entity in preview if isinstance(entity, LineEntity)]
    for actual, expected in zip(positions, ((0, 5), (-4, 0), (-4, 5)), strict=True):
        assert actual == pytest.approx(expected, abs=1e-8)
    bar.clear()
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert tuple(canvas.entities[1:]) == preview


def test_arrayrect_angle_uses_mouse_direction_points(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "5", "AN"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 10)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 20)))
    target = canvas.transform_preview_entities[0]
    assert isinstance(target, LineEntity)
    assert target.start_mm == pytest.approx((0, 5), abs=0.1)


def test_arrayrect_rotated_unit_cell_keeps_full_precision(qtbot: QtBot) -> None:
    import math
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    editor.document_layer_mode = True
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "2", "2", "4", "5", "AN", "45", "S", "U", "0,0", "10,0"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    preview = canvas.transform_preview_entities
    positions = [entity.start_mm for entity in preview if isinstance(entity, LineEntity)]
    for actual, expected in zip(positions, ((5, 5), (5, -5), (10, 0)), strict=True):
        assert actual == pytest.approx(expected, abs=1e-8)
    editor.delta_u_field.setValue(999)
    editor.delta_v_field.setValue(999)
    for value in ("AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.pending_associative_arrays
    array = canvas.pending_associative_arrays[0]
    assert array.column_spacing == pytest.approx(10 / math.sqrt(2), abs=1e-12)
    assert array.row_spacing == pytest.approx(-10 / math.sqrt(2), abs=1e-12)
    assert tuple(canvas.entities[1:]) == preview


def test_arrayrect_angle_invalid_points_and_rotated_unit_cell(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar
    for value in ("ARRAYRECT", "", "2", "2", "4", "5", "AN"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    original_preview = canvas.transform_preview_entities
    for value in ("nan", "10,10", "10,10"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
        assert canvas.transform_preview_entities == original_preview
    assert "重合" in bar.status.text()
    for value in ("10,20", "S", "U", "0,0", "-4,5"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    preview = canvas.transform_preview_entities
    positions = [entity.start_mm for entity in preview if isinstance(entity, LineEntity)]
    for actual, expected in zip(positions, ((0, 5), (-4, 0), (-4, 5)), strict=True):
        assert actual == pytest.approx(expected, abs=1e-8)
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert canvas.entities == [source] and not canvas.transform_preview_entities


def test_arrayrect_preview_options_update_rows_columns_and_spacing(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input

    def send(value: str) -> None:
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)

    for value in ("ARRAYRECT", "", "2", "2", "4", "5"):
        send(value)
    assert len(list(canvas.transform_preview_entities)) == 3
    for value in ("R", "3", "6"):
        send(value)
    assert len(list(canvas.transform_preview_entities)) == 5
    for value in ("C", "3", "7"):
        send(value)
    assert len(list(canvas.transform_preview_entities)) == 8
    for value in ("S", "8", "9"):
        send(value)
    preview = canvas.transform_preview_entities
    assert len(preview) == 8
    assert {entity.start_mm for entity in preview if isinstance(entity, LineEntity)} == {
        (9, 0),
        (18, 0),
        (0, 8),
        (9, 8),
        (18, 8),
        (0, 16),
        (9, 16),
        (18, 16),
    }
    assert canvas.entities == [source]
    send("")
    assert tuple(canvas.entities[1:]) == preview


def test_arrayrect_associative_option_explains_current_boundary(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar

    def send(value: str) -> None:
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)

    for value in ("ARRAYRECT", "", "2", "2", "4", "5"):
        send(value)
    preview = canvas.transform_preview_entities
    for value in ("AS", "Y"):
        send(value)
    send("")
    assert "独立二维" in bar.status.text()
    assert canvas.transform_preview_entities == preview and canvas.entities == [source]
    send("AS")
    send("N")
    send("")
    assert tuple(canvas.entities[1:]) == preview


def test_arrayrect_associative_draft_undo_redo_and_finish(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    editor.document_layer_mode = True
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "2", "2", "4", "5", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(canvas.pending_associative_arrays) == 1 and len(canvas.entities) == 4
    assert canvas.undo_last_operation() and not canvas.pending_associative_arrays
    assert canvas.redo_last_operation() and len(canvas.pending_associative_arrays) == 1
    editor.finish_sketch()
    assert editor.result_sketch is not None
    array = editor.result_associative_arrays[0]
    assert all(ref.sketch_id == editor.result_sketch.sketch_id for ref in array.sources)
    assert all(
        member.target.sketch_id == editor.result_sketch.sketch_id for member in array.members
    )


@pytest.mark.parametrize("base_input", [("B", "12.123456789,-4.5"), ("BASE", "K", "1,0")])
def test_arrayrect_creation_accepts_fixed_or_source_key_base(
    qtbot: QtBot, base_input: tuple[str, ...]
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    editor.document_layer_mode = True
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "5", *base_input, "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(canvas.pending_associative_arrays) == 1
    base = canvas.pending_associative_arrays[0].base_point
    assert base is not None
    if "K" in base_input:
        assert base.source is not None and base.source.sketch_id == editor.draft_sketch_id
        assert base.reference is not None and base.reference.kind == "end"
    else:
        assert base.point_mm == pytest.approx((12.123456789, -4.5))
    assert canvas.undo_last_operation() and not canvas.pending_associative_arrays
    assert canvas.redo_last_operation()
    editor.finish_sketch()
    assert editor.result_sketch is not None
    saved_base = editor.result_associative_arrays[0].base_point
    assert saved_base is not None
    if "K" in base_input:
        assert saved_base.source is not None
        assert saved_base.source.sketch_id == editor.result_sketch.sketch_id
    else:
        assert saved_base.point_mm == pytest.approx((12.123456789, -4.5))


def test_arrayrect_base_point_retries_invalid_and_escape_discards_preview(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    editor.document_layer_mode = True
    qtbot.addWidget(editor)
    editor.show()
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((source,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "5", "B", "nan,2"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert "有限" in editor.drawing_command_bar.status.text()
    preview = editor.canvas.transform_preview_entities
    assert preview and editor.canvas.entities == [source]
    bar.setText("K")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    bar.setText("1000,1000")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert "关键点" in editor.drawing_command_bar.status.text()
    assert editor.canvas.transform_preview_entities == preview
    QTest.keyClick(bar, Qt.Key.Key_Escape)
    assert editor.canvas.entities == [source]
    assert not editor.canvas.pending_associative_arrays
    assert not editor.canvas.transform_preview_entities


def test_arrayrect_creation_can_reset_base_to_default(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    editor.document_layer_mode = True
    qtbot.addWidget(editor)
    editor.show()
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((source,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "5", "B", "1,2", "B", "D", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(editor.canvas.pending_associative_arrays) == 1
    assert editor.canvas.pending_associative_arrays[0].base_point is None


@pytest.mark.parametrize("key_point", [False, True])
def test_arrayrect_base_point_accepts_mouse_pick(qtbot: QtBot, key_point: bool) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    editor.document_layer_mode = True
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (10, 10), (20, 10))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "5", "B", *(("K",) if key_point else ())):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20, 10)))
    for value in ("AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    base = canvas.pending_associative_arrays[0].base_point
    assert base is not None
    if key_point:
        assert base.reference is not None and base.reference.kind == "end"
    else:
        assert base.point_mm == pytest.approx((20, 10), abs=0.2)


def test_arrayrect_associative_draft_rejects_unsynchronized_edit(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    editor.document_layer_mode = True
    qtbot.addWidget(editor)
    editor.show()
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert editor.canvas.replace_draft_entities((source,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.pending_associative_arrays
    edited = replace(source, end_mm=(2, 0))
    assert editor.canvas.replace_draft_entities((edited, *editor.canvas.entities[1:]))
    editor.finish_sketch()
    assert editor.isVisible()
    assert editor.status_label.text()
    assert not editor.result_associative_arrays


def test_arrayrect_row_and_column_total_distances(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in (
        "ARRAYRECT",
        "",
        "2",
        "2",
        "4",
        "5",
        "R",
        "3",
        "T",
        "10",
        "C",
        "3",
        "TOTAL",
        "-14",
    ):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    preview = canvas.transform_preview_entities
    assert len(preview) == 8
    assert {entity.start_mm for entity in preview if isinstance(entity, LineEntity)} == {
        (-7, 0),
        (-14, 0),
        (0, 5),
        (-7, 5),
        (-14, 5),
        (0, 10),
        (-7, 10),
        (-14, 10),
    }
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert tuple(canvas.entities[1:]) == preview


def test_arrayrect_spacing_unit_cell_accepts_two_coordinates(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "2", "2", "4", "5", "S", "U", "1,1", "@9,-6"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    preview = canvas.transform_preview_entities
    assert {entity.start_mm for entity in preview if isinstance(entity, LineEntity)} == {
        (9, 0),
        (0, -6),
        (9, -6),
    }
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert tuple(canvas.entities[1:]) == preview


def test_arrayrect_spacing_unit_cell_accepts_mouse_points(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "2", "2", "4", "5", "S", "U"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    first = canvas.local_to_screen((3, 3))
    second = canvas.local_to_screen((12, -3))
    p1 = canvas.screen_to_local(QPointF(first))
    p2 = canvas.screen_to_local(QPointF(second))
    dx = round(p2[0], 4) - round(p1[0], 4)
    dy = round(p2[1], 4) - round(p1[1], 4)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=first)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=second)
    preview = canvas.transform_preview_entities
    starts = [entity.start_mm for entity in preview if isinstance(entity, LineEntity)]
    assert len(starts) == 3
    assert any(point == pytest.approx((dx, dy)) for point in starts)
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert tuple(canvas.entities[1:]) == preview


def test_arrayrect_unit_cell_mouse_uses_object_snaps(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(True)
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (10, 10), (15, 10))
    assert canvas.replace_draft_entities((source, target))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "2", "2", "4", "5", "S", "U"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.2, 0.2)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10.2, 10.2)))
    preview = canvas.transform_preview_entities
    assert {entity.start_mm for entity in preview if isinstance(entity, LineEntity)} == {
        (10, 0),
        (0, 10),
        (10, 10),
    }
    QTest.keyClick(bar, Qt.Key.Key_Escape)
    assert canvas.entities == [source, target]


def test_arrayrect_count_option_preserves_or_requests_axis_spacing(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar

    def send(value: str) -> None:
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)

    for value in ("ARRAYRECT", "", "2", "2", "4", "5", "CO", "3", "2"):
        send(value)
    assert len(list(canvas.transform_preview_entities)) == 5
    for value in ("COUNT", "1", "4"):
        send(value)
    assert len(list(canvas.transform_preview_entities)) == 3
    for value in ("CO", "2", "1"):
        send(value)
    assert "行间距" in bar.status.text()
    send("8")
    preview = canvas.transform_preview_entities
    assert len(preview) == 1
    assert isinstance(preview[0], LineEntity) and preview[0].start_mm == (0, 8)
    send("")
    assert tuple(canvas.entities[1:]) == preview


def test_arrayrect_total_keeps_full_spacing_precision(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar

    def send(value: str) -> None:
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)

    for value in ("ARRAYRECT", "", "2", "2", "4", "5"):
        send(value)
    original = canvas.transform_preview_entities
    for value in ("R", "3", "T", "nan"):
        send(value)
    assert canvas.transform_preview_entities == original
    send("10.0001")
    assert len(canvas.transform_preview_entities) == 5
    points = [
        entity.start_mm
        for entity in canvas.transform_preview_entities
        if isinstance(entity, LineEntity)
    ]
    assert points[1] == pytest.approx((0, 5.00005))
    assert points[3] == pytest.approx((0, 10.0001))
    assert canvas.entities == [source]


def test_arrayrect_preview_options_preserve_candidate_on_invalid_values(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (1, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar

    def send(value: str) -> None:
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)

    for value in ("ARRAYRECT", "", "2", "2", "4", "5"):
        send(value)
    first = canvas.transform_preview_entities
    for value in ("R", "0"):
        send(value)
    assert canvas.transform_preview_entities == first and "正整数" in bar.status.text()
    send("1")
    single_row = canvas.transform_preview_entities
    assert len(single_row) == 1
    for value in ("C", "1"):
        send(value)
    assert canvas.transform_preview_entities == single_row and "位置数" in bar.status.text()
    for value in ("3", "0"):
        send(value)
    assert canvas.transform_preview_entities == single_row and "非零" in bar.status.text()
    send("7")
    assert len(canvas.transform_preview_entities) == 2
    for value in ("S", "9"):
        send(value)
    preview = canvas.transform_preview_entities
    assert {entity.start_mm for entity in preview if isinstance(entity, LineEntity)} == {
        (9, 0),
        (18, 0),
    }
    send("X")
    assert tuple(canvas.entities[1:]) == preview


def test_arrayrect_preview_is_stable_and_escape_discards_it(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (5, 0))
    assert canvas.replace_draft_entities((source,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "2", "2", "4", "5"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    preview = canvas.transform_preview_entities
    assert len(preview) == 3 and canvas.entities == [source]
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 10)))
    QTest.mouseMove(canvas, canvas.local_to_screen((15, 15)))
    assert canvas.transform_preview_entities == preview
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.transform_preview_entities and canvas.entities == [source]
    assert canvas.active_transform is None


def test_arrayrect_canvas_escape_cancels_without_modifying_geometry(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (5, 0))
    assert canvas.replace_draft_entities((source,))
    bar = editor.drawing_command_bar.input
    bar.setText("ARRAYRECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((2, 0)))
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.entities == [source]
    assert "取消" in editor.drawing_command_bar.status.text()


@pytest.mark.parametrize("after_preview", [False, True])
def test_arrayrect_rejects_document_revision_change(qtbot: QtBot, after_preview: bool) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    source = LineEntity(uuid4().hex, (0, 0), (5, 0))
    assert editor.canvas.replace_draft_entities((source,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {source.entity_id}
    revision = [1]
    editor.canvas.source_revision_provider = lambda: revision[0]
    bar = editor.drawing_command_bar
    for value in ("ARRAYRECT", "", "2", "2", "4"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    if after_preview:
        bar.input.setText("5")
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
        assert len(editor.canvas.transform_preview_entities) == 3
    revision[0] = 2
    bar.input.setText("" if after_preview else "5")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "已变化" in bar.status.text()
    assert editor.canvas.entities == [source]
    assert not editor.canvas.transform_preview_entities


def test_rectangular_array_panel_creates_grid_and_undoes(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    source = LineEntity(uuid4().hex, (0, 0), (5, 0))
    assert editor.canvas.replace_draft_entities((source,))
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((2, 0))
    )
    editor.array_rows_field.setValue(2)
    editor.array_columns_field.setValue(3)
    editor.delta_u_field.setValue(10)
    editor.delta_v_field.setValue(-4)
    editor.transform_buttons["rectangular_array"].click()
    assert len(editor.canvas.entities) == 6
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == [source]
    assert editor.canvas.redo_last_operation() and len(editor.canvas.entities) == 6


def test_offsetdist_variable_accepts_finite_values_and_cancel(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar

    def send(value: str) -> None:
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)

    send("OFFSETDIST")
    send("4.5")
    assert editor.canvas.offset_default_distance == 4.5
    send("OFFSETDIST")
    send("nan")
    assert editor.canvas.offset_default_distance == 4.5
    send("-2")
    assert editor.canvas.offset_default_distance == -2
    send("OFFSET")
    send("")
    assert "通过点偏移" in editor.canvas.message
    assert editor.canvas.offset_default_distance == -2
    send("OFFSETDIST")
    assert "先完成或取消" in bar.status.text()
    assert editor.canvas.offset_default_distance == -2
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    send("OFFSETDIST")
    send("0")
    assert editor.canvas.offset_default_distance == 0
    send("OFFSET")
    send("")
    assert editor.canvas.interactive_offset_needs_distance
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    send("OFFSETDIST")
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert editor.canvas.offset_default_distance == 0


def test_offsetdist_is_shared_between_documents_for_window_lifetime(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad import app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    first = window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    for value in ("OFFSET", "3"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Escape)
    window.new_session_document("sketch")
    second = window.active_sketch_dialog()
    assert second is not None and second.canvas.offset_default_distance == 3
    for value in ("OFFSETDIST", "7"):
        second.drawing_command_bar.input.setText(value)
        QTest.keyClick(second.drawing_command_bar.input, Qt.Key.Key_Return)
    window.activate_session_document(first.loaded.document.document_id)
    assert window.active_sketch_dialog() is editor
    assert editor.canvas.offset_default_distance == 7
    new_window = MainWindow(services=app.build_app(discoverers=[]))
    qtbot.addWidget(new_window)
    new_window.show()
    new_window.act_new_drawing.trigger()
    fresh = new_window.active_sketch_dialog()
    assert fresh is not None and fresh.canvas.offset_default_distance == -1


def test_offset_erase_option_replaces_draft_source_atomically(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "E", "Y", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    command.setText("10,5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].entity_id != line.entity_id
    assert canvas.entities[0].start_mm == pytest.approx((0, 2))
    QTest.keyClick(command, Qt.Key.Key_Escape)
    assert canvas.undo_last_operation() and canvas.entities == [line]


def test_offset_erase_option_keeps_user_constrained_source(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    relation = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    canvas.constraints = [relation]
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "E", "Y", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    command.setText("10,5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [line] and canvas.constraints == [relation]
    assert "用户约束" in canvas.message


def test_offset_erase_option_waits_for_answer_and_n_preserves_source(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "E"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    assert canvas.interactive_offset_needs_distance
    assert "完成偏移选项" in canvas.message
    for value in ("N", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    command.setText("10,5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2 and canvas.entities[0] == line


def test_interactive_offset_button_shares_command_and_repeat(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    assert editor.interactive_offset_button.isEnabled()
    editor.interactive_offset_button.click()
    assert editor.canvas.interactive_offset_needs_distance
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Escape)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert editor.canvas.interactive_offset_needs_distance


def test_offset_command_preserves_unfinished_drawing(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for text in ("L", "0,0", "O"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.pending_point_count == 1
    assert editor.canvas.active_transform is None
    assert "未完成" in bar.status.text()


def test_trim_fence_commits_multiple_segments_as_one_undo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    targets = (LineEntity(uuid4().hex, (0, 0), (20, 0)), LineEntity(uuid4().hex, (0, 10), (20, 10)))
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 15))
    assert canvas.replace_draft_entities((*targets, boundary))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "F"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((15, -2), (15, 5), (15, 12)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 3
    assert all(
        isinstance(entity, LineEntity) and entity.end_mm == pytest.approx((10, y))
        for entity, y in zip(canvas.entities[:2], (0, 10), strict=True)
    )
    assert canvas.undo_last_operation() and canvas.entities == [*targets, boundary]


def test_trim_crossing_window_edits_targets_as_one_operation(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    targets = (LineEntity(uuid4().hex, (0, 0), (20, 0)), LineEntity(uuid4().hex, (0, 10), (20, 10)))
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 15))
    assert canvas.replace_draft_entities((*targets, boundary))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "CR", "14,-2", "@2,14"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 3
    assert all(
        isinstance(entity, LineEntity) and entity.end_mm == pytest.approx((10, y))
        for entity, y in zip(canvas.entities[:2], (0, 10), strict=True)
    )
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [*targets, boundary]


@pytest.mark.parametrize("operation", ["TRIM", "EXTEND"])
def test_crossing_selects_contained_line_and_rejects_flat_window(
    qtbot: QtBot, operation: str
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (5, 0))
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 5))
    assert canvas.replace_draft_entities((target, boundary))
    command = editor.drawing_command_bar.input
    for value in (operation, "CR", "6,-1", "6,1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target, boundary]
    assert "非零" in canvas.message
    command.setText("-1,1")
    QTest.keyClick(command, Qt.Key.Key_Return)
    if operation == "TRIM":
        assert canvas.entities == [boundary]
    else:
        assert isinstance(canvas.entities[0], LineEntity)
        assert canvas.entities[0].end_mm == pytest.approx((10, 0))
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target, boundary]


def test_crossing_accepts_small_window_given_by_coordinates(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 5))
    assert canvas.replace_draft_entities((target, boundary))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "CR", "14.95,-0.05", "15.05,0.05"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((10, 0))


def test_crossing_cancel_after_first_corner_keeps_geometry(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "CR", "5,-1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert "交叉窗口" in canvas.message
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.entities == [line]
    assert canvas.tool == "修剪"


def test_trim_crossing_intersects_arc_exactly(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import ArcEntity, LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, 180)
    boundary = LineEntity(uuid4().hex, (0, -7), (0, 7))
    assert canvas.replace_draft_entities((arc, boundary))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "CR", "2,2", "4,6"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert isinstance(canvas.entities[0], ArcEntity)
    assert canvas.entities[0].start_angle_deg == pytest.approx(90)
    assert canvas.entities[0].sweep_angle_deg == pytest.approx(90)
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [arc, boundary]


def test_trim_crossing_intersects_curved_polyline(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    path = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), bulges=(-1,))
    boundary = LineEntity(uuid4().hex, (0, 3), (0, 7))
    assert canvas.replace_draft_entities((path, boundary))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "CR", "2,2", "4,6"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert isinstance(canvas.entities[0], PolylineEntity)
    assert canvas.entities[0].points_mm[-1] == pytest.approx((0, 5))
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [path, boundary]


def test_extend_crossing_contained_polyline_uses_nearest_terminal(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    path = PolylineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5)))
    boundary = LineEntity(uuid4().hex, (-5, 10), (10, 10))
    assert canvas.replace_draft_entities((path, boundary))
    command = editor.drawing_command_bar.input
    for value in ("EXTEND", "CR", "6,6", "-1,-1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert isinstance(canvas.entities[0], PolylineEntity)
    assert canvas.entities[0].points_mm[-1] == pytest.approx((5, 10))
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [path, boundary]


def test_extend_crossing_selects_contained_arc_near_first_corner(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import ArcEntity, LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, 90)
    boundary = LineEntity(uuid4().hex, (-5, -8), (-5, 8))
    assert canvas.replace_draft_entities((arc, boundary))
    command = editor.drawing_command_bar.input
    for value in ("EXTEND", "CR", "-1,6", "6,-1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert isinstance(canvas.entities[0], ArcEntity)
    assert canvas.entities[0].sweep_angle_deg == pytest.approx(180)
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [arc, boundary]


def test_trim_command_undo_only_reverts_its_own_edits(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 5))
    assert canvas.replace_draft_entities((target, boundary))
    command = editor.drawing_command_bar.input
    command.setText("TRIM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, 0)))
    assert canvas.entities != [target, boundary]
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target, boundary]
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target, boundary]
    assert canvas.tool == "修剪"


@pytest.mark.parametrize("tool", ("TRIM", "EXTEND"))
def test_line_edit_edge_mode_uses_virtual_boundary(qtbot: QtBot, tool: str) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20 if tool == "TRIM" else 5, 0))
    boundary = LineEntity(uuid4().hex, (10, 2), (10, 5))
    assert canvas.replace_draft_entities((target, boundary))
    command = editor.drawing_command_bar.input
    for value in (tool, "E", "E"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    canvas.add_coordinate_point((15 if tool == "TRIM" else 5, 0), exact_point=True)
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((10, 0))
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target, boundary]


def test_line_edit_edge_mode_can_restore_finite_boundaries(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (10, 2), (10, 5))
    assert canvas.replace_draft_entities((target, boundary))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "E", "E", "E", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not canvas.line_edit_extend_boundaries
    canvas.add_coordinate_point((15, 0), exact_point=True)
    assert canvas.entities == [boundary]
    assert "删除" in canvas.message
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target, boundary]


def test_edgemode_system_command_controls_virtual_boundaries(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("EDGEMODE", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.line_edit_extend_boundaries
    for value in ("EDGEMODE", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not editor.canvas.line_edit_extend_boundaries


@pytest.mark.parametrize("mode", (0, 1, 2))
def test_projmode_keeps_planar_trim_geometry(qtbot: QtBot, mode: int) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 5))
    assert canvas.replace_draft_entities((target, boundary))
    command = editor.drawing_command_bar.input
    for value in ("PROJMODE", str(mode), "TRIM"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.line_edit_projection_mode == mode
    canvas.add_coordinate_point((15, 0), exact_point=True)
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((10, 0))


def test_project_option_switches_modes_without_ending_trim(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "P", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.line_edit_projection_mode == 0 and editor.canvas.tool == "修剪"
    for value in ("P", "V"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.line_edit_projection_mode == 2
    assert "异面边界" in editor.drawing_command_bar.status.text()


def test_edgemode_rejects_invalid_value_and_active_fence(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("EDGEMODE", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not editor.canvas.line_edit_extend_boundaries
    assert "0 或 1" in editor.drawing_command_bar.status.text()
    QTest.keyClick(command, Qt.Key.Key_Escape)
    for value in ("TRIM", "F", "EDGEMODE"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.trim_fence_active
    assert "完成或取消" in editor.drawing_command_bar.status.text()


def test_trimextendmode_standard_starts_boundary_selection(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("TRIMEXTENDMODE", "0", "TRIM"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.selecting_line_edit_boundaries
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert not canvas.selecting_line_edit_boundaries
    QTest.keyClick(command, Qt.Key.Key_Escape)
    for value in ("TRIMEXTENDMODE", "1", "EXTEND"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not canvas.selecting_line_edit_boundaries


def test_trim_mode_option_switches_to_standard_then_quick(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "MO", "S"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.line_edit_standard_mode and canvas.selecting_line_edit_boundaries
    QTest.keyClick(command, Qt.Key.Key_Return)
    for value in ("MO", "Q"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not canvas.line_edit_standard_mode and not canvas.selecting_line_edit_boundaries


def test_extend_shift_click_temporarily_trims(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 5))
    assert canvas.replace_draft_entities((target, boundary))
    command = editor.drawing_command_bar.input
    command.setText("EXTEND")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=canvas.local_to_screen((15, 0)),
    )
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((10, 0))
    assert canvas.tool == "延伸"


def test_standard_boundary_prompt_can_switch_to_quick_mode(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.canvas.set_line_edit_standard_mode(True)
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "O", "Q"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not editor.canvas.line_edit_standard_mode
    assert not editor.canvas.selecting_line_edit_boundaries
    assert editor.canvas.tool == "修剪"


@pytest.mark.parametrize("standard", (False, True))
def test_trim_unintersected_target_depends_on_mode(qtbot: QtBot, standard: bool) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((target,))
    canvas.set_line_edit_standard_mode(standard)
    command = editor.drawing_command_bar.input
    command.setText("TRIM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    if standard:
        QTest.keyClick(command, Qt.Key.Key_Return)
    else:
        pixel = canvas.local_to_screen((10, 0))
        QTest.mouseMove(canvas, canvas.local_to_screen((10, 3)))
        qtbot.wait(50)
        QTest.mouseMove(canvas, pixel)
        qtbot.waitUntil(lambda: canvas.previewed_line_edit_original == target, timeout=5000)
        assert canvas.previewed_line_edit_entities == () and canvas.entities == [target]
    canvas.add_coordinate_point((10, 0), exact_point=True)
    if standard:
        assert canvas.entities == [target]
        assert "交点" in canvas.message
    else:
        assert canvas.entities == []
        command.setText("U")
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert canvas.entities == [target]


def test_trim_erase_option_keeps_command_and_supports_undo(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 10), (20, 10))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "ERASE"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [second] and canvas.tool == "修剪"
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [first, second]


def test_trim_erase_escape_cancels_selection_without_leaving_command(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((target,))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "ERASE"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    QTest.keyClick(command, Qt.Key.Key_Escape)
    assert canvas.entities == [target] and not canvas.line_edit_erasing
    assert canvas.tool == "修剪" and not canvas.selected_entity_ids


def test_quick_trim_fence_deletes_unintersected_target_and_undoes(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((target,))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "F", "10,-2", "@0,4", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == []
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target]


def test_quick_trim_does_not_delete_user_constrained_target(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((target,))
    relation = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(target.entity_id, "geometry"),)
    )
    canvas.constraints = [relation]
    command = editor.drawing_command_bar.input
    command.setText("TRIM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    assert canvas.entities == [target] and canvas.constraints == [relation]
    assert "约束" in canvas.message


def test_trim_fence_escape_restores_preview(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 5))
    assert canvas.replace_draft_entities((target, boundary))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "F"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((15, -2), (15, 2)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.entities != [target, boundary]
    QTest.keyClick(command, Qt.Key.Key_Escape)
    assert not canvas.trim_fence_active
    assert canvas.entities == [target, boundary]


def test_trim_fence_accepts_relative_coordinates(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 5))
    assert canvas.replace_draft_entities((target, boundary))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "F", "15,-2", "@0,4", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((10, 0))
    assert canvas.undo_last_operation() and canvas.entities == [target, boundary]


def test_trim_fence_respects_explicit_cutting_boundary(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (5, -5), (5, 5))
    other = LineEntity(uuid4().hex, (15, -5), (15, 5))
    assert canvas.replace_draft_entities((target, boundary, other))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "C"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    QTest.keyClick(command, Qt.Key.Key_Return)
    for value in ("F", "10,-2", "@0,4", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((5, 0))
    assert canvas.entities[1:] == [boundary, other]


def test_extend_fence_extends_multiple_nearest_endpoints_atomically(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    canvas = editor.canvas
    lines = (LineEntity(uuid4().hex, (0, 0), (5, 0)), LineEntity(uuid4().hex, (0, 10), (5, 10)))
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 15))
    assert canvas.replace_draft_entities((*lines, boundary))
    command = editor.drawing_command_bar.input
    for value in ("EXTEND", "F", "4,-2", "@0,14", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 3
    assert all(
        isinstance(entity, LineEntity) and entity.end_mm == pytest.approx((10, y))
        for entity, y in zip(canvas.entities[:2], (0, 10), strict=True)
    )
    assert canvas.undo_last_operation() and canvas.entities == [*lines, boundary]


def test_extend_fence_rejects_equal_endpoint_distance_without_edit(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    boundary = LineEntity(uuid4().hex, (15, -5), (15, 5))
    assert canvas.replace_draft_entities((target, boundary))
    command = editor.drawing_command_bar.input
    for value in ("EXTEND", "F", "5,-2", "@0,4", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target, boundary]
    assert "端点" in canvas.message


def test_extend_fence_does_not_select_nearby_unintersected_curve(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    boundary = LineEntity(uuid4().hex, (15, -5), (15, 5))
    assert canvas.replace_draft_entities((target, boundary))
    command = editor.drawing_command_bar.input
    for value in ("EXTEND", "F", "8,0.5", "@0,3", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target, boundary]


def test_fence_overlapping_target_rejects_and_restores_prior_preview(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 5))
    overlapping = LineEntity(uuid4().hex, (12, 5), (20, 5))
    assert canvas.replace_draft_entities((target, boundary, overlapping))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "F", "15,-2", "@0,4", "@-3,3", "@8,0", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target, boundary, overlapping]
    assert "重叠" in canvas.message


def test_extend_fence_extends_curved_polyline_endpoint(qtbot: QtBot) -> None:
    import math
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    path = PolylineEntity(uuid4().hex, ((-5, 0), (0, 5)), bulges=(-math.tan(math.pi / 8),))
    boundary = LineEntity(uuid4().hex, (5, -2), (5, 2))
    assert canvas.replace_draft_entities((path, boundary))
    command = editor.drawing_command_bar.input
    for value in ("EXTEND", "F", "-3,4.5", "@3,0", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert isinstance(canvas.entities[0], PolylineEntity)
    assert canvas.entities[0].points_mm[-1] == pytest.approx((5, 0))
    assert canvas.undo_last_operation() and canvas.entities == [path, boundary]


def test_trim_command_selects_explicit_boundary(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (5, -5), (5, 5))
    other = LineEntity(uuid4().hex, (15, -5), (15, 5))
    canvas.replace_draft_entities((target, boundary, other))
    bar = editor.drawing_command_bar
    for text in ("TRIM", "C"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.selecting_line_edit_boundaries
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert not canvas.selecting_line_edit_boundaries
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
    assert canvas.previewed_line_edit_entities
    preview = canvas.previewed_line_edit_entities
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=pixel)
    assert canvas.entities[0] == preview[0]
    result = canvas.entities[0]
    assert isinstance(result, LineEntity)
    assert result.end_mm == pytest.approx((5, 0))
    assert canvas.entities[1:] == [boundary, other]


def test_trim_boundary_window_selection_and_cancel_box(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (5, -5), (5, 5))
    second = LineEntity(uuid4().hex, (15, -5), (15, 5))
    canvas.replace_draft_entities((first, second))
    bar = editor.drawing_command_bar
    for text in ("TRIM", "C"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    start, end = canvas.local_to_screen((2, -8)), canvas.local_to_screen((8, 8))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.selected_entity_ids == {first.entity_id}
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((12, -8)))
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert canvas.selecting_line_edit_boundaries
    assert canvas.selected_entity_ids == {first.entity_id}
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert not canvas.selecting_line_edit_boundaries


def test_extend_command_uses_selected_boundary(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    target = LineEntity(uuid4().hex, (0, 0), (5, 0))
    excluded = LineEntity(uuid4().hex, (10, -5), (10, 5))
    selected = LineEntity(uuid4().hex, (15, -5), (15, 5))
    assert canvas.replace_draft_entities((target, excluded, selected))
    bar = editor.drawing_command_bar
    for text in ("EXTEND", "C"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15, 4)))
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    result = canvas.entities[0]
    assert isinstance(result, LineEntity)
    assert result.end_mm == pytest.approx((15, 0))
    assert canvas.entities[1:] == [excluded, selected]


def test_trim_empty_boundary_selection_uses_all_visible(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first = LineEntity(uuid4().hex, (5, -5), (5, 5))
    second = LineEntity(uuid4().hex, (15, -5), (15, 5))
    canvas.replace_draft_entities((target, first, second))
    bar = editor.drawing_command_bar
    for text in ("TRIM", "C", ""):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert not canvas.selecting_line_edit_boundaries
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    assert len(canvas.entities) == 4
    assert first in canvas.entities and second in canvas.entities


@pytest.mark.parametrize("canvas_input", [False, True])
def test_rotate_reference_default_angles(qtbot: QtBot, canvas_input: bool) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar
    for value in ("RO", "0,0", "R"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClick(canvas if canvas_input else bar.input, Qt.Key.Key_Return)
    assert canvas.rotation_reference_angle == 0
    bar.input.setText("90")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    rotated = canvas.entities[0]
    assert isinstance(rotated, LineEntity)
    assert rotated.end_mm == pytest.approx((0, 10), abs=1e-8)

    canvas.selected_entity_ids = {source.entity_id}
    for value in ("RO", "0,0", "R", "90"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClick(canvas if canvas_input else bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform is None
    restored = canvas.entities[0]
    assert isinstance(restored, LineEntity)
    assert restored.end_mm == pytest.approx((10, 0), abs=1e-8)


@pytest.mark.parametrize("canvas_input", [False, True])
def test_rotate_remembers_normal_angle_and_cancel_preserves_it(
    qtbot: QtBot, canvas_input: bool
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar
    for value in ("RO", "0,0", "90"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.rotation_default_angle == 90
    for value in ("RO", "0,0"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "90" in canvas.message
    QTest.keyClick(canvas if canvas_input else bar.input, Qt.Key.Key_Return)
    result = canvas.entities[0]
    assert isinstance(result, LineEntity)
    assert result.end_mm == pytest.approx((-10, 0), abs=1e-8)
    assert canvas.active_transform is None
    for value in ("RO", "0,0"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClicks(canvas, "45")
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.rotation_default_angle == 90


def test_numeric_rotate_panel_updates_command_default(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    editor.angle_field.setValue(90)
    editor.numeric_rotate_button.click()
    assert canvas.rotation_default_angle == 90
    bar = editor.drawing_command_bar
    for value in ("RO", "0,0", ""):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    result = canvas.entities[0]
    assert isinstance(result, LineEntity)
    assert result.end_mm == pytest.approx((-10, 0), abs=1e-8)


def test_numeric_rotate_panel_rejected_constraint_preserves_default(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (10, 0), (20, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.constraints = [
        SketchConstraint(
            uuid4().hex, "fixed", (SketchGeometryReference(source.entity_id, "start"),)
        )
    ]
    canvas.selected_entity_ids = {source.entity_id}
    canvas.rotation_default_angle = 25
    editor.angle_field.setValue(90)
    editor.numeric_rotate_button.click()
    assert canvas.entities == [source]
    assert canvas.rotation_default_angle == 25
    assert "约束" in canvas.message


def test_rotate_default_angle_follows_point_copy_and_workspace(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar
    for value in ("RO", "0,0", "C", "0,10"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.rotation_default_angle == pytest.approx(90)
    assert len(canvas.entities) == 2
    next_editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(next_editor)
    next_editor.continue_workspace_from(editor)
    assert next_editor.canvas.rotation_default_angle == pytest.approx(90)


def test_rotate_mouse_preview_and_cancel_do_not_change_default(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar
    for value in ("RO", "0,0"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseMove(canvas, canvas.local_to_screen((0, 20)))
    assert canvas.rotation_default_angle == 0
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 20)))
    assert canvas.rotation_default_angle == pytest.approx(90, abs=1)
    for value in ("RO", "0,0"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseMove(canvas, canvas.local_to_screen((20, 0)))
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.rotation_default_angle == pytest.approx(90, abs=1)


def test_rotate_reference_numeric_angles(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    original = LineEntity(uuid4().hex, (0, 0), (10, 10))
    canvas.replace_draft_entities((original,))
    canvas.selected_entity_ids = {original.entity_id}
    bar = editor.drawing_command_bar
    for text in ("RO", "0,0", "R", "30"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform == "rotate"
    assert canvas.rotation_uses_reference
    assert canvas.entities == [original]
    bar.input.setText("120")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1
    rotated = canvas.entities[0]
    assert isinstance(rotated, LineEntity)
    assert rotated.entity_id == original.entity_id
    assert rotated.end_mm == pytest.approx((-10, 10), abs=1e-8)
    canvas.undo_last_operation()
    assert canvas.entities == [original]


def test_rotate_reference_invalid_input_and_restart_preserve_source(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("RO", "0,0", "R", "nan", "30", "R", "60"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.entities == [line]
    assert canvas.rotation_reference_angle == pytest.approx(60)
    assert editor.rotation_reference_check.isChecked()
    bar.input.setText("120")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    result = canvas.entities[0]
    assert isinstance(result, LineEntity)
    assert result.end_mm == pytest.approx((5, 5 * 3**0.5))


def test_rotate_reference_option_does_not_change_next_rotate_mode(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    assert not editor.rotation_reference_check.isChecked()
    for text in ("RO", "0,0", "R", "30", "90"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert not editor.rotation_reference_check.isChecked()
    canvas.selected_entity_ids = {line.entity_id}
    for text in ("RO", "0,0", "30"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform is None
    result = canvas.entities[0]
    assert isinstance(result, LineEntity)
    assert result.end_mm == pytest.approx((0, 10), abs=1e-8)


def test_rotate_reference_numeric_input_works_from_canvas(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("RO", "0,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClick(canvas, Qt.Key.Key_R, Qt.KeyboardModifier.ShiftModifier)
    assert canvas.rotation_uses_reference
    QTest.keyClicks(canvas, "30")
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas.entities == [line]
    assert canvas.rotation_reference_angle == pytest.approx(30)
    QTest.keyClicks(canvas, "120")
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    result = canvas.entities[0]
    assert isinstance(result, LineEntity)
    assert result.end_mm == pytest.approx((0, 10), abs=1e-8)


def test_rotate_reference_point_then_numeric_target(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("RO", "0,0", "R", "0,10", "180"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    result = canvas.entities[0]
    assert isinstance(result, LineEntity)
    assert result.end_mm == pytest.approx((0, 10), abs=1e-8)


def test_rotate_reference_canvas_invalid_angle_can_be_corrected(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("RO", "0,0", "R"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClicks(canvas, "-")
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas.entities == [line]
    assert canvas.rotation_reference_angle is None
    QTest.keyClick(canvas, Qt.Key.Key_Backspace)
    QTest.keyClicks(canvas, "30")
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas.rotation_reference_angle == pytest.approx(30)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.entities == [line]
    assert not editor.rotation_reference_check.isChecked()


@pytest.mark.parametrize("answer", ["", "N", "Y", "ESC"])
def test_mirror_command_asks_before_erasing_source(qtbot: QtBot, answer: str) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (1, 1), (5, 1))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("MI", "0,0", "0,10"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.entities == [line]
    assert canvas.awaiting_mirror_erase
    assert canvas.transform_preview_entities
    bar.input.setText("invalid")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.entities == [line] and canvas.awaiting_mirror_erase
    if answer == "ESC":
        QTest.keyClick(bar.input, Qt.Key.Key_Escape)
        assert canvas.entities == [line]
    else:
        bar.input.setText(answer)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
        assert len(canvas.entities) == (1 if answer == "Y" else 2)
        mirrored = canvas.entities[-1]
        assert isinstance(mirrored, LineEntity)
        assert mirrored.start_mm == pytest.approx((-1, 1))
        assert mirrored.end_mm == pytest.approx((-5, 1))
        canvas.undo_last_operation()
        assert canvas.entities == [line]


def test_mirror_prompt_rejects_draft_change(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (1, 1), (5, 1))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("MI", "0,0", "0,10"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    changed = LineEntity(line.entity_id, (1, 2), (5, 2))
    assert canvas.replace_draft_entities((changed,))
    bar.input.setText("Y")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.entities == [changed]
    assert canvas.active_transform is None
    assert "变化" in canvas.message


@pytest.mark.parametrize("answer", ["Y", "right"])
def test_mirror_prompt_accepts_canvas_input(qtbot: QtBot, answer: str) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (1, 1), (5, 1))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("MI", "0,0", "0,10"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.awaiting_mirror_erase
    if answer == "Y":
        QTest.keyClick(canvas, Qt.Key.Key_Y)
    else:
        QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
    assert canvas.active_transform is None
    assert len(canvas.entities) == (1 if answer == "Y" else 2)
    result = canvas.entities[-1]
    assert isinstance(result, LineEntity)
    assert result.start_mm == pytest.approx((-1, 1))


def test_mirror_command_can_select_after_start(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (1, 1), (5, 1))
    canvas.replace_draft_entities((line,))
    bar = editor.drawing_command_bar
    bar.input.setText("MI")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.transform_selecting
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 1)))
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    for text in ("0,0", "0,10"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.awaiting_mirror_erase
    assert canvas.entities == [line]
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2


def test_mirror_prompt_rejects_constrained_erase_but_can_keep_source(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (1, 1), (5, 1))
    canvas.replace_draft_entities((line,))
    constraint = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 4, "mm"
    )
    canvas.constraints.append(constraint)
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("MI", "0,0", "0,10", "Y"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.entities == [line]
    assert canvas.constraints == [constraint]
    assert canvas.awaiting_mirror_erase
    assert not canvas.transform_preview_entities
    bar.input.setText("N")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2
    assert canvas.constraints == [constraint]


def test_mirror_command_restores_existing_panel_preference(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (1, 1), (5, 1))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    editor.mirror_keep_source_check.setChecked(False)
    bar = editor.drawing_command_bar
    for text in ("MI", "0,0", "0,10"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.awaiting_mirror_erase
    assert editor.mirror_keep_source_check.isChecked()
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert not editor.mirror_keep_source_check.isChecked()
    assert canvas.entities == [line]


def test_mirror_prompt_rejects_changed_selection(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (1, 1), (5, 1))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("MI", "0,0", "0,10"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    canvas.selected_entity_ids.add(uuid4().hex)
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.entities == [line]
    assert canvas.active_transform is None
    assert "变化" in canvas.message


def test_mirror_prompt_ctrl_y_does_not_confirm_erase(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (1, 1), (5, 1))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("MI", "0,0", "0,10"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClick(canvas, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert canvas.awaiting_mirror_erase
    assert canvas.entities == [line]


@pytest.mark.parametrize("fit", [False, True])
def test_copy_array_command_spacing_fit_and_undo(qtbot: QtBot, fit: bool) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("CO", "0,0", "A", "4"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.entities == [line]
    if fit:
        bar.input.setText("F")
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("0,6")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(canvas.entities) == 4
    assert all(isinstance(entity, LineEntity) for entity in canvas.entities)
    values = [entity.start_mm[1] for entity in canvas.entities if isinstance(entity, LineEntity)]
    assert values == pytest.approx([0, 2, 4, 6] if fit else [0, 6, 12, 18])
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    canvas.undo_last_operation()
    assert canvas.entities == [line]
    canvas.redo_last_operation()
    assert len(canvas.entities) == 4


def test_copy_array_rejects_invalid_count_and_zero_step_then_recovers(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("CO", "0,0", "A", "1", "2.5", "1001"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
        assert canvas.entities == [line]
    assert canvas.copy_array_needs_count
    bar.input.setText("3")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("0,0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.entities == [line]
    assert canvas.copy_array_waiting_point
    bar.input.setText("0,3")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(canvas.entities) == 3
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    canvas.undo_last_operation()
    assert canvas.entities == [line]


def test_copy_array_u_undoes_whole_array_during_command(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("CO", "0,0", "A", "4", "0,3"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(canvas.entities) == 4 and canvas.active_transform == "copy"
    bar.input.setText("U")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.entities == [line] and canvas.active_transform == "copy"
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)


def test_copy_array_rejects_changed_source_before_placement(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("CO", "0,0", "A", "3"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    changed = LineEntity(line.entity_id, (0, 1), (10, 1))
    assert canvas.replace_draft_entities((changed,))
    bar.input.setText("0,3")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.entities == [changed]
    assert "变化" in canvas.message
    assert not canvas.transform_preview_entities


def test_copy_array_respects_single_copy_mode(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.set_copy_mode(1)
    bar = editor.drawing_command_bar
    for text in ("CO", "0,0", "A", "3", "0,2"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(canvas.entities) == 3
    assert canvas.active_transform is None
    assert canvas.copy_mode == 1
    canvas.undo_last_operation()
    assert canvas.entities == [line]


def test_copy_array_preview_matches_committed_candidate(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    for text in ("CO", "0,0", "A", "3"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    point = canvas.local_to_screen((0, 5))
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(point),
            QPointF(canvas.mapToGlobal(point)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert len(canvas.transform_preview_entities) == 2
    preview = canvas.transform_preview_entities
    assert canvas.entities == [line]
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    assert tuple(canvas.entities[1:]) == preview


def test_rotate_copy_keeps_original_and_undoes_as_one_operation(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    original = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    canvas.replace_draft_entities((original,))
    canvas.selected_entity_ids = {original.entity_id}
    bar = editor.drawing_command_bar
    for text in ("ROTATE", "0,0", "C", "90"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2
    assert canvas.entities[0] == original
    copied = canvas.entities[1]
    assert isinstance(copied, LineEntity)
    assert copied.entity_id != original.entity_id
    assert copied.end_mm == pytest.approx((0.0, 10.0), abs=1e-8)
    assert canvas.undo_last_operation()
    assert canvas.entities == [original]
    assert canvas.redo_last_operation()
    assert canvas.entities == [original, copied]


def test_rotate_reference_uses_two_points_independent_of_center(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    original = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    canvas.replace_draft_entities((original,))
    canvas.selected_entity_ids = {original.entity_id}
    bar = editor.drawing_command_bar
    for text in ("RO", "0,0", "R", "10,10", "10,20"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform == "rotate"
    assert canvas.entities == [original]
    assert canvas.rotation_reference_angle == pytest.approx(90.0)
    bar.input.setText("180")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    result = canvas.entities[0]
    assert isinstance(result, LineEntity)
    assert result.entity_id == original.entity_id
    assert result.end_mm == pytest.approx((0.0, 10.0), abs=1e-8)
    assert canvas.undo_last_operation()
    assert canvas.entities == [original]


def test_rotate_reference_rejects_coincident_line_points_and_preserves_copy_mode(
    qtbot: QtBot,
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    original = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    canvas.replace_draft_entities((original,))
    canvas.selected_entity_ids = {original.entity_id}
    bar = editor.drawing_command_bar
    for value in ("ROTATE", "0,0", "COPY", "R", "0,0", "0,0"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform == "rotate" and canvas.entities == [original]
    assert "不能重合" in canvas.message
    for value in ("0,10", "180"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2 and canvas.entities[0] == original
    result = canvas.entities[1]
    assert isinstance(result, LineEntity)
    assert result.end_mm == pytest.approx((0.0, 10.0), abs=1e-8)
    canvas.selected_entity_ids = {original.entity_id}
    for value in ("ROTATE", "0,0", "90"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2


def test_rotate_copy_option_is_available_from_canvas_keyboard(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    original = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    canvas.replace_draft_entities((original,))
    canvas.selected_entity_ids = {original.entity_id}
    bar = editor.drawing_command_bar
    for value in ("RO", "0,0"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClick(canvas, Qt.Key.Key_C)
    QTest.keyClicks(canvas, "90")
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2 and canvas.entities[0] == original
    copied = canvas.entities[1]
    assert isinstance(copied, LineEntity)
    assert copied.entity_id != original.entity_id
    assert copied.end_mm == pytest.approx((0.0, 10.0), abs=1e-8)


def test_spatial_boundary_sources_are_read_only_and_visibility_filtered(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    visible = LineEntity(uuid4().hex, (5, -2), (5, 2))
    hidden = LineEntity(uuid4().hex, (8, -2), (8, 2), layer_name="hidden")
    layers = SketchLayerTable((SketchLayer("0"), SketchLayer("hidden", visible=False)))
    source = Sketch(uuid4().hex, frame, (visible, hidden), layers=layers)
    canvas.set_background_sketches((source,), WorkPlaneFrame.xy())
    assert len(canvas.spatial_boundaries) == 1
    assert canvas.spatial_boundaries[0].sketch_id == source.sketch_id
    assert canvas.spatial_boundaries[0].entity is visible
    assert not canvas.background_entities
    assert visible not in canvas.selectable_entities()


def test_spatial_boundary_preview_projects_without_changing_source(qtbot: QtBot) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    canvas = editor.canvas
    frame = WorkPlaneFrame(
        origin_mm=(2, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    source = LineEntity(uuid4().hex, (5, -2), (5, 2))
    sketch = Sketch(uuid4().hex, frame, (source,))
    canvas.set_background_sketches((sketch,), WorkPlaneFrame.xy())
    paths = canvas.spatial_boundary_paths()
    assert len(paths) == 1 and paths[0][0] == source.entity_id
    assert canvas.spatial_boundary_paths() is paths
    assert paths[0][1][0] == pytest.approx((7, -2))
    assert paths[0][1][1] == pytest.approx((7, 2))
    assert sketch.entities == (source,) and not canvas.background_entities
    changed = LineEntity(source.entity_id, (7, -2), (7, 2))
    canvas.set_background_sketches(
        (Sketch(sketch.sketch_id, frame, (changed,)),), WorkPlaneFrame.xy()
    )
    updated = canvas.spatial_boundary_paths()
    assert updated is not paths and updated[0][1][0] == pytest.approx((9, -2))


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_trim_uses_spatial_boundaries_according_to_projection_mode(qtbot: QtBot, mode: int) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    source = LineEntity(uuid4().hex, (5, -2), (5, 2))
    sketch = Sketch(uuid4().hex, frame, (source,))
    canvas.set_background_sketches((sketch,), WorkPlaneFrame.xy())
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((target,))
    canvas.set_line_edit_projection_mode(mode)
    command = editor.drawing_command_bar.input
    command.setText("TRIM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    canvas.add_coordinate_point((8, 0), exact_point=True)
    if mode == 0:
        assert not canvas.entities
    else:
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
        assert canvas.entities[0].end_mm == pytest.approx((5, 0))
    assert sketch.entities == (source,)
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target]


def test_trim_can_select_one_projected_boundary_explicitly(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    chosen = LineEntity(uuid4().hex, (5, -10), (5, 10))
    other = LineEntity(uuid4().hex, (7, -10), (7, 10))
    sketch = Sketch(uuid4().hex, frame, (chosen, other))
    canvas.set_background_sketches((sketch,), WorkPlaneFrame.xy())
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((target,))
    canvas.set_line_edit_projection_mode(1)
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "C"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 8)))
    assert canvas.selected_entity_ids == {chosen.entity_id}
    QTest.keyClick(command, Qt.Key.Key_Return)
    canvas.add_coordinate_point((8, 0), exact_point=True)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((5, 0))
    assert sketch.entities == (chosen, other)


def test_projected_boundary_can_be_window_selected(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    source = LineEntity(uuid4().hex, (5, -10), (5, 10))
    canvas.set_background_sketches((Sketch(uuid4().hex, frame, (source,)),), WorkPlaneFrame.xy())
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((target,))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "C"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    start, end = canvas.local_to_screen((1, -12)), canvas.local_to_screen((9, 12))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.selected_entity_ids == {source.entity_id}


def test_spatial_boundary_change_during_fence_cancels_atomically(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    source = LineEntity(uuid4().hex, (5, -5), (5, 5))
    sketch_id = uuid4().hex
    canvas.set_background_sketches((Sketch(sketch_id, frame, (source,)),), WorkPlaneFrame.xy())
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((target,))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "F", "8,-2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    changed = LineEntity(source.entity_id, (7, -5), (7, 5))
    canvas.set_background_sketches((Sketch(sketch_id, frame, (changed,)),), WorkPlaneFrame.xy())
    for value in ("8,2", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target]
    assert "变化" in canvas.message


def test_selected_projected_boundary_rejects_changed_source(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    source = LineEntity(uuid4().hex, (5, -10), (5, 10))
    sketch_id = uuid4().hex
    canvas.set_background_sketches((Sketch(sketch_id, frame, (source,)),), WorkPlaneFrame.xy())
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((target,))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "C"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 8)))
    assert canvas.selected_entity_ids == {source.entity_id}
    QTest.keyClick(command, Qt.Key.Key_Return)
    changed = LineEntity(source.entity_id, (7, -10), (7, 10))
    canvas.set_background_sketches((Sketch(sketch_id, frame, (changed,)),), WorkPlaneFrame.xy())
    canvas.add_coordinate_point((8, 0), exact_point=True)
    assert canvas.entities == [target]
    assert "变化" in canvas.message


def test_projected_boundary_extends_draft_arc_and_undoes(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import ArcEntity, LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    source = LineEntity(uuid4().hex, (-5, -3), (-5, 3))
    sketch = Sketch(uuid4().hex, frame, (source,))
    canvas.set_background_sketches((sketch,), WorkPlaneFrame.xy())
    target = ArcEntity(uuid4().hex, (0, 0), 5, 0, 90)
    assert canvas.replace_draft_entities((target,))
    canvas.set_line_edit_projection_mode(1)
    command = editor.drawing_command_bar.input
    command.setText("EXTEND")
    QTest.keyClick(command, Qt.Key.Key_Return)
    canvas.add_coordinate_point((0, 5), exact_point=True)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], ArcEntity)
    assert canvas.entities[0].sweep_angle_deg == pytest.approx(180)
    assert sketch.entities == (source,)
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target]


def test_duplicate_projected_boundary_identity_is_rejected_in_selection(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    source = LineEntity(target.entity_id, (5, -10), (5, 10))
    canvas.set_background_sketches((Sketch(uuid4().hex, frame, (source,)),), WorkPlaneFrame.xy())
    assert canvas.replace_draft_entities((target,))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "C"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 8)))
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target]
    assert "不唯一" in canvas.message


def test_projected_circle_boundary_trims_circle_and_undoes(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import ArcEntity, CircleEntity, Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    source = CircleEntity(uuid4().hex, (4, 0), 5)
    sketch = Sketch(uuid4().hex, frame, (source,))
    canvas.set_background_sketches((sketch,), WorkPlaneFrame.xy())
    target = CircleEntity(uuid4().hex, (0, 0), 5)
    assert canvas.replace_draft_entities((target,))
    canvas.set_line_edit_projection_mode(1)
    command = editor.drawing_command_bar.input
    command.setText("TRIM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    canvas.add_coordinate_point((5, 0), exact_point=True)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], ArcEntity)
    assert canvas.entities[0].entity_id == target.entity_id
    assert canvas.entities[0].sweep_angle_deg > 180
    assert sketch.entities == (source,)
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target]


@pytest.mark.parametrize("closed", [False, True])
def test_spatial_boundary_trims_curved_polyline_and_undoes(qtbot: QtBot, closed: bool) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    source = LineEntity(uuid4().hex, (0, -2), (0, 12))
    sketch = Sketch(uuid4().hex, frame, (source,))
    canvas.set_background_sketches((sketch,), WorkPlaneFrame.xy())
    target = (
        PolylineEntity(uuid4().hex, ((-5, 0), (5, 0), (5, 10), (-5, 10)), True, bulges=(0, 1, 0, 1))
        if closed
        else PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), bulges=(-1,))
    )
    assert canvas.replace_draft_entities((target,))
    canvas.set_line_edit_projection_mode(1)
    command = editor.drawing_command_bar.input
    command.setText("TRIM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    canvas.add_coordinate_point((10, 5) if closed else (4, 3), exact_point=True)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity)
    assert canvas.entities[0].entity_id == target.entity_id
    assert not canvas.entities[0].closed
    assert canvas.entities[0].points_mm[-1] == pytest.approx((0, 0) if closed else (0, 5))
    assert sketch.entities == (source,)
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [target]


def test_no_projection_uses_real_intersection_with_edge_on_boundary(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (5, -2), (5, 2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xz(), (source,))
    canvas.set_background_sketches((sketch,), WorkPlaneFrame.xy())
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((target,))
    canvas.set_line_edit_projection_mode(0)
    command = editor.drawing_command_bar.input
    command.setText("TRIM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    canvas.add_coordinate_point((8, 0), exact_point=True)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((5, 0))
    assert sketch.entities == (source,)


def test_line_command_builds_video_style_two_circle_tangent(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.sketch import CircleEntity, LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    lower = CircleEntity(uuid4().hex, (0, 0), 20)
    right = CircleEntity(uuid4().hex, (90, 45), 30)
    assert canvas.replace_draft_entities((lower, right))
    command = editor.drawing_command_bar.input
    for value in ("LINE", "TAN"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    canvas.add_coordinate_point((6, -19), exact_point=True)
    command.setText("TAN")
    QTest.keyClick(command, Qt.Key.Key_Return)
    canvas.add_coordinate_point((100, 17), exact_point=True)
    assert len(canvas.entities) == 3 and isinstance(canvas.entities[-1], LineEntity)
    line = canvas.entities[-1]
    assert tangent_on_curves(line, lower) and tangent_on_curves(line, right)
    assert line.start_mm[1] < 0 and line.end_mm[1] < right.center_mm[1]
    assert canvas.undo_last_operation() and canvas.entities == [lower, right]


@pytest.mark.parametrize("copy", [False, True])
@pytest.mark.parametrize("point_reference", [False, True])
def test_rotate_reference_points_option_uses_arbitrary_target_line(
    qtbot: QtBot, copy: bool, point_reference: bool
) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar
    values = ["ROTATE", "0,0", *(["COPY"] if copy else []), "R"]
    values += ["10,10", "20,10"] if point_reference else ["0"]
    values += ["P", "30,20", "@0,10"]
    for value in values:
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform is None, bar.status.text()
    result = canvas.entities[-1]
    assert isinstance(result, LineEntity)
    assert result.end_mm == pytest.approx((0, 10), abs=1e-8)
    assert len(canvas.entities) == (2 if copy else 1)
    assert canvas.undo_last_operation() and canvas.entities == [source]


def test_rotate_reference_points_rejects_zero_direction_and_allows_retry(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar
    for value in ("ROTATE", "0,0", "R", "0", "POINTS", "30,20", "@0,0"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.entities == [source] and canvas.rotation_target_points_active
    assert "不能重合" in canvas.message
    bar.input.setText("@0,10")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform is None
    result = canvas.entities[0]
    assert isinstance(result, LineEntity) and result.end_mm == pytest.approx((0, 10), abs=1e-8)


def test_rotate_reference_points_mouse_preview_and_cancel(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar
    for value in ("RO", "0,0", "R", "0", "P"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((30, 20)))
    pixel = canvas.local_to_screen((30, 30))
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
    assert len(canvas.transform_preview_entities) == 1
    preview = canvas.transform_preview_entities[0]
    assert isinstance(preview, LineEntity) and preview.end_mm == pytest.approx((0, 10), abs=0.2)
    assert canvas.entities == [source]
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert canvas.entities == [source] and canvas.active_transform is None
    assert not canvas.transform_preview_entities and not canvas.rotation_target_points_active


def test_rotate_reference_points_option_from_canvas_keyboard(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar
    for value in ("RO", "0,0", "R", "0"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClick(canvas, Qt.Key.Key_P)
    assert canvas.rotation_target_points_active
    QTest.keyClicks(canvas, "90")
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas.entities == [source] and canvas.rotation_target_points_active
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((30, 20)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((30, 30)))
    result = canvas.entities[0]
    assert isinstance(result, LineEntity) and result.end_mm == pytest.approx((0, 10), abs=0.2)


def test_rotate_reference_points_option_requires_complete_reference(qtbot: QtBot) -> None:
    from uuid import uuid4

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import LineEntity
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar
    for value in ("RO", "0,0", "R", "10,10", "P"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert not canvas.rotation_target_points_active and canvas.entities == [source]
    assert "先确定参考角" in canvas.message
    bar.input.clear()
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform == "rotate" and canvas.entities == [source]
    assert "第二参考点" in canvas.message
    bar.input.setText("20,10")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("P")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.rotation_target_points_active
