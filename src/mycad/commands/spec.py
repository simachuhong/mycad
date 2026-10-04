# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Command specification model (T3 command framework).

``CommandSpec`` is the single source of truth shared by the CLI, the future
UI and the Agent tool layer: a stable command id, a version, an English CLI
summary, a Chinese UI label (phase-0 data only), a JSON-Schema (fixed
subset) parameter schema and the CLI verb aliases.

Field order is part of the public contract: ``undo_compensation`` is the
last field and carries its default, and it accepts exactly one value —
``"history_replay"`` — per the 技术路线 §7 undo-compensation baseline
(per-command inverse operations are explicitly out of scope for Phase 0).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from mycad.core.exceptions import ValidationError

UndoCompensation = Literal["history_replay"]


@dataclass(frozen=True)
class CliSyntax:
    """CLI-side syntax facts for one command.

    ``verb_aliases``: accepted verbs, first one is the canonical form used
    by ``to_cli``. ``positional``: names of positional parameters
    (reserved; every phase-0 command uses ``key=value`` form only).
    """

    verb_aliases: tuple[str, ...]
    positional: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandSpec:
    """Immutable description of one MyCAD command (Phase 0)."""

    id: str
    version: int
    summary_en: str
    label_zh: str
    params_schema: Mapping[str, object]
    cli: CliSyntax
    undo_compensation: UndoCompensation = "history_replay"

    def __post_init__(self) -> None:
        if self.undo_compensation != "history_replay":
            raise ValidationError(
                "undo_compensation must be 'history_replay' "
                f"(got {self.undo_compensation!r}); per-command inverse "
                "operations are not part of Phase 0"
            )


__all__ = ["CliSyntax", "CommandSpec", "UndoCompensation"]
