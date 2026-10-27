# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""P2-02: callers must not mutate committed geometry inputs or audit history."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from mycad.builtin_commands.defs import COMMAND_SCHEMA_DEFS
from mycad.builtin_commands.specs import BUILTIN_COMMAND_SPECS
from mycad.commands.registry import CommandRegistry
from mycad.core.bus import CommandBus
from mycad.core.document import CommandAmendment, Document, ExecutedCommand
from mycad.core.handlers import BuiltinModelingHandler, CommandHandler
from mycad.core.measurements import MeasurementRequest, MeasurementResult
from mycad.core.persistence import open_document, save_document

REVOLVE_VERSION = max(
    spec.version for spec in BUILTIN_COMMAND_SPECS if spec.id == "feature.revolve"
)


def _revolve_handlers() -> dict[tuple[str, int], CommandHandler]:
    return {
        ("feature.revolve", REVOLVE_VERSION): BuiltinModelingHandler(
            "feature.revolve", command_version=REVOLVE_VERSION
        )
    }


class RecordingKernel:
    """Retain handler input, exposing aliasing without requiring CAD libraries."""

    def __init__(self) -> None:
        self.applied: list[dict[str, object]] = []

    def reset(self) -> None:
        self.applied.clear()

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        self.applied.append(dict(params))

    def measure(self, request: MeasurementRequest) -> MeasurementResult:
        raise NotImplementedError(request)


def registry() -> CommandRegistry:
    result = CommandRegistry(schema_defs=COMMAND_SCHEMA_DEFS)
    for spec in BUILTIN_COMMAND_SPECS:
        result.register(spec)
    return result


def parameters(radius: float = 3.0) -> dict[str, object]:
    return {
        "profile": {"type": "circle", "radius": radius, "center": [0.0, 0.0]},
        "axis": [1.0, 0.0, 0.0],
        "angle_deg": 360.0,
        "mode": "new",
    }


def mutate_nested(params: dict[str, object]) -> None:
    cast("dict[str, object]", params["profile"])["radius"] = 99.0
    cast("list[float]", params["axis"])[0] = 99.0


def command() -> ExecutedCommand:
    return ExecutedCommand(
        id="feature.revolve",
        version=1,
        params=parameters(),
        ordinal=0,
        timestamp_utc="2026-01-01T00:00:00+00:00",
        confirmed_by="designer",
        amendments=(
            CommandAmendment(
                at="2026-01-02T00:00:00+00:00",
                actor="designer",
                from_params=parameters(2.0),
                reason="resize",
            ),
        ),
    )


@pytest.mark.parametrize("source", ["constructor", "history"])
def test_history_and_audit_have_no_external_mutable_aliases(source: str) -> None:
    original = command()
    doc = Document(registry(), commands=[original])
    exposed = original if source == "constructor" else doc.commands[0]
    mutate_nested(exposed.params)
    mutate_nested(exposed.amendments[0].from_params)
    assert doc.commands[0] == command()
    assert not doc.is_dirty


def test_amended_params_and_return_value_are_isolated() -> None:
    doc = Document(registry(), commands=[command()])
    params = parameters(4.0)
    revised = doc.replace_command_params(0, params, "designer", "wider")
    expected = parameters(4.0)
    mutate_nested(params)
    mutate_nested(revised.params)
    mutate_nested(revised.amendments[-1].from_params)
    assert doc.commands[0].params == expected
    assert doc.commands[0].amendments[-1].from_params == parameters()
    assert doc.commands[0].amendments[0] == command().amendments[0]
    assert doc.commands[0].timestamp_utc == command().timestamp_utc
    assert doc.is_dirty


def test_handler_retained_parameters_cannot_change_committed_history() -> None:
    reg = registry()
    doc = Document(reg)
    kernel = RecordingKernel()
    bus = CommandBus(doc, reg, kernel, _revolve_handlers())
    bus.execute("feature.revolve", parameters(), "designer")
    doc.mark_clean()
    mutate_nested(kernel.applied[0])
    assert doc.commands[0].params["profile"] == parameters()["profile"]
    assert doc.commands[0].params["axis"] == [1.0, 0.0, 0.0]
    assert not doc.is_dirty


def test_bus_edit_undo_redo_and_archive_keep_original_audit(tmp_path: Path) -> None:
    reg = registry()
    doc = Document(reg)
    kernel = RecordingKernel()
    handlers = _revolve_handlers()
    bus = CommandBus(doc, reg, kernel, handlers)
    bus.execute("feature.revolve", parameters(), "designer")
    original_timestamp = doc.commands[0].timestamp_utc
    params = parameters(4.0)
    bus.edit_and_replay(0, params, "designer", "wider")
    expected = doc.commands
    mutate_nested(params)
    leaked = doc.commands[0]
    bus.undo()
    mutate_nested(leaked.params)
    mutate_nested(leaked.amendments[-1].from_params)
    bus.redo()
    assert doc.commands == expected
    path = tmp_path / "part.mc.json"
    save_document(doc, path)
    reopened = open_document(path, registry=reg, kernel=RecordingKernel(), handlers=handlers)
    assert reopened.document.commands == expected
    assert reopened.document.commands[0].timestamp_utc == original_timestamp
    assert len(reopened.document.commands[0].amendments) == 1
    assert not reopened.document.is_dirty
