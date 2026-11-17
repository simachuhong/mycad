# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Closing another document must preserve independent work on cancellation."""

from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QTabBar, QWidget
from pytestqt.qtbot import QtBot

from mycad.app import build_app
from mycad.ui.document_session import DocumentSession, SessionDocument
from mycad.ui.main_window import MainWindow


def _close_tab(window: MainWindow, index: int) -> None:
    bar = window.document_tab_bar
    button = cast("QWidget | None", bar.tabButton(index, QTabBar.ButtonPosition.RightSide))
    if button is None:
        button = bar.tabButton(index, QTabBar.ButtonPosition.LeftSide)
    assert button is not None
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)


def _add_circle(window: MainWindow) -> None:
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.canvas.set_tool("圆")
    editor.canvas.add_coordinate_point((0, 0))
    editor.canvas.add_coordinate_point((5, 0))


def test_cancel_closing_inactive_part_preserves_both_histories(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    part = window.new_session_document("part")
    part.path = tmp_path / "part.my3d"
    for radius in (4, 5):
        part.loaded.bus.execute("feature.cylinder", {"radius": radius, "height": 2}, "local")
    second_identity = part.loaded.document.commands[-1].instance_id
    part.loaded.bus.undo()
    part_commands = part.loaded.document.commands
    sketch = window.new_session_document("sketch")
    _add_circle(window)
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.can_undo
    draft = tuple(editor.canvas.entities)

    def cancel(_entries: tuple[SessionDocument, ...]) -> None:
        return None

    monkeypatch.setattr(window, "_ask_session_close_dialog", cancel)
    _close_tab(window, 0)
    assert session.documents == (part, sketch)
    assert part.path == tmp_path / "part.my3d" and part.needs_save
    assert part.loaded.document.commands == part_commands
    window.activate_session_document(sketch.loaded.document.document_id)
    assert window.active_sketch_dialog() is editor
    assert tuple(editor.canvas.entities) == draft and sketch.needs_save
    window.request_undo()
    assert not editor.canvas.entities and editor.canvas.can_redo
    window.request_redo()
    assert tuple(editor.canvas.entities) == draft
    part.loaded.bus.redo()
    assert part.loaded.document.commands[-1].instance_id == second_identity


@pytest.mark.parametrize("outcome", ["cancel", "error"])
def test_unsuccessful_save_preserves_draft_redo(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    from mycad.ui import document_save

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    sketch = window.new_session_document("sketch")
    _add_circle(window)
    _add_circle(window)
    editor = window.active_sketch_dialog()
    assert editor is not None
    both = tuple(editor.canvas.entities)
    assert editor.canvas.undo_last_operation() and editor.canvas.can_redo
    window.new_session_document("part")

    def save(_entries: tuple[SessionDocument, ...]) -> dict[str, str]:
        return {sketch.loaded.document.document_id: "save"}

    monkeypatch.setattr(window, "_ask_session_close_dialog", save)
    path = "" if outcome == "cancel" else str(tmp_path / "drawing.my2d")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (path, "")))
    if outcome == "error":

        def fail_write(*_args: object, **_kwargs: object) -> None:
            raise OSError("simulated write failure")

        monkeypatch.setattr(document_save, "save_document", fail_write)
    _close_tab(window, 0)
    saver, unit = window.document_saver, window.execution_unit
    assert saver is not None and unit is not None
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    current = window.active_sketch_dialog()
    assert current is not None and current.canvas.can_redo
    window.request_redo()
    assert tuple(current.canvas.entities) == both


def test_save_as_during_result_notification_does_not_open_file_dialog(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.new_session_document("part")
    unit, saver = window.execution_unit, window.document_saver
    assert unit is not None and saver is not None
    picker_calls: list[bool] = []
    results: list[str] = []

    def choose(*_args: object, **_kwargs: object) -> tuple[str, str]:
        picker_calls.append(True)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(choose))

    def save_on_result(_result: object) -> None:
        window.act_save_as.trigger()
        results.append(saver.last_results[-1].status)

    unit.result_ready.connect(save_on_result)
    assert unit.submit(lambda: None, operation="test-save-as", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(results), timeout=10000)
    assert not picker_calls
    assert results == ["failed"]


def test_save_rechecks_session_after_async_preparation(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Callable

    from mycad.ui import document_save

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    entry = window.new_session_document("part")
    pending: list[Callable[[bool], None]] = []
    writes: list[Path] = []
    controller = document_save.DocumentSaveController(
        session,
        prepare=lambda _entry, done: pending.append(done),
        choose_path=lambda _entry: tmp_path / "part.my3d",
        changed=lambda: None,
        report=lambda _results: None,
    )

    def record_write(_document: object, path: Path, **_kwargs: object) -> None:
        writes.append(path)

    monkeypatch.setattr(document_save, "save_document", record_write)
    controller.save_many((entry,))
    assert controller.running and len(pending) == 1
    session.remove(entry.loaded.document.document_id)
    pending[0](True)
    assert not writes
    assert controller.last_results[-1].status == "failed"


def test_failed_save_preserves_preexisting_document_redo(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame
    from mycad.ui import document_save

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    entry.path = tmp_path / "drawing.my2d"
    for radius in (3.0, 4.0):
        geometry = Sketch(
            uuid4().hex,
            WorkPlaneFrame.xy(),
            (CircleEntity(uuid4().hex, (20.0, 0.0), radius),),
        )
        entry.loaded.bus.execute("sketch.create", geometry.to_state_mapping(), "local")
    second = entry.loaded.document.commands[-1].instance_id
    entry.loaded.bus.undo_operation()
    assert len(entry.loaded.document.commands) == 1
    _add_circle(window)

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(document_save, "save_document", fail_write)
    window.act_save.trigger()
    saver, unit = window.document_saver, window.execution_unit
    assert saver is not None and unit is not None
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    assert saver.last_results[-1].status == "failed"
    entry.loaded.bus.redo_operation()
    assert entry.loaded.document.commands[-1].instance_id == second


@pytest.mark.parametrize("outcome", ["cancel", "error"])
def test_closing_inactive_drawing_after_unsuccessful_save_keeps_work_undoable(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    from mycad.ui import document_save

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    sketch = window.new_session_document("sketch")
    _add_circle(window)
    editor = window.active_sketch_dialog()
    assert editor is not None
    original = tuple(editor.canvas.entities)
    part = window.new_session_document("part")
    part.loaded.bus.execute("feature.box", {"size_x": 2, "size_y": 3, "size_z": 4}, "local")
    part_commands = part.loaded.document.commands

    def save(_entries: tuple[SessionDocument, ...]) -> dict[str, str]:
        return {sketch.loaded.document.document_id: "save"}

    target = tmp_path / "drawing.my2d"
    monkeypatch.setattr(window, "_ask_session_close_dialog", save)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *_args, **_kwargs: ("" if outcome == "cancel" else str(target), "")),
    )
    if outcome == "error":

        def fail_write(*_args: object, **_kwargs: object) -> None:
            raise OSError("simulated write failure")

        monkeypatch.setattr(document_save, "save_document", fail_write)
    _close_tab(window, 0)
    saver, unit = window.document_saver, window.execution_unit
    assert saver is not None and unit is not None
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    assert saver.last_results[-1].status == ("cancelled" if outcome == "cancel" else "failed")
    assert session.documents == (sketch, part)
    assert sketch.path is None and sketch.needs_save and not target.exists()
    assert part.loaded.document.commands == part_commands and part.needs_save
    current = window.active_sketch_dialog()
    assert current is not None
    assert current is editor
    assert tuple(current.canvas.entities) == original
    assert not sketch.loaded.document.commands
    window.request_undo()
    assert not current.canvas.entities
    window.request_redo()
    assert tuple(current.canvas.entities) == original


@pytest.mark.parametrize("failure", ["temporary", "replace"])
def test_atomic_file_failure_restores_original_draft_and_existing_file(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from mycad.core import persistence

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    entry.path = tmp_path / "original.my2d"
    original_bytes = b"existing file must survive"
    entry.path.write_bytes(original_bytes)
    identity = entry.loaded.document.file_id
    archive_version = entry.loaded.document.archive_version
    _add_circle(window)
    _add_circle(window)
    draft = window.active_sketch_dialog()
    assert draft is not None and draft.canvas.undo_last_operation()
    entities = tuple(draft.canvas.entities)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated atomic file failure")

    if failure == "temporary":
        monkeypatch.setattr(persistence.tempfile, "NamedTemporaryFile", fail)
    else:
        monkeypatch.setattr(persistence.os, "replace", fail)
    window.act_save.trigger()
    saver, unit = window.document_saver, window.execution_unit
    assert saver is not None and unit is not None
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    assert saver.last_results[-1].status == "failed"
    assert window.active_sketch_dialog() is draft and draft.canvas.can_redo
    assert tuple(draft.canvas.entities) == entities
    assert entry.loaded.document.commands == () and entry.needs_save
    assert entry.loaded.document.file_id == identity
    assert entry.loaded.document.archive_version == archive_version
    assert entry.path.read_bytes() == original_bytes
    assert not tuple(tmp_path.glob("*.tmp"))


def test_failed_save_as_preserves_identity_path_and_draft_history(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.ui import document_save

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    entry.path = tmp_path / "original.my2d"
    entry.path.write_bytes(b"original")
    loaded = entry.loaded
    _add_circle(window)
    _add_circle(window)
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.undo_last_operation()
    target = tmp_path / "copy.my2d"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (str(target), ""))
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("copy write failure")

    monkeypatch.setattr(document_save, "save_document", fail)
    window.act_save_as.trigger()
    saver, unit = window.document_saver, window.execution_unit
    assert saver is not None and unit is not None
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    assert saver.last_results[-1].status == "failed"
    assert entry.loaded is loaded and session.active is entry
    assert entry.path == tmp_path / "original.my2d"
    assert entry.path.read_bytes() == b"original" and not target.exists()
    assert window.active_sketch_dialog() is editor and editor.canvas.can_redo
    assert not loaded.document.commands


def test_partial_save_all_restores_only_failed_draft_and_does_not_prepare_later_draft(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.ui import document_save

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entries: list[SessionDocument] = []
    for index in range(3):
        entry = window.new_session_document("sketch")
        entry.path = tmp_path / f"drawing-{index}.my2d"
        _add_circle(window)
        _add_circle(window)
        editor = window.active_sketch_dialog()
        assert editor is not None and editor.canvas.undo_last_operation()
        entries.append(entry)
    second_draft, third_draft = entries[1].draft, entries[2].draft
    original_save = document_save.save_document

    def fail_second(document: object, path: Path, **_kwargs: object) -> None:
        if path == entries[1].path:
            raise OSError("second write failed")
        assert document is entries[0].loaded.document
        original_save(entries[0].loaded.document, path)

    monkeypatch.setattr(document_save, "save_document", fail_second)
    window.act_save_all.trigger()
    saver, unit = window.document_saver, window.execution_unit
    assert saver is not None and unit is not None
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    assert [result.status for result in saver.last_results] == ["saved", "failed", "pending"]
    first, second, third = entries
    assert first.path is not None and first.path.exists() and not first.needs_save
    assert first.loaded.document.commands
    assert second.draft is second_draft and second_draft is not None
    assert second_draft.canvas.can_redo and not second.loaded.document.commands
    assert third.draft is third_draft and third_draft is not None
    assert third_draft.canvas.can_redo and not third.loaded.document.commands
    assert second.needs_save and third.needs_save


def test_failed_mixed_save_retains_redo_and_can_retry_save_and_reopen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad import app
    from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
    from mycad.ui import document_save

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    entry.path = tmp_path / "mixed.my2d"
    saved = LineEntity(uuid4().hex, (-5.0, 0.0), (5.0, 0.0))
    geometry = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,))
    entry.loaded.bus.execute("sketch.create", geometry.to_state_mapping(), "local")
    editor = window.active_sketch_dialog()
    unit, saver = window.execution_unit, window.document_saver
    assert editor is not None and unit is not None and saver is not None
    editor.set_context_sketches(entry.services.kernel.sketches)
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (10.0, 10.0), (20.0, 10.0))
    canvas.replace_draft_entities((line,))
    for _ in range(2):
        canvas.selected_entity_ids = {saved.entity_id, line.entity_id}
        canvas.begin_transform("move")
        canvas.add_coordinate_point((0.0, 0.0), exact_point=True)
        canvas.add_coordinate_point((2.0, 3.0), exact_point=True)
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.undo_last_operation() and canvas.can_redo
    before = entry.loaded.document.commands
    entities = tuple(canvas.entities)
    selected = set(canvas.selected_entity_ids)
    source_revision = entry.loaded.document.revision
    original_save = document_save.save_document

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("mixed write failed")

    monkeypatch.setattr(document_save, "save_document", fail)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    assert saver.last_results[-1].status == "failed"
    assert window.active_sketch_dialog() is editor
    assert entry.loaded.document.commands == before
    assert tuple(canvas.entities) == entities and canvas.selected_entity_ids == selected
    assert canvas.mixed_move is not None and canvas.mixed_move_is_valid
    assert canvas.mixed_move.source_revision == entry.loaded.document.revision > source_revision
    assert canvas.redo_last_operation()
    assert canvas.mixed_move is not None
    assert canvas.mixed_move.source_revision == entry.loaded.document.revision
    expected = {entity.entity_id: entity for entity, _layer in canvas.background_entities}
    expected.update((entity.entity_id, entity) for entity in canvas.entities)
    monkeypatch.setattr(document_save, "save_document", original_save)
    window.act_save.trigger()
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    assert saver.last_results[-1].status == "saved"
    assert not entry.needs_save
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    reopened_services = build_app(discoverers=[])
    opened = app.open_app_document(reopened_services, entry.path)
    assert opened.document.commands == entry.loaded.document.commands
    actual = {
        entity.entity_id: entity
        for sketch in reopened_services.kernel.sketches
        for entity in sketch.entities
    }
    assert actual == expected


@pytest.mark.parametrize("failure", ["stale", "rebuild", "prepare"])
def test_save_recovery_reports_errors_without_overwriting_new_work(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame
    from mycad.ui import document_save

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    entry.path = tmp_path / "drawing.my2d"
    _add_circle(window)
    editor = window.active_sketch_dialog()
    assert editor is not None
    original = tuple(editor.canvas.entities)
    new_geometry = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (30.0, 0.0), 2.0),)
    )

    def fail_reset() -> None:
        raise RuntimeError("recovery kernel failure")

    def fail_write(*_args: object, **_kwargs: object) -> None:
        if failure == "stale":
            entry.loaded.bus.execute("sketch.create", new_geometry.to_state_mapping(), "local")
        elif failure == "rebuild":
            monkeypatch.setattr(entry.services.kernel, "reset", fail_reset)
        raise OSError("write failed")

    def fail_prepare(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("prepare rejected")

    monkeypatch.setattr(document_save, "save_document", fail_write)
    if failure == "prepare":
        monkeypatch.setattr(entry.loaded.bus, "execute", fail_prepare)
    window.act_save.trigger()
    saver, unit = window.document_saver, window.execution_unit
    assert saver is not None and unit is not None
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    assert saver.last_results[-1].status == "failed"
    assert tuple(editor.canvas.entities) == original
    assert entry.draft is editor and entry.needs_save
    assert not entry.path.exists()
    if failure == "stale":
        assert "document changed after preparation" in saver.last_results[-1].error
        assert len(entry.loaded.document.commands) == 2
        assert Sketch.from_mapping(entry.loaded.document.commands[-1].params) == new_geometry
        assert entry.loaded.bus.is_healthy
    elif failure == "rebuild":
        assert "recovery kernel failure" in saver.last_results[-1].error
        assert not entry.loaded.bus.is_healthy
    else:
        assert not entry.loaded.document.commands
        assert window.active_sketch_dialog() is editor
        assert entry.loaded.bus.is_healthy
    if failure != "prepare":
        assert not editor.isEnabled()
        window.new_session_document("part")
        window.activate_session_document(entry.loaded.document.document_id)
        assert unit.submit(lambda: None, operation="test-idle", session_id=unit.session_id)
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
        assert not editor.isEnabled()
        window.close_active_document()
        assert session.find(entry.loaded.document.document_id) is None
        replacement = window.new_session_document("sketch")
        assert session.active is replacement
        assert window.active_sketch_dialog() is not None


def test_post_write_ui_failure_keeps_saved_file_and_committed_document(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from mycad.ui.sketch_editor import SketchEditorDialog

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    entry.path = tmp_path / "drawing.my2d"
    _add_circle(window)

    def fail_ui(_self: SketchEditorDialog, _previous: SketchEditorDialog) -> None:
        raise RuntimeError("workspace refresh failed")

    monkeypatch.setattr(SketchEditorDialog, "continue_workspace_from", fail_ui)
    window.act_save.trigger()
    saver, unit = window.document_saver, window.execution_unit
    assert saver is not None and unit is not None
    qtbot.waitUntil(lambda: not saver.running and not unit.is_busy, timeout=10000)
    assert saver.last_results[-1].status == "saved"
    assert "workspace refresh failed" in saver.last_results[-1].error
    commands = json.loads(entry.path.read_text(encoding="utf-8"))["commands"]
    assert len(commands) == len(entry.loaded.document.commands) == 1
    assert not entry.loaded.document.is_dirty


def test_new_changes_during_file_notification_remain_dirty_after_write(
    qtbot: QtBot, tmp_path: Path
) -> None:
    import json

    session = DocumentSession()
    window = MainWindow(services=build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    entry = window.new_session_document("part")
    entry.path = tmp_path / "model.my3d"
    entry.loaded.document.set_metadata("notes", "before")

    def change_during_save(_payload: object) -> None:
        entry.loaded.document.set_metadata("notes", "after")

    entry.loaded.document.events.subscribe("document_saving", change_during_save)
    window.act_save.trigger()
    saver = window.document_saver
    assert saver is not None and not saver.running
    assert saver.last_results[-1].status == "saved"
    assert "新增修改仍待保存" in saver.last_results[-1].error
    assert entry.loaded.document.is_dirty
    payload = json.loads(entry.path.read_text(encoding="utf-8"))
    assert payload["metadata"]["notes"] == "before"
    assert entry.loaded.document.metadata_snapshot()["notes"] == "after"
