# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Collection-only drafts remain owned across document lifecycle events."""

from collections.abc import Callable
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.persistence import LoadedDocument, save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.document_session import DocumentSession, SessionDocument
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog


def _skip_gl(*_args: object, **_kwargs: object) -> None:
    pass


def _staged_group(window: MainWindow) -> tuple[SessionDocument, SketchEditorDialog]:
    entry = window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(entry.services, entry.loaded, sketch, session_identity=0)
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    editor.canvas.set_source_context_revision(entry.loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    bar = editor.drawing_command_bar
    bar.input.setText("GROUP")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.collection_session is not None
    assert len(editor.canvas.collection_session.snapshot.groups) == 1
    assert not editor.canvas.entities and editor.canvas.mixed_move is None
    return entry, editor


def test_empty_collection_draft_is_saved_with_group(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    entry.path = tmp_path / "collection.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    cast("Callable[[MainWindow], None]", vars(type(window))["_refresh_document_choice"])(window)
    assert entry.has_draft and entry.needs_save
    saver = window.document_saver
    assert saver is not None
    outcome: list[bool] = []
    saver.save_many((entry,), on_complete=outcome.append)
    qtbot.waitUntil(lambda: bool(outcome), timeout=15000)
    assert outcome == [True]
    assert len(entry.services.kernel.drawing_groups) == 1
    reopened_services = app.fork_app_services(entry.services)
    app.open_app_document(reopened_services, entry.path)
    assert len(reopened_services.kernel.drawing_groups) == 1
    assert window.active_sketch_dialog() is not editor


def test_collection_draft_survives_switch_and_can_commit(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.replay_proposal import ReplayAppend

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    source, editor = _staged_group(window)
    session = editor.canvas.collection_session
    assert session is not None
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local")
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local")
    )
    before = session.snapshot
    assert source.services.kernel.drawing_block_instances == ()
    target = window.new_session_document("sketch")
    assert window.loaded_document() is target.loaded
    window.activate_session_document(source.loaded.document.document_id)
    restored = window.active_sketch_dialog()
    assert restored is not None and restored is editor
    assert session.snapshot == before
    assert restored.canvas.undo_last_operation()
    assert restored.canvas.redo_last_operation()
    unit = window.execution_unit
    assert unit is not None
    restored.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not restored, timeout=15000
    )
    assert source.services.kernel.drawing_groups == before.groups
    assert source.services.kernel.drawing_block_definitions == before.block_definitions
    assert source.services.kernel.drawing_block_instances == before.block_instances
    path = tmp_path / "switched.my2d"
    save_document(source.loaded.document, path)
    reopened = app.open_app_document(source.services, path)
    reopened.bus.undo_operation()
    assert source.services.kernel.drawing_block_instances == ()
    assert source.services.kernel.drawing_block_definitions == before.block_definitions
    reopened.bus.undo_operation()
    assert source.services.kernel.drawing_block_definitions == ()
    assert source.services.kernel.drawing_groups == before.groups
    reopened.bus.undo_operation()
    assert source.services.kernel.drawing_groups == ()
    for _ in range(3):
        reopened.bus.redo_operation()
    assert source.services.kernel.drawing_groups == before.groups
    assert source.services.kernel.drawing_block_definitions == before.block_definitions
    assert source.services.kernel.drawing_block_instances == before.block_instances


def test_failed_collection_save_restores_draft_and_retry(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.exceptions import ValidationError
    from mycad.ui import document_save

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    entry.path = tmp_path / "failure.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    original_bytes = entry.path.read_bytes()
    history = entry.loaded.document.commands
    session = editor.canvas.collection_session
    assert session is not None
    expected = session.snapshot
    saver = window.document_saver
    assert saver is not None
    real_save = document_save.save_document

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(document_save, "save_document", fail)
    outcomes: list[bool] = []
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [False] and saver.last_results[-1].status == "failed"
    assert entry.path.read_bytes() == original_bytes
    assert entry.loaded.document.commands == history
    assert window.active_sketch_dialog() is editor
    assert session.snapshot == expected
    with pytest.raises(ValidationError, match="暂存|草稿|写入"):
        entry.loaded.bus.execute(
            "drawing.text.add", DrawingText(uuid4().hex, "blocked", (0, 0)).to_mapping(), "local"
        )
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.redo_last_operation()
    monkeypatch.setattr(document_save, "save_document", real_save)
    outcomes.clear()
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [True]
    reopened = app.fork_app_services(entry.services)
    app.open_app_document(reopened, entry.path)
    assert reopened.kernel.drawing_groups == expected.groups


def test_failed_candidate_restore_remains_dirty_and_save_retries(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.ui import document_save

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    entry.path = tmp_path / "restore-failure.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    original = entry.path.read_bytes()
    history = entry.loaded.document.commands
    session = editor.canvas.collection_session
    assert session is not None
    expected = session.snapshot
    restore = session.restore_after_save_failure
    real_save = document_save.save_document

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated write failure")

    def fail_restore(
        services: app.AppServices,
        loaded: LoadedDocument,
        previous_revision: int,
        revision: int,
        session_identity: int,
    ) -> None:
        def fail_rebuild(*_args: object, **_kwargs: object) -> None:
            raise ValidationError("simulated candidate failure")

        with monkeypatch.context() as injection:
            injection.setattr(session, "_rebuild", fail_rebuild)
            restore(services, loaded, previous_revision, revision, session_identity)

    monkeypatch.setattr(document_save, "save_document", fail_save)
    monkeypatch.setattr(session, "restore_after_save_failure", fail_restore)
    saver = window.document_saver
    assert saver is not None
    outcomes: list[bool] = []
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [False]
    assert "再次保存" in saver.last_results[-1].error
    assert entry.path.read_bytes() == original
    assert entry.loaded.document.commands == history
    assert entry.draft is editor and entry.has_draft and entry.needs_save, saver.last_results
    monkeypatch.setattr(session, "restore_after_save_failure", restore)
    monkeypatch.setattr(document_save, "save_document", real_save)
    outcomes.clear()
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [True]
    reopened = app.fork_app_services(entry.services)
    app.open_app_document(reopened, entry.path)
    assert reopened.kernel.drawing_groups == expected.groups


@pytest.mark.parametrize("with_geometry", [False, True])
def test_save_rejects_unfinished_datum_without_losing_draft(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_geometry: bool
) -> None:
    from PySide6.QtWidgets import QInputDialog

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    entry.path = tmp_path / "pending-datum.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    original = entry.path.read_bytes()
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    if with_geometry:
        assert editor.canvas.replace_draft_entities((line,))
    tolerance = editor.canvas.geometric_tolerance_tools
    assert tolerance is not None

    def datum_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", datum_name)
    tolerance.begin_datum()
    assert tolerance.pending
    before = entry.loaded.document.commands
    saver = window.document_saver
    assert saver is not None
    outcomes: list[bool] = []
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [False]
    assert tolerance.pending and window.active_sketch_dialog() is editor
    assert entry.has_draft and entry.path.read_bytes() == original
    assert entry.loaded.document.commands == before
    if with_geometry:
        assert tuple(editor.canvas.entities) == (line,)
    tolerance.cancel()
    outcomes.clear()
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [True]
    if with_geometry:
        assert entry.services.kernel.sketches[0].entities == (line,)


@pytest.mark.parametrize("with_group", [False, True])
def test_finish_draft_rejects_unfinished_datum(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, with_group: bool
) -> None:
    from PySide6.QtWidgets import QInputDialog

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    if with_group:
        entry, editor = _staged_group(window)
    else:
        entry = window.new_session_document("sketch")
        editor = window.active_sketch_dialog()
    unit = window.execution_unit
    assert editor is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    tolerance = editor.canvas.geometric_tolerance_tools
    assert tolerance is not None

    def datum_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", datum_name)
    tolerance.begin_datum()
    assert tolerance.pending
    before = entry.loaded.document.commands
    collection = editor.canvas.collection_session
    checkpoint = collection.checkpoint() if collection is not None else None
    editor.finish_sketch()
    assert window.active_sketch_dialog() is editor
    assert tolerance.pending and not unit.is_busy
    assert "基准" in editor.status_label.text() or "公差" in editor.status_label.text()
    assert tuple(editor.canvas.entities) == (line,) and entry.loaded.document.commands == before
    if collection is not None:
        assert collection.checkpoint() == checkpoint
    tolerance.cancel()
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=15000
    )
    assert any(sketch.entities == (line,) for sketch in entry.services.kernel.sketches)
    if with_group:
        assert len(entry.services.kernel.drawing_groups) == 1


def test_finish_preserves_pending_frame_then_commits_it_with_group(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from mycad.ui.geometric_tolerance_dialog import GeometricToleranceDialog

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    unit = window.execution_unit
    assert unit is not None
    line = LineEntity(uuid4().hex, (0, 10), (10, 10))
    assert editor.canvas.replace_draft_entities((line,))
    collection = editor.canvas.collection_session
    tools = editor.canvas.geometric_tolerance_tools
    assert collection is not None and tools is not None

    def accept_frame() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.rows[0].characteristic.setCurrentIndex(
            dialog.rows[0].characteristic.findData("position")
        )
        dialog.rows[0].value.setValue(0.05)
        dialog.accept()

    QTimer.singleShot(20, accept_frame)
    tools.begin_frame()
    assert tools.pending
    before, checkpoint = entry.loaded.document.commands, collection.checkpoint()
    editor.finish_sketch()
    assert window.active_sketch_dialog() is editor and tools.pending
    assert entry.loaded.document.commands == before and collection.checkpoint() == checkpoint
    point = editor.canvas.local_to_screen((20, 20))
    QTest.mouseClick(editor.canvas, Qt.MouseButton.LeftButton, pos=point)
    assert not tools.pending and len(collection.snapshot.frames) == 1
    assert entry.services.kernel.drawing_tolerance_frames == ()
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=15000
    )
    assert len(entry.services.kernel.drawing_tolerance_frames) == 1
    assert len(entry.services.kernel.drawing_groups) == 1
    path = tmp_path / "group-frame.my2d"
    save_document(entry.loaded.document, path)
    reopened = app.open_app_document(entry.services, path)
    assert len(entry.services.kernel.drawing_tolerance_frames) == 1
    reopened.bus.undo_operation()
    assert entry.services.kernel.drawing_tolerance_frames == ()
    assert len(entry.services.kernel.drawing_groups) == 1


def test_failed_checkpoint_restore_retries_and_saves_in_one_action(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.exceptions import ValidationError
    from mycad.ui import document_save

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    entry.path = tmp_path / "checkpoint-failure.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    original = entry.path.read_bytes()
    session = editor.canvas.collection_session
    assert session is not None
    expected = session.snapshot
    real_restore = entry.loaded.bus.restore_save_checkpoint
    real_save = document_save.save_document
    attempts = 0

    def fail_once(
        token: str, *, expected_revision: int, drawing_write_guard: str | None = None
    ) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValidationError("simulated checkpoint failure")
        real_restore(
            token, expected_revision=expected_revision, drawing_write_guard=drawing_write_guard
        )

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(entry.loaded.bus, "restore_save_checkpoint", fail_once)
    monkeypatch.setattr(document_save, "save_document", fail_save)
    saver = window.document_saver
    assert saver is not None
    outcomes: list[bool] = []
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [False] and attempts == 1
    assert entry.path.read_bytes() == original
    assert entry.draft is editor and entry.has_draft and entry.needs_save
    with pytest.raises(ValidationError, match="暂存|草稿|写入"):
        entry.loaded.bus.execute(
            "drawing.text.add", DrawingText(uuid4().hex, "blocked", (0, 0)).to_mapping(), "local"
        )
    monkeypatch.setattr(document_save, "save_document", real_save)
    target = window.new_session_document("sketch")
    assert window.loaded_document() is target.loaded
    window.activate_session_document(entry.loaded.document.document_id)
    assert window.loaded_document() is entry.loaded
    assert window.act_save.isEnabled()
    window.act_save.trigger()
    qtbot.waitUntil(lambda: not saver.running, timeout=15000)
    assert saver.last_results[-1].status == "saved", saver.last_results
    assert attempts == 2
    reopened = app.fork_app_services(entry.services)
    app.open_app_document(reopened, entry.path)
    assert reopened.kernel.drawing_groups == expected.groups


def test_discard_after_failed_checkpoint_restore_releases_write_guard(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.exceptions import ValidationError
    from mycad.ui import document_save

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, _editor = _staged_group(window)
    entry.path = tmp_path / "discard.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()

    def fail_restore(*_args: object, **_kwargs: object) -> None:
        raise ValidationError("simulated checkpoint failure")

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(entry.loaded.bus, "restore_save_checkpoint", fail_restore)
    monkeypatch.setattr(document_save, "save_document", fail_save)
    saver = window.document_saver
    assert saver is not None
    outcome: list[bool] = []
    saver.save_many((entry,), on_complete=outcome.append)
    qtbot.waitUntil(lambda: bool(outcome), timeout=15000)
    assert outcome == [False] and entry.has_draft

    def discard(_entries: tuple[SessionDocument, ...]) -> dict[str, str]:
        return {entry.loaded.document.document_id: "discard"}

    monkeypatch.setattr(window, "_ask_session_close_dialog", discard)
    window.close_active_document()
    assert window.document_session is not None
    assert window.document_session.find(entry.loaded.document.document_id) is None
    entry.loaded.bus.execute(
        "drawing.text.add", DrawingText(uuid4().hex, "unblocked", (0, 0)).to_mapping(), "local"
    )


def test_save_other_document_recovers_pending_collection_first(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.exceptions import ValidationError
    from mycad.ui import document_save

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    source, editor = _staged_group(window)
    source.path = tmp_path / "source.my2d"
    save_document(source.loaded.document, source.path)
    source.loaded.document.mark_clean()
    source_session = editor.canvas.collection_session
    assert source_session is not None
    expected = source_session.snapshot
    real_restore = source.loaded.bus.restore_save_checkpoint
    real_save = document_save.save_document
    attempts = 0

    def fail_once(
        token: str, *, expected_revision: int, drawing_write_guard: str | None = None
    ) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValidationError("simulated checkpoint failure")
        real_restore(
            token, expected_revision=expected_revision, drawing_write_guard=drawing_write_guard
        )

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(source.loaded.bus, "restore_save_checkpoint", fail_once)
    monkeypatch.setattr(document_save, "save_document", fail_save)
    saver = window.document_saver
    assert saver is not None
    outcomes: list[bool] = []
    saver.save_many((source,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [False] and source.has_draft
    monkeypatch.setattr(document_save, "save_document", real_save)
    target = window.new_session_document("sketch")
    target.path = tmp_path / "target.my2d"
    target_editor = window.active_sketch_dialog()
    assert target_editor is not None and target_editor is not editor
    target_line = LineEntity(uuid4().hex, (1, 1), (4, 1))
    assert target_editor.canvas.replace_draft_entities((target_line,))
    target_editor.canvas.selected_entity_ids = {target_line.entity_id}
    target_editor.drawing_command_bar.input.setText("GROUP")
    QTest.keyClick(target_editor.drawing_command_bar.input, Qt.Key.Key_Return)
    target_session = target_editor.canvas.collection_session
    assert target_session is not None and len(target_session.snapshot.groups) == 1
    assert source.has_draft and source.loaded.document.commands != ()
    with pytest.raises(ValidationError, match="暂存|草稿|写入"):
        source.loaded.bus.execute(
            "drawing.text.add", DrawingText(uuid4().hex, "blocked", (0, 0)).to_mapping(), "local"
        )
    outcomes.clear()
    saver.save_many((target,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [True], saver.last_results
    assert attempts == 2 and source.has_draft
    assert target.path.exists()
    assert target.services.kernel.sketches[0].entities == (target_line,)
    assert len(target.services.kernel.drawing_groups) == 1
    assert window.active_sketch_dialog() is not None
    window.activate_session_document(source.loaded.document.document_id)
    assert window.active_sketch_dialog() is editor
    assert source_session.snapshot == expected
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.redo_last_operation()
    outcomes.clear()
    saver.save_many((source,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [True]
    reopened = app.fork_app_services(source.services)
    app.open_app_document(reopened, source.path)
    assert reopened.kernel.drawing_groups == expected.groups
    target_reopened = app.fork_app_services(target.services)
    reopened_target = app.open_app_document(target_reopened, target.path)
    assert len(target_reopened.kernel.drawing_groups) == 1
    assert target_reopened.kernel.sketches[0].entities == (target_line,)
    reopened_target.bus.undo_operation()
    assert target_reopened.kernel.drawing_groups == ()
    reopened_target.bus.redo_operation()
    assert len(target_reopened.kernel.drawing_groups) == 1


def test_discard_after_canvas_rebind_failure_releases_write_guard(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.exceptions import ValidationError
    from mycad.ui import document_save

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    entry.path = tmp_path / "canvas-discard.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()

    def fail_rebind(_previous_revision: int, _revision: int) -> None:
        raise ValidationError("simulated canvas rebind failure")

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(editor.canvas, "rebind_restored_source", fail_rebind)
    monkeypatch.setattr(document_save, "save_document", fail_save)
    saver = window.document_saver
    assert saver is not None
    outcomes: list[bool] = []
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [False] and entry.has_draft

    def discard(_entries: tuple[SessionDocument, ...]) -> dict[str, str]:
        return {entry.loaded.document.document_id: "discard"}

    monkeypatch.setattr(window, "_ask_session_close_dialog", discard)
    window.close_active_document()
    assert window.document_session is not None
    assert window.document_session.find(entry.loaded.document.document_id) is None
    entry.loaded.bus.execute(
        "drawing.text.add", DrawingText(uuid4().hex, "unblocked", (0, 0)).to_mapping(), "local"
    )


def test_canvas_rebind_failure_retry_keeps_recovered_candidate(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.ui import document_save

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    entry.path = tmp_path / "canvas-retry.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    session = editor.canvas.collection_session
    assert session is not None
    expected = session.snapshot
    real_rebind = editor.canvas.rebind_restored_source
    real_save = document_save.save_document
    attempts = 0

    def fail_once(previous_revision: int, revision: int) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValidationError("simulated canvas rebind failure")
        real_rebind(previous_revision, revision)

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(editor.canvas, "rebind_restored_source", fail_once)
    monkeypatch.setattr(document_save, "save_document", fail_save)
    saver = window.document_saver
    assert saver is not None
    outcomes: list[bool] = []
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [False] and entry.has_draft
    assert session.snapshot == expected
    monkeypatch.setattr(document_save, "save_document", real_save)
    outcomes.clear()
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [True], saver.last_results
    assert attempts == 2
    reopened = app.fork_app_services(entry.services)
    app.open_app_document(reopened, entry.path)
    assert reopened.kernel.drawing_groups == expected.groups


@pytest.mark.parametrize("kind", ("text", "datum"))
def test_window_close_keeps_unfinished_annotation_draft(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    entry.path = tmp_path / f"pending-{kind}.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    if kind == "text":
        tools = editor.canvas.text_tools
        assert tools is not None and tools.begin("text")
        tools.place((0, 0))
        tools.editor.setPlainText("未完成的文字")
    else:
        from PySide6.QtWidgets import QInputDialog

        tolerance = editor.canvas.geometric_tolerance_tools
        assert tolerance is not None

        def datum_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
            return "A", True

        monkeypatch.setattr(QInputDialog, "getText", datum_name)
        tolerance.begin_datum()
        assert tolerance.pending
    cast("Callable[[MainWindow], None]", vars(type(window))["_refresh_document_choice"])(window)
    requests: list[tuple[SessionDocument, ...]] = []

    def cancel_close(entries: tuple[SessionDocument, ...]) -> None:
        requests.append(entries)
        return

    monkeypatch.setattr(window, "_ask_session_close_dialog", cancel_close)
    window.close()
    assert window.isVisible()
    assert requests == [(entry,)]
    assert entry.has_draft and entry.needs_save
    if kind == "text":
        assert editor.canvas.text_tools is not None
        assert editor.canvas.text_tools.editor.toPlainText() == "未完成的文字"
        editor.canvas.text_tools.cancel()
    else:
        assert editor.canvas.geometric_tolerance_tools is not None
        editor.canvas.geometric_tolerance_tools.cancel()
    assert not entry.has_draft and not entry.needs_save


def test_failed_collection_commit_during_save_keeps_draft_editable(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    entry.path = tmp_path / "commit-failure.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    before = entry.loaded.document.commands
    file_bytes = entry.path.read_bytes()
    session = editor.canvas.collection_session
    assert session is not None
    expected = session.snapshot
    real_commit = session.commit

    def fail_commit() -> None:
        raise ValidationError("simulated candidate commit failure")

    monkeypatch.setattr(session, "commit", fail_commit)
    saver = window.document_saver
    assert saver is not None
    outcomes: list[bool] = []
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [False]
    assert entry.loaded.document.commands == before
    assert entry.path.read_bytes() == file_bytes
    assert window.active_sketch_dialog() is editor and editor.isEnabled()
    assert session.snapshot == expected
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.redo_last_operation()
    monkeypatch.setattr(session, "commit", real_commit)
    outcomes.clear()
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [True], saver.last_results
    reopened = app.fork_app_services(entry.services)
    app.open_app_document(reopened, entry.path)
    assert reopened.kernel.drawing_groups == expected.groups


def test_late_candidate_failure_rebinds_open_session_after_revision_change(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    entry.path = tmp_path / "late-commit-failure.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    initial_revision = entry.loaded.document.revision
    before = entry.loaded.document.commands
    original_bytes = entry.path.read_bytes()
    session = editor.canvas.collection_session
    assert session is not None
    expected = session.snapshot
    real_discard = entry.loaded.bus.discard_replay_candidate
    failed = False

    def fail_once(candidate_id: str) -> None:
        nonlocal failed
        if not failed and entry.loaded.document.revision > initial_revision:
            failed = True
            raise ValidationError("simulated late candidate failure")
        real_discard(candidate_id)

    monkeypatch.setattr(entry.loaded.bus, "discard_replay_candidate", fail_once)
    saver = window.document_saver
    assert saver is not None
    outcomes: list[bool] = []
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [False] and failed
    assert entry.loaded.document.revision > initial_revision
    assert entry.loaded.document.commands == before
    assert entry.path.read_bytes() == original_bytes
    assert entry.services.kernel.drawing_groups == ()
    assert window.active_sketch_dialog() is editor and editor.isEnabled()
    assert session.snapshot == expected
    with pytest.raises(ValidationError, match="暂存|草稿|写入"):
        entry.loaded.bus.execute(
            "drawing.text.add", DrawingText(uuid4().hex, "blocked", (0, 0)).to_mapping(), "local"
        )
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.redo_last_operation()
    outcomes.clear()
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [True], saver.last_results
    reopened = app.fork_app_services(entry.services)
    loaded = app.open_app_document(reopened, entry.path)
    assert reopened.kernel.drawing_groups == expected.groups
    loaded.bus.undo_operation()
    assert reopened.kernel.drawing_groups == ()
    loaded.bus.redo_operation()
    assert reopened.kernel.drawing_groups == expected.groups


def test_failed_save_preserves_group_block_redo_branch(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui import document_save

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    session = editor.canvas.collection_session
    assert session is not None
    definition = BlockDefinition(
        uuid4().hex, "Redo block", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local")
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local")
    )
    full = session.snapshot
    assert editor.canvas.undo_last_operation()
    without_instance = session.snapshot
    assert without_instance.block_definitions == (definition,)
    assert without_instance.block_instances == ()
    entry.path = tmp_path / "redo-failure.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    original_bytes = entry.path.read_bytes()
    original_history = entry.loaded.document.commands
    real_save = document_save.save_document

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(document_save, "save_document", fail_save)
    saver = window.document_saver
    assert saver is not None
    outcomes: list[bool] = []
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [False]
    assert entry.path.read_bytes() == original_bytes
    assert entry.loaded.document.commands == original_history
    assert session.snapshot == without_instance
    assert editor.canvas.redo_last_operation()
    assert session.snapshot == full
    assert editor.canvas.undo_last_operation()
    assert session.snapshot == without_instance
    assert editor.canvas.redo_last_operation()
    monkeypatch.setattr(document_save, "save_document", real_save)
    outcomes.clear()
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [True], saver.last_results
    reopened = app.fork_app_services(entry.services)
    loaded = app.open_app_document(reopened, entry.path)
    assert reopened.kernel.drawing_block_instances == (instance,)
    loaded.bus.undo_operation()
    assert reopened.kernel.drawing_block_instances == ()
    loaded.bus.redo_operation()
    assert reopened.kernel.drawing_block_instances == (instance,)


def test_failed_collection_save_as_restores_source_then_retries(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui import document_save

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    source_path, target_path = tmp_path / "source.my2d", tmp_path / "copy.my2d"
    entry.path = source_path
    save_document(entry.loaded.document, source_path)
    entry.loaded.document.mark_clean()
    original_bytes = source_path.read_bytes()
    original_loaded = entry.loaded
    original_history = original_loaded.document.commands
    session = editor.canvas.collection_session
    assert session is not None
    definition = BlockDefinition(
        uuid4().hex, "Save As", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local")
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local")
    )
    expected = session.snapshot
    saver = window.document_saver
    assert saver is not None

    def choose_path(_entry: SessionDocument) -> Path:
        return target_path

    monkeypatch.setattr(saver, "choose_path", choose_path)
    real_save = document_save.save_document

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(document_save, "save_document", fail_save)
    outcomes: list[bool] = []
    saver.save_many((entry,), save_as=True, on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [False], saver.last_results
    assert entry.loaded is original_loaded and entry.path == source_path
    assert source_path.read_bytes() == original_bytes and not target_path.exists()
    assert entry.loaded.document.commands == original_history
    assert window.active_sketch_dialog() is editor and editor.isEnabled()
    assert session.snapshot == expected
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.redo_last_operation()
    monkeypatch.setattr(document_save, "save_document", real_save)
    outcomes.clear()
    saver.save_many((entry,), save_as=True, on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [True], saver.last_results
    assert entry.loaded is not original_loaded and entry.path == target_path
    assert source_path.read_bytes() == original_bytes
    reopened = app.fork_app_services(entry.services)
    loaded = app.open_app_document(reopened, target_path)
    assert reopened.kernel.drawing_groups == expected.groups
    assert reopened.kernel.drawing_block_instances == (instance,)
    loaded.bus.undo_operation()
    assert reopened.kernel.drawing_block_instances == ()
    loaded.bus.redo_operation()
    assert reopened.kernel.drawing_block_instances == (instance,)


def test_unexpected_candidate_restore_error_can_retry_save(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_text import DrawingText
    from mycad.core.exceptions import ValidationError
    from mycad.ui import document_save

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    entry.path = tmp_path / "unexpected-restore.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    session = editor.canvas.collection_session
    assert session is not None
    expected = session.snapshot
    original_restore = session.restore_after_save_failure
    original_save = document_save.save_document

    def fail_restore(
        services: app.AppServices,
        loaded: LoadedDocument,
        previous_revision: int,
        revision: int,
        session_identity: int,
    ) -> None:
        def fail_rebuild(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated backend recovery error")

        with monkeypatch.context() as injection:
            injection.setattr(session, "_rebuild", fail_rebuild)
            original_restore(services, loaded, previous_revision, revision, session_identity)

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(session, "restore_after_save_failure", fail_restore)
    monkeypatch.setattr(document_save, "save_document", fail_save)
    saver = window.document_saver
    assert saver is not None
    outcomes: list[bool] = []
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [False] and not saver.running
    assert "simulated backend recovery error" in saver.last_results[-1].error
    assert entry.draft is editor and entry.has_draft and entry.needs_save
    with pytest.raises(ValidationError, match="暂存|草稿|写入"):
        entry.loaded.bus.execute(
            "drawing.text.add", DrawingText(uuid4().hex, "blocked", (0, 0)).to_mapping(), "local"
        )
    monkeypatch.setattr(session, "restore_after_save_failure", original_restore)
    monkeypatch.setattr(document_save, "save_document", original_save)
    outcomes.clear()
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [True], saver.last_results
    reopened = app.fork_app_services(entry.services)
    app.open_app_document(reopened, entry.path)
    assert reopened.kernel.drawing_groups == expected.groups


def test_late_finish_failure_keeps_collection_editable_and_retryable(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    session = editor.canvas.collection_session
    unit = window.execution_unit
    assert session is not None and unit is not None
    expected = session.snapshot
    before = entry.loaded.document.commands
    source_revision = entry.loaded.document.revision
    record = cast(
        "Callable[[object, object], None]",
        vars(type(entry.loaded.bus))["_record_appended_operations"],
    )
    failed = False

    def fail_once(state: object) -> None:
        nonlocal failed
        record(entry.loaded.bus, state)
        if not failed:
            failed = True
            raise RuntimeError("simulated late finish failure")

    monkeypatch.setattr(entry.loaded.bus, "_record_appended_operations", fail_once)
    editor.finish_sketch()
    qtbot.waitUntil(lambda: failed and not unit.is_busy, timeout=15000)
    assert (
        entry.loaded.document.commands == before
        and entry.loaded.document.revision > source_revision
    )
    assert entry.services.kernel.drawing_groups == ()
    assert window.active_sketch_dialog() is editor and editor.isEnabled()
    assert session.snapshot == expected
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.redo_last_operation()
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=15000
    )
    assert entry.services.kernel.drawing_groups == expected.groups
    entry.loaded.bus.undo_operation()
    assert entry.services.kernel.drawing_groups == ()


def test_finish_retry_recovers_after_temporary_candidate_rebuild_failure(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.replay_proposal import ReplayAppend

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    session = editor.canvas.collection_session
    unit = window.execution_unit
    assert session is not None and unit is not None
    expected = session.snapshot
    before = entry.loaded.document.commands
    revision = entry.loaded.document.revision
    record = cast(
        "Callable[[object, object], None]",
        vars(type(entry.loaded.bus))["_record_appended_operations"],
    )
    rebuild = cast(
        "Callable[[object, tuple[ReplayAppend, ...]], None]", vars(type(session))["_rebuild"]
    )
    commit_failed = False
    rebuild_failures = 0

    def fail_commit_once(state: object) -> None:
        nonlocal commit_failed
        record(entry.loaded.bus, state)
        if not commit_failed:
            commit_failed = True
            raise RuntimeError("simulated late finish failure")

    def fail_rebuild_twice(steps: tuple[ReplayAppend, ...]) -> None:
        nonlocal rebuild_failures
        if entry.loaded.document.revision > revision and rebuild_failures < 2:
            rebuild_failures += 1
            raise RuntimeError("simulated candidate rebuild failure")
        rebuild(session, steps)

    monkeypatch.setattr(entry.loaded.bus, "_record_appended_operations", fail_commit_once)
    monkeypatch.setattr(session, "_rebuild", fail_rebuild_twice)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: commit_failed and rebuild_failures == 1 and not unit.is_busy, timeout=15000
    )
    assert entry.loaded.document.commands == before and entry.services.kernel.drawing_groups == ()
    assert window.active_sketch_dialog() is editor and editor.isEnabled()
    assert "暂存恢复失败" in editor.status_label.text()
    editor.finish_sketch()
    assert rebuild_failures == 2 and "暂存恢复失败" in editor.status_label.text()
    assert entry.loaded.document.commands == before and window.active_sketch_dialog() is editor
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=15000
    )
    assert entry.services.kernel.drawing_groups == expected.groups
    entry.loaded.bus.undo_operation()
    assert entry.services.kernel.drawing_groups == ()


def test_finish_retry_rebinds_canvas_after_temporary_recovery_error(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    session = editor.canvas.collection_session
    unit = window.execution_unit
    assert session is not None and unit is not None
    expected = session.snapshot
    before = entry.loaded.document.commands
    record = cast(
        "Callable[[object, object], None]",
        vars(type(entry.loaded.bus))["_record_appended_operations"],
    )
    rebind = editor.canvas.rebind_restored_source
    commit_failed = False
    rebind_attempts = 0

    def fail_commit_once(state: object) -> None:
        nonlocal commit_failed
        record(entry.loaded.bus, state)
        if not commit_failed:
            commit_failed = True
            raise RuntimeError("simulated late finish failure")

    def fail_rebind_once(previous: int, revision: int) -> None:
        nonlocal rebind_attempts
        rebind_attempts += 1
        if rebind_attempts == 1:
            raise RuntimeError("simulated canvas recovery failure")
        rebind(previous, revision)

    monkeypatch.setattr(entry.loaded.bus, "_record_appended_operations", fail_commit_once)
    monkeypatch.setattr(editor.canvas, "rebind_restored_source", fail_rebind_once)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: commit_failed and rebind_attempts == 1 and not unit.is_busy, timeout=15000
    )
    assert entry.loaded.document.commands == before and entry.services.kernel.drawing_groups == ()
    assert "暂存恢复失败" in editor.status_label.text()
    from mycad.core.exceptions import ValidationError

    with pytest.raises(ValidationError, match="画布尚未恢复"):
        _ = session.snapshot
    assert editor.canvas.can_undo and not editor.canvas.undo_last_operation()
    assert "画布尚未恢复" in editor.canvas.message
    other = window.new_session_document("sketch")
    assert window.loaded_document() is other.loaded
    window.activate_session_document(entry.loaded.document.document_id)
    assert window.active_sketch_dialog() is editor
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=15000
    )
    assert rebind_attempts == 2
    assert entry.services.kernel.drawing_groups == expected.groups
    entry.loaded.bus.undo_operation()
    assert entry.services.kernel.drawing_groups == ()


@pytest.mark.parametrize("failure", ("candidate", "canvas"))
def test_cancel_after_failed_finish_recovery_releases_source_guard(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_text import DrawingText
    from mycad.core.replay_proposal import ReplayAppend

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    session = editor.canvas.collection_session
    unit = window.execution_unit
    assert session is not None and unit is not None
    definition = BlockDefinition(
        uuid4().hex, "Discard", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 0))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local")
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local")
    )
    before = entry.loaded.document.commands
    original_sketches = entry.services.kernel.sketches
    revision = entry.loaded.document.revision
    record = cast(
        "Callable[[object, object], None]",
        vars(type(entry.loaded.bus))["_record_appended_operations"],
    )
    rebuild = cast(
        "Callable[[object, tuple[ReplayAppend, ...]], None]", vars(type(session))["_rebuild"]
    )
    commit_failed = False
    recovery_failed = False

    def fail_commit_once(state: object) -> None:
        nonlocal commit_failed
        record(entry.loaded.bus, state)
        if not commit_failed:
            commit_failed = True
            raise RuntimeError("simulated late finish failure")

    def fail_rebuild(steps: tuple[ReplayAppend, ...]) -> None:
        nonlocal recovery_failed
        if entry.loaded.document.revision > revision:
            recovery_failed = True
            raise RuntimeError("simulated candidate recovery failure")
        rebuild(session, steps)

    def fail_canvas(_previous: int, _revision: int) -> None:
        nonlocal recovery_failed
        recovery_failed = True
        raise RuntimeError("simulated canvas recovery failure")

    monkeypatch.setattr(entry.loaded.bus, "_record_appended_operations", fail_commit_once)
    if failure == "candidate":
        monkeypatch.setattr(session, "_rebuild", fail_rebuild)
    else:
        monkeypatch.setattr(editor.canvas, "rebind_restored_source", fail_canvas)
    editor.finish_sketch()
    qtbot.waitUntil(lambda: commit_failed and recovery_failed and not unit.is_busy, timeout=15000)
    assert "暂存恢复失败" in editor.status_label.text()
    editor.cancel_button.click()
    assert entry.loaded.document.commands == before
    assert entry.services.kernel.sketches == original_sketches
    assert entry.services.kernel.drawing_groups == ()
    assert entry.services.kernel.drawing_block_definitions == ()
    assert entry.services.kernel.drawing_block_instances == ()
    text = DrawingText(uuid4().hex, "after cancel", (0, 0))
    entry.loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    assert entry.services.kernel.drawing_texts == (text,)


@pytest.mark.parametrize("failure", ("candidate", "canvas"))
def test_save_retry_does_not_trap_failed_finish_recovery(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from mycad.core.replay_proposal import ReplayAppend

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry, editor = _staged_group(window)
    entry.path = tmp_path / f"finish-save-{failure}.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    original_bytes = entry.path.read_bytes()
    before = entry.loaded.document.commands
    revision = entry.loaded.document.revision
    session = editor.canvas.collection_session
    unit = window.execution_unit
    assert session is not None and unit is not None
    expected = session.snapshot
    record = cast(
        "Callable[[object, object], None]",
        vars(type(entry.loaded.bus))["_record_appended_operations"],
    )
    rebuild = cast(
        "Callable[[object, tuple[ReplayAppend, ...]], None]", vars(type(session))["_rebuild"]
    )
    rebind = editor.canvas.rebind_restored_source
    commit_failed = False
    recovery_failures = 0

    def fail_commit_once(state: object) -> None:
        nonlocal commit_failed
        record(entry.loaded.bus, state)
        if not commit_failed:
            commit_failed = True
            raise RuntimeError("simulated late finish failure")

    def fail_rebuild(steps: tuple[ReplayAppend, ...]) -> None:
        nonlocal recovery_failures
        if entry.loaded.document.revision > revision and recovery_failures < 2:
            recovery_failures += 1
            raise RuntimeError("simulated recovery failure")
        rebuild(session, steps)

    def fail_canvas(previous: int, current: int) -> None:
        nonlocal recovery_failures
        if recovery_failures < 2:
            recovery_failures += 1
            raise RuntimeError("simulated recovery failure")
        rebind(previous, current)

    monkeypatch.setattr(entry.loaded.bus, "_record_appended_operations", fail_commit_once)

    def ignore_error(_message: str) -> None:
        pass

    monkeypatch.setattr(window, "_show_error", ignore_error)
    if failure == "candidate":
        monkeypatch.setattr(session, "_rebuild", fail_rebuild)
    else:
        monkeypatch.setattr(editor.canvas, "rebind_restored_source", fail_canvas)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: commit_failed and recovery_failures == 1 and not unit.is_busy, timeout=15000
    )
    saver = window.document_saver
    assert saver is not None
    outcomes: list[bool] = []
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [False] and recovery_failures == 2
    assert window.active_sketch_dialog() is editor and editor.isEnabled()
    assert entry.path.read_bytes() == original_bytes and entry.loaded.document.commands == before
    outcomes.clear()
    saver.save_many((entry,), on_complete=outcomes.append)
    qtbot.waitUntil(lambda: bool(outcomes), timeout=15000)
    assert outcomes == [True], saver.last_results
    reopened = app.fork_app_services(entry.services)
    opened = app.open_app_document(reopened, entry.path)
    assert reopened.kernel.drawing_groups == expected.groups
    opened.bus.undo_operation()
    assert reopened.kernel.drawing_groups == ()
    opened.bus.redo_operation()
    assert reopened.kernel.drawing_groups == expected.groups
