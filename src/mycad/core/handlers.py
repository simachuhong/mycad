# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Command handler contract (T6a).

Dispatch is fixed by spec: one ``BuiltinModelingHandler`` instance is
constructed per builtin command id (T7 wires
``{cid: BuiltinModelingHandler(cid) for cid in BUILTIN_COMMAND_IDS}``);
a handler never guesses the command inside a shared stateless instance.
The Bus passes the executing command id via ``HandlerContext`` as a
second safety net; mismatch is a hard error.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from mycad.core.kernel_protocol import Kernel


@dataclass(frozen=True)
class HandlerContext:
    """Per-call context injected by the Bus on every execution."""

    kernel: Kernel
    command_id: str


@runtime_checkable
class CommandHandler(Protocol):
    """Contract for command execution behind the Bus.

    ``command_id`` is an instance attribute: each handler instance is
    bound to exactly one command id at construction time.
    """

    command_id: str

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> object | None:
        """Execute the bound command.

        Modeling handlers return None (effects via ``ctx.kernel.apply``);
        non-geometric commands may return any JSON-serializable value.
        """
        ...


class BuiltinModelingHandler:
    """Modeling handler bound to exactly one builtin command id.

    All effects flow through ``ctx.kernel.apply``; the return value is
    always None. ``ctx.command_id`` must match the bound id — the Bus
    injects it per call and a mismatch means a wiring bug.
    """

    def __init__(self, command_id: str) -> None:
        self.command_id = command_id

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> None:
        """Apply the bound command to the kernel after checking the wiring."""
        if ctx.command_id != self.command_id:
            msg = (
                f"ctx.command_id {ctx.command_id!r} does not match "
                f"handler command_id {self.command_id!r}"
            )
            raise ValueError(msg)
        ctx.kernel.apply(self.command_id, params)
