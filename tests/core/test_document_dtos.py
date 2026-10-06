# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DTO contract tests for mycad.core.document (audit + planning dataclasses)."""

from __future__ import annotations

import dataclasses
import typing

import pytest

from mycad.core.document import (
    AFFECTED_OBJECTS,
    AffectedObject,
    CommandAmendment,
    ExecutedCommand,
    PlannedCommand,
)
from mycad.core.exceptions import UnknownCommandError

EXPECTED_AFFECTED: tuple[str, ...] = (
    "box_body",
    "cylinder_body",
    "extruded_body",
    "revolved_body",
    "hole",
    "hole_pattern",
    "edge",
    "tool_body",
)

EXPECTED_B2: dict[str, str] = {
    "feature.box": "box_body",
    "feature.cylinder": "cylinder_body",
    "feature.extrude": "extruded_body",
    "feature.revolve": "revolved_body",
    "feature.hole": "hole",
    "feature.hole_pattern": "hole_pattern",
    "modify.fillet": "edge",
    "modify.boolean_cut": "tool_body",
}


def _planned() -> PlannedCommand:
    return PlannedCommand(
        id="feature.box",
        version=1,
        params={"length": 10},
        summary_en="Create a parametric box.",
        affected_object="box_body",
    )


def _executed() -> ExecutedCommand:
    return ExecutedCommand(
        id="feature.box",
        version=1,
        params={"length": 10},
        ordinal=0,
        timestamp_utc="2026-01-01T00:00:00+00:00",
        confirmed_by="cli-local",
    )


def test_affected_object_literal_locked_to_eight_values() -> None:
    args = typing.get_args(AffectedObject)
    assert isinstance(args, tuple)
    assert args == EXPECTED_AFFECTED
    assert set(args) == set(AFFECTED_OBJECTS.values())


def test_affected_objects_table_locked_to_b2() -> None:
    assert dict(AFFECTED_OBJECTS) == EXPECTED_B2
    assert len(set(AFFECTED_OBJECTS.values())) == 8


def test_planned_command_unknown_id_raises_unknown_command_error() -> None:
    with pytest.raises(UnknownCommandError) as exc_info:
        PlannedCommand(
            id="bogus.command",
            version=1,
            params={},
            summary_en="Not in AFFECTED_OBJECTS.",
            affected_object="box_body",
        )
    assert exc_info.value.identifier == "bogus.command"


def _assert_frozen(obj: object, attr: str, value: object) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, attr, value)


def test_executed_command_is_frozen() -> None:
    _assert_frozen(_executed(), "params", {})


def test_planned_command_is_frozen() -> None:
    _assert_frozen(_planned(), "version", 2)


def test_executed_command_amendments_default_empty_tuple() -> None:
    assert _executed().amendments == ()


def test_executed_command_audit_field_layout() -> None:
    audit_names = ["id", "version", "params", "ordinal", "timestamp_utc", "confirmed_by"]
    fields = dataclasses.fields(ExecutedCommand)
    assert [f.name for f in fields] == [*audit_names, "amendments"]
    required = [f.name for f in fields if f.default is dataclasses.MISSING]
    assert required == audit_names


def test_planned_command_field_layout() -> None:
    names = [f.name for f in dataclasses.fields(PlannedCommand)]
    assert names == ["id", "version", "params", "summary_en", "affected_object"]


def test_command_amendment_field_layout() -> None:
    names = [f.name for f in dataclasses.fields(CommandAmendment)]
    assert names == ["at", "actor", "from_params", "reason"]


def test_executed_command_carries_amendments() -> None:
    amendment = CommandAmendment(
        at="2026-01-02T00:00:00+00:00",
        actor="cli-local",
        from_params={"length": 5},
        reason="resize",
    )
    executed = ExecutedCommand(
        id="feature.box",
        version=1,
        params={"length": 10},
        ordinal=0,
        timestamp_utc="2026-01-01T00:00:00+00:00",
        confirmed_by="cli-local",
        amendments=(amendment,),
    )
    assert executed.amendments == (amendment,)
