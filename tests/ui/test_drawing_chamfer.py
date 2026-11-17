# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Interactive independent 2D chamfers."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import ArcEntity, LineEntity, PolylineEntity, RectangleEntity
from mycad.core.sketch_layers import SketchLayer
from mycad.ui.sketch_editor import SketchEditorDialog


@pytest.mark.parametrize("tool", ["二维圆角", "二维倒角"])
@pytest.mark.parametrize("polyline", [False, True])
def test_corner_treats_layer_names_as_case_insensitive(
    qtbot: QtBot, tool: str, polyline: bool
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    editor.canvas.set_layer_table(editor.canvas.layer_table.add(SketchLayer("Edges")), "0")
    first = (
        PolylineEntity(uuid4().hex, ((0, 0), (20, 0)), layer_name="Edges")
        if polyline
        else LineEntity(uuid4().hex, (0, 0), (20, 0), layer_name="Edges")
    )
    second = LineEntity(uuid4().hex, (0, 0), (0, 20), layer_name="EDGES")
    assert editor.canvas.replace_draft_entities((first, second))
    editor.canvas.set_circle_fillet_radius(2)
    editor.canvas.set_chamfer_values((2, 2, 0, 0))
    editor.canvas.circle_fillet_trim = False
    QTest.mouseClick(editor.tool_buttons[tool], Qt.MouseButton.LeftButton)
    for point in ((10, 0), (0, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert len(editor.canvas.entities) == 3, editor.canvas.message
    assert editor.canvas.entities[-1].layer_name.casefold() == "edges"


@pytest.mark.parametrize("tool", ["二维圆角", "二维倒角"])
@pytest.mark.parametrize("rectangle", [False, True])
def test_corner_toolbar_first_pick_shows_selection_and_next_step(
    qtbot: QtBot, tool: str, rectangle: bool
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    entity = (
        RectangleEntity(uuid4().hex, (0, 0), (20, 10))
        if rectangle
        else LineEntity(uuid4().hex, (0, 0), (20, 0))
    )
    assert editor.canvas.replace_draft_entities((entity,))
    QTest.mouseClick(editor.tool_buttons[tool], Qt.MouseButton.LeftButton)
    assert "P" in editor.canvas.message
    assert ("R" if tool == "二维圆角" else "D") in editor.canvas.message
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    assert editor.canvas.selected_entity_ids == {entity.entity_id}
    assert "另" in editor.canvas.message or "第二" in editor.canvas.message
    assert editor.drawing_command_bar.status.text() == editor.canvas.message
    assert editor.canvas.entities == [entity]
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert not editor.canvas.selected_entity_ids


@pytest.mark.parametrize("tool", ["二维圆角", "二维倒角"])
@pytest.mark.parametrize("rectangle", [False, True])
def test_zero_corner_explains_unchanged_and_can_be_retried(
    qtbot: QtBot, tool: str, rectangle: bool
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    first = (
        RectangleEntity(uuid4().hex, (0, 0), (20, 10))
        if rectangle
        else LineEntity(uuid4().hex, (0, 0), (20, 0))
    )
    entities = (first,) if rectangle else (first, LineEntity(uuid4().hex, (0, 0), (0, 10)))
    assert editor.canvas.replace_draft_entities(entities)
    editor.canvas.set_circle_fillet_radius(0)
    points = ((10, 0), (20, 5)) if rectangle else ((10, 0), (0, 5))
    QTest.mouseClick(editor.tool_buttons[tool], Qt.MouseButton.LeftButton)
    for point in points:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert tuple(editor.canvas.entities) == entities
    assert "0" in editor.canvas.message
    assert ("R" if tool == "二维圆角" else "D") in editor.canvas.message
    QTest.mouseClick(editor.tool_buttons[tool], Qt.MouseButton.LeftButton)
    for value in ("R", "2") if tool == "二维圆角" else ("D", "2", "2"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    for point in points:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert tuple(editor.canvas.entities) != entities


@pytest.mark.parametrize("tool,option", [("二维圆角", "R"), ("二维倒角", "D")])
def test_corner_options_can_be_typed_with_canvas_focused(
    qtbot: QtBot, tool: str, option: str
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    QTest.mouseClick(editor.tool_buttons[tool], Qt.MouseButton.LeftButton)
    QTest.keyClicks(editor.canvas, option)
    assert editor.drawing_command_bar.input.text() == option
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert (
        editor.canvas.circle_fillet_radius_pending
        if option == "R"
        else "距离" in editor.drawing_command_bar.status.text()
    )


def test_chamfer_toolbar_prompt_shows_active_angle_method(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    QTest.mouseClick(editor.tool_buttons["二维倒角"], Qt.MouseButton.LeftButton)
    command = editor.drawing_command_bar.input
    for value in ("A", "4", "30"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.set_tool("选择元素")
    assert editor.canvas.set_tool("二维倒角")
    assert "4" in editor.canvas.message
    assert "30" in editor.canvas.message
    assert "角度" in editor.canvas.message
    assert editor.drawing_command_bar.status.text() == editor.canvas.message


@pytest.mark.parametrize("tool", ["二维圆角", "二维倒角"])
@pytest.mark.parametrize("rectangle", [False, True])
@pytest.mark.parametrize("start_point", [(-3, 7), (0, 4)])
def test_corner_drag_across_two_edges(
    qtbot: QtBot, tool: str, rectangle: bool, start_point: tuple[int, int]
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    first = (
        RectangleEntity(uuid4().hex, (0, 0), (20, 10))
        if rectangle
        else LineEntity(uuid4().hex, (0, 0), (20, 0))
    )
    source = (first,) if rectangle else (first, LineEntity(uuid4().hex, (0, 0), (0, 10)))
    assert editor.canvas.replace_draft_entities(source)
    QTest.mouseClick(editor.tool_buttons[tool], Qt.MouseButton.LeftButton)
    for value in ("R", "1") if tool == "二维圆角" else ("D", "1", "1"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    start = editor.canvas.local_to_screen(start_point)
    end = editor.canvas.local_to_screen((7, -3))
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tuple(editor.canvas.entities) != source, editor.canvas.message
    assert editor.canvas.undo_last_operation()
    assert tuple(editor.canvas.entities) == source


def test_fillet_drag_crosses_circle_twice_and_line_once(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    line = LineEntity(uuid4().hex, (-20, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    assert editor.canvas.replace_draft_entities((line, circle))
    QTest.mouseClick(editor.tool_buttons["二维圆角"], Qt.MouseButton.LeftButton)
    for value in ("R", "2"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    start = editor.canvas.local_to_screen((-1, 8))
    end = editor.canvas.local_to_screen((-3, -2))
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert any(isinstance(entity, ArcEntity) for entity in editor.canvas.entities), (
        editor.canvas.message
    )
    assert circle in editor.canvas.entities
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [line, circle]


@pytest.mark.parametrize("tool", ["二维圆角", "二维倒角"])
def test_corner_multiple_drag_and_escape(qtbot: QtBot, tool: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    source = tuple(
        line
        for x in (0, 30)
        for line in (
            LineEntity(uuid4().hex, (x, 0), (x + 20, 0)),
            LineEntity(uuid4().hex, (x, 0), (x, 10)),
        )
    )
    assert editor.canvas.replace_draft_entities(source)
    QTest.mouseClick(editor.tool_buttons[tool], Qt.MouseButton.LeftButton)
    assert "M 连续" in editor.canvas.message
    for value in ("R", "1", "M") if tool == "二维圆角" else ("D", "1", "1", "M"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    for x in (0, 30):
        start = editor.canvas.local_to_screen((x - 3, 7))
        end = editor.canvas.local_to_screen((x + 7, -3))
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(editor.canvas, end)
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
        assert editor.canvas.tool == tool, editor.canvas.message
    assert len(editor.canvas.entities) == 6
    assert "继续" in editor.canvas.message
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert editor.canvas.tool == "选择元素"


@pytest.mark.parametrize("tool", ["二维圆角", "二维倒角"])
def test_corner_drag_rejects_three_edges_and_escape(qtbot: QtBot, tool: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    source = tuple(LineEntity(uuid4().hex, (x, 0), (x, 10)) for x in (0, 5, 10))
    assert editor.canvas.replace_draft_entities(source)
    QTest.mouseClick(editor.tool_buttons[tool], Qt.MouseButton.LeftButton)
    start = editor.canvas.local_to_screen((-3, 5))
    end = editor.canvas.local_to_screen((13, 5))
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tuple(editor.canvas.entities) == source
    assert "两条" in editor.canvas.message
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tuple(editor.canvas.entities) == source
    assert "取消" in editor.canvas.message


@pytest.mark.parametrize("tool", ["二维圆角", "二维倒角"])
@pytest.mark.parametrize("finish", ["enter", "space", "right"])
def test_corner_multiple_can_finish_from_canvas(qtbot: QtBot, tool: str, finish: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    QTest.mouseClick(editor.tool_buttons[tool], Qt.MouseButton.LeftButton)
    editor.drawing_command_bar.input.setText("M")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    if finish == "right":
        QTest.mouseClick(editor.canvas, Qt.MouseButton.RightButton)
    else:
        QTest.keyClick(editor.canvas, Qt.Key.Key_Return if finish == "enter" else Qt.Key.Key_Space)
    assert editor.canvas.tool == "选择元素"


@pytest.mark.parametrize("tool", ["二维圆角", "二维倒角"])
def test_corner_drag_rejects_changed_document(qtbot: QtBot, tool: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    source = (
        LineEntity(uuid4().hex, (0, 0), (20, 0)),
        LineEntity(uuid4().hex, (0, 0), (0, 10)),
    )
    assert editor.canvas.replace_draft_entities(source)
    revision = [1]
    editor.canvas.source_revision_provider = lambda: revision[0]
    QTest.mouseClick(editor.tool_buttons[tool], Qt.MouseButton.LeftButton)
    start = editor.canvas.local_to_screen((-3, 7))
    end = editor.canvas.local_to_screen((7, -3))
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    revision[0] = 2
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tuple(editor.canvas.entities) == source
    assert "已变化" in editor.canvas.message


@pytest.mark.parametrize("tool", ["二维圆角", "二维倒角"])
def test_corner_failed_drag_can_change_size_and_retry(qtbot: QtBot, tool: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    source = (
        LineEntity(uuid4().hex, (0, 0), (10, 0)),
        LineEntity(uuid4().hex, (0, 0), (0, 10)),
    )
    assert editor.canvas.replace_draft_entities(source)
    QTest.mouseClick(editor.tool_buttons[tool], Qt.MouseButton.LeftButton)
    command = editor.drawing_command_bar.input
    for value in ("R", "20") if tool == "二维圆角" else ("D", "20", "20"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    start = editor.canvas.local_to_screen((-3, 7))
    end = editor.canvas.local_to_screen((7, -3))
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tuple(editor.canvas.entities) == source
    assert not editor.canvas.has_active_edit_gesture
    assert editor.canvas.tool == tool
    for value in ("R", "1") if tool == "二维圆角" else ("D", "1", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tuple(editor.canvas.entities) != source, editor.canvas.message


@pytest.mark.parametrize("tool,option", [("二维圆角", "R"), ("二维倒角", "D")])
@pytest.mark.parametrize("gesture", [False, True])
def test_corner_toolbar_saved_rectangle_keyboard_and_undo(
    qtbot: QtBot, tool: str, option: str, gesture: bool
) -> None:
    from mycad import app
    from mycad.core.sketch import PolylineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 10))
    assert editor.canvas.replace_draft_entities((rectangle,))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    QTest.mouseClick(editor.tool_buttons[tool], Qt.MouseButton.LeftButton)
    QTest.keyClicks(editor.canvas, option)
    command = editor.drawing_command_bar.input
    assert command.text() == option
    QTest.keyClick(command, Qt.Key.Key_Return)
    for _ in range(1 if option == "R" else 2):
        QTest.keyClicks(command, "2")
        QTest.keyClick(command, Qt.Key.Key_Return)
    count = len(loaded.document.commands)
    if gesture:
        start = editor.canvas.local_to_screen((-3, 7))
        end = editor.canvas.local_to_screen((7, -3))
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(editor.canvas, end)
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    else:
        for point in ((10, 0), (20, 5)):
            QTest.mouseClick(
                editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
            )
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    result = services.kernel.sketches[0].entities[0]
    assert isinstance(result, PolylineEntity) and result != rectangle
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == (rectangle,)
    loaded.bus.redo()
    assert services.kernel.sketches[0].entities == (result,)


@pytest.mark.parametrize("tool", ["二维圆角", "二维倒角"])
def test_corner_multiple_drag_saved_rectangle(qtbot: QtBot, tool: str) -> None:
    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 10))
    assert editor.canvas.replace_draft_entities((rectangle,))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    QTest.mouseClick(editor.tool_buttons[tool], Qt.MouseButton.LeftButton)
    for value in ("R", "1", "M") if tool == "二维圆角" else ("D", "1", "1", "M"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    before = len(loaded.document.commands)
    for index, (start_point, end_point) in enumerate(
        (((-3, 7), (7, -3)), ((23, 7), (13, -3))), start=1
    ):
        start = editor.canvas.local_to_screen(start_point)
        end = editor.canvas.local_to_screen(end_point)
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(editor.canvas, end)
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
        qtbot.waitUntil(
            lambda expected=before + index: (
                not unit.is_busy and len(loaded.document.commands) == expected
            ),
            timeout=10000,
        )
        assert editor.canvas.tool == tool
    changed = services.kernel.sketches[0].entities
    assert changed != (rectangle,)
    loaded.bus.undo()
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == (rectangle,)
    loaded.bus.redo()
    loaded.bus.redo()
    assert services.kernel.sketches[0].entities == changed


@pytest.mark.parametrize("source,target", [("FILLET", "CHAMFER"), ("CHAMFER", "FILLET")])
@pytest.mark.parametrize("trim", [False, True])
def test_corner_commands_share_trim_mode_and_apply_it(
    qtbot: QtBot, source: str, target: str, trim: bool
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 20))
    assert editor.canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("TRIMMODE", "0" if trim else "1", source, "T", "T" if trim else "N", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    entries = (target, "D", "2", "2") if target == "CHAMFER" else (target, "R", "2")
    for value in entries:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((10, 0), (0, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    entities = editor.canvas.entities
    assert len(entities) == 3
    assert (first in entities and second in entities) is (not trim)
    assert isinstance(entities[-1], LineEntity if target == "CHAMFER" else ArcEntity)


def test_trimmode_command_updates_both_corner_tools_and_rejects_invalid(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("TRIMMODE", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert "0 或 1" in editor.drawing_command_bar.status.text()
    assert editor.canvas.chamfer_trim and editor.canvas.circle_fillet_trim
    command.setText("0")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert not editor.canvas.chamfer_trim and not editor.canvas.circle_fillet_trim
    for value in ("TRIMMODE", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.chamfer_trim and editor.canvas.circle_fillet_trim


@pytest.mark.parametrize("tool", ["FILLET", "CHAMFER"])
@pytest.mark.parametrize("value", ["", "M", "D"])
def test_trimmode_prompt_has_priority_over_active_corner_command(
    qtbot: QtBot, tool: str, value: str
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for text in (tool, "TRIMMODE", value):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.tool == ("二维圆角" if tool == "FILLET" else "二维倒角")
    assert not editor.canvas.circle_fillet_multiple
    if value:
        assert "TRIMMODE 请输入" in bar.status.text()
        bar.input.setText("")
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "TRIMMODE 当前值" in bar.status.text()
    bar.input.setText("M")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.circle_fillet_multiple


def test_fillet_trim_prompt_rejects_trimmode_command(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for value in ("FILLET", "T", "TRIMMODE"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "请输入 T" in bar.status.text()
    bar.input.setText("N")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert not editor.canvas.circle_fillet_trim
    assert not editor.canvas.circle_fillet_trim_pending


@pytest.mark.parametrize("setting,value", [("OFFSETGAPTYPE", "2"), ("EDGEMODE", "1")])
def test_trimmode_does_not_interrupt_other_system_prompt(
    qtbot: QtBot, setting: str, value: str
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for entry in (setting, "TRIMMODE", value):
        bar.input.setText(entry)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.chamfer_trim
    if setting == "OFFSETGAPTYPE":
        assert editor.canvas.offset_gap_type == 2
    else:
        assert editor.canvas.line_edit_extend_boundaries


def test_trimmode_escape_clears_prompt(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for value in ("CHAMFER", "TRIMMODE"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    bar.input.setText("FILLET")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.tool == "二维圆角"
    assert editor.canvas.circle_fillet_trim


def test_trimmode_continues_with_workspace(qtbot: QtBot) -> None:
    previous = SketchEditorDialog(select_committed_entities=True)
    continued = SketchEditorDialog(select_committed_entities=True)
    for editor in (previous, continued):
        qtbot.addWidget(editor)
        editor.show()
    command = previous.drawing_command_bar.input
    for value in ("TRIMMODE", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    continued.continue_workspace_from(previous)
    assert not continued.canvas.chamfer_trim and not continued.canvas.circle_fillet_trim


def test_trimmode_shared_across_documents_and_new_windows(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    def user_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", user_settings)
    window = MainWindow(services=build_app(discoverers=()), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    first = window.active_sketch_dialog()
    assert first is not None
    assert window.document_session is not None and window.document_session.active is not None
    first_id = window.document_session.active.loaded.document.document_id
    window.act_new_drawing.trigger()
    second = window.active_sketch_dialog()
    assert second is not None and second is not first
    command = second.drawing_command_bar.input
    for value in ("FILLET", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not first.canvas.chamfer_trim and not second.canvas.circle_fillet_trim
    window.activate_session_document(first_id)
    assert window.active_sketch_dialog() is first
    command = first.drawing_command_bar.input
    for value in ("TRIMMODE", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert first.canvas.circle_fillet_trim and second.canvas.chamfer_trim
    for value in ("TRIMMODE", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    settings.sync()
    another = MainWindow(services=build_app(discoverers=()), document_session=DocumentSession())
    qtbot.addWidget(another)
    another.show()
    another.act_new_drawing.trigger()
    reopened = another.active_sketch_dialog()
    assert reopened is not None and not reopened.canvas.chamfer_trim


@pytest.mark.skipif(sys.platform != "linux", reason="isolates QSettings through XDG on Linux")
def test_trimmode_survives_application_restart(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "QT_QPA_PLATFORM": "offscreen",
            "QT_IM_MODULE": "compose",
        }
    )
    env.pop("QT_PLUGIN_PATH", None)
    common = """
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from mycad.app import build_app
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow
application = QApplication([])
window = MainWindow(services=build_app(discoverers=()), document_session=DocumentSession())
window._ask_session_close_dialog = lambda pending: {
    entry.loaded.document.document_id: 'discard' for entry in pending
}
window.show()
window.act_new_drawing.trigger()
editor = window.active_sketch_dialog()
assert editor is not None
"""
    save = (
        common
        + """
assert editor.canvas.chamfer_trim
for value in ('CHAMFER', 'T', 'N'):
    editor.drawing_command_bar.input.setText(value)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
assert not editor.canvas.circle_fillet_trim
window.close()
"""
    )
    reopen = (
        common
        + """
assert not editor.canvas.chamfer_trim and not editor.canvas.circle_fillet_trim
window.close()
"""
    )
    for script in (save, reopen):
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr[-4000:]


def test_chamfer_command_distance_trim_and_undo(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 20))
    assert editor.canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("CHAMFER", "D", "2", "3"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((10, 0), (0, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    entities = editor.canvas.entities
    assert len(entities) == 3 and all(isinstance(item, LineEntity) for item in entities)
    assert isinstance(entities[0], LineEntity) and entities[0].start_mm == pytest.approx((2, 0))
    assert isinstance(entities[1], LineEntity) and entities[1].start_mm == pytest.approx((0, 3))
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == [first, second]
    assert editor.canvas.redo_last_operation() and len(editor.canvas.entities) == 3


@pytest.mark.parametrize("value", ["", "D", "R", "T", "M", "U", "LINE"])
@pytest.mark.parametrize("tool", ["CHAMFER", "FILLET"])
def test_polyline_selection_does_not_execute_other_options(
    qtbot: QtBot, value: str, tool: str
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    for entry in (tool, "P", value):
        command.setText(entry)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.tool == ("二维倒角" if tool == "CHAMFER" else "二维圆角")
    assert (
        editor.canvas.chamfer_polyline_pending
        if tool == "CHAMFER"
        else editor.canvas.circle_fillet_polyline_pending
    )
    assert not editor.canvas.circle_fillet_multiple
    if tool == "FILLET" and value == "T":
        assert editor.canvas.circle_fillet_trim_pending
        command.setText("T")
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert editor.canvas.circle_fillet_trim
        assert not editor.canvas.circle_fillet_trim_pending
        assert editor.canvas.circle_fillet_polyline_pending
    else:
        assert "请选择多段线" in editor.drawing_command_bar.status.text()
    QTest.keyClick(command, Qt.Key.Key_Escape)
    assert not editor.canvas.chamfer_polyline_pending
    assert not editor.canvas.circle_fillet_polyline_pending


@pytest.mark.parametrize("tool", ["CHAMFER", "FILLET"])
def test_polyline_selection_still_completes_after_ignored_input(qtbot: QtBot, tool: str) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)))
    assert editor.canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    entries = (tool, "D", "2", "2", "P", "LINE") if tool == "CHAMFER" else (tool, "P", "LINE")
    for entry in entries:
        command.setText(entry)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    assert editor.canvas.entities != [source]
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [source]


@pytest.mark.parametrize("option", ["distance", "angle"])
def test_chamfer_command_no_trim_and_cancel(qtbot: QtBot, option: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    lines = (
        LineEntity(uuid4().hex, (0, 0), (20, 0)),
        LineEntity(uuid4().hex, (0, 0), (0, 20)),
    )
    assert editor.canvas.replace_draft_entities(lines)
    command = editor.drawing_command_bar.input
    values = (
        ("CHAMFER", "T", "N", "D", "2", "2")
        if option == "distance"
        else ("CHAMFER", "T", "N", "A", "2", "45")
    )
    for value in values:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((10, 0), (0, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert tuple(editor.canvas.entities[:2]) == lines
    edge = editor.canvas.entities[2]
    assert isinstance(edge, LineEntity)
    assert edge.start_mm == pytest.approx((2, 0)) and edge.end_mm == pytest.approx((0, 2))
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == list(lines)
    for value in ("CHAMFER", "D", "3"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.keyClick(command, Qt.Key.Key_Escape)
    assert editor.canvas.entities == list(lines)


@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("trim", [False, True])
def test_chamfer_saved_sources_replay_and_undo(
    qtbot: QtBot, tmp_path: object, mixed: bool, trim: bool
) -> None:
    from pathlib import Path

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    assert isinstance(tmp_path, Path)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 20))
    assert editor.canvas.replace_draft_entities((first,) if mixed else (first, second))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    if mixed:
        assert canvas.replace_draft_entities((second,))
    command = editor.drawing_command_bar.input
    for value in ["CHA", "D", "2", "3"] + ([] if trim else ["T", "N"]):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((10, 0), (0, 10)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    edge = next(
        item
        for item in canvas.entities
        if isinstance(item, LineEntity)
        and item.start_mm == pytest.approx((2, 0))
        and item.end_mm == pytest.approx((0, 3))
    )
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    loaded = window.loaded_document()
    assert loaded is not None
    changed = services.kernel.sketches
    path = tmp_path / "chamfer.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == changed
    reopened.bus.undo()
    assert all(edge not in sketch.entities for sketch in reopened_services.kernel.sketches)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == changed


def test_2d_fillet_and_chamfer_use_distinct_planar_icons(qtbot: QtBot) -> None:
    from mycad.ui.cad_icons import cad_icon

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    fillet = editor.tool_buttons["二维圆角"].icon()
    chamfer = editor.tool_buttons["二维倒角"].icon()
    assert not fillet.isNull() and not chamfer.isNull()
    assert fillet.pixmap(32, 32).toImage() != cad_icon("fillet").pixmap(32, 32).toImage()
    assert fillet.pixmap(32, 32).toImage() != chamfer.pixmap(32, 32).toImage()


@pytest.mark.parametrize("trim", [False, True])
def test_chamfer_polyline_all_corners(qtbot: QtBot, trim: bool) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)))
    assert editor.canvas.replace_draft_entities((polyline,))
    command = editor.drawing_command_bar.input
    values = ["CHAMFER", "D", "2", "3"] + ([] if trim else ["T", "N"]) + ["P"]
    for value in values:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    command.setText("M")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.chamfer_polyline_pending
    assert not editor.canvas.circle_fillet_multiple
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    if trim:
        result = editor.canvas.entities[0]
        assert isinstance(result, PolylineEntity)
        assert result.points_mm == ((0, 0), (18, 0), (20, 3), (20, 20))
    else:
        assert editor.canvas.entities[0] == polyline
        edge = editor.canvas.entities[1]
        assert isinstance(edge, LineEntity)
        assert edge.start_mm == pytest.approx((18, 0)) and edge.end_mm == pytest.approx((20, 3))
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == [polyline]


def test_chamfer_two_selected_polyline_segments_follow_pick_order(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20), (40, 20)))
    assert editor.canvas.replace_draft_entities((polyline,))
    command = editor.drawing_command_bar.input
    for value in ("CHA", "D", "2", "3"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((20, 10), (10, 0)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    result = editor.canvas.entities[0]
    assert isinstance(result, PolylineEntity)
    assert result.points_mm == ((0, 0), (17, 0), (20, 2), (20, 20), (40, 20))


def test_chamfer_defaults_enter_and_method_history(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("CHAMFER", "D", "2", "3", "A", "4", "30", "E", "D", "E", "A"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.chamfer_first_distance == 4
    assert editor.canvas.chamfer_second_distance == 3
    assert editor.canvas.chamfer_angle == 30
    for value in ("D", "", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.chamfer_first_distance == 2 and editor.canvas.chamfer_second_distance == 3
    command.setText("")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.tool == "选择元素"


def test_chamfer_method_keeps_separate_distance_and_angle_lengths(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    editor.canvas.entities = [
        LineEntity(uuid4().hex, (0, 0), (20, 0)),
        LineEntity(uuid4().hex, (0, 0), (0, 20)),
    ]
    command = editor.drawing_command_bar.input
    for value in ("CHAMFER", "D", "2", "3", "A", "4", "30", "E", "D"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.chamfer_first_distance == 2
    for point in ((15, 0), (0, 15)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert any(
        isinstance(entity, LineEntity)
        and {entity.start_mm, entity.end_mm} == {(2.0, 0.0), (0.0, 3.0)}
        for entity in editor.canvas.entities
    )
    assert editor.canvas.undo_last_operation()
    for value in ("CHAMFER", "E", "A"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.chamfer_first_distance == 4
    assert editor.canvas.chamfer_angle == 30
    for point in ((15, 0), (0, 15)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert any(
        isinstance(entity, LineEntity)
        and entity.start_mm == pytest.approx((4, 0))
        and entity.end_mm == pytest.approx((0, 4 / 3**0.5))
        for entity in editor.canvas.entities
    )


def test_chamfer_method_distances_continue_with_workspace(qtbot: QtBot) -> None:
    previous = SketchEditorDialog(select_committed_entities=True)
    continued = SketchEditorDialog(select_committed_entities=True)
    for editor in (previous, continued):
        qtbot.addWidget(editor)
        editor.show()
    command = previous.drawing_command_bar.input
    for value in ("CHAMFER", "D", "2", "3", "A", "4", "30"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    continued.continue_workspace_from(previous)
    command = continued.drawing_command_bar.input
    for value in ("CHAMFER", "E", "D"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert continued.canvas.chamfer_first_distance == 2
    assert continued.canvas.chamfer_second_distance == 3
    for value in ("E", "A"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert continued.canvas.chamfer_first_distance == 4
    assert continued.canvas.chamfer_angle == 30


@pytest.mark.parametrize(
    ("name", "value", "attribute"),
    [
        ("CHAMFERA", "2", "chamfer_distance_first"),
        ("CHAMFERB", "3", "chamfer_second_distance"),
        ("CHAMFERC", "4", "chamfer_angle_length"),
        ("CHAMFERD", "30", "chamfer_last_angle"),
    ],
)
def test_chamfer_system_variable_query_set_and_invalid_retry(
    qtbot: QtBot, name: str, value: str, attribute: str
) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for entry in (name, "-1"):
        bar.input.setText(entry)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "请输入" in bar.status.text()
    bar.input.setText(value)
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert getattr(editor.canvas, attribute) == float(value)
    for entry in (name, ""):
        bar.input.setText(entry)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert f"{name} 当前值 {value}" in bar.status.text()


def test_chamfer_system_prompt_priority_and_escape(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for entry in ("CHAMFER", "CHAMFERA", "M"):
        bar.input.setText(entry)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "CHAMFERA 请输入" in bar.status.text()
    assert not editor.canvas.circle_fillet_multiple
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    bar.input.setText("CHAMFER")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.tool == "二维倒角"
    for entry in ("D", "CHAMFERA", "2", "3"):
        bar.input.setText(entry)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.chamfer_distance_first == 2
    assert editor.canvas.chamfer_second_distance == 3


def test_chamfer_angle_system_variable_rejects_out_of_range(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for entry in ("CHAMFERD", "180", "inf", "nan"):
        bar.input.setText(entry)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
        if entry != "CHAMFERD":
            assert "CHAMFERD 请输入" in bar.status.text()
    bar.input.setText("0")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.chamfer_last_angle == 0


def test_chammode_query_set_and_method_options_are_consistent(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for entry in ("CHAMMODE", "2"):
        bar.input.setText(entry)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "CHAMMODE 请输入" in bar.status.text()
    bar.input.setText("1")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.chamfer_angle == 45
    for entry in ("CHAMFER", "E", "D", "", "CHAMMODE", ""):
        bar.input.setText(entry)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "CHAMMODE 当前值 0" in bar.status.text()
    for entry in ("CHAMFER", "A", "4", "30", "", "CHAMMODE", ""):
        bar.input.setText(entry)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert "CHAMMODE 当前值 1" in bar.status.text()


def test_chammode_is_shared_in_session_but_not_saved(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    first = window.active_sketch_dialog()
    assert first is not None
    assert window.document_session is not None and window.document_session.active is not None
    first_id = window.document_session.active.loaded.document.document_id
    window.act_new_drawing.trigger()
    second = window.active_sketch_dialog()
    assert second is not None and second is not first
    for entry in ("CHAMFERC", "4", "CHAMMODE", "1"):
        second.drawing_command_bar.input.setText(entry)
        QTest.keyClick(second.drawing_command_bar.input, Qt.Key.Key_Return)
    assert first.canvas.chamfer_angle is not None and second.canvas.chamfer_angle is not None
    assert first.canvas.chamfer_first_distance == 0
    assert second.canvas.chamfer_first_distance == 4
    window.activate_session_document(first_id)
    for entry in ("CHAMFER", "E", "D", "A", "5", "30"):
        first.drawing_command_bar.input.setText(entry)
        QTest.keyClick(first.drawing_command_bar.input, Qt.Key.Key_Return)
        if entry == "D":
            assert second.canvas.chamfer_angle is None
    assert first.canvas.chamfer_first_distance == 5
    assert second.canvas.chamfer_angle is not None and second.canvas.chamfer_first_distance == 4
    reopened = MainWindow(
        services=app.build_app(discoverers=[]), document_session=DocumentSession()
    )
    qtbot.addWidget(reopened)
    reopened.show()
    reopened.act_new_drawing.trigger()
    fresh = reopened.active_sketch_dialog()
    assert fresh is not None and fresh.canvas.chamfer_angle is None


@pytest.mark.parametrize("trim", [False, True])
def test_saved_polyline_chamfer_replay(qtbot: QtBot, tmp_path: object, trim: bool) -> None:
    from pathlib import Path

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity
    from mycad.ui.main_window import MainWindow

    assert isinstance(tmp_path, Path)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    original = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)))
    assert editor.canvas.replace_draft_entities((original,))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    loaded = window.loaded_document()
    assert loaded is not None
    before_count = len(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ["CHA", "D", "2", "3"] + ([] if trim else ["T", "N"]) + ["P"]:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    before_count = len(loaded.document.commands)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    if trim:
        qtbot.waitUntil(
            lambda: not unit.is_busy and len(loaded.document.commands) == before_count + 1,
            timeout=10000,
        )
        assert canvas.tool == "选择元素"
    else:
        assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
        editor.finish_sketch()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
    changed = services.kernel.sketches
    path = tmp_path / "polyline-chamfer.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == changed
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0].entities == (original,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == changed


def test_chamfer_multiple_undo_of_saved_polyline_uses_document_history(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import PolylineEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)))
    assert editor.canvas.replace_draft_entities((polyline,))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    command = editor.drawing_command_bar.input
    before = len(loaded.document.commands)
    for value in ("CHA", "D", "2", "3", "M", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    before = len(loaded.document.commands)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )
    assert editor.canvas.tool == "二维倒角"
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before, timeout=10000
    )
    assert services.kernel.sketches[0].entities == (polyline,)


def test_chamfer_multiple_undo_only_its_own_draft_operation(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 20))
    assert editor.canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("CHA", "D", "2", "3", "M"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((10, 0), (0, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert len(editor.canvas.entities) == 3
    for _ in range(2):
        command.setText("U")
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert editor.canvas.entities == [first, second]


@pytest.mark.parametrize("polyline_first", [False, True])
@pytest.mark.parametrize("trim", [False, True])
def test_chamfer_polyline_and_line(qtbot: QtBot, polyline_first: bool, trim: bool) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    line = LineEntity(uuid4().hex, (15, -10), (15, -2))
    assert editor.canvas.replace_draft_entities((source, line))
    command = editor.drawing_command_bar.input
    for value in ["CHA", "D", "2", "2"] + ([] if trim else ["T", "N"]):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    points = ((5, 0), (15, -8)) if polyline_first else ((15, -8), (5, 0))
    for point in points:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    if trim:
        assert len(editor.canvas.entities) == 1
        result = editor.canvas.entities[0]
        assert isinstance(result, PolylineEntity) and result.entity_id == source.entity_id
        assert len(result.points_mm) == 4
    else:
        assert editor.canvas.entities[:2] == [source, line]
        assert len(editor.canvas.entities) == 3 and isinstance(
            editor.canvas.entities[2], LineEntity
        )
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == [source, line]


def test_saved_polyline_and_line_chamfer_is_atomic_and_replayable(
    qtbot: QtBot, tmp_path: object
) -> None:
    from pathlib import Path

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity
    from mycad.ui.main_window import MainWindow

    assert isinstance(tmp_path, Path)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    line = LineEntity(uuid4().hex, (15, -10), (15, -2))
    assert editor.canvas.replace_draft_entities((polyline, line))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    before = len(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("CHA", "D", "2", "3"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    before = len(loaded.document.commands)
    for point in ((5, 0), (15, -8)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )
    changed = services.kernel.sketches
    assert len(changed[0].entities) == 1 and editor.canvas.tool == "选择元素"
    path = tmp_path / "joined-chamfer.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == changed
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0].entities == (polyline, line)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == changed


@pytest.mark.parametrize("trim", [False, True])
def test_chamfer_rectangle_all_corners(qtbot: QtBot, trim: bool) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 10))
    assert editor.canvas.replace_draft_entities((rectangle,))
    command = editor.drawing_command_bar.input
    for value in ["CHA", "D", "2", "2"] + ([] if trim else ["T", "N"]) + ["P"]:
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    if trim:
        assert len(editor.canvas.entities) == 1
        result = editor.canvas.entities[0]
        assert isinstance(result, PolylineEntity) and result.closed and len(result.points_mm) == 8
        assert result.entity_id != rectangle.entity_id
    else:
        assert editor.canvas.entities[0] == rectangle and len(editor.canvas.entities) == 5
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == [rectangle]


def test_saved_rectangle_chamfer_replaces_identity_and_replays(
    qtbot: QtBot, tmp_path: object
) -> None:
    from pathlib import Path

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.ui.main_window import MainWindow

    assert isinstance(tmp_path, Path)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 10))
    assert editor.canvas.replace_draft_entities((rectangle,))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    count = len(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("CHA", "D", "2", "2", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    count = len(loaded.document.commands)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count + 1, timeout=10000
    )
    result = services.kernel.sketches[0].entities[0]
    assert isinstance(result, PolylineEntity) and result.entity_id != rectangle.entity_id
    path = tmp_path / "rectangle-chamfer.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == (result,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0].entities == (rectangle,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches[0].entities == (result,)


def test_chamfer_two_rectangle_edges(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 10))
    assert editor.canvas.replace_draft_entities((rectangle,))
    command = editor.drawing_command_bar.input
    for value in ("CHA", "D", "2", "3"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((10, 0), (20, 5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    result = editor.canvas.entities[0]
    assert isinstance(result, PolylineEntity) and result.closed and len(result.points_mm) == 5
    assert (18, 0) in result.points_mm and (20, 3) in result.points_mm
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == [rectangle]


@pytest.mark.parametrize("trim", [False, True])
def test_chamfer_polyline_segments_replace_intervening_arc(qtbot: QtBot, trim: bool) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    source = PolylineEntity(
        uuid4().hex, ((0, 0), (8, 0), (10, 2), (10, 10)), bulges=(0, 2**0.5 - 1, 0)
    )
    assert editor.canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ["CHA", "D", "2", "3"] + ([] if trim else ["T", "N"]):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((4, 0), (10, 6)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    if trim:
        result = editor.canvas.entities[0]
        assert isinstance(result, PolylineEntity) and not result.bulges
        assert result.points_mm == ((0, 0), (8, 0), (10, 3), (10, 10))
    else:
        assert editor.canvas.entities[0] == source
        assert len(editor.canvas.entities) == 2 and isinstance(
            editor.canvas.entities[1], LineEntity
        )
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == [source]


def test_chamfer_open_polyline_end_segments_closes_path(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (2, 2)))
    assert editor.canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("CHA", "D", "2", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((2, 0), (3, 3)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    result = editor.canvas.entities[0]
    assert (
        isinstance(result, PolylineEntity)
        and result.closed
        and result.entity_id == source.entity_id
    )
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == [source]


@pytest.mark.parametrize("rectangle_first", [False, True])
@pytest.mark.parametrize("trim", [False, True])
def test_chamfer_rectangle_and_line(qtbot: QtBot, rectangle_first: bool, trim: bool) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    line = LineEntity(uuid4().hex, (5, -10), (5, -2))
    assert editor.canvas.replace_draft_entities((rectangle, line))
    command = editor.drawing_command_bar.input
    for value in ["CHA", "D", "1", "1"] + ([] if trim else ["T", "N"]):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    points = ((2, 0), (5, -8)) if rectangle_first else ((5, -8), (2, 0))
    for point in points:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    if trim:
        assert len(editor.canvas.entities) == 1
        result = editor.canvas.entities[0]
        assert isinstance(result, PolylineEntity) and result.entity_id != rectangle.entity_id
    else:
        assert editor.canvas.entities[:2] == [rectangle, line]
        assert len(editor.canvas.entities) == 3 and isinstance(
            editor.canvas.entities[-1], LineEntity
        )
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == [rectangle, line]


def test_saved_rectangle_and_line_chamfer_replays(qtbot: QtBot) -> None:
    from mycad import app
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
    line = LineEntity(uuid4().hex, (5, -10), (5, -2))
    assert editor.canvas.replace_draft_entities((rectangle, line))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    before = len(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("CHA", "D", "1", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    before = len(loaded.document.commands)
    for point in ((2, 0), (5, -8)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )
    result = services.kernel.sketches[0].entities[0]
    assert isinstance(result, PolylineEntity) and result.entity_id != rectangle.entity_id
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == (rectangle, line)
    loaded.bus.redo()
    assert services.kernel.sketches[0].entities == (result,)


def test_chamfer_closed_polyline_separated_segments_across_seam(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1100, 800)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5), (10, 5), (10, -5)), closed=True)
    assert editor.canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("CHA", "D", "1", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8, -4), (5, 4)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    result = editor.canvas.entities[0]
    assert isinstance(result, PolylineEntity) and result.closed and result != source
    assert (0, 0) not in result.points_mm and (5, 0) not in result.points_mm
    assert editor.canvas.undo_last_operation() and editor.canvas.entities == [source]
