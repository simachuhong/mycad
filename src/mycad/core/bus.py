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
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NoReturn, cast

from mycad.core.document import Document, ExecutedCommand
from mycad.core.document_kinds import DRAWING2D_COMMAND_IDS
from mycad.core.exceptions import (
    BatchRollbackError,
    GeometryBuildError,
    InvalidHistoryError,
    InvalidPlanTransition,
    MycadError,
    ReplayDuringRollbackError,
    TopologyReferenceError,
    UnknownCommandError,
    ValidationError,
)
from mycad.core.handlers import CommandHandler, HandlerContext, resolve_handler
from mycad.core.kernel_protocol import Kernel
from mycad.core.plan import ConfirmationScope, Plan, PlanConfirmation

if TYPE_CHECKING:
    from mycad.commands.registry import CommandRegistry


class CommandBus:
    """Single-threaded command bus driving document history and geometry."""

    def __init__(
        self,
        document: Document,
        registry: CommandRegistry,
        kernel: Kernel,
        handlers: Mapping[str, CommandHandler] | Mapping[tuple[str, int], CommandHandler],
    ) -> None:
        self._document = document
        self._registry = registry
        self._kernel = kernel
        self._handlers: Mapping[str, CommandHandler] | Mapping[tuple[str, int], CommandHandler] = (
            dict(handlers)
        )
        self._redo_stack: list[ExecutedCommand] = []
        self._recovery_failure: ReplayDuringRollbackError | None = None
        self._confirmation_secret = secrets.token_bytes(32)
        self._consumed_confirmation_nonces: set[str] = set()
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
        self._snapshot_state = cast(
            "Callable[[], object]",
            getattr(document, "_snapshot_state"),  # noqa: B009
        )
        self._restore_state = cast(
            "Callable[[object], None]",
            getattr(document, "_restore_state"),  # noqa: B009
        )
        self._advance_document_revision = cast(
            "Callable[[], None]",
            getattr(document, "_advance_revision"),  # noqa: B009
        )
        self._replace_document_command_params = cast(
            "Callable[..., ExecutedCommand]",
            getattr(document, "_replace_command_params"),  # noqa: B009
        )

    @property
    def is_healthy(self) -> bool:
        """Whether the geometry is known to match the committed document."""
        return self._recovery_failure is None

    def _ensure_healthy(self) -> None:
        """Block writes after failed recovery so the Bus cannot imply success."""
        if self._recovery_failure is not None:
            failure = self._recovery_failure
            raise ReplayDuringRollbackError(
                "command bus is unusable because state recovery previously failed",
                original=failure.original,
                replay_reason=failure.replay_reason,
                recovery_error=failure.recovery_error,
            ) from failure

    def _poison(self, original: BaseException, recovery: BaseException, context: str) -> None:
        """Remember that the document history no longer proves kernel state."""
        failure = ReplayDuringRollbackError(
            f"{context} recovery failed: {recovery}",
            original=original,
            replay_reason=str(recovery),
            recovery_error=recovery,
        )
        self._recovery_failure = failure
        raise failure from recovery

    def _normalized_plan_digest(self, plan: Plan) -> str:
        """Hash canonical validated commands, so defaults and key order are stable."""
        from mycad.commands.validation import normalize_params, validate_params

        normalized_steps: list[dict[str, object]] = []
        for step in plan.steps:
            spec = self._registry.get(step.id, step.version)
            validated = validate_params(
                spec,
                dict(step.params),
                defs=self._registry.schema_defs,
            )
            normalized_steps.append(
                {
                    "id": spec.id,
                    "version": spec.version,
                    "params": normalize_params(validated),
                }
            )
        encoded = json.dumps(
            normalized_steps,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _confirmation_payload(grant: PlanConfirmation) -> bytes:
        """Serialize every authorization binding except its signature."""
        return json.dumps(
            {
                "plan_id": grant.plan_id,
                "actor": grant.actor,
                "scope": grant.scope,
                "document_id": grant.document_id,
                "document_revision": grant.document_revision,
                "content_digest": grant.content_digest,
                "nonce": grant.nonce,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def confirm_plan(self, plan: Plan, actor: str, *, scope: ConfirmationScope) -> None:
        """Confirm one normalized plan for this document and one product channel."""
        self._ensure_healthy()
        if scope not in ("gui", "cli"):
            raise InvalidPlanTransition(f"unsupported confirmation scope {scope!r}")
        if not actor:
            plan.confirm(actor)
        digest = self._normalized_plan_digest(plan)
        grant = PlanConfirmation(
            plan_id=plan.plan_id,
            actor=actor,
            scope=scope,
            document_id=self._document.document_id,
            document_revision=self._document.revision,
            content_digest=digest,
            nonce=secrets.token_urlsafe(32),
            signature="",
        )
        signature = hmac.new(
            self._confirmation_secret,
            self._confirmation_payload(grant),
            hashlib.sha256,
        ).hexdigest()
        plan.confirm(
            actor,
            authorization=PlanConfirmation(
                plan_id=grant.plan_id,
                actor=grant.actor,
                scope=grant.scope,
                document_id=grant.document_id,
                document_revision=grant.document_revision,
                content_digest=grant.content_digest,
                nonce=grant.nonce,
                signature=signature,
            ),
        )

    def _consume_or_reject_stale_confirmation(self, plan: Plan, reason: str) -> NoReturn:
        """Revoke a legitimate but stale grant and make the old plan terminal."""
        grant = plan.authorization
        if grant is not None:
            self._consumed_confirmation_nonces.add(grant.nonce)
        plan.cancel()
        raise InvalidPlanTransition(f"plan confirmation {reason}; create and confirm a new plan")

    def _verify_confirmation(self, plan: Plan, expected_scope: ConfirmationScope) -> None:
        """Check capability signature, one-time use, content and document binding."""
        grant = plan.authorization
        if grant is None:
            raise InvalidPlanTransition(
                "execute batch requires a Bus-issued confirmation authorization"
            )
        if grant.nonce in self._consumed_confirmation_nonces:
            raise InvalidPlanTransition("plan confirmation authorization has already been consumed")
        expected_signature = hmac.new(
            self._confirmation_secret,
            self._confirmation_payload(grant),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(grant.signature, expected_signature):
            raise InvalidPlanTransition("plan confirmation authorization is invalid")
        if grant.scope not in ("gui", "cli"):
            raise InvalidPlanTransition("plan confirmation scope is invalid")
        if grant.scope != expected_scope:
            raise InvalidPlanTransition(
                f"plan confirmation scope {grant.scope!r} cannot authorize {expected_scope!r} execution"
            )
        if grant.plan_id != plan.plan_id or grant.actor != plan.confirmed_by:
            raise InvalidPlanTransition("plan confirmation is bound to another plan or actor")
        if (
            grant.document_id != self._document.document_id
            or grant.document_revision != self._document.revision
        ):
            self._consume_or_reject_stale_confirmation(
                plan, "document identity or revision changed"
            )
        try:
            current_digest = self._normalized_plan_digest(plan)
        except (MycadError, TypeError, ValueError) as exc:
            self._consume_or_reject_stale_confirmation(plan, f"content is no longer valid: {exc}")
        if current_digest != grant.content_digest:
            self._consume_or_reject_stale_confirmation(plan, "content changed after confirmation")
        self._consumed_confirmation_nonces.add(grant.nonce)

    def _restore_and_rebuild(
        self,
        document_snapshot: object,
        redo_snapshot: list[ExecutedCommand],
        original: BaseException,
        context: str,
    ) -> None:
        """Restore the document and geometry or permanently mark the Bus unhealthy."""
        try:
            self._restore_state(document_snapshot)
            self._redo_stack = copy.deepcopy(redo_snapshot)
            self._rebuild()
        except Exception as recovery:
            self._document.events.discard_transaction()
            self._poison(original, recovery, context)
        self._document.events.discard_transaction()
        self._document.events.emit("geometry_rebuilt")

    def _restore_without_rebuild(
        self,
        document_snapshot: object,
        redo_snapshot: list[ExecutedCommand],
        original: BaseException,
        context: str,
    ) -> None:
        """Restore state after validation fails before a handler can run."""
        try:
            self._restore_state(document_snapshot)
            self._redo_stack = copy.deepcopy(redo_snapshot)
        except Exception as recovery:
            self._document.events.discard_transaction()
            self._poison(original, recovery, context)
        self._document.events.discard_transaction()

    def execute(
        self,
        command_id: str,
        params: Mapping[str, object],
        confirmed_by: str | None = None,
        *,
        version: int | None = None,
    ) -> object | None:
        """Execute one command; any success clears the redo stack."""
        self._ensure_healthy()
        document_snapshot = self._snapshot_state()
        redo_snapshot = copy.deepcopy(self._redo_stack)
        handler_started = False

        def mark_handler_started() -> None:
            nonlocal handler_started
            handler_started = True

        self._document.events.begin_transaction()
        try:
            result = self._execute_one(
                command_id,
                params,
                confirmed_by,
                version=version,
                record=True,
                on_handler_start=mark_handler_started,
            )
            self._redo_stack.clear()
            self._advance_document_revision()
            self._document.events.commit_transaction()
            return result
        except Exception as original:
            if handler_started:
                self._restore_and_rebuild(document_snapshot, redo_snapshot, original, "execute")
            else:
                self._restore_without_rebuild(
                    document_snapshot, redo_snapshot, original, "execute document"
                )
            raise

    def _execute_one(
        self,
        command_id: str,
        params: Mapping[str, object],
        confirmed_by: str | None,
        *,
        version: int | None = None,
        record: bool = True,
        on_handler_start: Callable[[], None] | None = None,
    ) -> object | None:
        """The ONE pipeline: validate -> normalize -> handler (fixed order)."""
        from mycad.commands.validation import normalize_params, validate_params

        spec = self._registry.get(command_id, version)
        if (
            self._document.archive_version >= 4
            and self._document.document_kind != "drawing"
            and command_id.startswith(
                ("drawing.sheet.", "drawing.view.", "drawing.annotation.", "drawing.note.")
            )
        ):
            raise ValidationError("工程图对象只能写入独立工程图文档。")
        if self._document.document_type == "drawing2d" and spec.id not in DRAWING2D_COMMAND_IDS:
            raise ValidationError(f"command {spec.id!r} is not supported in a drawing2d document")
        handler = resolve_handler(
            self._handlers, spec.id, spec.version, self._registry.versions(spec.id)
        )
        if handler is None:
            raise UnknownCommandError(
                f"no handler registered for {command_id!r} version {spec.version}",
                command_id=command_id,
                identifier=command_id,
            )
        validated = validate_params(spec, dict(params), defs=self._registry.schema_defs)
        normalized = normalize_params(validated)
        if command_id in ("reference.attach", "reference.update"):
            from mycad.core.document_references import DocumentReference, validate_reference_tree

            reference = DocumentReference.from_mapping(normalized)
            validate_reference_tree(reference.archive, frozenset({self._document.file_id}))
            if self._document.document_kind != "drawing" and reference.kind == "part":
                raise ValidationError("only engineering drawings can reference a source part")
        if record:
            self._document.events.emit_immediate(
                "pre_command",
                {"command_id": command_id, "command_version": spec.version},
            )
        ctx = HandlerContext(
            kernel=self._kernel,
            command_id=command_id,
            command_version=spec.version,
        )
        if on_handler_start is not None:
            on_handler_start()
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
                {
                    "command_id": command_id,
                    "command_version": spec.version,
                    "ordinal": len(self._document.commands) - 1,
                },
            )
        return result

    def _validate_n(self, action: str, n: int) -> None:
        """``n`` must be an integer >= 1 (CLI parsing is T10's concern)."""
        # Runtime check of untrusted input; cast keeps it non-redundant for pyright.
        if not isinstance(cast("object", n), int) or n < 1:
            raise InvalidHistoryError(f"{action}: n must be an integer >= 1, got {n!r}")

    def undo(self, n: int = 1) -> None:
        """Pop the trailing ``n`` commands onto the redo stack; rebuild once."""
        self._ensure_healthy()
        self._validate_n("undo", n)
        if n > len(self._document.commands):
            raise InvalidHistoryError(
                f"undo: history has {len(self._document.commands)} commands, requested {n}"
            )
        document_snapshot = self._snapshot_state()
        redo_snapshot = copy.deepcopy(self._redo_stack)
        self._document.events.begin_transaction()
        try:
            popped = self._pop_commands(n)
            self._redo_stack.extend(reversed(popped))
            self._rebuild()
            self._advance_document_revision()
            self._document.events.commit_transaction()
        except Exception as original:
            self._restore_and_rebuild(document_snapshot, redo_snapshot, original, "undo")
            raise

    def redo(self, n: int = 1) -> None:
        """Pop ``n`` commands back from the redo stack; rebuild once."""
        self._ensure_healthy()
        self._validate_n("redo", n)
        if n > len(self._redo_stack):
            raise InvalidHistoryError(
                f"redo: redo stack has {len(self._redo_stack)} commands, requested {n}"
            )
        document_snapshot = self._snapshot_state()
        redo_snapshot = copy.deepcopy(self._redo_stack)
        self._document.events.begin_transaction()
        try:
            popped = self._redo_stack[-n:]
            del self._redo_stack[-n:]
            for cmd in reversed(popped):
                self._append_command(cmd)
            self._rebuild()
            self._advance_document_revision()
            self._document.events.commit_transaction()
        except Exception as original:
            self._restore_and_rebuild(document_snapshot, redo_snapshot, original, "redo")
            raise

    def _rebuild(self) -> None:
        """Reset the kernel, replay the history (record=False), notify once."""
        self._kernel.reset()
        for cmd in self._document.commands:
            try:
                self._execute_one(
                    cmd.id,
                    cmd.params,
                    cmd.confirmed_by,
                    version=cmd.version,
                    record=False,
                )
            except GeometryBuildError as exc:
                if exc.ordinal is None:
                    raise GeometryBuildError(
                        message=exc.message,
                        command_id=exc.command_id,
                        ordinal=cmd.ordinal,
                    ) from exc
                raise
            except TopologyReferenceError as exc:
                if exc.ordinal is None:
                    raise TopologyReferenceError(
                        message=exc.message,
                        command_id=exc.command_id,
                        ordinal=cmd.ordinal,
                        reason=exc.reason,
                        parameter_path=exc.parameter_path,
                    ) from exc
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
        self._ensure_healthy()
        document_snapshot = self._snapshot_state()
        redo_snapshot = copy.deepcopy(self._redo_stack)
        self._document.events.begin_transaction()
        replay_started = False
        try:
            self._replace_document_command_params(
                ordinal,
                params,
                actor,
                reason,
                notify=False,
                advance_revision=False,
            )
            self._document.events.emit(
                "command_amended",
                {
                    "ordinal": ordinal,
                    "command_id": self._document.commands[ordinal].id,
                    "command_version": self._document.commands[ordinal].version,
                },
            )
            replay_started = True
            self._rebuild()
            self._advance_document_revision()
            self._document.events.commit_transaction()
            self._redo_stack.clear()
        except Exception as original:
            if replay_started:
                self._restore_and_rebuild(document_snapshot, redo_snapshot, original, "edit")
            else:
                self._restore_without_rebuild(
                    document_snapshot, redo_snapshot, original, "edit document"
                )
            raise

    def execute_batch(self, plan: Plan, *, scope: ConfirmationScope) -> None:
        """Execute a scoped confirmed ``plan`` atomically; failures roll it back.

        Every step goes through the same ``_execute_one`` pipeline as single
        commands. On failure the document is restored, ``plan.mark_failed()``
        runs BEFORE the raise, and ``BatchRollbackError`` carries the
        0-based ``failed_ordinal``, the failing id, the reason and the ids
        of already-executed steps.
        """
        self._ensure_healthy()
        if scope not in ("gui", "cli"):
            raise InvalidPlanTransition(f"unsupported execution scope {scope!r}")
        if plan.status != "confirmed":
            plan.mark_executing()
        self._verify_confirmation(plan, expected_scope=scope)
        plan.mark_executing()
        document_snapshot = self._snapshot_state()
        redo_snapshot = copy.deepcopy(self._redo_stack)
        executed_ids: list[str] = []
        handler_started = False
        self._document.events.begin_transaction()
        for index, step in enumerate(plan.steps):

            def mark_handler_started() -> None:
                nonlocal handler_started
                handler_started = True

            try:
                self._execute_one(
                    step.id,
                    step.params,
                    plan.confirmed_by,
                    version=step.version,
                    record=True,
                    on_handler_start=mark_handler_started,
                )
                executed_ids.append(step.id)
            except Exception as exc:
                bre = BatchRollbackError(
                    f"batch failed at step {index} ({step.id}): {exc}",
                    failed_ordinal=index,
                    failed_command_id=step.id,
                    reason=str(exc),
                    executed_ids=tuple(executed_ids),
                )
                try:
                    self._restore_state(document_snapshot)
                    self._redo_stack = redo_snapshot
                except Exception as recovery:
                    self._document.events.discard_transaction()
                    plan.mark_failed()
                    self._poison(bre, recovery, "batch document")
                if handler_started:
                    try:
                        self._rebuild()
                    except Exception as rb:
                        self._document.events.discard_transaction()
                        plan.mark_failed()
                        self._poison(bre, rb, "batch replay")
                    self._document.events.discard_transaction()
                    self._document.events.emit("geometry_rebuilt")
                else:
                    self._document.events.discard_transaction()
                plan.mark_failed()
                raise bre from exc
        plan.mark_done()
        self._advance_document_revision()
        self._document.events.commit_transaction()
        self._redo_stack.clear()
