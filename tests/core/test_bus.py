# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""CommandBus tests (T6c): dispatch, undo/redo, edit replay, batch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import copy
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from mycad.commands.demo import demo_registry
from mycad.commands.registry import CommandRegistry
from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.core.bus import CommandBus
from mycad.core.document import AFFECTED_OBJECTS, Document, ExecutedCommand, PlannedCommand
from mycad.core.exceptions import (
    BatchRollbackError,
    GeometryBuildError,
    InvalidHistoryError,
    InvalidPlanTransition,
    ReplayDuringRollbackError,
    TopologyReferenceError,
    UnknownCommandError,
    ValidationError,
)
from mycad.core.groups import NamedGroup
from mycad.core.handlers import BuiltinModelingHandler, CommandHandler, HandlerContext
from mycad.core.measurements import MeasurementRequest, MeasurementResult
from mycad.core.plan import ConfirmationScope, Plan, PlanConfirmation

_EMPTY: dict[str, object] = {"type": "object", "properties": {}, "additionalProperties": False}


class FakeKernel:
    """Kernel double: records applies; ``fail_when`` injects failures."""

    def __init__(self) -> None:
        self.applied: list[tuple[str, dict[str, object]]] = []
        self.reset_count = 0
        self.fail_when: Callable[[int, str, dict[str, object]], Exception | None] | None = None
        self._apply_total = 0  # reset() never clears this

    def reset(self) -> None:
        self.reset_count += 1
        self.applied.clear()

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        n = self._apply_total
        self._apply_total += 1
        if self.fail_when is not None:
            exc = self.fail_when(n, command_id, dict(params))
            if exc is not None:
                raise exc
        self.applied.append((command_id, dict(params)))

    def measure(self, request: MeasurementRequest) -> MeasurementResult:
        raise NotImplementedError(request)


class FakeHandler:
    """Bound to demo.ping; returns 'pong'."""

    def __init__(self) -> None:
        self.command_id = "demo.ping"

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> object | None:
        return "pong"


class EchoHandler:
    """Echoes its bound id; asserts ctx.command_id agreement."""

    def __init__(self, command_id: str) -> None:
        self.command_id = command_id

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> object | None:
        assert ctx.command_id == self.command_id
        return self.command_id


class VersionHandler:
    """Expose the exact handler version selected by the Bus."""

    def __init__(self, command_id: str, version: int) -> None:
        self.command_id = command_id
        self.version = version

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> object | None:
        assert ctx.command_id == self.command_id
        assert ctx.command_version == self.version
        return self.version


class PartialFailureHandler:
    """Inject document and kernel mutations before failing a command."""

    command_id = "demo.a"

    def __init__(self, document: Document) -> None:
        self.document = document

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> object | None:
        ctx.kernel.apply(self.command_id, params)
        self.document.set_metadata("part_name", "uncommitted")
        self.document.add_named_group(NamedGroup("uncommitted"))
        raise RuntimeError("handler failed after mutation")


class FailingVersionHandler:
    """Force a v2 command to fail after its handler has begun."""

    command_id = "demo.schema_v2_fail"

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> object | None:
        ctx.kernel.apply(self.command_id, params)
        raise RuntimeError("deliberate failure")


def make_assembly() -> tuple[CommandRegistry, dict[str, CommandHandler], FakeKernel]:
    """Registry + handlers + fake kernel; demo.ghost has NO handler on purpose."""
    reg = demo_registry()
    for cid in ("demo.ping", "demo.a", "demo.b", "demo.ghost"):
        reg.register(CommandSpec(cid, 1, cid, cid, _EMPTY, CliSyntax((cid,))))
    reg.register(
        CommandSpec(
            "demo.sel",
            1,
            "sel",
            "选择器",
            {
                "type": "object",
                "properties": {
                    "surface": {"type": "string", "enum": ["plane", "cylinder"]},
                    "axis": {"type": "string"},
                },
                "required": ["surface"],
                "additionalProperties": False,
            },
            CliSyntax(("demo.sel",)),
        )
    )
    fake = FakeKernel()
    handlers: dict[str, CommandHandler] = {
        "demo.ping": FakeHandler(),
        "demo.a": EchoHandler("demo.a"),
        "demo.b": EchoHandler("demo.b"),
        "demo.sel": EchoHandler("demo.sel"),
        "feature.cylinder": BuiltinModelingHandler("feature.cylinder"),
    }
    return reg, handlers, fake


def make_bus() -> tuple[CommandBus, Document, FakeKernel]:
    reg, handlers, fake = make_assembly()
    doc = Document(reg)
    return CommandBus(doc, reg, fake, handlers), doc, fake


def test_versioned_datum_guard_receives_recorded_version_on_submit_and_history_edit() -> None:
    class GuardKernel(FakeKernel):
        def __init__(self) -> None:
            super().__init__()
            self.guarded: list[tuple[str, int]] = []

        def validate_datum_revision(self, command_id: str, params: Mapping[str, object]) -> None:
            raise AssertionError("versioned guard should be used")

        def validate_datum_revision_versioned(
            self, command_id: str, params: Mapping[str, object], version: int
        ) -> None:
            self.guarded.append((command_id, version))

    reg, _, _ = make_assembly()
    reg.register(replace(reg.get("demo.a", 1), version=2))
    kernel = GuardKernel()
    doc = Document(reg)
    versioned_handlers: dict[tuple[str, int], CommandHandler] = {
        ("demo.a", 2): EchoHandler("demo.a")
    }
    bus = CommandBus(doc, reg, kernel, versioned_handlers)
    bus.execute("demo.a", {}, "test", version=2)
    assert kernel.guarded == [("demo.a", 2)]
    kernel.guarded.clear()
    bus.edit_and_replay(0, {}, "test", "verify version")
    assert ("demo.a", 2) in kernel.guarded
    kernel.guarded.clear()
    assert bus.replay_for_candidate(guard_from_ordinal=0) is None
    assert kernel.guarded == [("demo.a", 2)]


def test_legacy_datum_guard_remains_compatible() -> None:
    class LegacyGuardKernel(FakeKernel):
        def __init__(self) -> None:
            super().__init__()
            self.guarded: list[str] = []

        def validate_datum_revision(self, command_id: str, params: Mapping[str, object]) -> None:
            self.guarded.append(command_id)

    reg, handlers, _ = make_assembly()
    kernel = LegacyGuardKernel()
    doc = Document(reg)
    bus = CommandBus(doc, reg, kernel, handlers)
    bus.execute("demo.a", {}, "test")
    assert kernel.guarded == ["demo.a"]
    kernel.guarded.clear()
    bus.edit_and_replay(0, {}, "test", "verify legacy guard")
    assert "demo.a" in kernel.guarded


def redo_stack(bus: CommandBus) -> list[ExecutedCommand]:
    """Test-side probe of the Bus redo stack (pyright-protected member)."""
    return cast(
        "list[ExecutedCommand]",
        getattr(bus, "_redo_stack"),  # noqa: B009
    )


def test_ping_pass_through_and_history() -> None:
    bus, doc, _fake = make_bus()
    assert bus.execute("demo.ping", {}) == "pong"
    assert len(doc.commands) == 1


def test_spec_without_handler_raises_unknown() -> None:
    bus, _doc, _fake = make_bus()
    with pytest.raises(UnknownCommandError):
        bus.execute("demo.ghost", {})


def test_unregistered_id_raises_unknown() -> None:
    bus, _doc, _fake = make_bus()
    with pytest.raises(UnknownCommandError):
        bus.execute("demo.nothing", {})


def test_archive_schema_version_changes_only_after_a_successful_bus_command() -> None:
    registry = demo_registry()
    registry.register(
        CommandSpec(
            "demo.schema_v2",
            1,
            "schema v2",
            "存档二",
            _EMPTY,
            CliSyntax(("schema-v2",)),
            min_archive_version=2,
        )
    )
    registry.register(
        CommandSpec(
            "demo.schema_v2_fail",
            1,
            "schema v2 failure",
            "失败",
            _EMPTY,
            CliSyntax(("schema-v2-fail",)),
            min_archive_version=2,
        )
    )
    successful_document = Document(registry)
    successful_bus = CommandBus(
        successful_document,
        registry,
        FakeKernel(),
        {"demo.schema_v2": EchoHandler("demo.schema_v2")},
    )

    assert successful_document.archive_version == 1
    successful_bus.execute("demo.schema_v2", {})
    assert successful_document.archive_version == 2
    successful_bus.undo()
    assert successful_document.archive_version == 2

    failed_document = Document(registry)
    failed_bus = CommandBus(
        failed_document,
        registry,
        FakeKernel(),
        {"demo.schema_v2_fail": FailingVersionHandler()},
    )
    with pytest.raises(RuntimeError, match="deliberate failure"):
        failed_bus.execute("demo.schema_v2_fail", {})
    assert failed_document.archive_version == 1


def test_dispatch_lock_echo_ids() -> None:
    bus, _doc, _fake = make_bus()
    assert bus.execute("demo.a", {}) == "demo.a"
    assert bus.execute("demo.b", {}) == "demo.b"


def test_execute_binds_spec_and_handler_to_requested_version() -> None:
    registry = CommandRegistry()
    command_id = "feature.cylinder"
    v1 = CommandSpec(
        command_id,
        1,
        "v1",
        "v1",
        {
            "type": "object",
            "properties": {"old": {"type": "string"}},
            "required": ["old"],
            "additionalProperties": False,
        },
        CliSyntax((command_id,)),
    )
    v2 = CommandSpec(
        command_id,
        2,
        "v2",
        "v2",
        {
            "type": "object",
            "properties": {"new": {"type": "integer"}},
            "required": ["new"],
            "additionalProperties": False,
        },
        CliSyntax((command_id,)),
    )
    registry.register(v1)
    registry.register(v2)
    document = Document(registry)
    handlers: dict[tuple[str, int], CommandHandler] = {
        (command_id, 1): VersionHandler(command_id, 1),
        (command_id, 2): VersionHandler(command_id, 2),
    }
    bus = CommandBus(document, registry, FakeKernel(), handlers)
    post_events: list[Mapping[str, object]] = []
    amendment_events: list[Mapping[str, object]] = []
    document.events.subscribe("post_command", post_events.append)
    document.events.subscribe("command_amended", amendment_events.append)

    assert bus.execute(command_id, {"old": "legacy"}, version=1) == 1
    assert bus.execute(command_id, {"new": 2}) == 2
    assert [event["command_version"] for event in post_events] == [1, 2]
    assert [command.version for command in document.commands] == [1, 2]
    bus.edit_and_replay(0, {"old": "edited"}, "tester", "keep v1 semantics")
    assert amendment_events[0]["command_version"] == 1
    assert document.commands[0].version == 1
    with pytest.raises(ValidationError):
        bus.execute(command_id, {"new": 3}, version=1)


def test_id_only_handler_cannot_be_reused_across_command_versions() -> None:
    registry = CommandRegistry()
    command_id = "demo.versioned"
    for version in (1, 2):
        registry.register(
            CommandSpec(
                command_id,
                version,
                f"v{version}",
                f"v{version}",
                _EMPTY,
                CliSyntax((command_id,)),
            )
        )
    document = Document(registry)
    legacy_handler: dict[str, CommandHandler] = {command_id: VersionHandler(command_id, 1)}
    bus = CommandBus(document, registry, FakeKernel(), legacy_handler)

    with pytest.raises(UnknownCommandError, match="version 2"):
        bus.execute(command_id, {}, version=2)


def test_execute_batch_uses_planned_command_version() -> None:
    registry = CommandRegistry()
    command_id = "feature.cylinder"
    registry.register(
        CommandSpec(
            command_id,
            1,
            "v1",
            "v1",
            {
                "type": "object",
                "properties": {"old": {"type": "string"}},
                "required": ["old"],
                "additionalProperties": False,
            },
            CliSyntax((command_id,)),
        )
    )
    registry.register(
        CommandSpec(
            command_id,
            2,
            "v2",
            "v2",
            {
                "type": "object",
                "properties": {"new": {"type": "integer"}},
                "required": ["new"],
                "additionalProperties": False,
            },
            CliSyntax((command_id,)),
        )
    )
    document = Document(registry)
    handlers: dict[tuple[str, int], CommandHandler] = {
        (command_id, 1): VersionHandler(command_id, 1),
        (command_id, 2): VersionHandler(command_id, 2),
    }
    bus = CommandBus(document, registry, FakeKernel(), handlers)
    plan = Plan(
        [
            PlannedCommand(
                id=command_id,
                version=1,
                params={"old": "legacy"},
                summary_en="v1",
                affected_object="cylinder_body",
            )
        ]
    )
    bus.confirm_plan(plan, "tester", scope="cli")

    bus.execute_batch(plan, scope="cli")

    assert document.commands[0].version == 1


def test_echo_handler_ctx_mismatch_asserts() -> None:
    _reg, _handlers, fake = make_assembly()
    with pytest.raises(AssertionError):
        EchoHandler("demo.a").handle({}, HandlerContext(kernel=fake, command_id="demo.b"))


def run_four_cylinders(bus: CommandBus) -> None:
    for radius in (1.0, 2.0, 3.0, 4.0):
        bus.execute("feature.cylinder", {"radius": radius, "height": 1.0})


def test_execute_confirmed_by_lands_in_history() -> None:
    bus, doc, _fake = make_bus()
    bus.execute("feature.cylinder", {"radius": 1.0, "height": 1.0}, confirmed_by="cli-local")
    assert doc.commands[0].confirmed_by == "cli-local"
    bus.execute("feature.cylinder", {"radius": 2.0, "height": 1.0})
    assert doc.commands[1].confirmed_by is None


def test_undo_default_pops_one() -> None:
    bus, doc, fake = make_bus()
    run_four_cylinders(bus)
    bus.undo()
    assert len(doc.commands) == 3
    assert len(redo_stack(bus)) == 1
    assert fake.reset_count == 1


def test_undo_three_single_rebuild() -> None:
    bus, _doc, fake = make_bus()
    run_four_cylinders(bus)
    bus.undo(3)
    assert len(_doc.commands) == 1
    assert fake.reset_count == 1
    assert [p["radius"] for _, p in fake.applied] == [1.0]


def test_redo_two_restores_sequence() -> None:
    bus, doc, fake = make_bus()
    run_four_cylinders(bus)
    bus.undo(2)
    bus.redo(2)
    assert [p["radius"] for _, p in fake.applied] == [1.0, 2.0, 3.0, 4.0]
    assert len(doc.commands) == 4
    assert redo_stack(bus) == []


@pytest.mark.parametrize("bad_n", [0, -1])
def test_undo_invalid_n_raises(bad_n: int) -> None:
    bus, _doc, _fake = make_bus()
    run_four_cylinders(bus)
    with pytest.raises(InvalidHistoryError):
        bus.undo(bad_n)


def test_undo_empty_history_raises() -> None:
    bus, _doc, _fake = make_bus()
    with pytest.raises(InvalidHistoryError):
        bus.undo()


def test_redo_empty_stack_raises() -> None:
    bus, _doc, _fake = make_bus()
    with pytest.raises(InvalidHistoryError):
        bus.redo()


def test_redo_insufficient_atomic_before_any_change() -> None:
    bus, doc, fake = make_bus()
    run_four_cylinders(bus)
    bus.undo(1)
    before = (fake.reset_count, list(fake.applied), len(doc.commands), len(redo_stack(bus)))
    with pytest.raises(InvalidHistoryError):
        bus.redo(99)
    after = (fake.reset_count, list(fake.applied), len(doc.commands), len(redo_stack(bus)))
    assert before == after


def test_execute_after_undo_clears_redo_stack() -> None:
    bus, _doc, _fake = make_bus()
    run_four_cylinders(bus)
    bus.undo(1)
    bus.execute("demo.ping", {})
    assert redo_stack(bus) == []
    with pytest.raises(InvalidHistoryError):
        bus.redo()


def test_execute_failure_restores_state_and_discards_uncommitted_notifications() -> None:
    reg, handlers, fake = make_assembly()
    doc = Document(reg)
    handlers["demo.a"] = PartialFailureHandler(doc)
    bus = CommandBus(doc, reg, fake, handlers)
    bus.execute("feature.cylinder", {"radius": 1.0, "height": 2.0})
    bus.undo()
    doc.set_metadata("part_name", "saved")
    doc.add_named_group(NamedGroup("saved"))
    doc.mark_clean()
    post_events: list[Mapping[str, object]] = []
    pre_events: list[object] = []
    metadata_events: list[object] = []
    group_events: list[object] = []
    rebuild_events: list[object] = []
    doc.events.subscribe("post_command", post_events.append)
    doc.events.subscribe("pre_command", pre_events.append)
    doc.events.subscribe("metadata_changed", metadata_events.append)
    doc.events.subscribe("named_group_added", group_events.append)
    doc.events.subscribe("geometry_rebuilt", rebuild_events.append)

    with pytest.raises(RuntimeError, match="handler failed after mutation"):
        bus.execute("demo.a", {})

    assert doc.commands == ()
    assert doc.metadata["part_name"] == "saved"
    assert doc.named_groups == {"saved": NamedGroup("saved")}
    assert doc.is_dirty is False
    assert fake.applied == []
    assert post_events == []
    assert pre_events == [{"command_id": "demo.a", "command_version": 1}]
    assert metadata_events == []
    assert group_events == []
    assert len(rebuild_events) == 1
    assert bus.is_healthy is True
    assert len(redo_stack(bus)) == 1


def make_two_cylinder_doc_bus() -> tuple[CommandBus, Document, FakeKernel]:
    """Document preloaded with TWO hand-written cylinder commands (ordinal 0/1)."""
    reg, handlers, fake = make_assembly()
    cmds = [
        ExecutedCommand(
            id="feature.cylinder",
            version=1,
            params={"radius": 1.0, "height": 2.0},
            ordinal=0,
            timestamp_utc="2026-01-01T00:00:00+00:00",
            confirmed_by=None,
        ),
        ExecutedCommand(
            id="feature.cylinder",
            version=1,
            params={"radius": 2.0, "height": 2.0},
            ordinal=1,
            timestamp_utc="2026-01-02T00:00:00+00:00",
            confirmed_by=None,
        ),
    ]
    doc = Document(reg, commands=cmds)
    return CommandBus(doc, reg, fake, handlers), doc, fake


def test_operation_undo_restores_revision_and_redo_keeps_original_audit() -> None:
    bus, doc, fake = make_two_cylinder_doc_bus()
    before = doc.commands
    bus.edit_and_replay(0, {"radius": 3.0, "height": 2.0}, "tester", "revision")
    amended = doc.commands
    revision = doc.revision
    doc.mark_clean()

    bus.undo_operation()

    assert doc.commands == before
    assert fake.applied[0][1]["radius"] == 1.0
    assert doc.is_dirty
    assert doc.revision == revision + 1
    bus.redo_operation()
    assert doc.commands == amended
    assert fake.applied[0][1]["radius"] == 3.0
    assert doc.revision == revision + 2


def test_operation_order_crosses_loaded_history_and_redoes_in_order() -> None:
    bus, doc, _fake = make_two_cylinder_doc_bus()
    bus.edit_and_replay(0, {"radius": 3.0, "height": 2.0}, "tester", "revision")
    bus.execute("feature.cylinder", {"radius": 4.0, "height": 2.0})
    final = doc.commands
    bus.undo_operation()
    bus.undo_operation()
    bus.undo_operation()
    assert len(doc.commands) == 1
    assert doc.commands[0].params["radius"] == 1.0
    bus.redo_operation()
    bus.redo_operation()
    bus.redo_operation()
    assert doc.commands == final


def test_operation_undo_refuses_stale_document_revision() -> None:
    bus, doc, _fake = make_two_cylinder_doc_bus()
    bus.edit_and_replay(0, {"radius": 3.0, "height": 2.0}, "tester", "revision")
    doc.set_metadata("part_name", "preserve me")
    before = doc.commands
    with pytest.raises(InvalidHistoryError):
        bus.undo_operation()
    assert doc.commands == before
    assert doc.metadata["part_name"] == "preserve me"


def test_identity_only_session_replacement_preserves_operation_undo() -> None:
    bus, doc, _fake = make_two_cylinder_doc_bus()
    original = doc.commands
    bus.edit_and_replay(0, {"radius": 3.0, "height": 2.0}, "tester", "revision")
    registry, _handlers, _kernel = make_assembly()
    replacement = Document(registry, commands=doc.commands)
    replacement_bus = bus.copy_for_document(replacement)

    replacement_bus.undo_operation()

    assert replacement.commands == original
    assert doc.commands[0].params["radius"] == 3.0


def test_gui_redo_accepts_existing_legacy_redo_after_command_level_undo() -> None:
    bus, doc, _fake = make_two_cylinder_doc_bus()
    original = doc.commands
    bus.undo()

    bus.redo_operation()

    assert doc.commands == original
    bus.undo_operation()
    assert len(doc.commands) == 1


def test_failed_operation_undo_rolls_back_and_can_be_retried() -> None:
    bus, doc, fake = make_two_cylinder_doc_bus()
    bus.edit_and_replay(0, {"radius": 3.0, "height": 2.0}, "tester", "revision")
    amended = doc.commands
    doc.mark_clean()
    revision = doc.revision
    fake.fail_when = lambda _n, _cid, params: (
        GeometryBuildError("restore failed") if params.get("radius") == 1.0 else None
    )

    with pytest.raises(GeometryBuildError):
        bus.undo_operation()

    assert doc.commands == amended
    assert not doc.is_dirty
    assert doc.revision == revision
    assert fake.applied[0][1]["radius"] == 3.0
    fake.fail_when = None
    bus.undo_operation()
    assert doc.commands[0].params["radius"] == 1.0


def test_operation_undo_recovery_failure_marks_bus_unhealthy() -> None:
    bus, doc, fake = make_two_cylinder_doc_bus()
    bus.edit_and_replay(0, {"radius": 3.0, "height": 2.0}, "tester", "revision")
    amended = doc.commands
    fake.fail_when = lambda _n, _cid, _params: GeometryBuildError("kernel unavailable")

    with pytest.raises(ReplayDuringRollbackError):
        bus.undo_operation()

    assert doc.commands == amended
    assert not bus.is_healthy
    with pytest.raises(ReplayDuringRollbackError):
        bus.redo_operation()


def test_operation_redo_history_limit_does_not_discard_recoverable_steps() -> None:
    bus, doc, _fake = make_bus()
    for _ in range(101):
        bus.execute("demo.ping", {})
    for _ in range(100):
        bus.undo_operation()
    before = doc.commands

    with pytest.raises(InvalidHistoryError):
        bus.undo_operation()

    assert doc.commands == before
    for _ in range(100):
        bus.redo_operation()
    assert len(doc.commands) == 101


def test_command_submitted_by_commit_listener_keeps_operation_order() -> None:
    bus, doc, _fake = make_bus()

    def submit_followup(payload: Mapping[str, object]) -> None:
        if payload.get("command_id") == "demo.a":
            bus.execute("demo.b", {})

    doc.events.subscribe("post_command", submit_followup)
    bus.execute("demo.a", {})
    assert [command.id for command in doc.commands] == ["demo.a", "demo.b"]

    bus.undo_operation()
    assert [command.id for command in doc.commands] == ["demo.a"]
    bus.undo_operation()
    assert not doc.commands


def test_command_submitted_by_undo_listener_follows_undone_operation() -> None:
    bus, doc, _fake = make_bus()
    bus.execute("demo.a", {})
    triggered = False

    def submit_followup(_payload: Mapping[str, object]) -> None:
        nonlocal triggered
        if not triggered:
            triggered = True
            bus.execute("demo.b", {})

    doc.events.subscribe("geometry_rebuilt", submit_followup)
    bus.undo_operation()
    assert [command.id for command in doc.commands] == ["demo.b"]
    bus.undo_operation()
    assert not doc.commands
    bus.redo_operation()
    assert [command.id for command in doc.commands] == ["demo.b"]
    with pytest.raises(InvalidHistoryError):
        bus.redo_operation()


def test_edit_and_replay_success_amends_and_rebuilds() -> None:
    bus, doc, fake = make_two_cylinder_doc_bus()
    amended_events: list[object] = []
    event_order: list[str] = []

    def record_amendment(_payload: object) -> None:
        event_order.append("amended")

    def record_rebuild(_payload: object) -> None:
        event_order.append("rebuilt")

    doc.events.subscribe("command_amended", amended_events.append)
    doc.events.subscribe("command_amended", record_amendment)
    doc.events.subscribe("geometry_rebuilt", record_rebuild)
    ts_before = doc.commands[0].timestamp_utc
    bus.edit_and_replay(0, {"radius": 3.0, "height": 2.0}, "cli-local", "fix radius")
    assert fake.applied[0][1]["radius"] == 3.0
    assert len(doc.commands[0].amendments) == 1
    assert doc.commands[0].amendments[0].from_params == {"radius": 1.0, "height": 2.0}
    assert doc.commands[0].timestamp_utc == ts_before
    assert len(amended_events) == 1
    assert event_order == ["amended", "rebuilt"]


def test_edit_and_replay_invalid_params_leaves_all_untouched() -> None:
    bus, doc, fake = make_two_cylinder_doc_bus()
    amended_events: list[object] = []
    doc.events.subscribe("command_amended", amended_events.append)
    with pytest.raises(ValidationError):
        bus.edit_and_replay(0, {"radius": -1.0, "height": 2.0}, "cli-local", "bad")
    assert doc.commands[0].params == {"radius": 1.0, "height": 2.0}
    assert doc.commands[0].amendments == ()
    assert len(amended_events) == 0
    assert fake.applied == []


def test_edit_and_replay_geometry_failure_rolls_back() -> None:
    bus, doc, fake = make_two_cylinder_doc_bus()
    fake.fail_when = lambda n, cid, p: (
        GeometryBuildError("boom") if p.get("radius") == 99.0 else None
    )
    with pytest.raises(GeometryBuildError) as excinfo:
        bus.edit_and_replay(0, {"radius": 99.0, "height": 2.0}, "cli-local", "boom")
    assert excinfo.value.ordinal == 0
    assert doc.commands[0].params == {"radius": 1.0, "height": 2.0}
    assert doc.commands[0].amendments == ()
    assert [p["radius"] for _, p in fake.applied] == [1.0, 2.0]


def test_edit_and_replay_preserves_topology_failure_context() -> None:
    bus, doc, fake = make_two_cylinder_doc_bus()
    fail_once = True

    def fail_during_replay(
        _number: int, _command_id: str, params: dict[str, object]
    ) -> Exception | None:
        nonlocal fail_once
        if params.get("radius") == 3.0 and fail_once:
            fail_once = False
            return TopologyReferenceError(
                message="selected face disappeared",
                command_id="modify.fillet",
                reason="deleted",
                parameter_path="edges.0",
            )
        return None

    fake.fail_when = fail_during_replay

    with pytest.raises(TopologyReferenceError) as excinfo:
        bus.edit_and_replay(0, {"radius": 3.0, "height": 2.0}, "cli-local", "repair")

    error = excinfo.value
    assert error.command_id == "modify.fillet"
    assert error.ordinal == 0
    assert error.reason == "deleted"
    assert error.parameter_path == "edges.0"
    assert doc.commands[0].params == {"radius": 1.0, "height": 2.0}
    assert [params["radius"] for _, params in fake.applied] == [1.0, 2.0]


def test_edit_failure_does_not_emit_amendment_as_if_committed() -> None:
    bus, doc, fake = make_two_cylinder_doc_bus()
    doc.mark_clean()
    amended_events: list[object] = []
    rebuilt_events: list[object] = []
    doc.events.subscribe("command_amended", amended_events.append)
    doc.events.subscribe("geometry_rebuilt", rebuilt_events.append)
    fake.fail_when = lambda n, cid, p: (
        GeometryBuildError("boom") if p.get("radius") == 99.0 else None
    )

    with pytest.raises(GeometryBuildError):
        bus.edit_and_replay(0, {"radius": 99.0, "height": 2.0}, "cli-local", "boom")

    assert amended_events == []
    assert len(rebuilt_events) == 1
    assert doc.is_dirty is False


def test_edit_and_replay_rollback_failure_raises_replay_error() -> None:
    bus, _doc, fake = make_two_cylinder_doc_bus()
    fake.fail_when = lambda n, cid, p: GeometryBuildError("dead") if n >= 1 else None
    with pytest.raises(ReplayDuringRollbackError) as excinfo:
        bus.edit_and_replay(0, {"radius": 3.0, "height": 2.0}, "cli-local", "poison")
    assert isinstance(excinfo.value.original, GeometryBuildError)
    assert excinfo.value.replay_reason
    assert isinstance(excinfo.value.recovery_error, GeometryBuildError)
    assert bus.is_healthy is False
    with pytest.raises(ReplayDuringRollbackError):
        bus.undo()


def add_demo_plan_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """demo.a/demo.b are test-only ids outside AFFECTED_OBJECTS' eight builtins."""
    monkeypatch.setitem(AFFECTED_OBJECTS, "demo.a", "box_body")
    monkeypatch.setitem(AFFECTED_OBJECTS, "demo.b", "box_body")


def make_step(cid: str, params: dict[str, object]) -> PlannedCommand:
    return PlannedCommand(
        id=cid, version=1, params=params, summary_en=cid, affected_object="box_body"
    )


def test_confirmed_batch_is_one_undoable_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    add_demo_plan_keys(monkeypatch)
    bus, doc, _fake = make_bus()
    bus.execute("demo.ping", {})
    plan = Plan(steps=[make_step("demo.a", {}), make_step("demo.b", {})])
    bus.confirm_plan(plan, "tester", scope="cli")
    bus.execute_batch(plan, scope="cli")
    final = doc.commands

    bus.undo_operation()

    assert [command.id for command in doc.commands] == ["demo.ping"]
    bus.redo_operation()
    assert doc.commands == final


@pytest.mark.parametrize("actor", ["cli-local", "acceptance-test"])
def test_execute_batch_success_lifecycle(actor: str, monkeypatch: pytest.MonkeyPatch) -> None:
    add_demo_plan_keys(monkeypatch)
    bus, doc, _fake = make_bus()
    plan = Plan(steps=[make_step("demo.a", {}), make_step("demo.b", {}), make_step("demo.a", {})])
    bus.confirm_plan(plan, actor, scope="cli")
    calls: list[str] = []
    post_events: list[Mapping[str, object]] = []
    doc.events.subscribe("post_command", post_events.append)
    orig_exec, orig_done = plan.mark_executing, plan.mark_done
    monkeypatch.setattr(plan, "mark_executing", lambda: (calls.append("exec"), orig_exec()))
    monkeypatch.setattr(plan, "mark_done", lambda: (calls.append("done"), orig_done()))
    bus.execute_batch(plan, scope="cli")
    assert plan.status == "done"
    assert calls == ["exec", "done"]
    assert len(doc.commands) == 3
    assert all(cmd.confirmed_by == actor for cmd in doc.commands)
    assert [event["ordinal"] for event in post_events] == [0, 1, 2]
    assert [event["command_version"] for event in post_events] == [1, 1, 1]


def test_execute_batch_validate_failure_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    add_demo_plan_keys(monkeypatch)
    bus, doc, fake = make_bus()
    plan = Plan(
        steps=[
            make_step("demo.a", {}),
            make_step("feature.cylinder", {"radius": -1.0, "height": 2.0}),
        ]
    )
    with pytest.raises(ValidationError, match="radius"):
        bus.confirm_plan(plan, "cli-local", scope="cli")
    assert len(doc.commands) == 0
    assert fake.applied == []
    assert plan.status == "draft"


def test_execute_batch_geometry_failure_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    add_demo_plan_keys(monkeypatch)
    bus, doc, fake = make_bus()
    fake.fail_when = lambda n, cid, p: (
        GeometryBuildError("kernel boom") if cid == "feature.cylinder" else None
    )
    plan = Plan(
        steps=[
            make_step("demo.a", {}),
            make_step("demo.b", {}),
            make_step("feature.cylinder", {"radius": 1.0, "height": 2.0}),
        ]
    )
    bus.confirm_plan(plan, "cli-local", scope="cli")
    post_events: list[object] = []
    pre_events: list[object] = []
    doc.events.subscribe("post_command", post_events.append)
    doc.events.subscribe("pre_command", pre_events.append)
    with pytest.raises(BatchRollbackError) as excinfo:
        bus.execute_batch(plan, scope="cli")
    err = excinfo.value
    assert err.failed_ordinal == 2
    assert err.failed_command_id == "feature.cylinder"
    assert err.executed_ids == ("demo.a", "demo.b")
    assert len(doc.commands) == 0
    assert fake.applied == []
    assert plan.status == "failed"
    assert post_events == []
    assert pre_events == [
        {"command_id": "demo.a", "command_version": 1},
        {"command_id": "demo.b", "command_version": 1},
        {"command_id": "feature.cylinder", "command_version": 1},
    ]


def test_undo_rebuild_failure_restores_history_redo_and_geometry() -> None:
    bus, doc, fake = make_bus()
    bus.execute("feature.cylinder", {"radius": 1.0, "height": 2.0})
    bus.execute("feature.cylinder", {"radius": 2.0, "height": 2.0})
    before = doc.commands
    fake.fail_when = lambda n, cid, p: GeometryBuildError("undo replay failed") if n == 2 else None

    with pytest.raises(GeometryBuildError, match="undo replay failed"):
        bus.undo()

    assert doc.commands == before
    assert redo_stack(bus) == []
    assert [params["radius"] for _, params in fake.applied] == [1.0, 2.0]
    assert bus.is_healthy is True


def test_redo_rebuild_failure_restores_history_and_redo_stack() -> None:
    bus, doc, fake = make_bus()
    bus.execute("feature.cylinder", {"radius": 1.0, "height": 2.0})
    bus.undo()
    fake.fail_when = lambda n, cid, p: GeometryBuildError("redo replay failed") if n == 1 else None

    with pytest.raises(GeometryBuildError, match="redo replay failed"):
        bus.redo()

    assert doc.commands == ()
    assert len(redo_stack(bus)) == 1
    assert fake.applied == []
    assert bus.is_healthy is True


def test_execute_batch_rejects_draft_and_done_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    add_demo_plan_keys(monkeypatch)
    bus, doc, fake = make_bus()
    draft = Plan(steps=[make_step("demo.a", {})])
    with pytest.raises(InvalidPlanTransition):
        bus.execute_batch(draft, scope="cli")
    finished = Plan(steps=[make_step("demo.a", {})])
    finished.confirm("cli-local")
    finished.mark_executing()
    finished.mark_done()
    with pytest.raises(InvalidPlanTransition):
        bus.execute_batch(finished, scope="cli")
    assert len(doc.commands) == 0
    assert fake.applied == []


def test_execute_batch_double_failure_raises_replay_error(monkeypatch: pytest.MonkeyPatch) -> None:
    reg, handlers, fake = make_assembly()
    seed = ExecutedCommand(
        id="feature.cylinder",
        version=1,
        params={"radius": 1.0, "height": 2.0},
        ordinal=0,
        timestamp_utc="2026-01-01T00:00:00+00:00",
        confirmed_by=None,
    )
    doc = Document(reg, commands=[seed])
    bus = CommandBus(doc, reg, fake, handlers)
    fake.fail_when = lambda n, cid, p: GeometryBuildError("dead") if n >= 1 else None
    plan = Plan(
        steps=[
            make_step("feature.cylinder", {"radius": 1.0, "height": 2.0}),
            make_step("feature.cylinder", {"radius": 1.0, "height": 2.0}),
        ]
    )
    bus.confirm_plan(plan, "cli-local", scope="cli")
    with pytest.raises(ReplayDuringRollbackError) as excinfo:
        bus.execute_batch(plan, scope="cli")
    assert isinstance(excinfo.value.original, BatchRollbackError)
    assert excinfo.value.replay_reason
    assert isinstance(excinfo.value.recovery_error, GeometryBuildError)
    assert bus.is_healthy is False
    assert plan.status == "failed"


def _cylinder_plan(radius: float = 1.0) -> Plan:
    return Plan(steps=[make_step("feature.cylinder", {"radius": radius, "height": 2.0})])


def test_document_revision_is_monotonic_across_bus_mutations() -> None:
    bus, doc, _fake = make_bus()
    assert doc.revision == 0
    bus.execute("feature.cylinder", {"radius": 1.0, "height": 2.0})
    assert doc.revision == 1
    bus.undo()
    assert doc.revision == 2
    bus.redo()
    assert doc.revision == 3
    bus.edit_and_replay(0, {"radius": 2.0, "height": 2.0}, "tester", "revision")
    assert doc.revision == 4


def test_failed_batch_does_not_advance_document_revision() -> None:
    bus, doc, fake = make_bus()
    fake.fail_when = lambda _n, _cid, _params: GeometryBuildError("kernel boom")
    plan = _cylinder_plan()
    bus.confirm_plan(plan, "tester", scope="cli")
    with pytest.raises(BatchRollbackError):
        bus.execute_batch(plan, scope="cli")
    assert doc.revision == 0
    assert plan.status == "failed"


def test_failed_batch_can_be_replaced_and_reconfirmed() -> None:
    bus, doc, fake = make_bus()
    fake.fail_when = lambda _n, _cid, _params: GeometryBuildError("kernel boom")
    failed = _cylinder_plan()
    bus.confirm_plan(failed, "cli-local", scope="cli")
    with pytest.raises(BatchRollbackError):
        bus.execute_batch(failed, scope="cli")
    assert failed.status == "failed"
    assert doc.revision == 0

    fake.fail_when = None
    replacement = _cylinder_plan(radius=2.0)
    bus.confirm_plan(replacement, "cli-local", scope="cli")
    bus.execute_batch(replacement, scope="cli")

    assert replacement.status == "done"
    assert doc.revision == 1


def test_batch_requires_bus_confirmation_not_status_or_actor_alone() -> None:
    bus, doc, _fake = make_bus()
    forged = Plan(steps=_cylinder_plan().steps, status="confirmed", confirmed_by="cli-local")
    with pytest.raises(InvalidPlanTransition, match="authorization"):
        bus.execute_batch(forged, scope="cli")
    assert forged.status == "confirmed"
    assert doc.commands == ()


def test_forged_confirmation_signature_is_rejected() -> None:
    bus, doc, _fake = make_bus()
    forged = _cylinder_plan()
    forged.confirm(
        "cli-local",
        authorization=PlanConfirmation(
            plan_id=forged.plan_id,
            actor="cli-local",
            scope="cli",
            document_id=doc.document_id,
            document_revision=doc.revision,
            content_digest="0" * 64,
            nonce="forged-nonce",
            signature="forged-signature",
        ),
    )

    with pytest.raises(InvalidPlanTransition, match="invalid"):
        bus.execute_batch(forged, scope="cli")

    assert doc.commands == ()


def test_confirmation_scope_rejects_agent_authority() -> None:
    bus, _doc, _fake = make_bus()
    plan = _cylinder_plan()

    with pytest.raises(InvalidPlanTransition, match="scope"):
        bus.confirm_plan(plan, "agent", scope=cast("ConfirmationScope", "agent"))

    assert plan.status == "draft"


def test_confirmation_cannot_be_consumed_from_a_different_scope() -> None:
    bus, doc, _fake = make_bus()
    plan = _cylinder_plan()
    bus.confirm_plan(plan, "gui", scope="gui")

    with pytest.raises(InvalidPlanTransition, match="scope"):
        bus.execute_batch(plan, scope="cli")

    assert plan.status == "confirmed"
    assert doc.commands == ()
    bus.execute_batch(plan, scope="gui")
    assert plan.status == "done"
    assert doc.revision == 1


def test_confirmed_plan_rejects_changed_normalized_command_content() -> None:
    bus, doc, _fake = make_bus()
    plan = _cylinder_plan()
    bus.confirm_plan(plan, "gui", scope="gui")
    plan.steps[0].params["radius"] = 99.0

    with pytest.raises(InvalidPlanTransition, match="content"):
        bus.execute_batch(plan, scope="gui")

    assert plan.status == "cancelled"
    assert doc.commands == ()


def test_non_json_content_change_invalidates_confirmation_cleanly() -> None:
    bus, doc, _fake = make_bus()
    plan = _cylinder_plan()
    bus.confirm_plan(plan, "gui", scope="gui")
    plan.steps[0].params["radius"] = float("nan")

    with pytest.raises(InvalidPlanTransition, match="content"):
        bus.execute_batch(plan, scope="gui")

    assert plan.status == "cancelled"
    assert doc.commands == ()


def test_confirmation_binds_normalized_content_not_raw_default_spelling() -> None:
    bus, doc, _fake = make_bus()
    plan = _cylinder_plan()
    bus.confirm_plan(plan, "gui", scope="gui")
    plan.steps[0].params["center"] = [0.0, 0.0, 0.0]
    plan.steps[0].params["mode"] = "new"

    bus.execute_batch(plan, scope="gui")

    assert plan.status == "done"
    assert len(doc.commands) == 1


def test_confirmation_binds_document_identity_and_revision() -> None:
    bus, doc, _fake = make_bus()
    plan = _cylinder_plan()
    bus.confirm_plan(plan, "cli-local", scope="cli")
    original_identity = doc.document_id
    bus.execute("feature.cylinder", {"radius": 3.0, "height": 2.0})
    bus.undo()
    bus.redo()
    assert doc.revision == 3

    with pytest.raises(InvalidPlanTransition, match="document"):
        bus.execute_batch(plan, scope="cli")

    assert doc.document_id == original_identity
    assert plan.status == "cancelled"
    assert len(doc.commands) == 1


def test_direct_history_amendment_invalidates_plan_confirmation() -> None:
    bus, doc, _fake = make_bus()
    bus.execute("feature.cylinder", {"radius": 1.0, "height": 2.0})
    plan = _cylinder_plan()
    bus.confirm_plan(plan, "gui", scope="gui")
    confirmed_revision = doc.revision

    doc.replace_command_params(
        0, {"radius": 2.0, "height": 2.0}, actor="tester", reason="history edit"
    )

    assert doc.revision == confirmed_revision + 1
    with pytest.raises(InvalidPlanTransition, match="document"):
        bus.execute_batch(plan, scope="gui")
    assert plan.status == "cancelled"


def test_foreign_document_bus_rejects_an_existing_plan_grant() -> None:
    first_bus, _first_doc, _first_fake = make_bus()
    second_bus, second_doc, _second_fake = make_bus()
    plan = _cylinder_plan()
    first_bus.confirm_plan(plan, "gui", scope="gui")

    with pytest.raises(InvalidPlanTransition, match="authorization"):
        second_bus.execute_batch(plan, scope="gui")

    assert second_doc.commands == ()


def test_confirmation_grant_is_one_time_even_if_plan_is_copied() -> None:
    bus, doc, _fake = make_bus()
    plan = _cylinder_plan()
    bus.confirm_plan(plan, "gui", scope="gui")
    copied_plan = copy(plan)

    bus.execute_batch(plan, scope="gui")
    with pytest.raises(InvalidPlanTransition, match="consumed"):
        bus.execute_batch(copied_plan, scope="gui")

    assert doc.revision == 1
    assert len(doc.commands) == 1


def test_normalize_pipeline_strips_axis_key() -> None:
    """demo.sel via the Bus: normalize deletes the empty-string ``axis`` key.

    Key deletion is the spec-equivalent of "value is None" for selector
    predicates (#round7-1); the FakeKernel records what geom would receive.
    """
    reg, handlers, fake = make_assembly()
    handlers["demo.sel"] = BuiltinModelingHandler("demo.sel")
    doc = Document(reg)
    bus = CommandBus(doc, reg, fake, handlers)
    bus.execute("demo.sel", {"surface": "cylinder", "axis": ""})
    assert "axis" not in fake.applied[-1][1]


def test_normalize_params_call_sites_are_limited() -> None:
    """Bypass guard: geom never mentions normalize_params; call sites are closed.

    Text-level mentions exist in docstrings (grammar.py, __init__.py); the
    closed-set invariant targets import/call sites.
    """
    root = Path(__file__).resolve().parents[2]
    for path in (root / "src" / "mycad" / "geom").glob("*.py"):
        assert "normalize_params" not in path.read_text(encoding="utf-8"), path.name
    callers: set[str] = set()
    for path in (root / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import normalize_params" in text or "normalize_params(" in text:
            # as_posix(): the closed set below is written with "/" — str()
            # would yield "\" separators on Windows.
            callers.add(path.relative_to(root).as_posix())
    assert callers <= {
        "src/mycad/commands/validation.py",
        "src/mycad/core/bus.py",
        "src/mycad/ui/parameter_forms.py",
        "src/mycad/ui/plan_draft.py",
    }
