# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Saved drawing entities remain selectable after the real GUI save/open cycle."""

from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
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


def test_scale_saved_line_is_replayable_and_undoable(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {saved.entity_id}
    before = loaded.document.commands
    bar = editor.drawing_command_bar.input
    for value in ("SC", "0,0", "2"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    scaled = next(
        entity
        for entity, _layer in editor.canvas.background_entities
        if entity.entity_id == saved.entity_id
    )
    assert (
        isinstance(scaled, LineEntity) and scaled.start_mm == (-10, 0) and scaled.end_mm == (10, 0)
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before), timeout=10000
    )
    assert saved in {entity for entity, _layer in editor.canvas.background_entities}


def test_scale_saved_and_draft_together_stages_one_history_step(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    draft = LineEntity(uuid4().hex, (1, 10), (3, 10))
    assert editor.canvas.replace_draft_entities((draft,)) and editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    before = loaded.document.commands
    for value in ("SCALE", "0,0", "2"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: not unit.is_busy and editor.canvas.mixed_move is not None, timeout=10000
    )
    assert editor.canvas.entities == [LineEntity(draft.entity_id, (2, 20), (6, 20))]
    assert loaded.document.commands == before
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert len(loaded.document.commands) == len(before) + 2
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    assert saved in {item for item, _layer in current.canvas.background_entities}


def test_scale_copy_of_saved_entity_keeps_original(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None and editor.canvas.set_tool("选择元素")
    before = loaded.document.commands
    editor.canvas.selected_entity_ids = {saved.entity_id}
    for value in ("SCALE", "0,0", "COPY", "2"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert loaded.document.commands == before and len(editor.canvas.entities) == 1
    copy = editor.canvas.entities[0]
    assert isinstance(copy, LineEntity) and copy.entity_id != saved.entity_id
    assert copy.start_mm == (-10, 0) and copy.end_mm == (10, 0)


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


def test_saved_and_new_objects_share_selection_without_changing_history(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, inside, _crosses = reopened_drawing
    draft = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert draft is not None and loaded is not None
    canvas = draft.canvas
    original_commands = loaded.document.commands
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
    assert not canvas.has_active_edit_gesture
    assert tuple(canvas.entities) == (new_line,)
    assert loaded.document.commands == original_commands
    assert canvas.selected_entity_ids == {inside.entity_id, new_line.entity_id}
    draft.cancel_button.click()


def test_offset_saved_and_draft_creates_replayable_copies(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10.0, 4.0), (20.0, 4.0))
    canvas.replace_draft_entities((line,))
    editor.tool_buttons["选择元素"].click()
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    canvas.changed.emit()
    editor.offset_distance_field.setValue(3.0)
    before = loaded.document.commands
    editor.transform_buttons["offset"].click()
    assert loaded.document.commands == before
    assert tuple(e for e, _ in canvas.background_entities) == (saved, other)
    assert len(canvas.entities) == 3
    copies = [entity for entity in canvas.entities if entity.entity_id != line.entity_id]
    assert len({entity.entity_id for entity in copies}) == 2
    assert all(isinstance(entity, LineEntity) for entity in copies)
    assert {
        (entity.start_mm, entity.end_mm) for entity in copies if isinstance(entity, LineEntity)
    } == {((-5.0, 3.0), (5.0, 3.0)), ((10.0, 7.0), (20.0, 7.0))}
    window.request_undo()
    assert canvas.entities == [line]
    window.request_redo()
    assert len(canvas.entities) == 3
    expected = tuple(canvas.entities)
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not submitted and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    actual = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert all(actual[entity.entity_id] == entity for entity in expected)
    assert actual[saved.entity_id] == saved and actual[other.entity_id] == other


@pytest.mark.parametrize("failure", ["zero", "spline"])
def test_offset_saved_mixed_failure_preserves_selection_and_geometry(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], failure: str
) -> None:
    from mycad.core.sketch import SplineEntity

    window, saved, other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    draft = SplineEntity(uuid4().hex, ((10, 10), (12, 15), (16, 15), (20, 10)))
    canvas.replace_draft_entities((draft,))
    editor.tool_buttons["选择元素"].click()
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.changed.emit()
    editor.offset_distance_field.setValue(0.0 if failure == "zero" else 2.0)
    before = loaded.document.commands
    editor.transform_buttons["offset"].click()
    assert canvas.entities == [draft]
    assert tuple(e for e, _ in canvas.background_entities) == (saved, other)
    assert canvas.selected_entity_ids == {saved.entity_id, draft.entity_id}
    assert loaded.document.commands == before
    assert ("非零" if failure == "zero" else "样条") in editor.status_label.text()


def test_offset_saved_uses_current_workplane_coordinates(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.origin_fields["X"].setValue(10.0)
    editor.tool_buttons["选择元素"].click()
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.changed.emit()
    editor.offset_distance_field.setValue(3.0)
    editor.transform_buttons["offset"].click()
    assert len(canvas.entities) == 1
    offset = canvas.entities[0]
    assert isinstance(offset, LineEntity)
    assert offset.start_mm == pytest.approx((-15.0, 3.0))
    assert offset.end_mm == pytest.approx((-5.0, 3.0))


@pytest.mark.parametrize("tool", ["修剪", "延伸", "分割"])
def test_saved_geometry_is_read_only_boundary_for_draft_edit(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], tool: str
) -> None:
    window, first, boundary = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    end_y = 0.0 if tool == "延伸" else 10.0
    draft = LineEntity(uuid4().hex, (25.0, -10.0), (25.0, end_y))
    canvas.replace_draft_entities((draft,))
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool(tool)
    before = loaded.document.commands
    point = (25.0, 0.0) if tool != "修剪" else (25.0, 8.0)
    canvas.add_coordinate_point(point, exact_point=True)
    assert loaded.document.commands == before
    assert tuple(entity for entity, _layer in canvas.background_entities) == (first, boundary)
    if tool == "分割":
        assert len(canvas.entities) == 2
        assert canvas.entities[0].entity_id == draft.entity_id
    else:
        assert len(canvas.entities) == 1
        result = canvas.entities[0]
        assert isinstance(result, LineEntity)
        assert result.entity_id == draft.entity_id
        assert result.end_mm == pytest.approx((25.0, 5.0))
    window.request_undo()
    assert canvas.entities == [draft]


@pytest.mark.parametrize("tool", ["修剪", "延伸"])
def test_saved_boundary_preview_matches_mouse_commit(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], tool: str
) -> None:
    window, _first, _boundary = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    end_y = 0.0 if tool == "延伸" else 10.0
    draft = LineEntity(uuid4().hex, (25.0, -10.0), (25.0, end_y))
    canvas.replace_draft_entities((draft,))
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool(tool)
    point = (25.0, 0.0) if tool == "延伸" else (25.0, 8.0)
    pixel = canvas.local_to_screen(point)
    QTest.mouseMove(canvas, pixel)
    qtbot.waitUntil(lambda: bool(canvas.previewed_line_edit_entities), timeout=5000)
    preview = canvas.previewed_line_edit_entities
    assert canvas.entities == [draft]
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=pixel)
    assert tuple(canvas.entities) == preview


def test_line_edit_preview_clears_when_document_revision_changes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, _boundary = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (25.0, -10.0), (25.0, 10.0))
    canvas.replace_draft_entities((draft,))
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool("修剪")
    QTest.mouseMove(canvas, canvas.local_to_screen((25.0, 8.0)))
    qtbot.waitUntil(lambda: bool(canvas.previewed_line_edit_entities), timeout=5000)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    editor.set_context_sketches(editor.dimension_sources()[1:])
    assert canvas.previewed_line_edit_original is None
    assert not canvas.previewed_line_edit_entities
    assert canvas.entities == [draft]


def test_line_edit_hover_does_not_preview_stale_boundaries(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, _boundary = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (25.0, -10.0), (25.0, 10.0))
    canvas.replace_draft_entities((draft,))
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool("修剪")
    QTest.mouseMove(canvas, canvas.local_to_screen((25.0, 8.0)))
    qtbot.waitUntil(lambda: bool(canvas.previewed_line_edit_entities), timeout=5000)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    QTest.mouseMove(canvas, canvas.local_to_screen((25.0, 9.0)))
    assert canvas.previewed_line_edit_original is None
    assert not canvas.previewed_line_edit_entities


@pytest.mark.parametrize("drag", [False, True])
@pytest.mark.parametrize("refresh", [False, True])
def test_draft_trim_rejects_stale_saved_boundaries(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], drag: bool, refresh: bool
) -> None:
    window, _first, _boundary = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (25.0, -10.0), (25.0, 10.0))
    canvas.replace_draft_entities((draft,))
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool("修剪")
    end = canvas.local_to_screen((26.0, 8.0))
    if drag:
        start = canvas.local_to_screen((24.0, 8.0))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        assert canvas.entities != [draft]
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    after_external = loaded.document.commands
    if refresh:
        editor.set_context_sketches(editor.dimension_sources()[1:])
    if drag:
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    else:
        canvas.add_coordinate_point((25.0, 8.0), exact_point=True)
    if refresh and not drag:
        # A fresh click after a context refresh uses the refreshed boundaries.
        assert canvas.entities != [draft]
        assert loaded.document.commands == after_external
        return
    assert canvas.entities == [draft]
    assert loaded.document.commands == after_external
    assert "变化" in editor.status_label.text()


@pytest.mark.parametrize("tool", ["延伸", "分割"])
def test_draft_line_edit_rejects_stale_saved_boundaries(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], tool: str
) -> None:
    window, _first, _boundary = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    end_y = 0.0 if tool == "延伸" else 10.0
    draft = LineEntity(uuid4().hex, (25.0, -10.0), (25.0, end_y))
    canvas.replace_draft_entities((draft,))
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool(tool)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    after_external = loaded.document.commands
    canvas.add_coordinate_point((25.0, 0.0), exact_point=True)
    assert canvas.entities == [draft]
    assert loaded.document.commands == after_external
    assert "变化" in editor.status_label.text()


def test_drag_started_on_stale_context_is_not_revived_by_refresh(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, _first, _boundary = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (25.0, -10.0), (25.0, 10.0))
    canvas.replace_draft_entities((draft,))
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool("修剪")
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    after_external = loaded.document.commands
    start = canvas.local_to_screen((24.0, 8.0))
    end = canvas.local_to_screen((26.0, 8.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    assert canvas.entities != [draft]
    editor.set_context_sketches(editor.dimension_sources()[1:])
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.entities == [draft]
    assert loaded.document.commands == after_external
    assert "变化" in editor.status_label.text()


@pytest.mark.parametrize("locked", [False, True])
def test_saved_boundary_visibility_and_lock_state(qtbot: QtBot, locked: bool) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    boundary = LineEntity(uuid4().hex, (-10.0, 0.0), (10.0, 0.0), layer_name="boundary")
    layers = SketchLayerTable().add(SketchLayer("boundary", locked=locked, visible=locked))
    frame = WorkPlaneFrame.xy()
    canvas.set_background_sketches((Sketch(uuid4().hex, frame, (boundary,), layers=layers),), frame)
    target = LineEntity(uuid4().hex, (0.0, -10.0), (0.0, 10.0))
    canvas.replace_draft_entities((target,))
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((0.0, 8.0), exact_point=True)
    if locked:
        assert canvas.entities == [LineEntity(target.entity_id, (0.0, -10.0), (0.0, 0.0))]
    else:
        # Quick trim erases an unbounded target when the only boundary is hidden.
        assert canvas.entities == []
    assert canvas.background_entities[0][0] == boundary


@pytest.mark.parametrize("select_saved", [False, True])
def test_hidden_saved_identity_collision_cannot_remove_draft_on_trim(
    qtbot: QtBot, select_saved: bool
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=select_saved)
    qtbot.addWidget(canvas)
    identity = uuid4().hex
    hidden = LineEntity(identity, (-30.0, -20.0), (30.0, -20.0), layer_name="hidden")
    layers = SketchLayerTable().add(SketchLayer("hidden", visible=False))
    frame = WorkPlaneFrame.xy()
    canvas.set_background_sketches((Sketch(uuid4().hex, frame, (hidden,), layers=layers),), frame)
    target = LineEntity(identity, (0.0, -10.0), (0.0, 10.0))
    boundary = LineEntity(uuid4().hex, (-10.0, 0.0), (10.0, 0.0))
    canvas.replace_draft_entities((target, boundary))
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((0.0, 8.0), exact_point=True)
    if select_saved:
        assert canvas.entities == [target, boundary]
        assert "身份" in canvas.message
    else:
        assert canvas.entities == [
            LineEntity(identity, (0.0, -10.0), (0.0, 0.0)),
            boundary,
        ]


def test_saved_boundary_drag_trim_is_one_draft_undo(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, first, boundary = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (25.0, -10.0), (25.0, 10.0))
    canvas.replace_draft_entities((target,))
    canvas.set_snapping_enabled(False)
    canvas.set_tool("修剪")
    start, end = canvas.local_to_screen((25.0, 8.0)), canvas.local_to_screen((25.0, 9.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.entities == [LineEntity(target.entity_id, (25.0, -10.0), (25.0, 5.0))]
    assert tuple(entity for entity, _layer in canvas.background_entities) == (first, boundary)
    window.request_undo()
    assert canvas.entities == [target]


def test_saved_boundary_duplicate_identity_is_rejected(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    identity = uuid4().hex
    boundary = LineEntity(identity, (-10.0, 0.0), (10.0, 0.0))
    frame = WorkPlaneFrame.xy()
    canvas.set_background_sketches((Sketch(uuid4().hex, frame, (boundary,)),), frame)
    draft = LineEntity(identity, (0.0, -10.0), (0.0, 10.0))
    canvas.replace_draft_entities((draft,))
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((0.0, 8.0), exact_point=True)
    assert canvas.entities == [draft]
    assert canvas.background_entities[0][0] == boundary
    assert "身份不唯一" in canvas.message


def test_part_reference_is_not_used_as_drawing_boundary(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=False)
    qtbot.addWidget(canvas)
    boundary = LineEntity(uuid4().hex, (-10.0, 0.0), (10.0, 0.0))
    frame = WorkPlaneFrame.xy()
    canvas.set_background_sketches((Sketch(uuid4().hex, frame, (boundary,)),), frame)
    target = LineEntity(uuid4().hex, (0.0, -10.0), (0.0, 10.0))
    canvas.replace_draft_entities((target,))
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((0.0, 8.0), exact_point=True)
    assert canvas.entities == [target]


def test_boundary_preview_does_not_include_hidden_draft_geometry(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.show()
    qtbot.waitExposed(canvas)
    layers = SketchLayerTable().add(SketchLayer("hidden", visible=False))
    canvas.set_layer_table(layers, "0")
    boundary = LineEntity(uuid4().hex, (-10.0, 0.0), (10.0, 0.0))
    frame = WorkPlaneFrame.xy()
    canvas.set_background_sketches((Sketch(uuid4().hex, frame, (boundary,)),), frame)
    target = LineEntity(uuid4().hex, (0.0, -10.0), (0.0, 10.0))
    hidden = LineEntity(uuid4().hex, (20.0, 0.0), (30.0, 0.0), layer_name="hidden")
    canvas.replace_draft_entities((target, hidden))
    canvas.set_tool("修剪")
    QTest.mouseMove(canvas, canvas.local_to_screen((0.0, 8.0)))
    qtbot.waitUntil(lambda: bool(canvas.previewed_line_edit_entities), timeout=5000)
    assert {e.entity_id for e in canvas.previewed_line_edit_entities} == {target.entity_id}
    assert canvas.entities == [target, hidden]


def test_trim_against_saved_boundary_survives_save_and_reopen(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, first, boundary = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (25.0, -10.0), (25.0, 10.0))
    canvas.replace_draft_entities((target,))
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((25.0, 8.0), exact_point=True)
    expected = LineEntity(target.entity_id, (25.0, -10.0), (25.0, 5.0))
    assert canvas.entities == [expected]
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not previous and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    actual = {entity.entity_id: entity for entity, _layer in reopened.canvas.background_entities}
    assert actual[first.entity_id] == first and actual[boundary.entity_id] == boundary
    assert actual[target.entity_id] == expected


@pytest.mark.parametrize("tool", ["修剪", "延伸", "分割"])
def test_saved_target_edits_are_replayable_and_undoable(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], tool: str
) -> None:
    window, _first, target = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    boundary_x = 40.0 if tool == "延伸" else 20.0
    boundary = LineEntity(uuid4().hex, (boundary_x, -5.0), (boundary_x, 10.0))
    editor.canvas.replace_draft_entities((boundary,))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool(tool)
    before = loaded.document.commands
    point = (30.0, 5.0) if tool == "延伸" else (25.0, 5.0)
    pixel = canvas.local_to_screen(point)
    if tool != "分割":
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
        qtbot.waitUntil(lambda: bool(canvas.previewed_line_edit_entities), timeout=5000)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=pixel)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) > len(before) and not unit.is_busy, timeout=10000
    )
    result = {entity.entity_id: entity for entity, _layer in canvas.background_entities}
    assert result[boundary.entity_id] == boundary
    assert isinstance(result[target.entity_id], LineEntity)
    if tool == "分割":
        assert len(result) == 4
    else:
        edited = result[target.entity_id]
        assert isinstance(edited, LineEntity)
        assert edited.end_mm == pytest.approx((boundary_x, 5.0))
    window.act_save.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not previous and not unit.is_busy,
        timeout=10000,
    )
    editor = window.active_sketch_dialog()
    reopened_loaded = window.loaded_document()
    assert editor is not None and reopened_loaded is not None
    canvas = editor.canvas
    assert {entity.entity_id: entity for entity, _layer in canvas.background_entities} == result
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(reopened_loaded.document.commands) == len(before),
        timeout=10000,
    )
    restored = {entity.entity_id: entity for entity, _layer in canvas.background_entities}
    assert restored[target.entity_id] == target and restored[boundary.entity_id] == boundary


def test_saved_trim_command_undo_only_undoes_its_revision(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, target = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    boundary = LineEntity(uuid4().hex, (20, -5), (20, 10))
    editor.canvas.replace_draft_entities((boundary,))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas, command = editor.canvas, editor.drawing_command_bar.input
    command.setText("TRIM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    before = len(loaded.document.commands)
    canvas.add_coordinate_point((25, 5), exact_point=True)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before + 1 and not unit.is_busy, timeout=10000
    )
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before and not unit.is_busy, timeout=10000
    )
    assert target in tuple(entity for entity, _ in canvas.background_entities)
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(loaded.document.commands) == before


def test_saved_trim_command_undo_rejects_external_revision(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, target = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    boundary = LineEntity(uuid4().hex, (20, -5), (20, 10))
    editor.canvas.replace_draft_entities((boundary,))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas, command = editor.canvas, editor.drawing_command_bar.input
    command.setText("TRIM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    before = len(loaded.document.commands)
    canvas.add_coordinate_point((25, 5), exact_point=True)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before + 1 and not unit.is_busy, timeout=10000
    )
    edited = tuple(entity for entity, _ in canvas.background_entities)
    assert target not in edited
    loaded.document.set_metadata("notes", "changed after trim")
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(loaded.document.commands) == before + 1
    assert tuple(entity for entity, _ in canvas.background_entities) == edited
    assert "变化" in editor.status_label.text()


def test_saved_trim_command_undo_handles_two_consecutive_edits(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, target = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    second = LineEntity(uuid4().hex, (-30, 10), (30, 10))
    boundary = LineEntity(uuid4().hex, (20, -5), (20, 15))
    editor.canvas.replace_draft_entities((second, boundary))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas, command = editor.canvas, editor.drawing_command_bar.input
    command.setText("TRIM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    before = len(loaded.document.commands)
    for index, point in enumerate(((25, 5), (25, 10)), start=1):
        canvas.add_coordinate_point(point, exact_point=True)
        qtbot.waitUntil(
            lambda index=index: (
                len(loaded.document.commands) == before + index and not unit.is_busy
            ),
            timeout=10000,
        )
    for remaining in (before + 1, before):
        command.setText("U")
        QTest.keyClick(command, Qt.Key.Key_Return)
        qtbot.waitUntil(
            lambda remaining=remaining: (
                len(loaded.document.commands) == remaining and not unit.is_busy
            ),
            timeout=10000,
        )
    restored = tuple(entity for entity, _ in canvas.background_entities)
    assert target in restored and second in restored


def test_saved_fence_command_undoes_one_atomic_revision(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, target = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    boundary = LineEntity(uuid4().hex, (20, -5), (20, 10))
    editor.canvas.replace_draft_entities((boundary,))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas, command = editor.canvas, editor.drawing_command_bar.input
    before = len(loaded.document.commands)
    for value in ("TRIM", "F", "25,3", "@0,4", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before + 1 and not unit.is_busy, timeout=15000
    )
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before and not unit.is_busy, timeout=15000
    )
    assert target in tuple(entity for entity, _ in canvas.background_entities)


def test_quick_trim_deletes_unintersected_saved_target_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, target, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas, command = editor.canvas, editor.drawing_command_bar.input
    command.setText("TRIM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    before = len(loaded.document.commands)
    canvas.add_coordinate_point((0, 0), exact_point=True)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before + 1 and not unit.is_busy, timeout=15000
    )
    assert target not in tuple(entity for entity, _ in canvas.background_entities)
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before and not unit.is_busy, timeout=15000
    )
    assert target in tuple(entity for entity, _ in canvas.background_entities)


def test_trim_erase_option_deletes_saved_target_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, target, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas, command = editor.canvas, editor.drawing_command_bar.input
    before = len(loaded.document.commands)
    for value in ("TRIM", "ERASE"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 0)))
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before + 1 and not unit.is_busy, timeout=15000
    )
    assert target not in tuple(entity for entity, _ in canvas.background_entities)
    assert canvas.tool == "修剪"
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before and not unit.is_busy, timeout=15000
    )
    assert target in tuple(entity for entity, _ in canvas.background_entities)


def test_trim_erase_option_stages_mixed_targets_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas, command = editor.canvas, editor.drawing_command_bar.input
    draft = LineEntity(uuid4().hex, (-5, 10), (5, 10))
    assert canvas.replace_draft_entities((draft,))
    before = loaded.document.commands
    for value in ("TRIM", "ERASE"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((0, 0), (0, 10)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=15000)
    assert canvas.entities == [] and loaded.document.commands == before
    assert saved not in tuple(entity for entity, _ in canvas.background_entities)
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [draft]
    assert saved in tuple(entity for entity, _ in canvas.background_entities)


def test_extend_saved_target_with_virtual_draft_boundary_replays(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, target = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    boundary = LineEntity(uuid4().hex, (40, 8), (40, 12))
    assert canvas.replace_draft_entities((boundary,))
    command = editor.drawing_command_bar.input
    for value in ("EXTEND", "E", "E"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    canvas.add_coordinate_point((30, 5), exact_point=True)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=15000)
    changed = {entity.entity_id: entity for entity, _ in canvas.background_entities}
    extended = changed[target.entity_id]
    assert isinstance(extended, LineEntity) and extended.end_mm == pytest.approx((40, 5))
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert target in tuple(entity for entity, _ in canvas.background_entities)
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    restored = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    result = restored[target.entity_id]
    assert isinstance(result, LineEntity) and result.end_mm == pytest.approx((40, 5))
    assert restored[boundary.entity_id] == boundary


def test_edge_mode_persists_after_reopening_drawing(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "E", "E"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.line_edit_extend_boundaries
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None and reopened.canvas.line_edit_extend_boundaries


def test_trimextendmode_persists_after_reopening_drawing(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    command = editor.drawing_command_bar.input
    for value in ("TRIMEXTENDMODE", "0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.line_edit_standard_mode
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None and reopened.canvas.line_edit_standard_mode
    command = reopened.drawing_command_bar.input
    command.setText("EXTEND")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert reopened.canvas.selecting_line_edit_boundaries


def test_projmode_persists_after_reopening_drawing(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    command = editor.drawing_command_bar.input
    for value in ("PROJMODE", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.line_edit_projection_mode == 2
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None and reopened.canvas.line_edit_projection_mode == 2


@pytest.mark.parametrize("tool", ["修剪", "延伸", "分割"])
def test_saved_edit_with_draft_boundary_is_staged_and_undoable(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], tool: str
) -> None:
    window, _first, target = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    boundary_x = 40.0 if tool == "延伸" else 20.0
    boundary = LineEntity(uuid4().hex, (boundary_x, -5.0), (boundary_x, 10.0))
    canvas.replace_draft_entities((boundary,))
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool(tool)
    before = loaded.document.commands
    point = (30.0, 5.0) if tool == "延伸" else (25.0, 5.0)
    pixel = canvas.local_to_screen(point)
    if tool != "分割":
        QTest.mouseMove(canvas, pixel + QPoint(4, 4))
        QTest.mouseMove(canvas, pixel)
        qtbot.waitUntil(lambda: bool(canvas.previewed_line_edit_entities), timeout=5000)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=pixel)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert loaded.document.commands == before and canvas.entities == [boundary]
    edited = {entity.entity_id: entity for entity, _layer in canvas.background_entities}[
        target.entity_id
    ]
    assert isinstance(edited, LineEntity) and edited.end_mm == pytest.approx((boundary_x, 5.0))
    window.request_undo()
    assert {entity.entity_id: entity for entity, _layer in canvas.background_entities}[
        target.entity_id
    ] == target
    assert canvas.entities == [boundary]
    window.request_redo()
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not previous and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    restored = {entity.entity_id: entity for entity, _layer in reopened.canvas.background_entities}
    assert restored[target.entity_id] == target and restored[boundary.entity_id] == boundary


@pytest.mark.parametrize("mixed", [False, True])
def test_saved_trim_rejects_violating_driving_dimension(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], mixed: bool
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window, _first, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    target = LineEntity(uuid4().hex, (-30.0, 30.0), (30.0, 30.0))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(target.entity_id, "geometry"),), 60.0, "mm"
    )
    editor.canvas.replace_draft_entities((target,))
    editor.canvas.constraints = [dimension]
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    boundary = LineEntity(uuid4().hex, (20.0, 20.0), (20.0, 40.0))
    editor.canvas.replace_draft_entities((boundary,))
    if not mixed:
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
        editor = window.active_sketch_dialog()
        assert editor is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool("修剪")
    before = loaded.document.commands
    canvas.add_coordinate_point((25.0, 30.0), exact_point=True)
    qtbot.waitUntil(
        lambda: "失败" in editor.status_label.text() and not unit.is_busy, timeout=10000
    )
    assert loaded.document.commands == before
    assert canvas.entities == ([boundary] if mixed else [])
    assert {e.entity_id: e for e, _layer in canvas.background_entities}[target.entity_id] == target
    assert dimension.constraint_id in {c.constraint_id for c in canvas.visible_dimensions()}


def test_saved_trim_converts_from_current_workplane_to_source_frame(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, target = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    boundary = LineEntity(uuid4().hex, (20.0, -5.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((boundary,))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.origin_fields["X"].setValue(10.0)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((15.0, 5.0), exact_point=True)
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and any(
                e.entity_id == target.entity_id
                and isinstance(e, LineEntity)
                and e.end_mm[0] == pytest.approx(10.0)
                for e, _layer in canvas.background_entities
            )
        ),
        timeout=10000,
    )
    editor.origin_fields["X"].setValue(0.0)
    actual = {entity.entity_id: entity for entity, _layer in canvas.background_entities}
    edited = actual[target.entity_id]
    assert isinstance(edited, LineEntity) and edited.end_mm == pytest.approx((20.0, 5.0))
    assert actual[boundary.entity_id] == boundary


@pytest.mark.parametrize("locked", [False, True])
def test_saved_line_edit_rejects_hidden_or_locked_target(qtbot: QtBot, locked: bool) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    layer = SketchLayer("restricted", locked=locked, visible=locked)
    layers = SketchLayerTable().add(layer)
    target = LineEntity(uuid4().hex, (-30.0, 5.0), (30.0, 5.0), layer_name="restricted")
    boundary = LineEntity(uuid4().hex, (20.0, 0.0), (20.0, 10.0))
    frame = WorkPlaneFrame.xy()
    canvas.set_background_sketches(
        (Sketch(uuid4().hex, frame, (target, boundary), layers=layers),), frame
    )
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((25.0, 5.0), exact_point=True)
    assert tuple(entity for entity, _layer in canvas.background_entities) == (target, boundary)
    assert ("锁定" if locked else "点选") in canvas.message


def test_trim_saved_circle_creates_new_arc_identity_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch import ArcEntity, CircleEntity

    window, _first, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    circle = CircleEntity(uuid4().hex, (0.0, 30.0), 10.0)
    cutters = tuple(LineEntity(uuid4().hex, (x, 20.0), (x, 40.0)) for x in (-5.0, 5.0))
    editor.canvas.replace_draft_entities((circle, *cutters))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("修剪")
    before = loaded.document.commands
    canvas.add_coordinate_point((0.0, 40.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == len(before) + 1, editor.status_label.text()
    objects = tuple(e for e, _layer in canvas.background_entities)
    assert circle.entity_id not in {e.entity_id for e in objects}
    arcs = [e for e in objects if isinstance(e, ArcEntity) and e.center_mm == circle.center_mm]
    assert len(arcs) == 1 and arcs[0].entity_id != circle.entity_id
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before), timeout=10000
    )
    assert circle in tuple(e for e, _layer in canvas.background_entities)


@pytest.mark.parametrize("tool", ("修剪", "分割"))
def test_edit_saved_curved_polyline_replays_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], tool: str
) -> None:
    from mycad.core.sketch import PolylineEntity

    window, _first, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    path = PolylineEntity(uuid4().hex, ((-5, 30), (5, 30), (10, 30)), bulges=(-1, 0))
    cutters = tuple(LineEntity(uuid4().hex, (x, 32), (x, 36)) for x in (-3, 3))
    editor.canvas.replace_draft_entities((path, *cutters))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool(tool)
    before = loaded.document.commands
    point = (0, 35) if tool == "修剪" else (-2, 30 + 21**0.5)
    canvas.add_coordinate_point(point, exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == len(before) + 1, editor.status_label.text()
    fragments = [
        entity
        for entity, _ in canvas.background_entities
        if isinstance(entity, PolylineEntity) and entity.points_mm[0][1] >= 30
    ]
    assert len(fragments) == 2 and all(fragment.bulges for fragment in fragments)
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    reopened_fragments = [
        entity
        for entity, _ in canvas.background_entities
        if isinstance(entity, PolylineEntity) and entity.points_mm[0][1] >= 30
    ]
    assert reopened_fragments == fragments
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before), timeout=10000
    )
    assert path in tuple(entity for entity, _ in canvas.background_entities)


def test_drag_trim_saved_circle_creates_new_arc_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch import ArcEntity, CircleEntity

    window, _first, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    circle = CircleEntity(uuid4().hex, (0.0, 30.0), 10.0)
    cutters = tuple(LineEntity(uuid4().hex, (x, 20.0), (x, 40.0)) for x in (-5.0, 5.0))
    editor.canvas.replace_draft_entities((circle, *cutters))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    qtbot.waitUntil(lambda: not unit.is_delivering_result, timeout=10000)
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("修剪")
    before = loaded.document.commands
    start, end = canvas.local_to_screen((-1.0, 40.0)), canvas.local_to_screen((1.0, 40.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) > len(before) and not unit.is_busy, timeout=10000
    )
    objects = tuple(e for e, _layer in canvas.background_entities)
    assert circle.entity_id not in {e.entity_id for e in objects}
    arcs = [e for e in objects if isinstance(e, ArcEntity) and e.center_mm == circle.center_mm]
    assert len(arcs) == 1 and arcs[0].entity_id != circle.entity_id
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before), timeout=10000
    )
    assert circle in tuple(e for e, _layer in canvas.background_entities)


@pytest.mark.parametrize("drag", [False, True])
def test_trim_saved_circle_with_dimension_rejects_identity_change(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], drag: bool
) -> None:
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window, _first, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    circle = CircleEntity(uuid4().hex, (0.0, 30.0), 10.0)
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 10.0, "mm"
    )
    cutters = tuple(LineEntity(uuid4().hex, (x, 20.0), (x, 40.0)) for x in (-5.0, 5.0))
    editor.canvas.replace_draft_entities((circle, *cutters))
    editor.canvas.constraints = [dimension]
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("修剪")
    before = loaded.document.commands
    if drag:
        start = canvas.local_to_screen((-1.0, 40.0))
        end = canvas.local_to_screen((1.0, 40.0))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    else:
        canvas.add_coordinate_point((0.0, 40.0), exact_point=True)
    qtbot.waitUntil(
        lambda: "失败" in editor.status_label.text() and not unit.is_busy, timeout=10000
    )
    assert loaded.document.commands == before
    assert circle in tuple(e for e, _layer in canvas.background_entities)
    assert dimension.constraint_id in {c.constraint_id for c in canvas.visible_dimensions()}


@pytest.mark.parametrize("drag", [False, True])
def test_trim_saved_circle_with_draft_boundaries_preserves_history(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], drag: bool
) -> None:
    from mycad.core.sketch import ArcEntity, CircleEntity

    window, _first, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    circle = CircleEntity(uuid4().hex, (0.0, 30.0), 10.0)
    editor.canvas.replace_draft_entities((circle,))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    cutters = tuple(LineEntity(uuid4().hex, (x, 20.0), (x, 40.0)) for x in (-5.0, 5.0))
    canvas.replace_draft_entities(cutters)
    canvas.set_snapping_enabled(False)
    canvas.set_tool("修剪")
    before = loaded.document.commands
    if drag:
        start = canvas.local_to_screen((-1.0, 40.0))
        end = canvas.local_to_screen((1.0, 40.0))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    else:
        canvas.add_coordinate_point((0.0, 40.0), exact_point=True)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert loaded.document.commands == before
    arcs = [
        e
        for e, _layer in canvas.background_entities
        if isinstance(e, ArcEntity) and e.center_mm == circle.center_mm
    ]
    assert len(arcs) == 1 and arcs[0].entity_id != circle.entity_id
    window.request_undo()
    assert circle in tuple(e for e, _layer in canvas.background_entities)
    assert tuple(canvas.entities) == cutters
    window.request_redo()
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not previous and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    objects = tuple(e for e, _layer in reopened.canvas.background_entities)
    assert circle in objects and all(cutter in objects for cutter in cutters)


@pytest.mark.parametrize("drag", [False, True])
def test_saved_trim_with_later_draft_edit_keeps_history_order(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], drag: bool
) -> None:
    window, _first, target = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    first_boundary = LineEntity(uuid4().hex, (20.0, -5.0), (20.0, 10.0))
    second_boundary = LineEntity(uuid4().hex, (0.0, -5.0), (0.0, 10.0))
    canvas.replace_draft_entities((first_boundary,))
    canvas.set_tool("修剪")
    canvas.add_coordinate_point((25.0, 5.0), exact_point=True)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    canvas.replace_draft_entities((*canvas.entities, second_boundary))
    if drag:
        start, end = canvas.local_to_screen((15.0, 5.0)), canvas.local_to_screen((18.0, 5.0))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    else:
        canvas.add_coordinate_point((15.0, 5.0), exact_point=True)
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and any(
                e.entity_id == target.entity_id
                and isinstance(e, LineEntity)
                and e.end_mm == pytest.approx((0.0, 5.0))
                for e, _layer in canvas.background_entities
            )
        ),
        timeout=10000,
    )
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not submitted and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    first = {e.entity_id: e for e, _layer in reopened.canvas.background_entities}
    first_target = first[target.entity_id]
    assert isinstance(first_target, LineEntity)
    assert first_target.end_mm == pytest.approx((20.0, 5.0))
    assert second_boundary.entity_id in first
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    second = {e.entity_id: e for e, _layer in reopened.canvas.background_entities}
    assert second_boundary.entity_id not in second
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    third = {e.entity_id: e for e, _layer in reopened.canvas.background_entities}
    assert third[target.entity_id] == target and third[first_boundary.entity_id] == first_boundary


def test_drag_trim_mixed_targets_is_one_staged_operation(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (-30.0, 0.0), (30.0, 0.0))
    boundary = LineEntity(uuid4().hex, (20.0, -10.0), (20.0, 10.0))
    canvas.replace_draft_entities((draft, boundary))
    canvas.set_snapping_enabled(False)
    canvas.set_tool("修剪")
    commands = loaded.document.commands
    start, end = canvas.local_to_screen((25.0, 0.0)), canvas.local_to_screen((25.0, 8.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert canvas.entities == [LineEntity(draft.entity_id, (-30.0, 0.0), (20.0, 0.0)), boundary]
    result = {e.entity_id: e for e, _layer in canvas.background_entities}
    assert result[first.entity_id] == first
    assert result[saved.entity_id] == LineEntity(saved.entity_id, (-30.0, 5.0), (20.0, 5.0))
    assert loaded.document.commands == commands
    window.request_undo()
    assert canvas.entities == [draft, boundary]
    assert tuple(entity for entity, _layer in canvas.background_entities) == (first, saved)
    window.request_redo()
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not previous and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    restored = {entity.entity_id: entity for entity, _layer in reopened.canvas.background_entities}
    assert restored[saved.entity_id] == saved
    assert restored[draft.entity_id] == draft and restored[boundary.entity_id] == boundary


@pytest.mark.parametrize("tool", ("TRIM", "EXTEND"))
@pytest.mark.parametrize("selection", ("F", "CR"))
def test_fence_mixed_targets_is_atomic_and_undoable(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    tool: str,
    selection: str,
) -> None:
    window, _first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    loaded = window.loaded_document()
    assert editor is not None and unit is not None and loaded is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (-30, 0), (30, 0))
    boundary_x = 20 if tool == "TRIM" else 40
    boundary = LineEntity(uuid4().hex, (boundary_x, -10), (boundary_x, 10))
    canvas.replace_draft_entities((draft, boundary))
    commands = loaded.document.commands
    command = editor.drawing_command_bar.input
    for value in (tool, selection):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((24, -2), (26, 8)) if selection == "CR" else ((25, -2), (25, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if selection == "F":
        QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=15000)
    assert loaded.document.commands == commands
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((boundary_x, 0))
    changed = {entity.entity_id: entity for entity, _ in canvas.background_entities}
    changed_saved = changed[saved.entity_id]
    assert isinstance(changed_saved, LineEntity)
    assert changed_saved.end_mm == pytest.approx((boundary_x, 5))
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [draft, boundary]
    assert saved in tuple(entity for entity, _ in canvas.background_entities)
    assert canvas.redo_last_operation()
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    reopened_entities = {
        entity.entity_id: entity for entity, _ in reopened.canvas.background_entities
    }
    reopened_draft = reopened_entities[draft.entity_id]
    reopened_saved = reopened_entities[saved.entity_id]
    assert isinstance(reopened_draft, LineEntity) and isinstance(reopened_saved, LineEntity)
    assert reopened_draft.end_mm == pytest.approx((boundary_x, 0))
    assert reopened_saved.end_mm == pytest.approx((boundary_x, 5))
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    restored = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert restored[draft.entity_id] == draft and restored[saved.entity_id] == saved


@pytest.mark.parametrize("selection", ("F", "CR"))
def test_trim_fence_rejects_changed_document_before_commit(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], selection: str
) -> None:
    window, first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (-30, 0), (30, 0))
    boundary = LineEntity(uuid4().hex, (20, -10), (20, 10))
    canvas.replace_draft_entities((draft, boundary))
    command = editor.drawing_command_bar.input
    for value in ("TRIM", selection):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    points = ((24, -2), (26, 8)) if selection == "CR" else ((25, -2), (25, 8))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(points[0]))
    if selection == "CR":
        loaded.document.set_metadata("notes", "crossing source changed")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(points[1]))
    if selection == "F":
        loaded.document.set_metadata("notes", "fence source changed")
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.mixed_move is None
    assert canvas.entities == [draft, boundary]
    assert tuple(entity for entity, _ in canvas.background_entities) == (first, saved)
    assert "变化" in canvas.message


def test_drag_trim_mixed_targets_preserves_satisfied_inferred_relation(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window, _first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (-30.0, 0.0), (30.0, 0.0))
    boundary = LineEntity(uuid4().hex, (20.0, -10.0), (20.0, 10.0))
    relation = SketchConstraint(
        uuid4().hex,
        "horizontal",
        (SketchGeometryReference(draft.entity_id, "geometry"),),
        source="inferred",
    )
    canvas.replace_draft_entities((draft, boundary))
    canvas.constraints = [relation]
    canvas.set_tool("修剪")
    start, end = canvas.local_to_screen((25.0, 0.0)), canvas.local_to_screen((25.0, 8.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert canvas.constraints == [relation]
    window.request_undo()
    assert canvas.entities == [draft, boundary] and canvas.constraints == [relation]
    assert {e.entity_id: e for e, _layer in canvas.background_entities}[saved.entity_id] == saved


@pytest.mark.parametrize("draft_boundary", [False, True])
def test_drag_trim_single_saved_target_uses_one_replayable_revision(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], draft_boundary: bool
) -> None:
    window, _first, target = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    boundary = LineEntity(uuid4().hex, (20.0, -5.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((boundary,))
    if not draft_boundary:
        editor.finish_button.click()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
        editor = window.active_sketch_dialog()
        assert editor is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("修剪")
    before = loaded.document.commands
    start, end = canvas.local_to_screen((25.0, 5.0)), canvas.local_to_screen((27.0, 5.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    if draft_boundary:
        qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
        assert loaded.document.commands == before and canvas.entities == [boundary]
    else:
        qtbot.waitUntil(
            lambda: len(loaded.document.commands) == len(before) + 1 and not unit.is_busy,
            timeout=10000,
        )
    result = {e.entity_id: e for e, _layer in canvas.background_entities}
    edited = result[target.entity_id]
    assert isinstance(edited, LineEntity) and edited.end_mm == pytest.approx((20.0, 5.0))
    if not draft_boundary:
        assert result[boundary.entity_id] == boundary
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before), timeout=10000
    )
    assert {e.entity_id: e for e, _layer in canvas.background_entities}[target.entity_id] == target


def test_drag_trim_across_two_saved_segments_is_one_atomic_undo(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, target = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    cutters = tuple(LineEntity(uuid4().hex, (x, -5.0), (x, 10.0)) for x in (10.0, 20.0))
    editor.canvas.replace_draft_entities(cutters)
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("修剪")
    before = loaded.document.commands
    start, end = canvas.local_to_screen((15.0, 5.0)), canvas.local_to_screen((25.0, 5.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == len(before) + 1, editor.status_label.text()
    result = {e.entity_id: e for e, _layer in canvas.background_entities}
    edited = result[target.entity_id]
    assert isinstance(edited, LineEntity) and edited.end_mm == pytest.approx((10.0, 5.0))
    window.request_undo()
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == len(before) and not unit.is_busy, timeout=10000
    )
    assert {e.entity_id: e for e, _layer in canvas.background_entities}[target.entity_id] == target


def test_drag_trim_saved_target_escape_preserves_draft_and_history(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    boundary = LineEntity(uuid4().hex, (20.0, -5.0), (20.0, 10.0))
    canvas.replace_draft_entities((boundary,))
    canvas.set_tool("修剪")
    before = loaded.document.commands
    start, end = canvas.local_to_screen((25.0, 5.0)), canvas.local_to_screen((27.0, 5.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.entities == [boundary]
    assert tuple(e for e, _layer in canvas.background_entities) == (first, saved)
    assert loaded.document.commands == before and canvas.mixed_move is None


def test_drag_trim_two_saved_targets_is_one_atomic_undo(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    second = LineEntity(uuid4().hex, (-30.0, 0.0), (30.0, 0.0))
    boundary = LineEntity(uuid4().hex, (20.0, -10.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((second, boundary))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("修剪")
    before = loaded.document.commands
    start, end = canvas.local_to_screen((25.0, 0.0)), canvas.local_to_screen((25.0, 8.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == len(before) + 1 and not unit.is_busy, timeout=10000
    )
    result = {e.entity_id: e for e, _layer in canvas.background_entities}
    assert result[saved.entity_id] == LineEntity(saved.entity_id, (-30.0, 5.0), (20.0, 5.0))
    assert result[second.entity_id] == LineEntity(second.entity_id, (-30.0, 0.0), (20.0, 0.0))
    assert result[boundary.entity_id] == boundary
    window.act_save.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not previous and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    reopened_loaded = window.loaded_document()
    assert reopened is not None and reopened_loaded is not None
    canvas = reopened.canvas
    assert {e.entity_id: e for e, _layer in canvas.background_entities} == result
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(reopened_loaded.document.commands) == len(before),
        timeout=10000,
    )
    restored = {e.entity_id: e for e, _layer in canvas.background_entities}
    assert restored[saved.entity_id] == saved and restored[second.entity_id] == second


def test_saved_drag_trim_rejects_stale_source_and_refreshes_canvas(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window, _first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    second = LineEntity(uuid4().hex, (-30.0, 0.0), (30.0, 0.0))
    boundary = LineEntity(uuid4().hex, (20.0, -10.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((second, boundary))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.set_tool("修剪")
    start, end = canvas.local_to_screen((25.0, 0.0)), canvas.local_to_screen((25.0, 8.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    extra_line = LineEntity(uuid4().hex, (100.0, 0.0), (110.0, 0.0))
    extra = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (extra_line,))
    loaded.bus.execute("sketch.create", extra.to_state_mapping(), confirmed_by="local")
    after_external = loaded.document.commands
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert loaded.document.commands == after_external
    visible = {e.entity_id: e for e, _layer in canvas.background_entities}
    assert visible[saved.entity_id] == saved and visible[second.entity_id] == second
    assert visible[extra_line.entity_id] == extra_line
    assert "变化" in editor.status_label.text()


def test_saved_drag_trim_rejects_revision_change_without_geometry_change(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    second = LineEntity(uuid4().hex, (-30.0, 0.0), (30.0, 0.0))
    boundary = LineEntity(uuid4().hex, (20.0, -10.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((second, boundary))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    qtbot.waitUntil(lambda: not unit.is_delivering_result, timeout=10000)
    canvas = editor.canvas
    canvas.set_tool("修剪")
    start, end = canvas.local_to_screen((25.0, 0.0)), canvas.local_to_screen((25.0, 8.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    after_external = loaded.document.commands
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert loaded.document.commands == after_external
    visible = {e.entity_id: e for e, _layer in canvas.background_entities}
    assert visible[saved.entity_id] == saved and visible[second.entity_id] == second
    assert "变化" in editor.status_label.text()


def test_drag_trim_multiple_saved_targets_uses_source_workplane(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    second = LineEntity(uuid4().hex, (-30.0, 0.0), (30.0, 0.0))
    boundary = LineEntity(uuid4().hex, (20.0, -10.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((second, boundary))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.origin_fields["X"].setValue(10.0)
    canvas = editor.canvas
    canvas.set_tool("修剪")
    before = loaded.document.commands
    start, end = canvas.local_to_screen((15.0, 0.0)), canvas.local_to_screen((15.0, 8.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == len(before) + 1 and not unit.is_busy, timeout=10000
    )
    editor.origin_fields["X"].setValue(0.0)
    result = {e.entity_id: e for e, _layer in canvas.background_entities}
    assert result[saved.entity_id] == LineEntity(saved.entity_id, (-30.0, 5.0), (20.0, 5.0))
    assert result[second.entity_id] == LineEntity(second.entity_id, (-30.0, 0.0), (20.0, 0.0))
    assert result[boundary.entity_id] == boundary


def test_saved_click_trim_rejects_stale_source_and_refreshes_canvas(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window, _first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    boundary = LineEntity(uuid4().hex, (20.0, -5.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((boundary,))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.set_tool("修剪")
    extra_line = LineEntity(uuid4().hex, (100.0, 0.0), (110.0, 0.0))
    extra = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (extra_line,))
    loaded.bus.execute("sketch.create", extra.to_state_mapping(), confirmed_by="local")
    after_external = loaded.document.commands
    canvas.add_coordinate_point((25.0, 5.0), exact_point=True)
    assert loaded.document.commands == after_external
    visible = {e.entity_id: e for e, _layer in canvas.background_entities}
    assert visible[saved.entity_id] == saved and visible[extra_line.entity_id] == extra_line
    assert "变化" in editor.status_label.text()


def test_saved_click_trim_rejects_revision_change_without_geometry_change(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    boundary = LineEntity(uuid4().hex, (20.0, -5.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((boundary,))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    qtbot.waitUntil(lambda: not unit.is_delivering_result, timeout=10000)
    canvas = editor.canvas
    canvas.set_tool("修剪")
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    after_external = loaded.document.commands
    canvas.add_coordinate_point((25.0, 5.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert loaded.document.commands == after_external
    assert {e.entity_id: e for e, _layer in canvas.background_entities}[saved.entity_id] == saved
    assert "变化" in editor.status_label.text()


@pytest.mark.parametrize("operation", ["move", "rotate", "mirror", "delete"])
def test_saved_transform_rejects_stale_document_revision(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], operation: str
) -> None:
    window, saved, other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    if operation in {"move", "rotate", "mirror"}:
        canvas.begin_transform(operation, keep_source=False)
        canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    after_external = loaded.document.commands
    if operation == "move":
        canvas.add_coordinate_point((5.0, 0.0), exact_point=True)
    elif operation == "rotate":
        canvas.apply_rotation_angle(45.0)
    elif operation == "mirror":
        canvas.add_coordinate_point((5.0, 0.0), exact_point=True)
    else:
        canvas.delete_selected()
    assert loaded.document.commands == after_external
    assert tuple(e for e, _layer in canvas.background_entities) == (saved, other)
    assert "变化" in editor.status_label.text()


@pytest.mark.parametrize("operation", ["move", "rotate", "mirror"])
def test_transform_gesture_rejects_revision_change_after_context_refresh(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], operation: str
) -> None:
    window, saved, other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform(operation, keep_source=False)
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    after_external = loaded.document.commands
    editor.set_context_sketches(editor.dimension_sources()[1:])
    if operation == "rotate":
        canvas.apply_rotation_angle(45.0)
    else:
        canvas.add_coordinate_point((5.0, 0.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert loaded.document.commands == after_external
    assert tuple(e for e, _layer in canvas.background_entities) == (saved, other)
    assert "变化" in editor.status_label.text()


def test_starting_transform_with_stale_context_cancels_previous_gesture(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    after_external = loaded.document.commands
    canvas.begin_transform("copy")
    assert "变化" in editor.status_label.text()
    canvas.add_coordinate_point((5.0, 0.0), exact_point=True)
    assert loaded.document.commands == after_external
    assert canvas.entities == []


@pytest.mark.parametrize(
    "operation", ["copy", "mirror", "offset", "linear_array", "circular_array"]
)
def test_numeric_saved_copy_rejects_stale_document_revision(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], operation: str
) -> None:
    window, saved, other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    editor.tool_buttons["选择元素"].click()
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.changed.emit()
    editor.delta_u_field.setValue(2.0)
    editor.offset_distance_field.setValue(2.0)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    after_external = loaded.document.commands
    if operation == "copy":
        editor.numeric_copy_button.click()
    elif operation == "mirror":
        editor.numeric_mirror_button.click()
    else:
        editor.transform_buttons[operation].click()
    assert loaded.document.commands == after_external
    assert canvas.entities == []
    assert tuple(e for e, _layer in canvas.background_entities) == (saved, other)
    assert "变化" in editor.status_label.text()


def test_repeated_copy_revision_change_keeps_placed_copies(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((5.0, 0.0), exact_point=True)
    assert len(canvas.entities) == 1
    placed = canvas.entities[0]
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    after_external = loaded.document.commands
    editor.set_context_sketches(editor.dimension_sources()[1:])
    canvas.add_coordinate_point((10.0, 0.0), exact_point=True)
    assert canvas.active_transform is None and canvas.entities == [placed]
    assert tuple(e for e, _layer in canvas.background_entities) == (saved, other)
    assert loaded.document.commands == after_external
    assert "变化" in editor.status_label.text()


def test_drag_trim_locked_saved_target_rolls_back_draft_preview(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    from dataclasses import replace

    window, first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    canvas.background_entities = tuple(
        (entity, replace(layer, locked=True) if entity.entity_id == saved.entity_id else layer)
        for entity, layer in canvas.background_entities
    )
    draft = LineEntity(uuid4().hex, (-30.0, 0.0), (30.0, 0.0))
    boundary = LineEntity(uuid4().hex, (20.0, -10.0), (20.0, 10.0))
    canvas.replace_draft_entities((draft, boundary))
    canvas.set_tool("修剪")
    before = loaded.document.commands
    start, end = canvas.local_to_screen((25.0, 0.0)), canvas.local_to_screen((25.0, 8.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.entities == [draft, boundary]
    assert tuple(entity for entity, _layer in canvas.background_entities) == (first, saved)
    assert loaded.document.commands == before and canvas.mixed_move is None


def test_drag_trim_locked_draft_target_rolls_back_saved_preview(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    from mycad.core.sketch_layers import SketchLayer

    window, first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    layers = editor.layer_table.add(SketchLayer("restricted", locked=True))
    editor.set_document_layers(layers, editor.dimension_layer)
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (-30.0, 0.0), (30.0, 0.0), layer_name="restricted")
    boundary = LineEntity(uuid4().hex, (20.0, -10.0), (20.0, 10.0))
    canvas.replace_draft_entities((draft, boundary))
    canvas.set_tool("修剪")
    before = loaded.document.commands
    start, end = canvas.local_to_screen((25.0, 0.0)), canvas.local_to_screen((25.0, 8.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.entities == [draft, boundary]
    assert tuple(entity for entity, _layer in canvas.background_entities) == (first, saved)
    assert loaded.document.commands == before and canvas.mixed_move is None


def test_drag_trim_locked_draft_target_rolls_back_other_draft_targets(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    from mycad.core.sketch_layers import SketchLayer

    window, _first, _saved = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    layers = editor.layer_table.add(SketchLayer("restricted", locked=True))
    editor.set_document_layers(layers, editor.dimension_layer)
    canvas = editor.canvas
    editable = LineEntity(uuid4().hex, (-30.0, 15.0), (30.0, 15.0))
    locked = LineEntity(uuid4().hex, (-30.0, 20.0), (30.0, 20.0), layer_name="restricted")
    boundary = LineEntity(uuid4().hex, (20.0, 10.0), (20.0, 25.0))
    canvas.replace_draft_entities((editable, locked, boundary))
    canvas.set_tool("修剪")
    history_position = canvas.history_position
    start, end = canvas.local_to_screen((25.0, 15.0)), canvas.local_to_screen((25.0, 23.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.entities == [editable, locked, boundary]
    assert canvas.history_position == history_position
    assert "锁定" in editor.status_label.text()


def test_drag_trim_invalid_draft_target_rolls_back_saved_preview(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    from mycad.core.sketch import CircleEntity

    window, first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    draft = CircleEntity(uuid4().hex, (25.0, 0.0), 3.0)
    boundary = LineEntity(uuid4().hex, (20.0, -10.0), (20.0, 10.0))
    canvas.replace_draft_entities((draft, boundary))
    canvas.set_tool("修剪")
    before = loaded.document.commands
    start, end = canvas.local_to_screen((25.0, 3.0)), canvas.local_to_screen((25.0, 8.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert canvas.entities == [draft, boundary]
    assert tuple(entity for entity, _layer in canvas.background_entities) == (first, saved)
    assert loaded.document.commands == before and canvas.mixed_move is None


def test_drag_trim_constraint_failure_rolls_back_every_saved_target(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window, _first, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    constrained = LineEntity(uuid4().hex, (-30.0, 20.0), (30.0, 20.0))
    other = LineEntity(uuid4().hex, (-30.0, 15.0), (30.0, 15.0))
    boundary = LineEntity(uuid4().hex, (20.0, 10.0), (20.0, 25.0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(constrained.entity_id, "geometry"),),
        60.0,
        "mm",
    )
    editor.canvas.replace_draft_entities((constrained, other, boundary))
    editor.canvas.constraints = [dimension]
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.set_tool("修剪")
    before = loaded.document.commands
    start, end = canvas.local_to_screen((25.0, 15.0)), canvas.local_to_screen((25.0, 23.0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(
        lambda: "失败" in editor.status_label.text() and not unit.is_busy, timeout=10000
    )
    assert loaded.document.commands == before
    actual = {entity.entity_id: entity for entity, _layer in canvas.background_entities}
    assert actual[constrained.entity_id] == constrained
    assert actual[other.entity_id] == other and actual[boundary.entity_id] == boundary
    assert dimension.constraint_id in {c.constraint_id for c in canvas.visible_dimensions()}


def test_arrayrect_saved_preview_blocks_document_undo(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {saved.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "2", "2", "-4", "8"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.transform_preview_entities) == 3 and not canvas.entities
    before = loaded.document.commands
    window.request_undo()
    assert loaded.document.commands == before
    assert "完成或取消" in window.status_command.text()
    QTest.keyClick(command, Qt.Key.Key_Escape)
    assert not canvas.transform_preview_entities and loaded.document.commands == before


@pytest.mark.parametrize("include_saved", [False, True])
@pytest.mark.parametrize("angle", [0, 90])
def test_arrayrect_associative_draft_saves_and_reopens(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    include_saved: bool,
    angle: int,
) -> None:
    window, saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = (
        {source.entity_id, saved.entity_id} if include_saved else {source.entity_id}
    )
    command = editor.drawing_command_bar.input
    angle_options = ("AN", str(angle)) if angle else ()
    for value in ("ARRAYRECT", "", "2", "2", "-4", "8", *angle_options, "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.pending_associative_arrays) == 1
    array = editor.canvas.pending_associative_arrays[0]
    assert len(array.sources) == (2 if include_saved else 1)
    assert array.angle_deg == angle
    draft_copy_ids = {member.target.entity_id for member in array.members}
    assert len(draft_copy_ids) == (6 if include_saved else 3)
    assert editor.canvas.undo_last_operation() and not editor.canvas.pending_associative_arrays
    assert editor.canvas.redo_last_operation() and editor.canvas.pending_associative_arrays == [
        array
    ]
    before_count = len(loaded.document.commands)
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert len(loaded.document.commands) == before_count + 1
    assert loaded.document.commands[-1].version == (14 if angle else 11)
    assert "associative_arrays" in loaded.document.commands[-1].params
    submitted = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not submitted and not unit.is_busy, timeout=10000
    )
    reopened = window.loaded_document()
    assert reopened is not None and "associative_arrays" in reopened.document.commands[-1].params
    current = window.active_sketch_dialog()
    assert current is not None
    assert draft_copy_ids.issubset(
        {entity.entity_id for entity, _ in current.canvas.background_entities}
    )
    if include_saved and angle:
        member = next(item for item in array.members if item.source.entity_id == saved.entity_id)
        previous = next(
            entity
            for entity, _ in current.canvas.background_entities
            if entity.entity_id == member.target.entity_id
        )
        assert isinstance(previous, LineEntity)
        current.canvas.selected_entity_ids = {saved.entity_id}
        current.canvas.begin_transform("move")
        current.canvas.add_coordinate_point((0, 0), exact_point=True)
        current.canvas.add_coordinate_point((1, 0), exact_point=True)
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
        updated = next(
            entity
            for entity, _ in current.canvas.background_entities
            if entity.entity_id == member.target.entity_id
        )
        assert isinstance(updated, LineEntity)
        assert updated.start_mm == pytest.approx((previous.start_mm[0] + 1, previous.start_mm[1]))


def test_mixed_move_preview_rejects_unsynchronized_array_source(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {saved.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.pending_associative_arrays
    extra = LineEntity(uuid4().hex, (0, 10), (2, 10))
    assert canvas.replace_draft_entities((*canvas.entities, extra))
    before = loaded.document.commands
    canvas.selected_entity_ids = {saved.entity_id, extra.entity_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((0, 3), exact_point=True)
    qtbot.waitUntil(
        lambda: not unit.is_busy and "关联阵列" in editor.status_label.text(), timeout=10000
    )
    assert canvas.mixed_move is None and loaded.document.commands == before
    assert saved in tuple(entity for entity, _layer in canvas.background_entities)


@pytest.mark.parametrize("angle", [0, 180])
def test_associative_array_before_staged_cross_sketch_trim(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], angle: int
) -> None:
    window, _first, _target = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    boundary = LineEntity(uuid4().hex, (20, -5), (20, 10))
    assert canvas.replace_draft_entities((boundary,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {boundary.entity_id}
    command = editor.drawing_command_bar.input
    for value in (
        "ARRAYRECT",
        "",
        "1",
        "2",
        "8",
        *(("AN", str(angle)) if angle else ()),
        "AS",
        "Y",
        "",
    ):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.pending_associative_arrays) == 1
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool("修剪")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((25, 5)))
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    assert any("associative_arrays" in command.params for command in loaded.document.commands)
    if angle:
        assert any(
            command.id == "sketch.create" and command.version == 14
            for command in loaded.document.commands
        )


@pytest.mark.parametrize("angle", [0, 180])
def test_associative_array_after_staged_cross_sketch_trim(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], angle: int
) -> None:
    window, _first, _target = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    boundary = LineEntity(uuid4().hex, (20, -5), (20, 10))
    assert canvas.replace_draft_entities((boundary,))
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool("修剪")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((25, 5)))
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {boundary.entity_id}
    command = editor.drawing_command_bar.input
    for value in (
        "ARRAYRECT",
        "",
        "1",
        "2",
        "8",
        *(("AN", str(angle)) if angle else ()),
        "AS",
        "Y",
        "",
    ):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.pending_associative_arrays) == 1
    copy_id = canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    assert loaded.document.commands[-1].id == "drawing.sketch.revise"
    assert loaded.document.commands[-1].version == (11 if angle else 6)
    assert "associative_arrays" in loaded.document.commands[-1].params
    current = window.active_sketch_dialog()
    assert current is not None and any(
        entity.entity_id == copy_id for entity, _ in current.canvas.background_entities
    )
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert all(entity.entity_id != copy_id for entity, _ in current.canvas.background_entities)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert any(entity.entity_id == copy_id for entity, _ in current.canvas.background_entities)
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not current and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    assert any(entity.entity_id == copy_id for entity, _ in reopened.canvas.background_entities)


def test_associative_array_and_pending_tangency_commit_together(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch import CircleEntity

    window, saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    assert editor.canvas.replace_draft_entities((circle,))
    editor.canvas.pending_cross_tangencies = [(saved.entity_id, circle.entity_id)]
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {circle.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.pending_associative_arrays) == 1
    assert editor.canvas.undo_last_operation() and not editor.canvas.pending_associative_arrays
    assert editor.canvas.pending_cross_tangencies == [(saved.entity_id, circle.entity_id)]
    assert (
        editor.canvas.redo_last_operation() and len(editor.canvas.pending_associative_arrays) == 1
    )
    before = len(loaded.document.commands)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert len(loaded.document.commands) == before + 1
    params = loaded.document.commands[-1].params
    assert "cross_tangencies" in params and "associative_arrays" in params
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before, timeout=10000
    )


@pytest.mark.parametrize("angle", [0, 90])
def test_saved_associative_array_exposes_spacing_grips(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    angle: int,
) -> None:
    from dataclasses import replace

    window, _saved, _other = reopened_drawing
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in (
        "ARRAYRECT",
        "",
        "2",
        "2",
        "4",
        "8",
        *(("AN", str(angle)) if angle else ()),
        "AS",
        "Y",
        "",
    ):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    array = editor.canvas.pending_associative_arrays[0]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    assert current.canvas.set_tool("选择元素")
    current.canvas.selected_entity_ids = {source.entity_id}
    grips = current.canvas.associative_spacing_grips()
    assert len(grips) == 2
    assert all(item[0].array_id == array.array_id for item in grips)
    positions = {axis: point for _array, axis, point in grips}
    assert positions["column"] == pytest.approx((10, 12) if angle else (18, 4))
    assert positions["row"] == pytest.approx((6, 4) if angle else (10, 8))
    current.canvas.selected_entity_ids = {array.members[0].target.entity_id}
    assert current.canvas.associative_spacing_grips() == grips
    background = current.canvas.background_entities
    current.canvas.background_entities = tuple(
        (entity, replace(layer, locked=True) if entity.entity_id == source.entity_id else layer)
        for entity, layer in background
    )
    assert not current.canvas.associative_spacing_grips()
    current.canvas.background_entities = background
    provider = current.canvas.source_revision_provider
    assert provider is not None
    current.canvas.source_revision_provider = lambda: provider() + 1
    assert not current.canvas.associative_spacing_grips()
    current.canvas.source_revision_provider = provider
    current.canvas.begin_transform("move")
    assert not current.canvas.associative_spacing_grips()
    current.canvas.cancel_transform()
    current.canvas.selected_entity_ids = {source.entity_id, _other.entity_id}
    assert not current.canvas.associative_spacing_grips()


@pytest.mark.parametrize("kind", ["fixed", "key"])
def test_saved_array_grips_use_explicit_base_point(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], kind: str
) -> None:
    from dataclasses import replace

    from mycad.core.associative_array import ArrayBasePoint
    from mycad.core.sketch_constraints import SketchGeometryReference

    window, _saved, _other = reopened_drawing
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {source.entity_id}
    provider = canvas.associative_arrays_provider
    assert provider is not None
    array = next(a for a in provider() if a.sources[0].entity_id == source.entity_id)
    base = (
        ArrayBasePoint(point_mm=(30, 9))
        if kind == "fixed"
        else ArrayBasePoint(
            source=array.sources[0], reference=SketchGeometryReference(source.entity_id, "end")
        )
    )
    canvas.associative_arrays_provider = lambda: (replace(array, base_point=base),)
    grips = canvas.associative_spacing_grips()
    assert len(grips) == 1
    assert grips[0][2] == pytest.approx((38, 9) if kind == "fixed" else (28, 4))


@pytest.mark.parametrize("kind", ["fixed", "key"])
def test_arrayrect_base_point_creation_saves_and_reopens(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], kind: str
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    base_input = ("B", "30,9") if kind == "fixed" else ("B", "K", "20,4")
    for value in ("ARRAYRECT", "", "1", "2", "8", *base_input, "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(editor.canvas.pending_associative_arrays) == 1
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert loaded.document.commands[-1].version == 15
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    current.canvas.selected_entity_ids = {source.entity_id}
    expected = (38, 9) if kind == "fixed" else (28, 4)
    assert current.canvas.associative_spacing_grips()[0][2] == pytest.approx(expected)
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.loaded_document() is not loaded, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None and reopened.canvas.set_tool("选择元素")
    reopened.canvas.selected_entity_ids = {source.entity_id}
    assert reopened.canvas.associative_spacing_grips()[0][2] == pytest.approx(expected)


@pytest.mark.parametrize("base_kind", ["default", "fixed", "key"])
def test_array_base_grip_moves_whole_array_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], base_kind: str
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    base_input = (
        ("B", "30,9") if base_kind == "fixed" else ("B", "K", "20,4") if base_kind == "key" else ()
    )
    for value in ("ARRAYRECT", "", "1", "2", "8", *base_input, "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    array = editor.canvas.pending_associative_arrays[0]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {source.entity_id}
    grip = canvas.associative_base_grips()[0][1]
    expected_base = (30, 9) if base_kind == "fixed" else (20, 4) if base_kind == "key" else (10, 4)
    expected_moved = (expected_base[0] + 3, expected_base[1] + 2)
    assert grip == pytest.approx(expected_base)
    before = loaded.document.commands
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(grip))
    destination = canvas.local_to_screen(expected_moved)
    QTest.mouseMove(canvas, destination)
    assert canvas.array_spacing_drag_active and len(canvas.array_spacing_preview) == 2
    assert loaded.document.commands == before
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=destination)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.move"
    moved = {entity.entity_id: entity for entity, _layer in canvas.background_entities}
    moved_source = moved[source.entity_id]
    moved_member = moved[array.members[0].target.entity_id]
    assert isinstance(moved_source, LineEntity) and isinstance(moved_member, LineEntity)
    assert moved_source.start_mm == pytest.approx((13, 6), abs=0.25)
    assert moved_member.start_mm == pytest.approx((21, 6), abs=0.25)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and loaded.document.commands == before, timeout=10000)
    assert canvas.associative_base_grips()[0][1] == pytest.approx(expected_base)
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert canvas.associative_base_grips()[0][1] == pytest.approx(expected_moved, abs=0.25)
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.loaded_document() is not loaded, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None and reopened.canvas.set_tool("选择元素")
    reopened.canvas.selected_entity_ids = {source.entity_id}
    assert reopened.canvas.associative_base_grips()[0][1] == pytest.approx(expected_moved, abs=0.25)


@pytest.mark.parametrize("case", ["escape", "stale", "draft", "locked_member", "zero"])
def test_array_base_grip_cancellation_and_stale_state_do_not_write(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], case: str
) -> None:
    from dataclasses import replace

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "B", "30,9", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    member = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {source.entity_id}
    before = loaded.document.commands
    if case == "locked_member":
        canvas.background_entities = tuple(
            (entity, replace(layer, locked=True) if entity.entity_id == member else layer)
            for entity, layer in canvas.background_entities
        )
    origin = canvas.local_to_screen((30, 9))
    destination = canvas.local_to_screen((33, 11)) if case != "zero" else origin
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=origin)
    assert canvas.array_spacing_drag_active
    if case == "stale":
        provider = canvas.source_revision_provider
        assert provider is not None
        canvas.source_revision_provider = lambda: provider() + 1
    if case == "draft":
        assert canvas.replace_draft_entities(
            (*canvas.entities, LineEntity(uuid4().hex, (40, 40), (42, 40)))
        )
    QTest.mouseMove(canvas, destination)
    if case == "locked_member":
        assert not canvas.array_spacing_preview and "锁定" in canvas.message
    if case == "escape":
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
    else:
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=destination)
    assert not canvas.array_spacing_drag_active
    assert loaded.document.commands == before


def test_array_base_grip_previews_moving_dimensions(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(source.entity_id, "geometry"),),
        10.0,
        "mm",
        position_mm=(12, 8),
        text_position_mm=(14, 9),
    )
    assert editor.canvas.replace_draft_entities((source,), new_relations=(constraint,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "B", "30,9", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {source.entity_id}
    origin, target = canvas.local_to_screen((30, 9)), canvas.local_to_screen((33, 11))
    before = loaded.document.commands
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=origin)
    QTest.mouseMove(canvas, target)
    preview_source = canvas.dimension_entities()[source.entity_id]
    assert isinstance(preview_source, LineEntity)
    assert preview_source.start_mm == pytest.approx((13, 6), abs=0.25)
    preview_dimension = next(
        c for c in canvas.dimension_constraints() if c.constraint_id == constraint.constraint_id
    )
    assert preview_dimension.position_mm == pytest.approx((15, 10), abs=0.25)
    assert preview_dimension.text_position_mm == pytest.approx((17, 11), abs=0.25)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    committed = next(
        c for c in canvas.dimension_constraints() if c.constraint_id == constraint.constraint_id
    )
    assert committed.position_mm == pytest.approx((15, 10), abs=0.25)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and loaded.document.commands == before, timeout=10000)
    assert canvas.dimension_entities()[source.entity_id] == source
    assert (
        next(
            c for c in canvas.dimension_constraints() if c.constraint_id == constraint.constraint_id
        )
        == constraint
    )
    assert loaded.document.commands == before


def test_downstream_array_base_grip_moves_using_member_offset(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for index in range(2):
        for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
            bar.setText(value)
            QTest.keyClick(bar, Qt.Key.Key_Return)
        if index == 0:
            editor.canvas.selected_entity_ids = {
                editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
            }
    assert len(editor.canvas.pending_associative_arrays) == 2
    upstream, downstream = editor.canvas.pending_associative_arrays
    first_copy = upstream.members[0].target.entity_id
    final_copy = downstream.members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {final_copy}
    grip = canvas.associative_base_grips()[0][1]
    destination = (grip[0] + 2, grip[1] + 3)
    before = loaded.document.commands
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(grip))
    QTest.mouseMove(canvas, canvas.local_to_screen(destination))
    assert len(canvas.array_spacing_preview) == 2
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(destination))
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.move"
    assert loaded.document.commands[-1].version == 2
    entities = {entity.entity_id: entity for entity, _layer in canvas.background_entities}
    assert entities[source.entity_id] == source
    moved_source, moved_copy = entities[first_copy], entities[final_copy]
    assert isinstance(moved_source, LineEntity) and isinstance(moved_copy, LineEntity)
    assert moved_source.start_mm == pytest.approx((7, 3), abs=0.25)
    assert moved_copy.start_mm == pytest.approx((12, 3), abs=0.25)
    provider = canvas.associative_arrays_provider
    assert provider is not None
    assert next(a for a in provider() if a.array_id == upstream.array_id).members[
        0
    ].offset_mm == pytest.approx((2, 3), abs=0.25)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and loaded.document.commands == before, timeout=10000)
    assert next(a for a in provider() if a.array_id == upstream.array_id).members[0].offset_mm == (
        0,
        0,
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.loaded_document() is not loaded, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    reopened_provider = reopened.canvas.associative_arrays_provider
    assert reopened_provider is not None
    assert next(a for a in reopened_provider() if a.array_id == upstream.array_id).members[
        0
    ].offset_mm == pytest.approx((2, 3), abs=0.25)
    assert reopened.canvas.set_tool("选择元素")
    reopened.canvas.selected_entity_ids = {first_copy}
    reopened_loaded = window.loaded_document()
    assert reopened_loaded is not None
    previous = reopened_loaded.document.commands
    window.act_reset_associative_offsets.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(reopened_loaded.document.commands) == len(previous) + 1,
        timeout=10000,
    )
    assert next(a for a in reopened_provider() if a.array_id == upstream.array_id).members[
        0
    ].offset_mm == (0, 0)
    restored = {entity.entity_id: entity for entity, _layer in reopened.canvas.background_entities}
    restored_downstream = restored[final_copy]
    assert isinstance(restored_downstream, LineEntity)
    assert restored_downstream.start_mm == pytest.approx((10, 0), abs=0.25)


def test_array_member_offset_menu_edit_reset_and_undo(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    member = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(member, "geometry"),),
        10.0,
        "mm",
        position_mm=(23, 7),
        text_position_mm=(23, 8),
    )
    editor.canvas.constraints = [dimension]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {member}
    before = loaded.document.commands

    def enter_offset(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "2.123456789,3", True

    def unchanged(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "0,0", True

    def invalid(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "nan,0", True

    def cancelled(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "3,4", False

    for handler in (unchanged, invalid, cancelled):
        monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", handler)
        window.act_offset_associative_member.trigger()
        assert loaded.document.commands == before
    window.act_reset_associative_offsets.trigger()
    assert loaded.document.commands == before
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", enter_offset)
    window.act_offset_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    provider = canvas.associative_arrays_provider
    assert provider is not None
    assert provider()[0].members[0].offset_mm == pytest.approx((2.123456789, 3))
    moved_dimension = next(
        c for c in canvas.visible_dimensions() if c.constraint_id == dimension.constraint_id
    )
    assert moved_dimension.position_mm == pytest.approx((25.123456789, 10))
    assert moved_dimension.text_position_mm == pytest.approx((25.123456789, 11))
    window.act_reset_associative_offsets.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert provider()[0].members[0].offset_mm == (0, 0)
    assert (
        next(c for c in canvas.visible_dimensions() if c.constraint_id == dimension.constraint_id)
        == dimension
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert provider()[0].members[0].offset_mm == pytest.approx((2.123456789, 3))


def test_array_member_rotation_menu_updates_and_undoes(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    member = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    current.canvas.selected_entity_ids = {member}
    before = loaded.document.commands

    def invalid(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "nan", True

    def cancelled(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "45", False

    for handler in (invalid, cancelled):
        monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", handler)
        window.act_rotate_associative_member.trigger()
        assert loaded.document.commands == before
    answers = iter((("90", True), ("23,4", True)))

    def answer(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return next(answers)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", answer)
    window.act_rotate_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    provider = current.canvas.associative_arrays_provider
    assert provider is not None and provider()[0].members[0].rotation_deg == 90
    entity = next(
        entity
        for entity, _layer in current.canvas.background_entities
        if entity.entity_id == member
    )
    assert isinstance(entity, LineEntity)
    assert entity.start_mm == pytest.approx((23, -1))
    assert entity.end_mm == pytest.approx((23, 9))
    counts = iter(((1, True), (3, True)))

    def answer_count(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return next(counts)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", answer_count)
    window.act_resize_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2,
        timeout=10000,
    )
    assert loaded.document.commands[-1].version == 5
    assert provider()[0].columns == 3 and provider()[0].members[0].rotation_deg == 90
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1,
        timeout=10000,
    )
    window.act_reset_associative_overrides.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2,
        timeout=10000,
    )
    assert provider()[0].members[0].rotation_deg == 0
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert provider()[0].members[0].rotation_deg == 90
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before), timeout=10000
    )
    assert provider()[0].members[0].rotation_deg == 0


def test_delete_members_from_two_arrays_and_ordinary_entity_as_one_operation(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    sources = (LineEntity(uuid4().hex, (0, 0), (2, 0)), LineEntity(uuid4().hex, (0, 5), (2, 5)))
    ordinary = LineEntity(uuid4().hex, (0, 10), (2, 10))
    assert editor.canvas.replace_draft_entities((*sources, ordinary))
    bar = editor.drawing_command_bar.input
    for source in sources:
        editor.canvas.selected_entity_ids = {source.entity_id}
        for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
            bar.setText(value)
            QTest.keyClick(bar, Qt.Key.Key_Return)
    members = {
        array.members[0].target.entity_id for array in editor.canvas.pending_associative_arrays
    }
    assert len(members) == 2
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    selected = members | {ordinary.entity_id}
    canvas.selected_entity_ids = selected.copy()
    before = loaded.document.commands
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.erase"
    assert loaded.document.commands[-1].version == 3
    assert not selected & {entity.entity_id for entity, _layer in canvas.background_entities}
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before), timeout=10000
    )
    assert selected <= {entity.entity_id for entity, _layer in canvas.background_entities}


def test_draft_array_member_with_pending_cross_tangency_cannot_be_deleted(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    from mycad.core.sketch import CircleEntity

    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    source = CircleEntity(uuid4().hex, (-5, 2), 2)
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    canvas = editor.canvas
    member = canvas.pending_associative_arrays[0].members[0].target.entity_id
    pair = (saved.entity_id, member)
    canvas.pending_cross_tangencies.append(pair)
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {member}
    assert not canvas.delete_selected()
    assert member in {entity.entity_id for entity in canvas.entities}
    assert canvas.pending_cross_tangencies == [pair]


def test_delete_draft_array_member_retains_recoverable_identity(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    canvas = editor.canvas
    member = canvas.pending_associative_arrays[0].members[0].target.entity_id
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    assert not canvas.delete_selected()
    assert source.entity_id in {entity.entity_id for entity in canvas.entities}
    canvas.selected_entity_ids = {member}
    assert canvas.delete_selected()
    assert member not in {entity.entity_id for entity in canvas.entities}
    assert canvas.pending_associative_arrays[0].members[0].erased_index is not None
    assert canvas.undo_last_operation()
    assert member in {entity.entity_id for entity in canvas.entities}
    assert canvas.redo_last_operation()
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert loaded.document.commands[-1].id == "sketch.create"
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.associative_arrays_provider is not None
    assert current.canvas.associative_arrays_provider()[-1].members[0].erased_index is not None
    assert current.canvas.set_tool("选择元素")
    current.canvas.selected_entity_ids = {source.entity_id}
    before = loaded.document.commands
    window.act_reset_associative_overrides.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert member in {entity.entity_id for entity, _layer in current.canvas.background_entities}


def test_delete_draft_array_member_and_saved_entity_together(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 20), (2, 20))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    canvas = editor.canvas
    member = canvas.pending_associative_arrays[0].members[0].target.entity_id
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {member, saved.entity_id}
    before = loaded.document.commands
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=10000)
    assert member not in {entity.entity_id for entity in canvas.entities}
    assert canvas.pending_associative_arrays[0].members[0].erased_index is not None
    assert saved.entity_id not in {
        entity.entity_id for entity, _layer in canvas.background_entities
    }
    assert loaded.document.commands == before
    assert canvas.undo_last_operation()
    assert member in {entity.entity_id for entity in canvas.entities}
    assert canvas.pending_associative_arrays[0].members[0].erased_index is None
    assert canvas.redo_last_operation()
    assert canvas.pending_associative_arrays[0].members[0].erased_index is not None
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert loaded.document.commands[-1].version == 20
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    ids = {entity.entity_id for entity, _layer in current.canvas.background_entities}
    assert {member, saved.entity_id} <= ids


@pytest.mark.parametrize("include_saved", [False, True])
def test_consecutive_mixed_erases_keep_saved_and_draft_array_states(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], include_saved: bool
) -> None:
    window, saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 20), (2, 20))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    saved_member = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    draft_source = LineEntity(uuid4().hex, (0, 30), (2, 30))
    ordinary = LineEntity(uuid4().hex, (0, 40), (2, 40))
    canvas = current.canvas
    assert canvas.replace_draft_entities((draft_source, ordinary))
    canvas.selected_entity_ids = {draft_source.entity_id}
    for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
        current.drawing_command_bar.input.setText(value)
        QTest.keyClick(current.drawing_command_bar.input, Qt.Key.Key_Return)
    draft_member = canvas.pending_associative_arrays[0].members[0].target.entity_id
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {saved_member, ordinary.entity_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=10000)
    assert saved_member not in {entity.entity_id for entity, _ in canvas.background_entities}
    canvas.selected_entity_ids = (
        {draft_member, saved.entity_id} if include_saved else {draft_member}
    )
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(
        lambda: not unit.is_busy and draft_member not in {e.entity_id for e in canvas.entities},
        timeout=10000,
    )
    assert canvas.pending_associative_arrays[0].members[0].erased_index is not None
    before = loaded.document.commands
    current.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not current and not unit.is_busy, timeout=10000
    )
    assert len(loaded.document.commands) == len(before) + 3
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    after_undo = window.active_sketch_dialog()
    assert after_undo is not None
    ids = {entity.entity_id for entity, _ in after_undo.canvas.background_entities}
    assert draft_member in ids and saved.entity_id in ids and saved_member not in ids


def test_delete_saved_array_member_with_draft_in_one_staged_step(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    member = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    draft = LineEntity(uuid4().hex, (0, 10), (2, 10))
    canvas = current.canvas
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {member, draft.entity_id}
    before = loaded.document.commands
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=10000)
    assert not canvas.entities
    assert member not in {entity.entity_id for entity, _layer in canvas.background_entities}
    assert loaded.document.commands == before
    current.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not current and not unit.is_busy, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.sketch.revise"
    assert loaded.document.commands[-1].version == 20
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    assert member in {entity.entity_id for entity, _layer in reopened.canvas.background_entities}


@pytest.mark.parametrize("mixed", [False, True])
def test_delete_saved_array_member_with_dimension_atomically(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    mixed: bool,
    tmp_path: Path,
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert editor.canvas.replace_draft_entities((source,))
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["horizontal"].click()
    for point in ((10, 0), (10, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    dimension = editor.canvas.constraints[0]
    QTest.keyClick(editor.canvas, Qt.Key.Key_Return)
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "30", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    member = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    draft = LineEntity(uuid4().hex, (0, 30), (20, 30))
    if mixed:
        assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {member, *([draft.entity_id] if mixed else [])}
    canvas.selected_constraint_ids = {dimension.constraint_id}
    before = len(loaded.document.commands)
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    if mixed:
        qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=10000)
        assert canvas.undo_last_operation() and canvas.redo_last_operation()
        current.finish_sketch()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not current and not unit.is_busy,
            timeout=10000,
        )
    else:
        qtbot.waitUntil(
            lambda: not unit.is_busy and len(loaded.document.commands) == before + 1,
            timeout=10000,
        )
    assert loaded.document.commands[-1].id == "drawing.sketch.revise"
    assert loaded.document.commands[-1].version == 20
    active = window.active_sketch_dialog()
    assert active is not None and dimension not in active.canvas.background_constraints
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + int(mixed),
        timeout=10000,
    )
    active = window.active_sketch_dialog()
    assert active is not None and dimension in active.canvas.background_constraints
    assert member in {entity.entity_id for entity, _ in active.canvas.background_entities}
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1 + int(mixed),
        timeout=10000,
    )
    from mycad import app
    from mycad.core.persistence import save_document

    path = tmp_path / "array-dimension-delete.my2d"
    save_document(loaded.document, path)
    services = app.build_app(discoverers=())
    reopened = app.open_app_document(services, path)
    assert all(dimension not in sketch.constraints for sketch in services.kernel.sketches)
    assert services.kernel.associative_arrays[-1].members[0].erased_index is not None
    reopened.bus.undo()
    assert any(dimension in sketch.constraints for sketch in services.kernel.sketches)
    assert services.kernel.associative_arrays[-1].members[0].erased_index is None


def test_delete_pending_array_member_with_saved_dimension_atomically(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], tmp_path: Path
) -> None:
    window, _saved, _other = reopened_drawing
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert editor.canvas.replace_draft_entities((source,))
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["horizontal"].click()
    for point in ((10, 0), (10, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    dimension = editor.canvas.constraints[0]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    canvas = current.canvas
    draft = LineEntity(uuid4().hex, (0, 30), (20, 30))
    assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {draft.entity_id}
    bar = current.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "30", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    member = canvas.pending_associative_arrays[0].members[0].target.entity_id
    current.dimensions.driving_check.setChecked(False)
    current.dimensions.buttons["horizontal"].click()
    for point in ((40, 30), (40, 40)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    draft_dimension = canvas.constraints[0]
    assert any(ref.entity_id == member for ref in draft_dimension.references)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    canvas.selected_entity_ids = {member}
    canvas.selected_constraint_ids = {dimension.constraint_id, draft_dimension.constraint_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=10000)
    assert canvas.pending_associative_arrays[0].members[0].erased_index is not None
    assert canvas.undo_last_operation()
    assert canvas.pending_associative_arrays[0].members[0].erased_index is None
    assert canvas.redo_last_operation()
    current.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not current and not unit.is_busy, timeout=10000
    )
    active = window.active_sketch_dialog()
    assert active is not None and dimension not in active.canvas.background_constraints
    assert draft_dimension not in active.canvas.background_constraints
    assert member not in {entity.entity_id for entity, _ in active.canvas.background_entities}
    provider = active.canvas.associative_arrays_provider
    assert provider is not None and provider()[-1].members[0].erased_index is not None
    assert loaded.document.commands[-1].version == 26
    from mycad import app
    from mycad.core.persistence import save_document

    path = tmp_path / "pending-member-dimension.my2d"
    save_document(loaded.document, path)
    services = app.build_app(discoverers=())
    reopened = app.open_app_document(services, path)
    assert services.kernel.associative_arrays[-1].members[0].erased_index is not None
    reopened.bus.undo()
    assert services.kernel.associative_arrays[-1].members[0].erased_index is None
    assert any(draft_dimension in sketch.constraints for sketch in services.kernel.sketches)
    reopened.bus.redo()
    assert services.kernel.associative_arrays[-1].members[0].erased_index is not None


@pytest.mark.parametrize("mixed", [False, True])
def test_delete_array_member_with_its_dimension_atomically(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], mixed: bool
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 20), (20, 20))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "30", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    member = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.dimensions.driving_check.setChecked(False)
    editor.dimensions.buttons["horizontal"].click()
    for point in ((40, 20), (40, 30)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    dimension = editor.canvas.constraints[0]
    assert any(ref.entity_id == member for ref in dimension.references)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    draft = LineEntity(uuid4().hex, (0, 50), (10, 50))
    if mixed:
        assert current.canvas.replace_draft_entities((draft,))
    current.canvas.selected_entity_ids = {member, *([draft.entity_id] if mixed else [])}
    current.canvas.selected_constraint_ids = {dimension.constraint_id}
    before = len(loaded.document.commands)
    QTest.keyClick(current.canvas, Qt.Key.Key_Delete)
    if mixed:
        qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=10000)
        current.finish_sketch()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not current and not unit.is_busy,
            timeout=10000,
        )
        current = window.active_sketch_dialog()
        assert current is not None
    else:
        qtbot.waitUntil(
            lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
        )
    assert loaded.document.commands[-1].version == 26
    assert dimension not in current.canvas.background_constraints
    assert member not in {entity.entity_id for entity, _ in current.canvas.background_entities}
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + int(mixed),
        timeout=10000,
    )
    assert dimension in current.canvas.background_constraints
    assert member in {entity.entity_id for entity, _ in current.canvas.background_entities}


def test_delete_array_member_and_reset_from_source(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    member = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {member}
    before = loaded.document.commands
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.erase"
    assert member not in {entity.entity_id for entity, _layer in canvas.background_entities}
    canvas.selected_entity_ids = {source.entity_id}
    counts = iter(((1, True), (3, True)))

    def answer_count(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return next(counts)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", answer_count)
    window.act_resize_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert loaded.document.commands[-1].version == 7
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    window.act_reset_associative_overrides.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert member in {entity.entity_id for entity, _layer in canvas.background_entities}
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert member not in {entity.entity_id for entity, _layer in canvas.background_entities}


def test_reset_erased_downstream_member_from_its_shared_source(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for index in range(2):
        for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
            bar.setText(value)
            QTest.keyClick(bar, Qt.Key.Key_Return)
        if index == 0:
            editor.canvas.selected_entity_ids = {
                editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
            }
    upstream, downstream = editor.canvas.pending_associative_arrays
    shared, target = upstream.members[0].target.entity_id, downstream.members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    current.canvas.selected_entity_ids = {target}
    before = loaded.document.commands
    QTest.keyClick(current.canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    current.canvas.selected_entity_ids = {shared}
    window.act_reset_associative_overrides.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert target in {entity.entity_id for entity, _layer in current.canvas.background_entities}


@pytest.mark.parametrize("with_extra", [False, True])
def test_draft_shared_replacement_rebinds_sources_on_commit(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], with_extra: bool
) -> None:
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayReplacement,
        replace_array_cell_with_extra_outputs,
        set_array_member_replacements,
    )
    from mycad.core.sketch import CircleEntity

    window, saved_line, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    replacement = CircleEntity(uuid4().hex, (20, 20), 2)
    other = CircleEntity(uuid4().hex, (20, 22), 2)
    assert editor.canvas.replace_draft_entities((source, replacement, other))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    array = editor.canvas.pending_associative_arrays[0]
    member = array.members[0]
    draft = editor.dimension_sources()[0]
    changes = {
        member.target: ArrayReplacement(
            ArrayEntityRef(draft.sketch_id, replacement.entity_id), anchor_source=member.source
        )
    }
    extra: ArrayExtraOutput | None = None
    if with_extra:
        extra = ArrayExtraOutput(
            ArrayEntityRef(draft.sketch_id, other.entity_id),
            ArrayEntityRef(draft.sketch_id, uuid4().hex),
            member.source,
            0,
            1,
            (0, -2),
        )
        states, updated = replace_array_cell_with_extra_outputs(
            (draft,), (array,), array.array_id, changes, (extra,)
        )
    else:
        states, updated = set_array_member_replacements((draft,), (array,), array.array_id, changes)
    editor.canvas.entities = list(states[0].entities)
    editor.canvas.pending_associative_arrays = [updated]
    if with_extra:
        assert extra is not None
        pair = (saved_line.entity_id, extra.target.entity_id)
        editor.canvas.pending_cross_tangencies.append(pair)
        assert editor.canvas.set_tool("选择元素")
        editor.canvas.selected_entity_ids = {extra.target.entity_id}
        assert not editor.canvas.delete_selected()
        assert editor.canvas.pending_cross_tangencies == [pair]
        editor.canvas.pending_cross_tangencies.clear()
        assert editor.canvas.delete_selected()
        assert not editor.canvas.pending_associative_arrays[0].extra_outputs
        assert editor.canvas.undo_last_operation()
        assert editor.canvas.pending_associative_arrays[0].extra_outputs == (extra,)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert loaded.document.commands[-1].version == (24 if with_extra else 23)
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.associative_arrays_provider is not None
    saved = current.canvas.associative_arrays_provider()[-1]
    assert saved.members[0].replacement is not None
    assert saved.members[0].replacement.anchor_source == saved.sources[0]
    assert saved.members[0].replacement.source.sketch_id == saved.sources[0].sketch_id
    if with_extra:
        assert saved.extra_outputs[0].source.sketch_id == saved.sources[0].sketch_id
        assert saved.extra_outputs[0].anchor_source == saved.sources[0]
        assert saved.extra_outputs[0].target.sketch_id == saved.sources[0].sketch_id


@pytest.mark.parametrize("source_count", [1, 2])
def test_replace_array_cell_with_extra_entity_and_reset(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
    source_count: int,
) -> None:
    from mycad.core.sketch import CircleEntity

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    sources = (LineEntity(uuid4().hex, (0, 0), (2, 0)), LineEntity(uuid4().hex, (0, 4), (2, 4)))[
        :source_count
    ]
    replacements = tuple(CircleEntity(uuid4().hex, (20, y), 2) for y in (20, 25, 30))[
        : source_count + 1
    ]
    assert editor.canvas.replace_draft_entities((*sources, *replacements))
    editor.canvas.selected_entity_ids = {entity.entity_id for entity in sources}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    members = tuple(
        member.target.entity_id for member in editor.canvas.pending_associative_arrays[0].members
    )
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = set(members)
    choices = iter(replacements)

    def count(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return source_count + 1, True

    def choose(
        _parent: object, _title: object, _label: object, items: list[str], *_args: object
    ) -> tuple[str, bool]:
        item = next(choices)
        return next(value for value in items if item.entity_id[:8] in value), True

    def base(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "20,20", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", count)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", base)
    before = loaded.document.commands
    window.act_replace_associative_cell.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].version == 6
    assert canvas.associative_arrays_provider is not None
    extra = canvas.associative_arrays_provider()[-1].extra_outputs[0].target.entity_id
    assert extra in {entity.entity_id for entity, _ in canvas.background_entities}
    canvas.selected_entity_ids = {extra}
    original_extra = next(
        entity for entity, _ in canvas.background_entities if entity.entity_id == extra
    )
    rotation_values = iter((("90", True), ("8,0", True)))

    def rotate_extra(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return next(rotation_values)

    def cancel_rotation(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "", False

    def invalid_rotation(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "nan", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", cancel_rotation)
    window.act_rotate_associative_member.trigger()
    assert len(loaded.document.commands) == len(before) + 1
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", invalid_rotation)
    window.act_rotate_associative_member.trigger()
    assert len(loaded.document.commands) == len(before) + 1
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", rotate_extra)
    window.act_rotate_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.rotate"
    assert loaded.document.commands[-1].version == 2
    rotated_extra = next(
        entity for entity, _ in canvas.background_entities if entity.entity_id == extra
    )
    assert isinstance(original_extra, CircleEntity) and isinstance(rotated_extra, CircleEntity)
    assert rotated_extra.center_mm == pytest.approx(
        (8 - original_extra.center_mm[1], original_extra.center_mm[0] - 8)
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert original_extra in {entity for entity, _ in canvas.background_entities}
    canvas.selected_entity_ids = {members[0], extra}
    batch_rotation_values = iter((("90", True), ("8,0", True)))

    def rotate_batch(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return next(batch_rotation_values)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", cancel_rotation)
    window.act_rotate_associative_member.trigger()
    assert len(loaded.document.commands) == len(before) + 1
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", invalid_rotation)
    window.act_rotate_associative_member.trigger()
    assert len(loaded.document.commands) == len(before) + 1
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", rotate_batch)
    window.act_rotate_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.rotate"
    assert loaded.document.commands[-1].version == 2
    rotated_array = canvas.associative_arrays_provider()[-1]
    assert rotated_array.members[0].rotation_deg == 90
    assert rotated_array.extra_outputs[0].rotation_deg == 90
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    if source_count == 2:
        canvas.selected_entity_ids = set(members)
        ordinary_rotation = iter((("90", True), ("8,0", True)))

        def rotate_ordinary(*_args: object, **_kwargs: object) -> tuple[str, bool]:
            return next(ordinary_rotation)

        monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", rotate_ordinary)
        window.act_rotate_associative_member.trigger()
        qtbot.waitUntil(
            lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2,
            timeout=10000,
        )
        assert loaded.document.commands[-1].version == 1
        window.request_undo()
        qtbot.waitUntil(
            lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1,
            timeout=10000,
        )
    canvas.selected_entity_ids = {extra}

    def offset_input(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "3,4", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", offset_input)
    regular = next(
        entity for entity, _ in canvas.background_entities if entity.entity_id == members[0]
    )
    canvas.selected_entity_ids = {members[0], extra}

    def cancel_offset(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "", False

    def invalid_offset(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "nan,0", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", cancel_offset)
    window.act_offset_associative_member.trigger()
    assert len(loaded.document.commands) == len(before) + 1
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", invalid_offset)
    window.act_offset_associative_member.trigger()
    assert len(loaded.document.commands) == len(before) + 1
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", offset_input)
    window.act_offset_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert loaded.document.commands[-1].version == 2
    for original in (regular, original_extra):
        shifted_item = next(
            entity
            for entity, _ in canvas.background_entities
            if entity.entity_id == original.entity_id
        )
        assert isinstance(original, CircleEntity) and isinstance(shifted_item, CircleEntity)
        assert shifted_item.center_mm == pytest.approx(
            (original.center_mm[0] + 3, original.center_mm[1] + 4)
        )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    canvas.selected_entity_ids = {extra}
    window.act_offset_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.offset"
    assert loaded.document.commands[-1].version == 2
    shifted = next(entity for entity, _ in canvas.background_entities if entity.entity_id == extra)
    assert isinstance(original_extra, CircleEntity) and isinstance(shifted, CircleEntity)
    assert shifted.center_mm == pytest.approx(
        (original_extra.center_mm[0] + 3, original_extra.center_mm[1] + 4)
    )
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.loaded_document() is not loaded, timeout=10000
    )
    reopened_loaded = window.loaded_document()
    current = window.active_sketch_dialog()
    assert reopened_loaded is not None and current is not None
    canvas = current.canvas
    assert shifted in {entity for entity, _ in canvas.background_entities}
    canvas.selected_entity_ids = {extra}
    window.act_reset_associative_offsets.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(reopened_loaded.document.commands) == len(before) + 3,
        timeout=10000,
    )
    assert reopened_loaded.document.commands[-1].version == 2
    assert original_extra in {entity for entity, _ in canvas.background_entities}
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(reopened_loaded.document.commands) == len(before) + 2,
        timeout=10000,
    )
    assert shifted in {entity for entity, _ in canvas.background_entities}
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(reopened_loaded.document.commands) == len(before) + 1,
        timeout=10000,
    )
    assert original_extra in {entity for entity, _ in canvas.background_entities}
    canvas.selected_entity_ids = {extra}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(reopened_loaded.document.commands) == len(before) + 2,
        timeout=10000,
    )
    assert reopened_loaded.document.commands[-1].id == "drawing.array.erase"
    assert reopened_loaded.document.commands[-1].version == 4
    assert extra not in {entity.entity_id for entity, _ in canvas.background_entities}
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(reopened_loaded.document.commands) == len(before) + 1,
        timeout=10000,
    )
    assert extra in {entity.entity_id for entity, _ in canvas.background_entities}
    canvas.selected_entity_ids = {extra}
    window.act_reset_associative_overrides.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(reopened_loaded.document.commands) == len(before) + 2,
        timeout=10000,
    )
    assert reopened_loaded.document.commands[-1].version == 4
    assert extra not in {entity.entity_id for entity, _ in canvas.background_entities}


def test_extra_output_rotation_center_uses_editor_coordinates_across_sketches(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.associative_array import (
        ArrayEntityRef,
        ArrayExtraOutput,
        ArrayMember,
        AssociativeRectArray,
    )
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.replay_proposal import ReplayChangeSet
    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame

    services = build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    frame = WorkPlaneFrame.xy()
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    replacement = LineEntity(uuid4().hex, (20, 20), (22, 20))
    origin = Sketch(uuid4().hex, frame, (source, replacement))
    app.commit_new_sketch(services, loaded, origin, session_identity=0)
    target = LineEntity(uuid4().hex, (-5, 0), (-3, 0))
    extra = LineEntity(uuid4().hex, (-15, 0), (-13, 0))
    target_sketch = Sketch(uuid4().hex, replace(frame, origin_mm=(10, 0, 0)), (target,))
    app.commit_new_sketch(services, loaded, target_sketch, session_identity=0)
    extra_sketch = Sketch(uuid4().hex, replace(frame, origin_mm=(20, 0, 0)), (extra,))
    source_ref = ArrayEntityRef(origin.sketch_id, source.entity_id)
    target_ref = ArrayEntityRef(target_sketch.sketch_id, target.entity_id)
    extra_ref = ArrayEntityRef(extra_sketch.sketch_id, extra.entity_id)
    output = ArrayExtraOutput(
        ArrayEntityRef(origin.sketch_id, replacement.entity_id), extra_ref, source_ref, 0, 1
    )
    array = AssociativeRectArray(
        uuid4().hex,
        frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
        extra_outputs=(output,),
    )
    app.commit_new_sketch(services, loaded, extra_sketch, session_identity=0)
    candidate = app.create_replay_candidate(services, loaded, session_identity=0)
    candidate.stage(
        ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=0
    )
    assert candidate.preview(current_session_identity=0).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=0), current_session_identity=0
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local", version=12)
    editor.set_context_sketches(services.kernel.sketches)
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {target.entity_id, extra.entity_id}
    prompts = iter((("90", True), ("5,0", True)))

    def answer(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return next(prompts)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", answer)
    before = len(loaded.document.commands)
    window.act_rotate_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )
    updated = next(
        sketch for sketch in services.kernel.sketches if sketch.sketch_id == target_sketch.sketch_id
    )
    rotated = updated.entities[0]
    assert isinstance(rotated, LineEntity)
    assert rotated.start_mm == pytest.approx((-5, 0))
    assert rotated.end_mm == pytest.approx((-5, 2))
    changed_extra = next(
        sketch for sketch in services.kernel.sketches if sketch.sketch_id == extra_sketch.sketch_id
    ).entities[0]
    assert isinstance(changed_extra, LineEntity)
    assert changed_extra.start_mm == pytest.approx((-15, 0))
    assert changed_extra.end_mm == pytest.approx((-15, 2))
    assert services.kernel.associative_arrays[0].extra_outputs[0].rotation_center_offset_mm == (
        0,
        0,
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before, timeout=10000
    )
    assert services.kernel.sketches[-2:] == (target_sketch, extra_sketch)
    second_target = LineEntity(uuid4().hex, (-20, 0), (-18, 0))
    second_sketch = Sketch(uuid4().hex, replace(frame, origin_mm=(30, 0, 0)), (second_target,))
    app.commit_new_sketch(services, loaded, second_sketch, session_identity=0)
    second_ref = ArrayEntityRef(second_sketch.sketch_id, second_target.entity_id)
    second_array = AssociativeRectArray(
        uuid4().hex,
        frame,
        1,
        2,
        0,
        10,
        (source_ref,),
        (ArrayMember(source_ref, second_ref, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": second_array.to_mapping()}, "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.selected_entity_ids = {extra.entity_id, second_target.entity_id}
    prompts = iter((("90", True), ("0,0", True)))
    before = len(loaded.document.commands)
    window.act_rotate_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.batch_override"
    for sketch_id, expected in (
        (extra_sketch.sketch_id, (-20, 5)),
        (second_sketch.sketch_id, (-30, 10)),
    ):
        entity = next(
            sketch for sketch in services.kernel.sketches if sketch.sketch_id == sketch_id
        ).entities[0]
        assert isinstance(entity, LineEntity)
        assert entity.start_mm == pytest.approx(expected)
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before, timeout=10000
    )
    circle = CircleEntity(uuid4().hex, (6, 2), 2)
    circle_sketch = Sketch(uuid4().hex, frame, (circle,))
    app.commit_new_sketch(services, loaded, circle_sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(extra_sketch.sketch_id, extra.entity_id),
        CrossSketchRef(circle_sketch.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.selected_entity_ids = {target.entity_id, extra.entity_id}
    prompts = iter((("90", True), ("5,0", True)))
    before_commands, before_geometry = loaded.document.commands, services.kernel.sketches
    window.act_rotate_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and "相切" in window.status_command.text(), timeout=10000
    )
    assert (
        loaded.document.commands == before_commands and services.kernel.sketches == before_geometry
    )


def test_downstream_array_moves_when_source_is_extra_output(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycad.core.sketch import CircleEntity

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    replacements = (CircleEntity(uuid4().hex, (20, 20), 2), CircleEntity(uuid4().hex, (20, 25), 2))
    assert editor.canvas.replace_draft_entities((source, *replacements))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    member = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {member}
    choices = iter(replacements)

    def count(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return 2, True

    def choose(
        _parent: object, _title: object, _label: object, items: list[str], *_args: object
    ) -> tuple[str, bool]:
        item = next(choices)
        return next(value for value in items if item.entity_id[:8] in value), True

    def base(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "20,20", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", count)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", base)
    before = loaded.document.commands
    window.act_replace_associative_cell.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert canvas.associative_arrays_provider is not None
    extra = canvas.associative_arrays_provider()[-1].extra_outputs[0].target.entity_id
    canvas.selected_entity_ids = {extra}
    for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
        current.drawing_command_bar.input.setText(value)
        QTest.keyClick(current.drawing_command_bar.input, Qt.Key.Key_Return)
    downstream = canvas.pending_associative_arrays[0].members[0].target.entity_id
    current.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not current and not unit.is_busy, timeout=10000
    )
    active = window.active_sketch_dialog()
    assert active is not None and active.canvas.set_tool("选择元素")
    canvas = active.canvas
    canvas.selected_entity_ids = {downstream}
    grip = canvas.associative_base_grips()[0][1]
    destination = (grip[0] + 2, grip[1])
    prior = loaded.document.commands
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(grip))
    QTest.mouseMove(canvas, canvas.local_to_screen(destination))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(destination))
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(prior) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].version == 3
    entities = {item.entity_id: item for item, _layer in canvas.background_entities}
    extra_entity, downstream_entity = entities[extra], entities[downstream]
    assert isinstance(extra_entity, CircleEntity) and isinstance(downstream_entity, CircleEntity)
    assert extra_entity.center_mm == pytest.approx((7, 5), abs=0.25)
    assert downstream_entity.center_mm == pytest.approx((12, 5), abs=0.25)
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(prior), timeout=10000
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(prior) + 1, timeout=10000
    )
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.loaded_document() is not loaded, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    entities = {item.entity_id: item for item, _layer in reopened.canvas.background_entities}
    extra_entity = entities[extra]
    assert isinstance(extra_entity, CircleEntity)
    assert extra_entity.center_mm == pytest.approx((7, 5), abs=0.25)


def test_resize_array_removes_extra_output_with_its_cell(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycad.core.sketch import CircleEntity

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    replacements = (CircleEntity(uuid4().hex, (20, 20), 2), CircleEntity(uuid4().hex, (20, 25), 2))
    assert editor.canvas.replace_draft_entities((source, *replacements))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "3", "5", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    last = editor.canvas.pending_associative_arrays[0].members[-1].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {last}
    choices = iter(replacements)

    def count(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return 2, True

    def choose(
        _parent: object, _title: object, _label: object, items: list[str], *_args: object
    ) -> tuple[str, bool]:
        item = next(choices)
        return next(value for value in items if item.entity_id[:8] in value), True

    def base(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "20,20", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", count)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", base)
    before = loaded.document.commands
    window.act_replace_associative_cell.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert canvas.associative_arrays_provider is not None
    extra = canvas.associative_arrays_provider()[-1].extra_outputs[0].target.entity_id
    canvas.selected_entity_ids = {extra}
    assert canvas.associative_count_grips()
    answers = iter(((1, True), (2, True)))

    def dimensions(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return next(answers)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", dimensions)
    canvas.selected_entity_ids = {source.entity_id}
    window.act_resize_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert loaded.document.commands[-1].version == 13
    assert extra not in {entity.entity_id for entity, _ in canvas.background_entities}
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert extra in {entity.entity_id for entity, _ in canvas.background_entities}
    canvas.selected_entity_ids = {source.entity_id}
    grip = canvas.local_to_screen(canvas.associative_count_grips()[0][1])
    target = grip + canvas.local_to_screen((-5, 0)) - canvas.local_to_screen((0, 0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=grip)
    QTest.mouseMove(canvas, target)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert loaded.document.commands[-1].version == 13
    assert extra not in {entity.entity_id for entity, _ in canvas.background_entities}


@pytest.mark.parametrize(("mixed", "with_dimension"), [(True, False), (True, True), (False, True)])
def test_delete_extra_array_output_with_draft_as_one_step(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
    with_dimension: bool,
    mixed: bool,
) -> None:
    from mycad.core.sketch import CircleEntity

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    replacements = (CircleEntity(uuid4().hex, (20, 20), 2), CircleEntity(uuid4().hex, (20, 25), 2))
    assert editor.canvas.replace_draft_entities((source, *replacements))
    dimension = None
    if with_dimension:
        editor.dimensions.driving_check.setChecked(False)
        editor.dimensions.buttons["radius"].click()
        for point in ((22, 20), (30, 30)):
            QTest.mouseClick(
                editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
            )
        dimension = editor.canvas.constraints[0]
        QTest.keyClick(editor.canvas, Qt.Key.Key_Return)
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "5", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    member = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {member}
    choices = iter(replacements)

    def count(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return 2, True

    def choose(
        _parent: object, _title: object, _label: object, items: list[str], *_args: object
    ) -> tuple[str, bool]:
        item = next(choices)
        return next(value for value in items if item.entity_id[:8] in value), True

    def base(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "20,20", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", count)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", base)
    before = loaded.document.commands
    window.act_replace_associative_cell.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert canvas.associative_arrays_provider is not None
    extra = canvas.associative_arrays_provider()[-1].extra_outputs[0].target.entity_id
    draft = LineEntity(uuid4().hex, (0, 40), (2, 40))
    if mixed:
        assert canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {extra, *([draft.entity_id] if mixed else [])}
    if dimension is not None:
        canvas.selected_constraint_ids = {dimension.constraint_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    if mixed:
        qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=10000)
        assert not canvas.entities
        current.finish_sketch()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not current and not unit.is_busy, timeout=10000
        )
    else:
        qtbot.waitUntil(
            lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2,
            timeout=10000,
        )
    assert loaded.document.commands[-1].version == 23
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1 + int(mixed),
        timeout=10000,
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    assert extra in {entity.entity_id for entity, _ in reopened.canvas.background_entities}
    if dimension is not None:
        assert dimension in reopened.canvas.background_constraints


def test_replace_array_cell_with_fewer_entities_and_reset(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycad.core.sketch import CircleEntity

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    sources = (LineEntity(uuid4().hex, (0, 0), (2, 0)), LineEntity(uuid4().hex, (0, 4), (2, 4)))
    replacement = CircleEntity(uuid4().hex, (20, 20), 2)
    assert editor.canvas.replace_draft_entities((*sources, replacement))
    editor.canvas.selected_entity_ids = {entity.entity_id for entity in sources}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    members = tuple(
        member.target.entity_id for member in editor.canvas.pending_associative_arrays[0].members
    )
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = set(members)

    def count(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return 1, True

    def choose(
        _parent: object, _title: object, _label: object, items: list[str], *_args: object
    ) -> tuple[str, bool]:
        item = next((item for item in items if replacement.entity_id[:8] in item), "")
        return item, bool(item)

    def base(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "20,20", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", count)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", base)
    before = loaded.document.commands
    window.act_replace_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].version == 5
    ids = {entity.entity_id for entity, _ in canvas.background_entities}
    assert members[0] in ids and members[1] not in ids
    canvas.selected_entity_ids = {members[0]}
    window.act_reset_associative_overrides.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert set(members) <= {entity.entity_id for entity, _ in canvas.background_entities}


def test_replace_multiple_entities_in_one_array_cell_atomically(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycad.core.sketch import CircleEntity

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    sources = (LineEntity(uuid4().hex, (0, 0), (2, 0)), LineEntity(uuid4().hex, (0, 4), (2, 4)))
    replacements = (CircleEntity(uuid4().hex, (20, 20), 2), CircleEntity(uuid4().hex, (20, 25), 3))
    assert editor.canvas.replace_draft_entities((*sources, *replacements))
    editor.canvas.selected_entity_ids = {item.entity_id for item in sources}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    members = tuple(
        member.target.entity_id for member in editor.canvas.pending_associative_arrays[0].members
    )
    assert len(members) == 2
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = set(members)
    choices = iter(replacements)

    def choose(
        _parent: object, _title: object, _label: object, items: list[str], *_args: object
    ) -> tuple[str, bool]:
        replacement = next(choices)
        return next(item for item in items if replacement.entity_id[:8] in item), True

    def cancel(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "", False

    def replacement_count(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return 2, True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", replacement_count)
    before = loaded.document.commands
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", cancel)
    window.act_replace_associative_member.trigger()
    assert loaded.document.commands == before
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", choose)

    def base(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "20,20", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", base)
    window.act_replace_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.replace"
    assert loaded.document.commands[-1].version == 4
    assert all(
        isinstance(entity, CircleEntity)
        for entity, _layer in canvas.background_entities
        if entity.entity_id in members
    )
    actual = {
        entity.entity_id: entity.center_mm
        for entity, _layer in canvas.background_entities
        if entity.entity_id in members and isinstance(entity, CircleEntity)
    }
    assert actual[members[0]] == pytest.approx((8, 0))
    assert actual[members[1]] == pytest.approx((8, 5))
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before), timeout=10000
    )
    assert all(
        isinstance(entity, LineEntity)
        for entity, _layer in canvas.background_entities
        if entity.entity_id in members
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    canvas.selected_entity_ids = {members[0]}
    counts = iter(((1, True), (3, True)))

    def answer_count(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return next(counts)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", answer_count)
    window.act_resize_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert loaded.document.commands[-1].version == 11
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    window.act_reset_associative_overrides.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert all(
        isinstance(entity, LineEntity)
        for entity, _layer in canvas.background_entities
        if entity.entity_id in members
    )


def test_array_member_replacement_menu_and_reset(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycad.core.sketch import CircleEntity

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    replacement = CircleEntity(uuid4().hex, (20, 20), 2)
    assert editor.canvas.replace_draft_entities((source, replacement))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    member = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {member}

    def choose(
        _parent: object, _title: object, _label: object, items: list[str], *_args: object
    ) -> tuple[str, bool]:
        return next(item for item in items if replacement.entity_id[:8] in item), True

    def base(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "20,20", True

    def cancel(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "", False

    def invalid(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "nan,0", True

    before = loaded.document.commands
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", cancel)
    window.act_replace_associative_member.trigger()
    assert loaded.document.commands == before
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", invalid)
    window.act_replace_associative_member.trigger()
    assert loaded.document.commands == before
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", base)
    window.act_replace_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    entity = next(
        entity for entity, _layer in canvas.background_entities if entity.entity_id == member
    )
    assert isinstance(entity, CircleEntity) and entity.center_mm == pytest.approx((18, 4))
    counts = iter(((1, True), (3, True)))

    def answer_count(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return next(counts)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", answer_count)
    window.act_resize_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert loaded.document.commands[-1].version == 8
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    window.act_reset_associative_overrides.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    entity = next(
        entity for entity, _layer in canvas.background_entities if entity.entity_id == member
    )
    assert isinstance(entity, LineEntity)
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert isinstance(
        next(entity for entity, _layer in canvas.background_entities if entity.entity_id == member),
        CircleEntity,
    )


def test_internal_array_member_replacement_uses_new_version(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "3", "8", "AS", "Y", ""):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    members = editor.canvas.pending_associative_arrays[0].members
    first, second = members[0].target.entity_id, members[1].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {second}
    rotation = iter((("90", True), ("26,4", True)))

    def rotate_input(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return next(rotation)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", rotate_input)
    before = loaded.document.commands
    window.act_rotate_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    canvas.selected_entity_ids = {first}

    def choose(
        _parent: object, _title: object, _label: object, items: list[str], *_args: object
    ) -> tuple[str, bool]:
        return next(item for item in items if second[:8] in item), True

    def base(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "26,4", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", base)
    window.act_replace_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert loaded.document.commands[-1].version == 2
    entity = next(
        entity for entity, _layer in canvas.background_entities if entity.entity_id == first
    )
    assert isinstance(entity, LineEntity) and entity.end_mm == pytest.approx((18, 14))
    counts = iter(((1, True), (4, True)))

    def count(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return next(counts)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", count)
    window.act_resize_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 3, timeout=10000
    )
    assert loaded.document.commands[-1].version == 9
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert isinstance(
        next(entity for entity, _layer in canvas.background_entities if entity.entity_id == first),
        LineEntity,
    )


def test_interleaved_array_replacement_uses_new_version_and_reopens(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    sources = (LineEntity(uuid4().hex, (0, 0), (2, 0)), LineEntity(uuid4().hex, (0, 5), (2, 5)))
    assert editor.canvas.replace_draft_entities(sources)
    bar = editor.drawing_command_bar.input
    for source in sources:
        editor.canvas.selected_entity_ids = {source.entity_id}
        for value in ("ARRAYRECT", "", "1", "3", "5", "AS", "Y", ""):
            bar.setText(value)
            QTest.keyClick(bar, Qt.Key.Key_Return)
    first, second = editor.canvas.pending_associative_arrays
    a1, a2 = (member.target.entity_id for member in first.members)
    b1, b2 = (member.target.entity_id for member in second.members)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    desired = [b1]

    def choose(
        _parent: object, _title: object, _label: object, items: list[str], *_args: object
    ) -> tuple[str, bool]:
        return next(item for item in items if desired[0][:8] in item), True

    def base(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return ("5,5" if desired[0] == b1 else "10,0"), True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", choose)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", base)
    before = loaded.document.commands
    current.canvas.selected_entity_ids = {a1}
    window.act_replace_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    desired[0] = a2
    current.canvas.selected_entity_ids = {b2}
    window.act_replace_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert loaded.document.commands[-1].version == 3
    counts = iter(((1, True), (4, True)))

    def count(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return next(counts)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", count)
    window.act_resize_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 3, timeout=10000
    )
    assert loaded.document.commands[-1].version == 10
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.loaded_document() is not loaded, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None and reopened.canvas.associative_arrays_provider is not None
    assert (
        sum(
            m.replacement is not None
            for a in reopened.canvas.associative_arrays_provider()
            for m in a.members
        )
        == 2
    )


def test_saved_array_base_point_menu_updates_and_undoes(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycad.core.associative_array import ArrayBasePoint

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    current.canvas.selected_entity_ids = {source.entity_id}
    before = loaded.document.commands

    def choose_coordinate(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "坐标", True

    def enter_coordinate(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "30,9", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", choose_coordinate)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", enter_coordinate)
    window.act_base_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].version == 3
    assert current.canvas.associative_spacing_grips()[0][2] == pytest.approx((38, 9))
    provider = current.canvas.associative_arrays_provider
    assert provider is not None
    assert provider()[0].base_point == ArrayBasePoint(point_mm=(30, 9))
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and loaded.document.commands == before, timeout=10000)
    assert current.canvas.associative_spacing_grips()[0][2] == pytest.approx((18, 4))

    choices = iter(("源关键点", f"2: {source.entity_id[:8]} end (20, 4)"))

    def choose_key(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return next(choices), True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", choose_key)
    window.act_base_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert current.canvas.associative_spacing_grips()[0][2] == pytest.approx((28, 4))
    key_base = provider()[0].base_point
    assert key_base is not None and key_base.reference is not None

    def choose_default(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "恢复默认", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getItem", choose_default)
    window.act_base_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2, timeout=10000
    )
    assert provider()[0].base_point is None
    assert current.canvas.associative_spacing_grips()[0][2] == pytest.approx((18, 4))


@pytest.mark.parametrize("angle", [0, 90])
def test_array_spacing_grip_drag_previews_commits_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], angle: int
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in (
        "ARRAYRECT",
        "",
        "1",
        "2",
        "8",
        *(("AN", str(angle)) if angle else ()),
        "AS",
        "Y",
        "",
    ):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    target_id = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {source.entity_id}
    before = loaded.document.commands
    grip = canvas.local_to_screen((10, 12) if angle else (18, 4))
    target = canvas.local_to_screen((10, 16) if angle else (22, 4))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=grip)
    QTest.mouseMove(canvas, target)
    assert canvas.array_spacing_drag_active
    assert loaded.document.commands == before
    assert any(entity.entity_id == target_id for entity, _ in canvas.array_spacing_preview)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.update"
    result = next(
        entity for entity, _ in canvas.background_entities if entity.entity_id == target_id
    )
    assert isinstance(result, LineEntity)
    assert result.start_mm == pytest.approx((10, 16) if angle else (22, 4), abs=0.25)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and loaded.document.commands == before, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.loaded_document() is not loaded, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    reloaded = next(
        item for item, _ in reopened.canvas.background_entities if item.entity_id == target_id
    )
    assert isinstance(reloaded, LineEntity)
    assert reloaded.start_mm == pytest.approx((10, 16) if angle else (22, 4), abs=0.25)


@pytest.mark.parametrize(
    "case",
    [
        "escape",
        "stale",
        "draft_changed",
        "count_draft_changed",
        "zero",
        "locked_member",
        "locked_source",
        "perpendicular",
    ],
)
def test_array_spacing_grip_cancel_and_invalid_do_not_write(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], case: str
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    extra = LineEntity(uuid4().hex, (30, 10), (40, 10))
    entities = (source, extra) if case == "locked_source" else (source,)
    assert editor.canvas.replace_draft_entities(entities)
    editor.canvas.selected_entity_ids = {entity.entity_id for entity in entities}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    target_id = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {source.entity_id}
    before = loaded.document.commands
    if case in {"locked_member", "locked_source"}:
        from dataclasses import replace

        locked_id = target_id if case == "locked_member" else extra.entity_id
        canvas.background_entities = tuple(
            (entity, replace(layer, locked=True) if entity.entity_id == locked_id else layer)
            for entity, layer in canvas.background_entities
        )
    grip = (
        canvas.local_to_screen(canvas.associative_count_grips()[0][1])
        if case == "count_draft_changed"
        else canvas.local_to_screen((18, 4))
    )
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=grip)
    assert canvas.array_spacing_drag_active
    if case == "stale":
        provider = canvas.source_revision_provider
        assert provider is not None
        canvas.source_revision_provider = lambda: provider() + 1
    draft = None
    if case in {"draft_changed", "count_draft_changed"}:
        draft = LineEntity(uuid4().hex, (30, 20), (40, 20))
        assert canvas.replace_draft_entities((*canvas.entities, draft))
    destination = canvas.local_to_screen(
        (10, 9) if case == "zero" else (18, 9) if case == "perpendicular" else (22, 4)
    )
    QTest.mouseMove(canvas, destination)
    if case in {"draft_changed", "count_draft_changed"}:
        assert not canvas.array_spacing_drag_active
        assert draft is not None
        assert draft in canvas.entities
    if case in {"locked_member", "locked_source"}:
        assert not canvas.array_spacing_preview and "锁定" in canvas.message
    if case == "escape":
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
    else:
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=destination)
    assert not canvas.array_spacing_drag_active
    assert loaded.document.commands == before


@pytest.mark.parametrize("mode", ["spacing", "move"])
def test_array_spacing_grip_rejects_real_cross_sketch_tangency_in_preview(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], mode: str
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    target_id = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    provider = current.canvas.associative_sketches_provider
    assert provider is not None
    owner = next(
        sketch
        for sketch in provider()
        if any(item.entity_id == target_id for item in sketch.entities)
    )
    circle = CircleEntity(uuid4().hex, (23, 6), 2)
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    loaded.bus.execute("sketch.create", other.to_state_mapping(), confirmed_by="local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(owner.sketch_id, target_id),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    loaded.bus.execute(
        "drawing.tangency.add",
        {"relation": relation.to_mapping(), "revisions": []},
        confirmed_by="local",
    )
    current.set_context_sketches(provider())
    assert current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {source.entity_id}
    before, background = loaded.document.commands, canvas.background_entities
    origin = (18, 4) if mode == "spacing" else (10, 4)
    destination = (22, 4) if mode == "spacing" else (10, 7)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(origin))
    assert canvas.array_spacing_drag_active
    QTest.mouseMove(canvas, canvas.local_to_screen(destination))
    assert not canvas.array_spacing_preview
    assert "对象相切" in canvas.message
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(destination))
    assert not canvas.array_spacing_drag_active
    assert "对象相切" in canvas.message
    assert loaded.document.commands == before and canvas.background_entities == background


def test_array_count_grip_previews_commits_and_replays(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "2", "2", "4", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    array = editor.canvas.pending_associative_arrays[0]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {source.entity_id}
    grips = canvas.associative_count_grips()
    assert len(grips) == 1
    grip = canvas.local_to_screen(grips[0][1])
    target = grip + canvas.local_to_screen((18, 8)) - canvas.local_to_screen((10, 4))
    before = loaded.document.commands
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=grip)
    QTest.mouseMove(canvas, target)
    assert canvas.array_spacing_drag_active and loaded.document.commands == before
    preview_ids = {item.entity_id for item, _ in canvas.array_spacing_preview}
    assert len(preview_ids) == 5
    QTest.mouseMove(
        canvas, target + canvas.local_to_screen((0, 4)) - canvas.local_to_screen((0, 0))
    )
    assert preview_ids.issubset({item.entity_id for item, _ in canvas.array_spacing_preview})
    QTest.mouseMove(canvas, target)
    assert preview_ids == {item.entity_id for item, _ in canvas.array_spacing_preview}
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.resize"
    assert preview_ids.issubset({item.entity_id for item, _ in canvas.background_entities})
    assert {member.target.entity_id for member in array.members}.issubset(
        {item.entity_id for item, _ in canvas.background_entities}
    )
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and loaded.document.commands == before, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.loaded_document() is not loaded, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    assert preview_ids.issubset({item.entity_id for item, _ in reopened.canvas.background_entities})


def test_array_count_grip_enables_single_row_rotated_array(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AN", "90", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {source.entity_id}
    grip = canvas.local_to_screen(canvas.associative_count_grips()[0][1])
    target = grip + canvas.local_to_screen((-8, 8)) - canvas.local_to_screen((0, 0))
    before = loaded.document.commands
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=grip)
    QTest.mouseMove(canvas, target)
    assert len(canvas.array_spacing_preview) == 4
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].version == 2
    mapping = loaded.document.commands[-1].params["array"]
    assert isinstance(mapping, dict)
    assert mapping["rows"] == 2 and mapping["columns"] == 3 and mapping["row_spacing"] == 8


@pytest.mark.parametrize("mode", ["shrink", "invalid", "escape"])
def test_array_count_grip_shrink_cancel_and_invalid(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], mode: str
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "2", "2", "4", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    array = editor.canvas.pending_associative_arrays[0]
    removed = {item.target.entity_id for item in array.members if item.row == 1}
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {source.entity_id}
    grip = canvas.local_to_screen(canvas.associative_count_grips()[0][1])
    shift = (0, -4) if mode == "shrink" else (-8, -4)
    target = grip + canvas.local_to_screen(shift) - canvas.local_to_screen((0, 0))
    before = loaded.document.commands
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=grip)
    QTest.mouseMove(canvas, target)
    if mode == "escape":
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
    else:
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    if mode == "shrink":
        qtbot.waitUntil(
            lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1,
            timeout=10000,
        )
        assert not removed.intersection(item.entity_id for item, _ in canvas.background_entities)
        window.request_undo()
        qtbot.waitUntil(
            lambda: not unit.is_busy and loaded.document.commands == before, timeout=10000
        )
        assert removed.issubset({item.entity_id for item, _ in canvas.background_entities})
    else:
        assert not canvas.array_spacing_drag_active and loaded.document.commands == before


def test_array_count_grip_rejects_removing_tangent_member(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "2", "2", "4", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    array = editor.canvas.pending_associative_arrays[0]
    target_id = next(
        member.target.entity_id
        for member in array.members
        if member.row == 1 and member.column == 1
    )
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    provider = current.canvas.associative_sketches_provider
    assert provider is not None
    owner = next(
        sketch
        for sketch in provider()
        if any(item.entity_id == target_id for item in sketch.entities)
    )
    circle = CircleEntity(uuid4().hex, (23, 10), 2)
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    loaded.bus.execute("sketch.create", other.to_state_mapping(), confirmed_by="local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(owner.sketch_id, target_id),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    loaded.bus.execute(
        "drawing.tangency.add",
        {"relation": relation.to_mapping(), "revisions": []},
        confirmed_by="local",
    )
    current.set_context_sketches(provider())
    assert current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {source.entity_id}
    before, background = loaded.document.commands, canvas.background_entities
    grip = canvas.local_to_screen(canvas.associative_count_grips()[0][1])
    target = grip + canvas.local_to_screen((0, -4)) - canvas.local_to_screen((0, 0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=grip)
    QTest.mouseMove(canvas, target)
    assert not canvas.array_spacing_preview and "对象相切" in canvas.message
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    assert not canvas.array_spacing_drag_active and "对象相切" in canvas.message
    assert loaded.document.commands == before and canvas.background_entities == background


@pytest.mark.parametrize("kind", ["spacing", "count", "move"])
def test_array_spacing_grip_failed_commit_restores_canvas(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    from mycad.core.exceptions import ValidationError

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    params = ("2", "2", "4", "8") if kind == "count" else ("1", "2", "8")
    for value in ("ARRAYRECT", "", *params, "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.set_tool("选择元素")
    canvas = current.canvas
    canvas.selected_entity_ids = {source.entity_id}
    before, background = loaded.document.commands, canvas.background_entities

    def reject(*_args: object, **_kwargs: object) -> object:
        raise ValidationError("模拟阵列约束冲突")

    monkeypatch.setattr(loaded.bus, "execute", reject)
    if kind == "count":
        grip = canvas.local_to_screen(canvas.associative_count_grips()[0][1])
        target = grip + canvas.local_to_screen((8, 4)) - canvas.local_to_screen((0, 0))
    elif kind == "move":
        grip = canvas.local_to_screen(canvas.associative_base_grips()[0][1])
        target = grip + canvas.local_to_screen((3, 2)) - canvas.local_to_screen((0, 0))
    else:
        grip, target = canvas.local_to_screen((18, 4)), canvas.local_to_screen((22, 4))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=grip)
    QTest.mouseMove(canvas, target)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    qtbot.waitUntil(
        lambda: not unit.is_busy and not canvas.array_spacing_drag_active, timeout=10000
    )
    assert "冲突" in canvas.message
    assert loaded.document.commands == before and canvas.background_entities == background
    assert not canvas.array_spacing_preview


def test_rotated_unit_cell_precision_survives_save_reopen_and_source_edit(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    import math

    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in (
        "ARRAYRECT",
        "",
        "2",
        "2",
        "4",
        "5",
        "AN",
        "45",
        "S",
        "U",
        "0,0",
        "10,0",
        "AS",
        "Y",
        "",
    ):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    array = editor.canvas.pending_associative_arrays[0]
    assert array.column_spacing == pytest.approx(10 / math.sqrt(2), abs=1e-12)
    target_id = array.members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not submitted and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    previous = next(
        item for item, _ in current.canvas.background_entities if item.entity_id == target_id
    )
    assert isinstance(previous, LineEntity)
    current.canvas.selected_entity_ids = {source.entity_id}
    current.canvas.begin_transform("move")
    current.canvas.add_coordinate_point((0, 0), exact_point=True)
    current.canvas.add_coordinate_point((1, 0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    moved = next(
        item for item, _ in current.canvas.background_entities if item.entity_id == target_id
    )
    assert isinstance(moved, LineEntity)
    assert moved.start_mm == pytest.approx((previous.start_mm[0] + 1, previous.start_mm[1]))


def test_scale_pending_array_member_is_rejected_without_corrupting_draft(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    array = canvas.pending_associative_arrays[0]
    selected = array.members[0].target.entity_id
    before = tuple(canvas.entities)
    canvas.selected_entity_ids = {selected}
    for value in ("SCALE", "0,0", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert tuple(canvas.entities) == before
    assert canvas.pending_associative_arrays == [array]
    assert "关联阵列" in canvas.message


def test_scale_pending_array_source_regenerates_members_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    array = canvas.pending_associative_arrays[0]
    before = tuple(canvas.entities)
    canvas.selected_entity_ids = {source.entity_id}
    for value in ("SCALE", "0,0", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    target = next(
        item for item in canvas.entities if item.entity_id == array.members[0].target.entity_id
    )
    assert isinstance(target, LineEntity)
    assert target.start_mm == (28, 8) and target.end_mm == (48, 8)
    assert canvas.pending_associative_arrays == [array]
    assert canvas.undo_last_operation()
    assert tuple(canvas.entities) == before and canvas.pending_associative_arrays == [array]
    assert canvas.redo_last_operation()
    unit = window.execution_unit
    assert unit is not None
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    window.act_save.trigger()
    saved_document = window.loaded_document()
    window.act_open.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy and window.loaded_document() is not saved_document)
    current = window.active_sketch_dialog()
    assert current is not None
    reopened = next(
        item
        for item, _layer in current.canvas.background_entities
        if item.entity_id == target.entity_id
    )
    assert reopened == target


def test_scale_saved_array_source_propagates_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    loaded = window.loaded_document()
    assert editor is not None and unit is not None and loaded is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    target_id = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    current = window.active_sketch_dialog()
    assert current is not None
    before = tuple(entity for entity, _layer in current.canvas.background_entities)
    history_count = len(loaded.document.commands)
    current.canvas.selected_entity_ids = {source.entity_id}
    command = current.drawing_command_bar.input
    for value in ("SCALE", "0,0", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) > history_count)
    entities = [entity for entity, _layer in current.canvas.background_entities]
    result = next(entity for entity in entities if entity.entity_id == target_id)
    assert isinstance(result, LineEntity)
    assert result.start_mm == pytest.approx((28, 8))
    assert result.end_mm == pytest.approx((48, 8))
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == history_count)
    assert tuple(entity for entity, _layer in current.canvas.background_entities) == before


def test_scale_pending_array_source_propagates_through_downstream_array(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, _saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    canvas.selected_entity_ids = {source.entity_id}
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    first = canvas.pending_associative_arrays[0].members[0].target.entity_id
    canvas.selected_entity_ids = {first}
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    second = canvas.pending_associative_arrays[1].members[0].target.entity_id
    canvas.selected_entity_ids = {source.entity_id}
    for value in ("SCALE", "0,0", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    items = {item.entity_id: item for item in canvas.entities}
    result = items[second]
    assert isinstance(result, LineEntity)
    assert result.start_mm == (36, 8) and result.end_mm == (56, 8)
    assert canvas.undo_last_operation()
    assert items[second] != next(item for item in canvas.entities if item.entity_id == second)


def test_scale_saved_array_member_rejects_direct_edit(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _saved, _other = reopened_drawing
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    target_id = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    current = window.active_sketch_dialog()
    assert current is not None
    before = loaded.document.commands
    geometry = tuple(item for item, _layer in current.canvas.background_entities)
    current.canvas.selected_entity_ids = {target_id}
    for value in ("SCALE", "0,0", "2"):
        current.drawing_command_bar.input.setText(value)
        QTest.keyClick(current.drawing_command_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: not unit.is_busy and "关联阵列" in current.status_label.text(), timeout=10000
    )
    assert loaded.document.commands == before
    assert tuple(item for item, _layer in current.canvas.background_entities) == geometry


def test_scale_copy_of_pending_array_member_keeps_association(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, _saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert canvas.replace_draft_entities((source,))
    canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    array = canvas.pending_associative_arrays[0]
    before = tuple(canvas.entities)
    canvas.selected_entity_ids = {array.members[0].target.entity_id}
    for value in ("SCALE", "0,0", "C", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert tuple(canvas.entities[:2]) == before and canvas.pending_associative_arrays == [array]
    copied = canvas.entities[-1]
    assert isinstance(copied, LineEntity)
    assert copied.entity_id not in {item.entity_id for item in before}
    assert copied.start_mm == (36, 8) and copied.end_mm == (56, 8)
    assert canvas.undo_last_operation()
    assert tuple(canvas.entities) == before and canvas.pending_associative_arrays == [array]


@pytest.mark.parametrize("include_draft", [False, True])
def test_scale_saved_source_of_pending_array_stages_propagation(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], include_draft: bool
) -> None:
    window, source, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit, loaded = window.execution_unit, window.loaded_document()
    assert editor is not None and unit is not None and loaded is not None
    canvas = editor.canvas
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    target_id = canvas.pending_associative_arrays[0].members[0].target.entity_id
    before = loaded.document.commands
    draft_line = LineEntity(uuid4().hex, (1, 10), (3, 10))
    if include_draft:
        assert canvas.replace_draft_entities((*canvas.entities, draft_line))
    canvas.selected_entity_ids = (
        {source.entity_id, draft_line.entity_id} if include_draft else {source.entity_id}
    )
    for value in ("SCALE", "0,0", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)

    def staged() -> None:
        assert not unit.is_busy and canvas.mixed_move is not None, (
            canvas.message,
            editor.status_label.text(),
            editor.drawing_command_bar.status.text(),
        )

    qtbot.waitUntil(staged, timeout=10000)
    assert loaded.document.commands == before
    target = next(item for item in canvas.entities if item.entity_id == target_id)
    assert isinstance(target, LineEntity)
    assert target.start_mm == (-2, 0) and target.end_mm == (18, 0)
    if include_draft:
        assert LineEntity(draft_line.entity_id, (2, 20), (6, 20)) in canvas.entities
    editor.finish_sketch()
    qtbot.waitUntil(lambda: not unit.is_busy and window.active_sketch_dialog() is not editor)
    assert len(loaded.document.commands) == len(before) + 2
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy and window.loaded_document() is not loaded)
    loaded = window.loaded_document()
    current = window.active_sketch_dialog()
    assert loaded is not None and current is not None
    assert target in {entity for entity, _layer in current.canvas.background_entities}
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == len(before))
    current = window.active_sketch_dialog()
    assert current is not None
    assert source in {entity for entity, _layer in current.canvas.background_entities}
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 2)
    assert target in {entity for entity, _layer in current.canvas.background_entities}


def test_rotated_associative_array_ui_replays_and_reopens(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AN", "90", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.pending_associative_arrays) == 1
    array = editor.canvas.pending_associative_arrays[0]
    assert array.angle_deg == 90
    target_id = array.members[0].target.entity_id
    target = next(item for item in editor.canvas.entities if item.entity_id == target_id)
    assert isinstance(target, LineEntity) and target.start_mm == pytest.approx((10, 12))
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert loaded.document.commands[-1].version == 14
    count = len(loaded.document.commands)
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count - 1, timeout=10000
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == count, timeout=10000
    )
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.loaded_document() is not loaded, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    assert any(item.entity_id == target_id for item, _ in current.canvas.background_entities)


@pytest.mark.parametrize("select_source", [False, True])
def test_remove_associative_array_from_selected_member(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], select_source: bool
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    target_id = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    before = len(loaded.document.commands)
    current.canvas.selected_entity_ids = {source.entity_id if select_source else target_id}
    window.act_remove_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.remove"
    assert any(entity.entity_id == target_id for entity, _ in current.canvas.background_entities)
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before, timeout=10000
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )


@pytest.mark.parametrize("select_source", [False, True])
def test_change_associative_array_angle_from_source_or_member(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
    select_source: bool,
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    target_id = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    current.canvas.selected_entity_ids = {source.entity_id if select_source else target_id}
    before = len(loaded.document.commands)

    def canceled(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "90", False

    def accepted(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "90", True

    def unchanged(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "0.0", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", unchanged)
    window.act_rotate_associative_array.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == before

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", canceled)
    window.act_rotate_associative_array.trigger()
    assert len(loaded.document.commands) == before
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", accepted)
    window.act_rotate_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.update"
    assert loaded.document.commands[-1].version == 2
    target = next(
        item for item, _ in current.canvas.background_entities if item.entity_id == target_id
    )
    assert isinstance(target, LineEntity) and target.start_mm == pytest.approx((10, 12))
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before, timeout=10000
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )


def test_associative_angle_edit_preserves_exact_default_and_rejects_invalid_input(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    angle = "1234567890123.123"
    for value in ("ARRAYRECT", "", "1", "2", "8", "AN", angle, "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    array = editor.canvas.pending_associative_arrays[0]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    current.canvas.selected_entity_ids = {source.entity_id}
    before = loaded.document.commands
    responses = iter((repr(array.angle_deg), "nan", "not-a-number"))

    def input_value(*_args: object, **kwargs: object) -> tuple[str, bool]:
        assert kwargs.get("text") == repr(array.angle_deg)
        return next(responses), True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", input_value)
    for _ in range(3):
        window.act_rotate_associative_array.trigger()
        assert loaded.document.commands == before
    assert "有限" in window.status_command.text()


def test_associative_spacing_edit_preserves_precise_default(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in (
        "ARRAYRECT",
        "",
        "2",
        "2",
        "4",
        "5",
        "AN",
        "45",
        "S",
        "U",
        "0,0",
        "10,0",
        "AS",
        "Y",
        "",
    ):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    array = editor.canvas.pending_associative_arrays[0]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    current.canvas.selected_entity_ids = {source.entity_id}
    before = loaded.document.commands
    defaults = iter((repr(array.row_spacing), repr(array.column_spacing)))

    def same_text(*_args: object, **kwargs: object) -> tuple[str, bool]:
        expected = next(defaults)
        assert kwargs.get("text") == expected
        return expected, True

    def rounded_double(*args: object, **_kwargs: object) -> tuple[float, bool]:
        assert isinstance(args[3], float)
        return round(args[3], 4), True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", same_text)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getDouble", rounded_double)
    window.act_edit_associative_array.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert loaded.document.commands == before
    responses = iter(
        (
            repr(array.row_spacing),
            "nan",
            repr(array.row_spacing - 0.123456789),
            repr(array.column_spacing),
        )
    )

    def new_text(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return next(responses), True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", new_text)
    window.act_edit_associative_array.trigger()
    assert loaded.document.commands == before
    assert "有限" in window.status_command.text()
    window.act_edit_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].params["row_spacing"] == array.row_spacing - 0.123456789
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and loaded.document.commands == before, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.loaded_document() is not loaded, timeout=10000
    )
    reopened = window.loaded_document()
    assert reopened is not None
    assert reopened.document.commands[-1].params["row_spacing"] == array.row_spacing - 0.123456789


@pytest.mark.parametrize("select_source", [False, True])
@pytest.mark.parametrize("angle", [0, 90])
def test_update_associative_array_spacing_from_selected_member(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
    select_source: bool,
    angle: int,
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in (
        "ARRAYRECT",
        "",
        "1",
        "2",
        "8",
        *(("AN", str(angle)) if angle else ()),
        "AS",
        "Y",
        "",
    ):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    target_id = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    current.canvas.selected_entity_ids = {source.entity_id if select_source else target_id}
    before = len(loaded.document.commands)

    def canceled(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "12.0", False

    def accepted(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "12.0", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", canceled)
    window.act_edit_associative_array.trigger()
    assert len(loaded.document.commands) == before
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", accepted)
    window.act_edit_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.update"
    target = next(
        entity for entity, _ in current.canvas.background_entities if entity.entity_id == target_id
    )
    assert isinstance(target, LineEntity)
    assert target.start_mm == pytest.approx((10, 16) if angle else (22, 4))
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before, timeout=10000
    )


@pytest.mark.parametrize("select_source", [False, True])
@pytest.mark.parametrize("angle", [0, 90])
def test_resize_associative_array_from_selected_member(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
    select_source: bool,
    angle: int,
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in (
        "ARRAYRECT",
        "",
        "1",
        "2",
        "8",
        *(("AN", str(angle)) if angle else ()),
        "AS",
        "Y",
        "",
    ):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    target_id = editor.canvas.pending_associative_arrays[0].members[0].target.entity_id
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    current.canvas.selected_entity_ids = {source.entity_id if select_source else target_id}
    values = iter(((1, True), (3, True)))

    def next_value(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return next(values)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", next_value)
    before = len(loaded.document.commands)
    window.act_resize_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.resize"
    assert loaded.document.commands[-1].version == (2 if angle else 1)
    assert any(
        isinstance(entity, LineEntity)
        and entity.start_mm == pytest.approx((10, 20) if angle else (26, 4))
        for entity, _ in current.canvas.background_entities
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == before, timeout=10000
    )


def test_resize_associative_array_new_axis_preserves_precision(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, _saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    current.canvas.selected_entity_ids = {source.entity_id}
    before = loaded.document.commands
    values = iter(((1, True), (2, True), (2, True), (2, True)))

    def next_count(*_args: object, **_kwargs: object) -> tuple[int, bool]:
        return next(values)

    def next_spacing(*_args: object, **kwargs: object) -> tuple[str, bool]:
        assert kwargs.get("text") == "0.0"
        return "0.123456789", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getInt", next_count)
    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", next_spacing)
    window.act_resize_associative_array.trigger()
    assert loaded.document.commands == before
    assert "未变化" in window.status_command.text()
    window.act_resize_associative_array.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    mapping = loaded.document.commands[-1].params["array"]
    assert isinstance(mapping, dict)
    assert mapping["row_spacing"] == 0.123456789


def test_associative_array_shared_source_selection_is_ambiguous(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, _saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    source = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert editor.canvas.replace_draft_entities((source,))
    assert editor.canvas.set_tool("选择元素")
    command = editor.drawing_command_bar.input
    for spacing in ("8", "12"):
        editor.canvas.selected_entity_ids = {source.entity_id}
        for value in ("ARRAYRECT", "", "1", "2", spacing, "AS", "Y", ""):
            command.setText(value)
            QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.pending_associative_arrays) == 2
    members = {
        array.members[0].target.entity_id for array in editor.canvas.pending_associative_arrays
    }
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    assert current.canvas.set_tool("选择元素")
    current.canvas.selected_entity_ids = {source.entity_id}
    before = loaded.document.commands
    assert not current.canvas.associative_spacing_grips()
    for action in (
        window.act_remove_associative_array,
        window.act_edit_associative_array,
        window.act_resize_associative_array,
        window.act_rotate_associative_array,
    ):
        action.trigger()
        assert loaded.document.commands == before
        assert "多个" in window.status_command.text()
    current.canvas.selected_entity_ids = members

    def cancel_input(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "", False

    def invalid_input(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "nan,3", True

    def stale_input(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        current.canvas.selected_entity_ids = {next(iter(members))}
        return "2,3", True

    for input_handler in (cancel_input, invalid_input, stale_input):
        current.canvas.selected_entity_ids = members
        monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", input_handler)
        window.act_offset_associative_member.trigger()
        if unit.is_busy:
            qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
        assert loaded.document.commands == before
    current.canvas.selected_entity_ids = members

    def offset_input(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "2,3", True

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", offset_input)
    window.act_offset_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.batch_override"
    assert current.canvas.associative_arrays_provider is not None
    assert all(
        array.members[0].offset_mm == (2, 3)
        for array in current.canvas.associative_arrays_provider()[-2:]
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before), timeout=10000
    )
    current.canvas.selected_entity_ids = members
    values = iter((("90", True), ("0,0", True)))

    def rotation_input(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return next(values)

    monkeypatch.setattr("PySide6.QtWidgets.QInputDialog.getText", rotation_input)
    window.act_rotate_associative_member.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(loaded.document.commands) == len(before) + 1, timeout=10000
    )
    assert loaded.document.commands[-1].id == "drawing.array.batch_override"
    assert all(
        array.members[0].rotation_deg == 90
        for array in current.canvas.associative_arrays_provider()[-2:]
    )


@pytest.mark.parametrize("edit_preview", [False, True])
def test_arrayrect_command_mixed_sources_saves_and_reopens(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], edit_preview: bool
) -> None:
    window, saved, other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert canvas.replace_draft_entities((draft,))
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    before = loaded.document.commands
    command = editor.drawing_command_bar.input
    for value in ("ARRAYRECT", "", "2", "2", "-4", "8"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [draft] and len(list(canvas.transform_preview_entities)) == 6
    if edit_preview:
        for value in ("R", "3", "-6"):
            command.setText(value)
            QTest.keyClick(command, Qt.Key.Key_Return)
        assert len(canvas.transform_preview_entities) == 10
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert (
        len(canvas.entities) == (11 if edit_preview else 7) and loaded.document.commands == before
    )
    window.request_undo()
    assert canvas.entities == [draft]
    window.request_redo()
    expected = tuple(canvas.entities)
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not submitted and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    actual = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert all(actual[entity.entity_id] == entity for entity in expected)
    assert actual[saved.entity_id] == saved and actual[other.entity_id] == other


def test_rectangular_array_saved_and_draft_roundtrips(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert canvas.replace_draft_entities((draft,))
    editor.tool_buttons["选择元素"].click()
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.changed.emit()
    editor.array_rows_field.setValue(2)
    editor.array_columns_field.setValue(3)
    editor.delta_u_field.setValue(8)
    editor.delta_v_field.setValue(-5)
    before = loaded.document.commands
    editor.transform_buttons["rectangular_array"].click()
    assert loaded.document.commands == before
    assert len(canvas.entities) == 11
    assert tuple(entity for entity, _ in canvas.background_entities) == (saved, other)
    assert len({entity.entity_id for entity in canvas.entities}) == 11
    window.request_undo()
    assert canvas.entities == [draft]
    window.request_redo()
    expected = tuple(canvas.entities)
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not submitted and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    actual = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert all(actual[entity.entity_id] == entity for entity in expected)
    assert actual[saved.entity_id] == saved and actual[other.entity_id] == other


@pytest.mark.parametrize("operation", ["linear_array", "circular_array"])
def test_array_saved_and_draft_creates_replayable_copies(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], operation: str
) -> None:
    window, saved, other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10.0, 4.0), (20.0, 4.0))
    canvas.replace_draft_entities((line,))
    editor.tool_buttons["选择元素"].click()
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    canvas.changed.emit()
    editor.count_field.setValue(2)
    editor.delta_u_field.setValue(0.0)
    editor.delta_v_field.setValue(5.0)
    editor.pattern_angle_field.setValue(180.0)
    before = loaded.document.commands
    editor.transform_buttons[operation].click()
    assert loaded.document.commands == before
    assert tuple(e for e, _ in canvas.background_entities) == (saved, other)
    assert len(canvas.entities) == 3
    copies = [entity for entity in canvas.entities if entity.entity_id != line.entity_id]
    assert len({entity.entity_id for entity in copies}) == 2
    assert all(isinstance(entity, LineEntity) for entity in copies)
    centers = [
        ((entity.start_mm[0] + entity.end_mm[0]) / 2, (entity.start_mm[1] + entity.end_mm[1]) / 2)
        for entity in copies
        if isinstance(entity, LineEntity)
    ]
    expected_centers = (
        [(0.0, 5.0), (15.0, 9.0)] if operation == "linear_array" else [(0.0, 0.0), (-15.0, -4.0)]
    )
    for actual_center, expected_center in zip(
        sorted(centers), sorted(expected_centers), strict=True
    ):
        assert actual_center == pytest.approx(expected_center, abs=1e-8)
    window.request_undo()
    assert canvas.entities == [line]
    window.request_redo()
    expected = tuple(canvas.entities)
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not submitted and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    actual = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert all(actual[entity.entity_id] == entity for entity in expected)
    assert actual[saved.entity_id] == saved and actual[other.entity_id] == other


@pytest.mark.parametrize("operation", ["linear_array", "rectangular_array", "circular_array"])
def test_array_saved_invalid_parameters_preserve_mixed_selection(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], operation: str
) -> None:
    window, saved, other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (10.0, 4.0), (20.0, 4.0))
    canvas.replace_draft_entities((draft,))
    editor.tool_buttons["选择元素"].click()
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.changed.emit()
    editor.delta_u_field.setValue(0)
    editor.delta_v_field.setValue(0)
    editor.pattern_angle_field.setValue(0)
    before = loaded.document.commands
    editor.transform_buttons[operation].click()
    assert canvas.entities == [draft]
    assert tuple(entity for entity, _layer in canvas.background_entities) == (saved, other)
    assert canvas.selected_entity_ids == {saved.entity_id, draft.entity_id}
    assert loaded.document.commands == before
    expected = {"linear_array": "步距", "rectangular_array": "间距", "circular_array": "角度"}
    assert expected[operation] in editor.status_label.text()


def test_delete_saved_object_can_be_undone(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, other = reopened_drawing
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    canvas = draft.canvas
    draft.tool_buttons["选择元素"].click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    assert canvas.selected_entity_ids == {saved.entity_id}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and {entity.entity_id for entity, _ in canvas.background_entities} == {other.entity_id}
        ),
        timeout=10000,
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and {entity.entity_id for entity, _ in canvas.background_entities}
            == {saved.entity_id, other.entity_id}
        ),
        timeout=10000,
    )
    window.request_redo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and {entity.entity_id for entity, _ in canvas.background_entities} == {other.entity_id}
        ),
        timeout=10000,
    )
    window.act_save.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not draft and not unit.is_busy,
        timeout=10000,
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    assert {entity.entity_id for entity, _ in reopened.canvas.background_entities} == {
        other.entity_id
    }
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and {entity.entity_id for entity, _ in reopened.canvas.background_entities}
            == {saved.entity_id, other.entity_id}
        ),
        timeout=10000,
    )


def test_delete_all_saved_entities_and_undo(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, first, second = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    editor.canvas.selected_entity_ids = {first.entity_id, second.entity_id}
    assert editor.canvas.delete_selected()
    qtbot.waitUntil(
        lambda: not unit.is_busy and not editor.canvas.background_entities, timeout=10000
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(editor.canvas.background_entities) == 2, timeout=10000
    )


def test_erase_command_deletes_saved_object_and_can_undo(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    bar = editor.drawing_command_bar
    bar.input.setText("ERASE")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and {entity.entity_id for entity, _ in canvas.background_entities} == {other.entity_id}
        ),
        timeout=10000,
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: not unit.is_busy and len(canvas.background_entities) == 2, timeout=10000
    )


def test_delete_mixed_selection_is_atomic_and_saved(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    draft = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert draft is not None and loaded is not None
    new_line = LineEntity(uuid4().hex, (10.0, -10.0), (20.0, -10.0))
    canvas = draft.canvas
    canvas.replace_draft_entities((new_line,))
    canvas.selected_entity_ids = {saved.entity_id, new_line.entity_id}
    original = loaded.document.commands
    unit = window.execution_unit
    assert unit is not None
    editor_bar = draft.drawing_command_bar
    editor_bar.input.setText("ERASE")
    QTest.keyClick(editor_bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy and canvas.mixed_move is not None, timeout=10000)
    assert not canvas.entities
    assert saved.entity_id not in {e.entity_id for e, _layer in canvas.background_entities}
    assert loaded.document.commands == original
    assert draft.finish_button.isEnabled()
    assert all(field.isReadOnly() for field in draft.origin_fields.values())
    plane = draft.plane_combo.currentText()
    draft.plane_combo.setCurrentText("YZ")
    assert draft.plane_combo.currentText() == plane
    window.request_undo()
    assert canvas.entities == [new_line]
    assert not any(field.isReadOnly() for field in draft.origin_fields.values())
    assert saved.entity_id in {e.entity_id for e, _layer in canvas.background_entities}
    window.request_redo()
    assert not canvas.entities
    assert all(field.isReadOnly() for field in draft.origin_fields.values())
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not draft and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    assert saved.entity_id not in {
        e.entity_id for e, _layer in submitted.canvas.background_entities
    }
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not submitted and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    restored = {e.entity_id for e, _layer in submitted.canvas.background_entities}
    assert {saved.entity_id, new_line.entity_id}.issubset(restored)


def test_delete_mixed_selection_removes_and_restores_draft_constraint(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    loaded = window.loaded_document()
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    canvas = editor.canvas
    canvas.replace_draft_entities((line,))
    relation = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 10.0, "mm"
    )
    canvas.constraints = [relation]
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    commands = loaded.document.commands
    assert canvas.delete_selected()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.mixed_move is not None, editor.status_label.text()
    assert not canvas.constraints
    window.request_undo()
    assert canvas.entities == [line]
    assert canvas.constraints == [relation]
    window.request_redo()
    assert not canvas.constraints
    editor.cancel_button.click()
    assert loaded.document.commands == commands


def test_delete_mixed_selection_rejects_locked_dependent_dimension(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer

    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    canvas = editor.canvas
    canvas.replace_draft_entities((line,))
    layers = editor.layer_table.add(SketchLayer("locked-dimension", locked=True))
    editor.set_document_layers(layers, editor.dimension_layer)
    relation = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10.0,
        "mm",
        layer_name="locked-dimension",
    )
    canvas.constraints = [relation]
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    commands = loaded.document.commands
    assert canvas.delete_selected()
    assert "锁定" in editor.status_label.text()
    assert canvas.entities == [line] and canvas.constraints == [relation]
    assert canvas.mixed_move is None and loaded.document.commands == commands


def test_mixed_delete_removes_saved_dimension_until_undo(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window, _first, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    saved = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(saved.entity_id, "geometry"),), 10.0, "mm"
    )
    editor.canvas.replace_draft_entities((saved,))
    editor.canvas.constraints = [dimension]
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    assert dimension.constraint_id in {c.constraint_id for c in canvas.visible_dimensions()}
    draft = LineEntity(uuid4().hex, (10.0, -10.0), (20.0, -10.0))
    canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    assert canvas.delete_selected()
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert dimension.constraint_id not in {c.constraint_id for c in canvas.visible_dimensions()}
    assert dimension.constraint_id not in {
        c.constraint_id for sketch in editor.dimension_sources() for c in sketch.constraints
    }
    window.request_undo()
    assert dimension.constraint_id in {c.constraint_id for c in canvas.visible_dimensions()}
    assert dimension.constraint_id in {
        c.constraint_id for sketch in editor.dimension_sources() for c in sketch.constraints
    }
    window.request_redo()
    loaded = window.loaded_document()
    assert loaded is not None
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    extra = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (LineEntity(uuid4().hex, (100.0, 0.0), (110.0, 0.0)),),
    )
    loaded.bus.execute("sketch.create", extra.to_state_mapping(), confirmed_by="local")
    editor.finish_button.click()
    qtbot.waitUntil(lambda: "提交失败" in editor.status_label.text(), timeout=10000)
    assert not canvas.mixed_move_is_valid
    assert dimension.constraint_id in {c.constraint_id for c in canvas.visible_dimensions()}
    assert dimension.constraint_id in {
        c.constraint_id for sketch in editor.dimension_sources() for c in sketch.constraints
    }


def test_edit_after_mixed_delete_keeps_separate_undo_after_reopen(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    added = LineEntity(uuid4().hex, (30.0, 10.0), (40.0, 10.0))
    canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    assert canvas.delete_selected()
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    canvas.replace_draft_entities((added,))
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not previous and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    after_first = {e.entity_id for e, _layer in reopened.canvas.background_entities}
    assert not {added.entity_id, saved.entity_id, draft.entity_id} & after_first
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    after_second = {e.entity_id for e, _layer in reopened.canvas.background_entities}
    assert {saved.entity_id, draft.entity_id}.issubset(after_second)


def test_stale_mixed_delete_cannot_commit_and_can_be_undone(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    draft = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    canvas = editor.canvas
    canvas.replace_draft_entities((draft,))
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    assert canvas.delete_selected()
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    extra = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (LineEntity(uuid4().hex, (100.0, 0.0), (110.0, 0.0)),),
    )
    loaded.bus.execute("sketch.create", extra.to_state_mapping(), confirmed_by="local")
    before = loaded.document.commands
    assert editor.finish_button.isEnabled()
    editor.finish_button.click()
    qtbot.waitUntil(lambda: "提交失败" in editor.status_label.text(), timeout=10000)
    assert window.active_sketch_dialog() is editor
    assert loaded.document.commands == before and canvas.entities == []
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.entities == [draft]
    visible = {entity.entity_id for entity, _layer in canvas.background_entities}
    assert {saved.entity_id, extra.entities[0].entity_id}.issubset(visible)


@pytest.mark.parametrize("keep", [False, True])
@pytest.mark.parametrize("numeric", [False, True])
def test_mirror_saved_object_preserves_choice_and_reopens(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    keep: bool,
    numeric: bool,
) -> None:
    window, saved, other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    editor.mirror_keep_source_check.setChecked(keep)
    if numeric:
        editor.center_v_field.setValue(10.0)
        editor.numeric_mirror_button.click()
    else:
        editor.transform_buttons["mirror"].click()
        canvas.add_coordinate_point((0.0, 10.0), exact_point=True)
        canvas.add_coordinate_point((10.0, 10.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    if keep:
        assert len(canvas.entities) == 1
        mirrored = canvas.entities[0]
        assert mirrored.entity_id != saved.entity_id
        assert {entity.entity_id: entity for entity, _ in canvas.background_entities}[
            saved.entity_id
        ] == saved
    else:
        mirrored = {entity.entity_id: entity for entity, _ in canvas.background_entities}[
            saved.entity_id
        ]
        assert mirrored.entity_id == saved.entity_id
    assert isinstance(mirrored, LineEntity)
    assert mirrored.start_mm == pytest.approx((-5.0, 20.0))
    assert mirrored.end_mm == pytest.approx((5.0, 20.0))
    assert {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        other.entity_id
    ] == other
    window.act_save.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    saved_editor = window.active_sketch_dialog()
    assert saved_editor is not None
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not saved_editor and not unit.is_busy,
        timeout=10000,
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    entities = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert entities[mirrored.entity_id] == mirrored
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    entities = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert entities[saved.entity_id] == saved
    if keep:
        assert mirrored.entity_id not in entities


def test_mirror_saved_and_draft_without_source_is_one_staged_operation(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10.0, 4.0), (20.0, 4.0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    canvas.begin_transform("mirror", keep_source=False)
    canvas.add_coordinate_point((0.0, 10.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 10.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    mirrored = canvas.entities[0]
    assert isinstance(mirrored, LineEntity)
    assert mirrored.start_mm == pytest.approx((10.0, 16.0))
    window.request_undo()
    assert canvas.entities == [line]
    assert {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        saved.entity_id
    ] == saved
    window.request_redo()
    assert canvas.entities == [mirrored]
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    restored = {entity.entity_id: entity for entity, _ in submitted.canvas.background_entities}
    assert restored[saved.entity_id] == saved
    assert restored[line.entity_id] == line


def test_mirror_saved_and_draft_with_source_creates_only_new_draft_copies(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10.0, 4.0), (20.0, 4.0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    original_commands = loaded.document.commands
    canvas.begin_transform("mirror", keep_source=True)
    canvas.add_coordinate_point((0.0, 10.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 10.0), exact_point=True)
    assert loaded.document.commands == original_commands
    assert line in canvas.entities
    assert {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        saved.entity_id
    ] == saved
    copies = [entity for entity in canvas.entities if entity.entity_id != line.entity_id]
    assert len(copies) == 2
    lines = [entity for entity in copies if isinstance(entity, LineEntity)]
    assert len(lines) == 2
    assert {entity.start_mm for entity in lines} == {(-5.0, 20.0), (10.0, 16.0)}
    window.request_undo()
    assert canvas.entities == [line]
    window.request_redo()
    assert all(entity in canvas.entities for entity in copies)


def test_mirror_saved_object_uses_current_workplane_origin(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    editor.origin_fields["Y"].setValue(5.0)
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("mirror", keep_source=False)
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 0.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    mirrored = {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        saved.entity_id
    ]
    assert isinstance(mirrored, LineEntity)
    assert mirrored.start_mm == pytest.approx((-5.0, 5.0))
    assert mirrored.end_mm == pytest.approx((5.0, 5.0))


def test_mirror_rejects_degenerate_axis_without_changing_sources(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    before = loaded.document.commands
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("mirror", keep_source=False)
    canvas.add_coordinate_point((0.0, 1.0), exact_point=True)
    canvas.add_coordinate_point((0.0, 1.0), exact_point=True)
    assert canvas.active_transform == "mirror"
    assert loaded.document.commands == before
    assert {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        saved.entity_id
    ] == saved


def test_cancel_saved_mirror_keeps_selection_and_history(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    before = loaded.document.commands
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("mirror", keep_source=False)
    canvas.add_coordinate_point((0.0, 10.0), exact_point=True)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.active_transform is None
    assert canvas.selected_entity_ids == {saved.entity_id}
    assert loaded.document.commands == before
    assert not loaded.document.is_dirty


def test_mirror_on_own_axis_does_not_append_a_document_revision(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    before = loaded.document.commands
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("mirror", keep_source=False)
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 0.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert loaded.document.commands == before
    assert not loaded.document.is_dirty


def test_mixed_mirror_allows_unchanged_saved_entity_and_mirrors_draft(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10.0, 4.0), (20.0, 4.0))
    canvas.replace_draft_entities((line,))
    before = loaded.document.commands
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    canvas.begin_transform("mirror", keep_source=False)
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 0.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.entities == [LineEntity(line.entity_id, (10.0, -4.0), (20.0, -4.0))]
    assert loaded.document.commands == before
    window.request_undo()
    assert canvas.entities == [line]


@pytest.mark.parametrize("method", ["pointer", "angle", "numeric", "reference"])
def test_rotate_saved_object_is_replayable_and_undoable(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], method: str
) -> None:
    window, saved, other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    if method == "numeric":
        editor.center_u_field.setValue(0.0)
        editor.center_v_field.setValue(0.0)
        editor.angle_field.setValue(90.0)
        editor.numeric_rotate_button.click()
    else:
        canvas.begin_transform("rotate", reference_rotation=method == "reference")
        canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
        if method == "angle":
            assert canvas.apply_rotation_angle(90.0)
        elif method == "reference":
            canvas.add_coordinate_point((0.0, 10.0), exact_point=True)
            canvas.add_coordinate_point((-10.0, 0.0), exact_point=True)
        else:
            canvas.add_coordinate_point((0.0, 10.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    rotated = {entity.entity_id: entity for entity, _ in canvas.background_entities}
    line = rotated[saved.entity_id]
    assert isinstance(line, LineEntity)
    assert line.start_mm == pytest.approx((0.0, -5.0))
    assert line.end_mm == pytest.approx((0.0, 5.0))
    assert rotated[other.entity_id] == other
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        saved.entity_id
    ] == saved
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        saved.entity_id
    ] == line
    if method == "pointer":
        window.act_save.trigger()
        window.act_open.trigger()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
        )
        reopened = window.active_sketch_dialog()
        assert reopened is not None
        assert {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}[
            saved.entity_id
        ] == line


def test_rotate_saved_and_draft_together_is_one_staged_operation(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10.0, 0.0), (20.0, 0.0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((0.0, 10.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].start_mm == pytest.approx((0.0, 10.0))
    window.request_undo()
    assert canvas.entities == [line]
    assert {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        saved.entity_id
    ] == saved
    window.request_redo()
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].start_mm == pytest.approx((0.0, 10.0))
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    restored = {entity.entity_id: entity for entity, _ in submitted.canvas.background_entities}
    assert restored[saved.entity_id] == saved
    assert restored[line.entity_id] == line


def test_rotate_saved_object_uses_current_workplane_origin(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    editor.origin_fields["X"].setValue(10.0)
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((0.0, 10.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    rotated = {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        saved.entity_id
    ]
    assert isinstance(rotated, LineEntity)
    assert rotated.start_mm == pytest.approx((0.0, -15.0))
    assert rotated.end_mm == pytest.approx((0.0, -5.0))


def test_saved_numeric_rotate_updates_command_default(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    editor.angle_field.setValue(90)
    editor.numeric_rotate_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.rotation_default_angle == 90
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    result = {entity.entity_id: entity for entity, _ in canvas.background_entities}[saved.entity_id]
    assert isinstance(result, LineEntity)
    assert result.start_mm == pytest.approx((5.0, 0.0))
    assert result.end_mm == pytest.approx((-5.0, 0.0))


def test_saved_rotate_accepts_last_angle_as_default(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    assert canvas.apply_rotation_angle(90.0)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    result = {entity.entity_id: entity for entity, _ in canvas.background_entities}[saved.entity_id]
    assert isinstance(result, LineEntity)
    assert result.start_mm == pytest.approx((5.0, 0.0))
    assert result.end_mm == pytest.approx((-5.0, 0.0))


def test_zero_rotation_does_not_append_a_document_revision(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    before = loaded.document.commands
    editor.canvas.selected_entity_ids = {saved.entity_id}
    editor.angle_field.setValue(0.0)
    editor.numeric_rotate_button.click()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert loaded.document.commands == before
    assert not loaded.document.is_dirty


def test_rotate_mixed_selection_when_draft_circle_is_rotation_invariant(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch import CircleEntity

    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    circle = CircleEntity(uuid4().hex, (0.0, 0.0), 3.0)
    canvas.replace_draft_entities((circle,))
    canvas.selected_entity_ids = {saved.entity_id, circle.entity_id}
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((0.0, 10.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.entities == [circle]
    rotated = {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        saved.entity_id
    ]
    assert isinstance(rotated, LineEntity)
    assert rotated.start_mm == pytest.approx((0.0, -5.0))
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    restored = {entity.entity_id: entity for entity, _ in submitted.canvas.background_entities}
    assert restored[saved.entity_id] == saved
    assert restored[circle.entity_id] == circle


def test_mixed_move_then_rotation_keeps_separate_undo_steps(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10.0, 0.0), (20.0, 0.0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((2.0, 3.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    moved = LineEntity(line.entity_id, (12.0, 3.0), (22.0, 3.0))
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((0.0, 10.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].start_mm == pytest.approx((-3.0, 12.0))
    window.request_undo()
    assert canvas.entities == [moved]
    window.request_undo()
    assert canvas.entities == [line]
    window.request_redo()
    assert canvas.entities == [moved]


@pytest.mark.parametrize("numeric", [False, True])
def test_copy_saved_and_draft_objects_preserves_sources_and_reopens(
    qtbot: QtBot,
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
    numeric: bool,
) -> None:
    window, saved, other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    canvas.replace_draft_entities((draft,))
    commands_before = loaded.document.commands
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    if numeric:
        editor.delta_u_field.setValue(10.0)
        editor.delta_v_field.setValue(20.0)
        editor.numeric_copy_button.click()
    else:
        editor.transform_buttons["copy"].click()
        canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
        canvas.add_coordinate_point((10.0, 20.0), exact_point=True)
        QTest.keyClick(canvas, Qt.Key.Key_Return)

    assert loaded.document.commands == commands_before
    assert tuple(entity for entity, _layer in canvas.background_entities) == (saved, other)
    assert draft in canvas.entities
    copies = [entity for entity in canvas.entities if entity.entity_id != draft.entity_id]
    assert len(copies) == 2
    lines = [entity for entity in copies if isinstance(entity, LineEntity)]
    assert len(lines) == 2
    assert {(entity.start_mm, entity.end_mm) for entity in lines} == {
        ((5.0, 20.0), (15.0, 20.0)),
        ((20.0, 30.0), (30.0, 30.0)),
    }
    assert len({saved.entity_id, draft.entity_id, *(entity.entity_id for entity in copies)}) == 4

    window.request_undo()
    assert canvas.entities == [draft]
    window.request_redo()
    assert all(entity in canvas.entities for entity in copies)

    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not submitted and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    saved_entities = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert saved_entities[saved.entity_id] == saved
    assert saved_entities[draft.entity_id] == draft
    assert all(saved_entities[entity.entity_id] == entity for entity in copies)


def test_copy_repeats_from_original_saved_and_draft_selection(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    draft = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    canvas.replace_draft_entities((draft,))
    original = loaded.document.commands
    canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 0.0), exact_point=True)
    assert canvas.active_transform == "copy"
    assert canvas.selected_entity_ids == {saved.entity_id, draft.entity_id}
    canvas.add_coordinate_point((20.0, 0.0), exact_point=True)
    assert canvas.active_transform == "copy"
    assert len(canvas.entities) == 5
    lines = [entity for entity in canvas.entities if isinstance(entity, LineEntity)]
    assert {entity.start_mm for entity in lines} == {
        (10.0, 10.0),
        (5.0, 0.0),
        (20.0, 10.0),
        (15.0, 0.0),
        (30.0, 10.0),
    }
    assert loaded.document.commands == original
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas.active_transform is None
    window.request_undo()
    assert len(canvas.entities) == 3
    window.request_redo()
    assert len(canvas.entities) == 5
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not submitted and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    saved_lines = [
        entity
        for entity, _ in reopened.canvas.background_entities
        if isinstance(entity, LineEntity)
    ]
    assert {(entity.start_mm, entity.end_mm) for entity in lines}.issubset(
        {(entity.start_mm, entity.end_mm) for entity in saved_lines}
    )


def test_copy_command_bar_repeats_and_empty_enter_finishes(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    bar = editor.drawing_command_bar
    for text in ("COPY", "0,0", "@10,0", "@10,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform == "copy"
    lines = [entity for entity in canvas.entities if isinstance(entity, LineEntity)]
    assert {line.start_mm for line in lines} == {(5.0, 0.0), (15.0, 0.0)}
    bar.input.clear()
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform is None
    assert len(canvas.entities) == 2


@pytest.mark.parametrize("entry", ["canvas", "command"])
def test_copy_first_point_can_be_used_as_displacement(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], entry: str
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    if entry == "command":
        bar = editor.drawing_command_bar
        for text in ("COPY", "2,3", ""):
            bar.input.setText(text)
            QTest.keyClick(bar.input, Qt.Key.Key_Return)
    else:
        canvas.begin_transform("copy")
        canvas.add_coordinate_point((2.0, 3.0), exact_point=True)
        QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1
    copied = canvas.entities[0]
    assert isinstance(copied, LineEntity)
    assert copied.start_mm == pytest.approx((-3.0, 3.0))
    assert copied.end_mm == pytest.approx((7.0, 3.0))
    assert canvas.active_transform == "copy"
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas.active_transform is None


def test_copy_zero_default_displacement_keeps_command_active(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas.active_transform == "copy"
    assert canvas.entities == []
    canvas.add_coordinate_point((10.0, 0.0), exact_point=True)
    assert len(canvas.entities) == 1


def test_copymode_single_persists_after_draft_commit_and_new_window(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    commands_before = loaded.document.commands
    bar = editor.drawing_command_bar
    for text in ("COPYMODE", "2"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.copy_mode == 0
    assert loaded.document.commands == commands_before
    bar.input.setText("1")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.copy_mode == 1
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 0.0), exact_point=True)
    assert canvas.active_transform is None
    assert len(canvas.entities) == 1
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    replacement = window.active_sketch_dialog()
    assert replacement is not None and replacement.canvas.copy_mode == 1

    another = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(another)
    another.act_new_drawing.trigger()
    second_editor = another.active_sketch_dialog()
    assert second_editor is not None and second_editor.canvas.copy_mode == 1


def test_copymode_follows_application_preference_when_switching_documents(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=build_app(discoverers=()), document_session=DocumentSession())
    qtbot.addWidget(window)
    first = window.new_session_document("sketch")
    first_editor = window.active_sketch_dialog()
    assert first_editor is not None
    second = window.new_session_document("sketch")
    second_editor = window.active_sketch_dialog()
    assert second_editor is not None and second_editor is not first_editor
    window.activate_session_document(first.loaded.document.document_id)
    assert window.active_sketch_dialog() is first_editor
    bar = first_editor.drawing_command_bar
    for text in ("COPYMODE", "1"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    window.activate_session_document(second.loaded.document.document_id)
    assert window.active_sketch_dialog() is second_editor
    assert second_editor.canvas.copy_mode == 1
    for text in ("COPYMODE", "0"):
        bar = second_editor.drawing_command_bar
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    window.activate_session_document(first.loaded.document.document_id)
    assert window.active_sketch_dialog() is first_editor
    assert first_editor.canvas.copy_mode == 0


def test_copymode_cancel_and_active_gesture_do_not_change_preference(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    bar = editor.drawing_command_bar
    bar.input.setText("COPYMODE")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    bar.input.setText("1")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.copy_mode == 0
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    bar.input.setText("COPYMODE")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.copy_mode == 0
    assert canvas.active_transform == "copy"
    assert "完成或取消" in bar.status.text()


def test_copymode_single_first_point_displacement_finishes_copy(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    bar = editor.drawing_command_bar
    for text in ("COPYMODE", "1"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    canvas.selected_entity_ids = {saved.entity_id}
    for text in ("COPY", "2,3", ""):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform is None
    assert len(canvas.entities) == 1
    line = canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == pytest.approx((-3.0, 3.0))


def test_copy_multiple_option_overrides_single_mode_only_for_current_command(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    bar = editor.drawing_command_bar
    for text in ("COPYMODE", "1"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    canvas.selected_entity_ids = {saved.entity_id}
    for text in ("COPY", "M", "0,0", "10,0", "20,0", ""):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform is None
    assert len(canvas.entities) == 2
    assert canvas.copy_mode == 1
    canvas.selected_entity_ids = {saved.entity_id}
    for text in ("COPY", "0,0", "10,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform is None
    assert len(canvas.entities) == 3


def test_copy_mode_option_changes_persistent_mode(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    bar = editor.drawing_command_bar
    canvas.selected_entity_ids = {saved.entity_id}
    for text in ("COPY", "MO", "S", "0,0", "10,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.copy_mode == 1
    assert canvas.active_transform is None
    assert len(canvas.entities) == 1
    canvas.selected_entity_ids = {saved.entity_id}
    for text in ("COPY", "MODE", "invalid"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.copy_mode == 1
    assert canvas.active_transform == "copy"
    for text in ("M", "0,0", "10,0", "20,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.copy_mode == 0
    assert canvas.active_transform == "copy"
    assert len(canvas.entities) == 3
    bar.input.clear()
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform is None


def test_copy_command_undo_restores_previous_relative_point_and_keeps_session(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    bar = editor.drawing_command_bar
    for text in ("COPY", "0,0", "@10,0", "@10,0", "U", "@10,5"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.active_transform == "copy"
    lines = [entity for entity in canvas.entities if isinstance(entity, LineEntity)]
    assert {line.start_mm for line in lines} == {(5.0, 0.0), (15.0, 5.0)}
    assert canvas.selected_entity_ids == {saved.entity_id}
    bar.input.setText("U")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("U")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    bar.input.setText("U")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.entities == []
    assert canvas.active_transform == "copy"
    assert canvas.selected_entity_ids == {saved.entity_id}


def test_copy_undo_refuses_to_cross_an_intervening_draft_change(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 0.0), exact_point=True)
    extra = LineEntity(uuid4().hex, (30.0, 2.0), (40.0, 2.0))
    canvas.replace_draft_entities((*canvas.entities, extra))
    before = tuple(canvas.entities)
    QTest.keyClick(canvas, Qt.Key.Key_U)
    assert tuple(canvas.entities) == before
    assert canvas.active_transform == "copy"
    assert "历史" in canvas.message


@pytest.mark.parametrize("finish", ["escape", "right_click"])
def test_copy_finish_keeps_already_placed_duplicates(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], finish: str
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 0.0), exact_point=True)
    copied = tuple(canvas.entities)
    if finish == "escape":
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
    else:
        QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
    assert canvas.active_transform is None
    assert tuple(canvas.entities) == copied
    assert len(copied) == 1


def test_copy_saved_object_alone_can_be_undone_after_reopen(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    assert canvas.cancel_transform()
    assert canvas.entities == []
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 20.0), exact_point=True)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1
    copied_id = canvas.entities[0].entity_id
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    submitted = window.active_sketch_dialog()
    assert submitted is not None
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not submitted and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    assert copied_id in {entity.entity_id for entity, _ in reopened.canvas.background_entities}
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    remaining = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert remaining[saved.entity_id] == saved
    assert copied_id not in remaining
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert copied_id in {entity.entity_id for entity, _ in reopened.canvas.background_entities}


def test_move_saved_object_is_replayable_and_undoable(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, inside, crosses = reopened_drawing
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    canvas = draft.canvas
    canvas.set_snapping_enabled(False)
    draft.tool_buttons["选择元素"].click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    draft.transform_buttons["move"].click()
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 20.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    moved = tuple(entity for entity, _layer in canvas.background_entities)
    assert moved == (LineEntity(inside.entity_id, (5.0, 20.0), (15.0, 20.0)), crosses)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert tuple(entity for entity, _layer in canvas.background_entities) == (inside, crosses)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert tuple(entity for entity, _layer in canvas.background_entities) == moved
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not draft and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    assert tuple(entity for entity, _layer in reopened.canvas.background_entities) == moved


def test_pending_move_does_not_undo_or_redo_saved_geometry(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, inside, crosses = reopened_drawing
    draft = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert draft is not None and loaded is not None and unit is not None
    canvas = draft.canvas
    draft.tool_buttons["选择元素"].click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    draft.transform_buttons["move"].click()
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    assert canvas.active_transform == "move"
    commands = loaded.document.commands
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert loaded.document.commands == commands
    assert tuple(entity for entity, _layer in canvas.background_entities) == (inside, crosses)
    QTest.keyClick(canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert loaded.document.commands == commands
    window.request_redo()
    assert loaded.document.commands == commands
    assert canvas.active_transform == "move"
    assert "取消" in window.status_command.text()
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not canvas.background_entities, timeout=10000)


@pytest.mark.parametrize("operation", ["undo", "redo"])
def test_busy_worker_prevents_draft_history_changes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], operation: str
) -> None:
    window, _, _ = reopened_drawing
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    canvas = draft.canvas
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    canvas.replace_draft_entities((line,))
    if operation == "redo":
        assert canvas.undo_last_operation()
    before = tuple(canvas.entities)
    position = canvas.history_position
    entered, release = Event(), Event()

    def blocking_work() -> None:
        entered.set()
        assert release.wait(10)

    assert unit.submit(blocking_work, operation="test-busy", session_id=unit.session_id)
    try:
        qtbot.waitUntil(entered.is_set, timeout=5000)
        if operation == "undo":
            window.request_undo()
        else:
            window.request_redo()
        assert tuple(canvas.entities) == before
        assert canvas.history_position == position
        assert "完成" in window.status_command.text()
    finally:
        release.set()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    if operation == "undo":
        window.request_undo()
        assert not canvas.entities
    else:
        window.request_redo()
        assert canvas.entities == [line]


def test_undo_is_blocked_until_worker_result_callback_finishes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _, _ = reopened_drawing
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    canvas = draft.canvas
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    canvas.replace_draft_entities((line,))
    entered, release = Event(), Event()
    observed: list[tuple[LineEntity, ...]] = []
    callbacks: list[tuple[LineEntity, ...]] = []

    def blocking_work() -> None:
        entered.set()
        assert release.wait(10)

    def busy_changed(busy: bool) -> None:
        if not busy:
            window.request_undo()
            observed.append(
                tuple(entity for entity in canvas.entities if isinstance(entity, LineEntity))
            )

    def completed(_result: object) -> None:
        window.request_undo()
        callbacks.append(
            tuple(entity for entity in canvas.entities if isinstance(entity, LineEntity))
        )

    unit.busy_changed.connect(busy_changed)
    assert unit.submit(
        blocking_work, operation="test-busy", session_id=unit.session_id, on_complete=completed
    )
    try:
        qtbot.waitUntil(entered.is_set, timeout=5000)
    finally:
        release.set()
    qtbot.waitUntil(lambda: len(callbacks) == 1, timeout=10000)
    assert observed == [(line,)]
    assert callbacks == [(line,)]
    assert not unit.is_delivering_result
    window.request_undo()
    assert not canvas.entities


def test_command_bar_moves_saved_object_with_document_undo(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, inside, crosses = reopened_drawing
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    canvas = draft.canvas
    canvas.selected_entity_ids = {inside.entity_id}
    command = draft.drawing_command_bar
    for text in ("MOVE", "0,0", "@10,20"):
        command.input.setText(text)
        QTest.keyClick(command.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert tuple(entity for entity, _layer in canvas.background_entities) == (
        LineEntity(inside.entity_id, (5.0, 20.0), (15.0, 20.0)),
        crosses,
    )
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert tuple(entity for entity, _layer in canvas.background_entities) == (inside, crosses)


def test_numeric_move_of_saved_object(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, inside, crosses = reopened_drawing
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    canvas = draft.canvas
    draft.tool_buttons["选择元素"].click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0.0, 0.0)))
    draft.delta_u_field.setValue(2.0)
    draft.delta_v_field.setValue(3.0)
    draft.numeric_move_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert tuple(entity for entity, _layer in canvas.background_entities) == (
        LineEntity(inside.entity_id, (-3.0, 3.0), (7.0, 3.0)),
        crosses,
    )


def test_move_across_saved_sketches_is_one_undo_step(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, first, _ = reopened_drawing
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    second = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    draft.canvas.replace_draft_entities((second,))
    draft.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not draft and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    canvas = current.canvas
    canvas.selected_entity_ids = {first.entity_id, second.entity_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((2.0, 3.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    actual = {entity.entity_id: entity for entity, _ in canvas.background_entities}
    assert actual[first.entity_id] == LineEntity(first.entity_id, (-3.0, 3.0), (7.0, 3.0))
    assert actual[second.entity_id] == LineEntity(second.entity_id, (12.0, 13.0), (22.0, 13.0))
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    actual = {entity.entity_id: entity for entity, _ in canvas.background_entities}
    assert actual[first.entity_id] == first
    assert actual[second.entity_id] == second
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    actual = {entity.entity_id: entity for entity, _ in canvas.background_entities}
    assert actual[first.entity_id] == LineEntity(first.entity_id, (-3.0, 3.0), (7.0, 3.0))
    assert actual[second.entity_id] == LineEntity(second.entity_id, (12.0, 13.0), (22.0, 13.0))
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not current and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    assert {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities} == actual


def test_move_rejects_ambiguous_identity_across_sketches(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, first, _ = reopened_drawing
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    duplicate = LineEntity(first.entity_id, (10.0, 10.0), (20.0, 10.0))
    draft.canvas.replace_draft_entities((duplicate,))
    draft.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not draft and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    canvas = current.canvas
    before = canvas.background_entities
    assert sum(entity.entity_id == first.entity_id for entity, _ in before) == 2
    canvas.selected_entity_ids = {first.entity_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((2.0, 3.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.background_entities == before


def test_delete_across_saved_sketches_is_one_undo_step(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, first, other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    second = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((second,))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {first.entity_id, second.entity_id}
    assert canvas.delete_selected()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and {entity.entity_id for entity, _ in canvas.background_entities} == {other.entity_id}
        ),
        timeout=10000,
    )
    window.request_undo()
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and {entity.entity_id for entity, _ in canvas.background_entities}
            == {first.entity_id, second.entity_id, other.entity_id}
        ),
        timeout=10000,
    )


def test_delete_rejects_ambiguous_identity_across_sketches(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, first, _ = reopened_drawing
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    loaded = window.loaded_document()
    assert draft is not None and unit is not None and loaded is not None
    duplicate = LineEntity(first.entity_id, (10.0, 10.0), (20.0, 10.0))
    draft.canvas.replace_draft_entities((duplicate,))
    draft.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not draft and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    before = canvas.background_entities
    commands = loaded.document.commands
    canvas.selected_entity_ids = {first.entity_id}
    assert not canvas.delete_selected()
    assert "重复" in canvas.message or "不唯一" in canvas.message
    assert canvas.background_entities == before and loaded.document.commands == commands


@pytest.mark.parametrize(
    "operation", ["offset", "linear_array", "rectangular_array", "circular_array"]
)
def test_numeric_copy_rejects_ambiguous_identity_across_sketches(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], operation: str
) -> None:
    window, first, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    loaded = window.loaded_document()
    assert editor is not None and unit is not None and loaded is not None
    duplicate = LineEntity(first.entity_id, (10.0, 10.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((duplicate,))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    before = canvas.background_entities
    commands = loaded.document.commands
    editor.tool_buttons["选择元素"].click()
    canvas.selected_entity_ids = {first.entity_id}
    canvas.changed.emit()
    editor.transform_buttons[operation].click()
    assert "不唯一" in editor.status_label.text()
    assert not canvas.entities and canvas.background_entities == before
    assert canvas.selected_entity_ids == {first.entity_id} and loaded.document.commands == commands


def test_move_saved_and_draft_together_undoes_atomically(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _ = reopened_drawing
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    canvas = draft.canvas
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((2.0, 3.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.entities == [LineEntity(line.entity_id, (12.0, 13.0), (22.0, 13.0))]
    assert {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        saved.entity_id
    ] == LineEntity(saved.entity_id, (-3.0, 3.0), (7.0, 3.0))
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.entities == [line]
    assert {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        saved.entity_id
    ] == saved
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.entities == [LineEntity(line.entity_id, (12.0, 13.0), (22.0, 13.0))]
    assert {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        saved.entity_id
    ] == LineEntity(saved.entity_id, (-3.0, 3.0), (7.0, 3.0))
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not draft and not unit.is_busy, timeout=10000
    )
    after_save = window.active_sketch_dialog()
    assert after_save is not None
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not after_save and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    entities = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    entities.update((entity.entity_id, entity) for entity in reopened.canvas.entities)
    assert entities[saved.entity_id] == saved
    assert entities[line.entity_id] == line


def test_mixed_move_save_keeps_last_move_as_one_session_undo_step(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _ = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((2.0, 3.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    saved_editor = window.active_sketch_dialog()
    assert saved_editor is not None

    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    entities = {entity.entity_id: entity for entity, _ in saved_editor.canvas.background_entities}
    assert entities[saved.entity_id] == saved
    assert entities[line.entity_id] == line


@pytest.mark.parametrize("reopen", [False, True])
def test_edit_after_mixed_move_is_separate_undo_step(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], reopen: bool
) -> None:
    window, saved, _ = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    added = LineEntity(uuid4().hex, (30.0, 0.0), (40.0, 0.0))
    canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((2.0, 3.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    moved = LineEntity(line.entity_id, (12.0, 13.0), (22.0, 13.0))
    assert canvas.entities == [moved]
    canvas.replace_draft_entities((*canvas.entities, added))
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    saved_editor = window.active_sketch_dialog()
    assert saved_editor is not None
    if reopen:
        window.act_open.trigger()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not saved_editor and not unit.is_busy,
            timeout=10000,
        )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    first = {entity.entity_id: entity for entity, _layer in reopened.canvas.background_entities}
    assert added.entity_id not in first
    assert first[line.entity_id] == moved
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    second = {entity.entity_id: entity for entity, _layer in reopened.canvas.background_entities}
    assert second[saved.entity_id] == saved
    assert second[line.entity_id] == line


@pytest.mark.parametrize("reopen", [False, True])
def test_two_mixed_moves_remain_separate(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], reopen: bool
) -> None:
    window, saved, _ = reopened_drawing
    editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    canvas.replace_draft_entities((line,))
    for delta in ((2.0, 3.0), (4.0, 5.0)):
        canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
        canvas.begin_transform("move")
        canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
        canvas.add_coordinate_point(delta, exact_point=True)
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.entities == [LineEntity(line.entity_id, (16.0, 18.0), (26.0, 18.0))]
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    saved_editor = window.active_sketch_dialog()
    assert saved_editor is not None
    if reopen:
        window.act_open.trigger()
        qtbot.waitUntil(
            lambda: window.active_sketch_dialog() is not saved_editor and not unit.is_busy,
            timeout=10000,
        )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    first = {entity.entity_id: entity for entity, _layer in reopened.canvas.background_entities}
    assert first[line.entity_id] == LineEntity(line.entity_id, (12.0, 13.0), (22.0, 13.0))
    assert first[saved.entity_id] == LineEntity(saved.entity_id, (-3.0, 3.0), (7.0, 3.0))
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    second = {entity.entity_id: entity for entity, _layer in reopened.canvas.background_entities}
    assert second[saved.entity_id] == saved
    assert second[line.entity_id] == line


def test_cancel_mixed_move_draft_preserves_document_history(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _ = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    before = loaded.document.commands
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    editor.canvas.add_coordinate_point((2.0, 3.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.mixed_move is not None
    assert loaded.document.commands == before
    editor.cancel_button.click()
    assert loaded.document.commands == before


def test_stale_mixed_move_never_commits_and_keeps_draft(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window, saved, _ = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    editor.canvas.add_coordinate_point((2.0, 3.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.mixed_move is not None
    extra = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (LineEntity(uuid4().hex, (100.0, 0.0), (110.0, 0.0)),),
    )
    loaded.bus.execute("sketch.create", extra.to_state_mapping(), confirmed_by="local")
    before = loaded.document.commands
    editor.finish_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert window.active_sketch_dialog() is editor
    assert loaded.document.commands == before
    assert editor.canvas.entities == [LineEntity(line.entity_id, (12.0, 13.0), (22.0, 13.0))]
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    visible = {entity.entity_id: entity for entity, _layer in editor.canvas.background_entities}
    assert visible[saved.entity_id] == saved
    assert extra.entities[0].entity_id in visible
    assert editor.canvas.entities == [line]


def test_mixed_move_with_user_constraint_keeps_both_sides_unchanged(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window, saved, _ = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((line,))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    editor.canvas.constraints = [constraint]
    editor.canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    commands = loaded.document.commands
    background = editor.canvas.background_entities
    editor.canvas.begin_transform("move")
    assert not editor.canvas.has_active_edit_gesture
    assert editor.canvas.entities == [line]
    assert editor.canvas.constraints == [constraint]
    assert editor.canvas.background_entities == background
    assert loaded.document.commands == commands


@pytest.mark.parametrize("numeric", [False, True])
def test_mixed_rotation_with_user_constraint_keeps_both_sides_unchanged(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], numeric: bool
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window, saved, _ = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    canvas.replace_draft_entities((line,))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    canvas.constraints = [constraint]
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    commands = loaded.document.commands
    background = canvas.background_entities
    if numeric:
        editor.angle_field.setValue(90.0)
        editor.numeric_rotate_button.click()
    else:
        canvas.begin_transform("rotate")
        canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
        canvas.add_coordinate_point((0.0, 10.0), exact_point=True)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.entities == [line]
    assert canvas.constraints == [constraint]
    assert canvas.background_entities == background
    assert loaded.document.commands == commands
    assert "约束" in (canvas.message + editor.status_label.text())
    assert canvas.rotation_default_angle == 0


@pytest.mark.parametrize("numeric", [False, True])
def test_mixed_mirror_with_user_constraint_keeps_both_sides_unchanged(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], numeric: bool
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window, saved, _ = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10.0, 4.0), (20.0, 4.0))
    canvas.replace_draft_entities((line,))
    constraint = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    canvas.constraints = [constraint]
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    before = loaded.document.commands
    background = canvas.background_entities
    if numeric:
        editor.center_v_field.setValue(10.0)
        editor.mirror_keep_source_check.setChecked(False)
        editor.numeric_mirror_button.click()
    else:
        canvas.begin_transform("mirror", keep_source=False)
        canvas.add_coordinate_point((0.0, 10.0), exact_point=True)
        canvas.add_coordinate_point((10.0, 10.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.entities == [line]
    assert canvas.constraints == [constraint]
    assert canvas.background_entities == background
    assert loaded.document.commands == before
    assert "约束" in (canvas.message + editor.status_label.text())


def test_mixed_move_refuses_changed_workplane_without_losing_draft(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _ = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    editor.canvas.add_coordinate_point((2.0, 3.0), exact_point=True)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    before = loaded.document.commands
    editor.origin_fields["X"].setValue(10.0)
    editor.finish_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert window.active_sketch_dialog() is editor
    assert loaded.document.commands == before
    assert editor.canvas.entities == [LineEntity(line.entity_id, (12.0, 13.0), (22.0, 13.0))]


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


@pytest.mark.parametrize("operation", ["copy", "rotate", "mirror"])
def test_transform_rejects_selected_committed_entity_on_locked_layer(
    qtbot: QtBot, operation: str
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0), layer_name="locked")
    layers = SketchLayerTable().add(SketchLayer("locked", locked=True))
    frame = WorkPlaneFrame.xy()
    canvas.set_background_sketches((Sketch(uuid4().hex, frame, (line,), layers=layers),), frame)
    canvas.selected_entity_ids = {line.entity_id}

    canvas.begin_transform(operation)

    assert canvas.active_transform is None
    assert "锁定" in canvas.message
    assert canvas.entities == []


def test_delete_rejects_selected_committed_entity_on_locked_layer(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0), layer_name="locked")
    layers = SketchLayerTable().add(SketchLayer("locked", locked=True))
    frame = WorkPlaneFrame.xy()
    canvas.set_background_sketches((Sketch(uuid4().hex, frame, (line,), layers=layers),), frame)
    canvas.selected_entity_ids = {line.entity_id}
    assert not canvas.delete_selected()
    assert "锁定" in canvas.message
    assert canvas.selected_entity_ids == {line.entity_id}


@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize(
    "operation", ["offset", "linear_array", "rectangular_array", "circular_array"]
)
def test_copy_operations_reject_hidden_or_locked_saved_geometry(
    qtbot: QtBot, locked: bool, operation: str
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.ui.sketch_editor import SketchCanvas

    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0), layer_name="restricted")
    layers = SketchLayerTable().add(SketchLayer("restricted", locked=locked, visible=locked))
    frame = WorkPlaneFrame.xy()
    canvas.set_background_sketches((Sketch(uuid4().hex, frame, (line,), layers=layers),), frame)
    canvas.selected_entity_ids = {line.entity_id}
    assert ("锁定" if locked else "隐藏") in canvas.transform_selection_error(operation)


def test_copy_uses_current_workplane_coordinates_for_saved_geometry(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    saved = LineEntity(uuid4().hex, (0.0, 0.0), (20.0, 0.0))
    editor.set_context_sketches((Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,)),))
    editor.origin_fields["X"].setValue(10.0)
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    canvas.begin_transform("copy")
    canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((5.0, 7.0), exact_point=True)

    assert len(canvas.entities) == 1
    copied = canvas.entities[0]
    assert isinstance(copied, LineEntity)
    assert copied.start_mm == (-5.0, 7.0)
    assert copied.end_mm == (15.0, 7.0)
    assert copied.entity_id != saved.entity_id


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


@pytest.mark.parametrize("through", [False, True])
def test_interactive_offset_saved_source_creates_draft_and_can_undo(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], through: bool
) -> None:
    window, source, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    commands = loaded.document.commands
    bar = editor.drawing_command_bar
    for text in ("OFFSET", "T" if through else "2"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, -4)))
    assert len(canvas.entities) == 1
    copy = canvas.entities[0]
    assert isinstance(copy, LineEntity)
    assert copy.start_mm == pytest.approx((-5, -4 if through else -2), abs=0.2)
    assert copy.entity_id != source.entity_id
    assert loaded.document.commands == commands
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    canvas.undo_last_operation()
    assert not canvas.entities
    canvas.redo_last_operation()
    assert canvas.entities == [copy]
    assert loaded.document.commands == commands
    unit = window.execution_unit
    assert unit is not None
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    saved_editor = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not saved_editor and not unit.is_busy,
        timeout=10000,
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    actual = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert actual[source.entity_id] == source
    assert actual[copy.entity_id] == copy


def test_offset_erase_saved_source_saves_reopens_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, source, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    before = loaded.document.commands
    bar = editor.drawing_command_bar
    for text in ("OFFSET", "E", "Y", "2"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 0)))
    bar.input.setText("3,-4")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert loaded.document.commands == before
    assert source.entity_id not in {item.entity_id for item, _ in canvas.background_entities}
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], LineEntity)
    copy = canvas.entities[0]
    assert copy.start_mm == pytest.approx((-5, -2))
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert canvas.undo_last_operation()
    assert source.entity_id in {item.entity_id for item, _ in canvas.background_entities}
    assert canvas.redo_last_operation()
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    saved = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not saved and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    entities = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert source.entity_id not in entities and entities[copy.entity_id] == copy


def test_offset_multiple_undo_restores_saved_source(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, source, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    before = loaded.document.commands
    bar = editor.drawing_command_bar.input

    def send(value: str) -> None:
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)

    for value in ("OFFSET", "E", "Y", "2"):
        send(value)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 0)))
    send("M")
    send("3,-4")
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    first = tuple(canvas.entities)
    send("3,-6")
    assert len(canvas.entities) == 1 and canvas.entities != list(first)
    send("U")
    assert tuple(canvas.entities) == first
    send("U")
    assert not canvas.entities and canvas.mixed_move is None
    assert source.entity_id in {entity.entity_id for entity, _ in canvas.background_entities}
    assert loaded.document.commands == before


def test_offset_erase_saved_source_with_constraint_keeps_document(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    source = LineEntity(uuid4().hex, (-5.0, 0.0), (5.0, 0.0))
    other = LineEntity(uuid4().hex, (-30.0, 5.0), (30.0, 5.0))
    assert editor.canvas.replace_draft_entities((source, other))
    editor.canvas.constraints = [
        SketchConstraint(
            uuid4().hex,
            "horizontal",
            (SketchGeometryReference(source.entity_id, "geometry"),),
            source="inferred",
        )
    ]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    before = loaded.document.commands
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "E", "Y", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((3, 0))
    )
    command.setText("3,-4")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert loaded.document.commands == before and not editor.canvas.entities
    assert source in (item for item, _ in editor.canvas.background_entities)
    assert "约束" in editor.canvas.message


def test_offset_erase_save_failure_preserves_candidate_and_redo(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui import document_save
    from mycad.ui.document_session import DocumentSession

    session = DocumentSession()
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    entry = window.new_session_document("sketch")
    path = tmp_path / "offset-erase.my2d"
    entry.path = path
    source = LineEntity(uuid4().hex, (-5.0, 0.0), (5.0, 0.0))
    other = LineEntity(uuid4().hex, (-30.0, 5.0), (30.0, 5.0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, other))
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
    for value in ("OFFSET", "E", "Y", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 0)))
    command.setText("3,-4")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    QTest.keyClick(command, Qt.Key.Key_Escape)
    extra = LineEntity(uuid4().hex, (20.0, 0.0), (25.0, 0.0))
    assert canvas.replace_draft_entities((*canvas.entities, extra))
    assert canvas.undo_last_operation() and canvas.can_redo
    original_save = document_save.save_document

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(document_save, "save_document", fail)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    assert saver.last_results[-1].status == "failed" and not path.exists()
    assert window.active_sketch_dialog() is editor and entry.loaded.document.commands == before
    assert canvas.mixed_move is not None and canvas.mixed_move_is_valid and canvas.can_redo
    assert canvas.redo_last_operation() and extra in canvas.entities
    assert canvas.undo_last_operation() and extra not in canvas.entities
    monkeypatch.setattr(document_save, "save_document", original_save)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    assert saver.last_results[-1].status == "saved" and path.is_file()
    services = app.fork_app_services(entry.services)
    app.open_app_document(services, path)
    entities = {item.entity_id for sketch in services.kernel.sketches for item in sketch.entities}
    assert source.entity_id not in entities and other.entity_id in entities


def test_interactive_offset_rejects_source_revision_change(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, _source, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    canvas.begin_interactive_offset()
    canvas.set_interactive_offset_distance(2)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 0)))
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, -4)))
    assert not canvas.entities
    assert canvas.active_transform is None


def test_interactive_offset_blocks_save_until_completed_or_cancelled(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, source, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    bar = editor.drawing_command_bar
    for text in ("O", "2"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 0)))
    before = loaded.document.commands
    window.act_save.trigger()
    assert loaded.document.commands == before
    assert window.active_sketch_dialog() is editor
    assert canvas.active_transform == "offset"
    assert any(entity.entity_id == source.entity_id for entity, _ in canvas.background_entities)
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert canvas.active_transform is None


def test_trim_explicit_saved_boundary_preserves_other_saved_geometry(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, other, selected = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    target = LineEntity(uuid4().hex, (0, -10), (0, 10))
    assert canvas.replace_draft_entities((target,))
    before = loaded.document.commands
    bar = editor.drawing_command_bar
    for text in ("TRIM", "C"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20, 5)))
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 2)))
    assert len(canvas.entities) == 1
    result = canvas.entities[0]
    assert isinstance(result, LineEntity)
    assert result.start_mm == pytest.approx((0, 5))
    assert result.end_mm == pytest.approx((0, 10))
    assert tuple(e for e, _ in canvas.background_entities) == (other, selected)
    assert loaded.document.commands == before


def test_trim_saved_target_uses_explicit_draft_boundary(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _other, target = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 15))
    excluded = LineEntity(uuid4().hex, (20, -5), (20, 15))
    assert canvas.replace_draft_entities((boundary, excluded))
    canvas.set_snapping_enabled(False)
    before = loaded.document.commands
    bar = editor.drawing_command_bar
    for text in ("TRIM", "C"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 12)))
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((25, 5)))
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert loaded.document.commands == before
    assert canvas.entities == [boundary, excluded]
    edited = {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        target.entity_id
    ]
    assert isinstance(edited, LineEntity)
    assert edited.end_mm == pytest.approx((10, 5))
    window.request_undo()
    restored = {entity.entity_id: entity for entity, _ in canvas.background_entities}
    assert restored[target.entity_id] == target


def test_drag_trim_saved_target_with_explicit_draft_boundary_is_atomic(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, _other, target = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    boundary = LineEntity(uuid4().hex, (10, -5), (10, 15))
    excluded = LineEntity(uuid4().hex, (20, -5), (20, 15))
    assert canvas.replace_draft_entities((boundary, excluded))
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool("修剪")
    canvas.set_line_edit_boundaries(frozenset({boundary.entity_id}))
    before = loaded.document.commands
    start, end = canvas.local_to_screen((25, 5)), canvas.local_to_screen((27, 5))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert loaded.document.commands == before
    assert canvas.entities == [boundary, excluded]
    edited = {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        target.entity_id
    ]
    assert isinstance(edited, LineEntity)
    assert edited.end_mm == pytest.approx((10, 5))
    window.request_undo()
    restored = {entity.entity_id: entity for entity, _ in canvas.background_entities}
    assert restored[target.entity_id] == target
    assert canvas.entities == [boundary, excluded]


def test_explicit_boundary_rejects_stale_revision_even_after_source_refresh(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, _other, boundary = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    target = LineEntity(uuid4().hex, (0, -10), (0, 10))
    assert canvas.replace_draft_entities((target,))
    assert canvas.set_tool("修剪")
    canvas.set_line_edit_boundaries(frozenset({boundary.entity_id}))
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    canvas.set_source_context_revision(loaded.document.revision)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 8)))
    assert canvas.entities == [target]
    assert "变化" in canvas.message


def test_boundary_selection_rejects_revision_change_before_confirmation(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, _other, boundary = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    assert canvas.set_tool("修剪")
    canvas.begin_line_edit_boundary_selection()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((20, 5)))
    assert canvas.selected_entity_ids == {boundary.entity_id}
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    canvas.set_source_context_revision(loaded.document.revision)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert not canvas.selecting_line_edit_boundaries
    assert "变化" in canvas.message


def test_trim_with_saved_boundary_continues_after_own_saved_edit(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, first, second = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    boundary = LineEntity(uuid4().hex, (0, -10), (0, 10))
    assert editor.canvas.replace_draft_entities((boundary,))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool("修剪")
    canvas.set_line_edit_boundaries(frozenset({boundary.entity_id}))
    before = len(loaded.document.commands)
    start_revision = loaded.document.revision
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 0)))
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before + 1 and not unit.is_busy, timeout=10000
    )
    assert loaded.document.revision == start_revision + 1
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 5)))
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before + 2 and not unit.is_busy, timeout=10000
    )
    result = {entity.entity_id: entity for entity, _ in canvas.background_entities}
    edited_first = result[first.entity_id]
    edited_second = result[second.entity_id]
    assert isinstance(edited_first, LineEntity)
    assert isinstance(edited_second, LineEntity)
    assert edited_first.end_mm == pytest.approx((0, 0))
    assert edited_second.end_mm == pytest.approx((0, 5))
    assert result[boundary.entity_id] == boundary


def test_boundary_selection_refuses_stale_context_at_start(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, _other, _boundary = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    assert canvas.set_tool("修剪")
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    canvas.begin_line_edit_boundary_selection()
    assert not canvas.selecting_line_edit_boundaries
    assert "变化" in canvas.message


def test_rotate_reference_command_mixed_selection_save_and_reopen(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    before = loaded.document.commands
    bar = editor.drawing_command_bar
    for text in ("RO", "0,0", "R", "30", "120"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert loaded.document.commands == before
    rotated = canvas.entities[0]
    assert isinstance(rotated, LineEntity)
    assert rotated.start_mm == pytest.approx((0, 10), abs=1e-8)
    assert rotated.end_mm == pytest.approx((0, 20), abs=1e-8)
    saved_rotated = {entity.entity_id: entity for entity, _ in canvas.background_entities}[
        saved.entity_id
    ]
    assert isinstance(saved_rotated, LineEntity)
    assert saved_rotated.end_mm == pytest.approx((0, 5), abs=1e-8)
    window.request_undo()
    assert canvas.entities == [line]
    window.request_redo()
    assert canvas.entities == [rotated]
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not previous and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    actual = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert actual[saved.entity_id] == saved_rotated
    assert actual[line.entity_id] == rotated


@pytest.mark.parametrize("erase", [False, True])
def test_mirror_prompt_mixed_objects_save_and_reopen(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], erase: bool
) -> None:
    window, _other, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    before = loaded.document.commands
    bar = editor.drawing_command_bar
    for text in ("MI", "0,0", "10,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.awaiting_mirror_erase
    assert loaded.document.commands == before and canvas.entities == [line]
    bar.input.setText("Y" if erase else "N")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    if erase:
        qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
        assert len(canvas.entities) == 1
        mirrored_draft = canvas.entities[0]
        assert isinstance(mirrored_draft, LineEntity)
        assert mirrored_draft.entity_id == line.entity_id
        assert mirrored_draft.start_mm == pytest.approx((10, -4))
        expected = tuple(canvas.entities)
    else:
        assert len(canvas.entities) == 3
        expected = tuple(canvas.entities)
        assert line in expected
        assert any(isinstance(e, LineEntity) and e.start_mm == (10, -4) for e in expected)
    assert loaded.document.commands == before
    window.request_undo()
    assert canvas.entities == [line]
    window.request_redo()
    assert tuple(canvas.entities) == expected
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not previous and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    actual = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert all(actual[entity.entity_id] == entity for entity in expected)
    assert saved.entity_id in actual


def test_mirror_prompt_rejects_document_revision_change(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, _other, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    bar = editor.drawing_command_bar
    for text in ("MI", "0,0", "10,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.awaiting_mirror_erase
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    before = loaded.document.commands
    bar.input.setText("Y")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert loaded.document.commands == before
    assert canvas.active_transform is None
    assert not canvas.entities


def test_mirror_prompt_revalidates_saved_layer_before_copy(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    from dataclasses import replace

    window, _other, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    bar = editor.drawing_command_bar
    for text in ("MI", "0,0", "10,0"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert canvas.awaiting_mirror_erase
    canvas.background_entities = tuple(
        (entity, replace(layer, locked=True) if entity.entity_id == saved.entity_id else layer)
        for entity, layer in canvas.background_entities
    )
    bar.input.setText("N")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert not canvas.entities
    assert "锁定" in canvas.message


def test_copy_array_mixed_sources_save_reopen_and_undo(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    unit = window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10, 4), (20, 4))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    before = loaded.document.commands
    bar = editor.drawing_command_bar
    for text in ("CO", "0,0", "A", "3", "F", "0,8"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert loaded.document.commands == before
    assert len(canvas.entities) == 5
    expected = tuple(canvas.entities)
    assert len({entity.entity_id for entity in expected}) == 5
    assert {entity.start_mm for entity in expected if isinstance(entity, LineEntity)} == {
        (10, 4),
        (-5, 4),
        (10, 8),
        (-5, 8),
        (10, 12),
    }
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    window.request_undo()
    assert canvas.entities == [line]
    window.request_redo()
    assert tuple(canvas.entities) == expected
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not previous and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    actual = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert actual[saved.entity_id] == saved
    assert all(actual[entity.entity_id] == entity for entity in expected)


def test_copy_array_rejects_stale_saved_source(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    bar = editor.drawing_command_bar
    for text in ("CO", "0,0", "A", "3"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    before = loaded.document.commands
    bar.input.setText("0,3")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert not canvas.entities
    assert loaded.document.commands == before
    assert canvas.active_transform is None


def test_copy_array_fit_rejects_stale_source_without_qt_exception(
    reopened_drawing: tuple[MainWindow, LineEntity, LineEntity],
) -> None:
    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    bar = editor.drawing_command_bar
    for text in ("CO", "0,0", "A", "3"):
        bar.input.setText(text)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": editor.layer_table.to_mapping(), "dimension_layer": editor.dimension_layer},
        confirmed_by="local",
    )
    before = loaded.document.commands
    bar.input.setText("F")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert loaded.document.commands == before
    assert canvas.active_transform is None
    assert not canvas.entities


def test_rotate_copy_mixed_sources_preserves_originals_and_reopens(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    draft_line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    canvas.replace_draft_entities((draft_line,))
    canvas.selected_entity_ids = {saved.entity_id, draft_line.entity_id}
    source_commands = window.loaded_document()
    assert source_commands is not None
    before = source_commands.document.commands
    bar = editor.drawing_command_bar
    for value in ("ROTATE", "0,0", "C", "R", "10,10", "10,20", "180"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert source_commands.document.commands == before
    assert saved in tuple(entity for entity, _layer in canvas.background_entities)
    assert canvas.entities[0] == draft_line and len(canvas.entities) == 3
    copied = tuple(canvas.entities[1:])
    assert all(entity.entity_id not in {saved.entity_id, draft_line.entity_id} for entity in copied)
    assert all(isinstance(entity, LineEntity) for entity in copied)
    assert any(
        isinstance(entity, LineEntity)
        and entity.start_mm == pytest.approx((0.0, -5.0), abs=1e-8)
        and entity.end_mm == pytest.approx((0.0, 5.0), abs=1e-8)
        for entity in copied
    )
    assert any(
        isinstance(entity, LineEntity)
        and entity.start_mm == pytest.approx((-10.0, 10.0), abs=1e-8)
        and entity.end_mm == pytest.approx((-10.0, 20.0), abs=1e-8)
        for entity in copied
    )
    assert canvas.undo_last_operation() and canvas.entities == [draft_line]
    assert canvas.redo_last_operation() and tuple(canvas.entities[1:]) == copied
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    current = window.active_sketch_dialog()
    assert current is not None
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not current and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    actual = {entity for entity, _layer in reopened.canvas.background_entities}
    assert {saved, draft_line, *copied} <= actual


def test_spatial_projection_trim_saved_target_replays_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window, _first, target = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    source = LineEntity(uuid4().hex, (20, -10), (20, 10))
    extra = Sketch(uuid4().hex, frame, (source,))
    loaded.bus.execute("sketch.create", extra.to_state_mapping(), confirmed_by="local")
    editor.set_context_sketches((*editor.dimension_sources()[1:], extra))
    canvas, command = editor.canvas, editor.drawing_command_bar.input
    canvas.set_line_edit_projection_mode(1)
    before = len(loaded.document.commands)
    command.setText("TRIM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    canvas.add_coordinate_point((25, 5), exact_point=True)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before + 1 and not unit.is_busy, timeout=15000
    )
    changed = {entity.entity_id: entity for entity, _ in canvas.background_entities}
    changed_target = changed[target.entity_id]
    assert isinstance(changed_target, LineEntity)
    assert changed_target.end_mm == pytest.approx((20, 5))
    assert extra.entities == (source,)
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    restored = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    restored_target = restored[target.entity_id]
    assert isinstance(restored_target, LineEntity)
    assert restored_target.end_mm == pytest.approx((20, 5))
    assert any(item.entity == source for item in reopened.canvas.spatial_boundaries)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    restored = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert restored[target.entity_id] == target


def test_spatial_projection_fence_mixed_targets_reopens_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    window, _first, saved = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    source = LineEntity(uuid4().hex, (20, -10), (20, 10))
    extra = Sketch(uuid4().hex, frame, (source,))
    loaded.bus.execute("sketch.create", extra.to_state_mapping(), confirmed_by="local")
    editor.set_context_sketches((*editor.dimension_sources()[1:], extra))
    canvas, command = editor.canvas, editor.drawing_command_bar.input
    draft = LineEntity(uuid4().hex, (-30, 0), (30, 0))
    assert canvas.replace_draft_entities((draft,))
    canvas.set_line_edit_projection_mode(1)
    for value in ("TRIM", "F", "25,-2", "25,8", ""):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=15000)
    assert isinstance(canvas.entities[0], LineEntity)
    assert canvas.entities[0].end_mm == pytest.approx((20, 0))
    changed = {entity.entity_id: entity for entity, _ in canvas.background_entities}
    changed_saved = changed[saved.entity_id]
    assert isinstance(changed_saved, LineEntity)
    assert changed_saved.end_mm == pytest.approx((20, 5))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    entities = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    saved_result, draft_result = entities[saved.entity_id], entities[draft.entity_id]
    assert isinstance(saved_result, LineEntity)
    assert isinstance(draft_result, LineEntity)
    assert saved_result.end_mm == pytest.approx((20, 5))
    assert draft_result.end_mm == pytest.approx((20, 0))
    assert any(item.entity == source for item in reopened.canvas.spatial_boundaries)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    restored = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert restored[saved.entity_id] == saved and restored[draft.entity_id] == draft


def test_spatial_projection_trims_saved_curved_polyline_and_replays(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    from mycad.core.sketch import PolylineEntity, Sketch, WorkPlaneFrame

    window, _first, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    source = LineEntity(uuid4().hex, (50, -2), (50, 12))
    extra = Sketch(uuid4().hex, frame, (source,))
    loaded.bus.execute("sketch.create", extra.to_state_mapping(), confirmed_by="local")
    editor.set_context_sketches((*editor.dimension_sources()[1:], extra))
    target = PolylineEntity(
        uuid4().hex, ((45, 0), (55, 0), (55, 10), (45, 10)), True, bulges=(0, 1, 0, 1)
    )
    assert editor.canvas.replace_draft_entities((target,))
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas, command = editor.canvas, editor.drawing_command_bar.input
    canvas.set_line_edit_projection_mode(1)
    before = len(loaded.document.commands)
    command.setText("TRIM")
    QTest.keyClick(command, Qt.Key.Key_Return)
    canvas.add_coordinate_point((60, 5), exact_point=True)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before + 1 and not unit.is_busy, timeout=15000
    )
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    entities = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    result = entities[target.entity_id]
    assert isinstance(result, PolylineEntity) and not result.closed
    assert result.points_mm[0] == pytest.approx((50, 10))
    assert result.points_mm[-1] == pytest.approx((50, 0))
    assert any(item.entity == source for item in reopened.canvas.spatial_boundaries)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    restored = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert restored[target.entity_id] == target


def test_polar_move_saved_object_replays_and_undoes(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    import math

    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    window, saved, _other = reopened_drawing
    editor = window.active_sketch_dialog()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert editor is not None and loaded is not None and unit is not None
    canvas, command = editor.canvas, editor.drawing_command_bar.input
    canvas.set_snapping_enabled(False)
    canvas.selected_entity_ids = {saved.entity_id}
    editor.polar_angle_field.setValue(45)
    editor.polar_check.setChecked(True)
    before = len(loaded.document.commands)
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
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert "极轴" in canvas.current_snap_kind
    command.setText("20")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == before + 1 and not unit.is_busy, timeout=15000
    )
    entities = {entity.entity_id: entity for entity, _ in canvas.background_entities}
    moved = entities[saved.entity_id]
    assert isinstance(moved, LineEntity)
    delta = 10 * math.sqrt(2)
    assert moved.start_mm == pytest.approx((saved.start_mm[0] + delta, saved.start_mm[1] + delta))
    window.act_save.trigger()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    entities = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert entities[saved.entity_id] == moved
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    entities = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert entities[saved.entity_id] == saved


def test_rotate_reference_target_points_mixed_selection_save_and_reopen(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity]
) -> None:
    window, saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
    before = tuple(loaded.document.commands)
    bar = editor.drawing_command_bar
    for value in ("RO", "0,0", "R", "0", "P", "30,20", "@0,10"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert tuple(loaded.document.commands) == before
    rotated = canvas.entities[0]
    assert isinstance(rotated, LineEntity) and rotated.end_mm == pytest.approx((0, 20), abs=1e-8)
    saved_rotated = next(
        entity for entity, _ in canvas.background_entities if entity.entity_id == saved.entity_id
    )
    assert isinstance(saved_rotated, LineEntity) and saved_rotated.end_mm == pytest.approx(
        (0, 5), abs=1e-8
    )
    window.request_undo()
    assert canvas.entities == [line]
    window.request_redo()
    assert canvas.entities == [rotated]
    window.act_save.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    previous = window.active_sketch_dialog()
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not previous and not unit.is_busy, timeout=10000
    )
    reopened = window.active_sketch_dialog()
    assert reopened is not None
    actual = {entity.entity_id: entity for entity, _ in reopened.canvas.background_entities}
    assert actual[saved.entity_id] == saved_rotated and actual[line.entity_id] == rotated


@pytest.mark.parametrize("copy", [False, True])
def test_rotate_reference_target_points_saved_selection_replays(
    qtbot: QtBot, reopened_drawing: tuple[MainWindow, LineEntity, LineEntity], copy: bool
) -> None:
    window, saved, _other = reopened_drawing
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    canvas.selected_entity_ids = {saved.entity_id}
    before = tuple(loaded.document.commands)
    bar = editor.drawing_command_bar
    for value in ("RO", "0,0", *(("C",) if copy else ()), "R", "0", "P", "30,20", "@0,10"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    if copy:
        assert len(canvas.entities) == 1, canvas.message
        rotated = canvas.entities[0]
        assert isinstance(rotated, LineEntity) and rotated.end_mm == pytest.approx((0, 5), abs=1e-8)
        assert tuple(loaded.document.commands) == before
        assert canvas.undo_last_operation() and not canvas.entities
        assert canvas.redo_last_operation() and canvas.entities == [rotated]
    else:
        qtbot.waitUntil(
            lambda: tuple(loaded.document.commands) != before and not unit.is_busy, timeout=10000
        )
        rotated = next(
            entity
            for entity, _ in canvas.background_entities
            if entity.entity_id == saved.entity_id
        )
        assert isinstance(rotated, LineEntity) and rotated.end_mm == pytest.approx((0, 5), abs=1e-8)
        window.request_undo()
        qtbot.waitUntil(
            lambda: (
                not unit.is_busy
                and any(entity == saved for entity, _ in canvas.background_entities)
            ),
            timeout=10000,
        )
        window.request_redo()
        qtbot.waitUntil(
            lambda: (
                not unit.is_busy
                and any(entity == rotated for entity, _ in canvas.background_entities)
            ),
            timeout=10000,
        )
