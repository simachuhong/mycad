# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Saved drawing entities remain selectable after the real GUI save/open cycle."""

from pathlib import Path
from threading import Event
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
    draft.transform_buttons["offset"].click()
    assert not canvas.has_active_edit_gesture
    assert tuple(canvas.entities) == (new_line,)
    assert loaded.document.commands == original_commands
    assert canvas.selected_entity_ids == {inside.entity_id, new_line.entity_id}
    assert "历史编辑" in draft.status_label.text()
    draft.cancel_button.click()


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


def test_delete_mixed_selection_does_not_partially_delete(
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
    assert not canvas.delete_selected()
    assert tuple(canvas.entities) == (new_line,)
    assert loaded.document.commands == original
    assert canvas.selected_entity_ids == {saved.entity_id, new_line.entity_id}
    assert "同时删除" in canvas.message


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
