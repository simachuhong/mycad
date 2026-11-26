# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Save recovery restores history and geometry without rewinding revisions."""

import pytest

from mycad.core.exceptions import ReplayDuringRollbackError, ValidationError
from tests.core.test_bus import make_bus


def test_checkpoint_restores_both_history_branches_and_document_state() -> None:
    bus, document, kernel = make_bus()
    params = {"radius": 3, "height": 2}
    bus.execute("feature.cylinder", params, "local")
    bus.execute("feature.cylinder", {**params, "radius": 4}, "local")
    second = document.commands[-1]
    bus.undo_operation()
    document.mark_clean()
    before = document.commands
    checkpoint = bus.create_save_checkpoint()
    bus.execute("feature.cylinder", {**params, "radius": 5}, "local")
    revision = document.revision
    bus.restore_save_checkpoint(checkpoint, expected_revision=revision)
    assert document.commands == before
    assert not document.is_dirty
    assert document.revision > revision
    assert kernel.applied == [("feature.cylinder", before[0].params)]
    bus.redo_operation()
    assert document.commands[-1] == second
    bus.undo_operation()
    bus.undo_operation()
    assert not document.commands
    with pytest.raises(ValidationError):
        bus.restore_save_checkpoint(checkpoint, expected_revision=document.revision)


def test_checkpoint_restores_command_redo() -> None:
    bus, document, _kernel = make_bus()
    bus.execute("demo.a", {}, "local")
    bus.execute("demo.b", {}, "local")
    second = document.commands[-1]
    bus.undo()
    checkpoint = bus.create_save_checkpoint()
    bus.execute("demo.a", {}, "local")
    bus.restore_save_checkpoint(checkpoint, expected_revision=document.revision)
    bus.redo()
    assert document.commands[-1] == second


def test_checkpoint_refuses_foreign_stale_or_consumed_handle() -> None:
    bus, document, _kernel = make_bus()
    other, _document, _other_kernel = make_bus()
    checkpoint = bus.create_save_checkpoint()
    with pytest.raises(ValidationError):
        other.restore_save_checkpoint(checkpoint, expected_revision=0)
    revision = document.revision
    bus.execute("demo.a", {}, "local")
    with pytest.raises(ValidationError):
        bus.restore_save_checkpoint(checkpoint, expected_revision=revision)
    assert len(document.commands) == 1
    bus.release_save_checkpoint(checkpoint)
    with pytest.raises(ValidationError):
        bus.restore_save_checkpoint(checkpoint, expected_revision=document.revision)


def test_releasing_checkpoint_keeps_successful_edits() -> None:
    bus, document, _kernel = make_bus()
    checkpoint = bus.create_save_checkpoint()
    bus.execute("demo.a", {}, "local")
    bus.release_save_checkpoint(checkpoint)
    assert len(document.commands) == 1
    bus.undo_operation()
    assert not document.commands


def test_failed_recovery_marks_bus_unhealthy() -> None:
    bus, document, kernel = make_bus()
    bus.execute("feature.cylinder", {"radius": 3, "height": 2}, "local")
    checkpoint = bus.create_save_checkpoint()
    bus.execute("demo.a", {}, "local")

    def unavailable(_index: int, _command: str, _params: dict[str, object]) -> Exception:
        return RuntimeError("recovery unavailable")

    kernel.fail_when = unavailable
    with pytest.raises(ReplayDuringRollbackError):
        bus.restore_save_checkpoint(checkpoint, expected_revision=document.revision)
    assert not bus.is_healthy


def test_checkpoint_restores_metadata_groups_and_archive_version() -> None:
    from mycad.commands.spec import CliSyntax, CommandSpec
    from mycad.core.bus import CommandBus
    from mycad.core.document import Document
    from mycad.core.groups import NamedGroup
    from tests.core.test_bus import EchoHandler, make_assembly

    registry, handlers, kernel = make_assembly()
    registry.register(
        CommandSpec(
            "demo.upgrade",
            1,
            "upgrade",
            "upgrade",
            {"type": "object", "properties": {}, "additionalProperties": False},
            CliSyntax(("upgrade",)),
            min_archive_version=2,
        )
    )
    handlers["demo.upgrade"] = EchoHandler("demo.upgrade")
    document = Document(registry)
    bus = CommandBus(document, registry, kernel, handlers)
    version = document.archive_version
    checkpoint = bus.create_save_checkpoint()
    bus.execute("demo.upgrade", {}, "local")
    document.set_metadata("notes", "temporary")
    document.add_named_group(NamedGroup("temporary"))
    bus.restore_save_checkpoint(checkpoint, expected_revision=document.revision)
    assert not document.commands
    assert not document.named_groups
    assert document.metadata_snapshot().get("notes") is None
    assert document.archive_version == version


def test_unchanged_preparation_keeps_revision_and_redo() -> None:
    bus, document, _kernel = make_bus()
    bus.execute("demo.a", {}, "local")
    bus.undo_operation()
    revision = document.revision
    checkpoint = bus.create_save_checkpoint()
    bus.restore_save_checkpoint(checkpoint, expected_revision=revision)
    assert document.revision == revision
    bus.redo_operation()
    assert len(document.commands) == 1


def test_checkpoint_recovery_requires_matching_drawing_guard() -> None:
    bus, document, _kernel = make_bus()
    checkpoint = bus.create_save_checkpoint()
    bus.execute("demo.a", {}, "local")
    guard = bus.acquire_drawing_write_guard()
    revision = document.revision
    with pytest.raises(ValidationError, match="暂存"):
        bus.restore_save_checkpoint(checkpoint, expected_revision=revision)
    with pytest.raises(ValidationError, match="暂存"):
        bus.restore_save_checkpoint(
            checkpoint, expected_revision=revision, drawing_write_guard="invalid"
        )
    assert len(document.commands) == 1
    bus.restore_save_checkpoint(checkpoint, expected_revision=revision, drawing_write_guard=guard)
    assert not document.commands
    with pytest.raises(ValidationError, match="暂存"):
        bus.execute("demo.a", {}, "local")
    bus.release_drawing_write_guard(guard)
    bus.execute("demo.a", {}, "local")


def test_late_execute_failure_restores_operation_undo_and_redo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import Callable
    from typing import cast

    bus, document, _kernel = make_bus()
    bus.execute("demo.a", {}, "local")
    bus.execute("demo.b", {}, "local")
    second = document.commands[-1]
    bus.undo_operation()
    before = document.commands
    revision = document.revision
    record = cast("Callable[[object, object], None]", vars(type(bus))["_record_operation"])

    def fail_after_record(state: object) -> None:
        record(bus, state)
        raise RuntimeError("simulated late failure")

    monkeypatch.setattr(bus, "_record_operation", fail_after_record)
    with pytest.raises(RuntimeError, match="simulated late failure"):
        bus.execute("demo.a", {}, "local")
    assert document.commands == before and document.revision > revision
    assert bus.execute_rolled_back_from(revision)
    bus.redo_operation()
    assert document.commands[-1] == second
    assert not bus.execute_rolled_back_from(revision)
    bus.undo_operation()
    bus.undo_operation()
    assert document.commands == ()


def test_late_redo_failure_preserves_original_undo_and_redo_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import Callable
    from typing import cast

    bus, document, _kernel = make_bus()
    bus.execute("demo.a", {}, "local")
    bus.execute("demo.b", {}, "local")
    original = document.commands
    bus.undo()
    before = document.commands
    revision = document.revision
    record = cast("Callable[[object, object], None]", vars(type(bus))["_record_operation"])

    def fail_after_record(state: object) -> None:
        record(bus, state)
        raise RuntimeError("simulated late redo failure")

    monkeypatch.setattr(bus, "_record_operation", fail_after_record)
    with pytest.raises(RuntimeError, match="simulated late redo failure"):
        bus.redo_operation()
    assert document.commands == before and document.revision > revision
    monkeypatch.undo()
    bus.redo_operation()
    assert document.commands == original
    bus.undo_operation()
    assert document.commands == before
    bus.undo_operation()
    assert document.commands == ()


def test_late_undo_failure_keeps_original_operation_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import Callable
    from typing import cast

    bus, document, _kernel = make_bus()
    bus.execute("demo.a", {}, "local")
    bus.execute("demo.b", {}, "local")
    original = document.commands
    revision = document.revision
    advance = cast("Callable[[], None]", vars(bus)["_advance_document_revision"])

    def fail_after_advance() -> None:
        advance()
        raise RuntimeError("simulated late undo failure")

    monkeypatch.setattr(bus, "_advance_document_revision", fail_after_advance)
    with pytest.raises(RuntimeError, match="simulated late undo failure"):
        bus.undo_operation()
    assert document.commands == original and document.revision > revision
    monkeypatch.setattr(bus, "_advance_document_revision", advance)
    bus.undo_operation()
    assert len(document.commands) == 1
    bus.redo_operation()
    assert document.commands == original
