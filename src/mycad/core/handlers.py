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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

from mycad.core.bound_refs import is_bound_hole
from mycad.core.command_identity import ExecutionContext
from mycad.core.exceptions import TopologyReferenceError
from mycad.core.kernel_protocol import BoundFaceKernel, ContextualKernel, Kernel


@dataclass(frozen=True)
class HandlerContext:
    """Per-call context injected by the Bus on every execution."""

    kernel: Kernel
    command_id: str
    command_version: int = 1
    instance_id: str | None = None


@runtime_checkable
class CommandHandler(Protocol):
    """Contract for command execution behind the Bus.

    ``command_id`` is an instance attribute: each handler instance is
    bound to exactly one command id at construction time.

    A handler recorded in document history can be called again during load,
    undo, redo, edit, or failure recovery. It must therefore be deterministic
    and replay-safe. Effects must be represented by ``ctx.kernel.apply``;
    sending messages, writing files, or changing other external state cannot
    be undone by rebuilding geometry and is outside the Bus rollback guarantee.
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

    def __init__(self, command_id: str, command_version: int = 1) -> None:
        self.command_id = command_id
        self.command_version = command_version

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> None:
        """Apply the bound command to the kernel after checking the wiring."""
        if ctx.command_id != self.command_id:
            msg = (
                f"ctx.command_id {ctx.command_id!r} does not match "
                f"handler command_id {self.command_id!r}"
            )
            raise ValueError(msg)
        if ctx.command_version != self.command_version:
            raise ValueError(
                f"ctx.command_version {ctx.command_version!r} does not match "
                f"handler command_version {self.command_version!r}"
            )
        if is_bound_hole(self.command_id, params) and (
            ctx.instance_id is None or not isinstance(ctx.kernel, BoundFaceKernel)
        ):
            raise TopologyReferenceError(
                "kernel does not support identity-bound faces",
                command_id=self.command_id,
                reason="unsupported-kernel",
                parameter_path="target_face",
            )
        if isinstance(ctx.kernel, ContextualKernel):
            ctx.kernel.apply_with_context(
                self.command_id,
                params,
                ExecutionContext(self.command_id, self.command_version, ctx.instance_id),
            )
        else:
            ctx.kernel.apply(self.command_id, params)


def resolve_handler(
    handlers: Mapping[str, CommandHandler] | Mapping[tuple[str, int], CommandHandler],
    command_id: str,
    version: int,
    available_versions: Sequence[int],
) -> CommandHandler | None:
    """Resolve a handler without allowing an id-only binding across versions.

    Tuple keys are the version-aware contract. A legacy id-only mapping stays
    valid for a command with exactly one registered version.
    """
    handler = cast("Mapping[tuple[str, int], CommandHandler]", handlers).get((command_id, version))
    if handler is not None:
        return handler
    if tuple(available_versions) == (version,):
        return cast("Mapping[str, CommandHandler]", handlers).get(command_id)
    return None
