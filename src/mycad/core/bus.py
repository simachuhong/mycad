# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""CommandBus (T6c): the sole execution pipeline for every command.

Single-threaded document model (no write lock — phase 0 "Must NOT do").
The Bus is the ONLY call site of the validate -> normalize pipeline
(#round11-2): execute, execute_batch and open-replay all funnel through
``_execute_one`` with the constructor-injected ``registry.schema_defs``,
so handlers and geom only ever receive already-normalized dicts.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from mycad.core.document import Document, ExecutedCommand
from mycad.core.exceptions import (
    BatchRollbackError,
    GeometryBuildError,
    InvalidHistoryError,
    ReplayDuringRollbackError,
    TopologyReferenceError,
    UnknownCommandError,
)
from mycad.core.handlers import CommandHandler, HandlerContext
from mycad.core.kernel_protocol import Kernel
from mycad.core.plan import Plan

if TYPE_CHECKING:
    from mycad.commands.registry import CommandRegistry


class CommandBus:
    """Single-threaded command bus driving document history and geometry."""

    def __init__(
        self,
        document: Document,
        registry: CommandRegistry,
        kernel: Kernel,
        handlers: Mapping[str, CommandHandler],
    ) -> None:
        self._document = document
        self._registry = registry
        self._kernel = kernel
        self._handlers: dict[str, CommandHandler] = dict(handlers)
        self._redo_stack: list[ExecutedCommand] = []
        # T6b's Bus-facing internals, bound once (documented "Bus-side"
        # single write paths); constant getattr bridges the conflict between
        # ruff B009 and pyright's reportPrivateUsage (direct access errors).
        self._append_command = cast(
            "Callable[[ExecutedCommand], None]",
            getattr(document, "_append_command"),  # noqa: B009
        )
        self._pop_commands = cast(
            "Callable[[int], list[ExecutedCommand]]",
            getattr(document, "_pop_commands"),  # noqa: B009
        )
        self._restore_commands = cast(
            "Callable[[list[ExecutedCommand]], None]",
            getattr(document, "_restore_commands"),  # noqa: B009
        )
        self._restore_metadata = cast(
            "Callable[[Mapping[str, str]], None]",
            getattr(document, "_restore_metadata"),  # noqa: B009
        )

    def execute(
        self, command_id: str, params: Mapping[str, object], confirmed_by: str | None = None
    ) -> object | None:
        """Execute one command; any success clears the redo stack."""
        result = self._execute_one(command_id, params, confirmed_by, record=True)
        self._redo_stack.clear()
        return result

    def _execute_one(
        self,
        command_id: str,
        params: Mapping[str, object],
        confirmed_by: str | None,
        *,
        record: bool = True,
    ) -> object | None:
        """The ONE pipeline: validate -> normalize -> handler (fixed order)."""
        from mycad.commands.validation import normalize_params, validate_params

        spec = self._registry.get(command_id)
        handler = self._handlers.get(command_id)
        if handler is None:
            raise UnknownCommandError(
                f"no handler registered for {command_id!r}",
                command_id=command_id,
                identifier=command_id,
            )
        validated = validate_params(spec, dict(params), defs=self._registry.schema_defs)
        normalized = normalize_params(validated)
        if record:
            self._document.events.emit("pre_command", {"command_id": command_id})
        ctx = HandlerContext(kernel=self._kernel, command_id=command_id)
        result = handler.handle(normalized, ctx)
        if record:
            self._append_command(
                ExecutedCommand(
                    id=command_id,
                    version=spec.version,
                    params=dict(normalized),
                    ordinal=len(self._document.commands),
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    confirmed_by=confirmed_by,
                )
            )
            self._document.events.emit(
                "post_command",
                {"command_id": command_id, "ordinal": len(self._document.commands) - 1},
            )
        return result

    def _validate_n(self, action: str, n: int) -> None:
        """``n`` must be an integer >= 1 (CLI parsing is T10's concern)."""
        # Runtime check of untrusted input; cast keeps it non-redundant for pyright.
        if not isinstance(cast("object", n), int) or n < 1:
            raise InvalidHistoryError(f"{action}: n must be an integer >= 1, got {n!r}")

    def undo(self, n: int = 1) -> None:
        """Pop the trailing ``n`` commands onto the redo stack; rebuild once."""
        self._validate_n("undo", n)
        if n > len(self._document.commands):
            raise InvalidHistoryError(
                f"undo: history has {len(self._document.commands)} commands, requested {n}"
            )
        popped = self._pop_commands(n)
        self._redo_stack.extend(reversed(popped))
        self._rebuild()

    def redo(self, n: int = 1) -> None:
        """Pop ``n`` commands back from the redo stack; rebuild once."""
        self._validate_n("redo", n)
        if n > len(self._redo_stack):
            raise InvalidHistoryError(
                f"redo: redo stack has {len(self._redo_stack)} commands, requested {n}"
            )
        popped = self._redo_stack[-n:]
        del self._redo_stack[-n:]
        for cmd in reversed(popped):
            self._append_command(cmd)
        self._rebuild()

    def _rebuild(self) -> None:
        """Reset the kernel, replay the history (record=False), notify once."""
        self._kernel.reset()
        for cmd in self._document.commands:
            try:
                self._execute_one(cmd.id, cmd.params, cmd.confirmed_by, record=False)
            except GeometryBuildError as exc:
                if exc.ordinal is None:
                    raise type(exc)(str(exc), ordinal=cmd.ordinal) from exc
                raise
            except TopologyReferenceError as exc:
                if exc.ordinal is None:
                    raise type(exc)(str(exc), ordinal=cmd.ordinal) from exc
                raise
        self._document.events.emit("geometry_rebuilt")

    def edit_and_replay(
        self, ordinal: int, params: Mapping[str, object], actor: str, reason: str
    ) -> None:
        """Edit one history entry, then rebuild geometry from the revised history.

        On success the redo stack is cleared and the document stays dirty:
        an edit IS an unsaved change (the spec's "clear redo stack, dirty
        flag" wording is executed as "mark dirty"). ``geometry_rebuilt`` is
        emitted by ``_rebuild`` itself, never re-emitted here.
        """
        commands_snapshot = copy.deepcopy(list(self._document.commands))
        metadata_snapshot = self._document.metadata_snapshot()
        self._document.replace_command_params(ordinal, params, actor, reason)
        try:
            self._rebuild()
        except (GeometryBuildError, TopologyReferenceError) as original:
            self._restore_commands(commands_snapshot)
            self._restore_metadata(metadata_snapshot)
            try:
                self._rebuild()
            except Exception as rb:
                raise ReplayDuringRollbackError(
                    f"edit_and_replay rollback replay failed: {rb}",
                    original=original,
                    replay_reason=str(rb),
                ) from rb
            raise type(original)(str(original), ordinal=ordinal) from original
        self._redo_stack.clear()

    def execute_batch(self, plan: Plan) -> None:
        """Execute a confirmed ``plan`` atomically; any failure rolls it back.

        Every step goes through the same ``_execute_one`` pipeline as single
        commands. On failure the document is restored, ``plan.mark_failed()``
        runs BEFORE the raise, and ``BatchRollbackError`` carries the
        0-based ``failed_ordinal``, the failing id, the reason and the ids
        of already-executed steps.
        """
        plan.mark_executing()
        commands_snapshot = copy.deepcopy(list(self._document.commands))
        metadata_snapshot = self._document.metadata_snapshot()
        executed_ids: list[str] = []
        for index, step in enumerate(plan.steps):
            try:
                self._execute_one(step.id, step.params, plan.confirmed_by, record=True)
                executed_ids.append(step.id)
            except Exception as exc:
                self._restore_commands(commands_snapshot)
                self._restore_metadata(metadata_snapshot)
                bre = BatchRollbackError(
                    f"batch failed at step {index} ({step.id}): {exc}",
                    failed_ordinal=index,
                    failed_command_id=step.id,
                    reason=str(exc),
                    executed_ids=tuple(executed_ids),
                )
                try:
                    self._rebuild()
                except Exception as rb:
                    plan.mark_failed()
                    raise ReplayDuringRollbackError(
                        f"batch rollback replay failed: {rb}",
                        original=bre,
                        replay_reason=str(rb),
                    ) from rb
                plan.mark_failed()
                raise bre from exc
        plan.mark_done()
        self._redo_stack.clear()
