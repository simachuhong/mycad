# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Saved drawing entities remain selectable after the real GUI save/open cycle."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.app import build_app
from mycad.core.sketch import LineEntity
from mycad.ui.main_window import MainWindow


@pytest.fixture
def reopened_drawing(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[MainWindow, LineEntity, LineEntity]:
    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    inside = LineEntity(uuid4().hex, (-5.0, 0.0), (5.0, 0.0))
    crosses = LineEntity(uuid4().hex, (-30.0, 5.0), (30.0, 5.0))
    draft.canvas.replace_draft_entities((inside, crosses))
    draft.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not None and not unit.is_busy,
        timeout=10000,
    )
    submitted = window.active_sketch_dialog()
    assert submitted is not None and submitted is not draft
    path = tmp_path / "reopen-selection.mc.json"

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
    return window, inside, crosses


@pytest.mark.parametrize(
    "mode", ["point", "window", "crossing", "window_clicks", "crossing_clicks"]
)
def test_saved_drawing_objects_can_be_selected_without_changing_history(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], mode: str
) -> None:
    window, inside, crosses = reopened_drawing
    draft = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert draft is not None and loaded is not None
    original_commands = loaded.document.commands
    draft.tool_buttons["选择元素"].click()
    canvas = draft.canvas
    unselected_image = canvas.grab().toImage()
    if mode == "point":
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    else:
        crossing = mode.startswith("crossing")
        first = (20.0, 15.0) if crossing else (-20.0, 15.0)
        second = (-20.0, -15.0) if crossing else (20.0, -15.0)
        start, end = canvas.local_to_screen(first), canvas.local_to_screen(second)
        if mode.endswith("clicks"):
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(canvas, end)
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=end)
        else:
            QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(canvas, end)
            QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    expected = (
        {inside.entity_id, crosses.entity_id} if mode.startswith("crossing") else {inside.entity_id}
    )
    assert canvas.selected_entity_ids == expected
    assert canvas.grab().toImage() != unselected_image
    assert loaded.document.commands == original_commands
    assert not loaded.document.is_dirty
    assert canvas.entities == []  # Selection never duplicates committed geometry into a new draft.


@pytest.mark.parametrize("pending_window", [False, True])
def test_selected_saved_objects_are_cleared_by_document_undo(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    pending_window: bool,
) -> None:
    window, inside, _crosses = reopened_drawing
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    canvas = draft.canvas
    draft.tool_buttons["选择元素"].click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    assert canvas.selected_entity_ids == {inside.entity_id}
    if pending_window:
        QTest.mouseClick(
            canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-20.0, 15.0))
        )
        QTest.mouseMove(canvas, canvas.local_to_screen((20.0, -15.0)))
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not canvas.background_entities, timeout=10000)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.selected_entity_ids
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(canvas.background_entities) == 2, timeout=10000
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    assert canvas.selected_entity_ids == {inside.entity_id}


def test_saved_and_new_objects_share_selection_without_partial_transform(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, inside, _crosses = reopened_drawing
    draft = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert draft is not None and loaded is not None
    canvas = draft.canvas
    draft.tool_buttons["选择元素"].click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    new_line = LineEntity(uuid4().hex, (10.0, -10.0), (20.0, -10.0))
    canvas.replace_draft_entities((new_line,))
    assert canvas.selected_entity_ids == {inside.entity_id}
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        canvas.local_to_screen((15.0, -10.0)),
    )
    assert canvas.selected_entity_ids == {inside.entity_id, new_line.entity_id}
    original_commands = loaded.document.commands
    for operation in ("move", "copy", "rotate"):
        draft.transform_buttons[operation].click()
        assert not canvas.has_active_edit_gesture
        assert tuple(canvas.entities) == (new_line,)
        assert loaded.document.commands == original_commands
        assert canvas.selected_entity_ids == {inside.entity_id, new_line.entity_id}
        assert "历史编辑" in draft.status_label.text()
    draft.cancel_button.click()


def test_drawing_selection_uses_projected_committed_layers(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.ui.sketch_editor import SketchEditorDialog

    draft = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(draft)
    draft.resize(1100, 800)
    draft.show()
    qtbot.waitExposed(draft)
    visible = LineEntity(uuid4().hex, (0.0, 0.0), (20.0, 0.0), layer_name="saved")
    hidden = LineEntity(uuid4().hex, (0.0, 5.0), (20.0, 5.0), layer_name="hidden")
    layers = SketchLayerTable().add(SketchLayer("saved")).add(SketchLayer("hidden", visible=False))
    draft.set_context_sketches(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (visible, hidden), layers=layers),)
    )
    draft.origin_fields["X"].setValue(10.0)
    draft.tool_buttons["选择元素"].click()
    canvas = draft.canvas
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((15.0, 10.0)))
    QTest.mouseMove(canvas, canvas.local_to_screen((-15.0, -10.0)))
    QTest.mouseRelease(
        canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((-15.0, -10.0))
    )
    assert canvas.selected_entity_ids == {visible.entity_id}
    assert canvas.entities == []
    draft.plane_combo.setCurrentText("YZ")
    assert canvas.background_entities == ()
    assert canvas.selected_entity_ids == set()


@pytest.mark.parametrize("operation", ["undo", "redo"])
def test_draft_history_does_not_restore_removed_committed_selection(
    qtbot: QtBot, operation: str
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(700, 500)
    canvas.show()
    canvas.set_tool("选择元素")
    saved = LineEntity(uuid4().hex, (-5.0, 0.0), (5.0, 0.0))
    frame = WorkPlaneFrame.xy()
    canvas.set_background_sketches((Sketch(uuid4().hex, frame, (saved,)),), frame)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    assert canvas.selected_entity_ids == {saved.entity_id}
    canvas.replace_draft_entities((LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0)),))
    if operation == "redo":
        assert canvas.undo_last_operation()
    canvas.set_background_sketches((), frame)
    if operation == "undo":
        assert canvas.undo_last_operation()
    else:
        assert canvas.redo_last_operation()
    assert canvas.selected_entity_ids == set()
