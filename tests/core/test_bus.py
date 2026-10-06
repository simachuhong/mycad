# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""CommandBus tests (T6c): dispatch, undo/redo, edit replay, batch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
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
    UnknownCommandError,
    ValidationError,
)
from mycad.core.handlers import BuiltinModelingHandler, CommandHandler, HandlerContext
from mycad.core.plan import Plan

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


def test_dispatch_lock_echo_ids() -> None:
    bus, _doc, _fake = make_bus()
    assert bus.execute("demo.a", {}) == "demo.a"
    assert bus.execute("demo.b", {}) == "demo.b"


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


def test_edit_and_replay_success_amends_and_rebuilds() -> None:
    bus, doc, fake = make_two_cylinder_doc_bus()
    amended_events: list[object] = []
    doc.events.subscribe("command_amended", amended_events.append)
    ts_before = doc.commands[0].timestamp_utc
    bus.edit_and_replay(0, {"radius": 3.0, "height": 2.0}, "cli-local", "fix radius")
    assert fake.applied[0][1]["radius"] == 3.0
    assert len(doc.commands[0].amendments) == 1
    assert doc.commands[0].amendments[0].from_params == {"radius": 1.0, "height": 2.0}
    assert doc.commands[0].timestamp_utc == ts_before
    assert len(amended_events) == 1


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


def test_edit_and_replay_rollback_failure_raises_replay_error() -> None:
    bus, _doc, fake = make_two_cylinder_doc_bus()
    fake.fail_when = lambda n, cid, p: GeometryBuildError("dead") if n >= 1 else None
    with pytest.raises(ReplayDuringRollbackError) as excinfo:
        bus.edit_and_replay(0, {"radius": 3.0, "height": 2.0}, "cli-local", "poison")
    assert isinstance(excinfo.value.original, GeometryBuildError)
    assert excinfo.value.replay_reason


def add_demo_plan_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """demo.a/demo.b are test-only ids outside AFFECTED_OBJECTS' eight builtins."""
    monkeypatch.setitem(AFFECTED_OBJECTS, "demo.a", "box_body")
    monkeypatch.setitem(AFFECTED_OBJECTS, "demo.b", "box_body")


def make_step(cid: str, params: dict[str, object]) -> PlannedCommand:
    return PlannedCommand(
        id=cid, version=1, params=params, summary_en=cid, affected_object="box_body"
    )


@pytest.mark.parametrize("actor", ["cli-local", "acceptance-test"])
def test_execute_batch_success_lifecycle(actor: str, monkeypatch: pytest.MonkeyPatch) -> None:
    add_demo_plan_keys(monkeypatch)
    bus, doc, _fake = make_bus()
    plan = Plan(steps=[make_step("demo.a", {}), make_step("demo.b", {}), make_step("demo.a", {})])
    plan.confirm(actor)
    calls: list[str] = []
    orig_exec, orig_done = plan.mark_executing, plan.mark_done
    monkeypatch.setattr(plan, "mark_executing", lambda: (calls.append("exec"), orig_exec()))
    monkeypatch.setattr(plan, "mark_done", lambda: (calls.append("done"), orig_done()))
    bus.execute_batch(plan)
    assert plan.status == "done"
    assert calls == ["exec", "done"]
    assert len(doc.commands) == 3
    assert all(cmd.confirmed_by == actor for cmd in doc.commands)


def test_execute_batch_validate_failure_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    add_demo_plan_keys(monkeypatch)
    bus, doc, fake = make_bus()
    plan = Plan(
        steps=[
            make_step("demo.a", {}),
            make_step("feature.cylinder", {"radius": -1.0, "height": 2.0}),
        ]
    )
    plan.confirm("cli-local")
    with pytest.raises(BatchRollbackError) as excinfo:
        bus.execute_batch(plan)
    err = excinfo.value
    assert err.failed_ordinal == 1
    assert err.failed_command_id == "feature.cylinder"
    assert "radius" in err.reason
    assert err.executed_ids == ("demo.a",)
    assert len(doc.commands) == 0
    assert fake.applied == []
    assert plan.status == "failed"


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
    plan.confirm("cli-local")
    with pytest.raises(BatchRollbackError) as excinfo:
        bus.execute_batch(plan)
    err = excinfo.value
    assert err.failed_ordinal == 2
    assert err.failed_command_id == "feature.cylinder"
    assert err.executed_ids == ("demo.a", "demo.b")
    assert len(doc.commands) == 0
    assert fake.applied == []
    assert plan.status == "failed"


def test_execute_batch_rejects_draft_and_done_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    add_demo_plan_keys(monkeypatch)
    bus, doc, fake = make_bus()
    draft = Plan(steps=[make_step("demo.a", {})])
    with pytest.raises(InvalidPlanTransition):
        bus.execute_batch(draft)
    finished = Plan(steps=[make_step("demo.a", {})])
    finished.confirm("cli-local")
    finished.mark_executing()
    finished.mark_done()
    with pytest.raises(InvalidPlanTransition):
        bus.execute_batch(finished)
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
    plan.confirm("cli-local")
    with pytest.raises(ReplayDuringRollbackError) as excinfo:
        bus.execute_batch(plan)
    assert isinstance(excinfo.value.original, BatchRollbackError)
    assert excinfo.value.replay_reason
    assert plan.status == "failed"


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
            callers.add(str(path.relative_to(root)))
    assert callers <= {"src/mycad/commands/validation.py", "src/mycad/core/bus.py"}
