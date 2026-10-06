# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Plan state machine contract tests: six legal edges, everything else rejected."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable

import pytest

from mycad.core.document import PlannedCommand
from mycad.core.exceptions import InvalidPlanTransition
from mycad.core.plan import Plan, PlanStatus


def _step() -> PlannedCommand:
    return PlannedCommand(
        id="feature.box",
        version=1,
        params={"length": 10},
        summary_en="Create a parametric box.",
        affected_object="box_body",
    )


def _plan_in(status: PlanStatus) -> Plan:
    return Plan([_step()], status=status)


_ACTIONS: dict[str, Callable[[Plan], None]] = {
    "confirm": lambda plan: plan.confirm("cli-local"),
    "mark_executing": lambda plan: plan.mark_executing(),
    "mark_done": lambda plan: plan.mark_done(),
    "mark_failed": lambda plan: plan.mark_failed(),
    "cancel": lambda plan: plan.cancel(),
}

TERMINAL_STATUSES: list[PlanStatus] = ["done", "failed", "cancelled"]

_ILLEGAL_NON_TERMINAL: list[tuple[PlanStatus, str]] = [
    ("draft", "mark_executing"),
    ("draft", "mark_done"),
    ("draft", "mark_failed"),
    ("confirmed", "confirm"),
    ("confirmed", "mark_done"),
    ("confirmed", "mark_failed"),
    ("executing", "confirm"),
    ("executing", "mark_executing"),
    ("executing", "cancel"),
]


def test_plan_field_order_and_defaults() -> None:
    names = [f.name for f in dataclasses.fields(Plan)]
    assert names == ["steps", "status", "plan_id", "confirmed_by"]
    by_name = {f.name: f for f in dataclasses.fields(Plan)}
    assert by_name["status"].default == "draft"
    assert by_name["confirmed_by"].default is None
    assert by_name["plan_id"].default_factory is not None


def test_plan_steps_only_construction() -> None:
    plan = Plan([_step()])
    assert plan.status == "draft"
    assert plan.confirmed_by is None
    assert re.fullmatch(r"[0-9a-f]{32}", plan.plan_id)


def test_edge_draft_to_confirmed() -> None:
    plan = _plan_in("draft")
    plan.confirm("cli-local")
    assert plan.status == "confirmed"
    assert plan.confirmed_by == "cli-local"


def test_confirm_with_empty_actor_is_rejected_atomically() -> None:
    plan = _plan_in("draft")
    with pytest.raises(ValueError):
        plan.confirm("")
    assert plan.status == "draft"
    assert plan.confirmed_by is None


def test_edge_draft_to_cancelled() -> None:
    plan = _plan_in("draft")
    plan.cancel()
    assert plan.status == "cancelled"
    assert plan.confirmed_by is None


def test_edge_confirmed_to_executing() -> None:
    plan = _plan_in("confirmed")
    plan.mark_executing()
    assert plan.status == "executing"


def test_edge_confirmed_to_cancelled() -> None:
    plan = _plan_in("confirmed")
    plan.cancel()
    assert plan.status == "cancelled"


def test_edge_executing_to_done() -> None:
    plan = _plan_in("executing")
    plan.mark_done()
    assert plan.status == "done"


def test_edge_executing_to_failed() -> None:
    plan = _plan_in("executing")
    plan.mark_failed()
    assert plan.status == "failed"


@pytest.mark.parametrize("action", list(_ACTIONS))
@pytest.mark.parametrize("status", TERMINAL_STATUSES)
def test_terminal_state_rejects_every_action(status: PlanStatus, action: str) -> None:
    plan = _plan_in(status)
    with pytest.raises(InvalidPlanTransition):
        _ACTIONS[action](plan)
    assert plan.status == status


@pytest.mark.parametrize(("status", "action"), _ILLEGAL_NON_TERMINAL)
def test_illegal_non_terminal_transition_rejected(status: PlanStatus, action: str) -> None:
    plan = _plan_in(status)
    with pytest.raises(InvalidPlanTransition):
        _ACTIONS[action](plan)
    assert plan.status == status


def test_plan_id_is_read_only_after_construction() -> None:
    plan = _plan_in("draft")
    original = plan.plan_id
    with pytest.raises(AttributeError):
        plan.plan_id = "overwritten"
    assert plan.plan_id == original
