# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""CommandSpec / CliSyntax contract tests (T3-A).

Pins the frozen dataclass field order (undo_compensation last, defaulted),
the ``"history_replay"``-only undo policy, and CliSyntax defaults.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Literal, cast

import pytest

from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.core.exceptions import ValidationError


def _params_schema() -> Mapping[str, object]:
    return {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def _spec(**overrides: object) -> CommandSpec:
    """Build a minimal valid spec; overrides replace named fields."""
    values: dict[str, object] = {
        "id": "demo.ping",
        "version": 1,
        "summary_en": "Ping the demo registry",
        "label_zh": "演示",
        "params_schema": _params_schema(),
        "cli": CliSyntax(verb_aliases=("ping",)),
    }
    values.update(overrides)
    undo = values.pop("undo_compensation", "history_replay")
    return CommandSpec(
        id=cast(str, values["id"]),
        version=cast(int, values["version"]),
        summary_en=cast(str, values["summary_en"]),
        label_zh=cast(str, values["label_zh"]),
        params_schema=cast("Mapping[str, object]", values["params_schema"]),
        cli=cast(CliSyntax, values["cli"]),
        undo_compensation=cast(Literal["history_replay"], undo),
    )


def test_field_order_is_exact_and_undo_last() -> None:
    names = [f.name for f in dataclasses.fields(CommandSpec)]
    assert names == [
        "id",
        "version",
        "summary_en",
        "label_zh",
        "params_schema",
        "cli",
        "undo_compensation",
    ]


def test_undo_compensation_defaults_to_history_replay() -> None:
    assert _spec().undo_compensation == "history_replay"


def test_undo_compensation_rejects_any_other_value() -> None:
    bogus = cast(Literal["history_replay"], "inverse_geometry")
    with pytest.raises(ValidationError, match="history_replay"):
        _spec(undo_compensation=bogus)


def test_spec_is_frozen() -> None:
    spec = _spec()
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.__setattr__("version", 2)


def test_label_zh_is_carried_as_data() -> None:
    assert _spec(label_zh="圆柱体").label_zh == "圆柱体"


def test_cli_syntax_positional_defaults_empty() -> None:
    syntax = CliSyntax(verb_aliases=("cylinder", "cyl"))
    assert syntax.verb_aliases == ("cylinder", "cyl")
    assert syntax.positional == ()


def test_cli_syntax_is_frozen() -> None:
    syntax = CliSyntax(verb_aliases=("cut",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        syntax.__setattr__("verb_aliases", ("slice",))
