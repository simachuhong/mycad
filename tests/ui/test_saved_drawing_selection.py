# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Saved drawing entities remain selectable after the real GUI save/open cycle."""

from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from PySide6.QtCore import QPoint, Qt
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
        assert canvas.entities == [target]
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
        QTest.mouseMove(canvas, pixel + QPoint(4, 4))
        QTest.mouseMove(canvas, pixel)
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


@pytest.mark.parametrize("operation", ["linear_array", "circular_array"])
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
    assert ("步距" if operation == "linear_array" else "角度") in editor.status_label.text()


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


@pytest.mark.parametrize("operation", ["offset", "linear_array", "circular_array"])
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
@pytest.mark.parametrize("operation", ["offset", "linear_array", "circular_array"])
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
