# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Canvas history keeps isolated collection steps with their draft state."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
from mycad.core.replay_proposal import ReplayAppend
from mycad.core.sketch import LineEntity, Sketch
from mycad.ui.drawing_collection_session import DrawingCollectionSession
from mycad.ui.sketch_editor import SketchEditorDialog

_REVISION_METHOD = "_advance_revision"  # Simulate a source change outside this bus.
_SESSION_FIELD = "_session_id"


def _invoke(target: object, name: str, *args: object) -> None:
    cast("Callable[..., None]", getattr(target, name))(*args)


def _session_id(window: object) -> int:
    return cast("int", getattr(window, _SESSION_FIELD))


def _skip_gl_paint(*_args: object, **_kwargs: object) -> None:
    pass


@pytest.mark.parametrize("undo_first", [False, True])
def test_cancel_block_paste_restores_mixed_draft_history(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, undo_first: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow
    from mycad.ui.sketch_editor import MixedMoveState

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    definition = BlockDefinition(uuid4().hex, "MixedHistory", (first,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    _invoke(window, "_sync_drawing_layers")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    second = LineEntity(uuid4().hex, (0, 2), (2, 2))
    assert editor.canvas.replace_draft_entities((second,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (second,), layers=editor.layer_table
    )
    moved_first = replace(first, start_mm=(3, 0), end_mm=(5, 0))
    moved_second = replace(second, start_mm=(3, 2), end_mm=(5, 2))
    moved_saved = replace(saved, entities=(moved_first,))
    background = editor.canvas.background_entities
    overlay = tuple(
        (moved_first if item.entity_id == first.entity_id else item, layer)
        for item, layer in background
    )
    mixed = MixedMoveState(
        uuid4().hex, loaded.document.revision, draft, (saved,), (moved_saved,), background, overlay
    )
    editor.canvas.apply_mixed_move(mixed, (moved_second,))
    if undo_first:
        assert editor.canvas.undo_last_operation()
    expected_mixed = editor.canvas.mixed_move
    expected_background = editor.canvas.background_entities
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    try:
        assert editor.canvas.copy_to_clipboard()
        assert editor.canvas.begin_clipboard_paste()
        _invoke(qtbot, "keyClick", editor.canvas, Qt.Key.Key_Escape)
        assert editor.canvas.collection_session is None
        assert editor.canvas.mixed_move == expected_mixed
        assert editor.canvas.background_entities == expected_background
        if undo_first:
            assert editor.canvas.redo_last_operation()
            assert editor.canvas.mixed_move == mixed
            assert tuple(editor.canvas.entities) == (moved_second,)
        else:
            assert editor.canvas.undo_last_operation()
            assert editor.canvas.mixed_move is None
            assert tuple(editor.canvas.entities) == (second,)
    finally:
        QApplication.clipboard().clear()


def test_group_rejects_stale_selection_before_starting_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    editor.canvas.selected_entity_ids = {uuid4().hex}
    assert editor.canvas.collection_session is None
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert "不存在" in editor.status_label.text()
    assert editor.canvas.collection_session is None
    assert loaded.document.commands == ()


@pytest.mark.parametrize("selected_index", [0, 1])
def test_group_rejects_array_member_before_starting_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, selected_index: int
) -> None:
    from PySide6.QtCore import Qt

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    lines = (LineEntity(uuid4().hex, (0, 0), (2, 0)), LineEntity(uuid4().hex, (5, 0), (7, 0)))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    source, target = tuple(ArrayEntityRef(saved.sketch_id, item.entity_id) for item in lines)
    array = AssociativeRectArray(
        uuid4().hex, saved.frame, 1, 2, 0, 5, (source,), (ArrayMember(source, target, 0, 1),)
    )
    app.commit_new_sketch(
        services, loaded, saved, session_identity=_session_id(window), associative_arrays=(array,)
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {lines[selected_index].entity_id}
    history = tuple(loaded.document.commands)
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert "阵列" in editor.status_label.text()
    editor.canvas.cursor_changed.emit(1.0, 1.0, "")
    assert "阵列" in editor.status_label.text()
    assert editor.canvas.collection_session is None
    assert tuple(loaded.document.commands) == history


def test_unmapped_group_member_replacement_is_reported_and_not_inherited(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt

    from mycad.core.drawing_transactions import prepare_grouped_sketch_replacements
    from mycad.ui.drawing_collection_session import unmapped_group_replacements
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (0, 1), (2, 1))
    assert editor.canvas.replace_draft_entities((first, second))
    editor.canvas.selected_entity_ids = {first.entity_id, second.entity_id}
    _invoke(qtbot, "mouseClick", editor.group_button, Qt.MouseButton.LeftButton)
    session = editor.canvas.collection_session
    assert session is not None
    group = replace(session.snapshot.groups[0], selectable=False)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.update", 1, group.to_mapping(), "local")
    )
    before = session.snapshot
    draft = next(item for item in before.sketches if item.sketch_id == editor.draft_sketch_id)
    replacement = LineEntity(uuid4().hex, (0, 0), (1, 0))
    revised_sketch = replace(draft, entities=(replacement, second))
    old_ref = DrawingObjectRef("geometry", first.entity_id, draft.sketch_id)
    new_ref = DrawingObjectRef("geometry", replacement.entity_id, draft.sketch_id)
    mapped = prepare_grouped_sketch_replacements(
        (draft,), (revised_sketch,), before.groups, {old_ref: (new_ref,)}
    )
    mapped_preview = session.preview_operation(mapped)
    assert unmapped_group_replacements(before, mapped_preview, mapped) == ()
    assert new_ref in mapped_preview.groups[0].members and session.snapshot == before
    revised = revised_sketch.to_state_mapping()
    operation = ReplayAppend(
        "drawing.sketch.revise",
        79,
        {
            "revisions": [
                {
                    "sketch_id": draft.sketch_id,
                    "base_state_sha256": draft.local_state_digest(),
                    "entities": revised["entities"],
                    "constraints": revised["constraints"],
                }
            ]
        },
        "local",
    )
    assert editor.canvas.stage_collection_operation(operation)
    remaining = DrawingObjectRef("geometry", second.entity_id, draft.sketch_id)
    assert session.snapshot.groups[0].members == (remaining,)
    batch = ReplayAppend(
        "drawing.objects.batch",
        1,
        {"operations": [{"id": operation.command_id, "version": 79, "params": operation.params}]},
        "local",
    )
    assert unmapped_group_replacements(before, session.snapshot, batch) == (old_ref,)
    other_sketch = replace(draft, sketch_id=uuid4().hex, entities=(replacement,))
    cross_sketch = replace(
        session.snapshot,
        sketches=tuple(
            replace(item, entities=(second,)) if item.sketch_id == draft.sketch_id else item
            for item in session.snapshot.sketches
        )
        + (other_sketch,),
    )
    assert unmapped_group_replacements(before, cross_sketch, batch) == (old_ref,)
    assert "组" in editor.canvas.message and "映射" in editor.canvas.message
    assert group.group_id in editor.canvas.message
    assert "映射" in editor.status_label.text()
    assert loaded.document.commands == ()
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.replace_draft_entities((replacement, second))
    assert session.snapshot.groups[0].members == (remaining,)
    assert "映射" in editor.canvas.message and "映射" in editor.status_label.text()
    assert group.group_id in editor.canvas.message
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    editor.canvas.message = "准备同步"
    editor.canvas.entities = [replacement, second]
    editor.canvas.changed.emit()
    assert session.snapshot.groups[0].members == (remaining,)
    assert "映射" in editor.canvas.message and "映射" in editor.status_label.text()


def test_committed_unmapped_group_replacement_is_reported_in_status(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (4, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    new = LineEntity(uuid4().hex, (0, 0), (2, 0))
    revised = replace(sketch, entities=(new,)).to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": revised["entities"],
                    "constraints": revised["constraints"],
                }
            ]
        },
        "local",
        version=79,
    )
    qtbot.waitUntil(lambda: "替换映射" in window.status_command.text())
    assert group.group_id in window.status_command.toolTip()
    assert line.entity_id in window.status_command.toolTip()
    window.handle_core_signal(
        "post_command",
        {
            "command_id": "drawing.group.update",
            "ordinal": 3,
            "transaction_unmapped_group_memberships": [
                {"group_id": group.group_id, "member": ref.to_mapping()}
            ],
        },
    )
    assert "替换映射" in window.status_command.text()
    assert group.group_id in window.status_command.toolTip()
    assert services.kernel.drawing_groups == ()


def test_group_command_creates_session_and_groups_selected_draft(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None
    assert session.snapshot.groups[0].members == (
        DrawingObjectRef("geometry", line.entity_id, editor.draft_sketch_id),
    )
    assert loaded.document.commands == ()
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == ()


def test_ungroup_command_retains_objects_and_is_undoable(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and len(session.snapshot.groups) == 1
    editor.drawing_command_bar.input.setText("UNGROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert session.snapshot.groups == ()
    assert editor.canvas.entities == [line]
    assert editor.canvas.undo_last_operation()
    assert len(session.snapshot.groups) == 1
    assert loaded.document.commands == ()


def test_group_committed_object_without_draft_does_not_save_empty_sketch(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt

    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and len(session.snapshot.groups) == 1
    editor.finish_sketch()
    assert editor.result_sketch is not None, editor.status_label.text()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and window.active_sketch_dialog() is not editor)
    assert services.kernel.sketches == (saved,)
    assert len(services.kernel.drawing_groups) == 1, window.status_command.text()
    loaded.bus.undo_operation()
    assert services.kernel.sketches == (saved,)
    assert services.kernel.drawing_groups == ()


def test_group_toolbar_button_uses_same_group_operation(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    _invoke(qtbot, "mouseClick", editor.group_button, Qt.MouseButton.LeftButton)
    session = editor.canvas.collection_session
    assert session is not None and len(session.snapshot.groups) == 1
    _invoke(qtbot, "mouseClick", editor.ungroup_button, Qt.MouseButton.LeftButton)
    assert session.snapshot.groups == ()


def test_group_menu_creates_group_in_drawing_workspace(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    window.menu_edit.aboutToShow.emit()
    assert window.act_drawing_group.isEnabled()
    window.act_drawing_group.trigger()
    session = editor.canvas.collection_session
    assert session is not None and len(session.snapshot.groups) == 1


def test_ungroup_overlap_requires_explicit_target(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QInputDialog

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    _invoke(qtbot, "mouseClick", editor.group_button, Qt.MouseButton.LeftButton)
    session = editor.canvas.collection_session
    assert session is not None
    first = session.snapshot.groups[0]
    second = DrawingGroup(uuid4().hex, first.members, name="指定组")
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, second.to_mapping(), "local")
    )

    def cancelled(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "", False

    def choose_second(
        _parent: object, _title: object, _label: object, choices: list[str], *_args: object
    ) -> tuple[str, bool]:
        return choices[1], True

    monkeypatch.setattr(QInputDialog, "getItem", cancelled)
    _invoke(qtbot, "mouseClick", editor.ungroup_button, Qt.MouseButton.LeftButton)
    assert session.snapshot.groups == (first, second)
    monkeypatch.setattr(QInputDialog, "getItem", choose_second)
    _invoke(qtbot, "mouseClick", editor.ungroup_button, Qt.MouseButton.LeftButton)
    assert session.snapshot.groups == (first,)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (first, second)


@pytest.mark.parametrize(
    "action", ["cancel", "save", "stale", "selection_changed", "selection_changed_active"]
)
def test_groupedit_of_saved_group_stages_only_after_confirmation(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog

    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.drawing_collections import DrawingGroupEditor
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, saved.sketch_id),)
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    if action in {"selection_changed", "selection_changed_active"}:
        editor.canvas.selected_entity_ids = {line.entity_id}
    if action == "selection_changed_active":
        _invoke(window, "_ensure_collection_session", editor)
    original_session = editor.canvas.collection_session
    checkpoint = original_session.checkpoint() if original_session is not None else None
    before = tuple(loaded.document.commands)

    def edit(dialog: DrawingGroupEditor) -> int:
        assert editor.canvas.collection_session is original_session
        if action == "cancel":
            return QDialog.DialogCode.Rejected.value
        if action == "stale":
            loaded.bus.execute(
                "drawing.group.update", replace(group, name="Concurrent").to_mapping(), "local"
            )
        if action in {"selection_changed", "selection_changed_active"}:
            dialog.remove_selection()
            editor.canvas.selected_entity_ids.clear()
        dialog.name_field.setText("Edited")
        return QDialog.DialogCode.Accepted.value

    monkeypatch.setattr(DrawingGroupEditor, "exec", edit)
    editor.drawing_command_bar.input.setText("GROUPEDIT")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    if action == "save":
        session = editor.canvas.collection_session
        assert session is not None and session.snapshot.groups == (replace(group, name="Edited"),)
        assert services.kernel.drawing_groups == (group,)
        assert tuple(loaded.document.commands) == before
        assert editor.canvas.undo_last_operation() and session.snapshot.groups == (group,)
    elif action == "stale":
        assert editor.canvas.collection_session is None
        assert services.kernel.drawing_groups == (replace(group, name="Concurrent"),)
        assert "变化" in editor.status_label.text()
    elif action == "selection_changed":
        assert editor.canvas.collection_session is None
        assert tuple(loaded.document.commands) == before
        assert services.kernel.drawing_groups == (group,)
        assert "变化" in editor.status_label.text()
    elif action == "selection_changed_active":
        assert original_session is not None and editor.canvas.collection_session is original_session
        assert original_session.checkpoint() == checkpoint
        assert original_session.snapshot.groups == (group,)
        assert tuple(loaded.document.commands) == before
        assert "变化" in editor.status_label.text()
    else:
        assert editor.canvas.collection_session is None
        assert tuple(loaded.document.commands) == before
        assert services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("reason", ["duplicate_name", "array_member"])
@pytest.mark.parametrize("active_session", [False, True])
def test_groupedit_rejects_invalid_update_before_starting_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, reason: str, active_session: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QInputDialog

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.drawing_collections import DrawingGroupEditor
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    lines = tuple(LineEntity(uuid4().hex, (x, 0), (x + 2, 0)) for x in (0, 5, 10))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    source, generated = (ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in lines[:2])
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (source,), (ArrayMember(source, generated, 0, 1),)
    )
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=_session_id(window), associative_arrays=(array,)
    )
    member = DrawingObjectRef("geometry", lines[2].entity_id, sketch.sketch_id)
    target = DrawingGroup(uuid4().hex, (member,), name="First")
    loaded.bus.execute("drawing.group.create", target.to_mapping(), "local")
    if reason == "duplicate_name":
        second = DrawingGroup(uuid4().hex, (member,), name="Other")
        loaded.bus.execute("drawing.group.create", second.to_mapping(), "local")

        def select_target(*_args: object) -> tuple[str, bool]:
            return f"First ({target.group_id})", True

        monkeypatch.setattr(QInputDialog, "getItem", select_target)
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    if reason == "array_member":
        editor.canvas.selected_entity_ids = {lines[0].entity_id}
    if active_session:
        _invoke(window, "_ensure_collection_session", editor)
    session = editor.canvas.collection_session
    checkpoint = session.checkpoint() if session is not None else None
    history = tuple(loaded.document.commands)
    groups = services.kernel.drawing_groups

    def edit(dialog: DrawingGroupEditor) -> int:
        if reason == "duplicate_name":
            dialog.name_field.setText("other")
        else:
            dialog.add_selection()
        return QDialog.DialogCode.Accepted.value

    monkeypatch.setattr(DrawingGroupEditor, "exec", edit)
    editor.drawing_command_bar.input.setText("GROUPEDIT")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert editor.canvas.collection_session is session
    if session is not None:
        assert session.checkpoint() == checkpoint
    assert services.kernel.drawing_groups == groups
    assert tuple(loaded.document.commands) == history
    assert ("name" if reason == "duplicate_name" else "阵列") in editor.status_label.text()
    editor.canvas.cursor_changed.emit(1.0, 1.0, "")
    assert ("name" if reason == "duplicate_name" else "阵列") in editor.status_label.text()


@pytest.mark.parametrize("action", ["cancel", "choose", "stale", "selection_changed"])
def test_ungroup_saved_overlap_stages_only_after_target_choice(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QInputDialog

    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", line.entity_id, saved.sketch_id)
    first, second = DrawingGroup(uuid4().hex, (ref,)), DrawingGroup(uuid4().hex, (ref,))
    for group in (first, second):
        loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    history = tuple(loaded.document.commands)
    session_during_dialog: list[bool] = []

    def choose(
        _parent: object, _title: object, _label: object, choices: list[str], *_args: object
    ) -> tuple[str, bool]:
        session_during_dialog.append(editor.canvas.collection_session is not None)
        if action == "cancel":
            return "", False
        if action == "stale":
            loaded.bus.execute(
                "drawing.group.update", replace(first, name="Concurrent").to_mapping(), "local"
            )
        if action == "selection_changed":
            editor.canvas.selected_entity_ids.clear()
        return choices[1], True

    monkeypatch.setattr(QInputDialog, "getItem", choose)
    _invoke(qtbot, "mouseClick", editor.ungroup_button, Qt.MouseButton.LeftButton)
    assert session_during_dialog == [False]
    if action == "choose":
        session = editor.canvas.collection_session
        assert session is not None and session.snapshot.groups == (first,)
        assert services.kernel.drawing_groups == (first, second)
        assert tuple(loaded.document.commands) == history
        assert editor.canvas.undo_last_operation() and session.snapshot.groups == (first, second)
    elif action == "stale":
        assert editor.canvas.collection_session is None
        assert services.kernel.drawing_groups == (replace(first, name="Concurrent"), second)
        assert "变化" in editor.status_label.text()
    elif action == "selection_changed":
        assert editor.canvas.collection_session is None
        assert services.kernel.drawing_groups == (first, second)
        assert tuple(loaded.document.commands) == history
        assert "变化" in editor.status_label.text()
        editor.canvas.cursor_changed.emit(1.0, 1.0, "")
        assert "变化" in editor.status_label.text()
    else:
        assert editor.canvas.collection_session is None
        assert tuple(loaded.document.commands) == history
        assert services.kernel.drawing_groups == (first, second)


@pytest.mark.parametrize("operation", ["edit", "edit_choose", "ungroup"])
def test_group_dialog_rejects_stale_session_without_overwriting_changes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QInputDialog

    from mycad.ui.drawing_collections import DrawingGroupEditor
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    _invoke(qtbot, "mouseClick", editor.group_button, Qt.MouseButton.LeftButton)
    session = editor.canvas.collection_session
    assert session is not None
    first = session.snapshot.groups[0]
    if operation != "edit":
        second = DrawingGroup(uuid4().hex, first.members, name="Second")
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.create", 1, second.to_mapping(), "local")
        )

    concurrent = replace(first, name="Concurrent")

    def apply_concurrent() -> None:
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.update", 1, concurrent.to_mapping(), "local")
        )

    def edit(dialog: DrawingGroupEditor) -> int:
        assert operation == "edit"
        apply_concurrent()
        dialog.name_field.setText("Stale")
        return QDialog.DialogCode.Accepted.value

    def choose(
        _parent: object, _title: object, _label: object, choices: list[str], *_args: object
    ) -> tuple[str, bool]:
        apply_concurrent()
        return choices[0], True

    monkeypatch.setattr(DrawingGroupEditor, "exec", edit)
    monkeypatch.setattr(QInputDialog, "getItem", choose)
    if operation.startswith("edit"):
        editor.drawing_command_bar.input.setText("GROUPEDIT")
        _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    else:
        _invoke(qtbot, "mouseClick", editor.ungroup_button, Qt.MouseButton.LeftButton)
    assert session.snapshot.groups[0] == concurrent
    assert len(session.snapshot.groups) == (1 if operation == "edit" else 2)
    assert "变化" in editor.status_label.text()
    assert loaded.document.commands == ()
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups[0] == first


def test_groupedit_changes_properties_and_adds_selected_member(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog

    from mycad.ui.drawing_collections import DrawingGroupEditor
    from mycad.ui.main_window import MainWindow

    def edit(dialog: DrawingGroupEditor) -> int:
        dialog.name_field.setText("基准组")
        dialog.description_field.setText("主要对象")
        dialog.selectable_field.setChecked(False)
        dialog.add_selection()
        return QDialog.DialogCode.Accepted.value

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    monkeypatch.setattr(DrawingGroupEditor, "exec", edit)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (0, 1), (2, 1))
    assert editor.canvas.replace_draft_entities((first, second))
    editor.canvas.selected_entity_ids = {first.entity_id}
    _invoke(qtbot, "mouseClick", editor.group_button, Qt.MouseButton.LeftButton)
    session = editor.canvas.collection_session
    assert session is not None
    original = session.snapshot.groups[0]
    editor.canvas.selected_entity_ids = {second.entity_id}
    editor.drawing_command_bar.input.setText("GROUPEDIT")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    updated = session.snapshot.groups[0]
    assert updated.name == "基准组" and updated.description == "主要对象"
    assert not updated.selectable
    assert updated.members == (
        *original.members,
        DrawingObjectRef("geometry", second.entity_id, editor.draft_sketch_id),
    )
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (original,)


@pytest.mark.parametrize("overlap", [False, True])
def test_groupedit_removing_last_member_deletes_group_but_preserves_object(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, overlap: bool
) -> None:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QInputDialog

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.ui.drawing_collections import DrawingGroupEditor
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.drawing_command_bar.input.setText("GROUP")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None
    group = session.snapshot.groups[0]
    other = replace(group, group_id=uuid4().hex, name="重叠组") if overlap else None
    if other is not None:
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.create", 1, other.to_mapping(), "local")
        )

        def choose(
            _parent: object, _title: object, _label: object, choices: list[str], *_args: object
        ) -> tuple[str, bool]:
            return choices[0], True

        monkeypatch.setattr(QInputDialog, "getItem", choose)
    original_groups = (group,) if other is None else (group, other)
    remaining_groups = () if other is None else (other,)
    before = session.checkpoint()
    history = tuple(loaded.document.commands)

    def remove_last() -> None:
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, DrawingGroupEditor):
            return
        dialog.remove_selection()
        button = dialog.confirm.button(QDialogButtonBox.StandardButton.Ok)
        button.click()
        if dialog.isVisible():
            dialog.reject()

    def run_groupedit() -> None:
        QTimer.singleShot(0, remove_last)
        editor.drawing_command_bar.input.setText("GROUPEDIT")
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟空组候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        run_groupedit()
    assert "模拟空组候选失败" in editor.status_label.text()
    assert session.checkpoint() == before and tuple(loaded.document.commands) == history
    run_groupedit()
    assert session.snapshot.groups == remaining_groups
    assert session.snapshot.sketches[-1].entities == (line,)
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == original_groups
    assert editor.canvas.redo_last_operation() and session.snapshot.groups == remaining_groups
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "groupedit-last-member.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups == remaining_groups
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == original_groups
    assert services.kernel.sketches[-1].entities == (line,)


def test_ungroup_saved_group_without_draft(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtCore import Qt

    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, saved.sketch_id),)
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    _invoke(qtbot, "mouseClick", editor.ungroup_button, Qt.MouseButton.LeftButton)
    session = editor.canvas.collection_session
    assert session is not None and session.snapshot.groups == ()
    editor.finish_sketch()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and window.active_sketch_dialog() is not editor)
    assert services.kernel.sketches == (saved,)
    assert services.kernel.drawing_groups == ()
    loaded.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)


def test_saved_selectable_group_move_starts_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (0, 2), (2, 2))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex,
        tuple(
            DrawingObjectRef("geometry", item.entity_id, saved.sketch_id)
            for item in (first, second)
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {first.entity_id}
    assert editor.canvas.effective_group_selection() == frozenset(group.members)
    editor.canvas.begin_transform("move")
    assert editor.canvas.collection_session is not None
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None
    moved = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    assert moved.entities == (
        replace(first, start_mm=(0, 3), end_mm=(2, 3)),
        replace(second, start_mm=(0, 5), end_mm=(2, 5)),
    )
    assert services.kernel.sketches == (saved,)


@pytest.mark.parametrize("operation", ["move", "copy"])
def test_group_transform_uses_dimension_seed_with_cross_sketch_same_ids(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, operation: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.drawing_collection_session import DrawingCollectionTransformPreview
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 4),
    )
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    second = replace(first, start_mm=(0, 20), end_mm=(10, 20))
    other_dimension = replace(dimension, position_mm=(5, 24))
    assert editor.canvas.replace_draft_entities((second,), new_relations=(other_dimension,))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (second,),
        (other_dimension,),
        editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    saved_ref = DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            saved_ref,
            DrawingObjectRef("geometry", first.entity_id, saved.sketch_id),
            DrawingObjectRef("dimension", dimension.constraint_id, draft.sketch_id),
            DrawingObjectRef("geometry", second.entity_id, draft.sketch_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("选择元素")
    projected = next(
        item for item in editor.canvas.dimension_constraints() if item.position_mm == (5, 4)
    )
    rect = editor.canvas.dimension_label_rectangles_by_constraint()[id(projected)]
    QTest.mouseClick(editor.canvas, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
    assert editor.canvas.selected_dimension_refs == {saved_ref}
    before = session.snapshot
    editor.canvas.begin_transform(operation)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.preview_collection_displacement(operation == "copy", (0, 3))
    preview_field = "_collection_transform_preview"
    preview = getattr(editor.canvas, preview_field)
    assert isinstance(preview, DrawingCollectionTransformPreview) and preview.seeds == {saved_ref}
    assert session.snapshot == before
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    after = session.snapshot
    if operation == "move":
        assert after.sketches[0].constraints == (replace(dimension, position_mm=(5, 7)),)
        assert after.sketches[-1].constraints == (replace(other_dimension, position_mm=(5, 27)),)
        assert after.groups == (group,)
    else:
        assert len(after.groups) == 2
        copied_dimensions = [ref for ref in after.groups[-1].members if ref.kind == "dimension"]
        assert len(copied_dimensions) == 2
        assert {(ref.sketch_id, ref.object_id) for ref in copied_dimensions} == {
            (sketch.sketch_id, item.constraint_id)
            for sketch in preview.payload.sketches
            for item in sketch.constraints
        }
        copied_constraints = [
            next(
                item
                for sketch in after.sketches
                if sketch.sketch_id == ref.sketch_id
                for item in sketch.constraints
                if item.constraint_id == ref.object_id
            )
            for ref in copied_dimensions
        ]
        assert {item.position_mm for item in copied_constraints} == {(5, 7), (5, 27)}
        assert all(
            any(
                item.entity_id == constraint.references[0].entity_id
                for sketch in after.sketches
                if sketch.sketch_id == ref.sketch_id
                for item in sketch.entities
            )
            for ref, constraint in zip(copied_dimensions, copied_constraints, strict=True)
        )
        assert editor.canvas.cancel_transform()
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / f"dimension-seed-{operation}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


@pytest.mark.parametrize("selectable", [False, True])
def test_break_saved_group_member_respects_selection_and_maps_fragments(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, selectable: bool
) -> None:
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", line.entity_id, saved.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=selectable)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.set_tool("单点打断")
    editor.canvas.add_coordinate_point((1, 0), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None
    split = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    if selectable:
        assert split.entities == (line,) and session.snapshot.groups == (group,)
        assert "组选择" in editor.canvas.message
        return
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, saved.sketch_id) for item in split.entities
    )
    assert len(refs) == 2 and session.snapshot.groups[0].members == refs
    assert services.kernel.sketches == (saved,)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)


def test_repeated_break_of_saved_group_member_uses_candidate(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", line.entity_id, saved.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    history = tuple(loaded.document.commands)
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.set_tool("单点打断")
    editor.canvas.add_coordinate_point((10, 0), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None
    once = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    assert len(once.entities) == 2
    first = once.entities[0]
    editor.canvas.selected_entity_ids = {first.entity_id}
    assert editor.canvas.set_tool("单点打断")
    editor.canvas.add_coordinate_point((5, 0), exact_point=True)
    twice = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    assert len(twice.entities) == 3, editor.canvas.message
    assert session.snapshot.groups[0].members == tuple(
        DrawingObjectRef("geometry", item.entity_id, saved.sketch_id) for item in twice.entities
    )
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == once
    )
    assert editor.canvas.redo_last_operation()
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "repeated-break.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[0] == once
    reopened.bus.undo_operation()
    assert services.kernel.sketches[0] == saved and services.kernel.drawing_groups == (group,)


def test_break_ungrouped_saved_line_during_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    grouped = LineEntity(uuid4().hex, (0, 0), (20, 0))
    other = LineEntity(uuid4().hex, (0, 4), (20, 4))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (grouped, other))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", grouped.entity_id, saved.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    history = tuple(loaded.document.commands)
    editor.canvas.selected_entity_ids = {grouped.entity_id}
    assert editor.canvas.set_tool("单点打断")
    editor.canvas.add_coordinate_point((10, 0), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None
    once = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    group_after_first = session.snapshot.groups
    editor.canvas.selected_entity_ids = {other.entity_id}
    assert editor.canvas.set_tool("单点打断")
    editor.canvas.add_coordinate_point((10, 4), exact_point=True)
    twice = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    assert len(twice.entities) == 4, editor.canvas.message
    assert session.snapshot.groups == group_after_first
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == once
    )
    assert editor.canvas.redo_last_operation()
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "ungrouped-break.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches[0] == twice
    reopened.bus.undo_operation()
    assert (
        services.kernel.sketches[0] == once and services.kernel.drawing_groups == group_after_first
    )


@pytest.mark.parametrize("selectable", [False, True])
def test_split_saved_group_member_respects_selection_and_maps_fragments(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, selectable: bool
) -> None:
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    cutter = LineEntity(uuid4().hex, (15, -5), (15, 5))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, cutter))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", line.entity_id, saved.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=selectable)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    assert editor.canvas.set_tool("分割")
    editor.canvas.add_coordinate_point((13, 0), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None
    split = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    if selectable:
        assert split == saved and session.snapshot.groups == (group,)
        assert "组选择" in editor.canvas.message
        return
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, saved.sketch_id) for item in split.entities[:2]
    )
    assert len(split.entities) == 3 and session.snapshot.groups[0].members == refs
    assert services.kernel.sketches == (saved,)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)


@pytest.mark.parametrize(("move_count", "cancel"), [(1, False), (1, True), (2, False)])
def test_group_after_existing_mixed_move_keeps_both_undo_steps(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, move_count: int, cancel: bool
) -> None:
    from PySide6.QtCore import Qt

    from mycad.core.persistence import save_document
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow
    from mycad.ui.sketch_editor import MixedMoveState

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    second = LineEntity(uuid4().hex, (0, 2), (2, 2))
    assert editor.canvas.replace_draft_entities((second,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (second,), layers=editor.layer_table
    )
    background = editor.canvas.background_entities
    transaction_id = uuid4().hex
    saved_steps = [saved]
    draft_steps = [second]
    for index in range(1, move_count + 1):
        offset = 3 * index
        moved_first = replace(first, start_mm=(offset, 0), end_mm=(offset + 2, 0))
        moved_second = replace(second, start_mm=(offset, 2), end_mm=(offset + 2, 2))
        moved_saved = replace(saved, entities=(moved_first,))
        overlay = tuple(
            (moved_first if item.entity_id == first.entity_id else item, layer)
            for item, layer in background
        )
        state = MixedMoveState(
            transaction_id,
            loaded.document.revision,
            draft,
            (saved,),
            (moved_saved,),
            background,
            overlay,
        )
        editor.canvas.apply_mixed_move(state, (moved_second,))
        saved_steps.append(moved_saved)
        draft_steps.append(moved_second)
    editor.canvas.selected_entity_ids = {first.entity_id, second.entity_id}
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and len(session.snapshot.groups) == 1
    assert services.kernel.sketches == (saved,)
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == ()
    for index in reversed(range(move_count)):
        assert editor.canvas.undo_last_operation()
        assert tuple(editor.canvas.entities) == (draft_steps[index],)
        assert (
            next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
            == saved_steps[index]
        )
    for _ in range(move_count + 1):
        assert editor.canvas.redo_last_operation()
    assert len(session.snapshot.groups) == 1
    if cancel:
        commands = loaded.document.commands
        editor.reject()
        assert loaded.document.commands == commands
        assert services.kernel.sketches == (saved,) and services.kernel.drawing_groups == ()
        return
    editor.finish_sketch()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and window.active_sketch_dialog() is not editor)
    path = tmp_path / "mixed-before-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == () and services.kernel.sketches[0] == saved_steps[-1]
    for index in reversed(range(move_count)):
        reopened.bus.undo_operation()
        assert services.kernel.sketches[0] == saved_steps[index]
        assert services.kernel.sketches[-1].entities == (draft_steps[index],)


def test_group_after_mixed_saved_move_with_empty_draft(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt

    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow
    from mycad.ui.sketch_editor import MixedMoveState

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    moved = replace(line, start_mm=(3, 0), end_mm=(5, 0))
    moved_saved = replace(saved, entities=(moved,))
    background = editor.canvas.background_entities
    overlay = tuple(
        (moved if item.entity_id == line.entity_id else item, layer) for item, layer in background
    )
    state = MixedMoveState(
        uuid4().hex, loaded.document.revision, draft, (saved,), (moved_saved,), background, overlay
    )
    editor.canvas.apply_mixed_move(state, ())
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and len(session.snapshot.groups) == 1
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == moved_saved
    )
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == ()
    assert editor.canvas.undo_last_operation()
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == saved
    )
    assert editor.canvas.redo_last_operation() and editor.canvas.redo_last_operation()
    session.commit()
    editor.canvas.collection_session = None
    assert services.kernel.sketches == (moved_saved,) and len(services.kernel.drawing_groups) == 1
    loaded.bus.undo_operation()
    assert services.kernel.drawing_groups == () and services.kernel.sketches == (moved_saved,)
    loaded.bus.undo_operation()
    assert services.kernel.sketches == (saved,)


def test_adopting_mixed_history_keeps_existing_redo_branch(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow
    from mycad.ui.sketch_editor import MixedMoveState

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    second = LineEntity(uuid4().hex, (0, 2), (2, 2))
    assert editor.canvas.replace_draft_entities((second,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (second,), layers=editor.layer_table
    )
    moved_first = replace(first, start_mm=(3, 0), end_mm=(5, 0))
    moved_second = replace(second, start_mm=(3, 2), end_mm=(5, 2))
    moved_saved = replace(saved, entities=(moved_first,))
    background = editor.canvas.background_entities
    overlay = tuple(
        (moved_first if item.entity_id == first.entity_id else item, layer)
        for item, layer in background
    )
    state = MixedMoveState(
        uuid4().hex, loaded.document.revision, draft, (saved,), (moved_saved,), background, overlay
    )
    editor.canvas.apply_mixed_move(state, (moved_second,))
    assert editor.canvas.undo_last_operation() and editor.canvas.mixed_move is None
    with monkeypatch.context() as stale:
        stale.setattr(
            editor.canvas, "source_revision_provider", lambda: loaded.document.revision + 1
        )
        with pytest.raises(ValidationError, match="来源已变化"):
            _invoke(window, "_ensure_collection_session", editor)
    assert editor.canvas.collection_session is None and editor.canvas.can_redo
    _invoke(window, "_ensure_collection_session", editor)
    session = cast("DrawingCollectionSession | None", vars(editor.canvas)["collection_session"])
    assert session is not None
    assert editor.canvas.redo_last_operation()
    assert tuple(editor.canvas.entities) == (moved_second,)
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == moved_saved
    )
    assert editor.canvas.undo_last_operation()
    assert tuple(editor.canvas.entities) == (second,)
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == saved
    )


def test_adopting_mixed_history_preserves_tangencies_and_transform_evidence(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        RectangleTransformEvidence,
        map_transformed_rectangle_segments,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, RectangleEntity, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import rotate_entities
    from mycad.ui.sketch_editor import MixedMoveState

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, -20))
    circle = CircleEntity(uuid4().hex, (5, -5), 5)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    circle_ref = SketchGeometryReference(circle.entity_id, "geometry")
    initial_pairs = tuple(
        (SketchGeometryReference(rectangle.entity_id, "segment", index), circle_ref)
        for index in (0, 3)
    )
    expected_relations = app.draft_cross_relations((saved,), draft, initial_pairs)
    rotated_rectangle, rotated_circle = rotate_entities(
        (rectangle, circle), (rectangle.entity_id, circle.entity_id), (0, 0), 90
    )
    evidence = RectangleTransformEvidence(
        CrossSketchRef(saved.sketch_id, rectangle.entity_id), (0, -1, 1, 0, 0, 0)
    )
    segment_mapping = map_transformed_rectangle_segments(
        rectangle, rotated_rectangle, evidence.apply
    )
    changed_pairs = tuple(
        (
            SketchGeometryReference(rectangle.entity_id, "segment", segment_mapping[index][0]),
            circle_ref,
        )
        for index in (0, 3)
    )
    changed_saved = replace(saved, entities=(rotated_rectangle,))
    changed_draft = replace(draft, entities=(rotated_circle,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    checkpoints = session.adopt_mixed_history(
        draft,
        (saved,),
        (((changed_saved,), changed_draft),),
        cross_pairs_by_step=(changed_pairs,),
        initial_cross_pairs=initial_pairs,
        arrays_by_step=((),),
        initial_arrays=(),
        transforms_by_step=((evidence,),),
    )
    assert len(checkpoints) == 2
    assert {item.relation_id for item in session.snapshot.cross_tangencies} == {
        item.relation_id for item in expected_relations
    }
    session.restore(checkpoints[0])
    assert {item.relation_id: item for item in session.snapshot.cross_tangencies} == {
        item.relation_id: item for item in expected_relations
    }
    session.restore(checkpoints[1])
    assert {item.relation_id for item in session.snapshot.cross_tangencies} == {
        item.relation_id for item in expected_relations
    }
    session.cancel()
    assert services.kernel.sketches == (saved,) and not services.kernel.cross_sketch_tangencies
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.set_context_sketches((saved,))
    assert editor.canvas.replace_draft_entities((circle,))
    editor.canvas.pending_cross_tangencies = list(initial_pairs)
    canvas_draft = replace(draft, sketch_id=editor.draft_sketch_id, layers=editor.layer_table)
    background = editor.canvas.background_entities
    overlay = tuple(
        (rotated_rectangle if entity.entity_id == rectangle.entity_id else entity, layer)
        for entity, layer in background
    )
    mixed = MixedMoveState(
        uuid4().hex,
        loaded.document.revision,
        canvas_draft,
        (saved,),
        (changed_saved,),
        background,
        overlay,
        initial_pairs,
        (),
        (evidence,),
    )
    editor.canvas.apply_mixed_move(mixed, (rotated_circle,), pending_pairs=changed_pairs)
    current_draft = replace(canvas_draft, entities=(rotated_circle,))
    canvas_session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, current_draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(canvas_session, canvas_draft.sketch_id)
    assert len(canvas_session.snapshot.cross_tangencies) == 2
    assert editor.canvas.undo_last_operation()
    assert {item.relation_id for item in canvas_session.snapshot.cross_tangencies} == {
        item.relation_id
        for item in app.draft_cross_relations((saved,), canvas_draft, initial_pairs)
    }
    assert editor.canvas.redo_last_operation()
    assert len(canvas_session.snapshot.cross_tangencies) == 2
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.undo_last_operation()
    assert not canvas_session.snapshot.cross_tangencies and not editor.canvas.entities
    assert editor.canvas.redo_last_operation() and editor.canvas.redo_last_operation()
    canvas_session.commit()
    editor.canvas.collection_session = None
    moved_relations = services.kernel.cross_sketch_tangencies
    path = tmp_path / "mixed-tangencies.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.cross_sketch_tangencies == moved_relations
    reopened.bus.undo_operation()
    assert {item.relation_id for item in services.kernel.cross_sketch_tangencies} == {
        item.relation_id
        for item in app.draft_cross_relations((saved,), canvas_draft, initial_pairs)
    }


def test_adopting_mixed_history_preserves_unrelated_array() -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.sketch import WorkPlaneFrame

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    saved_line = LineEntity(uuid4().hex, (0, 10), (2, 10))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = LineEntity(uuid4().hex, (5, 0), (7, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    final_draft = replace(draft, entities=(source, target))
    source_ref, target_ref = (
        ArrayEntityRef(draft.sketch_id, entity.entity_id) for entity in (source, target)
    )
    array = AssociativeRectArray(
        uuid4().hex,
        draft.frame,
        1,
        2,
        0,
        5,
        (source_ref,),
        (ArrayMember(source_ref, target_ref, 0, 1),),
    )
    moved = replace(saved, entities=(replace(saved_line, start_mm=(1, 10), end_mm=(3, 10)),))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    checkpoints = session.adopt_mixed_history(
        draft,
        (saved,),
        (((moved,), final_draft),),
        cross_pairs_by_step=((),),
        initial_cross_pairs=(),
        arrays_by_step=((array,),),
        initial_arrays=(),
        transforms_by_step=((),),
    )
    assert session.snapshot.associative_arrays == (array,)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", saved_line.entity_id, saved.sketch_id),)
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.restore(checkpoints[0])
    assert session.snapshot.associative_arrays == () and session.snapshot.groups == ()
    session.restore(checkpoints[1])
    assert session.snapshot.associative_arrays == (array,)
    session.cancel()
    assert services.kernel.sketches == (saved,) and not services.kernel.associative_arrays
    initial_array_session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, final_draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    checkpoints = initial_array_session.adopt_mixed_history(
        final_draft,
        (saved,),
        (((moved,), final_draft),),
        cross_pairs_by_step=((),),
        initial_cross_pairs=(),
        arrays_by_step=((array,),),
        initial_arrays=(array,),
        transforms_by_step=((),),
    )
    initial_array_session.restore(checkpoints[0])
    initial_array_session.rebase_draft(
        replace(final_draft, entities=()),
        cross_tangent_pairs=(),
        associative_arrays=(),
    )
    assert not initial_array_session.snapshot.associative_arrays
    initial_array_session.restore(checkpoints[0])
    assert initial_array_session.snapshot.associative_arrays == (array,)
    initial_array_session.cancel()


def test_adopting_mixed_history_rolls_back_when_candidate_rebuild_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch import WorkPlaneFrame

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    second = LineEntity(uuid4().hex, (0, 2), (2, 2))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (second,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    checkpoint, snapshot, commands = (
        session.checkpoint(),
        session.snapshot,
        loaded.document.commands,
    )
    moved_saved = replace(saved, entities=(replace(first, start_mm=(3, 0), end_mm=(5, 0)),))
    moved_draft = replace(draft, entities=(replace(second, start_mm=(3, 2), end_mm=(5, 2)),))
    original = cast(
        "Callable[[DrawingCollectionSession, tuple[ReplayAppend, ...]], object]",
        vars(DrawingCollectionSession)["_build_candidate"],
    )
    calls = 0

    def fail_once(target: DrawingCollectionSession, steps: tuple[ReplayAppend, ...]) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValidationError("模拟混合历史候选失败")
        return original(target, steps)

    monkeypatch.setattr(DrawingCollectionSession, "_build_candidate", fail_once)
    with pytest.raises(ValidationError, match="模拟混合历史候选失败"):
        session.adopt_mixed_history(
            draft,
            (saved,),
            (((moved_saved,), moved_draft),),
            cross_pairs_by_step=((),),
            initial_cross_pairs=(),
            arrays_by_step=((),),
            initial_arrays=(),
            transforms_by_step=((),),
        )
    assert session.checkpoint() == checkpoint and session.snapshot == snapshot
    assert loaded.document.commands == commands and services.kernel.sketches == (saved,)
    session.cancel()


def test_adopting_mixed_history_keeps_original_candidate_when_rebuild_remains_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch import WorkPlaneFrame

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    line = LineEntity(uuid4().hex, (0, 2), (2, 2))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    checkpoint, snapshot, commands = (
        session.checkpoint(),
        session.snapshot,
        loaded.document.commands,
    )
    imported_draft = replace(draft, entities=(replace(line, start_mm=(4, 2), end_mm=(6, 2)),))
    moved_saved = replace(saved, entities=(replace(first, start_mm=(3, 0), end_mm=(5, 0)),))
    moved_draft = replace(imported_draft, entities=(replace(line, start_mm=(7, 2), end_mm=(9, 2)),))
    original = cast("Callable[..., object]", vars(DrawingCollectionSession)["_build_candidate"])
    calls = 0

    def fail_persistently(target: DrawingCollectionSession, *args: object) -> object:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise ValidationError("模拟持续的候选构建失败")
        return original(target, *args)

    monkeypatch.setattr(DrawingCollectionSession, "_build_candidate", fail_persistently)
    with pytest.raises(ValidationError, match="模拟持续的候选构建失败"):
        session.adopt_mixed_history(
            imported_draft,
            (saved,),
            (((moved_saved,), moved_draft),),
            cross_pairs_by_step=((),),
            initial_cross_pairs=(),
            arrays_by_step=((),),
            initial_arrays=(),
            transforms_by_step=((),),
        )
    assert session.checkpoint() == checkpoint and session.snapshot == snapshot
    assert loaded.document.commands == commands and services.kernel.sketches == (saved,)
    session.commit()
    assert services.kernel.sketches == (saved, draft)


def test_command_group_copy_saved_and_draft_reopens_with_step_undo(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt

    from mycad.core.persistence import save_document
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    second = LineEntity(uuid4().hex, (0, 2), (2, 2))
    assert editor.canvas.replace_draft_entities((second,))
    editor.canvas.selected_entity_ids = {first.entity_id, second.entity_id}
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and len(session.snapshot.groups) == 1
    editor.canvas.selected_entity_ids = {first.entity_id}
    editor.canvas.begin_transform("copy")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert len(session.snapshot.groups) == 2
    editor.canvas.cancel_transform()
    editor.finish_sketch()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and window.active_sketch_dialog() is not editor)
    path = tmp_path / "command-group-copy.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.drawing_groups) == 2
    reopened.bus.undo_operation()
    assert len(services.kernel.drawing_groups) == 1
    assert services.kernel.sketches[0].entities == (first,)
    assert services.kernel.sketches[-1].entities == (second,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == ()


def test_saved_selectable_group_blocks_single_text_update_without_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    text = DrawingText(uuid4().hex, "文字", (0, 0))
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("text", text.text_id),))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    tools = editor.canvas.text_tools
    assert tools is not None and tools.execute is not None
    before = loaded.document.commands
    with pytest.raises(ValueError, match="组选择"):
        tools.execute("drawing.text.update", replace(text, text="修改").to_mapping())
    assert loaded.document.commands == before
    assert services.kernel.drawing_texts == (text,)


def test_saved_group_move_from_datum_starts_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    datum = DatumIdentifier(uuid4().hex, "A", (4, 4), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, saved.sketch_id),
            DrawingObjectRef("datum", datum.datum_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    _invoke(window, "_sync_drawing_layers")
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.sync(
        services.kernel.drawing_tolerance_frames,
        services.kernel.drawing_datum_identifiers,
        services.kernel.drawing_reference_dimensions,
    )
    tools.selected_ids = {datum.datum_id}
    tools.selected_id = datum.datum_id
    tools.selected_kind = "datum"
    assert tools.handle_command("MOVE")
    assert editor.canvas.collection_session is not None
    assert tools.handle_command("0,0")
    assert tools.handle_command("0,3")
    session = editor.canvas.collection_session
    assert session is not None
    assert session.snapshot.datums[0].position_mm == (4, 7)
    moved = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    assert moved.entities == (replace(line, start_mm=(0, 3), end_mm=(2, 3)),)
    assert services.kernel.sketches == (saved,)


def test_saved_group_grip_is_rejected_before_any_member_changes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, saved.sketch_id),)
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    _invoke(window, "_sync_drawing_layers")
    editor.canvas.edit_handle_coordinate(
        line, SketchGeometryReference(line.entity_id, "end"), (2, 0), (3, 0)
    )
    assert editor.canvas.collection_session is not None
    assert "组选择" in editor.canvas.message
    assert services.kernel.sketches == (saved,)


@pytest.mark.parametrize("boxed", [False, True])
def test_copy_free_annotation_group_from_datum_seed(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, boxed: bool
) -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QImage, QPainter

    from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        layout_mode="shared" if boxed else "legacy",
        box_size_mm=(3, 3) if boxed else None,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),
            DrawingObjectRef("datum", datum.datum_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.selected_ids = {datum.datum_id}
    tools.selected_id = datum.datum_id
    tools.selected_kind = "datum"
    assert tools.handle_command("COPY")
    assert tools.handle_command("0,0")
    pixel = editor.canvas.local_to_screen((0, 3))
    target = editor.canvas.screen_to_local(QPointF(pixel))
    monkeypatch.setattr(editor.canvas, "_cursor", target)
    _invoke(tools, "_datum_pointer_moved", pixel)
    drawn: list[DrawingCollectionClipboard] = []

    def record(
        _painter: QPainter,
        payload: DrawingCollectionClipboard,
        _delta: tuple[float, float],
        **_kwargs: object,
    ) -> None:
        drawn.append(payload)

    monkeypatch.setattr(editor.canvas, "_draw_collection_preview", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1 and len(drawn[0].datums) == 1
    preview_datum = drawn[0].datums[0]
    assert preview_datum.label == "B"
    if boxed:
        assert preview_datum.box_size_mm != datum.box_size_mm
        assert preview_datum == tools.relayout_recorded_datum(
            preview_datum, session.snapshot.text_styles
        )
    assert tools.handle_command(f"{target[0]},{target[1]}")
    assert len(session.snapshot.groups) == 2
    assert len(session.snapshot.datums) == 2
    assert session.snapshot.datums[1].position_mm == pytest.approx((4 + target[0], 4 + target[1]))
    assert session.snapshot.datums[1].datum_id == preview_datum.datum_id
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)
    attached = replace(
        datum,
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend(
            "drawing.tolerance.batch", 28, {"update_datums": [attached.to_mapping()]}, "local"
        )
    )
    tools.selected_ids = {datum.datum_id}
    tools.selected_id = datum.datum_id
    tools.selected_kind = "datum"
    assert tools.handle_command("COPY")
    assert tools.handle_command("0,0")
    assert tools.handle_command("0,3")
    copied_group = session.snapshot.groups[-1]
    copied_geometry = next(item for item in copied_group.members if item.kind == "geometry")
    copied_datum = session.snapshot.datums[-1]
    assert copied_datum.attachment is not None
    assert copied_datum.attachment.reference.entity_id == copied_geometry.object_id
    assert copied_datum.attachment.sketch_id == copied_geometry.sketch_id
    assert editor.canvas.undo_last_operation()
    tools.selected_ids = {datum.datum_id}
    tools.selected_id = datum.datum_id
    tools.selected_kind = "datum"
    assert tools.handle_command("MOVE")
    assert tools.handle_command("0,0")
    monkeypatch.setattr(editor.canvas, "_cursor", target)
    _invoke(tools, "_datum_pointer_moved", pixel)
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1 and drawn[0].datums[0].datum_id == datum.datum_id
    assert drawn[0].datums[0].label == "A"
    assert tools.handle_command(f"{target[0]},{target[1]}")
    assert session.snapshot.datums[0].position_mm == drawn[0].datums[0].position_mm
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.datums == (attached,)
    tools.selected_ids = {datum.datum_id}
    tools.selected_id = datum.datum_id
    tools.selected_kind = "datum"
    assert tools.handle_command("MOVE")
    assert tools.handle_command("0,0")
    _invoke(tools, "_datum_pointer_moved", pixel)
    assert tools.cancel()
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert drawn == [] and session.snapshot.datums == (attached,)


def test_break_single_group_member_is_rejected_when_group_selection_enabled(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.checkpoint()
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.set_tool("单点打断")
    editor.canvas.add_coordinate_point((1, 0), exact_point=True)
    assert tuple(editor.canvas.entities) == (line,)
    assert session.checkpoint() == before and session.snapshot.groups == (group,)
    assert "组选择" in editor.canvas.message


def test_break_unselectable_group_member_maps_fragments_and_undoes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    groups = tuple(DrawingGroup(uuid4().hex, (ref,), selectable=False) for _ in range(2))
    for group in groups:
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
        )
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.set_tool("单点打断")
    before = session.checkpoint()
    history_notifications: list[bool] = []
    editor.canvas.history_recorded.connect(lambda: history_notifications.append(True))

    def reject_stage(_session: DrawingCollectionSession, _operation: ReplayAppend) -> None:
        raise ValidationError("模拟候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(DrawingCollectionSession, "stage", reject_stage)
        editor.canvas.add_coordinate_point((1, 0), exact_point=True)
    assert tuple(editor.canvas.entities) == (line,)
    assert session.checkpoint() == before and session.snapshot.groups == groups
    assert history_notifications == []
    assert "模拟候选失败" in editor.canvas.message
    editor.canvas.add_coordinate_point((1, 0), exact_point=True)
    assert history_notifications == [True]
    fragments = tuple(editor.canvas.entities)
    assert len(fragments) == 2
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in fragments
    )
    assert tuple(group.members for group in session.snapshot.groups) == (refs, refs)
    assert editor.canvas.undo_last_operation()
    assert tuple(editor.canvas.entities) == (line,)
    assert session.snapshot.groups == groups
    assert editor.canvas.redo_last_operation()
    assert tuple(editor.canvas.entities) == fragments
    assert tuple(group.members for group in session.snapshot.groups) == (refs, refs)
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "split-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert tuple(group.members for group in services.kernel.drawing_groups) == (refs, refs)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == (line,)
    assert services.kernel.drawing_groups == groups


@pytest.mark.parametrize("selectable", [False, True])
def test_split_draft_group_member_updates_members_atomically(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, selectable: bool, tmp_path: Path
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    lines = (
        LineEntity(uuid4().hex, (0, 0), (20, 0)),
        LineEntity(uuid4().hex, (15, -5), (15, 5)),
    )
    assert editor.canvas.replace_draft_entities(lines)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), lines, layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", lines[0].entity_id, draft.sketch_id),),
        selectable=selectable,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.checkpoint()
    assert editor.canvas.set_tool("分割")
    if not selectable:

        def reject_stage(_session: DrawingCollectionSession, _operation: ReplayAppend) -> None:
            raise ValidationError("模拟候选失败")

        with monkeypatch.context() as failure:
            failure.setattr(DrawingCollectionSession, "stage", reject_stage)
            editor.canvas.add_coordinate_point((13, 0), exact_point=True)
        assert tuple(editor.canvas.entities) == lines and session.checkpoint() == before
        assert "模拟候选失败" in editor.canvas.message
    editor.canvas.add_coordinate_point((13, 0), exact_point=True)
    if selectable:
        assert tuple(editor.canvas.entities) == lines
        assert session.checkpoint() == before
        assert "组选择" in editor.canvas.message
        return
    fragments = tuple(editor.canvas.entities[:2])
    assert len(editor.canvas.entities) == 3
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in fragments
    )
    assert session.snapshot.groups[0].members == refs
    assert editor.canvas.undo_last_operation()
    assert tuple(editor.canvas.entities) == lines and session.snapshot.groups == (group,)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups[0].members == refs
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "split.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups[0].members == refs
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == lines
    assert services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("saved", [False, True])
def test_trim_group_member_maps_both_surviving_fragments(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, saved: bool
) -> None:
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    lines = tuple(
        LineEntity(uuid4().hex, start, end)
        for start, end in (
            ((0, 0), (20, 0)),
            ((5, -5), (5, 5)),
            ((15, -5), (15, 5)),
        )
    )
    if saved:
        sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
        app.commit_new_sketch(services, loaded, sketch, session_identity=_session_id(window))
        editor.set_context_sketches(services.kernel.sketches)
    else:
        assert editor.canvas.replace_draft_entities(lines)
        sketch = Sketch(
            editor.draft_sketch_id, editor.current_frame(), lines, layers=editor.layer_table
        )
    ref = DrawingObjectRef("geometry", lines[0].entity_id, sketch.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    if saved:
        loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
        editor.canvas.set_source_context_revision(loaded.document.revision)
    else:
        session = DrawingCollectionSession(
            services,
            loaded,
            ReplayAppend("sketch.create", 3, sketch.to_mapping(version=3), "local"),
            session_identity=_session_id(window),
        )
        editor.canvas.attach_collection_session(session, sketch.sketch_id)
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
        )
    assert editor.canvas.set_tool("修剪")
    editor.canvas.add_coordinate_point((10, 0), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == sketch.sketch_id)
    assert len(revised.entities) == 4
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, sketch.sketch_id)
        for item in revised.entities[:2]
    )
    assert session.snapshot.groups[0].members == refs
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)


def test_trim_draft_group_member_with_same_id_in_saved_sketch(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    saved_line = LineEntity(uuid4().hex, (5, 5), (5, 15))
    saved = Sketch(uuid4().hex, editor.current_frame(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    draft_line = replace(saved_line, start_mm=(0, 10), end_mm=(20, 10))
    cutters = (LineEntity(uuid4().hex, (15, 5), (15, 15)),)
    assert editor.canvas.replace_draft_entities((draft_line, *cutters))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (draft_line, *cutters),
        layers=editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    ref = DrawingObjectRef("geometry", draft_line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    other_group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", saved_line.entity_id, saved.sketch_id),),
        selectable=True,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, other_group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("修剪")
    editor.canvas.add_coordinate_point((10, 10), exact_point=True)
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(revised.entities) == 3, editor.canvas.message
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == saved
    )
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id)
        for item in revised.entities[:2]
    )
    assert session.snapshot.groups[0].members == refs
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group, other_group)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups[0].members == refs
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "trim-same-id.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups[0].members == refs
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group, other_group)


def test_trim_saved_group_member_with_same_id_in_draft(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    saved_line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    draft_line = replace(saved_line, start_mm=(5, -5), end_mm=(5, 5))
    cutter = LineEntity(uuid4().hex, (15, -5), (15, 5))
    assert editor.canvas.replace_draft_entities((draft_line, cutter))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (draft_line, cutter),
        layers=editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    ref = DrawingObjectRef("geometry", saved_line.entity_id, saved.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    other_group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", draft_line.entity_id, draft.sketch_id),),
        selectable=True,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, other_group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("修剪")
    before = session.checkpoint()

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟修剪候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        editor.canvas.add_coordinate_point((10, 0), exact_point=True)
    assert "模拟修剪候选失败" in editor.canvas.message
    assert session.checkpoint() == before
    editor.canvas.add_coordinate_point((10, 0), exact_point=True)
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    assert len(revised.entities) == 2, editor.canvas.message
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
        == draft
    )
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, saved.sketch_id) for item in revised.entities
    )
    assert session.snapshot.groups[0].members == refs
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group, other_group)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups[0].members == refs
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "trim-saved-same-id.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups[0].members == refs
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group, other_group)


def test_trim_group_member_with_same_id_in_two_saved_sketches(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first_line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second_line = replace(first_line, start_mm=(0, 10), end_mm=(20, 10))
    first = Sketch(uuid4().hex, editor.current_frame(), (first_line,))
    second = Sketch(uuid4().hex, editor.current_frame(), (second_line,))
    app.commit_new_sketch(services, loaded, first, session_identity=_session_id(window))
    app.commit_new_sketch(services, loaded, second, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    cutters = (
        LineEntity(uuid4().hex, (5, 5), (5, 15)),
        LineEntity(uuid4().hex, (15, 5), (15, 15)),
    )
    assert editor.canvas.replace_draft_entities(cutters)
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), cutters, layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    ref = DrawingObjectRef("geometry", second_line.entity_id, second.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("修剪")
    editor.canvas.add_coordinate_point((10, 10), exact_point=True)
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == second.sketch_id)
    assert len(revised.entities) == 2, editor.canvas.message
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == first.sketch_id)
        == first
    )
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, second.sketch_id) for item in revised.entities
    )
    assert session.snapshot.groups[0].members == refs
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups[0].members == refs
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "trim-two-saved-same-id.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups[0].members == refs
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)


def test_trim_saved_same_id_without_existing_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first_line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second_line = replace(first_line, start_mm=(0, 10), end_mm=(20, 10))
    first = Sketch(uuid4().hex, editor.current_frame(), (first_line,))
    second = Sketch(uuid4().hex, editor.current_frame(), (second_line,))
    app.commit_new_sketch(services, loaded, first, session_identity=_session_id(window))
    app.commit_new_sketch(services, loaded, second, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", second_line.entity_id, second.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    _invoke(window, "_sync_drawing_layers")
    cutters = (
        LineEntity(uuid4().hex, (5, 5), (5, 15)),
        LineEntity(uuid4().hex, (15, 5), (15, 15)),
    )
    assert editor.canvas.replace_draft_entities(cutters)
    assert editor.canvas.collection_session is None
    assert editor.canvas.set_tool("修剪")
    editor.canvas.add_coordinate_point((10, 10), exact_point=True)
    session = cast("DrawingCollectionSession | None", vars(editor.canvas)["collection_session"])
    assert session is not None, editor.canvas.message
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == second.sketch_id)
    assert len(revised.entities) == 2, editor.canvas.message
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == first.sketch_id)
        == first
    )
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, second.sketch_id) for item in revised.entities
    )
    assert session.snapshot.groups[0].members == refs
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)


@pytest.mark.parametrize("saved_target", [False, True])
def test_trim_same_id_target_with_explicit_unique_boundaries(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, saved_target: bool
) -> None:
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    saved_line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    target = replace(saved_line, start_mm=(0, 10), end_mm=(20, 10))
    y = 0 if saved_target else 10
    cutters = (
        LineEntity(uuid4().hex, (5, y - 5), (5, y + 5)),
        LineEntity(uuid4().hex, (15, y - 5), (15, y + 5)),
    )
    assert editor.canvas.replace_draft_entities((target, *cutters))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (target, *cutters),
        layers=editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    owner = saved.sketch_id if saved_target else draft.sketch_id
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", target.entity_id, owner),), selectable=False
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("修剪")
    editor.canvas.set_line_edit_boundaries(frozenset(item.entity_id for item in cutters))
    editor.canvas.add_coordinate_point((10, y), exact_point=True)
    updated = next(item for item in session.snapshot.sketches if item.sketch_id == owner)
    assert len(updated.entities) == (2 if saved_target else 4), editor.canvas.message
    assert session.snapshot.groups[0].members == tuple(
        DrawingObjectRef("geometry", item.entity_id, owner) for item in updated.entities[:2]
    )
    other = draft if saved_target else saved
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == other.sketch_id)
        == other
    )
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)


@pytest.mark.parametrize("saved_boundary", [False, True])
@pytest.mark.parametrize("box", [False, True])
@pytest.mark.parametrize("select_both", [False, True])
def test_trim_selects_same_id_boundary_by_source(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    saved_boundary: bool,
    box: bool,
    select_both: bool,
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    boundary = LineEntity(uuid4().hex, (5, -5), (5, 5))
    saved = Sketch(uuid4().hex, editor.current_frame(), (boundary,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    other = replace(boundary, start_mm=(15, -5), end_mm=(15, 5))
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert editor.canvas.replace_draft_entities((target, other))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (target, other), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", target.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("修剪")
    editor.canvas.begin_line_edit_boundary_selection()
    x = 5 if saved_boundary else 15
    for picked_x in (x, 20 - x) if select_both else (x,):
        if box:
            for point in ((picked_x - 4, -9), (picked_x + 4, 9)):
                QTest.mouseClick(
                    editor.canvas,
                    Qt.MouseButton.LeftButton,
                    pos=editor.canvas.local_to_screen(point),
                )
        else:
            QTest.mouseClick(
                editor.canvas,
                Qt.MouseButton.LeftButton,
                pos=editor.canvas.local_to_screen((picked_x, 4)),
            )
    QTest.keyClick(editor.canvas, Qt.Key.Key_Return)
    assert not editor.canvas.selecting_line_edit_boundaries, editor.canvas.message
    editor.canvas.add_coordinate_point((10, 0), exact_point=True)
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    result = revised.entities[0]
    assert isinstance(result, LineEntity)
    assert (result.start_mm, result.end_mm) == (
        ((0, 0), (5, 0)) if saved_boundary or select_both else ((15, 0), (20, 0))
    )
    if select_both:
        assert isinstance(revised.entities[1], LineEntity)
        assert (revised.entities[1].start_mm, revised.entities[1].end_mm) == ((15, 0), (20, 0))
    assert revised.entities[-1] == other
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == saved
    )
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)
    if saved_boundary and not select_both and not box:
        assert editor.canvas.redo_last_operation()
        new_group = session.snapshot.groups[0]
        session.commit()
        editor.canvas.collection_session = None
        path = tmp_path / "trim-explicit-same-id.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert services.kernel.drawing_groups == (new_group,)
        reopened.bus.undo_operation()
        assert services.kernel.drawing_groups == (group,)
    if not saved_boundary and not select_both and not box:
        moved_boundary = replace(other, start_mm=(16, -5), end_mm=(16, 5))
        assert editor.canvas.replace_draft_entities((target, moved_boundary))
        before = session.checkpoint()
        editor.canvas.add_coordinate_point((10, 0), exact_point=True)
        assert "边界对象已变化" in editor.canvas.message
        assert session.checkpoint() == before


def test_trim_saved_target_with_same_id_boundary_in_draft(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (5, -5), (5, 5))
    saved = Sketch(uuid4().hex, editor.current_frame(), (target, boundary))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    other = replace(boundary, start_mm=(15, -5), end_mm=(15, 5))
    assert editor.canvas.replace_draft_entities((other,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (other,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", target.entity_id, saved.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("修剪")
    editor.canvas.begin_line_edit_boundary_selection()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((15, 4))
    )
    QTest.keyClick(editor.canvas, Qt.Key.Key_Return)
    assert not editor.canvas.selecting_line_edit_boundaries, editor.canvas.message
    editor.canvas.add_coordinate_point((10, 0), exact_point=True)
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    assert isinstance(revised.entities[0], LineEntity)
    assert (revised.entities[0].start_mm, revised.entities[0].end_mm) == ((15, 0), (20, 0)), (
        editor.canvas.message
    )
    assert revised.entities[1] == boundary
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
        == draft
    )
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)


@pytest.mark.parametrize("saved_target", [False, True])
@pytest.mark.parametrize("mode", ["修剪", "延伸"])
def test_line_edit_preview_matches_same_id_target_commit(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, saved_target: bool, mode: str
) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20 if mode == "修剪" else 10, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    other = replace(line, start_mm=(0, 10), end_mm=(line.end_mm[0], 10))
    y = 0 if saved_target else 10
    cutters = tuple(
        LineEntity(uuid4().hex, (x, y - 4), (x, y + 4))
        for x in ((5, 15) if mode == "修剪" else (15,))
    )
    assert editor.canvas.replace_draft_entities((other, *cutters))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (other, *cutters), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    owner = saved.sketch_id if saved_target else draft.sketch_id
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, owner),), selectable=False
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool(mode)
    before = session.checkpoint()
    pixel = editor.canvas.local_to_screen((10, y))
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
    preview = editor.canvas.previewed_line_edit_entities
    assert len(preview) == (2 if mode == "修剪" else 1), editor.canvas.message
    assert session.checkpoint() == before
    drawn: list[tuple[tuple[float, float], float]] = []

    def record(painter: QPainter, entity: object, **_kwargs: object) -> None:
        if isinstance(entity, LineEntity) and entity.entity_id == line.entity_id:
            drawn.append((entity.start_mm, painter.opacity()))

    with monkeypatch.context() as paint:
        paint.setattr(editor.canvas, "_draw_entity", record)
        editor.canvas.grab()
    assert ((0, 10 if saved_target else 0), 1.0) in drawn
    assert any(start == (0, y) and opacity < 0.5 for start, opacity in drawn)
    editor.canvas.add_coordinate_point((10, y), exact_point=True)
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == owner)
    result = revised.entities[: len(preview)]
    assert all(isinstance(item, LineEntity) for item in (*preview, *result))
    assert [(item.start_mm, item.end_mm) for item in preview if isinstance(item, LineEntity)] == [
        (item.start_mm, item.end_mm) for item in result if isinstance(item, LineEntity)
    ]


@pytest.mark.parametrize("mode", ["修剪", "延伸"])
def test_line_edit_preview_distinguishes_two_saved_same_id_sketches(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (20 if mode == "修剪" else 10, 0))
    second = replace(first, start_mm=(0, 10), end_mm=(first.end_mm[0], 10))
    first_sketch = Sketch(uuid4().hex, editor.current_frame(), (first,))
    second_sketch = Sketch(uuid4().hex, editor.current_frame(), (second,))
    app.commit_new_sketch(services, loaded, first_sketch, session_identity=_session_id(window))
    app.commit_new_sketch(services, loaded, second_sketch, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    cutters = tuple(
        LineEntity(uuid4().hex, (x, 6), (x, 14)) for x in ((5, 15) if mode == "修剪" else (15,))
    )
    assert editor.canvas.replace_draft_entities(cutters)
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), cutters, layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", second.entity_id, second_sketch.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool(mode)
    checkpoint = session.checkpoint()
    pixel = editor.canvas.local_to_screen((10, 10))
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
    preview = editor.canvas.previewed_line_edit_entities
    assert len(preview) == (2 if mode == "修剪" else 1)
    assert session.checkpoint() == checkpoint
    drawn: list[tuple[tuple[float, float], float]] = []

    def record(painter: QPainter, entity: object, **_kwargs: object) -> None:
        if isinstance(entity, LineEntity) and entity.entity_id == first.entity_id:
            drawn.append((entity.start_mm, painter.opacity()))

    with monkeypatch.context() as paint:
        paint.setattr(editor.canvas, "_draw_entity", record)
        editor.canvas.grab()
    assert ((0, 0), 1.0) in drawn
    assert any(start == (0, 10) and opacity < 0.5 for start, opacity in drawn)
    editor.canvas.add_coordinate_point((10, 10), exact_point=True)
    revised = next(
        item for item in session.snapshot.sketches if item.sketch_id == second_sketch.sketch_id
    )
    assert [(item.start_mm, item.end_mm) for item in preview if isinstance(item, LineEntity)] == [
        (item.start_mm, item.end_mm) for item in revised.entities if isinstance(item, LineEntity)
    ]
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == first_sketch.sketch_id)
        == first_sketch
    )
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == (group,)


@pytest.mark.parametrize("spatial_box", [False, True])
def test_explicit_boundaries_keep_geometry_source_when_selecting_spatial_boundary(
    qtbot: QtBot,
    spatial_box: bool,
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    spatial = LineEntity(uuid4().hex, (15, -10), (15, 10))
    canvas.set_background_sketches((Sketch(uuid4().hex, frame, (spatial,)),), WorkPlaneFrame.xy())
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (5, -10), (5, 10))
    assert canvas.replace_draft_entities((target, boundary))
    canvas.set_line_edit_projection_mode(1)
    assert canvas.set_tool("修剪")
    canvas.begin_line_edit_boundary_selection()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 8)))
    points = ((11, -14), (19, 14)) if spatial_box else ((15, 8),)
    for point in points:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.selected_geometry_refs == {
        DrawingObjectRef("geometry", boundary.entity_id, editor.draft_sketch_id)
    }
    assert spatial.entity_id in canvas.selected_entity_ids
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert not canvas.selecting_line_edit_boundaries, canvas.message
    canvas.add_coordinate_point((10, 0), exact_point=True)
    assert len(canvas.entities) == 3
    assert isinstance(canvas.entities[0], LineEntity) and canvas.entities[0].end_mm == (5, 0)
    assert isinstance(canvas.entities[1], LineEntity) and canvas.entities[1].start_mm == (15, 0)


@pytest.mark.parametrize("spatial_first", [False, True])
def test_explicit_planar_and_spatial_boundary_id_collision_is_rejected(
    qtbot: QtBot, spatial_first: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    canvas = editor.canvas
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    planar = LineEntity(uuid4().hex, (5, -10), (5, 10))
    spatial = replace(planar, start_mm=(15, -10), end_mm=(15, 10))
    canvas.set_background_sketches((Sketch(uuid4().hex, frame, (spatial,)),), WorkPlaneFrame.xy())
    assert canvas.replace_draft_entities((planar,))
    canvas.set_line_edit_projection_mode(1)
    assert canvas.set_tool("修剪")
    canvas.begin_line_edit_boundary_selection()
    for x in (15, 5) if spatial_first else (5, 15):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((x, 8)))
    assert "身份冲突" in canvas.message
    assert canvas.selected_entity_ids == {planar.entity_id}
    expected = (
        set[DrawingObjectRef]()
        if spatial_first
        else {DrawingObjectRef("geometry", planar.entity_id, editor.draft_sketch_id)}
    )
    assert canvas.selected_geometry_refs == expected


def test_quick_trim_deleting_group_member_removes_empty_group(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("修剪")
    editor.canvas.add_coordinate_point((10, 0), exact_point=True)
    assert not editor.canvas.entities and not session.snapshot.groups
    assert "组成员" in editor.canvas.message
    assert editor.canvas.undo_last_operation()
    assert tuple(editor.canvas.entities) == (line,) and session.snapshot.groups == (group,)


def test_trim_saved_group_rectangle_replaces_identity(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 10))
    cutter = LineEntity(uuid4().hex, (5, -5), (5, 15))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle, cutter))
    app.commit_new_sketch(services, loaded, sketch, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", rectangle.entity_id, sketch.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    assert editor.canvas.set_tool("修剪")
    editor.canvas.add_coordinate_point((10, 0), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == sketch.sketch_id)
    replacement = revised.entities[0]
    assert isinstance(replacement, PolylineEntity) and replacement.entity_id != rectangle.entity_id
    assert session.snapshot.groups[0].members == (
        DrawingObjectRef("geometry", replacement.entity_id, sketch.sketch_id),
    )
    assert services.kernel.sketches == (sketch,)
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == (group,)


def test_trim_draft_group_rectangle_replaces_identity(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 10))
    cutter = LineEntity(uuid4().hex, (5, -5), (5, 15))
    assert editor.canvas.replace_draft_entities((rectangle, cutter))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (rectangle, cutter),
        layers=editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    ref = DrawingObjectRef("geometry", rectangle.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("修剪")
    editor.canvas.add_coordinate_point((10, 0), exact_point=True)
    replacement = editor.canvas.entities[0]
    assert isinstance(replacement, PolylineEntity) and replacement.entity_id != rectangle.entity_id
    assert session.snapshot.groups[0].members == (
        DrawingObjectRef("geometry", replacement.entity_id, draft.sketch_id),
    )
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == (group,)


def test_group_move_preview_shows_effective_selection_without_staging(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter

    from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_text import DrawingText
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    lines = tuple(LineEntity(uuid4().hex, (0, y), (2, y)) for y in (0, 2))
    assert editor.canvas.replace_draft_entities(lines)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), lines, layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    text = DrawingText(uuid4().hex, "文字", (1, 1))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local")
    )
    raster = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (2, 2),
        2,
        2,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend(
            "drawing.raster.batch",
            2,
            {"action": "add", "images": [raster.to_mapping(version=2)]},
            "local",
        )
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            *(DrawingObjectRef("geometry", line.entity_id, draft.sketch_id) for line in lines),
            DrawingObjectRef("text", text.text_id),
            DrawingObjectRef("raster", raster.image_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    checkpoint = session.checkpoint()
    editor.canvas.selected_entity_ids = {lines[0].entity_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    monkeypatch.setattr(editor.canvas, "_cursor", (0, 3))
    transform_point = cast("Callable[..., None]", vars(type(editor.canvas))["_transform_point"])
    transform_point(editor.canvas, (0, 3), commit=False)
    drawn: list[DrawingCollectionClipboard] = []

    def record(
        _painter: QPainter,
        payload: DrawingCollectionClipboard,
        _delta: tuple[float, float],
        **_kwargs: object,
    ) -> None:
        drawn.append(payload)

    monkeypatch.setattr(editor.canvas, "_draw_collection_preview", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1
    assert len(drawn[0].sketches[0].entities) == 2
    assert drawn[0].texts[0].position_mm == pytest.approx((1, 4))
    assert drawn[0].rasters[0].origin_mm == pytest.approx((2, 5))
    assert session.checkpoint() == checkpoint and loaded.document.commands == ()
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert session.snapshot.texts[0].position_mm == pytest.approx((1, 4))
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.texts == (text,)
    editor.canvas.selected_entity_ids = {lines[0].entity_id}
    editor.canvas.begin_transform("copy")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    monkeypatch.setattr(editor.canvas, "_cursor", (0, 3))
    transform_point(editor.canvas, (0, 3), commit=False)
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1
    preview_geometry = {item.entity_id for sketch in drawn[0].sketches for item in sketch.entities}
    preview_text = drawn[0].texts[0].text_id
    preview_raster = drawn[0].rasters[0].image_id
    assert session.snapshot.sketches[-1].entities == lines
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    copied_geometry = {item.entity_id for item in session.snapshot.sketches[-1].entities} - {
        line.entity_id for line in lines
    }
    assert copied_geometry == preview_geometry
    assert session.snapshot.texts[-1].text_id == preview_text
    assert session.snapshot.rasters[-1].image_id == preview_raster
    assert editor.canvas.undo_copy_placement()
    editor.canvas.cancel_transform()
    assert editor.canvas.text_tools is not None
    for seed in ("text", "raster"):
        editor.canvas.selected_entity_ids.clear()
        editor.canvas.text_tools.selected_ids = {text.text_id} if seed == "text" else set()
        editor.canvas.selected_raster_ids = {raster.image_id} if seed == "raster" else set()
        editor.canvas.begin_transform("copy")
        editor.canvas.add_coordinate_point((0, 0), exact_point=True)
        transform_point(editor.canvas, (0, 3), commit=False)
        drawn.clear()
        painter = QPainter(image)
        try:
            _invoke(editor.canvas, "_draw_preview", painter)
        finally:
            painter.end()
        assert len(drawn) == 1 and drawn[0].texts and drawn[0].rasters
        preview_text = drawn[0].texts[0].text_id
        preview_raster = drawn[0].rasters[0].image_id
        editor.canvas.add_coordinate_point((0, 3), exact_point=True)
        assert session.snapshot.texts[-1].text_id == preview_text
        assert session.snapshot.rasters[-1].image_id == preview_raster
        assert editor.canvas.undo_copy_placement()
        editor.canvas.cancel_transform()


def test_copy_preview_is_not_reused_after_candidate_changes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter

    from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),)
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("copy")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    monkeypatch.setattr(editor.canvas, "_cursor", (0, 3))
    transform = cast("Callable[..., None]", vars(type(editor.canvas))["_transform_point"])
    transform(editor.canvas, (0, 3), commit=False)
    drawn: list[DrawingCollectionClipboard] = []

    def record(
        _painter: QPainter,
        payload: DrawingCollectionClipboard,
        _delta: tuple[float, float],
        **_kwargs: object,
    ) -> None:
        drawn.append(payload)

    monkeypatch.setattr(editor.canvas, "_draw_collection_preview", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1
    editor.canvas.selected_entity_ids.clear()
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert drawn == []
    editor.canvas.selected_entity_ids = {line.entity_id}
    transform(editor.canvas, (0, 3), commit=False)
    rotated = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor.canvas, "_spatial_target_frame", rotated)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert drawn == []
    monkeypatch.setattr(editor.canvas, "_spatial_target_frame", WorkPlaneFrame.xy())
    transform(editor.canvas, (0, 3), commit=False)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1
    preview_id = drawn[0].sketches[0].entities[0].entity_id
    renamed = replace(group, name="Changed")
    session.stage(ReplayAppend("drawing.group.update", 1, renamed.to_mapping(), "local"))
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert drawn == []
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert session.snapshot.groups[0] == renamed
    copied = session.snapshot.sketches[-1].entities[-1]
    assert copied.entity_id != preview_id
    assert len(session.snapshot.groups) == 2
    assert editor.canvas.undo_copy_placement()
    editor.canvas.cancel_transform()


def test_group_move_uses_geometry_identity_when_text_id_collides(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    lines = tuple(LineEntity(uuid4().hex, (0, y), (2, y)) for y in (0, 2))
    assert editor.canvas.replace_draft_entities(lines)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), lines, layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    text = DrawingText(lines[0].entity_id, "文字", (8, 8))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        tuple(DrawingObjectRef("geometry", line.entity_id, draft.sketch_id) for line in lines),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {lines[0].entity_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    moved = session.snapshot.sketches[-1].entities
    assert moved == tuple(
        replace(line, start_mm=(0, y + 3), end_mm=(2, y + 3))
        for line, y in zip(lines, (0, 2), strict=True)
    ), (editor.status_label.text(), editor.canvas.message)
    assert session.snapshot.texts == (text,)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[-1].entities == lines
    editor.canvas.selected_entity_ids = {lines[0].entity_id}
    editor.canvas.begin_transform("copy")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert len(session.snapshot.groups) == 2
    assert session.snapshot.texts == (text,)
    assert editor.canvas.undo_copy_placement()
    editor.canvas.cancel_transform()
    assert session.snapshot.groups == (group,)


@pytest.mark.parametrize("both_selected", [False, True])
def test_group_rejects_stale_picked_geometry_instead_of_using_same_id_from_other_sketch(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, both_selected: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    saved_line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    draft_line = replace(saved_line, start_mm=(0, 10), end_mm=(10, 10))
    assert editor.canvas.replace_draft_entities((draft_line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (draft_line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    ref = DrawingObjectRef("geometry", saved_line.entity_id, saved.sketch_id)
    picked = {ref}
    if both_selected:
        QTest.mouseClick(
            editor.canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier,
            editor.canvas.local_to_screen((5, 10)),
        )
        picked.add(DrawingObjectRef("geometry", draft_line.entity_id, draft.sketch_id))
    assert editor.canvas.selected_geometry_refs == picked
    operation = prepare_collection_delete(session.snapshot, (ref,))
    assert editor.canvas.stage_collection_operation(operation)
    assert editor.canvas.selected_geometry_refs == picked
    before = session.checkpoint()
    history = tuple(loaded.document.commands)
    for command in ("GROUP", "BLOCK"):
        editor.drawing_command_bar.input.setText(command)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
        assert "已变化" in editor.status_label.text()
        assert session.checkpoint() == before and session.snapshot.groups == ()
    editor.drawing_command_bar.input.setText("COPY")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((5, 0), exact_point=True)
    assert session.checkpoint() == before and session.snapshot.groups == ()
    assert "已变化" in (editor.canvas.message + editor.status_label.text())
    editor.canvas.cancel_transform()
    assert not editor.canvas.delete_selected()
    assert "已变化" in (editor.canvas.message + editor.status_label.text())
    assert session.checkpoint() == before and session.snapshot.groups == ()
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
        == draft
    )
    assert tuple(loaded.document.commands) == history


def test_group_rejects_stale_picked_dimension_with_same_id_in_other_sketch(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtTest import QTest

    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 4),
    )
    saved = Sketch(uuid4().hex, editor.current_frame(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    other = LineEntity(uuid4().hex, (0, 20), (10, 20))
    other_dimension = replace(
        dimension,
        references=(SketchGeometryReference(other.entity_id, "geometry"),),
        position_mm=(5, 24),
    )
    assert editor.canvas.replace_draft_entities((other,), new_relations=(other_dimension,))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (other,),
        (other_dimension,),
        editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    assert editor.canvas.set_tool("选择元素")
    displayed = next(
        item for item in editor.canvas.dimension_constraints() if item.position_mm == (5, 4)
    )
    rectangle = editor.canvas.dimension_label_rectangles_by_constraint()[id(displayed)]
    assert isinstance(rectangle, QRectF)
    QTest.mouseClick(editor.canvas, Qt.MouseButton.LeftButton, pos=rectangle.center().toPoint())
    ref = DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id)
    assert editor.canvas.selected_dimension_refs == {ref}
    assert editor.canvas.stage_collection_operation(
        prepare_collection_delete(session.snapshot, (ref,))
    )
    assert editor.canvas.selected_dimension_refs == {ref}
    before = session.checkpoint()
    editor.drawing_command_bar.input.setText("GROUP")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert "已变化" in editor.status_label.text()
    assert session.checkpoint() == before and session.snapshot.groups == ()
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
        == draft
    )


def test_geometry_pick_retains_sketch_owner_for_colliding_ids(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    identity = uuid4().hex
    first = LineEntity(identity, (0, 0), (10, 0))
    second = LineEntity(identity, (0, 10), (10, 10))
    third = LineEntity(identity, (0, 20), (10, 20))
    first_sketch = Sketch(uuid4().hex, editor.current_frame(), (first,))
    second_sketch = Sketch(uuid4().hex, editor.current_frame(), (second,))
    editor.canvas.set_background_sketches((first_sketch, second_sketch), editor.current_frame())
    assert editor.canvas.replace_draft_entities((third,))
    assert editor.canvas.geometry_ref_at((5, 0), editor.draft_sketch_id) == DrawingObjectRef(
        "geometry", identity, first_sketch.sketch_id
    )
    assert editor.canvas.geometry_ref_at((5, 10), editor.draft_sketch_id) == DrawingObjectRef(
        "geometry", identity, second_sketch.sketch_id
    )
    assert editor.canvas.geometry_ref_at((5, 20), editor.draft_sketch_id) == DrawingObjectRef(
        "geometry", identity, editor.draft_sketch_id
    )
    assert editor.canvas.geometry_ref_at((5, 5), editor.draft_sketch_id) is None


def test_group_command_uses_picked_sketch_when_geometry_ids_collide(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    draft = replace(first, start_mm=(0, 10), end_mm=(10, 10))
    assert editor.canvas.replace_draft_entities((draft,))
    assert editor.canvas.geometry_ref_at((5, 0), editor.draft_sketch_id) == DrawingObjectRef(
        "geometry", first.entity_id, saved.sketch_id
    )
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    assert editor.canvas.selected_entity_ids == {first.entity_id}, (
        editor.canvas.tool,
        editor.canvas.message,
    )
    picked = DrawingObjectRef("geometry", first.entity_id, saved.sketch_id)
    assert editor.canvas.selected_geometry_refs == {picked}
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None, editor.status_label.text()
    group = session.snapshot.groups[0]
    assert group.members == (DrawingObjectRef("geometry", first.entity_id, saved.sketch_id),)
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == ()
    assert editor.canvas.selected_geometry_refs == {picked}
    assert editor.canvas.redo_last_operation() and session.snapshot.groups == (group,)
    editor.canvas.selected_entity_ids.clear()
    editor.canvas.selected_entity_ids.add(first.entity_id)
    assert editor.canvas.selected_geometry_refs == set()


def test_same_id_geometry_highlights_only_direct_and_effective_members(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter
    from PySide6.QtTest import QTest

    from mycad.core.sketch import SketchEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    other = replace(first, start_mm=(0, 10), end_mm=(10, 10))
    third = LineEntity(uuid4().hex, (0, 20), (10, 20))
    assert editor.canvas.replace_draft_entities((other, third))
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    QTest.mouseMove(editor.canvas, editor.canvas.local_to_screen((30, 30)))
    saved_ref = DrawingObjectRef("geometry", first.entity_id, saved.sketch_id)
    third_ref = DrawingObjectRef("geometry", third.entity_id, editor.draft_sketch_id)
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (other, third), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (saved_ref, third_ref))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.selected_geometry_refs == {saved_ref}
    assert editor.canvas.effective_group_selection() == frozenset((saved_ref, third_ref))
    highlights: dict[tuple[float, float], bool] = {}

    def record(
        _painter: QPainter,
        entity: SketchEntity,
        *,
        highlighted: bool = False,
        layer: SketchLayer | None = None,
    ) -> None:
        del layer
        if isinstance(entity, LineEntity):
            highlights[entity.start_mm] = highlighted

    monkeypatch.setattr(editor.canvas, "_draw_entity", record)
    handles: list[tuple[float, float]] = []
    handles_method = "_entity_handles"
    original_handles = cast(
        "Callable[[SketchEntity], tuple[tuple[SketchGeometryReference, tuple[float, float]], ...]]",
        getattr(editor.canvas, handles_method),
    )

    def record_handles(
        entity: SketchEntity,
    ) -> tuple[tuple[SketchGeometryReference, tuple[float, float]], ...]:
        if isinstance(entity, LineEntity):
            handles.append(entity.start_mm)
        return original_handles(entity)

    monkeypatch.setattr(editor.canvas, "_entity_handles", record_handles)
    editor.canvas.grab()
    assert highlights == {(0, 0): True, (0, 10): False, (0, 20): True}
    assert handles == [(0, 0)]
    assert editor.canvas.selected_geometry_refs == {saved_ref}


def test_group_point_multiselect_distinguishes_same_id_in_two_sketches(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    draft = replace(first, start_mm=(0, 10), end_mm=(10, 10))
    assert editor.canvas.replace_draft_entities((draft,))
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        editor.canvas.local_to_screen((5, 10)),
    )
    saved_ref = DrawingObjectRef("geometry", first.entity_id, saved.sketch_id)
    draft_ref = DrawingObjectRef("geometry", first.entity_id, editor.draft_sketch_id)
    assert editor.canvas.selected_geometry_refs == {saved_ref, draft_ref}
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        editor.canvas.local_to_screen((5, 0)),
    )
    assert editor.canvas.selected_geometry_refs == {draft_ref}
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        editor.canvas.local_to_screen((5, 0)),
    )
    assert editor.canvas.selected_geometry_refs == {saved_ref, draft_ref}
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and set(session.snapshot.groups[0].members) == {saved_ref, draft_ref}
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == ()
    assert editor.canvas.selected_geometry_refs == {saved_ref, draft_ref}
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        editor.canvas.local_to_screen((5, 0)),
    )
    assert editor.canvas.selected_geometry_refs == {draft_ref}
    assert editor.canvas.selected_entity_ids == {first.entity_id}


@pytest.mark.parametrize("operation", ["move", "copy"])
def test_group_transform_distinguishes_same_id_in_two_sketches(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, operation: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.ui.drawing_collection_session import DrawingCollectionTransformPreview
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    second = replace(first, start_mm=(0, 10), end_mm=(10, 10))
    assert editor.canvas.replace_draft_entities((second,))
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        editor.canvas.local_to_screen((5, 10)),
    )
    refs = {
        DrawingObjectRef("geometry", first.entity_id, saved.sketch_id),
        DrawingObjectRef("geometry", second.entity_id, editor.draft_sketch_id),
    }
    assert editor.canvas.selected_geometry_refs == refs
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and set(session.snapshot.groups[0].members) == refs
    before = session.snapshot
    editor.canvas.begin_transform(operation)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.preview_collection_displacement(operation == "copy", (0, 3))
    preview_field = "_collection_transform_preview"
    preview = getattr(editor.canvas, preview_field)
    assert isinstance(preview, DrawingCollectionTransformPreview) and preview.seeds == refs
    preview_geometry = {sketch.sketch_id: sketch.entities for sketch in preview.payload.sketches}
    assert len(preview_geometry) == 2
    assert all(
        len(items) == 1 and isinstance(items[0], LineEntity) for items in preview_geometry.values()
    )
    assert {
        items[0].start_mm for items in preview_geometry.values() if isinstance(items[0], LineEntity)
    } == {(0, 3), (0, 13)}
    assert session.snapshot == before
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    after = session.snapshot
    assert all(
        set(preview_geometry[sketch.sketch_id]).issubset(sketch.entities)
        for sketch in after.sketches
        if sketch.sketch_id in preview_geometry
    )
    first_after, second_after = after.sketches[0], after.sketches[-1]
    if operation == "move":
        assert first_after.entities == (replace(first, start_mm=(0, 3), end_mm=(10, 3)),)
        assert second_after.entities == (replace(second, start_mm=(0, 13), end_mm=(10, 13)),)
        assert len(after.groups) == 1
    else:
        assert len(first_after.entities) == len(second_after.entities) == 2
        assert first_after.entities[0] == first and second_after.entities[0] == second
        assert isinstance(first_after.entities[1], LineEntity)
        assert isinstance(second_after.entities[1], LineEntity)
        assert first_after.entities[1].start_mm == (0, 3)
        assert second_after.entities[1].start_mm == (0, 13)
        assert len(after.groups) == 2
        assert editor.canvas.cancel_transform()
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / f"same-id-group-{operation}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


@pytest.mark.parametrize("operation", ["rotate", "scale", "delete"])
def test_group_affine_and_delete_distinguish_same_id_in_two_sketches(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, operation: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    second = replace(first, start_mm=(0, 10), end_mm=(10, 10))
    assert editor.canvas.replace_draft_entities((second,))
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        editor.canvas.local_to_screen((5, 10)),
    )
    refs = {
        DrawingObjectRef("geometry", first.entity_id, saved.sketch_id),
        DrawingObjectRef("geometry", second.entity_id, editor.draft_sketch_id),
    }
    assert editor.canvas.selected_geometry_refs == refs
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and set(session.snapshot.groups[0].members) == refs
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    assert editor.canvas.selected_geometry_refs == {
        DrawingObjectRef("geometry", first.entity_id, saved.sketch_id)
    }
    assert editor.canvas.effective_group_selection() == frozenset(refs)
    before = session.snapshot
    if operation == "delete":
        assert editor.canvas.delete_selected(), editor.canvas.message
    else:
        editor.canvas.begin_transform(operation)
        editor.canvas.add_coordinate_point((0, 0), exact_point=True)
        editor.canvas.preview_collection_affine(
            operation, (0, 0), 90 if operation == "rotate" else 2
        )
        preview_field = "_collection_transform_preview"
        assert getattr(editor.canvas, preview_field) is not None
        assert session.snapshot == before
        if operation == "rotate":
            assert editor.canvas.apply_rotation_angle(90)
        else:
            assert editor.canvas.apply_scale_factor(2)
    after = session.snapshot
    first_after, second_after = after.sketches[0], after.sketches[-1]
    if operation == "delete":
        assert first_after.entities == second_after.entities == () and after.groups == ()
    else:
        assert len(first_after.entities) == len(second_after.entities) == 1
        first_line, second_line = first_after.entities[0], second_after.entities[0]
        assert isinstance(first_line, LineEntity) and isinstance(second_line, LineEntity)
        if operation == "rotate":
            assert first_line.end_mm == pytest.approx((0, 10))
            assert second_line.start_mm == pytest.approx((-10, 0))
            assert second_line.end_mm == pytest.approx((-10, 10))
        else:
            assert first_line.end_mm == pytest.approx((20, 0))
            assert second_line.start_mm == pytest.approx((0, 20))
            assert second_line.end_mm == pytest.approx((20, 20))
        assert after.groups == before.groups
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / f"same-id-group-{operation}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


@pytest.mark.parametrize("rotated", [False, True])
def test_same_id_dimensions_render_against_their_own_sketch(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, rotated: bool
) -> None:
    from mycad.core.sketch import SketchEntity, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    frame = (
        WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
        if rotated
        else editor.current_frame()
    )
    first = LineEntity(uuid4().hex, (0, 0), (0, -10) if rotated else (10, 0))
    second = replace(first, start_mm=(0, 10), end_mm=(10, 10))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(2, -5) if rotated else (5, 2),
    )
    other_dimension = replace(dimension, position_mm=(5, 12))
    saved = Sketch(uuid4().hex, frame, (first,), (dimension,))
    editor.canvas.set_background_sketches((saved,), editor.current_frame())
    assert editor.canvas.replace_draft_entities((second,), new_relations=(other_dimension,))
    assert len(editor.canvas.dimension_constraints()) == 2
    projected, draft_constraint = editor.canvas.dimension_constraints()
    assert editor.canvas.dimension_basis(draft_constraint) is None
    if rotated:
        assert editor.canvas.dimension_basis(projected) == ((0, 1), (-1, 0), 1)
    records: set[tuple[tuple[float, float] | None, tuple[float, float]]] = set()
    original_layout = editor.canvas.dimension_layout

    def record(constraint: SketchConstraint, entities: dict[str, SketchEntity]) -> object:
        entity = entities[constraint.references[0].entity_id]
        assert isinstance(entity, LineEntity)
        records.add((constraint.position_mm, entity.start_mm))
        return original_layout(constraint, entities)

    monkeypatch.setattr(editor.canvas, "dimension_layout", record)
    editor.canvas.grab()
    assert records == {((5, 2), (0, 0)), ((5, 12), (0, 10))}


@pytest.mark.parametrize("crossing", [False, True])
def test_group_box_selection_distinguishes_same_id_dimensions(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, crossing: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 4),
    )
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    second = replace(first, start_mm=(0, 20), end_mm=(10, 20))
    other_dimension = replace(dimension, position_mm=(5, 24))
    assert editor.canvas.replace_draft_entities((second,), new_relations=(other_dimension,))
    assert editor.canvas.set_tool("选择元素")

    def box(y: float, modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
        left, right = ((20, y + 10), (-10, y - 8)) if crossing else ((-10, y + 10), (20, y - 8))
        start, end = editor.canvas.local_to_screen(left), editor.canvas.local_to_screen(right)
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, modifier, start)
        QTest.mouseMove(editor.canvas, end)
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, modifier, end)

    saved_ref = DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id)
    draft_ref = DrawingObjectRef("dimension", dimension.constraint_id, editor.draft_sketch_id)
    box(0)
    assert editor.canvas.selected_dimension_refs == {saved_ref}
    box(20, Qt.KeyboardModifier.ControlModifier)
    assert editor.canvas.selected_dimension_refs == {saved_ref, draft_ref}
    box(0, Qt.KeyboardModifier.ShiftModifier)
    assert editor.canvas.selected_dimension_refs == {draft_ref}
    assert editor.canvas.selected_constraint_ids == {dimension.constraint_id}
    QTest.mousePress(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((-15, -15))
    )
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert editor.canvas.selected_dimension_refs == {draft_ref}
    editor.canvas.selected_entity_ids.clear()
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and session.snapshot.groups[0].members == (draft_ref,)
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == ()
    assert editor.canvas.selected_dimension_refs == {draft_ref}


@pytest.mark.parametrize("selectable", [False, True])
def test_delete_selected_dimension_preserves_same_id_in_other_sketch(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, selectable: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 4),
    )
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    second = replace(first, start_mm=(0, 20), end_mm=(10, 20))
    other_dimension = replace(dimension, position_mm=(5, 24))
    assert editor.canvas.replace_draft_entities((second,), new_relations=(other_dimension,))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (second,),
        (other_dimension,),
        editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    saved_ref = DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id)
    draft_ref = DrawingObjectRef("dimension", dimension.constraint_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (saved_ref, draft_ref), selectable=selectable)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("选择元素")
    projected = next(
        item for item in editor.canvas.dimension_constraints() if item.position_mm == (5, 4)
    )
    rect = editor.canvas.dimension_label_rectangles_by_constraint()[id(projected)]
    QTest.mouseClick(editor.canvas, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
    assert editor.canvas.selected_dimension_refs == {saved_ref}
    before, history = session.snapshot, tuple(loaded.document.commands)

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟尺寸删除候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        assert not editor.canvas.delete_selected()
    assert "模拟尺寸删除候选失败" in editor.canvas.message
    assert session.snapshot == before and tuple(loaded.document.commands) == history
    assert editor.canvas.delete_selected(), editor.canvas.message
    after = session.snapshot
    assert after.sketches[0].constraints == ()
    assert after.sketches[-1].constraints == (() if selectable else (other_dimension,))
    assert after.groups == (() if selectable else (replace(group, members=(draft_ref,)),))
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "same-id-dimension-delete.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


@pytest.mark.parametrize("target_saved", [False, True])
def test_edit_same_id_driving_dimension_changes_only_own_sketch(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target_saved: bool
) -> None:
    from math import dist

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 4),
    )
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    second = replace(first, start_mm=(0, 20), end_mm=(10, 20))
    other_dimension = replace(dimension, position_mm=(5, 24))
    assert editor.canvas.replace_draft_entities((second,), new_relations=(other_dimension,))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (second,),
        (other_dimension,),
        editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id),
            DrawingObjectRef("dimension", dimension.constraint_id, draft.sketch_id),
        ),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("选择元素")
    shown = next(
        item
        for item in editor.canvas.dimension_constraints()
        if item.position_mm == ((5, 4) if target_saved else (5, 24))
    )
    rect = editor.canvas.dimension_label_rectangles_by_constraint()[id(shown)]
    QTest.mouseDClick(editor.canvas, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
    original = saved if target_saved else draft
    assert editor.dimensions.original == original
    before, history = session.snapshot, tuple(loaded.document.commands)
    editor.dimensions.value_editor.setValue(12)
    candidate = editor.dimensions.candidate
    assert candidate is not None and candidate.value == 12
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, candidate) is not None, timeout=15000
    )
    preview = editor.dimensions.accepted_preview(original, candidate)
    assert preview is not None and preview.status == "success", editor.status_label.text()
    assert session.snapshot == before
    from mycad.core.exceptions import ValidationError

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟同 ID 尺寸候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        editor.dimensions.apply_button.click()
        qtbot.waitUntil(
            lambda: "模拟同 ID 尺寸候选失败" in editor.status_label.text(), timeout=15000
        )
    assert session.snapshot == before and tuple(loaded.document.commands) == history
    editor.dimensions.apply_button.click()
    qtbot.waitUntil(lambda: session.snapshot != before, timeout=15000)
    after = session.snapshot
    changed = after.sketches[0] if target_saved else after.sketches[-1]
    untouched = after.sketches[-1] if target_saved else after.sketches[0]
    line = changed.entities[0]
    assert isinstance(line, LineEntity) and dist(line.start_mm, line.end_mm) == pytest.approx(12)
    assert changed.constraints[0].value == 12 and untouched == (draft if target_saved else saved)
    assert after.groups == (group,) and tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "same-id-driving-dimension.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


def test_saved_selectable_group_blocks_dimension_drag_without_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 4),
    )
    saved = Sketch(uuid4().hex, editor.current_frame(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id),)
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    _invoke(window, "_sync_drawing_layers")
    assert editor.canvas.collection_session is None and editor.canvas.set_tool("选择元素")
    projected = editor.canvas.dimension_constraints()[0]
    start = (
        editor.canvas.dimension_label_rectangles_by_constraint()[id(projected)].center().toPoint()
    )
    end = editor.canvas.local_to_screen((8, 8))
    history = tuple(loaded.document.commands)
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert "组选择" in editor.status_label.text()
    assert editor.canvas.collection_session is None
    assert tuple(loaded.document.commands) == history
    assert services.kernel.sketches == (saved,) and services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("selectable", [False, True, "other"])
@pytest.mark.parametrize("target_saved", [False, True])
def test_drag_same_id_dimension_commits_only_selected_sketch(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target_saved: bool,
    selectable: bool | str,
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 4),
    )
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    second = replace(first, start_mm=(0, 20), end_mm=(10, 20))
    other_dimension = replace(dimension, position_mm=(5, 24))
    assert editor.canvas.replace_draft_entities((second,), new_relations=(other_dimension,))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (second,),
        (other_dimension,),
        editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    members = (DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id),)
    if selectable != "other":
        members += (DrawingObjectRef("dimension", dimension.constraint_id, draft.sketch_id),)
    group = DrawingGroup(uuid4().hex, members, selectable=bool(selectable))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("选择元素")
    target = next(
        item
        for item in editor.canvas.dimension_constraints()
        if item.position_mm == ((5, 4) if target_saved else (5, 24))
    )
    start = editor.canvas.dimension_label_rectangles_by_constraint()[id(target)].center().toPoint()
    end = editor.canvas.local_to_screen((8, 8 if target_saved else 28))
    before, history = session.snapshot, tuple(loaded.document.commands)
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    if selectable is True or (selectable == "other" and target_saved):
        qtbot.waitUntil(lambda: "组选择" in editor.status_label.text(), timeout=8000)
        assert session.snapshot == before and tuple(loaded.document.commands) == history
        return
    try:
        qtbot.waitUntil(lambda: session.snapshot != before, timeout=8000)
    except Exception as exc:
        raise AssertionError(editor.status_label.text()) from exc
    after = session.snapshot
    selected = after.sketches[0] if target_saved else after.sketches[-1]
    untouched = after.sketches[-1] if target_saved else after.sketches[0]
    assert selected.constraints[0].text_position_mm == pytest.approx(
        (8, 8 if target_saved else 28), abs=0.3
    )
    assert untouched == (draft if target_saved else saved)
    assert after.groups == (group,) and tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "same-id-dimension-drag.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


@pytest.mark.parametrize("target_saved", [False, True])
def test_dragging_same_id_dimension_keeps_other_sketch_visible_in_preview(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, target_saved: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import SketchEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 4),
    )
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    second = replace(first, start_mm=(0, 20), end_mm=(10, 20))
    other_dimension = replace(dimension, position_mm=(5, 24))
    assert editor.canvas.replace_draft_entities((second,), new_relations=(other_dimension,))
    assert editor.canvas.set_tool("选择元素")
    projected = next(
        item
        for item in editor.canvas.dimension_constraints()
        if item.position_mm == ((5, 4) if target_saved else (5, 24))
    )
    rect = editor.canvas.dimension_label_rectangles_by_constraint()[id(projected)]
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
    QTest.mouseMove(editor.canvas, editor.canvas.local_to_screen((8, 8 if target_saved else 28)))
    assert editor.canvas.dimension_candidate is not None
    records: set[tuple[tuple[float, float] | None, tuple[float, float]]] = set()
    original_layout = editor.canvas.dimension_layout

    def record(constraint: SketchConstraint, entities: dict[str, SketchEntity]) -> object:
        entity = entities[constraint.references[0].entity_id]
        assert isinstance(entity, LineEntity)
        records.add((constraint.position_mm, entity.start_mm))
        return original_layout(constraint, entities)

    monkeypatch.setattr(editor.canvas, "dimension_layout", record)
    editor.canvas.grab()
    assert records == {((5, 4), (0, 0)), ((5, 24), (0, 20))}
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert services.kernel.sketches == (saved,)
    from mycad.core.sketch_constraints import SketchConstraintSolveResult

    shifted = replace(saved, entities=(replace(first, start_mm=(0, 3), end_mm=(10, 3)),))
    editor.show_dimension_preview(SketchConstraintSolveResult("success", shifted, None))
    records.clear()
    editor.canvas.grab()
    assert records == {((5, 4), (0, 3)), ((5, 24), (0, 20))}
    editor.clear_dimension_preview()


def test_same_id_dimensions_highlight_only_selected_sketch(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter, QPen
    from PySide6.QtTest import QTest

    from mycad.core.sketch import SketchEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow
    from mycad.ui.sketch_editor import DimensionLayout

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 4),
    )
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    second = replace(first, start_mm=(0, 20), end_mm=(10, 20))
    other_dimension = replace(dimension, position_mm=(5, 24))
    assert editor.canvas.replace_draft_entities((second,), new_relations=(other_dimension,))
    assert editor.canvas.set_tool("选择元素")
    projected = next(
        item for item in editor.canvas.dimension_constraints() if item.position_mm == (5, 4)
    )
    rect = editor.canvas.dimension_label_rectangles_by_constraint()[id(projected)]
    QTest.mouseClick(editor.canvas, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
    QTest.mouseMove(editor.canvas, editor.canvas.local_to_screen((35, 35)))
    picked = DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id)
    assert editor.canvas.selected_dimension_refs == {picked}
    lines: dict[tuple[float, float], bool] = {}
    widths: dict[tuple[float, float] | None, float] = {}

    def record_entity(
        _painter: QPainter,
        entity: SketchEntity,
        *,
        highlighted: bool = False,
        layer: SketchLayer | None = None,
    ) -> None:
        del layer
        if isinstance(entity, LineEntity):
            lines[entity.start_mm] = highlighted

    def record_dimension(
        painter: QPainter,
        _layout: DimensionLayout,
        _scale: float,
        constraint: SketchConstraint | None = None,
        *,
        extension_pen: QPen | None = None,
        second_extension_pen: QPen | None = None,
    ) -> None:
        del extension_pen, second_extension_pen
        assert constraint is not None
        widths[constraint.position_mm] = painter.pen().widthF()

    monkeypatch.setattr(editor.canvas, "_draw_entity", record_entity)
    monkeypatch.setattr(editor.canvas, "_draw_dimension_lines", record_dimension)
    editor.canvas.grab()
    assert lines == {(0, 0): True, (0, 20): False}
    assert widths[(5, 4)] > widths[(5, 24)]
    unselected_width = widths[(5, 24)]
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (second,),
        (other_dimension,),
        editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (picked, DrawingObjectRef("dimension", dimension.constraint_id, draft.sketch_id)),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.selected_dimension_refs == {picked}
    widths.clear()
    editor.canvas.grab()
    assert widths[(5, 4)] > unselected_width and widths[(5, 24)] > unselected_width
    assert editor.canvas.selected_dimension_refs == {picked}


def test_group_command_selects_dimension_with_same_id_in_other_sketch(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 4),
    )
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    second = replace(first, start_mm=(0, 20), end_mm=(10, 20))
    draft_dimension = replace(dimension, position_mm=(5, 24))
    assert editor.canvas.replace_draft_entities((second,), new_relations=(draft_dimension,))
    assert editor.canvas.set_tool("选择元素")
    projected = next(
        item for item in editor.canvas.dimension_constraints() if item.position_mm == (5, 4)
    )
    rectangles = editor.canvas.dimension_label_rectangles_by_constraint()
    from PySide6.QtCore import QRectF

    rect = rectangles[id(projected)]
    assert isinstance(rect, QRectF)
    QTest.mouseClick(editor.canvas, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
    picked = DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id)
    assert editor.canvas.selected_dimension_refs == {picked}
    draft_ref = DrawingObjectRef("dimension", dimension.constraint_id, editor.draft_sketch_id)
    draft_rect = rectangles[id(draft_dimension)]
    assert isinstance(draft_rect, QRectF)
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        draft_rect.center().toPoint(),
    )
    assert editor.canvas.selected_dimension_refs == {picked, draft_ref}
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        draft_rect.center().toPoint(),
    )
    assert editor.canvas.selected_dimension_refs == {picked}
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and session.snapshot.groups[0].members == (picked,)
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == ()
    assert editor.canvas.selected_dimension_refs == {picked}


@pytest.mark.parametrize("with_dimensions", [False, True])
def test_clipboard_preserves_group_members_with_same_id_in_two_sketches(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, with_dimensions: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 2),
    )
    saved = Sketch(
        uuid4().hex, editor.current_frame(), (first,), (dimension,) if with_dimensions else ()
    )
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    second = replace(first, start_mm=(0, 10), end_mm=(10, 10))
    other_dimension = replace(dimension, position_mm=(5, 12))
    assert editor.canvas.replace_draft_entities(
        (second,), new_relations=(other_dimension,) if with_dimensions else ()
    )
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (second,),
        (other_dimension,) if with_dimensions else (),
        editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    saved_ref = DrawingObjectRef("geometry", first.entity_id, saved.sketch_id)
    draft_ref = DrawingObjectRef("geometry", second.entity_id, draft.sketch_id)
    members = (saved_ref, draft_ref)
    if with_dimensions:
        members += (
            DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id),
            DrawingObjectRef("dimension", other_dimension.constraint_id, draft.sketch_id),
        )
    group = DrawingGroup(uuid4().hex, members)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    assert editor.canvas.selected_geometry_refs == {saved_ref}
    before = session.snapshot
    try:
        assert editor.canvas.copy_to_clipboard(), editor.canvas.message
        assert editor.canvas.begin_clipboard_paste(), editor.canvas.message
        editor.canvas.add_coordinate_point((0, 30), exact_point=True)
        after = session.snapshot
        assert len(after.groups) == 2
        cloned_group = after.groups[-1]
        assert len(cloned_group.members) == len(group.members)
        assert set(cloned_group.members).isdisjoint(group.members)
        copied_lines = {
            (sketch.sketch_id, entity.entity_id): entity
            for sketch in after.sketches
            for entity in sketch.entities
        }
        geometry_refs = [ref for ref in cloned_group.members if ref.kind == "geometry"]
        assert all(ref.sketch_id is not None for ref in geometry_refs)
        cloned = [
            copied_lines[(cast("str", ref.sketch_id), ref.object_id)] for ref in geometry_refs
        ]
        assert all(isinstance(item, LineEntity) for item in cloned)
        assert {item.start_mm for item in cloned if isinstance(item, LineEntity)} == {
            (0, 30),
            (0, 40),
        }
        assert len({item.entity_id for item in cloned}) == 2
        if with_dimensions:
            cloned_dimensions = [ref for ref in cloned_group.members if ref.kind == "dimension"]
            assert len(cloned_dimensions) == 2
            assert len({ref.object_id for ref in cloned_dimensions}) == 2
            for ref in cloned_dimensions:
                sketch = next(item for item in after.sketches if item.sketch_id == ref.sketch_id)
                constraint = next(
                    item for item in sketch.constraints if item.constraint_id == ref.object_id
                )
                assert constraint.references[0].entity_id == sketch.entities[0].entity_id
        assert editor.canvas.undo_last_operation() and session.snapshot == before
        assert editor.canvas.redo_last_operation() and session.snapshot == after
        session.commit()
        editor.canvas.collection_session = None
        path = tmp_path / "same-id-clipboard.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        reopened.bus.undo_operation()
        assert app.drawing_collection_snapshot(services) == before
    finally:
        QApplication.clipboard().clear()


def test_partial_copy_of_disabled_group_distinguishes_same_id_in_two_sketches(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    second = replace(first, start_mm=(0, 10), end_mm=(10, 10))
    assert editor.canvas.replace_draft_entities((second,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (second,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    saved_ref = DrawingObjectRef("geometry", first.entity_id, saved.sketch_id)
    draft_ref = DrawingObjectRef("geometry", second.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (saved_ref, draft_ref), selectable=False)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    assert editor.canvas.selected_geometry_refs == {saved_ref}
    before = session.snapshot
    editor.canvas.begin_transform("copy")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    after = session.snapshot
    assert len(after.sketches[0].entities) == 2
    assert after.sketches[-1].entities == (second,) and after.groups == (group,)
    copied = after.sketches[0].entities[1]
    assert isinstance(copied, LineEntity) and copied.start_mm == (0, 3)
    assert copied.entity_id != first.entity_id
    assert editor.canvas.cancel_transform()
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "partial-same-id-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before


@pytest.mark.parametrize("crossing", [False, True])
def test_group_box_selection_distinguishes_same_id_in_two_sketches(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, crossing: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    draft = replace(first, start_mm=(0, 10), end_mm=(10, 10))
    assert editor.canvas.replace_draft_entities((draft,))
    assert editor.canvas.set_tool("选择元素")

    def box(y: float, modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
        left, right = ((12, y + 2), (-2, y - 2)) if crossing else ((-2, y + 2), (12, y - 2))
        start, end = editor.canvas.local_to_screen(left), editor.canvas.local_to_screen(right)
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, modifier, start)
        QTest.mouseMove(editor.canvas, end)
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, modifier, end)

    saved_ref = DrawingObjectRef("geometry", first.entity_id, saved.sketch_id)
    draft_ref = DrawingObjectRef("geometry", first.entity_id, editor.draft_sketch_id)
    box(0)
    assert editor.canvas.selected_geometry_refs == {saved_ref}
    box(10, Qt.KeyboardModifier.ControlModifier)
    assert editor.canvas.selected_geometry_refs == {saved_ref, draft_ref}
    box(0, Qt.KeyboardModifier.ShiftModifier)
    assert editor.canvas.selected_geometry_refs == {draft_ref}
    assert editor.canvas.selected_entity_ids == {first.entity_id}
    QTest.mousePress(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((-2, -4))
    )
    QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
    assert editor.canvas.selected_geometry_refs == {draft_ref}
    first_corner, second_corner = ((12, 12), (-2, -2)) if crossing else ((-2, 12), (12, -2))
    start = editor.canvas.local_to_screen(first_corner)
    end = editor.canvas.local_to_screen(second_corner)
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert editor.canvas.selected_geometry_refs == {saved_ref, draft_ref}
    box(0, Qt.KeyboardModifier.ShiftModifier)
    assert editor.canvas.selected_geometry_refs == {draft_ref}
    editor.drawing_command_bar.input.setText("GROUP")
    _invoke(qtbot, "keyClick", editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and session.snapshot.groups[0].members == (draft_ref,)
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == ()
    assert editor.canvas.selected_geometry_refs == {draft_ref}


@pytest.mark.parametrize("attached_member", [False, True])
def test_group_move_with_unrelated_attachment_and_cross_type_id_collision(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, attached_member: bool
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    other = LineEntity(uuid4().hex, (0, 5), (2, 5))
    assert editor.canvas.replace_draft_entities((first, other))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (first, other), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    text = DrawingText(first.entity_id, "文字", (8, 8))
    datum = DatumIdentifier(
        first.entity_id if attached_member else uuid4().hex,
        "A",
        (4, 9),
        (0, 0) if attached_member else (0, 5),
        attachment=DatumAttachment(
            draft.sketch_id,
            SketchGeometryReference((first if attached_member else other).entity_id, "start"),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local")
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", first.entity_id, draft.sketch_id)
    members = (ref, DrawingObjectRef("text", text.text_id))
    if attached_member:
        members += (DrawingObjectRef("datum", datum.datum_id),)
    group = DrawingGroup(uuid4().hex, members)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.snapshot
    editor.canvas.selected_entity_ids = {first.entity_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    after = session.snapshot
    assert after.sketches[-1].entities == (
        replace(first, start_mm=(0, 3), end_mm=(2, 3)),
        other,
    ), (editor.status_label.text(), editor.canvas.message)
    assert after.texts == (replace(text, position_mm=(8, 11)),)
    expected_datum = (
        replace(datum, position_mm=(4, 12), target_mm=(0, 3)) if attached_member else datum
    )
    assert after.datums == (expected_datum,) and after.groups == (group,)
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after


def test_group_mirror_replaces_draft_members_in_one_step(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter

    from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
    from mycad.core.drawing_text import DrawingText
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (1, 1), (2, 1))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    text = DrawingText(uuid4().hex, "文字", (1, 1))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),
            DrawingObjectRef("text", text.text_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("mirror", keep_source=False)
    assert editor.canvas.active_transform == "mirror", editor.canvas.message
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    assert editor.canvas.active_transform == "mirror", editor.canvas.message
    before = session.checkpoint()
    monkeypatch.setattr(editor.canvas, "_cursor", (2, 0))
    transform = cast("Callable[..., None]", vars(type(editor.canvas))["_transform_point"])
    transform(editor.canvas, (2, 0), commit=False)
    drawn: list[DrawingCollectionClipboard] = []

    def record(
        _painter: QPainter,
        payload: DrawingCollectionClipboard,
        _delta: tuple[float, float],
        **_kwargs: object,
    ) -> None:
        drawn.append(payload)

    monkeypatch.setattr(editor.canvas, "_draw_collection_preview", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1 and drawn[0].texts[0].position_mm == pytest.approx((1, -1))
    assert session.checkpoint() == before
    editor.canvas.add_coordinate_point((2, 0), exact_point=True)
    mirrored = session.snapshot.sketches[-1].entities[0]
    assert isinstance(mirrored, LineEntity)
    assert mirrored.start_mm == pytest.approx((1, -1)), (
        editor.canvas.message,
        editor.status_label.text(),
    )
    assert session.snapshot.texts[0].position_mm == pytest.approx((1, -1))
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[-1].entities == (line,)
    assert session.snapshot.texts == (text,)
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("mirror", ask_mirror_erase=True)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    transform(editor.canvas, (2, 0), commit=False)
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1
    asked_preview_line = drawn[0].sketches[0].entities[0].entity_id
    asked_preview_text = drawn[0].texts[0].text_id
    editor.canvas.add_coordinate_point((2, 0), exact_point=True)
    assert editor.canvas.awaiting_mirror_erase
    assert editor.canvas.confirm_mirror_erase(False)
    assert len(session.snapshot.groups) == 2
    assert len(session.snapshot.texts) == 2
    assert session.snapshot.sketches[-1].entities[-1].entity_id == asked_preview_line
    assert session.snapshot.texts[-1].text_id == asked_preview_text
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[-1].entities == (line,)
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("mirror", ask_mirror_erase=True)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((2, 0), exact_point=True)
    assert editor.canvas.confirm_mirror_erase(True)
    mirrored = session.snapshot.sketches[-1].entities[0]
    assert isinstance(mirrored, LineEntity)
    assert mirrored.start_mm == pytest.approx((1, -1))
    assert editor.canvas.undo_last_operation()
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("mirror", keep_source=True)
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    transform(editor.canvas, (2, 0), commit=False)
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1
    preview_line = drawn[0].sketches[0].entities[0].entity_id
    preview_text = drawn[0].texts[0].text_id
    editor.canvas.add_coordinate_point((2, 0), exact_point=True)
    assert len(session.snapshot.groups) == 2
    assert len(session.snapshot.sketches[-1].entities) == 2
    assert session.snapshot.sketches[-1].entities[-1].entity_id == preview_line
    assert session.snapshot.texts[-1].text_id == preview_text
    assert editor.canvas.undo_last_operation()


def test_group_delete_from_canvas_is_one_undo_step(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    text = DrawingText(uuid4().hex, "文字", (1, 1))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),
            DrawingObjectRef("text", text.text_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.delete_selected()
    assert session.snapshot.groups == () and session.snapshot.texts == ()
    assert session.snapshot.sketches[-1].entities == ()
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)
    assert session.snapshot.texts == (text,)
    assert session.snapshot.sketches[-1].entities == (line,)


def test_group_delete_from_canvas_removes_geometry_and_attached_datum_together(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (0, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),
            DrawingObjectRef("datum", datum.datum_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.delete_selected()
    assert not session.snapshot.groups and not session.snapshot.datums
    assert not session.snapshot.sketches[-1].entities
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,) and session.snapshot.datums == (datum,)
    assert session.snapshot.sketches[-1].entities == (line,)


def test_delete_uses_typed_group_members_when_ids_collide(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    text = DrawingText(line.entity_id, "文字", (1, 1))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local")
    )
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("text", text.text_id),))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    calls: list[bool] = []
    delete_group = editor.canvas.delete_collection_selection
    assert delete_group is not None

    def record_group_delete() -> bool:
        calls.append(True)
        return delete_group()

    editor.canvas.delete_collection_selection = record_group_delete
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.delete_selected()
    assert calls == []
    assert session.snapshot.groups == (group,)
    assert session.snapshot.texts == (text,)
    assert session.snapshot.sketches[-1].entities == ()
    assert editor.canvas.undo_last_operation()
    editor.canvas.group_selection_provider = lambda: frozenset()
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.delete_collection_selection = lambda: False
    assert not editor.canvas.delete_selected()
    assert session.snapshot.sketches[-1].entities == (line,)


def test_effective_selection_refresh_does_not_expand_overlap_recursively(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter

    from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
    from mycad.core.sketch import SketchEntity
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    lines = tuple(LineEntity(uuid4().hex, (0, y), (2, y)) for y in (0, 2, 4))
    assert editor.canvas.replace_draft_entities(lines)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), lines, layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    refs = tuple(DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in lines)
    for members in (refs[:2], refs[1:]):
        group = DrawingGroup(uuid4().hex, members)
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
        )
    editor.canvas.selected_entity_ids = {lines[0].entity_id}
    assert editor.canvas.effective_group_selection() == frozenset(refs[:2])
    assert editor.canvas.effective_group_selection() == frozenset(refs[:2])
    assert editor.canvas.selected_entity_ids == {lines[0].entity_id}
    highlights: dict[str, bool] = {}

    def record_entity(
        _painter: QPainter,
        entity: SketchEntity,
        *,
        highlighted: bool = False,
        layer: SketchLayer | None = None,
    ) -> None:
        del layer
        highlights[entity.entity_id] = highlighted

    monkeypatch.setattr(editor.canvas, "_draw_entity", record_entity)
    editor.canvas.grab()
    assert highlights[lines[0].entity_id] and highlights[lines[1].entity_id]
    assert not highlights[lines[2].entity_id]
    before = session.checkpoint()
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    monkeypatch.setattr(editor.canvas, "_cursor", (0, 3))
    transform = cast("Callable[..., None]", vars(type(editor.canvas))["_transform_point"])
    transform(editor.canvas, (0, 3), commit=False)
    drawn: list[DrawingCollectionClipboard] = []

    def record_preview(
        _painter: QPainter,
        payload: DrawingCollectionClipboard,
        _delta: tuple[float, float],
        **_kwargs: object,
    ) -> None:
        drawn.append(payload)

    monkeypatch.setattr(editor.canvas, "_draw_collection_preview", record_preview)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    for _ in range(2):
        painter = QPainter(image)
        try:
            _invoke(editor.canvas, "_draw_preview", painter)
        finally:
            painter.end()
    assert len(drawn) == 2
    assert all(
        {item.entity_id for item in preview.sketches[0].entities}
        == {lines[0].entity_id, lines[1].entity_id}
        for preview in drawn
    )
    assert session.checkpoint() == before
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert session.snapshot.sketches[-1].entities[-1] == lines[2]
    assert editor.canvas.undo_last_operation()


def test_group_rotation_from_canvas_moves_geometry_and_text_together(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter

    from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
    from mycad.core.drawing_text import DrawingText
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    text = DrawingText(uuid4().hex, "文字", (1, 0))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),
            DrawingObjectRef("text", text.text_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("rotate")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    before = session.checkpoint()
    monkeypatch.setattr(editor.canvas, "_cursor", (0, 1))
    transform = cast("Callable[..., None]", vars(type(editor.canvas))["_transform_point"])
    transform(editor.canvas, (0, 1), commit=False)
    drawn: list[DrawingCollectionClipboard] = []

    def record(
        _painter: QPainter,
        payload: DrawingCollectionClipboard,
        _delta: tuple[float, float],
        **_kwargs: object,
    ) -> None:
        drawn.append(payload)

    monkeypatch.setattr(editor.canvas, "_draw_collection_preview", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1 and drawn[0].texts[0].position_mm == pytest.approx((0, 1))
    assert session.checkpoint() == before
    assert editor.canvas.apply_rotation_angle(90)
    assert session.snapshot.texts[0].position_mm == pytest.approx((0, 1))
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.texts == (text,)
    assert session.snapshot.sketches[-1].entities == (line,)
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("rotate")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    transform(editor.canvas, (0, 1), commit=False)
    assert editor.canvas.start_rotation_reference()
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert drawn == []
    editor.canvas.set_rotation_reference_angle(0)
    assert editor.canvas.start_rotation_target_points()
    transform(editor.canvas, (0, 0), commit=True)
    monkeypatch.setattr(editor.canvas, "_cursor", (0, 1))
    transform(editor.canvas, (0, 1), commit=False)
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1 and drawn[0].texts[0].position_mm == pytest.approx((0, 1))
    monkeypatch.setattr(editor.canvas, "_cursor", (0, 0))
    transform(editor.canvas, (0, 0), commit=False)
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert drawn == []
    editor.canvas.cancel_transform()
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("rotate")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    monkeypatch.setattr(editor.canvas, "_cursor", (0, 1))
    transform(editor.canvas, (0, 1), commit=False)
    editor.canvas.configure_active_transform(reference_rotation=True, keep_source=True)
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert drawn == []
    editor.canvas.cancel_transform()


def test_group_scale_from_canvas_updates_geometry_and_text(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter

    from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
    from mycad.core.drawing_text import DrawingText
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (1, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    text = DrawingText(uuid4().hex, "文字", (1, 0), height_mm=2)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),
            DrawingObjectRef("text", text.text_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("scale")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    before = session.checkpoint()
    monkeypatch.setattr(editor.canvas, "_cursor", (2, 0))
    transform = cast("Callable[..., None]", vars(type(editor.canvas))["_transform_point"])
    transform(editor.canvas, (2, 0), commit=False)
    drawn: list[DrawingCollectionClipboard] = []

    def record(
        _painter: QPainter,
        payload: DrawingCollectionClipboard,
        _delta: tuple[float, float],
        **_kwargs: object,
    ) -> None:
        drawn.append(payload)

    monkeypatch.setattr(editor.canvas, "_draw_collection_preview", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1 and drawn[0].texts[0].height_mm == 4
    assert session.checkpoint() == before
    assert editor.canvas.apply_scale_factor(2)
    assert session.snapshot.texts[0].height_mm == 4
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.texts == (text,)
    assert session.snapshot.sketches[-1].entities == (line,)
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("scale")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    transform(editor.canvas, (2, 0), commit=False)
    assert editor.canvas.start_scale_reference()
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert drawn == []
    assert editor.canvas.apply_scale_length(10)
    assert editor.canvas.start_scale_target_points()
    transform(editor.canvas, (0, 0), commit=True)
    monkeypatch.setattr(editor.canvas, "_cursor", (20, 0))
    transform(editor.canvas, (20, 0), commit=False)
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1 and drawn[0].texts[0].height_mm == 4
    monkeypatch.setattr(editor.canvas, "_cursor", (0, 0))
    transform(editor.canvas, (0, 0), commit=False)
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert drawn == []
    editor.canvas.cancel_transform()


def test_group_clipboard_does_not_silently_copy_only_seed(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QApplication

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    lines = tuple(LineEntity(uuid4().hex, (0, y), (2, y)) for y in (0, 2))
    assert editor.canvas.replace_draft_entities(lines)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), lines, layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        tuple(DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in lines),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {lines[0].entity_id}
    assert editor.canvas.copy_to_clipboard()
    mime = QApplication.clipboard().mimeData()
    assert mime is not None and mime.hasFormat("application/x-mycad-drawing-collections+json")
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert len(session.snapshot.groups) == 2
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)
    QApplication.clipboard().clear()


def test_group_clipboard_preview_draws_each_geometry_at_paste_position(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.core.sketch import SketchEntity
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    lines = tuple(LineEntity(uuid4().hex, (0, y), (2, y)) for y in (0, 2))
    assert editor.canvas.replace_draft_entities(lines)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), lines, layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        tuple(DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in lines),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {lines[0].entity_id}
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    monkeypatch.setattr(editor.canvas, "_cursor", (5, 5))
    drawn: list[SketchEntity] = []

    def record(
        _painter: QPainter,
        entity: SketchEntity,
        *,
        highlighted: bool = False,
        layer: SketchLayer | None = None,
    ) -> None:
        del highlighted, layer
        drawn.append(entity)

    monkeypatch.setattr(editor.canvas, "_draw_entity", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
        QApplication.clipboard().clear()
        _invoke(editor.canvas, "_cancel_active_edit_gesture")
    assert len(drawn) == 2
    assert all(isinstance(item, LineEntity) for item in drawn)
    assert {item.start_mm for item in drawn if isinstance(item, LineEntity)} == {(5, 5), (5, 7)}
    assert session.snapshot.sketches[-1].entities == lines


def test_group_clipboard_preview_draws_picture_at_paste_position(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.core.drawing_raster import DrawingRaster
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    picture = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (1, 2),
        2,
        2,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend(
            "drawing.raster.batch",
            2,
            {"action": "add", "images": [picture.to_mapping(version=2)]},
            "local",
        )
    )
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("raster", picture.image_id),))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_raster_ids = {picture.image_id}
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    monkeypatch.setattr(editor.canvas, "_cursor", (5, 5))
    drawn: list[DrawingRaster] = []

    def record(_painter: QPainter, raster: DrawingRaster, **_kwargs: object) -> None:
        drawn.append(raster)

    monkeypatch.setattr(editor.canvas, "_draw_raster", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
        QApplication.clipboard().clear()
        _invoke(editor.canvas, "_cancel_active_edit_gesture")
    assert len(drawn) == 1
    assert drawn[0].origin_mm == pytest.approx((5, 5))
    assert session.snapshot.rasters == (picture,)


def test_group_clipboard_preview_draws_text_with_source_style(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.core.drawing_text import DrawingText, TextStyleTable
    from mycad.core.sketch_layers import SketchLayerTable
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    text = DrawingText(uuid4().hex, "文字", (1, 2))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local")
    )
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("text", text.text_id),))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    text_tools = editor.canvas.text_tools
    assert text_tools is not None
    text_tools.selected_ids = {text.text_id}
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    monkeypatch.setattr(editor.canvas, "_cursor", (5, 5))
    drawn: list[tuple[DrawingText, TextStyleTable]] = []
    original_draw = text_tools.draw_clipboard_preview

    def record(
        painter: QPainter, item: DrawingText, styles: TextStyleTable, layers: SketchLayerTable
    ) -> None:
        drawn.append((item, styles))
        original_draw(painter, item, styles, layers)

    monkeypatch.setattr(text_tools, "draw_clipboard_preview", record, raising=False)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
        QApplication.clipboard().clear()
        _invoke(editor.canvas, "_cancel_active_edit_gesture")
    assert len(drawn) == 1
    assert drawn[0][0].position_mm == pytest.approx((5, 5))
    assert drawn[0][1] == session.snapshot.text_styles
    assert session.snapshot.texts == (text,)


def test_nonselectable_group_clipboard_allows_partial_but_not_silent_complete_copy(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QApplication

    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    lines = tuple(LineEntity(uuid4().hex, (0, y), (2, y)) for y in (0, 2))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex,
        tuple(DrawingObjectRef("geometry", item.entity_id, saved.sketch_id) for item in lines),
        selectable=False,
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    _invoke(window, "_sync_drawing_layers")
    editor.canvas.selected_entity_ids = {lines[0].entity_id}
    assert editor.canvas.copy_to_clipboard()
    editor.canvas.selected_entity_ids = {item.entity_id for item in lines}
    assert editor.canvas.copy_to_clipboard()
    mime = QApplication.clipboard().mimeData()
    assert mime is not None and mime.hasFormat("application/x-mycad-drawing-collections+json")
    QApplication.clipboard().clear()


def test_group_clipboard_explains_missing_dimension_geometry_without_overwriting_clipboard(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QApplication

    from mycad.core.drawing_collection_clipboard import (
        DRAWING_COLLECTION_CLIPBOARD_MIME,
        decode_collection_clipboard,
    )
    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 10, "mm"
    )
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.constraints = [dimension]
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), (dimension,), editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    text = DrawingText(uuid4().hex, "说明", (1, 2))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("dimension", dimension.constraint_id, draft.sketch_id),
            DrawingObjectRef("text", text.text_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    text_tools = editor.canvas.text_tools
    assert text_tools is not None
    text_tools.selected_ids = {text.text_id}
    clipboard = QApplication.clipboard()
    clipboard.setText("existing clipboard")
    before, checkpoint = session.snapshot, session.checkpoint()
    try:
        assert not editor.canvas.copy_to_clipboard()
        assert "尺寸" in editor.canvas.message and "全部关联几何" in editor.canvas.message
        assert clipboard.text() == "existing clipboard"
        assert session.snapshot == before and session.checkpoint() == checkpoint
        assert loaded.document.commands == ()
        editor.canvas.selected_entity_ids = {line.entity_id}
        assert editor.canvas.copy_to_clipboard(), editor.canvas.message
        mime = clipboard.mimeData()
        assert mime is not None
        payload = decode_collection_clipboard(
            bytes(mime.data(DRAWING_COLLECTION_CLIPBOARD_MIME).data())
        )
        assert payload.groups == (group,)
        assert payload.sketches[0].entities == (line,)
        assert payload.sketches[0].constraints == (dimension,)
    finally:
        clipboard.clear()


def test_group_clipboard_with_dimension_pastes_and_undoes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow
    from mycad.ui.sketch_editor import SketchCanvas

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 10, "mm"
    )
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.constraints = [dimension]
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), (dimension,), editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (ref, DrawingObjectRef("dimension", dimension.constraint_id, draft.sketch_id))
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    monkeypatch.setattr(editor.canvas, "_cursor", (5, 5))
    drawn: list[tuple[SketchConstraint, LineEntity]] = []
    original_draw = cast("Callable[..., None]", vars(SketchCanvas)["_draw_constraint_overlays"])

    def record(
        canvas: SketchCanvas, painter: QPainter, effective: frozenset[str] = frozenset()
    ) -> None:
        if canvas is not editor.canvas:
            for constraint in canvas.dimension_constraints():
                entity = canvas.dimension_entities()[constraint.references[0].entity_id]
                assert isinstance(entity, LineEntity)
                drawn.append((constraint, entity))
        original_draw(canvas, painter, effective)

    monkeypatch.setattr(SketchCanvas, "_draw_constraint_overlays", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
        QApplication.clipboard().clear()
    assert len(drawn) == 1
    assert drawn[0][0].constraint_id != dimension.constraint_id
    assert drawn[0][1].start_mm == pytest.approx((5, 5))
    assert session.snapshot.sketches[-1].entities == (line,)
    editor.canvas.add_coordinate_point((5, 5), exact_point=True)
    assert len(session.snapshot.groups) == 2
    copied_group = session.snapshot.groups[-1]
    copied_dimension = next(item for item in copied_group.members if item.kind == "dimension")
    copied_geometry = next(item for item in copied_group.members if item.kind == "geometry")
    copied_sketch = next(
        item for item in session.snapshot.sketches if item.sketch_id == copied_geometry.sketch_id
    )
    assert copied_dimension.object_id == drawn[0][0].constraint_id
    assert copied_geometry.object_id == drawn[0][1].entity_id
    assert copied_sketch.constraints[0].constraint_id == copied_dimension.object_id
    assert copied_sketch.constraints[0].references[0].entity_id == copied_geometry.object_id
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)
    QApplication.clipboard().clear()


def test_clipboard_dimension_preview_keeps_sketch_identity_and_frame(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QByteArray, QMimeData
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
    from mycad.core.drawing_collection_clipboard import (
        DRAWING_COLLECTION_CLIPBOARD_MIME,
        DrawingCollectionClipboard,
        encode_collection_clipboard,
    )
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow
    from mycad.ui.sketch_editor import SketchCanvas

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    identity = uuid4().hex
    line = LineEntity(identity, (0, 0), (2, 0))
    source_font = TextStyle(height_mm=7)
    source_styles = TextStyleTable((source_font,), "standard")
    dimension_style = DimensionStyle("Clipboard", text_height=5, text_style_id="standard")
    rotated = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    sketches = tuple(
        Sketch(
            uuid4().hex,
            frame,
            (line,),
            (
                SketchConstraint(
                    uuid4().hex,
                    "length",
                    (SketchGeometryReference(identity, "geometry"),),
                    2,
                    "mm",
                    style_name="Clipboard",
                ),
            ),
        )
        for frame in (WorkPlaneFrame.xy(), rotated)
    )
    refs = tuple(
        ref
        for sketch in sketches
        for ref in (
            DrawingObjectRef("geometry", identity, sketch.sketch_id),
            DrawingObjectRef("dimension", sketch.constraints[0].constraint_id, sketch.sketch_id),
        )
    )
    payload = DrawingCollectionClipboard(
        sketches,
        (),
        (),
        (DrawingGroup(uuid4().hex, refs),),
        source_styles,
        dimension_styles=DimensionStyleTable((dimension_style,), "Clipboard"),
    )
    mime = QMimeData()
    mime.setData(
        DRAWING_COLLECTION_CLIPBOARD_MIME, QByteArray(encode_collection_clipboard(payload))
    )
    QApplication.clipboard().setMimeData(mime)
    assert editor.canvas.begin_clipboard_paste()
    monkeypatch.setattr(editor.canvas, "_cursor", (5, 5))
    drawn: list[LineEntity] = []
    original_draw = cast("Callable[..., None]", vars(SketchCanvas)["_draw_constraint_overlays"])

    def record(
        canvas: SketchCanvas, painter: QPainter, effective: frozenset[str] = frozenset()
    ) -> None:
        if canvas is not editor.canvas:
            for constraint in canvas.dimension_constraints():
                preview_style = canvas.dimension_style_for_constraint(constraint)
                assert preview_style is not None and preview_style.text_style_id is not None
                assert replace(preview_style, text_style_id="standard") == dimension_style
                preview_styles = cast(
                    "TextStyleTable", vars(canvas)["_dimension_text_styles_override"]
                )
                preview_font = preview_styles.get(preview_style.text_style_id)
                assert (
                    replace(preview_font, style_id=source_font.style_id, name=source_font.name)
                    == source_font
                )
                entity = canvas.dimension_entities()[constraint.references[0].entity_id]
                assert isinstance(entity, LineEntity)
                drawn.append(entity)
        original_draw(canvas, painter, effective)

    monkeypatch.setattr(SketchCanvas, "_draw_constraint_overlays", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
        QApplication.clipboard().clear()
        _invoke(editor.canvas, "_cancel_active_edit_gesture")
    assert len(drawn) == 2
    assert all(item.start_mm == pytest.approx((5, 5)) for item in drawn)
    assert {tuple(round(x, 5) for x in item.end_mm) for item in drawn} == {(7, 5), (5, 7)}
    assert loaded.document.commands == ()


def test_unsupported_annotation_group_clipboard_preserves_original_clipboard(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QApplication

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    external = LineEntity(uuid4().hex, (0, 5), (2, 5))
    assert editor.canvas.replace_draft_entities((line, external))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line, external), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 8),
        (0, 5),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(external.entity_id, "start")
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),
            DrawingObjectRef("datum", datum.datum_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    QApplication.clipboard().setText("existing clipboard")
    assert not editor.canvas.copy_to_clipboard()
    assert QApplication.clipboard().text() == "existing clipboard"
    assert session.snapshot.groups == (group,)


@pytest.mark.parametrize("sweep", [360.0, 120.0])
def test_group_clipboard_pastes_ellipse_from_its_center(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sweep: float
) -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.core.persistence import save_document
    from mycad.core.sketch import EllipseEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    ellipse = EllipseEntity(uuid4().hex, (2, 3), 4, 2, sweep_angle_deg=sweep)
    assert editor.canvas.replace_draft_entities((ellipse,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (ellipse,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", ellipse.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {ellipse.entity_id}
    before = session.snapshot
    try:
        assert editor.canvas.copy_to_clipboard()
        assert editor.canvas.begin_clipboard_paste()
        monkeypatch.setattr(editor.canvas, "_cursor", (10, 11))
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        try:
            _invoke(editor.canvas, "_draw_preview", painter)
        finally:
            painter.end()
        preview = editor.canvas.collection_paste_preview
        assert preview is not None and session.snapshot == before
        preview_ellipse = preview.payload.sketches[0].entities[0]
        assert isinstance(preview_ellipse, EllipseEntity)
        assert preview_ellipse.center_mm == pytest.approx((10, 11))
        editor.canvas.add_coordinate_point((10, 11), exact_point=True)
        assert len(session.snapshot.groups) == 2
        copied_ref = session.snapshot.groups[-1].members[0]
        copied = next(
            item
            for sketch in session.snapshot.sketches
            for item in sketch.entities
            if item.entity_id == copied_ref.object_id and sketch.sketch_id == copied_ref.sketch_id
        )
        assert isinstance(copied, EllipseEntity)
        assert copied.center_mm == pytest.approx((10, 11))
        assert copied.sweep_angle_deg == sweep
        assert editor.canvas.undo_last_operation() and session.snapshot == before
        assert editor.canvas.redo_last_operation() and len(session.snapshot.groups) == 2
        session.commit()
        editor.canvas.collection_session = None
        path = tmp_path / "ellipse-group.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert len(services.kernel.drawing_groups) == 2
        reopened.bus.undo_operation()
        assert services.kernel.drawing_groups == (group,)
        assert all(
            item.entity_id != copied_ref.object_id
            for sketch in services.kernel.sketches
            for item in sketch.entities
        )
    finally:
        QApplication.clipboard().clear()


def test_group_clipboard_with_attached_datum_pastes_and_undoes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QApplication

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),
            DrawingObjectRef("datum", datum.datum_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert len(session.snapshot.groups) == 2 and len(session.snapshot.datums) == 2
    copied_geometry = next(
        item for item in session.snapshot.groups[-1].members if item.kind == "geometry"
    )
    copied_datum = session.snapshot.datums[-1]
    assert copied_datum.attachment is not None
    assert copied_datum.attachment.reference.entity_id == copied_geometry.object_id
    assert copied_datum.attachment.sketch_id == copied_geometry.sketch_id
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,) and session.snapshot.datums == (datum,)
    QApplication.clipboard().clear()


def test_group_clipboard_with_only_reference_dimension_can_paste(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch_layers import SketchLayerTable
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    dimension = DetachedDimension(uuid4().hex, "aligned", (0, 2), (2, 2), (1, 3), 0, 2)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend(
            "drawing.reference_dimensions.batch", 10, {"add": [dimension.to_mapping()]}, "local"
        )
    )
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("reference_dimension", dimension.dimension_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.selected_ids = {dimension.dimension_id}
    tools.selected_id = dimension.dimension_id
    tools.selected_kind = "reference"
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    monkeypatch.setattr(editor.canvas, "_cursor", (5, 5))
    drawn: list[DetachedDimension] = []
    original_draw = tools.draw_clipboard_preview

    def record(
        painter: QPainter,
        item: DetachedDimension,
        layers: SketchLayerTable,
        styles: TextStyleTable,
    ) -> None:
        drawn.append(item)
        original_draw(painter, item, layers, styles)

    monkeypatch.setattr(tools, "draw_clipboard_preview", record, raising=False)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    QApplication.clipboard().clear()
    assert len(drawn) == 1 and drawn[0].location_mm == pytest.approx((5, 5))
    editor.canvas.add_coordinate_point((5, 5), exact_point=True)
    assert len(session.snapshot.reference_dimensions) == 2
    assert len(session.snapshot.groups) == 2
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.reference_dimensions == (dimension,)
    QApplication.clipboard().clear()


@pytest.mark.parametrize("kind", ("frame", "datum"))
def test_group_clipboard_with_only_geometric_annotation_can_paste(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.core.sketch_layers import SketchLayerTable
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    identity = uuid4().hex
    if kind == "frame":
        item = FeatureControlFrame(identity, (ToleranceRow("position", 0.1, 2),), (4, 4))
        params = {"add_frames": [item.to_mapping()]}
        ref = DrawingObjectRef("tolerance", identity)
    else:
        datum = DatumIdentifier(identity, "A", (4, 4), (1, 1))
        params = {"add_datums": [datum.to_mapping()]}
        ref = DrawingObjectRef("datum", identity)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.tolerance.batch", 28, params, "local")
    )
    group = DrawingGroup(uuid4().hex, (ref,))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.selected_ids = {identity}
    tools.selected_id = identity
    tools.selected_kind = kind
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    monkeypatch.setattr(editor.canvas, "_cursor", (5, 5))
    drawn: list[FeatureControlFrame | DatumIdentifier] = []
    original_draw = tools.draw_clipboard_preview

    def record(
        painter: QPainter,
        item: FeatureControlFrame | DatumIdentifier,
        layers: SketchLayerTable,
        styles: TextStyleTable,
    ) -> None:
        drawn.append(item)
        original_draw(painter, item, layers, styles)

    monkeypatch.setattr(tools, "draw_clipboard_preview", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
        QApplication.clipboard().clear()
    assert len(drawn) == 1 and drawn[0].position_mm == pytest.approx((5, 5))
    editor.canvas.add_coordinate_point((5, 5), exact_point=True)
    assert len(session.snapshot.groups) == 2
    assert len(session.snapshot.frames if kind == "frame" else session.snapshot.datums) == 2
    if kind == "datum":
        assert isinstance(drawn[0], DatumIdentifier)
        assert drawn[0].label == session.snapshot.datums[-1].label == "B"
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)
    QApplication.clipboard().clear()


def test_rotated_canvas_group_annotation_clipboard_preview_matches_commit(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayerTable
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (4, 4))
    datum = DatumIdentifier(uuid4().hex, "A", (6, 4), (4, 2))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend(
            "drawing.tolerance.batch",
            28,
            {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
            "local",
        )
    )
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("tolerance", frame.frame_id), DrawingObjectRef("datum", datum.datum_id)),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.selected_ids = {frame.frame_id}
    tools.selected_id, tools.selected_kind = frame.frame_id, "frame"
    assert editor.canvas.copy_to_clipboard()
    rotated = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    monkeypatch.setattr(editor, "current_frame", lambda: rotated)
    monkeypatch.setattr(editor.canvas, "_spatial_target_frame", rotated)
    assert editor.canvas.begin_clipboard_paste()
    monkeypatch.setattr(editor.canvas, "_cursor", (5, 7))
    drawn: list[FeatureControlFrame | DatumIdentifier] = []
    original = tools.draw_clipboard_preview

    def record(
        painter: QPainter,
        item: FeatureControlFrame | DatumIdentifier,
        layers: SketchLayerTable,
        styles: TextStyleTable,
    ) -> None:
        drawn.append(item)
        original(painter, item, layers, styles)

    monkeypatch.setattr(tools, "draw_clipboard_preview", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 2
    editor.canvas.add_coordinate_point((5, 7), exact_point=True)
    assert len(session.snapshot.groups) == 2
    copied_frame, copied_datum = session.snapshot.frames[-1], session.snapshot.datums[-1]
    for preview, stored in zip(drawn, (copied_frame, copied_datum), strict=True):
        expected = rotated.world_to_local(WorkPlaneFrame.xy().local_to_world(stored.position_mm))
        assert preview.position_mm == pytest.approx(expected)
    assert isinstance(drawn[0], FeatureControlFrame)
    assert drawn[0].rotation_deg == pytest.approx(copied_frame.rotation_deg - 90)
    assert isinstance(drawn[1], DatumIdentifier) and drawn[1].label == copied_datum.label
    assert replace(drawn[0], frame_id=copied_frame.frame_id) == tools.display_frame(copied_frame)
    assert replace(drawn[1], datum_id=copied_datum.datum_id) == tools.display_datum(copied_datum)
    target = rotated.world_to_local(WorkPlaneFrame.xy().local_to_world(copied_datum.target_mm))
    assert drawn[1].target_mm == pytest.approx(target)
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == (group,)
    QApplication.clipboard().clear()


def test_clipboard_preview_rebinds_frame_datum_label_like_paste(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.geometric_tolerance import (
        DatumIdentifier,
        DatumReference,
        FeatureControlFrame,
        ToleranceRow,
    )
    from mycad.core.sketch_layers import SketchLayerTable
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    datum = DatumIdentifier(uuid4().hex, "A", (6, 4), (4, 2))
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (4, 4),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend(
            "drawing.tolerance.batch",
            28,
            {"add_datums": [datum.to_mapping()], "add_frames": [frame.to_mapping()]},
            "local",
        )
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("tolerance", frame.frame_id),
            DrawingObjectRef("datum", datum.datum_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.selected_ids = {frame.frame_id}
    tools.selected_id = frame.frame_id
    tools.selected_kind = "frame"
    assert editor.canvas.copy_to_clipboard()
    assert editor.canvas.begin_clipboard_paste()
    monkeypatch.setattr(editor.canvas, "_cursor", (5, 5))
    drawn: list[FeatureControlFrame | DatumIdentifier] = []
    original_draw = tools.draw_clipboard_preview

    def record(
        painter: QPainter,
        item: FeatureControlFrame | DatumIdentifier,
        layers: SketchLayerTable,
        styles: TextStyleTable,
    ) -> None:
        drawn.append(item)
        original_draw(painter, item, layers, styles)

    monkeypatch.setattr(tools, "draw_clipboard_preview", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
        QApplication.clipboard().clear()
    preview_frame = next(item for item in drawn if isinstance(item, FeatureControlFrame))
    preview_datum = next(item for item in drawn if isinstance(item, DatumIdentifier))
    assert preview_frame.rows[0].datums[0].label == preview_datum.label == "B"
    editor.canvas.add_coordinate_point((5, 5), exact_point=True)
    assert (
        session.snapshot.frames[-1].rows[0].datums[0].label
        == session.snapshot.datums[-1].label
        == "B"
    )
    assert editor.canvas.undo_last_operation()


def test_clipboard_preview_surface_extension_uses_projected_copy_position(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.geometric_tolerance import DatumAttachment
    from mycad.core.geometric_tolerance_surface_extension import SurfaceExtensionSpec
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.geometric_tolerance_tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    attachment = DatumAttachment(
        sketch.sketch_id,
        SketchGeometryReference(line.entity_id, "geometry"),
        1,
        surface_extension=SurfaceExtensionSpec("end", 5, 1, 2),
    )
    path = editor.canvas.geometric_tolerance_tools.surface_screen_path(
        attachment, source_sketches=(sketch,), target_frame=WorkPlaneFrame.xy(), delta=(3, 4)
    )
    assert len(path) == 2
    start, end = (editor.canvas.screen_to_local(point) for point in path)
    assert start == pytest.approx((14, 4), abs=0.2)
    assert end == pytest.approx((20, 4), abs=0.2)


def test_group_paste_locked_layer_fails_without_partial_changes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QByteArray, QMimeData
    from PySide6.QtWidgets import QApplication

    from mycad.core.drawing_collection_clipboard import (
        DRAWING_COLLECTION_CLIPBOARD_MIME,
        DrawingCollectionClipboard,
        encode_collection_clipboard,
    )
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    target_layers = services.kernel.drawing_layers.add(SketchLayer("missing", locked=True))
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": target_layers.to_mapping(), "dimension_layer": services.kernel.dimension_layer},
        "local",
    )
    _invoke(window, "_sync_drawing_layers")
    before = loaded.document.commands
    line = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="missing")
    sketch = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (line,),
        layers=SketchLayerTable().add(SketchLayer("missing")),
    )
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),)
    )
    data = encode_collection_clipboard(
        DrawingCollectionClipboard((sketch,), (), (), (group,), TextStyleTable(), sketch.layers)
    )
    mime = QMimeData()
    mime.setData(DRAWING_COLLECTION_CLIPBOARD_MIME, QByteArray(data))
    QApplication.clipboard().setMimeData(mime)
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert editor.canvas.clipboard_paste_active
    assert loaded.document.commands == before and services.kernel.sketches == ()
    assert editor.canvas.collection_session is not None
    assert editor.canvas.collection_session.snapshot.groups == ()
    _invoke(editor.canvas, "_cancel_active_edit_gesture")
    QApplication.clipboard().clear()


def test_group_paste_imports_layer_and_canvas_undo_restores_it(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QByteArray, QMimeData
    from PySide6.QtWidgets import QApplication

    from mycad.core.drawing_collection_clipboard import (
        DRAWING_COLLECTION_CLIPBOARD_MIME,
        DrawingCollectionClipboard,
        encode_collection_clipboard,
    )
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = SketchLayerTable().add(SketchLayer("Detail", color_rgb=(40, 80, 120)))
    line = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="Detail")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), layers=layers)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),)
    )
    data = encode_collection_clipboard(
        DrawingCollectionClipboard((sketch,), (), (), (group,), TextStyleTable(), layers)
    )
    mime = QMimeData()
    mime.setData(DRAWING_COLLECTION_CLIPBOARD_MIME, QByteArray(data))
    QApplication.clipboard().setMimeData(mime)
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None and len(session.snapshot.groups) == 1
    assert editor.layer_table.get("Detail").color_rgb == (40, 80, 120)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == ()
    with pytest.raises(KeyError):
        editor.layer_table.get("Detail")
    assert editor.canvas.redo_last_operation()
    assert editor.layer_table.get("Detail").color_rgb == (40, 80, 120)
    QApplication.clipboard().clear()


def test_group_paste_projects_imported_dimension_styles_and_undoes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QByteArray, QMimeData
    from PySide6.QtWidgets import QApplication

    from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
    from mycad.core.drawing_collection_clipboard import (
        DRAWING_COLLECTION_CLIPBOARD_MIME,
        DrawingCollectionClipboard,
        encode_collection_clipboard,
    )
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        style_name="Imported",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id),
        ),
    )
    fonts = TextStyleTable((TextStyle(height_mm=7),), "standard")
    style = DimensionStyle("Imported", text_height=5, text_style_id="standard")
    styles = DimensionStyleTable((style,), "Imported")
    data = encode_collection_clipboard(
        DrawingCollectionClipboard((sketch,), (), (), (group,), fonts, sketch.layers, styles)
    )
    mime = QMimeData()
    mime.setData(DRAWING_COLLECTION_CLIPBOARD_MIME, QByteArray(data))
    QApplication.clipboard().setMimeData(mime)
    before_styles = editor.canvas.drawing_dimension_styles
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None and len(session.snapshot.groups) == 1
    imported = session.snapshot.dimension_styles.get("Imported")
    assert editor.canvas.drawing_dimension_styles == session.snapshot.dimension_styles
    assert imported.text_style_id is not None
    assert session.snapshot.text_styles.get(imported.text_style_id).height_mm == 7
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.drawing_dimension_styles == before_styles
    QApplication.clipboard().clear()


def test_collection_stage_follows_canvas_undo_redo_and_keeps_draft_identity(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, editor.draft_sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert session.snapshot.groups == (group,)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == ()
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups == (group,)
    assert loaded.document.commands == ()
    editor.finish_sketch()
    assert editor.result_sketch is not None
    assert editor.result_sketch.sketch_id == editor.draft_sketch_id


def test_collection_failed_stage_does_not_add_canvas_undo(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    position = editor.canvas.history_position
    invalid = DrawingGroup(uuid4().hex, (DrawingObjectRef("text", uuid4().hex),))
    assert not editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, invalid.to_mapping(), "local")
    )
    assert editor.canvas.history_position == position
    assert session.snapshot.groups == ()
    assert loaded.document.commands == ()


def test_collection_finish_rejects_unstaged_cross_sketch_relations(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    editor.canvas.pending_cross_tangencies.append((line.entity_id, uuid4().hex))
    editor.finish_sketch()
    assert editor.result_sketch is None
    assert "关联" in editor.status_label.text()
    assert loaded.document.commands == ()


def test_collection_move_updates_draft_and_reverts_with_canvas_history(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    signals: list[object] = []
    editor.canvas.collection_snapshot_changed.connect(signals.append)
    moved = replace(line, start_mm=(0, 5), end_mm=(10, 5))
    revised = replace(draft, entities=(moved,))
    state = revised.to_state_mapping()
    operation = ReplayAppend(
        "drawing.sketch.revise",
        52,
        {
            "revisions": [
                {
                    "sketch_id": draft.sketch_id,
                    "base_state_sha256": draft.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    assert editor.canvas.stage_collection_operation(operation)
    assert editor.canvas.entities == [moved]
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [line]
    assert editor.canvas.redo_last_operation()
    assert editor.canvas.entities == [moved]
    assert len(signals) == 3
    assert loaded.document.commands == ()


def test_stale_collection_undo_does_not_consume_canvas_history(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    position = editor.canvas.history_position
    getattr(loaded.document, _REVISION_METHOD)()
    assert not editor.canvas.undo_last_operation()
    assert editor.canvas.history_position == position
    assert editor.canvas.entities == [line]
    assert editor.canvas.can_undo


def test_stale_mixed_copy_undo_preserves_canvas_history(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    before = editor.canvas.history_position
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    after = editor.canvas.history_position
    getattr(loaded.document, _REVISION_METHOD)()
    assert not editor.canvas.undo_mixed_draft_copy(before, after)
    assert editor.canvas.history_position == after
    assert editor.canvas.mixed_draft_history_matches(before, after, redo=False)


def test_stale_collection_rejects_new_draft_geometry_without_exception(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 2), (10, 2))
    assert editor.canvas.replace_draft_entities((first,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (first,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    getattr(loaded.document, _REVISION_METHOD)()
    position = editor.canvas.history_position
    assert not editor.canvas.replace_draft_entities((first, second))
    assert editor.canvas.history_position == position
    assert editor.canvas.entities == [first]
    assert "变化" in editor.canvas.message


def test_stale_collection_finish_preserves_uncommitted_draft(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    getattr(loaded.document, _REVISION_METHOD)()
    editor.finish_sketch()
    assert editor.result_sketch is None
    assert editor.canvas.entities == [line]
    assert "变化" in editor.status_label.text()


def test_finishing_editor_commits_staged_group_and_draft(qtbot: QtBot) -> None:
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
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
    )
    assert services.kernel.drawing_groups == (group,)
    assert any(sketch.sketch_id == draft.sketch_id for sketch in services.kernel.sketches)


def test_layer_write_is_rejected_before_invalidating_collection_session(qtbot: QtBot) -> None:
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
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    before = tuple(loaded.document.commands)
    _invoke(window, "_on_drawing_layer_update", editor, _session_id(window), {"params": {}})
    assert not unit.is_busy
    assert tuple(loaded.document.commands) == before
    assert session.snapshot.sketches[-1] == draft
    assert "暂存" in editor.status_label.text()
    editor.status_label.clear()
    _invoke(
        window,
        "_on_drawing_assign_construction",
        editor,
        _session_id(window),
        (line.entity_id,),
        True,
    )
    assert not unit.is_busy
    assert tuple(loaded.document.commands) == before
    assert session.snapshot.sketches[-1] == draft
    assert "暂存" in editor.status_label.text()
    editor.status_label.clear()
    _invoke(window, "_on_drawing_assign_layer", editor, _session_id(window), (line.entity_id,), "0")
    assert not unit.is_busy
    assert tuple(loaded.document.commands) == before
    assert session.snapshot.sketches[-1] == draft
    assert "暂存" in editor.status_label.text()


def test_text_write_joins_session_and_restores_on_undo(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None and editor.canvas.text_tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    text = DrawingText(uuid4().hex, "draft", (0, 0))
    execute = editor.canvas.text_tools.execute
    assert execute is not None
    assert execute("drawing.text.add", text.to_mapping())
    assert loaded.document.commands == ()
    assert session.snapshot.texts == (text,)
    assert editor.canvas.text_tools.texts == (text,)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.texts == ()
    assert editor.canvas.text_tools.texts == ()
    assert editor.canvas.redo_last_operation()
    assert editor.canvas.text_tools.texts == (text,)
    editor.finish_sketch()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and window.active_sketch_dialog() is not editor)
    assert services.kernel.drawing_texts == (text,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_texts == ()


def test_text_update_and_remove_follow_session_undo(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None and editor.canvas.text_tools is not None
    original = DrawingText(uuid4().hex, "original", (0, 0))
    loaded.bus.execute("drawing.text.add", original.to_mapping(), "local")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    updated = replace(original, text="updated")
    execute = editor.canvas.text_tools.execute
    assert execute is not None
    assert execute("drawing.text.update", updated.to_mapping())
    assert execute("drawing.text.remove", {"text_id": original.text_id})
    assert services.kernel.drawing_texts == (original,)
    assert editor.canvas.text_tools.texts == ()
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.text_tools.texts == (updated,)
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.text_tools.texts == (original,)


def test_saved_geometry_projection_tracks_session_move_and_undo(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    if window.viewport is not None:
        monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    window.show()
    window.act_new_drawing.trigger()
    if window.viewport is not None:
        window.viewport.hide()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    saved_line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    editor.set_context_sketches(services.kernel.sketches)
    draft_line = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((draft_line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (draft_line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    moved = replace(saved, entities=(replace(saved_line, start_mm=(0, 2), end_mm=(10, 2)),))
    state = moved.to_state_mapping()
    operation = ReplayAppend(
        "drawing.sketch.revise",
        52,
        {
            "revisions": [
                {
                    "sketch_id": saved.sketch_id,
                    "base_state_sha256": saved.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
    )
    assert editor.canvas.stage_collection_operation(operation)
    assert [entity for entity, _layer in editor.canvas.background_entities] == list(moved.entities)
    assert services.kernel.sketches == (saved,)
    _invoke(window, "_sync_drawing_layers")
    assert [entity for entity, _layer in editor.canvas.background_entities] == list(moved.entities)
    assert editor.canvas.undo_last_operation()
    assert [entity for entity, _layer in editor.canvas.background_entities] == [saved_line]


def test_datum_write_joins_collection_session_and_undo(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    if window.viewport is not None:
        monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None and tools.execute is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    datum = DatumIdentifier(uuid4().hex, "A", (25, 25), (10, 15))
    assert tools.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]})
    assert loaded.document.commands == ()
    assert tools.datums == (datum,)
    assert editor.canvas.undo_last_operation()
    assert tools.datums == ()
    assert editor.canvas.redo_last_operation()
    assert tools.datums == (datum,)
    editor.finish_sketch()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and window.active_sketch_dialog() is not editor)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_datum_identifiers == ()


def test_mixed_clipboard_write_is_rejected_during_session(qtbot: QtBot) -> None:
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    text_tools, tolerance_tools = editor.canvas.text_tools, editor.canvas.geometric_tolerance_tools
    assert text_tools is not None and text_tools.paste_commit is not None
    assert tolerance_tools is not None and tolerance_tools.commit_mixed is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    with pytest.raises(ValueError, match="暂存"):
        text_tools.paste_commit(draft, (), services.kernel.drawing_text_styles, (), None)
    with pytest.raises(ValueError, match="暂存"):
        tolerance_tools.commit_mixed(draft, (), (), (), (), (), None, None, False)
    assert loaded.document.commands == ()
    assert session.snapshot.sketches[-1] == draft


def test_saved_dimension_commit_is_rejected_while_session_active(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.sketch_constraints import (
        SketchConstraint,
        SketchConstraintSolveResult,
        SketchGeometryReference,
    )
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
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 10, "mm"
    )
    results: list[SketchConstraintSolveResult] = []

    def record_result(
        _sketch: Sketch, _constraint: SketchConstraint, result: SketchConstraintSolveResult
    ) -> None:
        results.append(result)

    monkeypatch.setattr(editor.dimensions, "complete_commit", record_result)
    _invoke(window, "_on_canvas_dimension_commit", editor, _session_id(window), draft, dimension)
    assert not unit.is_busy
    assert len(results) == 1
    assert "暂存" in (results[0].message or "")
    assert loaded.document.commands == ()
    assert session.snapshot.sketches[-1] == draft


def test_collection_undo_restores_text_and_datum_selection(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    text_tools, tolerance_tools = editor.canvas.text_tools, editor.canvas.geometric_tolerance_tools
    assert text_tools is not None and tolerance_tools is not None
    text = DrawingText(uuid4().hex, "A", (0, 0))
    datum = DatumIdentifier(uuid4().hex, "A", (25, 25), (10, 15))
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    _invoke(window, "_sync_drawing_layers")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    text_tools.selected_ids = {text.text_id}
    tolerance_tools.selected_ids = {datum.datum_id}
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    text_tools.selected_ids.clear()
    tolerance_tools.selected_ids.clear()
    assert editor.canvas.undo_last_operation()
    assert text_tools.selected_ids == {text.text_id}
    assert tolerance_tools.selected_ids == {datum.datum_id}
    assert tolerance_tools.selected_id == datum.datum_id
    assert tolerance_tools.selected_kind == "datum"
    assert "1" in text_tools.selection_label.text()
    assert editor.canvas.redo_last_operation()
    assert text_tools.selected_ids == set()
    assert tolerance_tools.selected_ids == set()


def test_grip_edit_undo_preserves_preceding_group(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.edit_handle_coordinate(
        editor.canvas.entities[0], SketchGeometryReference(line.entity_id, "end"), (10, 0), (15, 0)
    )
    assert editor.canvas.entities[0] != line
    assert session.snapshot.sketches[-1].entities == tuple(editor.canvas.entities)
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [line]
    assert session.snapshot.groups == (group,)
    assert session.snapshot.sketches[-1].entities == (line,)


def test_grip_drag_preview_is_not_staged_until_release(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    qtbot.waitExposed(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    start = editor.canvas.local_to_screen((10, 0))
    target = editor.canvas.local_to_screen((15, 0))
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, target, delay=30)
    assert editor.canvas.entities != [line]
    assert session.snapshot.sketches[-1].entities == (line,)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=target)
    assert session.snapshot.sketches[-1].entities == tuple(editor.canvas.entities)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)
    assert session.snapshot.sketches[-1].entities == (line,)


@pytest.mark.parametrize("selectable", [False, True])
def test_trim_drag_preview_preserves_group_until_release_and_undo(
    qtbot: QtBot, selectable: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    qtbot.waitExposed(editor)
    lines = tuple(
        LineEntity(uuid4().hex, start, end)
        for start, end in (
            ((0, 0), (20, 0)),
            ((5, -5), (5, 5)),
            ((10, -5), (10, 5)),
            ((15, -5), (15, 5)),
        )
    )
    assert editor.canvas.replace_draft_entities(lines)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), lines, layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", lines[0].entity_id, draft.sketch_id),),
        selectable=selectable,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.set_snapping_enabled(False)
    editor.tool_combo.setCurrentText("修剪")
    start = editor.canvas.local_to_screen((2.5, 0))
    end = editor.canvas.local_to_screen((17.5, 0))
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    assert tuple(editor.canvas.entities) != lines
    assert session.snapshot.sketches[-1].entities == lines
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    if selectable:
        assert tuple(editor.canvas.entities) == lines
        assert session.snapshot.groups == (group,)
        return
    assert session.snapshot.sketches[-1].entities == tuple(editor.canvas.entities)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[-1].entities == lines
    assert session.snapshot.groups == (group,)


def test_trim_drag_maps_both_surviving_group_fragments(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    qtbot.waitExposed(editor)
    lines = tuple(
        LineEntity(uuid4().hex, start, end)
        for start, end in (
            ((0, 0), (20, 0)),
            ((5, -5), (5, 5)),
            ((15, -5), (15, 5)),
        )
    )
    assert editor.canvas.replace_draft_entities(lines)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), lines, layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", lines[0].entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.set_snapping_enabled(False)
    editor.tool_combo.setCurrentText("修剪")
    start = editor.canvas.local_to_screen((10, -2))
    end = editor.canvas.local_to_screen((10, 2))
    checkpoint = session.checkpoint()
    notifications: list[bool] = []
    editor.canvas.history_recorded.connect(lambda: notifications.append(True))

    def reject_stage(_session: DrawingCollectionSession, _operation: ReplayAppend) -> None:
        raise ValidationError("模拟拖动候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(DrawingCollectionSession, "stage", reject_stage)
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(editor.canvas, end)
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tuple(editor.canvas.entities) == lines and session.checkpoint() == checkpoint
    assert notifications == [] and "模拟拖动候选失败" in editor.canvas.message
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert notifications == [True]
    fragments = tuple(editor.canvas.entities[:2])
    assert len(editor.canvas.entities) == 4
    refs = tuple(
        DrawingObjectRef("geometry", entity.entity_id, draft.sketch_id) for entity in fragments
    )
    assert session.snapshot.groups[0].members == refs
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)


@pytest.mark.parametrize("selectable", [False, True])
def test_saved_trim_drag_maps_both_surviving_group_fragments(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, selectable: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    lines = tuple(
        LineEntity(uuid4().hex, start, end)
        for start, end in (
            ((0, 0), (20, 0)),
            ((5, -5), (5, 5)),
            ((15, -5), (15, 5)),
        )
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    app.commit_new_sketch(services, loaded, sketch, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", lines[0].entity_id, sketch.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=selectable)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.set_snapping_enabled(False)
    editor.tool_combo.setCurrentText("修剪")
    start, end = editor.canvas.local_to_screen((10, -2)), editor.canvas.local_to_screen((10, 2))
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    session = editor.canvas.collection_session
    if selectable:
        assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == (group,)
        assert "组选择" in editor.canvas.message
        return
    assert session is not None
    updated = next(item for item in session.snapshot.sketches if item.sketch_id == sketch.sketch_id)
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, sketch.sketch_id)
        for item in updated.entities[:2]
    )
    assert len(updated.entities) == 4 and session.snapshot.groups[0].members == refs
    assert services.kernel.sketches == (sketch,)
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == (group,)


def test_draft_trim_drag_group_rectangle_replaces_identity(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import PolylineEntity, RectangleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    qtbot.waitExposed(editor)
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 10))
    cutter = LineEntity(uuid4().hex, (5, -5), (5, 15))
    assert editor.canvas.replace_draft_entities((rectangle, cutter))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (rectangle, cutter),
        layers=editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    ref = DrawingObjectRef("geometry", rectangle.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.set_snapping_enabled(False)
    editor.tool_combo.setCurrentText("修剪")
    start, end = editor.canvas.local_to_screen((10, -2)), editor.canvas.local_to_screen((10, 2))
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    replacement = editor.canvas.entities[0]
    assert isinstance(replacement, PolylineEntity) and replacement.entity_id != rectangle.entity_id
    assert session.snapshot.groups[0].members == (
        DrawingObjectRef("geometry", replacement.entity_id, draft.sketch_id),
    )
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == (group,)


def test_saved_trim_drag_group_rectangle_replaces_identity(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import PolylineEntity, RectangleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 10))
    cutter = LineEntity(uuid4().hex, (5, -5), (5, 15))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle, cutter))
    app.commit_new_sketch(services, loaded, sketch, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", rectangle.entity_id, sketch.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.set_snapping_enabled(False)
    editor.tool_combo.setCurrentText("修剪")
    start, end = editor.canvas.local_to_screen((10, -2)), editor.canvas.local_to_screen((10, 2))
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    session = editor.canvas.collection_session
    assert session is not None
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == sketch.sketch_id)
    replacement = revised.entities[0]
    assert isinstance(replacement, PolylineEntity) and replacement.entity_id != rectangle.entity_id
    assert session.snapshot.groups[0].members == (
        DrawingObjectRef("geometry", replacement.entity_id, sketch.sketch_id),
    )
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == (group,)


def test_mixed_trim_drag_updates_saved_and_draft_group_members(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    saved_line = LineEntity(uuid4().hex, (0, 5), (20, 5))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    draft_lines = tuple(
        LineEntity(uuid4().hex, start, end)
        for start, end in (
            ((0, 0), (20, 0)),
            ((5, -5), (5, 10)),
            ((15, -5), (15, 10)),
        )
    )
    assert editor.canvas.replace_draft_entities(draft_lines)
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), draft_lines, layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", saved_line.entity_id, saved.sketch_id),
            DrawingObjectRef("geometry", draft_lines[0].entity_id, draft.sketch_id),
        ),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.set_snapping_enabled(False)
    editor.tool_combo.setCurrentText("修剪")
    start, end = editor.canvas.local_to_screen((10, -2)), editor.canvas.local_to_screen((10, 7))
    before = session.checkpoint()

    def reject_stage(_session: DrawingCollectionSession, _operation: ReplayAppend) -> None:
        raise ValidationError("模拟混合候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(DrawingCollectionSession, "stage", reject_stage)
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(editor.canvas, end)
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert session.checkpoint() == before and tuple(editor.canvas.entities) == draft_lines
    assert "模拟混合候选失败" in editor.canvas.message
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    revised_saved = next(
        item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id
    )
    revised_draft = next(
        item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id
    )
    assert len(revised_saved.entities) == 2 and len(revised_draft.entities) == 4
    expected = tuple(
        DrawingObjectRef("geometry", item.entity_id, saved.sketch_id)
        for item in revised_saved.entities
    )
    expected += tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id)
        for item in revised_draft.entities[:2]
    )
    assert session.snapshot.groups[0].members == expected
    assert services.kernel.sketches == (saved,)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)
    assert (
        next(
            item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id
        ).entities
        == draft_lines
    )
    assert editor.canvas.redo_last_operation()
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "mixed-trim.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups[0].members == expected
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)
    assert (
        next(item for item in services.kernel.sketches if item.sketch_id == saved.sketch_id)
        == saved
    )


@pytest.mark.parametrize("cancel", [False, True])
def test_saved_group_trim_after_existing_mixed_move(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cancel: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow
    from mycad.ui.sketch_editor import MixedMoveState

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 5), (20, 5))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", line.entity_id, saved.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    boundaries = (
        LineEntity(uuid4().hex, (5, -5), (5, 12)),
        LineEntity(uuid4().hex, (15, -5), (15, 12)),
    )
    assert editor.canvas.replace_draft_entities(boundaries)
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), boundaries, layers=editor.layer_table
    )
    moved_line = replace(line, start_mm=(0, 6), end_mm=(20, 6))
    moved_saved = replace(saved, entities=(moved_line,))
    background = editor.canvas.background_entities
    overlay = tuple(
        (moved_line if item.entity_id == line.entity_id else item, layer)
        for item, layer in background
    )
    state = MixedMoveState(
        uuid4().hex, loaded.document.revision, draft, (saved,), (moved_saved,), background, overlay
    )
    editor.canvas.apply_mixed_move(state, boundaries)
    history = tuple(loaded.document.commands)
    editor.canvas.set_snapping_enabled(False)
    editor.tool_combo.setCurrentText("修剪")
    start, end = editor.canvas.local_to_screen((10, 4)), editor.canvas.local_to_screen((10, 8))

    def reject_replacement(*_args: object, **_kwargs: object) -> ReplayAppend:
        raise ValidationError("模拟替换失败")

    with monkeypatch.context() as failure:
        failure.setattr(
            "mycad.core.drawing_transactions.prepare_grouped_sketch_replacements",
            reject_replacement,
        )
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(editor.canvas, end)
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    session = editor.canvas.collection_session
    assert session is not None
    assert "模拟替换失败" in editor.canvas.message
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == moved_saved
    )
    assert session.snapshot.groups == (group,)
    assert tuple(loaded.document.commands) == history

    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)

    session = editor.canvas.collection_session
    assert session is not None, editor.canvas.message
    current = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    assert len(current.entities) == 2, editor.canvas.message
    assert session.snapshot.groups[0].members == tuple(
        DrawingObjectRef("geometry", item.entity_id, saved.sketch_id) for item in current.entities
    )
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == moved_saved
    )
    assert editor.canvas.undo_last_operation()
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == saved
    )
    assert editor.canvas.redo_last_operation() and editor.canvas.redo_last_operation()
    if cancel:
        editor.reject()
        assert tuple(loaded.document.commands) == history
        assert services.kernel.sketches == (saved,)
        assert services.kernel.drawing_groups == (group,)
        return
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "mixed-before-trim.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[0] == moved_saved
    assert services.kernel.drawing_groups == (group,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[0] == saved


def test_drag_trim_ungrouped_saved_line_during_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    grouped = LineEntity(uuid4().hex, (0, 0), (20, 0))
    other = LineEntity(uuid4().hex, (0, 5), (20, 5))
    boundaries = (
        LineEntity(uuid4().hex, (5, 2), (5, 8)),
        LineEntity(uuid4().hex, (15, 2), (15, 8)),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (grouped, other, *boundaries))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", grouped.entity_id, saved.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    history = tuple(loaded.document.commands)
    editor.canvas.selected_entity_ids = {grouped.entity_id}
    assert editor.canvas.set_tool("单点打断")
    editor.canvas.add_coordinate_point((10, 0), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None
    once = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    group_after_first = session.snapshot.groups
    editor.canvas.set_snapping_enabled(False)
    editor.tool_combo.setCurrentText("修剪")
    start, end = editor.canvas.local_to_screen((10, 3)), editor.canvas.local_to_screen((10, 7))
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    twice = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    assert len(twice.entities) == 6, editor.canvas.message
    assert session.snapshot.groups == group_after_first
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == once
    )
    assert editor.canvas.redo_last_operation()
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "ungrouped-drag-trim.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches[0] == twice
    reopened.bus.undo_operation()
    assert (
        services.kernel.sketches[0] == once and services.kernel.drawing_groups == group_after_first
    )


@pytest.mark.parametrize(
    ("group_first", "selectable"), [(False, False), (True, False), (True, True)]
)
def test_chamfer_saved_lines_during_collection_session(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    group_first: bool,
    selectable: bool,
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 20))
    unrelated = LineEntity(uuid4().hex, (30, 0), (40, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second, unrelated))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    ref = DrawingObjectRef(
        "geometry", (first if group_first else unrelated).entity_id, saved.sketch_id
    )
    group = DrawingGroup(uuid4().hex, (ref,), selectable=selectable)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    draft_sketch = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft_sketch.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft_sketch.sketch_id)
    history = tuple(loaded.document.commands)
    editor.canvas.chamfer_first_distance = 2
    editor.canvas.chamfer_second_distance = 3
    assert editor.canvas.set_tool("二维倒角")
    for point in ((10, 0), (0, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    draft = next(
        item for item in session.snapshot.sketches if item.sketch_id == editor.draft_sketch_id
    )
    if selectable:
        assert revised == saved and draft.entities == () and session.snapshot.groups == (group,)
        assert "组选择" in editor.canvas.message
        assert tuple(loaded.document.commands) == history
        return
    assert revised != saved, editor.canvas.message
    assert len(draft.entities) == 1 and session.snapshot.groups == (group,)
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == saved
    )
    assert editor.canvas.redo_last_operation()
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-chamfer.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[0] == saved and services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize(
    ("auto", "selectable", "trim"),
    [(True, False, True), (False, False, True), (True, True, True), (True, False, False)],
)
def test_fillet_saved_lines_in_collection_preserves_tangencies(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    auto: bool,
    selectable: bool,
    trim: bool,
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import ArcEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 20))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", first.entity_id, saved.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=selectable)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    draft_sketch = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft_sketch.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft_sketch.sketch_id)
    history = tuple(loaded.document.commands)
    editor.canvas.set_auto_inference_enabled(auto)
    editor.canvas.circle_fillet_radius = 2
    editor.canvas.circle_fillet_trim = trim
    assert editor.canvas.set_tool("二维圆角")
    if auto and not selectable:
        before = session.checkpoint()

        def reject_stage(_operation: ReplayAppend) -> None:
            raise ValidationError("模拟圆角候选失败")

        with monkeypatch.context() as failure:
            failure.setattr(session, "stage", reject_stage)
            for point in ((10, 0), (0, 10)):
                QTest.mouseClick(
                    editor.canvas,
                    Qt.MouseButton.LeftButton,
                    pos=editor.canvas.local_to_screen(point),
                )
        assert "模拟圆角候选失败" in editor.canvas.message
        assert session.checkpoint() == before and session.snapshot.cross_tangencies == ()
        assert editor.canvas.pending_cross_tangencies == []
        assert editor.canvas.fillet_pending_cross_tangencies == ()
        assert tuple(loaded.document.commands) == history
    for point in ((10, 0), (0, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    draft = next(
        item for item in session.snapshot.sketches if item.sketch_id == draft_sketch.sketch_id
    )
    if selectable:
        assert revised == saved and draft.entities == () and session.snapshot.groups == (group,)
        assert "组选择" in editor.canvas.message
        assert tuple(loaded.document.commands) == history
        return
    assert (revised != saved) == trim, editor.canvas.message
    assert len(draft.entities) == 1 and isinstance(draft.entities[0], ArcEntity)
    assert len(session.snapshot.cross_tangencies) == (2 if auto else 0)
    assert session.snapshot.groups == (group,) and tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.cross_tangencies == () and session.snapshot.groups == (group,)
    assert editor.canvas.pending_cross_tangencies == []
    assert editor.canvas.redo_last_operation()
    assert len(session.snapshot.cross_tangencies) == (2 if auto else 0)
    assert len(editor.canvas.pending_cross_tangencies) == (2 if auto else 0)
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-fillet.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.cross_sketch_tangencies) == (2 if auto else 0)
    reopened.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == ()
    assert services.kernel.sketches[0] == saved and services.kernel.drawing_groups == (group,)


def test_notrim_polyline_fillet_in_collection_keeps_segment_tangencies(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.core.sketch import ArcEntity, PolylineEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (15, 0)))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", polyline.entity_id, saved.sketch_id),),
        selectable=False,
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    line = LineEntity(uuid4().hex, (10, 0), (10, 10))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    history = tuple(loaded.document.commands)
    editor.canvas.set_auto_inference_enabled(True)
    editor.canvas.circle_fillet_radius = 2
    editor.canvas.circle_fillet_trim = False
    assert editor.canvas.set_tool("二维圆角")
    for point in ((5, 0), (10, 8)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    after = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(after.entities) == 2 and isinstance(after.entities[-1], ArcEntity), (
        editor.canvas.message
    )
    assert len(session.snapshot.cross_tangencies) == 1
    relation = session.snapshot.cross_tangencies[0]
    assert relation.first.entity_id == polyline.entity_id and relation.first.segment_index == 0
    assert len([item for item in after.constraints if item.kind == "tangent"]) == 1
    assert session.snapshot.groups == (group,) and tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.cross_tangencies == () and session.snapshot.groups == (group,)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.cross_tangencies == (relation,)
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-polyline-fillet.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    reopened.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == () and services.kernel.drawing_groups == (
        group,
    )


@pytest.mark.parametrize("saved_target", [False, True])
def test_offset_erase_group_member_with_same_id_in_other_sketch(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, saved_target: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    saved_line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    draft_line = replace(saved_line, start_mm=(0, 10), end_mm=(20, 10))
    assert editor.canvas.replace_draft_entities((draft_line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (draft_line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    saved_ref = DrawingObjectRef("geometry", saved_line.entity_id, saved.sketch_id)
    draft_ref = DrawingObjectRef("geometry", draft_line.entity_id, draft.sketch_id)
    target_ref, other_ref = (saved_ref, draft_ref) if saved_target else (draft_ref, saved_ref)
    group = DrawingGroup(uuid4().hex, (target_ref,), selectable=False)
    other_group = DrawingGroup(uuid4().hex, (other_ref,), selectable=True)
    for item in (group, other_group):
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.create", 1, item.to_mapping(), "local")
        )
    history = tuple(loaded.document.commands)
    bar = editor.drawing_command_bar
    for value in ("OFFSET", "E", "Y", "2"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    y = 0 if saved_target else 10
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, y))
    )
    checkpoint = session.checkpoint()

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟偏移候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        editor.canvas.add_coordinate_point((10, y + 4), exact_point=True)
    assert "模拟偏移候选失败" in editor.canvas.message
    assert session.checkpoint() == checkpoint
    if saved_target:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, y))
        )
    editor.canvas.add_coordinate_point((10, y + 4), exact_point=True)
    assert session.snapshot.groups[0] != group, editor.canvas.message
    assert session.snapshot.groups[1] == other_group
    changed_saved = next(
        item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id
    )
    changed_draft = next(
        item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id
    )
    assert (changed_saved.entities == ()) if saved_target else (changed_saved == saved)
    expected = next(
        item for item in changed_draft.entities if item.entity_id != draft_line.entity_id
    )
    assert isinstance(expected, LineEntity)
    assert expected.start_mm == pytest.approx((0, y + 2))
    assert expected.end_mm == pytest.approx((20, y + 2))
    assert session.snapshot.groups[0].members == (
        DrawingObjectRef("geometry", expected.entity_id, draft.sketch_id),
    )
    assert (draft_line in changed_draft.entities) == saved_target
    assert tuple(loaded.document.commands) == history
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group, other_group)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups[0].members == (
        DrawingObjectRef("geometry", expected.entity_id, draft.sketch_id),
    )
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "offset-same-id.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group, other_group)


@pytest.mark.parametrize("saved_target", [False, True])
def test_offset_same_id_checks_only_the_picked_layer(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, saved_target: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("locked"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    saved_line = LineEntity(uuid4().hex, (0, 0), (20, 0), layer_name="locked")
    saved = Sketch(uuid4().hex, editor.current_frame(), (saved_line,), layers=layers)
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    locked = layers.replace(replace(layers.get("locked"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    _invoke(window, "_sync_drawing_layers")
    draft_line = replace(saved_line, start_mm=(0, 10), end_mm=(20, 10), layer_name="0")
    assert editor.canvas.replace_draft_entities((draft_line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (draft_line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    checkpoint = session.checkpoint()
    bar = editor.drawing_command_bar
    for value in ("OFFSET", "2"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    y = 0 if saved_target else 10
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, y))
    )
    if saved_target:
        assert "锁定" in editor.canvas.message
        assert session.checkpoint() == checkpoint
    else:
        editor.canvas.add_coordinate_point((10, 14), exact_point=True)
        revised = next(
            item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id
        )
        assert len(revised.entities) == 2, editor.canvas.message
        unchanged = next(
            item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id
        )
        assert unchanged.entities == saved.entities and unchanged.layers == locked


def test_offset_multiple_saved_same_id_updates_group_each_step(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    other_line = replace(line, start_mm=(0, 10), end_mm=(20, 10))
    assert editor.canvas.replace_draft_entities((other_line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (other_line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", line.entity_id, saved.sketch_id),),
        selectable=False,
    )
    other = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", other_line.entity_id, draft.sketch_id),)
    )
    for item in (group, other):
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.create", 1, item.to_mapping(), "local")
        )
    bar = editor.drawing_command_bar

    def send(value: str) -> None:
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)

    for value in ("OFFSET", "E", "Y", "2"):
        send(value)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    send("M")
    send("10,2")
    first = session.snapshot.groups[0]
    assert first != group, editor.canvas.message
    send("10,4")
    second = session.snapshot.groups[0]
    assert second != first, editor.canvas.message
    assert session.snapshot.groups[1] == other
    draft_after = next(
        item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id
    )
    result = next(
        item for item in draft_after.entities if item.entity_id == second.members[0].object_id
    )
    assert isinstance(result, LineEntity) and result.start_mm == pytest.approx((0, 4))
    send("U")
    assert session.snapshot.groups == (first, other)
    send("U")
    assert session.snapshot.groups == (group, other)


@pytest.mark.parametrize("source_constrained", [False, True])
def test_offset_saved_same_id_without_existing_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, source_constrained: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    constraints = (
        (
            SketchConstraint(
                uuid4().hex, "horizontal", (SketchGeometryReference(line.entity_id, "geometry"),)
            ),
        )
        if source_constrained
        else ()
    )
    saved = Sketch(uuid4().hex, editor.current_frame(), (line,), constraints=constraints)
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", line.entity_id, saved.sketch_id),),
        selectable=False,
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    _invoke(window, "_sync_drawing_layers")
    other = replace(line, start_mm=(0, 10), end_mm=(20, 10))
    assert editor.canvas.replace_draft_entities((other,))
    assert editor.canvas.collection_session is None
    history = tuple(loaded.document.commands)
    bar = editor.drawing_command_bar
    for value in ("OFFSET", "E", "Y", "2"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    editor.canvas.add_coordinate_point((10, 4), exact_point=True)
    if source_constrained:
        assert "约束" in editor.canvas.message
        assert editor.canvas.collection_session is None
        assert tuple(loaded.document.commands) == history
        assert tuple(editor.canvas.entities) == (other,)
        return
    session = cast("DrawingCollectionSession | None", vars(editor.canvas)["collection_session"])
    assert session is not None, editor.canvas.message
    assert session.snapshot.groups[0] != group
    assert tuple(loaded.document.commands) == history
    draft = next(
        item for item in session.snapshot.sketches if item.sketch_id == editor.draft_sketch_id
    )
    assert other in draft.entities
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)


def test_offset_erase_group_member_with_same_id_in_two_saved_sketches(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first_line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second_line = replace(first_line, start_mm=(0, 10), end_mm=(20, 10))
    relation = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(first_line.entity_id, "geometry"),)
    )
    first = Sketch(uuid4().hex, editor.current_frame(), (first_line,), constraints=(relation,))
    second = Sketch(uuid4().hex, editor.current_frame(), (second_line,))
    app.commit_new_sketch(services, loaded, first, session_identity=_session_id(window))
    app.commit_new_sketch(services, loaded, second, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    ref = DrawingObjectRef("geometry", second_line.entity_id, second.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    other = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", first_line.entity_id, first.sketch_id),)
    )
    for item in (group, other):
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.create", 1, item.to_mapping(), "local")
        )
    bar = editor.drawing_command_bar
    for value in ("OFFSET", "E", "Y", "2"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    editor.canvas.add_coordinate_point((10, 14), exact_point=True)
    assert session.snapshot.groups[0] != group, editor.canvas.message
    assert session.snapshot.groups[1] == other
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == first.sketch_id)
        == first
    )
    assert (
        next(
            item for item in session.snapshot.sketches if item.sketch_id == second.sketch_id
        ).entities
        == ()
    )
    output = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert session.snapshot.groups[0].members == (
        DrawingObjectRef("geometry", output.entities[0].entity_id, draft.sketch_id),
    )
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group, other)
    assert editor.canvas.redo_last_operation()
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "offset-two-saved-same-id.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group, other)


@pytest.mark.parametrize("preexisting", [True, False])
def test_offset_erase_saved_group_member_in_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, preexisting: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", line.entity_id, saved.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session: DrawingCollectionSession | None = None
    if preexisting:
        session = DrawingCollectionSession(
            services,
            loaded,
            ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
            session_identity=_session_id(window),
        )
        editor.canvas.attach_collection_session(session, draft.sketch_id)
    history = tuple(loaded.document.commands)
    bar = editor.drawing_command_bar
    for value in ("OFFSET", "E", "Y", "2"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟偏移候选失败")

    if preexisting:
        assert session is not None
        before = session.checkpoint()
        with monkeypatch.context() as failure:
            failure.setattr(session, "stage", reject_stage)
            QTest.mouseClick(
                editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
            )
            editor.canvas.add_coordinate_point((10, 4), exact_point=True)
        assert "模拟偏移候选失败" in editor.canvas.message
        assert session.checkpoint() == before and session.snapshot.groups == (group,)
        assert tuple(loaded.document.commands) == history
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    editor.canvas.add_coordinate_point((10, 4), exact_point=True)
    session = editor.canvas.collection_session
    assert session is not None, editor.canvas.message
    updated = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert updated.entities == () and len(result.entities) == 1, editor.canvas.message
    new_ref = DrawingObjectRef("geometry", result.entities[0].entity_id, draft.sketch_id)
    assert session.snapshot.groups[0].members == (new_ref,)
    assert tuple(loaded.document.commands) == history
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)
    assert editor.canvas.redo_last_operation()
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "group-offset.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups[0].members == (new_ref,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[0] == saved and services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("erase", [True, False])
@pytest.mark.parametrize("preexisting", [True, False])
def test_offset_erase_selectable_group_is_rejected_atomically(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, erase: bool, preexisting: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 8), (20, 8))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex,
        tuple(
            DrawingObjectRef("geometry", item.entity_id, saved.sketch_id) for item in saved.entities
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session: DrawingCollectionSession | None = None
    if preexisting:
        session = DrawingCollectionSession(
            services,
            loaded,
            ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
            session_identity=_session_id(window),
        )
        editor.canvas.attach_collection_session(session, draft.sketch_id)
    before, history = session.checkpoint() if session else None, tuple(loaded.document.commands)
    bar = editor.drawing_command_bar
    for value in ("OFFSET", "E", "Y" if erase else "N", "2"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    if session is not None:
        assert session.checkpoint() == before
        assert session.snapshot.groups == (group,)
        assert (
            next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
            == saved
        )
    else:
        assert editor.canvas.collection_session is None
        assert services.kernel.drawing_groups == (group,) and services.kernel.sketches == (saved,)
    assert tuple(editor.canvas.entities) == () and tuple(loaded.document.commands) == history
    assert "组" in editor.canvas.message


@pytest.mark.parametrize("multiple", [False, True])
def test_spline_offset_erase_maps_all_group_fragments(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, multiple: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.core.sketch import SplineEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    source = SplineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5), (10, 5)))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    ref = DrawingObjectRef("geometry", source.entity_id, saved.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    history = tuple(loaded.document.commands)
    bar = editor.drawing_command_bar
    for value in ("OFFSET", "E", "Y", "1"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 2.5))
    )
    if multiple:
        bar.input.setText("M")
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    editor.canvas.add_coordinate_point((4, 3.5), exact_point=True)
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(result.entities) > 1 and all(
        isinstance(item, SplineEntity) for item in result.entities
    ), editor.canvas.message
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in result.entities
    )
    assert session.snapshot.groups[0].members == refs
    assert tuple(loaded.document.commands) == history
    initial_refs = refs
    if multiple:
        from mycad.core.exceptions import ValidationError

        checkpoint = session.checkpoint()

        def reject_stage(_operation: ReplayAppend) -> None:
            raise ValidationError("模拟连续偏移失败")

        with monkeypatch.context() as failure:
            failure.setattr(session, "stage", reject_stage)
            editor.canvas.add_coordinate_point((3, 5), exact_point=True)
        assert "模拟连续偏移失败" in editor.canvas.message
        assert (
            session.checkpoint() == checkpoint
            and session.snapshot.groups[0].members == initial_refs
        )
        assert tuple(editor.canvas.entities) == result.entities
        editor.canvas.add_coordinate_point((3, 5), exact_point=True)
        result = next(
            item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id
        )
        refs = tuple(
            DrawingObjectRef("geometry", item.entity_id, draft.sketch_id)
            for item in result.entities
        )
        assert refs and refs != initial_refs, editor.canvas.message
        assert session.snapshot.groups[0].members == refs
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    if multiple:
        assert (
            editor.canvas.undo_last_operation()
            and session.snapshot.groups[0].members == initial_refs
        )
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == (group,)
    assert editor.canvas.redo_last_operation()
    if multiple:
        assert session.snapshot.groups[0].members == initial_refs
        assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups[0].members == refs
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "group-spline-offset.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups[0].members == refs
    reopened.bus.undo_operation()
    if multiple:
        assert services.kernel.drawing_groups[0].members == initial_refs
        reopened.bus.undo_operation()
    assert services.kernel.sketches[0] == saved and services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("erase", [False, True])
def test_ungrouped_draft_offset_failure_rolls_back_collection(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, erase: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    source = LineEntity(uuid4().hex, (0, 0), (20, 0))
    other = LineEntity(uuid4().hex, (0, 8), (20, 8))
    assert editor.canvas.replace_draft_entities((source, other))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (source, other), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", other.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    checkpoint, history = session.checkpoint(), tuple(loaded.document.commands)
    bar = editor.drawing_command_bar
    for value in ("OFFSET", "E", "Y" if erase else "N", "2"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟草稿偏移失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        editor.canvas.add_coordinate_point((10, 4), exact_point=True)
    assert "模拟草稿偏移失败" in editor.canvas.message
    assert session.checkpoint() == checkpoint and session.snapshot.groups == (group,)
    assert tuple(editor.canvas.entities) == (source, other)
    assert tuple(loaded.document.commands) == history
    editor.canvas.add_coordinate_point((10, 4), exact_point=True)
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(result.entities) == (2 if erase else 3) and result.entities[-1] != source
    assert session.snapshot.groups == (group,) and tuple(loaded.document.commands) == history
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert editor.canvas.undo_last_operation()
    assert tuple(editor.canvas.entities) == (source, other) and session.snapshot.groups == (group,)
    assert editor.canvas.redo_last_operation()
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "ungrouped-offset.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[0].entities == (source, other)
    assert services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("saved_source", [False, True])
def test_offset_keeps_grouped_source_without_grouping_copy(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, saved_source: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    source = LineEntity(uuid4().hex, (0, 0), (20, 0))
    if saved_source:
        saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
        app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
        group = DrawingGroup(
            uuid4().hex,
            (DrawingObjectRef("geometry", source.entity_id, saved.sketch_id),),
            selectable=False,
        )
        loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
        editor.set_context_sketches(services.kernel.sketches)
        editor.canvas.set_source_context_revision(loaded.document.revision)
    else:
        assert editor.canvas.replace_draft_entities((source,))
        group = DrawingGroup(
            uuid4().hex,
            (DrawingObjectRef("geometry", source.entity_id, editor.draft_sketch_id),),
            selectable=False,
        )
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        tuple(editor.canvas.entities),
        layers=editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    if not saved_source:
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
        )
    before, history = session.checkpoint(), tuple(loaded.document.commands)
    bar = editor.drawing_command_bar
    for value in ("OFFSET", "E", "N", "2"):
        bar.input.setText(value)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟偏移副本失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        editor.canvas.add_coordinate_point((10, 4), exact_point=True)
    assert "模拟偏移副本失败" in editor.canvas.message
    assert session.checkpoint() == before and session.snapshot.groups == (group,)
    assert tuple(loaded.document.commands) == history
    editor.canvas.add_coordinate_point((10, 4), exact_point=True)
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(result.entities) == (1 if saved_source else 2), editor.canvas.message
    assert session.snapshot.groups == (group,) and tuple(loaded.document.commands) == history
    QTest.keyClick(bar.input, Qt.Key.Key_Escape)
    assert editor.canvas.undo_last_operation() and session.snapshot.groups == (group,)
    assert editor.canvas.redo_last_operation()
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "keep-grouped-source.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups == (group,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)


def test_drawing_line_candidate_failure_keeps_canvas_and_history(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((source,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (source,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", source.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    checkpoint, history = session.checkpoint(), tuple(loaded.document.commands)
    assert editor.canvas.set_tool("直线")
    editor.canvas.set_snapping_enabled(False)
    editor.canvas.add_coordinate_point((0, 4), exact_point=True)

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟画线候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        editor.canvas.add_coordinate_point((10, 4), exact_point=True)
    assert "模拟画线候选失败" in editor.canvas.message
    assert session.checkpoint() == checkpoint and session.snapshot.groups == (group,)
    assert tuple(editor.canvas.entities) == (source,) and tuple(loaded.document.commands) == history
    editor.canvas.add_coordinate_point((10, 4), exact_point=True)
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(result.entities) == 2 and tuple(editor.canvas.entities) == result.entities
    assert editor.canvas.set_tool("选择元素")
    assert editor.canvas.undo_last_operation() and tuple(editor.canvas.entities) == (source,)
    assert editor.canvas.redo_last_operation() and tuple(editor.canvas.entities) == result.entities
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "line-candidate.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[0].entities == (source,)
    assert services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("kind", ["点", "多段线", "样条曲线"])
def test_drawing_other_geometry_failure_keeps_collection_consistent(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((source,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (source,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", source.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.checkpoint()
    assert editor.canvas.set_tool(kind)
    editor.canvas.set_snapping_enabled(False)
    if kind != "点":
        points = ((0, 4), (3, 4), (6, 5), (9, 5)) if kind == "样条曲线" else ((0, 4), (3, 4))
        for point in points:
            editor.canvas.add_coordinate_point(point, exact_point=True)

    def finish() -> None:
        if kind == "点":
            editor.canvas.add_coordinate_point((0, 4), exact_point=True)
        elif kind == "样条曲线":
            editor.canvas.finish_spline()
        else:
            editor.canvas.finish_polyline()

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟绘图候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        finish()
    assert "模拟绘图候选失败" in editor.canvas.message
    assert tuple(editor.canvas.entities) == (source,) and session.checkpoint() == before
    finish()
    current = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(current.entities) == 2 and tuple(editor.canvas.entities) == current.entities
    assert session.snapshot.groups == (group,)


@pytest.mark.parametrize("kind", ["line", "circle", "arc"])
def test_tangent_line_of_saved_circles_stages_cross_relations(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import ArcEntity, CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    circles = (CircleEntity(uuid4().hex, (0, 0), 2), CircleEntity(uuid4().hex, (10, 0), 2))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), circles)
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circles[0].entity_id, saved.sketch_id),),
        selectable=False,
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    editor.canvas.set_auto_inference_enabled(True)
    history = tuple(loaded.document.commands)
    bar = editor.drawing_command_bar
    if kind == "line":
        for value in ("LINE", "TAN"):
            bar.input.setText(value)
            QTest.keyClick(bar.input, Qt.Key.Key_Return)
        editor.canvas.add_coordinate_point((0, 2), exact_point=True)
        bar.input.setText("TAN")
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
        editor.canvas.add_coordinate_point((10, 2), exact_point=True)
    else:
        for value in ("ARC" if kind == "arc" else "CIRCLE", "TTR"):
            bar.input.setText(value)
            QTest.keyClick(bar.input, Qt.Key.Key_Return)
        for point in ((1.7, 1.1), (8.3, 1.1)):
            QTest.mouseClick(
                editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
            )

        def reject_stage(_operation: ReplayAppend) -> None:
            raise ValidationError("模拟 TTR 候选失败")

        before = session.checkpoint()
        with monkeypatch.context() as failure:
            failure.setattr(session, "stage", reject_stage)
            bar.input.setText("4")
            QTest.keyClick(bar.input, Qt.Key.Key_Return)
        assert "模拟 TTR 候选失败" in editor.canvas.message
        assert session.checkpoint() == before and session.snapshot.cross_tangencies == ()
        assert tuple(editor.canvas.entities) == () and editor.canvas.pending_cross_tangencies == []
        bar.input.setText("4")
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(result.entities) == 1 and isinstance(
        result.entities[0], {"line": LineEntity, "circle": CircleEntity, "arc": ArcEntity}[kind]
    ), editor.canvas.message
    assert len(session.snapshot.cross_tangencies) == 2
    assert session.snapshot.groups == (group,) and tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.cross_tangencies == ()
    assert editor.canvas.redo_last_operation()
    assert len(session.snapshot.cross_tangencies) == 2
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-tangent-line.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.cross_sketch_tangencies) == 2
    reopened.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == () and services.kernel.drawing_groups == (
        group,
    )


def test_collection_undo_restores_constraint_and_picture_selection(qtbot: QtBot) -> None:
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    picture = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (0, 0),
        2,
        2,
    )
    loaded.bus.execute(
        "drawing.raster.batch",
        {"action": "add", "images": [picture.to_mapping(version=2)]},
        "local",
    )
    _invoke(window, "_sync_drawing_layers")
    line = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    editor.canvas.set_snapping_enabled(False)
    editor.canvas.set_tool("直线")
    editor.canvas.add_coordinate_point((0, 0))
    editor.canvas.add_coordinate_point((10, 0.2))
    constraint_id = editor.canvas.constraints[0].constraint_id
    editor.canvas.selected_constraint_ids = {constraint_id}
    editor.canvas.selected_raster_ids = {picture.image_id}
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_constraint_ids.clear()
    editor.canvas.selected_raster_ids.clear()
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.selected_constraint_ids == {constraint_id}
    assert editor.canvas.selected_raster_ids == {picture.image_id}


def test_undo_before_session_start_rewinds_draft_and_group(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((first,))
    assert editor.canvas.replace_draft_entities((first, second))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (first, second), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", second.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == ()
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[-1].entities == (first,)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.sketches[-1].entities == (first, second)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups == (group,)


def test_undo_predating_session_does_not_reappear_after_commit(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((first,))
    assert editor.canvas.replace_draft_entities((first, second))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (first, second), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[-1].entities == (first,)
    session.commit()
    assert services.kernel.sketches[-1].entities == (first,)
    loaded.bus.undo_operation()
    assert services.kernel.sketches == ()


def test_undo_first_draft_object_after_attaching_session(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == []
    assert session.snapshot.sketches[-1].entities == ()
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.sketches[-1].entities == (line,)


def test_pre_session_drawing_steps_remain_distinct_after_commit(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((first,))
    assert editor.canvas.replace_draft_entities((first, second))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (first, second), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    session.commit()
    loaded.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == (first,)
    loaded.bus.undo_operation()
    assert services.kernel.sketches == ()


def test_pre_session_steps_and_group_undo_after_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((first,))
    assert editor.canvas.replace_draft_entities((first, second))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (first, second), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", second.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    session.commit()
    path = tmp_path / "history.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == ()
    assert services.kernel.sketches[-1].entities == (first, second)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == (first,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == ()


def test_pre_session_redo_branch_remains_replayable_after_commit(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((first,))
    assert editor.canvas.replace_draft_entities((first, second))
    assert editor.canvas.undo_last_operation()
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (first,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.sketches[-1].entities == (first, second)
    session.commit()
    loaded.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == (first,)


def test_pre_session_redo_from_empty_draft_creates_one_history_step(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    assert editor.canvas.undo_last_operation()
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    assert editor.canvas.redo_last_operation()
    session.commit()
    assert services.kernel.sketches[-1].entities == (line,)
    loaded.bus.undo_operation()
    assert services.kernel.sketches == ()


def test_bound_session_guards_document_writes_until_cancel(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    text = DrawingText(uuid4().hex, "external", (0, 0))
    with pytest.raises(ValidationError, match="暂存"):
        loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    with pytest.raises(ValidationError, match="暂存"):
        loaded.bus.undo_operation()
    with pytest.raises(ValidationError, match="暂存"):
        loaded.bus.redo_operation()
    with pytest.raises(ValidationError, match="暂存"):
        loaded.bus.copy_for_document(loaded.document)
    assert loaded.document.commands == ()
    session.cancel()
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    assert services.kernel.drawing_texts == (text,)


def test_failed_session_commit_keeps_document_write_guard(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    getattr(loaded.document, _REVISION_METHOD)()
    with pytest.raises(ValidationError, match="变化"):
        session.commit()
    text = DrawingText(uuid4().hex, "external", (0, 0))
    with pytest.raises(ValidationError, match="暂存"):
        loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    session.cancel()
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    assert services.kernel.drawing_texts == (text,)


def test_noop_save_recovery_can_finish_during_bound_session(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    token = loaded.bus.create_save_checkpoint()
    loaded.bus.restore_save_checkpoint(token, expected_revision=loaded.document.revision)
    assert session.snapshot.sketches[-1] == draft
    session.cancel()


def test_other_replay_candidate_cannot_commit_during_bound_session(qtbot: QtBot) -> None:
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    other = replace(draft, sketch_id=uuid4().hex)
    rival = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, other.to_mapping(version=3), "local"),
        session_identity=1,
    )
    with pytest.raises(ValidationError, match="暂存"):
        rival.commit()
    assert loaded.document.commands == ()
    rival.cancel()
    session.commit()
    assert services.kernel.sketches[-1].sketch_id == draft.sketch_id


def test_group_move_spanning_saved_and_draft_uses_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    if window.viewport is not None:
        monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    _invoke(window, "_sync_drawing_layers")
    second = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((second,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (second,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", first.entity_id, saved.sketch_id),
            DrawingObjectRef("geometry", second.entity_id, draft.sketch_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = tuple(loaded.document.commands)
    editor.canvas.selected_entity_ids = {second.entity_id}
    assert editor.canvas.delete_selected()
    assert session.snapshot.groups == ()
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,)
    assert session.snapshot.sketches[-1].entities == (second,)
    editor.canvas.selected_entity_ids = {second.entity_id}
    editor.canvas.begin_transform("rotate")
    assert editor.canvas.active_transform == "rotate"
    editor.canvas.cancel_transform()
    assert session.snapshot.sketches[-1].entities == (second,)
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert tuple(loaded.document.commands) == before
    moved_first = session.snapshot.sketches[0].entities[0]
    moved_second = session.snapshot.sketches[-1].entities[0]
    assert isinstance(moved_first, LineEntity) and moved_first.start_mm == (0, 3)
    assert isinstance(moved_second, LineEntity) and moved_second.start_mm == (0, 8)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[0].entities == (first,)
    assert session.snapshot.sketches[-1].entities == (second,)
    assert session.snapshot.groups == (group,)
    assert editor.canvas.redo_last_operation()
    editor.canvas.selected_entity_ids = {second.entity_id}
    editor.canvas.begin_transform("copy")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert len(session.snapshot.groups) == 2
    copied_group = session.snapshot.groups[-1]
    assert editor.canvas.undo_copy_placement()
    assert session.snapshot.groups == (group,)
    editor.canvas.cancel_transform()
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups[-1] == copied_group
    editor.finish_sketch()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and window.active_sketch_dialog() is not editor)
    path = tmp_path / "group-move.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.sketches[0].entities == (moved_first,)
    assert services.kernel.sketches[-1].entities == (moved_second,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[0].entities == (first,)
    assert services.kernel.sketches[-1].entities == (second,)
    assert services.kernel.drawing_groups == (group,)


def test_repeated_group_copy_uses_one_session_step_per_placement(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mycad.core.drawing_transactions as transactions
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    if window.viewport is not None:
        monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    _invoke(window, "_sync_drawing_layers")
    second = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((second,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (second,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", first.entity_id, saved.sketch_id),
            DrawingObjectRef("geometry", second.entity_id, draft.sketch_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {first.entity_id}
    editor.canvas.begin_transform("copy")
    assert editor.canvas.selected_entity_ids == {first.entity_id}
    assert first.entity_id in {
        entity.entity_id for entity, _layer in editor.canvas.background_entities
    }
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    assert editor.canvas.selected_entity_ids == {first.entity_id}

    def fail_copy(*_args: object, **_kwargs: object) -> None:
        raise ValidationError("模拟复制预检失败")

    with monkeypatch.context() as failure:
        failure.setattr(transactions, "prepare_collection_copy", fail_copy)
        before = session.checkpoint()
        editor.canvas.add_coordinate_point((0, 3), exact_point=True)
        assert session.checkpoint() == before
        assert "模拟复制预检失败" in editor.canvas.message and "重新指定" in editor.canvas.message
        editor.canvas.cursor_changed.emit(1.0, 1.0, "")
        assert "模拟复制预检失败" in editor.status_label.text()
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert len(session.snapshot.groups) == 2, (
        editor.canvas.message,
        editor.status_label.text(),
        editor.canvas.active_transform,
        tuple(len(sketch.entities) for sketch in session.snapshot.sketches),
        tuple(item.entity_id for item in editor.canvas.entities),
    )
    assert "下一个目标点" in editor.canvas.message and "Enter" in editor.canvas.message
    editor.canvas.cursor_changed.emit(1.0, 1.0, "")
    assert "下一个目标点" in editor.status_label.text()
    assert len(session.snapshot.sketches[0].entities) == 2
    assert len(session.snapshot.sketches[-1].entities) == 2
    editor.canvas.add_coordinate_point((0, 6), exact_point=True)
    assert len(session.snapshot.groups) == 3
    assert len(session.snapshot.sketches[0].entities) == 3
    assert editor.canvas.undo_copy_placement()
    assert len(session.snapshot.groups) == 2
    assert editor.canvas.undo_copy_placement()
    assert session.snapshot.groups == (group,)
    assert session.snapshot.sketches[0].entities == (first,)
    assert session.snapshot.sketches[-1].entities == (second,)
    assert editor.canvas.active_transform == "copy"


def test_selectable_group_member_grip_edit_is_rejected(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.edit_handle_coordinate(
        editor.canvas.entities[0], SketchGeometryReference(line.entity_id, "end"), (10, 0), (15, 0)
    )
    assert editor.canvas.entities == [line]
    assert session.snapshot.groups == (group,)
    assert session.snapshot.sketches[-1].entities == (line,)


def test_collection_move_rejects_ambiguous_object_identity(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    identity = uuid4().hex
    loaded.bus.execute(
        "drawing.text.add", DrawingText(identity, "same id", (0, 0)).to_mapping(), "local"
    )
    _invoke(window, "_sync_drawing_layers")
    line = LineEntity(identity, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    _invoke(window, "_on_drawing_move", editor, _session_id(window), (identity,), (0.0, 3.0))
    assert session.snapshot.sketches[-1].entities == (line,)
    assert "不唯一" in editor.status_label.text()


def test_document_undo_redo_routes_to_bound_session(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    text = DrawingText(uuid4().hex, "committed", (0, 0))
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.layer_history_boundaries[len(loaded.document.commands)] = editor.canvas.history_position
    window.request_undo()
    assert session.snapshot.groups == ()
    assert services.kernel.drawing_texts == (text,)
    window.request_redo()
    assert session.snapshot.groups == (group,)
    assert services.kernel.drawing_texts == (text,)


def test_raster_add_update_remove_follow_collection_history(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    if window.viewport is not None:
        monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    add_raster, edit_raster, batch_rasters = (
        editor.canvas.commit_clipboard_raster,
        editor.canvas.commit_raster_edit,
        editor.canvas.commit_raster_batch,
    )
    assert add_raster is not None and edit_raster is not None and batch_rasters is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    raster = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (0, 0),
        2,
        2,
    )
    add_raster(raster)
    updated = replace(raster, origin_mm=(3, 4))
    edit_raster("update", updated)
    batch_rasters("remove", (updated,))
    assert loaded.document.commands == ()
    assert editor.canvas.drawing_rasters == ()
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.drawing_rasters == (updated,)
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.drawing_rasters == (raster,)
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.drawing_rasters == ()
    assert editor.canvas.redo_last_operation()
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("raster", raster.image_id),))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    with pytest.raises(ValueError, match="组选择"):
        edit_raster("update", updated)
    assert session.snapshot.rasters == (raster,)
    independent = replace(group, selectable=False)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.update", 1, independent.to_mapping(), "local")
    )
    edit_raster("update", updated)
    assert session.snapshot.rasters == (updated,)
    assert session.snapshot.groups == (independent,)
    editor.finish_sketch()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and window.active_sketch_dialog() is not editor)
    path = tmp_path / "image-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_rasters == (raster,)
    assert services.kernel.drawing_groups == (independent,)


def test_stale_session_rejects_raster_add_without_losing_draft(qtbot: QtBot) -> None:
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    add_raster = editor.canvas.commit_clipboard_raster
    assert add_raster is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    getattr(loaded.document, _REVISION_METHOD)()
    raster = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (0, 0),
        2,
        2,
    )
    with pytest.raises(ValueError, match="变化"):
        add_raster(raster)
    assert editor.canvas.entities == [line]
    assert services.kernel.drawing_rasters == ()


def test_mixed_group_move_updates_canvas_and_undoes_together(qtbot: QtBot) -> None:
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_text import DrawingText
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None and editor.canvas.text_tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    text = DrawingText(uuid4().hex, "A", (2, 1))
    image = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (3, 2),
        2,
        2,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local")
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend(
            "drawing.raster.batch",
            2,
            {"action": "add", "images": [image.to_mapping(version=2)]},
            "local",
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (ref, DrawingObjectRef("text", text.text_id), DrawingObjectRef("raster", image.image_id)),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    execute = editor.canvas.text_tools.execute
    assert execute is not None
    with pytest.raises(ValueError, match="组选择"):
        execute("drawing.text.update", replace(text, position_mm=(5, 1)).to_mapping())
    assert session.snapshot.texts == (text,)
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert editor.canvas.entities == [replace(line, start_mm=(0, 3), end_mm=(10, 3))]
    assert editor.canvas.text_tools.texts == (replace(text, position_mm=(2, 4)),)
    assert editor.canvas.drawing_rasters == (replace(image, origin_mm=(3, 5)),)
    assert loaded.document.commands == ()
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [line]
    assert editor.canvas.text_tools.texts == (text,)
    assert editor.canvas.drawing_rasters == (image,)
    editor.canvas.cancel_transform()
    editor.canvas.selected_entity_ids.clear()
    editor.canvas.selected_raster_ids = {image.image_id}
    editor.canvas.begin_transform("copy")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert len(session.snapshot.groups) == 2
    assert editor.canvas.undo_copy_placement()
    assert session.snapshot.groups == (group,)
    editor.canvas.cancel_transform()
    editor.canvas.selected_raster_ids.clear()
    editor.canvas.selected_entity_ids.clear()
    editor.canvas.text_tools.selected_ids = {text.text_id}
    editor.canvas.begin_transform("copy")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert len(session.snapshot.groups) == 2
    assert editor.canvas.undo_copy_placement()
    assert session.snapshot.groups == (group,)
    editor.canvas.cancel_transform()
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert editor.canvas.entities == [replace(line, start_mm=(0, 3), end_mm=(10, 3))]
    assert editor.canvas.text_tools.texts == (replace(text, position_mm=(2, 4)),)
    assert editor.canvas.drawing_rasters == (replace(image, origin_mm=(3, 5)),)
    assert editor.canvas.undo_last_operation()
    editor.canvas.text_tools.selected_ids.clear()
    editor.canvas.selected_raster_ids = {image.image_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert editor.canvas.entities == [replace(line, start_mm=(0, 3), end_mm=(10, 3))]
    assert editor.canvas.text_tools.texts == (replace(text, position_mm=(2, 4)),)
    assert editor.canvas.drawing_rasters == (replace(image, origin_mm=(3, 5)),)
    assert editor.canvas.undo_last_operation()
    editor.canvas.selected_raster_ids.clear()
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("copy")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert len(session.snapshot.groups) == 2
    assert len(editor.canvas.entities) == 2
    assert len(editor.canvas.text_tools.texts) == 2
    assert len(editor.canvas.drawing_rasters) == 2
    assert editor.canvas.undo_copy_placement()
    assert session.snapshot.groups == (group,)
    assert editor.canvas.entities == [line]
    assert editor.canvas.text_tools.texts == (text,)
    assert editor.canvas.drawing_rasters == (image,)


def test_cancelling_moved_and_copied_group_restores_saved_document(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    if window.viewport is not None:
        monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    _invoke(window, "_sync_drawing_layers")
    before = tuple(loaded.document.commands)
    second = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((second,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (second,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", first.entity_id, saved.sketch_id),
            DrawingObjectRef("geometry", second.entity_id, draft.sketch_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {second.entity_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    editor.canvas.begin_transform("copy")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert len(session.snapshot.groups) == 2
    editor.reject()
    assert tuple(loaded.document.commands) == before
    assert services.kernel.sketches == (saved,)
    assert services.kernel.drawing_groups == ()


def test_group_move_projects_free_tolerance_datum_and_reference(qtbot: QtBot) -> None:
    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.geometric_tolerance import DatumIdentifier, FeatureControlFrame, ToleranceRow
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    frame = FeatureControlFrame(uuid4().hex, (ToleranceRow("position", 0.1, 2),), (5, 5))
    datum = DatumIdentifier(uuid4().hex, "A", (8, 5), (7, 4))
    reference = DetachedDimension(uuid4().hex, "aligned", (0, 2), (2, 2), (1, 3), 0, 2)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend(
            "drawing.tolerance.batch",
            28,
            {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
            "local",
        )
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend(
            "drawing.reference_dimensions.batch", 10, {"add": [reference.to_mapping()]}, "local"
        )
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            ref,
            DrawingObjectRef("tolerance", frame.frame_id),
            DrawingObjectRef("datum", datum.datum_id),
            DrawingObjectRef("reference_dimension", reference.dimension_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert tools.execute is not None
    tools.selected_ids = {datum.datum_id}
    tools.selected_id = datum.datum_id
    tools.selected_kind = "datum"
    assert tools.handle_command("COPY")
    assert tools.mixed_move_active
    assert tools.cancel()
    assert session.snapshot.groups == (group,)
    tools.selected_ids.clear()
    tools.selected_id = None
    with pytest.raises(ValueError, match="组选择"):
        tools.execute(
            "drawing.tolerance.batch",
            {"update_datums": [replace(datum, position_mm=(8, 6)).to_mapping()]},
        )
    with pytest.raises(ValueError, match="组选择"):
        tools.execute(
            "drawing.reference_dimensions.batch",
            {"update": [replace(reference, location_mm=(1, 4)).to_mapping()]},
        )
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert tools.frames[0].position_mm == (5, 8)
    assert tools.datums[0].position_mm == (8, 8)
    assert tools.reference_dimensions[0].first_mm == (0, 5)
    assert editor.canvas.undo_last_operation()
    assert tools.frames == (frame,)
    assert tools.datums == (datum,)
    assert tools.reference_dimensions == (reference,)
    editor.canvas.selected_entity_ids.clear()
    tools.selected_ids = {datum.datum_id}
    tools.selected_id = datum.datum_id
    tools.selected_kind = "datum"
    assert tools.handle_command("MOVE")
    assert tools.handle_command("0,0")
    assert tools.handle_command("0,3")
    assert editor.canvas.entities == [replace(line, start_mm=(0, 3), end_mm=(2, 3))]
    assert tools.frames[0].position_mm == (5, 8)
    assert tools.datums[0].position_mm == (8, 8)
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [line]
    for identity, kind in ((frame.frame_id, "frame"), (reference.dimension_id, "reference")):
        tools.selected_ids = {identity}
        tools.selected_id = identity
        tools.selected_kind = kind
        assert tools.handle_command("MOVE")
        assert tools.handle_command("0,0")
        assert tools.handle_command("0,3")
        assert editor.canvas.entities == [replace(line, start_mm=(0, 3), end_mm=(2, 3))]
        assert editor.canvas.undo_last_operation()


@pytest.mark.parametrize(
    ("copy_source", "boxed", "grouped"),
    [
        (False, False, True),
        (True, False, True),
        (True, True, True),
        (False, False, False),
        (True, False, False),
    ],
)
def test_canvas_transform_accepts_direct_geometry_and_datum_seeds(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    copy_source: bool,
    boxed: bool,
    grouped: bool,
) -> None:
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.persistence import save_document
    from mycad.ui.drawing_collection_session import DrawingCollectionTransformPreview
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 3),
        (3, 2),
        layout_mode="shared" if boxed else "legacy",
        box_size_mm=(3, 3) if boxed else None,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),
            DrawingObjectRef("datum", datum.datum_id),
        ),
    )
    if grouped:
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
        )
    editor.canvas.selected_entity_ids = {line.entity_id}
    tools.selected_ids = {datum.datum_id}
    tools.selected_id = datum.datum_id
    tools.selected_kind = "datum"
    editor.canvas.begin_transform("copy" if copy_source else "move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    checkpoint = session.checkpoint()
    editor.canvas.preview_collection_displacement(copy_source, (0, 3))
    preview = cast(
        "DrawingCollectionTransformPreview | None",
        vars(editor.canvas)["_collection_transform_preview"],
    )
    assert preview is not None and session.checkpoint() == checkpoint
    assert preview.payload.datums[0].position_mm == (4, 6)
    if boxed:
        assert preview.payload.datums[0] == tools.relayout_recorded_datum(
            preview.payload.datums[0], session.snapshot.text_styles
        )
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    if copy_source:
        assert len(session.snapshot.groups) == (2 if grouped else 0)
        assert len(session.snapshot.datums) == 2
        assert session.snapshot.datums[1].position_mm == (4, 6)
        assert session.snapshot.datums[1].datum_id == preview.payload.datums[0].datum_id
        editor.canvas.cancel_transform()
    else:
        assert session.snapshot.datums[0].position_mm == (4, 6)
        assert editor.canvas.entities == [replace(line, start_mm=(0, 3), end_mm=(2, 3))]
    if boxed:
        copied_datum = session.snapshot.datums[1]
        editor.finish_sketch()
        unit = window.execution_unit
        assert unit is not None
        qtbot.waitUntil(lambda: not unit.is_busy and window.active_sketch_dialog() is not editor)
        path = tmp_path / "boxed-datum-group-copy.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert services.kernel.drawing_datum_identifiers[1] == copied_datum
        assert len(services.kernel.drawing_groups) == 2
        reopened.bus.undo_operation()
        assert services.kernel.drawing_datum_identifiers == (datum,)
        assert services.kernel.drawing_groups == (group,)
        return
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == ((group,) if grouped else ())
    assert session.snapshot.datums == (datum,)


@pytest.mark.parametrize("attached", [False, True])
def test_group_move_from_canvas_preserves_cross_sketch_tangency(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, attached: bool
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.drawing_collection_session import DrawingCollectionTransformPreview
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=_session_id(window))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(
        services, loaded, relation, session_identity=_session_id(window)
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (0, 0),
        attachment=DatumAttachment(
            first.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    if attached:
        loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    refs = (
        DrawingObjectRef("geometry", line.entity_id, first.sketch_id),
        DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
        *((DrawingObjectRef("datum", datum.datum_id),) if attached else ()),
    )
    group = DrawingGroup(uuid4().hex, refs)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("move")
    session = editor.canvas.collection_session
    assert session is not None
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    checkpoint = session.checkpoint()
    editor.canvas.preview_collection_displacement(False, (0, 3))
    preview = cast(
        "DrawingCollectionTransformPreview | None",
        vars(editor.canvas)["_collection_transform_preview"],
    )
    assert preview is not None and session.checkpoint() == checkpoint
    assert {item.entity_id for sketch in preview.payload.sketches for item in sketch.entities} == {
        line.entity_id,
        circle.entity_id,
    }
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert session.snapshot.sketches[0].entities == (
        replace(line, start_mm=(0, 3), end_mm=(10, 3)),
    )
    assert session.snapshot.sketches[1].entities == (replace(circle, center_mm=(5, 5)),)
    assert session.snapshot.cross_tangencies == (relation,)
    if attached:
        assert session.snapshot.datums[0].position_mm == (2, 7)
        assert session.snapshot.datums[0].target_mm == (0, 3)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[:2] == (first, second)
    assert session.snapshot.cross_tangencies == (relation,)
    if attached:
        assert session.snapshot.datums == (datum,)


@pytest.mark.parametrize("operation", ["rotate", "scale", "mirror"])
def test_group_affine_from_canvas_preserves_cross_sketch_tangency(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.core.sketch_edit import mirror_entities, rotate_entities, scale_entities
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=_session_id(window))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(
        services, loaded, relation, session_identity=_session_id(window)
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, first.sketch_id),
            DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform(operation, keep_source=False)
    session = editor.canvas.collection_session
    assert session is not None and editor.canvas.active_transform == operation
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    checkpoint = session.checkpoint()
    if operation == "rotate":
        editor.canvas.preview_collection_affine("rotate", (0, 0), 90)
        expected = rotate_entities((line, circle), (line.entity_id, circle.entity_id), (0, 0), 90)
    elif operation == "scale":
        editor.canvas.preview_collection_affine("scale", (0, 0), 2)
        expected = scale_entities((line, circle), (line.entity_id, circle.entity_id), (0, 0), 2)
    else:
        editor.canvas.preview_collection_mirror(False, (0, 0), (1, 0))
        expected = mirror_entities(
            (line, circle), (line.entity_id, circle.entity_id), (0, 0), (1, 0)
        )
    assert vars(editor.canvas)["_collection_transform_preview"] is not None
    assert session.checkpoint() == checkpoint
    if operation == "rotate":
        assert editor.canvas.apply_rotation_angle(90)
    elif operation == "scale":
        assert editor.canvas.apply_scale_factor(2)
    else:
        editor.canvas.add_coordinate_point((1, 0), exact_point=True)
    assert session.snapshot.sketches[0].entities == (expected[0],)
    assert session.snapshot.sketches[1].entities == (expected[1],)
    assert session.snapshot.cross_tangencies == (
        replace(relation, branch="line_right") if operation == "mirror" else relation,
    )
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[:2] == (first, second)
    assert session.snapshot.cross_tangencies == (relation,)


def test_partial_group_copy_reports_omitted_local_constraint(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (2, 0), (2, 3))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (first, second),
        (relation,),
        editor.layer_table,
    )
    assert editor.canvas.replace_draft_entities(draft.entities, new_relations=(relation,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 9, draft.to_state_mapping(), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in (first, second)
    )
    group = DrawingGroup(uuid4().hex, refs, selectable=False)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {first.entity_id}
    editor.canvas.begin_transform("copy")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 4), exact_point=True)
    assert len(session.snapshot.sketches[-1].entities) == 3
    assert session.snapshot.sketches[-1].constraints == (relation,)
    assert session.snapshot.groups == (group,)
    assert "约束" in editor.status_label.text()
    assert "下一个目标点" in editor.status_label.text()
    editor.canvas.cursor_changed.emit(1.0, 1.0, "")
    assert "约束" in editor.status_label.text() and "下一个目标点" in editor.status_label.text()
    editor.canvas.cancel_transform()
    assert editor.canvas.undo_last_operation() and session.snapshot.sketches[-1] == draft


def test_group_copy_from_canvas_preserves_cross_sketch_tangency(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.drawing_collection_session import DrawingCollectionTransformPreview
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=_session_id(window))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(
        services, loaded, relation, session_identity=_session_id(window)
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, first.sketch_id),
            DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("copy")
    session = editor.canvas.collection_session
    assert session is not None and editor.canvas.active_transform == "copy"
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    before = session.checkpoint()
    editor.canvas.preview_collection_displacement(True, (0, 4))
    preview = cast(
        "DrawingCollectionTransformPreview | None",
        vars(editor.canvas)["_collection_transform_preview"],
    )
    assert preview is not None and session.checkpoint() == before
    preview_ids = {
        item.entity_id for sketch in preview.payload.sketches for item in sketch.entities
    }
    editor.canvas.add_coordinate_point((0, 4), exact_point=True)
    assert len(session.snapshot.groups) == 2 and len(session.snapshot.cross_tangencies) == 2
    copied_group = session.snapshot.groups[-1]
    assert {item.object_id for item in copied_group.members} == preview_ids
    copied_relation = next(
        item
        for item in session.snapshot.cross_tangencies
        if item.relation_id != relation.relation_id
    )
    assert {copied_relation.first.entity_id, copied_relation.second.entity_id} == preview_ids
    operations = cast("list[dict[str, object]]", preview.operation.params["operations"])
    revision = next(item for item in operations if item["id"] == "drawing.sketch.revise")
    revision_params = cast("dict[str, object]", revision["params"])
    relation_mappings = cast("list[dict[str, object]]", revision_params["cross_tangencies"])
    assert relation_mappings[0]["relation_id"] == copied_relation.relation_id
    editor.canvas.cancel_transform()
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,) and session.snapshot.cross_tangencies == (relation,)


def test_group_move_with_attached_datum_updates_canvas(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter

    from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),
            DrawingObjectRef("datum", datum.datum_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    monkeypatch.setattr(editor.canvas, "_cursor", (0, 3))
    transform = cast("Callable[..., None]", vars(type(editor.canvas))["_transform_point"])
    transform(editor.canvas, (0, 3), commit=False)
    drawn: list[DrawingCollectionClipboard] = []

    def record(
        _painter: QPainter,
        payload: DrawingCollectionClipboard,
        _delta: tuple[float, float],
        **_kwargs: object,
    ) -> None:
        drawn.append(payload)

    monkeypatch.setattr(editor.canvas, "_draw_collection_preview", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1
    assert drawn[0].datums[0].label == "A"
    assert drawn[0].datums[0].position_mm == (4, 7)
    assert tools.datums == (datum,)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert tools.datums[0].position_mm == (4, 7)
    assert tools.datums[0].target_mm == (0, 3)
    assert editor.canvas.undo_last_operation()
    assert tools.datums == (datum,)


def test_group_move_with_dimension_updates_once_on_canvas(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter

    from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    if window.viewport is not None:
        monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 2),
        text_position_mm=(5, 2.5),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    _invoke(window, "_sync_drawing_layers")
    draft_line = LineEntity(uuid4().hex, (0, 8), (2, 8))
    assert editor.canvas.replace_draft_entities((draft_line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (draft_line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    ref = DrawingObjectRef("geometry", line.entity_id, saved.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (ref, DrawingObjectRef("dimension", dimension.constraint_id, saved.sketch_id))
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert session.snapshot.sketches[0].constraints == (
        replace(dimension, position_mm=(5, 5), text_position_mm=(5, 5.5)),
    )
    assert editor.canvas.background_constraints == session.snapshot.sketches[0].constraints
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[0] == saved
    editor.canvas.selected_entity_ids.clear()
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    monkeypatch.setattr(editor.canvas, "_cursor", (0, 3))
    transform = cast("Callable[..., None]", vars(type(editor.canvas))["_transform_point"])
    transform(editor.canvas, (0, 3), commit=False)
    drawn: list[DrawingCollectionClipboard] = []

    def record(
        _painter: QPainter,
        payload: DrawingCollectionClipboard,
        _delta: tuple[float, float],
        **_kwargs: object,
    ) -> None:
        drawn.append(payload)

    monkeypatch.setattr(editor.canvas, "_draw_collection_preview", record)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1
    assert drawn[0].sketches[0].constraints[0].position_mm == (5, 5)
    assert session.snapshot.sketches[0] == saved
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert session.snapshot.sketches[0].constraints == (
        replace(dimension, position_mm=(5, 5), text_position_mm=(5, 5.5)),
    )
    assert editor.canvas.undo_last_operation()
    editor.canvas.selected_entity_ids.clear()
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    editor.canvas.begin_transform("copy")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    transform(editor.canvas, (0, 3), commit=False)
    drawn.clear()
    painter = QPainter(image)
    try:
        _invoke(editor.canvas, "_draw_preview", painter)
    finally:
        painter.end()
    assert len(drawn) == 1
    preview_dimension = drawn[0].sketches[0].constraints[0].constraint_id
    editor.canvas.add_coordinate_point((0, 3), exact_point=True)
    assert len(session.snapshot.groups) == 2
    copy_group = session.snapshot.groups[-1]
    assert {ref.kind for ref in copy_group.members} == {"geometry", "dimension"}
    assert (
        next(ref.object_id for ref in copy_group.members if ref.kind == "dimension")
        == preview_dimension
    )
    assert editor.canvas.undo_copy_placement()
    assert session.snapshot.groups == (group,)


def test_versioned_ellipse_draft_can_rebase_earlier_history(qtbot: QtBot) -> None:
    from mycad.core.sketch import EllipseEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    ellipse = EllipseEntity(uuid4().hex, (0, 5), 4, 2)
    assert editor.canvas.replace_draft_entities((line,))
    assert editor.canvas.replace_draft_entities((line, ellipse))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line, ellipse), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 53, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[-1].entities == (line,)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.sketches[-1].entities == (line, ellipse)


def test_cancelling_editor_discards_staged_group_and_draft(qtbot: QtBot) -> None:
    import pytest

    from mycad.core.exceptions import ValidationError
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.reject()
    assert loaded.document.commands == ()
    assert services.kernel.sketches == ()
    assert services.kernel.drawing_groups == ()
    with pytest.raises(ValidationError, match="关闭"):
        _ = session.snapshot


def test_drawing_after_group_is_staged_and_undoable_after_commit(qtbot: QtBot) -> None:
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
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 2), (10, 2))
    assert editor.canvas.replace_draft_entities((first,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (first,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", first.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.replace_draft_entities((first, second))
    assert session.snapshot.sketches[-1].entities == (first, second)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
    )
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.sketches[-1].entities == (first, second)
    loaded.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == (first,)
    assert services.kernel.drawing_groups == (group,)


def test_inferred_relation_after_group_joins_collection_timeline(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, editor.draft_sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.set_snapping_enabled(False)
    editor.canvas.set_tool("直线")
    editor.canvas.add_coordinate_point((0.0, 0.0))
    editor.canvas.add_coordinate_point((10.0, 0.2))
    assert len(editor.canvas.constraints) == 1
    assert session.snapshot.sketches[-1].constraints == tuple(editor.canvas.constraints)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[-1].constraints == ()
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.sketches[-1].constraints == tuple(editor.canvas.constraints)
    relation = editor.canvas.constraints[0]
    session.commit()
    assert services.kernel.sketches[-1].constraints == (relation,)
    loaded.bus.undo_operation()
    assert services.kernel.sketches[-1].constraints == ()
    assert services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("complete", [False, True])
def test_group_clipboard_pastes_cross_sketch_tangency_from_canvas(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, complete: bool
) -> None:
    from PySide6.QtWidgets import QApplication

    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=_session_id(window))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(
        services, loaded, relation, session_identity=_session_id(window)
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    refs = (
        DrawingObjectRef("geometry", line.entity_id, first.sketch_id),
        DrawingObjectRef("geometry", circle.entity_id, second.sketch_id),
    )
    group = DrawingGroup(uuid4().hex, refs if complete else refs[:1])
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    try:
        assert editor.canvas.copy_to_clipboard()
        assert ("外部约束未复制" in editor.canvas.message) is (not complete)
        assert editor.canvas.begin_clipboard_paste()
        editor.canvas.add_coordinate_point((0, 4), exact_point=True)
        if complete:
            assert len(session.snapshot.cross_tangencies) == 2
            copied = next(item for item in session.snapshot.cross_tangencies if item != relation)
            assert {
                (copied.first.sketch_id, copied.first.entity_id),
                (copied.second.sketch_id, copied.second.entity_id),
            } == {(item.sketch_id, item.object_id) for item in session.snapshot.groups[-1].members}
        else:
            assert session.snapshot.cross_tangencies == (relation,)
            assert len(session.snapshot.groups) == 2
        assert editor.canvas.undo_last_operation()
        assert session.snapshot.cross_tangencies == (relation,)
    finally:
        QApplication.clipboard().clear()


def test_group_clipboard_relayouts_renamed_boxed_datum(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    datum = DatumIdentifier(
        uuid4().hex, "A", (4, 4), (0, 0), layout_mode="shared", box_size_mm=(3, 3)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),
            DrawingObjectRef("datum", datum.datum_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    captured: list[DatumIdentifier] = []

    def record(_painter: QPainter, item: object, *_args: object) -> None:
        if isinstance(item, DatumIdentifier):
            captured.append(item)

    monkeypatch.setattr(tools, "draw_clipboard_preview", record)
    try:
        assert editor.canvas.copy_to_clipboard()
        assert editor.canvas.begin_clipboard_paste()
        monkeypatch.setattr(editor.canvas, "_cursor", (0, 3))
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        try:
            _invoke(editor.canvas, "_draw_preview", painter)
        finally:
            painter.end()
        assert len(captured) == 1 and captured[0].label == "B"
        assert captured[0].box_size_mm != datum.box_size_mm
        editor.canvas.add_coordinate_point((0, 3), exact_point=True)
        duplicate = next(
            item for item in session.snapshot.datums if item.datum_id != datum.datum_id
        )
        assert duplicate.label == captured[0].label
        assert duplicate.box_size_mm == captured[0].box_size_mm
        assert editor.canvas.undo_last_operation()
        assert session.snapshot.datums == (datum,)
    finally:
        QApplication.clipboard().clear()


def test_group_clipboard_candidate_preview_is_stable_and_invalidated(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {line.entity_id}
    try:
        assert editor.canvas.copy_to_clipboard() and editor.canvas.begin_clipboard_paste()
        monkeypatch.setattr(editor.canvas, "_cursor", (0, 3))
        image = QImage(100, 100, QImage.Format.Format_ARGB32)

        def draw() -> None:
            painter = QPainter(image)
            try:
                _invoke(editor.canvas, "_draw_preview", painter)
            finally:
                painter.end()

        checkpoint = session.checkpoint()
        draw()
        preview = editor.canvas.collection_paste_preview
        assert preview is not None and session.checkpoint() == checkpoint
        draw()
        assert editor.canvas.collection_paste_preview is preview
        monkeypatch.setattr(editor.canvas, "_cursor", (0, 4))
        draw()
        moved_preview = editor.canvas.collection_paste_preview
        assert moved_preview is not None and moved_preview is not preview
        assert moved_preview.payload.sketches[0].entities[0].entity_id != (
            preview.payload.sketches[0].entities[0].entity_id
        )
        assert editor.canvas.stage_collection_operation(
            ReplayAppend(
                "drawing.group.update", 1, replace(group, name="新名称").to_mapping(), "local"
            )
        )
        editor.canvas.add_coordinate_point((0, 3), exact_point=True)
        new_identity = session.snapshot.groups[-1].members[0].object_id
        assert new_identity not in {
            preview.payload.sketches[0].entities[0].entity_id,
            moved_preview.payload.sketches[0].entities[0].entity_id,
        }
        assert editor.canvas.undo_last_operation()
        assert len(session.snapshot.groups) == 1 and session.snapshot.groups[0].name == "新名称"
    finally:
        QApplication.clipboard().clear()


@pytest.mark.parametrize("crossing", [False, True])
def test_group_window_selection_expands_only_from_direct_hits(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, crossing: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    inside = LineEntity(uuid4().hex, (-4, 0), (4, 0))
    outside = LineEntity(uuid4().hex, (-4, 15), (4, 15))
    crosses = LineEntity(uuid4().hex, (-30, 4), (30, 4))
    lines = (inside, outside, crosses)
    assert editor.canvas.replace_draft_entities(lines)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), lines, layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    refs = tuple(DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in lines)
    for members in (refs[:2], refs[1:]):
        group = DrawingGroup(uuid4().hex, members)
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
        )
    assert editor.canvas.set_tool("选择元素")
    first, second = ((10, 8), (-10, -8)) if crossing else ((-10, 8), (10, -8))
    start, end = editor.canvas.local_to_screen(first), editor.canvas.local_to_screen(second)
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, end)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=end)
    expected_seed = {inside.entity_id, crosses.entity_id} if crossing else {inside.entity_id}
    expected_members = frozenset(refs) if crossing else frozenset(refs[:2])
    assert editor.canvas.selected_entity_ids == expected_seed
    assert editor.canvas.effective_group_selection() == expected_members
    assert editor.canvas.effective_group_selection() == expected_members
    editor.canvas.begin_transform("move")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((0, 5), exact_point=True)
    moved = {item.entity_id: item for item in session.snapshot.sketches[-1].entities}
    inside_moved, outside_moved, crosses_moved = (
        moved[inside.entity_id],
        moved[outside.entity_id],
        moved[crosses.entity_id],
    )
    assert isinstance(inside_moved, LineEntity)
    assert isinstance(outside_moved, LineEntity)
    assert isinstance(crosses_moved, LineEntity)
    assert inside_moved.start_mm == (-4, 5)
    assert outside_moved.start_mm == (-4, 20)
    assert crosses_moved.start_mm == ((-30, 9) if crossing else (-30, 4))
    editor.canvas.cancel_transform()
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[-1].entities == lines


def test_group_clipboard_reports_omitted_local_constraint(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QApplication

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (2, 0), (2, 3))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (first, second),
        (relation,),
        editor.layer_table,
    )
    assert editor.canvas.replace_draft_entities(draft.entities, new_relations=(relation,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    ref = DrawingObjectRef("geometry", first.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_entity_ids = {first.entity_id}
    try:
        assert editor.canvas.copy_to_clipboard()
        assert "外部约束未复制" in editor.canvas.message
        assert editor.canvas.begin_clipboard_paste()
        editor.canvas.add_coordinate_point((0, 4), exact_point=True)
        assert len(session.snapshot.groups) == 2
        original = next(
            item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id
        )
        assert original.constraints == (relation,)
        assert editor.canvas.undo_last_operation()
        assert session.snapshot.groups == (group,)
    finally:
        QApplication.clipboard().clear()


@pytest.mark.parametrize("kind", ["segments", "rectangle", "ends"])
def test_notrim_same_saved_polyline_fillet_stages_both_segment_tangencies(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.core.sketch import ArcEntity, PolylineEntity, RectangleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    if kind == "rectangle":
        polyline = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    elif kind == "ends":
        polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10), (0, 0.5)))
    else:
        polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", polyline.entity_id, saved.sketch_id),),
        selectable=False,
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    history = tuple(loaded.document.commands)
    editor.canvas.set_auto_inference_enabled(True)
    editor.canvas.circle_fillet_radius = 2
    editor.canvas.circle_fillet_trim = False
    assert editor.canvas.set_tool("二维圆角")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    if kind == "ends":
        assert editor.canvas.fillet_open_polyline_ends()
    else:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 5))
        )
    after = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(after.entities) == 1 and isinstance(after.entities[-1], ArcEntity), (
        editor.canvas.message
    )
    assert len(session.snapshot.cross_tangencies) == 2
    assert {item.first.segment_index for item in session.snapshot.cross_tangencies} == (
        {0, 3} if kind == "ends" else {0, 1}
    )
    assert session.snapshot.groups == (group,) and tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.cross_tangencies == ()
    assert editor.canvas.redo_last_operation()
    assert len(session.snapshot.cross_tangencies) == 2
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-same-polyline-fillet.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.cross_sketch_tangencies) == 2
    reopened.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == () and services.kernel.drawing_groups == (
        group,
    )


def test_trim_draft_line_to_saved_circle_stages_tangency_atomically(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import ArcEntity, CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, saved.sketch_id),),
        selectable=False,
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    line = LineEntity(uuid4().hex, (-20, 0), (20, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    history = tuple(loaded.document.commands)
    editor.canvas.set_auto_inference_enabled(True)
    editor.canvas.circle_fillet_radius = 2
    editor.canvas.circle_fillet_trim = True
    assert editor.canvas.set_tool("二维圆角")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((-3, 0))
    )
    before = session.checkpoint()

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟修剪候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((-1.3, 3.5))
        )
    assert "模拟修剪候选失败" in editor.canvas.message
    assert session.checkpoint() == before and tuple(editor.canvas.entities) == (line,)
    assert session.snapshot.cross_tangencies == () and editor.canvas.pending_cross_tangencies == []
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((-1.3, 3.5))
    )
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(result.entities) == 2 and isinstance(result.entities[-1], ArcEntity), (
        editor.canvas.message
    )
    assert result.entities[0] != line
    assert len(session.snapshot.cross_tangencies) == 1
    assert len([item for item in result.constraints if item.kind == "tangent"]) == 1
    assert session.snapshot.groups == (group,) and tuple(loaded.document.commands) == history
    linked_arc = result.entities[-1]
    assert isinstance(linked_arc, ArcEntity)
    checkpoint = session.checkpoint()
    assert not editor.canvas.replace_draft_entities(
        (result.entities[0], replace(linked_arc, center_mm=(50, 50)))
    )
    assert session.checkpoint() == checkpoint
    assert tuple(editor.canvas.entities) == result.entities
    assert len(session.snapshot.cross_tangencies) == 1
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.cross_tangencies == ()
    assert editor.canvas.redo_last_operation()
    assert len(session.snapshot.cross_tangencies) == 1
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-trim-line-circle.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.cross_sketch_tangencies) == 1
    reopened.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == () and services.kernel.drawing_groups == (
        group,
    )


def test_trim_saved_group_line_and_draft_line_stages_both_tangencies(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.core.sketch import ArcEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", first.entity_id, saved.sketch_id),),
        selectable=False,
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    second = LineEntity(uuid4().hex, (0, 0), (0, 20))
    assert editor.canvas.replace_draft_entities((second,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (second,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    history = tuple(loaded.document.commands)
    editor.canvas.set_auto_inference_enabled(True)
    editor.canvas.circle_fillet_radius = 2
    editor.canvas.circle_fillet_trim = True
    assert editor.canvas.set_tool("二维圆角")
    for point in ((10, 0), (0, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    assert revised != saved and result.entities[0] != second, editor.canvas.message
    assert len(result.entities) == 2 and isinstance(result.entities[-1], ArcEntity)
    assert len(session.snapshot.cross_tangencies) == 1
    assert len([item for item in result.constraints if item.kind == "tangent"]) == 1
    assert session.snapshot.groups == (group,) and tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.cross_tangencies == ()
    assert editor.canvas.redo_last_operation()
    assert len(session.snapshot.cross_tangencies) == 1
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-mixed-lines-fillet.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.cross_sketch_tangencies) == 1
    reopened.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == () and services.kernel.drawing_groups == (
        group,
    )


def test_trim_saved_group_rectangle_and_draft_arc_keeps_tangencies_and_mapping(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import ArcEntity, PolylineEntity, RectangleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    rectangle = RectangleEntity(uuid4().hex, (-20, 0), (20, -10))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", rectangle.entity_id, saved.sketch_id),),
        selectable=False,
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    arc = ArcEntity(uuid4().hex, (0, 5), 2, 180, 180)
    assert editor.canvas.replace_draft_entities((arc,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (arc,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    history = tuple(loaded.document.commands)
    editor.canvas.set_auto_inference_enabled(True)
    editor.canvas.circle_fillet_radius = 2
    editor.canvas.circle_fillet_trim = True
    assert editor.canvas.set_tool("二维圆角")
    before = session.checkpoint()

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟矩形圆角候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        for point in ((-3, 0), (-1.3, 3.5)):
            QTest.mouseClick(
                editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
            )
    assert "模拟矩形圆角候选失败" in editor.canvas.message
    assert session.checkpoint() == before and session.snapshot.groups == (group,)
    assert session.snapshot.cross_tangencies == () and tuple(editor.canvas.entities) == (arc,)
    for point in ((-3, 0), (-1.3, 3.5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    assert len(revised.entities) == 1 and isinstance(revised.entities[0], PolylineEntity), (
        editor.canvas.message
    )
    assert revised.entities[0].entity_id != rectangle.entity_id
    assert len(result.entities) == 2 and result.entities[0] != arc
    assert len(session.snapshot.cross_tangencies) == 1
    assert len([item for item in result.constraints if item.kind == "tangent"]) == 1
    new_ref = DrawingObjectRef("geometry", revised.entities[0].entity_id, saved.sketch_id)
    assert session.snapshot.groups[0].members == (new_ref,)
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.cross_tangencies == () and session.snapshot.groups == (group,)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups[0].members == (new_ref,)
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-rectangle-arc-fillet.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.cross_sketch_tangencies) == 1
    reopened.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == () and services.kernel.drawing_groups == (
        group,
    )


@pytest.mark.parametrize("selectable", [False, True])
def test_trim_draft_rectangle_group_member_updates_identity(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, selectable: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import ArcEntity, PolylineEntity, RectangleEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    rectangle = RectangleEntity(uuid4().hex, (-20, 0), (20, -10))
    arc = ArcEntity(uuid4().hex, (0, 5), 2, 180, 180)
    assert editor.canvas.replace_draft_entities((rectangle, arc))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (rectangle, arc), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", rectangle.entity_id, draft.sketch_id),),
        selectable=selectable,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.checkpoint()
    history = tuple(loaded.document.commands)
    editor.canvas.set_auto_inference_enabled(True)
    editor.canvas.circle_fillet_radius = 2
    editor.canvas.circle_fillet_trim = True
    assert editor.canvas.set_tool("二维圆角")
    if not selectable:

        def reject_stage(_operation: ReplayAppend) -> None:
            raise ValidationError("模拟草稿组圆角候选失败")

        with monkeypatch.context() as failure:
            failure.setattr(session, "stage", reject_stage)
            for point in ((-3, 0), (-1.3, 3.5)):
                QTest.mouseClick(
                    editor.canvas,
                    Qt.MouseButton.LeftButton,
                    pos=editor.canvas.local_to_screen(point),
                )
        assert "模拟草稿组圆角候选失败" in editor.canvas.message
        assert session.checkpoint() == before and tuple(editor.canvas.entities) == (rectangle, arc)
        assert session.snapshot.groups == (group,)
        # Keep the first source selection for a retry after a rejected candidate.
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((-1.3, 3.5))
        )
    else:
        for point in ((-3, 0), (-1.3, 3.5)):
            QTest.mouseClick(
                editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
            )
    if selectable:
        assert session.checkpoint() == before and tuple(editor.canvas.entities) == (rectangle, arc)
        assert "组选择" in editor.canvas.message
        return
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(result.entities) == 3 and isinstance(result.entities[0], PolylineEntity), (
        editor.canvas.message
    )
    assert result.entities[0].entity_id != rectangle.entity_id
    new_ref = DrawingObjectRef("geometry", result.entities[0].entity_id, draft.sketch_id)
    assert session.snapshot.groups[0].members == (new_ref,)
    assert len([item for item in result.constraints if item.kind == "tangent"]) == 2
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,) and tuple(editor.canvas.entities) == (rectangle, arc)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups[0].members == (new_ref,)
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-draft-rectangle-fillet.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups[0].members == (new_ref,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("selectable", [False, True])
@pytest.mark.parametrize("shape", ["polyline", "rectangle"])
def test_join_draft_group_polyline_and_line_updates_members(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, selectable: bool, shape: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    if shape == "rectangle":
        polyline = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
        line = LineEntity(uuid4().hex, (15, -10), (15, 5))
        points = ((4, 0), (15, -5))
    else:
        polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -5)))
        line = LineEntity(uuid4().hex, (10, 0), (10, 10))
        points = ((5, 0), (10, 8))
    assert editor.canvas.replace_draft_entities((polyline, line))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (polyline, line), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    polyref = DrawingObjectRef("geometry", polyline.entity_id, draft.sketch_id)
    lineref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (polyref, lineref), selectable=selectable)
    overlap = DrawingGroup(uuid4().hex, (lineref,), selectable=False)
    for item in (group, overlap):
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.create", 1, item.to_mapping(), "local")
        )
    before = session.checkpoint()
    history = tuple(loaded.document.commands)
    editor.canvas.circle_fillet_radius = 2
    editor.canvas.circle_fillet_trim = True
    assert editor.canvas.set_tool("二维圆角")
    for point in points:
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    if selectable:
        assert session.checkpoint() == before and tuple(editor.canvas.entities) == (polyline, line)
        assert "组选择" in editor.canvas.message
        return
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(result.entities) == 1 and isinstance(result.entities[0], PolylineEntity), (
        editor.canvas.message
    )
    newref = DrawingObjectRef("geometry", result.entities[0].entity_id, draft.sketch_id)
    assert (result.entities[0].entity_id == polyline.entity_id) == (shape == "polyline")
    assert session.snapshot.groups == (replace(group, members=(newref,)),)
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group, overlap) and tuple(editor.canvas.entities) == (
        polyline,
        line,
    )
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups == (replace(group, members=(newref,)),)
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-draft-join.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups == (replace(group, members=(newref,)),)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group, overlap)


def test_join_draft_group_rectangle_to_saved_line_maps_draft_identity(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, RectangleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (15, -10), (15, 5))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    assert editor.canvas.replace_draft_entities((rectangle,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (rectangle,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    oldref = DrawingObjectRef("geometry", rectangle.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (oldref,), selectable=False)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    history = tuple(loaded.document.commands)
    editor.canvas.circle_fillet_radius = 2
    editor.canvas.circle_fillet_trim = True
    assert editor.canvas.set_tool("二维圆角")
    for point in ((4, 0), (15, -5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(result.entities) == 1 and isinstance(result.entities[0], PolylineEntity), (
        editor.canvas.message
    )
    assert result.entities[0].entity_id != rectangle.entity_id
    newref = DrawingObjectRef("geometry", result.entities[0].entity_id, draft.sketch_id)
    assert session.snapshot.groups == (replace(group, members=(newref,)),)
    assert all(line not in item.entities for item in session.snapshot.sketches)
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,) and tuple(editor.canvas.entities) == (rectangle,)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups == (replace(group, members=(newref,)),)
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-mixed-join.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups == (replace(group, members=(newref,)),)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)
    assert (
        line
        in next(
            item for item in services.kernel.sketches if item.sketch_id == saved.sketch_id
        ).entities
    )


@pytest.mark.parametrize("shape", ["polyline", "rectangle"])
def test_notrim_whole_saved_group_path_stages_all_tangencies(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, shape: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import ArcEntity, PolylineEntity, RectangleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    source = (
        RectangleEntity(uuid4().hex, (0, 0), (10, 10))
        if shape == "rectangle"
        else PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True)
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", source.entity_id, saved.sketch_id),),
        selectable=False,
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    history = tuple(loaded.document.commands)
    editor.canvas.set_auto_inference_enabled(True)
    assert editor.canvas.set_tool("二维圆角")
    editor.canvas.circle_fillet_radius = 2
    editor.canvas.circle_fillet_trim = False
    editor.canvas.circle_fillet_polyline_pending = True
    if shape == "rectangle":
        before = session.checkpoint()

        def reject_stage(_operation: ReplayAppend) -> None:
            raise ValidationError("模拟整体圆角候选失败")

        with monkeypatch.context() as failure:
            failure.setattr(session, "stage", reject_stage)
            QTest.mouseClick(
                editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
            )
        assert "模拟整体圆角候选失败" in editor.canvas.message
        assert session.checkpoint() == before and tuple(editor.canvas.entities) == ()
        assert session.snapshot.cross_tangencies == () and session.snapshot.groups == (group,)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(result.entities) == 4 and all(
        isinstance(item, ArcEntity) for item in result.entities
    ), editor.canvas.message
    assert len(session.snapshot.cross_tangencies) == 8
    assert session.snapshot.groups == (group,) and tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.cross_tangencies == ()
    assert editor.canvas.redo_last_operation()
    assert len(session.snapshot.cross_tangencies) == 8
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-whole-fillet.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.cross_sketch_tangencies) == 8
    reopened.bus.undo_operation()
    assert services.kernel.cross_sketch_tangencies == () and services.kernel.drawing_groups == (
        group,
    )


def test_trim_draft_group_rectangle_and_saved_arc_maps_draft_identity(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import ArcEntity, PolylineEntity, RectangleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    arc = ArcEntity(uuid4().hex, (0, 5), 2, 180, 180)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    rectangle = RectangleEntity(uuid4().hex, (-20, 0), (20, -10))
    assert editor.canvas.replace_draft_entities((rectangle,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (rectangle,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    oldref = DrawingObjectRef("geometry", rectangle.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (oldref,), selectable=False)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    history = tuple(loaded.document.commands)
    editor.canvas.set_auto_inference_enabled(True)
    editor.canvas.circle_fillet_radius = 2
    editor.canvas.circle_fillet_trim = True
    assert editor.canvas.set_tool("二维圆角")
    before = session.checkpoint()

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟混合组圆角失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        for point in ((-3, 0), (-1.3, 3.5)):
            QTest.mouseClick(
                editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
            )
    assert "模拟混合组圆角失败" in editor.canvas.message
    assert session.checkpoint() == before and session.snapshot.groups == (group,)
    assert session.snapshot.cross_tangencies == () and tuple(editor.canvas.entities) == (rectangle,)
    for point in ((-3, 0), (-1.3, 3.5)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    revised = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    assert len(result.entities) == 2 and isinstance(result.entities[0], PolylineEntity), (
        editor.canvas.message
    )
    assert result.entities[0].entity_id != rectangle.entity_id and revised != saved
    newref = DrawingObjectRef("geometry", result.entities[0].entity_id, draft.sketch_id)
    assert session.snapshot.groups == (replace(group, members=(newref,)),)
    assert len(session.snapshot.cross_tangencies) == 1
    assert len([item for item in result.constraints if item.kind == "tangent"]) == 1
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.groups == (group,) and session.snapshot.cross_tangencies == ()
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.groups == (replace(group, members=(newref,)),)
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-draft-rectangle-saved-arc.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups == (replace(group, members=(newref,)),)
    reopened.bus.undo_operation()
    assert (
        services.kernel.drawing_groups == (group,) and services.kernel.cross_sketch_tangencies == ()
    )


def test_constraint_solution_in_collection_rolls_back_failed_candidate(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.checkpoint()
    history = tuple(loaded.document.commands)
    solved_line = replace(line, end_mm=(15, 0))
    solved = replace(draft, entities=(solved_line,))

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟求解候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        assert not editor.canvas.apply_constraint_solution(draft, solved)
    assert "模拟求解候选失败" in editor.canvas.message
    assert session.checkpoint() == before and tuple(editor.canvas.entities) == (line,)
    assert session.snapshot.groups == (group,) and tuple(loaded.document.commands) == history
    assert editor.canvas.apply_constraint_solution(draft, solved)
    assert tuple(editor.canvas.entities) == (solved_line,)
    assert session.snapshot.sketches[-1].entities == (solved_line,)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.sketches[-1].entities == (line,)
    assert editor.canvas.redo_last_operation()
    assert session.snapshot.sketches[-1].entities == (solved_line,)
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-constraint-solution.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches[-1].entities == (solved_line,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == (line,)
    assert services.kernel.drawing_groups == (group,)


def test_confirmed_draft_dimension_add_and_update_share_collection_timeline(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    assert editor.canvas.replace_draft_entities((circle,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (circle,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    history = tuple(loaded.document.commands)
    constraint = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 7, "mm"
    )
    result = services.kernel.preview_sketch_constraint(draft, constraint)
    assert result.status == "success" and result.sketch is not None
    checkpoint = session.checkpoint()

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟尺寸候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        assert not editor.canvas.apply_constraint_solution(
            draft, result.sketch, confirmed_constraint=constraint, solve_result=result
        )
    assert session.checkpoint() == checkpoint and tuple(editor.canvas.entities) == (circle,)
    assert editor.canvas.apply_constraint_solution(
        draft, result.sketch, confirmed_constraint=constraint, solve_result=result
    ), editor.canvas.message
    added = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert (
        added.entities == result.sketch.entities and added.constraints == result.sketch.constraints
    )
    updated_constraint = replace(constraint, value=9)
    updated = services.kernel.preview_sketch_constraint_update(added, updated_constraint)
    assert updated.status == "success" and updated.sketch is not None
    assert editor.canvas.apply_constraint_solution(
        added, updated.sketch, confirmed_constraint=updated_constraint, solve_result=updated
    ), editor.canvas.message
    final = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert (
        final.entities == updated.sketch.entities
        and final.constraints == updated.sketch.constraints
    )
    assert tuple(loaded.document.commands) == history and session.snapshot.groups == (group,)
    assert editor.canvas.undo_last_operation() and session.snapshot.sketches[-1] == added
    assert editor.canvas.undo_last_operation() and session.snapshot.sketches[-1] == draft
    assert editor.canvas.redo_last_operation() and session.snapshot.sketches[-1] == added
    assert editor.canvas.redo_last_operation() and session.snapshot.sketches[-1] == final
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-dimension-add-update.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches[-1] == final
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1] == added
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1] == draft and services.kernel.drawing_groups == (group,)


def test_dimension_tool_confirms_draft_radius_in_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import CircleEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    assert editor.canvas.replace_draft_entities((circle,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (circle,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    history = tuple(loaded.document.commands)
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["radius"].click()
    for point in ((5, 0), (10, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    editor.dimensions.value_editor.setValue(7)
    candidate = editor.dimensions.candidate
    assert candidate is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(draft, candidate) is not None, timeout=15000
    )
    preview = editor.dimensions.accepted_preview(draft, candidate)
    assert preview is not None and preview.status == "success"
    editor.dimensions.apply_button.click()
    current = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(current.constraints) == 1 and current.constraints[0].value == 7, (
        editor.status_label.text()
    )
    assert isinstance(current.entities[0], CircleEntity) and current.entities[
        0
    ].radius_mm == pytest.approx(7)
    assert tuple(loaded.document.commands) == history and session.snapshot.groups == (group,)
    assert editor.canvas.undo_last_operation() and session.snapshot.sketches[-1] == draft
    session.cancel()
    editor.canvas.collection_session = None


def test_local_tangency_command_stages_confirmed_constraint_in_collection(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (5, 4), 2)
    assert editor.canvas.replace_draft_entities((line, circle))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line, circle), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    history = tuple(loaded.document.commands)
    editor.canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    checkpoint = session.checkpoint()

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟相切候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        window.act_cross_sketch_tangency.trigger()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert "模拟相切候选失败" in window.status_command.text()
    assert session.checkpoint() == checkpoint and tuple(editor.canvas.entities) == (line, circle)
    assert session.snapshot.groups == (group,) and tuple(loaded.document.commands) == history
    editor.canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(result.constraints) == 1 and result.constraints[0].kind == "tangent", (
        window.status_command.text()
    )
    assert session.snapshot.groups == (group,) and tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation() and session.snapshot.sketches[-1] == draft
    assert editor.canvas.redo_last_operation() and session.snapshot.sketches[-1] == result
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-local-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches[-1] == result
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1] == draft and services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("selectable", [False, True])
def test_local_tangency_with_cross_relation_uses_collection_timeline(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, selectable: bool
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    linked = CircleEntity(uuid4().hex, (15, 2), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (linked,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (5, 4), 2)
    assert editor.canvas.replace_draft_entities((line, circle))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line, circle), layers=editor.layer_table
    )
    pairs = ((linked.entity_id, line.entity_id),)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 7, draft.to_mapping(version=7), "local"),
        session_identity=_session_id(window),
    )
    session.rebase_draft(draft, cross_tangent_pairs=pairs)
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    editor.canvas.pending_cross_tangencies = list(pairs)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, draft.sketch_id),),
        selectable=selectable,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.snapshot
    history = tuple(loaded.document.commands)
    editor.canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    checkpoint = session.checkpoint()

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟混合相切候选失败")

    if not selectable:
        with monkeypatch.context() as failure:
            failure.setattr(session, "stage", reject_stage)
            window.act_cross_sketch_tangency.trigger()
            qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
        assert "模拟混合相切候选失败" in window.status_command.text()
        assert session.checkpoint() == checkpoint and session.snapshot == before
        assert tuple(editor.canvas.entities) == (line, circle)
        editor.canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    if selectable:
        assert "组选择" in window.status_command.text()
        assert session.checkpoint() == checkpoint and session.snapshot == before
        return
    result = next(item for item in session.snapshot.sketches if item.sketch_id == draft.sketch_id)
    assert len(result.constraints) == 1 and result.constraints[0].kind == "tangent", (
        window.status_command.text()
    )
    assert len(session.snapshot.cross_tangencies) == 1 and session.snapshot.groups == (group,)
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation()
    assert len(session.snapshot.cross_tangencies) == 1 and session.snapshot.sketches[-1] == result
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-mixed-local-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.cross_sketch_tangencies) == 1
    reopened.bus.undo_operation()
    assert len(services.kernel.cross_sketch_tangencies) == 1
    assert not services.kernel.sketches[-1].constraints and services.kernel.drawing_groups == (
        group,
    )


def test_dimension_tool_on_cross_tangent_draft_uses_collection_component(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    assert editor.canvas.replace_draft_entities((circle,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (circle,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 7, draft.to_mapping(version=7), "local"),
        session_identity=_session_id(window),
    )
    session.rebase_draft(draft, cross_tangent_pairs=((line.entity_id, circle.entity_id),))
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.snapshot
    history = tuple(loaded.document.commands)
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["radius"].click()
    for point in ((0, 4), (8, 8)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    editor.dimensions.value_editor.setValue(3)
    candidate = editor.dimensions.candidate
    assert candidate is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(draft, candidate) is not None, timeout=15000
    )
    preview = editor.dimensions.accepted_preview(draft, candidate)
    assert preview is not None and preview.status == "success"
    assert editor.canvas.dimension_linked_sources
    checkpoint = session.checkpoint()

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟联动尺寸候选失败")

    unit = window.execution_unit
    assert unit is not None
    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        editor.dimensions.apply_button.click()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert "模拟联动尺寸候选失败" in editor.status_label.text()
    assert session.checkpoint() == checkpoint and session.snapshot == before
    editor.dimensions.apply_button.click()
    qtbot.waitUntil(lambda: bool(session.snapshot.sketches[-1].constraints), timeout=15000)
    after = session.snapshot
    result = next(item for item in after.sketches if item.sketch_id == draft.sketch_id)
    assert isinstance(result.entities[0], CircleEntity) and result.entities[
        0
    ].radius_mm == pytest.approx(3)
    assert len(after.cross_tangencies) == 1 and after.groups == (group,)
    validate_tangency_component(after.sketches, after.cross_tangencies, draft.sketch_id)
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-linked-dimension.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after.sketches
    reopened.bus.undo_operation()
    assert services.kernel.sketches == before.sketches and services.kernel.drawing_groups == (
        group,
    )


def test_dimension_tool_updates_saved_geometry_in_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    line = LineEntity(uuid4().hex, (20, 0), (30, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, saved.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.snapshot
    history = tuple(loaded.document.commands)
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["radius"].click()
    for point in ((5, 0), (10, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    editor.dimensions.value_editor.setValue(7)
    candidate = editor.dimensions.candidate
    assert candidate is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(saved, candidate) is not None, timeout=15000
    )
    preview = editor.dimensions.accepted_preview(saved, candidate)
    assert preview is not None and preview.status == "success", editor.status_label.text()
    checkpoint = session.checkpoint()
    unit = window.execution_unit
    assert unit is not None

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟已保存尺寸候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        editor.dimensions.apply_button.click()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert "模拟已保存尺寸候选失败" in editor.status_label.text()
    assert session.checkpoint() == checkpoint and session.snapshot == before
    editor.dimensions.apply_button.click()
    qtbot.waitUntil(lambda: bool(session.snapshot.sketches[0].constraints), timeout=15000)
    after = session.snapshot
    updated = next(item for item in after.sketches if item.sketch_id == saved.sketch_id)
    assert isinstance(updated.entities[0], CircleEntity) and updated.entities[
        0
    ].radius_mm == pytest.approx(7)
    assert updated.constraints[0].value == 7 and after.groups == (group,)
    assert tuple(loaded.document.commands) == history and services.kernel.sketches == (saved,)
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-saved-dimension.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after.sketches
    reopened.bus.undo_operation()
    assert services.kernel.sketches == before.sketches and services.kernel.drawing_groups == (
        group,
    )


@pytest.mark.parametrize("action", ["change", "confirm"])
def test_dimension_preview_handles_expired_collection_without_changing_draft(
    qtbot: QtBot, action: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import CircleEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    assert editor.canvas.replace_draft_entities((circle,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (circle,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["radius"].click()
    for point in ((5, 0), (10, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    editor.dimensions.value_editor.setValue(7)
    assert editor.dimensions.candidate is not None
    history_position = editor.canvas.history_position
    history = tuple(loaded.document.commands)
    getattr(loaded.document, _REVISION_METHOD)()
    if action == "change":
        editor.dimensions.value_editor.setValue(8)
    else:
        editor.dimensions.apply_button.click()
    assert "变化" in editor.status_label.text()
    assert not editor.dimensions.apply_button.isEnabled()
    assert (
        tuple(editor.canvas.entities) == (circle,)
        and editor.canvas.history_position == history_position
    )
    assert tuple(loaded.document.commands) == history


@pytest.mark.parametrize("saved", [False, True])
def test_dimension_rejects_partial_edit_of_selectable_group(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, saved: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    line = LineEntity(uuid4().hex, (20, 0), (30, 0))
    if saved:
        source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
        app.commit_new_sketch(services, loaded, source, session_identity=_session_id(window))
        editor.set_context_sketches(services.kernel.sketches)
        editor.canvas.set_source_context_revision(loaded.document.revision)
        entities = (line,)
    else:
        source = None
        entities = (circle, line)
    assert editor.canvas.replace_draft_entities(entities)
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), entities, layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    circle_ref = DrawingObjectRef(
        "geometry", circle.entity_id, source.sketch_id if source else draft.sketch_id
    )
    group = DrawingGroup(
        uuid4().hex, (circle_ref, DrawingObjectRef("geometry", line.entity_id, draft.sketch_id))
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.checkpoint()
    history = tuple(loaded.document.commands)
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["radius"].click()
    for point in ((5, 0), (10, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    editor.dimensions.value_editor.setValue(7)
    candidate = editor.dimensions.candidate
    assert candidate is not None
    original = source if source is not None else draft
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, candidate) is not None, timeout=15000
    )
    preview = editor.dimensions.accepted_preview(original, candidate)
    assert preview is not None
    if preview.status == "success":
        editor.dimensions.apply_button.click()
        unit = window.execution_unit
        assert unit is not None
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert "组选择" in editor.status_label.text()
    assert session.checkpoint() == before and tuple(loaded.document.commands) == history
    assert tuple(editor.canvas.entities) == entities and session.snapshot.groups == (group,)


@pytest.mark.parametrize("selectable", [False, True])
def test_saved_group_dimension_respects_group_selection_without_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, selectable: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
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
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    line = LineEntity(uuid4().hex, (20, 0), (30, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle, line))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", circle.entity_id, saved.sketch_id),
            DrawingObjectRef("geometry", line.entity_id, saved.sketch_id),
        ),
        selectable=selectable,
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    history = tuple(loaded.document.commands)
    assert editor.canvas.collection_session is None
    editor.dimensions.driving_check.setChecked(True)
    editor.dimensions.buttons["radius"].click()
    for point in ((5, 0), (10, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    editor.dimensions.value_editor.setValue(7)
    candidate = editor.dimensions.candidate
    assert candidate is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(saved, candidate) is not None, timeout=15000
    )
    preview = editor.dimensions.accepted_preview(saved, candidate)
    assert preview is not None
    if preview.status == "success":
        editor.dimensions.apply_button.click()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    if selectable:
        assert "组选择" in editor.status_label.text()
        assert tuple(loaded.document.commands) == history and services.kernel.sketches == (saved,)
        assert services.kernel.drawing_groups == (group,)
    else:
        updated = services.kernel.sketches[0]
        assert isinstance(updated.entities[0], CircleEntity) and updated.entities[
            0
        ].radius_mm == pytest.approx(7)
        assert updated.constraints and updated.constraints[0].value == 7
        assert services.kernel.drawing_groups == (group,)
        loaded.bus.undo_operation()
        assert services.kernel.sketches == (saved,)


@pytest.mark.parametrize("selectable", [False, True])
def test_saved_local_tangency_respects_group_selection(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, selectable: bool
) -> None:
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (5, 4), 2)
    extra = LineEntity(uuid4().hex, (30, 0), (40, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle, extra))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", circle.entity_id, saved.sketch_id),
            DrawingObjectRef("geometry", extra.entity_id, saved.sketch_id),
        ),
        selectable=selectable,
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    history = tuple(loaded.document.commands)
    editor.canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    if selectable:
        assert "组选择" in window.status_command.text()
        assert tuple(loaded.document.commands) == history and services.kernel.sketches == (saved,)
    else:
        assert len(services.kernel.sketches[0].constraints) == 1, window.status_command.text()
        assert services.kernel.drawing_groups == (group,)
        loaded.bus.undo_operation()
        assert services.kernel.sketches == (saved,)


@pytest.mark.parametrize("selectable", [False, True])
def test_saved_local_tangency_stays_in_existing_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, selectable: bool
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (5, 4), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    draft_line = LineEntity(uuid4().hex, (30, 0), (40, 0))
    assert editor.canvas.replace_draft_entities((draft_line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (draft_line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, saved.sketch_id),),
        selectable=selectable,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.snapshot
    history = tuple(loaded.document.commands)
    editor.canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    if not selectable:
        checkpoint = session.checkpoint()

        def reject_stage(_operation: ReplayAppend) -> None:
            raise ValidationError("模拟已保存相切候选失败")

        with monkeypatch.context() as failure:
            failure.setattr(session, "stage", reject_stage)
            window.act_cross_sketch_tangency.trigger()
            qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
        assert "模拟已保存相切候选失败" in window.status_command.text()
        assert session.checkpoint() == checkpoint and session.snapshot == before
        editor.canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    if selectable:
        assert "组选择" in window.status_command.text()
        assert session.snapshot == before and tuple(loaded.document.commands) == history
        return
    result = next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
    assert len(result.constraints) == 1 and result.constraints[0].kind == "tangent", (
        window.status_command.text()
    )
    assert tuple(loaded.document.commands) == history and services.kernel.sketches == (saved,)
    assert session.snapshot.groups == (group,)
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation()
    assert (
        next(item for item in session.snapshot.sketches if item.sketch_id == saved.sketch_id)
        == result
    )
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-saved-local-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches[0] == result
    reopened.bus.undo_operation()
    assert services.kernel.sketches[0] == saved and services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("selectable", [False, True])
def test_cross_tangency_between_saved_and_draft_uses_collection_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, selectable: bool
) -> None:
    from mycad.core.cross_sketch_tangency import validate_tangency_component
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    circle = CircleEntity(uuid4().hex, (0, 4), 2)
    assert editor.canvas.replace_draft_entities((circle,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (circle,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, draft.sketch_id),),
        selectable=selectable,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.snapshot
    history = tuple(loaded.document.commands)
    editor.canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    if selectable:
        window.act_cross_sketch_tangency.trigger()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
        dialog = window.findChild(CrossSketchTangencyDialog)
        assert dialog is not None and "组选择" in dialog.status_label.text()
        assert session.snapshot == before and tuple(loaded.document.commands) == history
        dialog.reject()
        return
    checkpoint = session.checkpoint()

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟跨草图相切候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        window.act_cross_sketch_tangency.trigger()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    dialog = window.findChild(CrossSketchTangencyDialog)
    assert dialog is not None and "候选失败" in dialog.status_label.text()
    assert session.checkpoint() == checkpoint and session.snapshot == before
    dialog.preview_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert dialog.commit_button.isEnabled(), dialog.status_label.text()
    dialog.commit_button.click()
    after = session.snapshot
    assert len(after.cross_tangencies) == 1, window.status_command.text()
    validate_tangency_component(after.sketches, after.cross_tangencies, draft.sketch_id)
    assert after.groups == (group,) and tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-new-cross-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.cross_sketch_tangencies) == 1
    reopened.bus.undo_operation()
    assert not services.kernel.cross_sketch_tangencies and services.kernel.drawing_groups == (
        group,
    )


def test_remove_cross_tangency_from_collection_dialog_is_undoable(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    assert editor.canvas.replace_draft_entities((circle,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (circle,), layers=editor.layer_table
    )
    pairs = ((line.entity_id, circle.entity_id),)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 7, draft.to_mapping(version=7), "local"),
        session_identity=_session_id(window),
    )
    session.rebase_draft(draft, cross_tangent_pairs=pairs)
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    editor.canvas.pending_cross_tangencies = list(pairs)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.snapshot
    history = tuple(loaded.document.commands)
    dialog_method = "_on_cross_sketch_tangency"
    cast("Callable[..., None]", getattr(window, dialog_method))(force_dialog=True)
    dialog = window.findChild(CrossSketchTangencyDialog)
    assert dialog is not None and dialog.existing_combo.count() == 1
    checkpoint = session.checkpoint()

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟相切删除候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        dialog.remove_button.click()
    assert "候选失败" in dialog.status_label.text()
    assert session.checkpoint() == checkpoint and session.snapshot == before
    assert editor.canvas.pending_cross_tangencies == list(pairs)
    dialog.remove_button.click()
    after = session.snapshot
    assert not after.cross_tangencies and after.groups == (group,), dialog.status_label.text()
    assert (
        editor.canvas.pending_cross_tangencies == [] and tuple(loaded.document.commands) == history
    )
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.pending_cross_tangencies == list(pairs)
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    assert editor.canvas.pending_cross_tangencies == []
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-remove-cross-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert not services.kernel.cross_sketch_tangencies
    reopened.bus.undo_operation()
    assert len(services.kernel.cross_sketch_tangencies) == 1 and services.kernel.drawing_groups == (
        group,
    )


def test_cross_tangency_preserves_stable_polyline_point_ids_in_collection(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.geometric_tolerance_topology import new_curve_point_identities
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, PolylineEntity, WorkPlaneFrame
    from mycad.ui.cross_sketch_tangency_dialog import CrossSketchTangencyDialog
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    path_id = uuid4().hex
    points = new_curve_point_identities(path_id, "polyline", 3)
    path_entity = PolylineEntity(path_id, ((0, 0), (10, 0), (10, 10)), point_ids=points)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (path_entity,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    circle = CircleEntity(uuid4().hex, (5, 4), 2)
    assert editor.canvas.replace_draft_entities((circle,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (circle,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.snapshot
    history = tuple(loaded.document.commands)
    select_method = "_select_at"
    select = cast("Callable[..., None]", getattr(editor.canvas, select_method))
    select((5, 0), additive=False)
    select((5, 6), additive=True)
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    dialog = window.findChild(CrossSketchTangencyDialog)
    after = session.snapshot
    assert len(after.cross_tangencies) == 1, (
        dialog.status_label.text() if dialog else window.status_command.text()
    )
    result = next(item for item in after.sketches if item.sketch_id == saved.sketch_id).entities[0]
    assert isinstance(result, PolylineEntity) and result.point_ids == points
    assert after.groups == (group,) and tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-cross-curve-identities.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    restored = services.kernel.sketches[0].entities[0]
    assert isinstance(restored, PolylineEntity) and restored.point_ids == points
    assert len(services.kernel.cross_sketch_tangencies) == 1
    reopened.bus.undo_operation()
    assert services.kernel.sketches[0] == saved and not services.kernel.cross_sketch_tangencies


def test_local_tangency_after_new_collection_cross_tangency_uses_component(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved_line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    circle = CircleEntity(uuid4().hex, (0, 4), 2)
    draft_line = LineEntity(uuid4().hex, (-10, 10), (10, 10))
    assert editor.canvas.replace_draft_entities((circle, draft_line))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (circle, draft_line),
        layers=editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(saved.sketch_id, saved_line.entity_id),
        CrossSketchRef(draft.sketch_id, circle.entity_id),
        "line_left",
    )
    original, solved = app.prepare_cross_sketch_tangency_from_state(
        session.snapshot.sketches, session.snapshot.cross_tangencies, relation
    )
    operation = ReplayAppend(
        "drawing.tangency.add",
        12,
        {
            "relation": relation.to_mapping(),
            "revisions": list(app.build_tangency_revisions(original, solved)),
        },
        "local",
    )
    assert editor.canvas.stage_collection_operation(operation), editor.canvas.message
    assert editor.canvas.pending_cross_tangencies == []
    before = session.snapshot
    history = tuple(loaded.document.commands)
    editor.canvas.selected_entity_ids = {circle.entity_id, draft_line.entity_id}
    window.act_cross_sketch_tangency.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    after = session.snapshot
    current = next(item for item in after.sketches if item.sketch_id == draft.sketch_id)
    assert len(current.constraints) == 1 and current.constraints[0].kind == "tangent", (
        window.status_command.text()
    )
    assert after.cross_tangencies == (relation,) and after.groups == (group,)
    validate_tangency_component(after.sketches, after.cross_tangencies, draft.sketch_id)
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-new-cross-then-local-tangent.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        len(services.kernel.cross_sketch_tangencies) == 1
        and services.kernel.sketches[-1].constraints
    )
    reopened.bus.undo_operation()
    assert (
        len(services.kernel.cross_sketch_tangencies) == 1
        and not services.kernel.sketches[-1].constraints
    )


@pytest.mark.parametrize("staged", [True, False])
def test_finish_collection_with_staged_cross_tangency_commits_and_reopens(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, staged: bool
) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    assert editor.canvas.replace_draft_entities((circle,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (circle,), layers=editor.layer_table
    )
    pairs = ((line.entity_id, circle.entity_id),)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 7, draft.to_mapping(version=7), "local"),
        session_identity=_session_id(window),
    )
    if staged:
        session.rebase_draft(draft, cross_tangent_pairs=pairs)
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    editor.canvas.pending_cross_tangencies = list(pairs)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    snapshot = session.snapshot
    history = tuple(loaded.document.commands)
    editor.finish_button.click()
    if not staged:
        assert window.active_sketch_dialog() is editor and "关联" in editor.status_label.text()
        assert session.snapshot == snapshot and tuple(loaded.document.commands) == history
        return
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    assert services.kernel.sketches == snapshot.sketches and services.kernel.drawing_groups == (
        group,
    )
    assert services.kernel.cross_sketch_tangencies == snapshot.cross_tangencies
    path = tmp_path / "collection-finish-cross-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == snapshot.sketches
        and len(services.kernel.cross_sketch_tangencies) == 1
    )
    reopened.bus.undo_operation()
    assert not services.kernel.drawing_groups and len(services.kernel.cross_sketch_tangencies) == 1


def test_group_grip_drag_rolls_back_failed_collection_candidate(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(900, 620)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", line.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    checkpoint = session.checkpoint()
    position = editor.canvas.history_position
    start, target = editor.canvas.local_to_screen((10, 0)), editor.canvas.local_to_screen((15, 0))

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟夹点候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(editor.canvas, target, delay=30)
        assert editor.canvas.entities != [line] and session.checkpoint() == checkpoint
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=target)
    assert "模拟夹点候选失败" in editor.canvas.message
    assert editor.canvas.entities == [line] and session.checkpoint() == checkpoint
    assert editor.canvas.history_position == position
    editor.canvas.selected_entity_ids = {line.entity_id}
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, target, delay=30)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=target)
    moved = tuple(editor.canvas.entities)
    assert moved != (line,) and session.snapshot.sketches[-1].entities == moved
    assert editor.canvas.undo_last_operation() and session.snapshot.sketches[-1].entities == (line,)
    assert editor.canvas.redo_last_operation() and session.snapshot.sketches[-1].entities == moved
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-grip-retry.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches[-1].entities == moved
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == (line,) and services.kernel.drawing_groups == (
        group,
    )


def test_grip_drag_after_new_collection_cross_tangency_uses_component(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved_line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    circle = CircleEntity(uuid4().hex, (0, 4), 2)
    draft_line = LineEntity(uuid4().hex, (-10, 10), (10, 10))
    assert editor.canvas.replace_draft_entities((circle, draft_line))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (circle, draft_line),
        layers=editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", circle.entity_id, draft.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(saved.sketch_id, saved_line.entity_id),
        CrossSketchRef(draft.sketch_id, circle.entity_id),
        "line_left",
    )
    original, solved = app.prepare_cross_sketch_tangency_from_state(
        session.snapshot.sketches, session.snapshot.cross_tangencies, relation
    )
    operation = ReplayAppend(
        "drawing.tangency.add",
        12,
        {
            "relation": relation.to_mapping(),
            "revisions": list(app.build_tangency_revisions(original, solved)),
        },
        "local",
    )
    assert editor.canvas.stage_collection_operation(operation), editor.canvas.message
    assert editor.canvas.pending_cross_tangencies == []
    before = session.snapshot
    history = tuple(loaded.document.commands)
    assert editor.canvas.set_tool("选择元素")
    editor.snap_check.setChecked(False)
    editor.canvas.selected_entity_ids = {circle.entity_id}
    current = next(item for item in before.sketches if item.sketch_id == draft.sketch_id)
    moved_circle = next(item for item in current.entities if item.entity_id == circle.entity_id)
    assert isinstance(moved_circle, CircleEntity)
    start = editor.canvas.local_to_screen(moved_circle.center_mm)
    target = editor.canvas.local_to_screen(
        (moved_circle.center_mm[0], moved_circle.center_mm[1] + 1)
    )

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟联动夹点候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(editor.canvas, target, delay=30)
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=target)
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert "模拟联动夹点候选失败" in editor.canvas.message
    assert session.snapshot == before and tuple(loaded.document.commands) == history
    editor.canvas.selected_entity_ids = {circle.entity_id}
    start = editor.canvas.local_to_screen(moved_circle.center_mm)
    target = editor.canvas.local_to_screen(
        (moved_circle.center_mm[0], moved_circle.center_mm[1] + 1)
    )
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, target, delay=30)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=target)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    after = session.snapshot
    assert after != before, editor.canvas.message
    assert after.cross_tangencies == (relation,) and after.groups == (group,)
    validate_tangency_component(after.sketches, after.cross_tangencies, draft.sketch_id)
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-cross-grip.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == before.sketches


def test_saved_grip_drag_after_new_collection_cross_tangency_uses_component(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        validate_tangency_component,
    )
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved_line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    circle = CircleEntity(uuid4().hex, (0, 4), 2)
    draft_line = LineEntity(uuid4().hex, (-10, 10), (10, 10))
    assert editor.canvas.replace_draft_entities((circle, draft_line))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (circle, draft_line),
        layers=editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", saved_line.entity_id, saved.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(saved.sketch_id, saved_line.entity_id),
        CrossSketchRef(draft.sketch_id, circle.entity_id),
        "line_left",
    )
    original, solved = app.prepare_cross_sketch_tangency_from_state(
        session.snapshot.sketches, session.snapshot.cross_tangencies, relation
    )
    operation = ReplayAppend(
        "drawing.tangency.add",
        12,
        {
            "relation": relation.to_mapping(),
            "revisions": list(app.build_tangency_revisions(original, solved)),
        },
        "local",
    )
    assert editor.canvas.stage_collection_operation(operation), editor.canvas.message
    assert editor.canvas.pending_cross_tangencies == []
    before = session.snapshot
    history = tuple(loaded.document.commands)
    assert editor.canvas.set_tool("选择元素")
    editor.snap_check.setChecked(False)
    editor.canvas.selected_entity_ids = {saved_line.entity_id}
    current_saved = next(item for item in before.sketches if item.sketch_id == saved.sketch_id)
    moved_line = next(
        item for item in current_saved.entities if item.entity_id == saved_line.entity_id
    )
    assert isinstance(moved_line, LineEntity)
    start = editor.canvas.local_to_screen(moved_line.start_mm)
    target = editor.canvas.local_to_screen((moved_line.start_mm[0], moved_line.start_mm[1] + 1))

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟联动夹点候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(editor.canvas, target, delay=30)
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=target)
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert "模拟联动夹点候选失败" in editor.canvas.message
    assert session.snapshot == before and tuple(loaded.document.commands) == history
    editor.canvas.selected_entity_ids = {saved_line.entity_id}
    start = editor.canvas.local_to_screen(moved_line.start_mm)
    target = editor.canvas.local_to_screen((moved_line.start_mm[0], moved_line.start_mm[1] + 1))
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, target, delay=30)
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=target)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    after = session.snapshot
    assert after != before, editor.canvas.message
    assert (
        next(item for item in after.sketches if item.sketch_id == saved.sketch_id) != current_saved
    )
    assert next(item for item in after.sketches if item.sketch_id == draft.sketch_id) != next(
        item for item in before.sketches if item.sketch_id == draft.sketch_id
    )
    assert after.cross_tangencies == (relation,) and after.groups == (group,)
    validate_tangency_component(after.sketches, after.cross_tangencies, draft.sketch_id)
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "collection-saved-cross-grip.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == before.sketches


def test_saved_grip_preview_rejects_changed_collection_checkpoint(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace
    from threading import Event

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
    )
    from mycad.core.sketch import CircleEntity, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved_line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    circle = CircleEntity(uuid4().hex, (0, 4), 2)
    draft_line = LineEntity(uuid4().hex, (-10, 10), (10, 10))
    assert editor.canvas.replace_draft_entities((circle, draft_line))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (circle, draft_line),
        layers=editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (DrawingObjectRef("geometry", saved_line.entity_id, saved.sketch_id),),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(saved.sketch_id, saved_line.entity_id),
        CrossSketchRef(draft.sketch_id, circle.entity_id),
        "line_left",
    )
    original, solved = app.prepare_cross_sketch_tangency_from_state(
        session.snapshot.sketches, session.snapshot.cross_tangencies, relation
    )
    operation = ReplayAppend(
        "drawing.tangency.add",
        12,
        {
            "relation": relation.to_mapping(),
            "revisions": list(app.build_tangency_revisions(original, solved)),
        },
        "local",
    )
    assert editor.canvas.stage_collection_operation(operation), editor.canvas.message
    assert editor.canvas.pending_cross_tangencies == []
    before = session.snapshot
    history = tuple(loaded.document.commands)
    assert editor.canvas.set_tool("选择元素")
    editor.snap_check.setChecked(False)
    editor.canvas.selected_entity_ids = {saved_line.entity_id}
    current_saved = next(item for item in before.sketches if item.sketch_id == saved.sketch_id)
    moved_line = next(
        item for item in current_saved.entities if item.entity_id == saved_line.entity_id
    )
    assert isinstance(moved_line, LineEntity)
    start = editor.canvas.local_to_screen(moved_line.start_mm)
    target = editor.canvas.local_to_screen((moved_line.start_mm[0], moved_line.start_mm[1] + 1))

    started, release_solver = Event(), Event()
    original_solve = app.prepare_cross_sketch_drag_from_state

    def delayed_solve(
        services: app.AppServices,
        sketches: tuple[Sketch, ...],
        relations: tuple[CrossSketchTangency, ...],
        sketch_id: str,
        reference: SketchGeometryReference,
        target_mm: tuple[float, float],
    ) -> tuple[tuple[Sketch, ...], tuple[Sketch, ...], tuple[CrossSketchRef, ...]]:
        started.set()
        if not release_solver.wait(15):
            raise ValueError("模拟求解超时")
        return original_solve(services, sketches, relations, sketch_id, reference, target_mm)

    monkeypatch.setattr(app, "prepare_cross_sketch_drag_from_state", delayed_solve)
    QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(editor.canvas, target, delay=30)
    try:
        qtbot.waitUntil(started.is_set, timeout=15000)
        renamed = replace(group, name="预览期间改名")
        assert editor.canvas.stage_collection_operation(
            ReplayAppend("drawing.group.update", 1, renamed.to_mapping(), "local")
        )
        changed = session.snapshot
    finally:
        release_solver.set()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert not editor.canvas.saved_handle_preview
    assert "暂存内容已变化" in editor.canvas.message
    QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=target)
    assert session.snapshot == changed
    assert session.snapshot.sketches == before.sketches
    assert tuple(loaded.document.commands) == history


@pytest.mark.parametrize("member_in_group", [False, True])
def test_delete_unselectable_group_member_candidate_failure_rolls_back(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, member_in_group: bool
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 4), (10, 4))
    assert editor.canvas.replace_draft_entities((first, second))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (first, second), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        tuple(
            DrawingObjectRef("geometry", item.entity_id, draft.sketch_id)
            for item in ((first, second) if member_in_group else (second,))
        ),
        selectable=False,
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before = session.snapshot
    position = editor.canvas.history_position
    history = tuple(loaded.document.commands)
    editor.canvas.selected_entity_ids = {first.entity_id}

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟删除候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        assert not editor.canvas.delete_selected()
    assert "模拟删除候选失败" in editor.canvas.message
    assert tuple(editor.canvas.entities) == (first, second) and session.snapshot == before
    assert editor.canvas.history_position == position and tuple(loaded.document.commands) == history
    assert editor.canvas.delete_selected(), editor.canvas.message
    after = session.snapshot
    assert after.sketches[-1].entities == (second,)
    assert after.groups[0].members == (group.members[-1],)
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "delete-ungrouped-selection.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups[0].members == (group.members[-1],)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)


def test_ungrouped_dimension_delete_candidate_failure_rolls_back(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    other = LineEntity(uuid4().hex, (0, 4), (10, 4))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 2),
    )
    assert editor.canvas.replace_draft_entities((line, other), new_relations=(dimension,))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (line, other),
        (dimension,),
        editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", other.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before, history = session.snapshot, tuple(loaded.document.commands)
    position = editor.canvas.history_position
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟删除尺寸候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        assert not editor.canvas.delete_selected()
    assert "模拟删除尺寸候选失败" in editor.canvas.message
    assert editor.canvas.constraints == [dimension] and session.snapshot == before
    assert editor.canvas.history_position == position and tuple(loaded.document.commands) == history
    assert editor.canvas.delete_selected(), editor.canvas.message
    after = session.snapshot
    assert after.sketches[-1].constraints == () and after.groups == (group,)
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "delete-dimension.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches[-1].constraints == ()
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].constraints == (dimension,)
    assert services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("remove_geometry", [False, True])
def test_geometric_constraint_delete_candidate_failure_rolls_back(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, remove_geometry: bool
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    other = LineEntity(uuid4().hex, (0, 4), (10, 4))
    dimension = SketchConstraint(
        uuid4().hex,
        "horizontal",
        (SketchGeometryReference(line.entity_id, "geometry"),),
    )
    assert editor.canvas.replace_draft_entities((line, other), new_relations=(dimension,))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (line, other),
        (dimension,),
        editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", other.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before, history = session.snapshot, tuple(loaded.document.commands)
    position = editor.canvas.history_position
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    if remove_geometry:
        editor.canvas.selected_entity_ids = {line.entity_id}

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟删除约束候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        assert not editor.canvas.delete_selected()
    assert "模拟删除约束候选失败" in editor.canvas.message
    assert editor.canvas.constraints == [dimension] and session.snapshot == before
    assert editor.canvas.history_position == position and tuple(loaded.document.commands) == history
    assert editor.canvas.delete_selected(), editor.canvas.message
    after = session.snapshot
    assert after.sketches[-1].constraints == () and after.groups == (group,)
    assert after.sketches[-1].entities == ((other,) if remove_geometry else (line, other))
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "delete-relation.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches[-1].constraints == ()
    assert services.kernel.sketches[-1].entities == ((other,) if remove_geometry else (line, other))
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1].constraints == (dimension,)
    assert services.kernel.drawing_groups == (group,)


def test_draft_constraint_and_group_delete_share_collection_transaction(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    grouped = LineEntity(uuid4().hex, (0, 4), (10, 4))
    relation = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(line.entity_id, "geometry"),)
    )
    assert editor.canvas.replace_draft_entities((line, grouped), new_relations=(relation,))
    draft = Sketch(
        editor.draft_sketch_id,
        editor.current_frame(),
        (line, grouped),
        (relation,),
        editor.layer_table,
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", grouped.entity_id, draft.sketch_id),)
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before, history = session.snapshot, tuple(loaded.document.commands)
    position = editor.canvas.history_position
    editor.canvas.selected_constraint_ids = {relation.constraint_id}
    editor.canvas.selected_entity_ids = {grouped.entity_id}

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟草稿约束和组删除失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        assert not editor.canvas.delete_selected()
    assert "模拟草稿约束和组删除失败" in editor.canvas.message
    assert session.snapshot == before and editor.canvas.history_position == position
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.delete_selected(), editor.canvas.message
    after = session.snapshot
    assert after.sketches[-1].entities == (line,)
    assert after.sketches[-1].constraints == () and after.groups == ()
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "draft-constraint-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches[-1] == draft and services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize(
    ("delete_group", "select_relation"), [(False, True), (True, True), (True, False)]
)
def test_saved_tangent_and_group_delete_share_collection_transaction(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    delete_group: bool,
    select_relation: bool,
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    saved = Sketch(uuid4().hex, editor.current_frame(), (line, circle), (relation,))
    app.commit_new_sketch(services, loaded, saved, session_identity=_session_id(window))
    _invoke(window, "_sync_drawing_layers")
    draft_line = LineEntity(uuid4().hex, (0, 8), (10, 8))
    assert editor.canvas.replace_draft_entities((draft_line,))
    draft = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (draft_line,), layers=editor.layer_table
    )
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=_session_id(window),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, saved.sketch_id),
            DrawingObjectRef("geometry", draft_line.entity_id, draft.sketch_id),
        ),
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    before, history = session.snapshot, tuple(loaded.document.commands)
    position = editor.canvas.history_position
    if select_relation:
        editor.canvas.selected_constraint_ids = {relation.constraint_id}
    if delete_group:
        editor.canvas.selected_entity_ids = {line.entity_id}

    def reject_stage(_operation: ReplayAppend) -> None:
        raise ValidationError("模拟混合删除候选失败")

    with monkeypatch.context() as failure:
        failure.setattr(session, "stage", reject_stage)
        assert not editor.canvas.delete_selected()
    assert "模拟混合删除候选失败" in editor.canvas.message
    assert session.snapshot == before and editor.canvas.history_position == position
    assert tuple(loaded.document.commands) == history
    assert editor.canvas.delete_selected(), editor.canvas.message
    after = session.snapshot
    saved_after = next(item for item in after.sketches if item.sketch_id == saved.sketch_id)
    draft_after = next(item for item in after.sketches if item.sketch_id == draft.sketch_id)
    assert saved_after.constraints == ()
    assert saved_after.entities == ((circle,) if delete_group else (line, circle))
    assert draft_after.entities == (() if delete_group else (draft_line,))
    assert after.groups == (() if delete_group else (group,))
    assert relation.constraint_id not in editor.canvas.selected_constraint_ids
    assert not delete_group or line.entity_id not in editor.canvas.selected_entity_ids
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    if select_relation:
        assert relation.constraint_id in editor.canvas.selected_constraint_ids
    if delete_group:
        assert line.entity_id in editor.canvas.selected_entity_ids
    assert editor.canvas.redo_last_operation() and session.snapshot == after
    assert relation.constraint_id not in editor.canvas.selected_constraint_ids
    session.commit()
    editor.canvas.collection_session = None
    path = tmp_path / "saved-tangent-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.sketches[0] == saved


def test_group_rotation_reports_removed_inferred_relation_from_canvas(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0))
    canvas.add_coordinate_point((10, 0.2))
    assert len(canvas.entities) == len(canvas.constraints) == 1
    relation = canvas.constraints[0]
    assert relation.kind == "horizontal" and relation.source == "inferred"
    line = canvas.entities[0]
    canvas.selected_entity_ids = {line.entity_id}
    editor.drawing_command_bar.input.setText("GROUP")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = canvas.collection_session
    assert session is not None and len(session.snapshot.groups) == 1
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    assert canvas.apply_rotation_angle(90)
    assert session.snapshot.sketches[-1].constraints == ()
    assert "移除 1 条" in editor.status_label.text()
    assert not loaded.document.commands
    assert canvas.undo_last_operation()
    assert session.snapshot.sketches[-1].constraints == (relation,)
    assert canvas.redo_last_operation()
    assert session.snapshot.sketches[-1].constraints == ()


def test_group_rotation_rechecks_inferred_coincidence_from_canvas(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((12, 4), exact_point=True)
    assert len(canvas.entities) == 2
    coincident = next(item for item in canvas.constraints if item.kind == "coincident")
    assert coincident.source == "inferred"
    canvas.selected_entity_ids = {canvas.entities[0].entity_id}
    editor.drawing_command_bar.input.setText("GROUP")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = canvas.collection_session
    assert session is not None and len(session.snapshot.groups) == 1
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    assert canvas.apply_rotation_angle(90)
    assert coincident not in session.snapshot.sketches[-1].constraints
    assert "失效的自动关系" in editor.status_label.text()
    assert not loaded.document.commands
    assert canvas.undo_last_operation()
    assert coincident in session.snapshot.sketches[-1].constraints
    assert canvas.redo_last_operation()
    assert coincident not in session.snapshot.sketches[-1].constraints


def test_group_rectangle_rotation_rebinds_inferred_vertex_from_canvas(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import PolylineEntity, RectangleEntity
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    assert canvas.set_tool("矩形")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((4, 2), exact_point=True)
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((4, 2), exact_point=True)
    canvas.add_coordinate_point((6, 3), exact_point=True)
    assert len(canvas.entities) == 2
    rectangle = canvas.entities[0]
    assert isinstance(rectangle, RectangleEntity)
    relation = next(item for item in canvas.constraints if item.kind == "coincident")
    canvas.selected_entity_ids = {rectangle.entity_id}
    editor.drawing_command_bar.input.setText("GROUP")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = canvas.collection_session
    assert session is not None
    canvas.begin_transform("rotate")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    assert canvas.apply_rotation_angle(45)
    updated = session.snapshot.sketches[-1]
    assert isinstance(updated.entities[0], PolylineEntity)
    assert updated.entities[0].entity_id == rectangle.entity_id
    assert relation not in updated.constraints
    assert "失效的自动关系" in editor.status_label.text()
    assert not loaded.document.commands
    assert canvas.undo_last_operation()
    assert session.snapshot.sketches[-1].entities[0] == rectangle
    assert relation in session.snapshot.sketches[-1].constraints
    assert canvas.redo_last_operation()
    assert session.snapshot.sketches[-1] == updated
