# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Desktop save operations target document ownership, including close cancellation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtWidgets import QFileDialog, QMenu
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.ui.document_save import SaveResult
from mycad.ui.document_session import SessionDocument
from mycad.ui.main_window import MainWindow


def window_with_session(qtbot: QtBot) -> MainWindow:
    from mycad.ui.document_session import DocumentSession

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    qtbot.addWidget(window)
    window.bind_document(app.new_workspace_document(services, kind="part"))
    return window


def test_overlapping_save_request_notifies_caller_of_rejection(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from collections.abc import Callable

    from mycad.ui.document_save import DocumentSaveController

    window = window_with_session(qtbot)
    session = window.document_session
    assert session is not None and session.active is not None
    pending: list[Callable[[bool], None]] = []
    responses: list[bool] = []
    controller = DocumentSaveController(
        session,
        prepare=lambda _entry, done: pending.append(done),
        choose_path=lambda _entry: tmp_path / "part.my3d",
        changed=lambda: None,
        report=lambda _results: None,
    )
    controller.save_many((session.active,))
    assert controller.running and len(pending) == 1
    controller.save_many((session.active,), on_complete=responses.append)
    assert responses == [False]
    assert controller.running
    pending[0](False)
    assert not controller.running


def test_save_during_result_notification_does_not_write_document(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.ui import document_save

    window = window_with_session(qtbot)
    session, unit, saver = window.document_session, window.execution_unit, window.document_saver
    assert session is not None and session.active is not None and unit is not None
    assert saver is not None
    active = session.active
    active.path = tmp_path / "model.my3d"
    active.loaded.document.set_metadata("notes", "unsaved")
    writes: list[Path] = []

    def record_write(_document: object, path: Path, **_kwargs: object) -> None:
        writes.append(path)

    monkeypatch.setattr(document_save, "save_document", record_write)
    observed: list[tuple[str, ...]] = []

    def save_on_result(_result: object) -> None:
        window.act_save.trigger()
        observed.append(tuple(result.status for result in saver.last_results))

    unit.result_ready.connect(save_on_result)
    assert unit.submit(lambda: None, operation="test-save", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert not writes
    assert observed == [("failed",)]
    assert active.loaded.document.is_dirty


def test_legacy_save_during_result_notification_waits(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    loaded = app.new_document(services)
    window.bind_document(loaded)
    loaded.document.set_metadata("notes", "unsaved")
    unit = window.execution_unit
    assert unit is not None

    def unexpected_dialog(*_args: object, **_kwargs: object) -> tuple[str, str]:
        pytest.fail("save dialog must wait for the original result")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(unexpected_dialog))
    observed: list[str] = []

    def save_on_result(_result: object) -> None:
        window.act_save.trigger()
        observed.append(window.status_command.text())

    unit.result_ready.connect(save_on_result)
    assert unit.submit(lambda: None, operation="test-legacy-save", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed), timeout=10000)
    assert "请稍候再保存" in observed[0]
    assert loaded.document.is_dirty


@pytest.mark.parametrize("fail_save_as", [False, True])
def test_v5_save_as_preserves_redo_and_failure_keeps_original_session(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_save_as: bool
) -> None:
    from mycad.ui import document_save

    window = window_with_session(qtbot)
    loaded = window.loaded_document()
    assert loaded is not None
    loaded.bus.apply_identity_upgrade(loaded.bus.prepare_identity_upgrade())
    for radius in (4, 5):
        loaded.bus.execute("feature.cylinder", {"radius": radius, "height": 2})
    old_path, new_path = tmp_path / "original.my3d", tmp_path / "copy.my3d"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (str(old_path), ""))
    )
    window.act_save.trigger()
    qtbot.waitUntil(old_path.exists)
    identity = loaded.document.commands[-1].instance_id
    loaded.bus.undo()
    before = old_path.read_bytes()
    original_file_id = loaded.document.file_id
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (str(new_path), ""))
    )
    if fail_save_as:

        def fail(*_args: object, **_kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(document_save, "save_document", fail)
    window.act_save_as.trigger()
    saver = window.document_saver
    assert saver is not None
    qtbot.waitUntil(lambda: not saver.running)
    current = window.loaded_document()
    assert current is not None
    if fail_save_as:
        assert current is loaded
        assert not new_path.exists()
        assert current.document.is_dirty
        assert saver.last_results[-1].status == "failed"
    else:
        assert current.document.archive_version == 5
        assert current.document.file_id != original_file_id
        assert json.loads(new_path.read_text())["version"] == 5
    current.bus.redo()
    assert current.document.commands[-1].instance_id == identity
    assert old_path.read_bytes() == before


def add_circle(window: MainWindow) -> None:
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.set_tool("圆")
    draft.canvas.add_coordinate_point((0, 0))
    draft.canvas.add_coordinate_point((5, 0))


def test_active_planar_sketch_uses_my2d_and_does_not_clean_model(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = window_with_session(qtbot)
    model = window.loaded_document()
    assert model is not None
    model.bus.execute("feature.box", {"size_x": 2, "size_y": 3, "size_z": 4}, "local")
    window.new_session_document("sketch")
    add_circle(window)
    defaults: list[str] = []
    target = tmp_path / "outline.my2d"

    def choose(*args: object, **_kwargs: object) -> tuple[str, str]:
        defaults.append(str(args[2]))
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(choose))
    window.act_save.trigger()
    qtbot.waitUntil(target.exists)
    assert Path(defaults[0]).name == "untitled-sketch.my2d"
    assert json.loads(target.read_text(encoding="utf-8"))["document_kind"] == "sketch"
    assert model.document.is_dirty
    assert window.document_session is not None
    assert window.document_session.active is not None
    assert window.document_session.active.path == target


def test_save_all_names_three_documents_independently(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = window_with_session(qtbot)
    model = window.loaded_document()
    assert model is not None
    model.bus.execute("feature.box", {"size_x": 2, "size_y": 3, "size_z": 4}, "local")
    window.new_session_document("sketch")
    add_circle(window)
    drawing = window.new_session_document("drawing")
    drawing.loaded.document.set_metadata("notes", "drawing")

    def choose(*args: object, **_kwargs: object) -> tuple[str, str]:
        return str(tmp_path / Path(str(args[2])).name), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(choose))
    window.act_save_all.trigger()
    saver = window.document_saver
    assert saver is not None
    qtbot.waitUntil(lambda: not saver.running)
    assert len(list(tmp_path.glob("*.my*"))) == 3, saver.last_results
    assert {p.name for p in tmp_path.glob("*.my*")} == {
        "untitled.my3d",
        "untitled-sketch.my2d",
        "untitled-drawing.my2d",
    }
    assert window.document_session is not None
    assert all(not d.needs_save for d in window.document_session.documents)


def test_save_all_does_not_prepare_inactive_document_when_switch_is_blocked(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.ui import document_save

    window = window_with_session(qtbot)
    window.show()
    session = window.document_session
    assert session is not None and session.active is not None
    part = session.active
    part.path = tmp_path / "part.my3d"
    part.loaded.document.set_metadata("notes", "unsaved")
    sketch = window.new_session_document("sketch")
    sketch.path = tmp_path / "sketch.my2d"
    add_circle(window)
    draft = window.active_sketch_dialog()
    assert draft is not None
    original = tuple(draft.canvas.entities)
    window.activate_session_document(part.loaded.document.document_id)
    assert session.active is part and window.command_palette is not None
    window.command_palette.command_activated.emit("feature.box")
    assert window.modeling_command_bar is not None and window.modeling_command_bar.isVisible()
    writes: list[Path] = []

    def record_write(_document: object, path: Path, **_kwargs: object) -> None:
        writes.append(path)

    monkeypatch.setattr(document_save, "save_document", record_write)
    window.act_save_all.trigger()
    saver = window.document_saver
    assert saver is not None
    qtbot.waitUntil(lambda: not saver.running, timeout=10000)
    assert writes == [part.path]
    assert not part.loaded.document.is_dirty
    assert session.active is part
    assert tuple(draft.canvas.entities) == original
    assert not sketch.loaded.document.commands
    assert any(
        result.document_id == sketch.loaded.document.document_id and result.status == "failed"
        for result in saver.last_results
    )


def test_close_discards_are_deferred_until_all_save_decisions_succeed(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = window_with_session(qtbot)
    window.show()
    model = window.loaded_document()
    assert model is not None
    model.bus.execute("feature.box", {"size_x": 2, "size_y": 3, "size_z": 4}, "local")
    window.new_session_document("sketch")
    add_circle(window)
    sketch = window.loaded_document()
    assert sketch is not None

    def choose_close(_self: MainWindow, entries: tuple[SessionDocument, ...]) -> dict[str, str]:
        return {
            d.loaded.document.document_id: "discard" if d.kind == "part" else "save"
            for d in entries
        }

    monkeypatch.setattr(MainWindow, "_ask_session_close_dialog", choose_close)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: ("", "")))
    window.close()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert window.isVisible()
    assert len(model.document.commands) == 1
    assert model.document.is_dirty
    assert window.document_session is not None
    assert len(window.document_session.documents) == 2
    assert not sketch.document.commands
    draft = window.active_sketch_dialog()
    assert draft is not None and len(draft.canvas.entities) == 1


def test_save_all_reports_partial_failure_and_keeps_unsaved_changes(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.ui import document_save

    window = window_with_session(qtbot)
    model = window.loaded_document()
    assert model is not None
    model.document.set_metadata("notes", "model")
    sketch = window.new_session_document("sketch")
    sketch.loaded.document.set_metadata("notes", "sketch")
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(
            lambda *_a, **_k: (
                str(
                    tmp_path
                    / ("model.my3d" if window.loaded_document() is model else "sketch.my2d")
                ),
                "",
            )
        ),
    )
    save = document_save.save_document

    def fail_second(document: app.Document, path: Path, **kwargs: object) -> None:
        if path.suffix == ".my2d":
            raise OSError("disk full")
        save(document, path)

    monkeypatch.setattr(document_save, "save_document", fail_second)
    window.act_save_all.trigger()
    assert (tmp_path / "model.my3d").exists()
    assert not model.document.is_dirty
    assert sketch.loaded.document.is_dirty
    assert window.document_saver is not None
    assert [r.status for r in window.document_saver.last_results] == ["saved", "failed"]


def test_save_all_rejects_duplicate_targets_before_any_write(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = window_with_session(qtbot)
    first = window.loaded_document()
    assert first is not None
    first.document.set_metadata("notes", "first")
    second = window.new_session_document("part")
    second.loaded.document.set_metadata("notes", "second")
    path = tmp_path / "collision.my3d"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (str(path), ""))
    )
    window.act_save_all.trigger()
    assert not path.exists()
    assert first.document.is_dirty and second.loaded.document.is_dirty
    assert window.document_saver is not None
    assert any(r.status == "failed" for r in window.document_saver.last_results)


def test_switch_requested_during_save_cannot_redirect_the_write(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = window_with_session(qtbot)
    session = window.document_session
    assert session is not None and session.active is not None
    model = session.active
    sketch = window.new_session_document("sketch")
    add_circle(window)
    entered, release = Event(), Event()
    original = sketch.loaded.bus.execute

    def slow_execute(
        command_id: str,
        params: Mapping[str, object],
        confirmed_by: str | None = None,
        *,
        version: int | None = None,
    ) -> object | None:
        entered.set()
        assert release.wait(5)
        return original(command_id, params, confirmed_by, version=version)

    monkeypatch.setattr(sketch.loaded.bus, "execute", slow_execute)
    path = tmp_path / "outline.my2d"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (str(path), ""))
    )
    window.act_save.trigger()
    qtbot.waitUntil(entered.is_set)
    window.activate_session_document(model.loaded.document.document_id)
    release.set()
    qtbot.waitUntil(lambda: path.exists() and session.active is model)
    assert json.loads(path.read_text(encoding="utf-8"))["document_kind"] == "sketch"
    assert model.loaded.document.commands == ()
    assert sketch.path == path


def test_save_as_creates_file_identity_without_retargeting_references(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = window_with_session(qtbot)
    source = window.new_session_document("sketch")
    add_circle(window)
    first = tmp_path / "source.my2d"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (str(first), ""))
    )
    window.act_save.trigger()
    qtbot.waitUntil(first.exists)
    before = first.read_bytes()
    old_identity = source.loaded.document.file_id
    target = window.new_session_document("part")
    target.loaded.bus.execute(
        "reference.attach",
        app.reference_parameters(
            source.loaded.document, object_id=source.services.kernel.sketches[0].sketch_id
        ),
        "local",
    )
    window.activate_session_document(source.loaded.document.document_id)
    copied = tmp_path / "copy.my2d"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (str(copied), ""))
    )
    window.act_save_as.trigger()
    assert copied.exists()
    assert first.read_bytes() == before
    assert source.loaded.document.file_id != old_identity
    assert target.services.kernel.document_references[0].file_id == old_identity


def test_close_can_save_a_named_dirty_document_synchronously(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = window_with_session(qtbot)
    window.show()
    loaded = window.loaded_document()
    assert loaded is not None
    target = tmp_path / "model.my3d"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (str(target), ""))
    )
    window.act_save.trigger()
    loaded.document.set_metadata("notes", "keep")

    def save_all(_self: MainWindow, entries: tuple[SessionDocument, ...]) -> dict[str, str]:
        return {e.loaded.document.document_id: "save" for e in entries}

    monkeypatch.setattr(MainWindow, "_ask_session_close_dialog", save_all)
    window.close()
    qtbot.waitUntil(lambda: not window.isVisible())
    assert json.loads(target.read_text(encoding="utf-8"))["metadata"]["notes"] == "keep"


def test_save_as_same_path_preserves_file_identity(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = window_with_session(qtbot)
    path = tmp_path / "same.my3d"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (str(path), ""))
    )
    window.act_save.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    identity = loaded.document.file_id
    loaded.document.set_metadata("notes", "revision")
    window.act_save_as.trigger()
    assert json.loads(path.read_text(encoding="utf-8"))["file_id"] == identity


def test_saved_migrated_document_reopens_with_its_path(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.persistence import save_document

    window = window_with_session(qtbot)
    services = app.fork_app_services(app.build_app(discoverers=[]))
    legacy = app.new_document(services)
    old = tmp_path / "legacy.mc.json"
    save_document(legacy.document, old)
    migrated = app.open_session_documents(services, old)[0][1]
    target = tmp_path / "migrated.my3d"
    save_document(migrated.document, target)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *_a, **_k: (str(target), ""))
    )
    window.act_open.trigger()
    session, unit = window.document_session, window.execution_unit
    assert session is not None and unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy and len(session.documents) == 2)
    assert session.active is not None
    assert session.active.path == target
    assert not session.active.needs_save
    session.active.loaded.document.set_metadata("notes", "next revision")

    def unexpected_dialog(*_args: object, **_kwargs: object) -> tuple[str, str]:
        pytest.fail("Ctrl+S must retain the path of a saved migrated v4 document")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(unexpected_dialog))
    window.act_save.trigger()
    assert json.loads(target.read_text(encoding="utf-8"))["metadata"]["notes"] == "next revision"


def test_save_as_rebases_reference_to_a_closed_source(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame

    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 5),))
    source.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    source_path = old / "source.my2d"
    save_document(source.document, source_path)
    window = window_with_session(qtbot)
    session = window.document_session
    assert session is not None and session.active is not None
    dependent = session.active
    dependent.loaded.bus.execute(
        "reference.attach",
        app.reference_parameters(source.document, object_id=sketch.sketch_id),
        "local",
    )
    dependent.path = old / "part.my3d"
    dependent.reference_locations[source.document.file_id] = "source.my2d"
    save_document(
        dependent.loaded.document, dependent.path, reference_locations=dependent.reference_locations
    )
    target = new / "copy.my3d"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (str(target), ""))
    )
    window.act_save_as.trigger()
    location = json.loads(target.read_text(encoding="utf-8"))["reference_locations"][
        source.document.file_id
    ]
    assert (target.parent / location).resolve() == source_path.resolve()


def test_failed_migration_does_not_change_the_active_session(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document

    window = window_with_session(qtbot)
    session, unit = window.document_session, window.execution_unit
    assert session is not None and session.active is not None and unit is not None
    active, documents = session.active, session.documents
    active.loaded.bus.execute("feature.box", {"size_x": 2, "size_y": 3, "size_z": 4}, "local")
    services = app.fork_app_services(active.services)
    legacy = app.new_document(services)
    path = tmp_path / "legacy.mc.json"
    save_document(legacy.document, path)

    def fail_migration(*_args: object) -> tuple[dict[str, object], ...]:
        raise ValidationError("cannot migrate this archive")

    monkeypatch.setattr(app, "migrate_archive", fail_migration)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *_a, **_k: (str(path), ""))
    )
    window.act_open.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert session.documents == documents and session.active is active
    assert len(active.loaded.document.commands) == 1
    assert len(active.services.kernel.body_ids) == 1


@pytest.mark.parametrize("duplicate_file_identity", [False, True])
def test_invalid_migration_bundle_does_not_leave_partial_documents(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    duplicate_file_identity: bool,
) -> None:
    window = window_with_session(qtbot)
    session, unit = window.document_session, window.execution_unit
    assert session is not None and session.active is not None and unit is not None
    active, documents = session.active, session.documents
    services = app.fork_app_services(active.services)
    candidate = app.new_workspace_document(services, kind="sketch")
    second_services, second = services, candidate
    if duplicate_file_identity:
        from mycad.core.persistence import save_document

        path = tmp_path / "candidate.my2d"
        save_document(candidate.document, path)
        second_services = app.fork_app_services(services)
        second = app.open_app_document(second_services, path)
        assert second.document.document_id != candidate.document.document_id
        assert second.document.file_id == candidate.document.file_id
    errors: list[str] = []

    def invalid_bundle(*_args: object) -> app.SessionOpenResult:
        return app.SessionOpenResult(((services, candidate), (second_services, second)), True)

    monkeypatch.setattr(window, "_show_error", errors.append)
    monkeypatch.setattr(app, "open_session_bundle", invalid_bundle)
    window.open_document_path(tmp_path / "invalid.mc.json")
    qtbot.waitUntil(lambda: bool(errors), timeout=10000)
    assert session.documents == documents
    assert session.active is active
    assert session.latest("sketch") is None


def test_close_after_save_waits_for_background_refresh_without_prompting_again(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = window_with_session(qtbot)
    window.show()
    session, unit, saver = window.document_session, window.execution_unit, window.document_saver
    assert (
        session is not None
        and session.active is not None
        and unit is not None
        and saver is not None
    )
    session.active.path = tmp_path / "model.my3d"
    session.active.loaded.document.set_metadata("notes", "keep")
    prompts: list[int] = []

    def choose(_self: MainWindow, entries: tuple[SessionDocument, ...]) -> dict[str, str]:
        prompts.append(1)
        return {e.loaded.document.document_id: "save" for e in entries}

    monkeypatch.setattr(MainWindow, "_ask_session_close_dialog", choose)
    release = Event()
    report = saver.report

    def report_and_refresh(results: tuple[SaveResult, ...]) -> None:
        report(results)
        unit.submit(
            lambda: release.wait(5), operation="viewport-refresh", session_id=unit.session_id
        )

    saver.report = report_and_refresh
    window.close()
    qtbot.waitUntil(lambda: unit.is_busy)
    qtbot.wait(20)
    release.set()
    qtbot.waitUntil(lambda: not window.isVisible())
    assert len(prompts) == 1


def test_locating_moved_source_updates_saved_locator(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 5),))
    source.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    original = tmp_path / "old.my2d"
    save_document(source.document, original)
    window = window_with_session(qtbot)
    session, unit = window.document_session, window.execution_unit
    assert session is not None and session.active is not None and unit is not None
    dependent = session.active
    dependent.path = tmp_path / "model.my3d"
    dependent.loaded.bus.execute(
        "reference.attach",
        app.reference_parameters(source.document, object_id=sketch.sketch_id, path=str(original)),
        "local",
    )
    dependent.reference_locations[source.document.file_id] = original.name
    moved = tmp_path / "moved.my2d"
    original.rename(moved)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *_a, **_k: (str(moved), ""))
    )
    menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "文档")
    assert isinstance(menu, QMenu)
    next(a for a in menu.actions() if a.text() == "更新来源引用").trigger()
    qtbot.waitUntil(lambda: len(dependent.loaded.document.commands) == 2 and not unit.is_busy)
    window.act_save.trigger()
    location = json.loads(dependent.path.read_text(encoding="utf-8"))["reference_locations"][
        source.document.file_id
    ]
    assert (dependent.path.parent / location).resolve() == moved.resolve()
