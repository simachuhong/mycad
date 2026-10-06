# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Plan aggregate and state machine (six states, exactly six legal edges).

Single-threaded by design (no write lock — see the phase 0 plan's "Must
NOT do" list). No LLM / network code: the transition methods are pure
in-place state changes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from mycad.core.document import PlannedCommand
from mycad.core.exceptions import InvalidPlanTransition

PlanStatus = Literal["draft", "confirmed", "executing", "done", "failed", "cancelled"]

# The sole transition authority: exactly six legal edges. Every (status,
# action) pair outside this table — including anything from the terminal
# states — raises InvalidPlanTransition.
_LEGAL: dict[tuple[PlanStatus, str], PlanStatus] = {
    ("draft", "confirm"): "confirmed",
    ("draft", "cancel"): "cancelled",
    ("confirmed", "mark_executing"): "executing",
    ("confirmed", "cancel"): "cancelled",
    ("executing", "mark_done"): "done",
    ("executing", "mark_failed"): "failed",
}


@dataclass
class Plan:
    """A batch of planned commands driven through a six-state lifecycle.

    ``steps`` is first and ``status`` defaults to ``"draft"`` so the CLI's
    ``Plan(steps)`` construction form is valid (#round11-4). ``plan_id``
    auto-generates as a 32-char lowercase hex and is read-only afterwards.
    """

    steps: list[PlannedCommand]
    status: PlanStatus = "draft"
    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    confirmed_by: str | None = None

    def __setattr__(self, name: str, value: object) -> None:
        if name == "plan_id" and "plan_id" in self.__dict__:
            raise AttributeError("plan_id is read-only after construction")
        object.__setattr__(self, name, value)

    def _transition(self, action: str) -> None:
        if (self.status, action) not in _LEGAL:
            raise InvalidPlanTransition(self.status, action)
        self.status = _LEGAL[(self.status, action)]

    def confirm(self, actor: str) -> None:
        """Edge 1: draft -> confirmed; requires a non-empty ``actor``."""
        if not actor:
            raise ValueError("confirm requires a non-empty actor")
        self._transition("confirm")
        self.confirmed_by = actor

    def mark_executing(self) -> None:
        """Edge 3: confirmed -> executing."""
        self._transition("mark_executing")

    def mark_done(self) -> None:
        """Edge 5: executing -> done."""
        self._transition("mark_done")

    def mark_failed(self) -> None:
        """Edge 6: executing -> failed."""
        self._transition("mark_failed")

    def cancel(self) -> None:
        """Edges 2 and 4: draft or confirmed -> cancelled."""
        self._transition("cancel")
