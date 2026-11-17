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
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NoReturn, cast
from uuid import uuid4

from mycad.core.bound_refs import is_bound_hole, validate_hole_binding
from mycad.core.command_identity import IdentityUpgrade, require_instance_id
from mycad.core.document import CommandAmendment, Document, ExecutedCommand
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
from mycad.core.kernel_protocol import ChamferBaselineKernel, DrawingBaselineKernel, Kernel
from mycad.core.plan import ConfirmationScope, Plan, PlanConfirmation
from mycad.core.replay_proposal import (
    ReplayCandidateProposal,
    ReplayChangeSet,
    ReplayCommitGrant,
    ReplayFailure,
    replay_digest,
)

if TYPE_CHECKING:
    from mycad.commands.registry import CommandRegistry


@dataclass(frozen=True)
class _OperationState:
    commands: tuple[ExecutedCommand, ...]
    redo: tuple[ExecutedCommand, ...]


@dataclass(frozen=True)
class _Operation:
    before: _OperationState
    after: _OperationState


@dataclass(frozen=True)
class _SaveState:
    document: object
    redo: list[ExecutedCommand]
    undo_operations: list[_Operation]
    redo_operations: list[_Operation]
    revision: int
    operation_revision: int


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
        self._operation_undo: list[_Operation] = []
        self._operation_redo: list[_Operation] = []
        self._operation_revision = document.revision
        self._save_checkpoints: dict[str, _SaveState] = {}
        self._recovery_failure: ReplayDuringRollbackError | None = None
        self._confirmation_secret = secrets.token_bytes(32)
        self._consumed_confirmation_nonces: set[str] = set()
        self._identity_upgrade_proposal: IdentityUpgrade | None = None
        self._prepared_replay_proposals: dict[str, tuple[ReplayCandidateProposal, bool]] = {}
        self._consumed_replay_grant_nonces: set[str] = set()
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

    def create_save_checkpoint(self) -> str:
        """Retain document and runtime history behind a Bus-owned, one-use handle."""
        self._ensure_healthy()
        token = uuid4().hex
        self._save_checkpoints[token] = _SaveState(
            self._snapshot_state(),
            copy.deepcopy(self._redo_stack),
            copy.deepcopy(self._operation_undo),
            copy.deepcopy(self._operation_redo),
            self._document.revision,
            self._operation_revision,
        )
        return token

    def release_save_checkpoint(self, token: str) -> None:
        """Accept the prepared edits after the file has been replaced."""
        if self._save_checkpoints.pop(token, None) is None:
            raise ValidationError("save checkpoint is invalid or already consumed")

    def restore_save_checkpoint(self, token: str, *, expected_revision: int) -> None:
        """Recover a failed save without overwriting edits made after preparation.

        The caller serializes preparation and recovery and supplies the revision
        observed at the end of its preparation, before delivering UI callbacks.
        Recovery invalidates old proposal capabilities and advances revision;
        restoring runtime history must not make stale grants valid again.
        """
        self._ensure_healthy()
        state = self._save_checkpoints.get(token)
        if state is None:
            raise ValidationError("save checkpoint is invalid or already consumed")
        if self._document.revision != expected_revision:
            raise ValidationError("save recovery refused: document changed after preparation")
        del self._save_checkpoints[token]
        if (
            self._snapshot_state() == state.document
            and self._redo_stack == state.redo
            and self._operation_undo == state.undo_operations
            and self._operation_redo == state.redo_operations
            and self._document.revision == state.revision
        ):
            return
        self._document.events.begin_transaction()
        try:
            self._restore_state(state.document)
            self._redo_stack = copy.deepcopy(state.redo)
            self._rebuild()
            self._restore_state(state.document)
            self._operation_undo = copy.deepcopy(state.undo_operations)
            self._operation_redo = copy.deepcopy(state.redo_operations)
            self._advance_document_revision()
            self._operation_revision = (
                self._document.revision
                if state.operation_revision == state.revision
                else state.operation_revision
            )
            self._identity_upgrade_proposal = None
            self._prepared_replay_proposals.clear()
        except Exception as recovery:
            self._document.events.discard_transaction()
            self._poison(ValidationError("save failed"), recovery, "save checkpoint")
        self._document.events.commit_transaction()

    def _operation_state(self) -> _OperationState:
        return _OperationState(
            tuple(self._document.commands), tuple(copy.deepcopy(self._redo_stack))
        )

    def _invalidate_operations(self) -> None:
        self._operation_undo.clear()
        self._operation_redo.clear()
        self._operation_revision = self._document.revision

    def _prepare_operation(self) -> _OperationState:
        if self._operation_revision != self._document.revision:
            self._invalidate_operations()
        return self._operation_state()

    def _record_operation(self, before: _OperationState) -> None:
        self._operation_undo.append(_Operation(before, self._operation_state()))
        del self._operation_undo[:-100]
        self._operation_redo.clear()
        self._operation_revision = self._document.revision

    def _record_appended_operations(self, before: _OperationState) -> None:
        commands = self._document.commands
        prior = before
        for end in range(len(before.commands) + 1, len(commands) + 1):
            after = _OperationState(commands[:end], ())
            self._operation_undo.append(_Operation(prior, after))
            prior = after
        del self._operation_undo[:-100]
        self._operation_redo.clear()
        self._operation_revision = self._document.revision

    def _restore_operation(self, state: _OperationState, on_commit: Callable[[], None]) -> None:
        snapshot = self._snapshot_state()
        redo = copy.deepcopy(self._redo_stack)
        self._document.events.begin_transaction()
        try:
            restore_commands = cast(
                "Callable[[list[ExecutedCommand]], None]",
                getattr(self._document, "_restore_commands"),  # noqa: B009
            )
            restore_commands(list(state.commands))
            self._redo_stack = list(copy.deepcopy(state.redo))
            self._rebuild()
            from mycad.core.persistence import document_payload

            document_payload(self._document)
            self._advance_document_revision()
            on_commit()
            self._document.events.commit_transaction()
        except Exception as original:
            self._restore_and_rebuild(snapshot, redo, original, "operation history")
            raise

    def _check_operation_revision(self) -> None:
        if self._operation_revision != self._document.revision:
            self._invalidate_operations()
            raise InvalidHistoryError("operation history is stale after document changes")

    def undo_operation(self) -> None:
        """Undo one runtime operation, falling back to loaded command history."""
        self._ensure_healthy()
        self._check_operation_revision()
        if len(self._operation_redo) >= 100:
            raise InvalidHistoryError("undo: operation redo history limit reached")
        if not self._operation_undo:
            before = self._operation_state()
            if not before.commands:
                raise InvalidHistoryError("undo: history has no commands")
            after = _OperationState(before.commands[:-1], (*before.redo, before.commands[-1]))

            def finish_fallback() -> None:
                self._operation_redo.append(_Operation(after, before))
                self._operation_revision = self._document.revision

            self._restore_operation(after, finish_fallback)
            return
        operation = self._operation_undo[-1]

        def finish_undo() -> None:
            self._operation_undo.pop()
            self._operation_redo.append(operation)
            self._operation_revision = self._document.revision

        self._restore_operation(operation.before, finish_undo)

    def undo_operation_before_drawing_settings(self, identity: str, revision: int) -> None:
        """Undo a runtime operation while retaining later 2D scalar settings and their audit data."""
        self._ensure_healthy()
        self._check_operation_revision()
        if self._document.document_type != "drawing2d" or self._document.revision != revision:
            raise InvalidHistoryError("document changed before drawing operation undo")
        before = self._operation_state()
        settings_ids = {"drawing.fillet_radius.set", "drawing.chamfer_values.set"}
        for operation in reversed(self._operation_undo):
            prior, after = operation.before.commands, operation.after.commands
            if not after or after[-1].instance_id != identity:
                continue
            if before.commands[: len(after)] != after:
                continue
            tail = before.commands[len(after) :]
            if (
                not tail
                or any(command.id not in settings_ids for command in tail)
                or any(command.instance_id == identity for command in prior)
            ):
                break
            restored = tuple(
                replace(command, ordinal=index) for index, command in enumerate((*prior, *tail))
            )
            self._restore_operation(
                _OperationState(restored, ()), lambda: self._record_operation(before)
            )
            return
        raise InvalidHistoryError("drawing operation is no longer followed only by settings")

    def redo_operation(self) -> None:
        """Redo one runtime operation, preserving its original audit fields."""
        self._ensure_healthy()
        self._check_operation_revision()
        if not self._operation_redo:
            before = self._operation_state()
            if not before.redo:
                raise InvalidHistoryError("redo: redo stack has no commands")
            after = _OperationState((*before.commands, before.redo[-1]), before.redo[:-1])
            self._restore_operation(after, lambda: self._record_operation(before))
            return
        operation = self._operation_redo[-1]

        def finish_redo() -> None:
            self._operation_redo.pop()
            self._operation_undo.append(operation)
            self._operation_revision = self._document.revision

        self._restore_operation(operation.after, finish_redo)

    @property
    def is_healthy(self) -> bool:
        """Whether the geometry is known to match the committed document."""
        return self._recovery_failure is None

    def _upgrade_signature(self, proposal: IdentityUpgrade) -> str:
        payload = json.dumps(
            [proposal.document_id, proposal.revision, proposal.active_ids, proposal.redo_ids],
            separators=(",", ":"),
        ).encode()
        return hmac.new(self._confirmation_secret, payload, hashlib.sha256).hexdigest()

    def prepare_identity_upgrade(self) -> IdentityUpgrade:
        """Allocate a revision-bound proposal without changing active/redo state."""
        self._ensure_healthy()
        cached = self._identity_upgrade_proposal
        if (
            cached is not None
            and cached.document_id == self._document.document_id
            and cached.revision == self._document.revision
            and len(cached.active_ids) == len(self._document.commands)
            and len(cached.redo_ids) == len(self._redo_stack)
            and hmac.compare_digest(cached.signature, self._upgrade_signature(cached))
        ):
            return cached
        proposal = IdentityUpgrade(
            self._document.document_id,
            self._document.revision,
            tuple(c.instance_id or uuid4().hex for c in self._document.commands),
            tuple(c.instance_id or uuid4().hex for c in self._redo_stack),
            "",
        )
        signed = replace(proposal, signature=self._upgrade_signature(proposal))
        self._identity_upgrade_proposal = signed
        return signed

    def prepare_replay_proposal(
        self,
        changes: ReplayChangeSet,
        *,
        session_identity: int,
        candidate_id: str,
        generation: int,
    ) -> ReplayCandidateProposal:
        """Normalize a complete isolated history without changing source state."""
        from mycad.commands.validation import normalize_params, validate_params

        self._ensure_healthy()
        commands = list(copy.deepcopy(self._document.commands))
        replaced_ordinals: set[int] = set()
        for edit in changes.replacements:
            if edit.ordinal in replaced_ordinals:
                raise ValidationError(f"duplicate replacement ordinal {edit.ordinal}")
            if not 0 <= edit.ordinal < len(commands):
                raise ValidationError(f"replacement ordinal {edit.ordinal} is outside history")
            replaced_ordinals.add(edit.ordinal)
            command = commands[edit.ordinal]
            spec = self._registry.get(command.id, command.version)
            validated = validate_params(
                spec,
                dict(edit.params),
                defs=self._registry.schema_defs,
            )
            normalized = normalize_params(validated)
            if normalized != command.params:
                amendment = CommandAmendment(
                    at=datetime.now(UTC).isoformat(),
                    actor=edit.actor,
                    from_params=copy.deepcopy(command.params),
                    reason=edit.reason,
                )
                commands[edit.ordinal] = replace(
                    command,
                    params=copy.deepcopy(normalized),
                    amendments=(*command.amendments, amendment),
                )

        archive_version = self._document.archive_version
        identity_upgrade: IdentityUpgrade | None = None
        if (
            changes.upgrade_to_v5 or changes.target_archive_version in (6, 7, 8)
        ) and archive_version < 5:
            identity_upgrade = self.prepare_identity_upgrade()
            commands = [
                replace(command, instance_id=identity)
                for command, identity in zip(commands, identity_upgrade.active_ids, strict=True)
            ]
            archive_version = 5
        if changes.target_archive_version is not None:
            archive_version = max(archive_version, changes.target_archive_version)

        for append in changes.appends:
            spec = self._registry.get(append.command_id, append.version)
            if (
                append.command_id.startswith("drawing.raster.")
                or "raster_batch" in append.params
                or "clipboard_styles" in append.params
            ) and self._document.document_type != "drawing2d":
                raise ValidationError("图纸图片只支持独立二维文档。")
            if (
                append.command_id
                in {
                    "drawing.fillet_radius.set",
                    "drawing.chamfer_values.set",
                    "drawing.dimension_styles.set",
                }
                and self._document.document_type != "drawing2d"
            ):
                raise ValidationError("二维图纸设置只支持独立二维文档。")
            if (
                append.command_id.startswith("drawing.array.")
                or (
                    append.command_id in ("sketch.create", "drawing.sketch.revise")
                    and "associative_arrays" in append.params
                )
            ) and self._document.document_type != "drawing2d":
                raise ValidationError("关联阵列目前只支持独立二维文档。")
            if spec.min_archive_version >= 5 and spec.min_archive_version > archive_version:
                raise ValidationError("command requires an explicit compatible archive upgrade")
            if (
                archive_version >= 4
                and self._document.document_kind != "drawing"
                and append.command_id.startswith(
                    ("drawing.sheet.", "drawing.view.", "drawing.annotation.", "drawing.note.")
                )
            ):
                raise ValidationError("工程图对象只能写入独立工程图文档。")
            if self._document.document_type == "drawing2d" and spec.id not in DRAWING2D_COMMAND_IDS:
                raise ValidationError(
                    f"command {spec.id!r} is not supported in a drawing2d document"
                )
            validated = validate_params(
                spec,
                dict(append.params),
                defs=self._registry.schema_defs,
            )
            normalized = normalize_params(validated)
            if is_bound_hole(spec.id, normalized) and archive_version < 5:
                raise ValidationError(
                    "bound face holes require explicit archive v5 identity upgrade"
                )
            if is_bound_hole(spec.id, normalized):
                validate_hole_binding(normalized, ordinal=len(commands))
            if spec.id in ("reference.attach", "reference.update"):
                from mycad.core.document_references import (
                    DocumentReference,
                    validate_reference_tree,
                )

                reference = DocumentReference.from_mapping(normalized)
                if cast("int", reference.archive["version"]) > archive_version:
                    raise ValidationError("reference requires a compatible archive upgrade")
                validate_reference_tree(reference.archive, frozenset({self._document.file_id}))
                if self._document.document_kind != "drawing" and reference.kind == "part":
                    raise ValidationError("only engineering drawings can reference a source part")
            instance_id = uuid4().hex if archive_version >= 5 else None
            if instance_id is not None:
                while any(command.instance_id == instance_id for command in commands):
                    instance_id = uuid4().hex
            commands.append(
                ExecutedCommand(
                    id=spec.id,
                    version=spec.version,
                    params=copy.deepcopy(normalized),
                    ordinal=len(commands),
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    confirmed_by=append.confirmed_by,
                    instance_id=instance_id,
                )
            )
            archive_version = max(archive_version, spec.min_archive_version)

        frozen_commands = tuple(commands)
        proposal = ReplayCandidateProposal(
            document_id=self._document.document_id,
            file_id=self._document.file_id,
            revision=self._document.revision,
            session_identity=session_identity,
            candidate_id=candidate_id,
            generation=generation,
            archive_version=archive_version,
            commands=frozen_commands,
            identity_upgrade=identity_upgrade,
            digest=replay_digest(archive_version, frozen_commands),
            undo_appends_separately=changes.undo_appends_separately,
        )
        self._prepared_replay_proposals[candidate_id] = (copy.deepcopy(proposal), False)
        return proposal

    def record_replay_candidate_preview(
        self, proposal: ReplayCandidateProposal, *, succeeded: bool
    ) -> None:
        """Record the latest isolated preview result for one prepared candidate."""
        if type(succeeded) is not bool:
            raise ValidationError("succeeded must be a boolean")
        cached_entry = self._prepared_replay_proposals.get(proposal.candidate_id)
        if cached_entry is None:
            raise ValidationError("candidate proposal is no longer prepared")
        cached, _previous_success = cached_entry
        if proposal.generation < cached.generation:
            raise ValidationError("candidate preview generation is stale")
        if replace(proposal, generation=cached.generation) != cached:
            raise ValidationError("candidate preview does not match its prepared proposal")
        if proposal.digest != replay_digest(proposal.archive_version, proposal.commands):
            raise ValidationError("candidate preview digest is invalid")
        if (
            proposal.document_id != self._document.document_id
            or proposal.file_id != self._document.file_id
            or proposal.revision != self._document.revision
        ):
            raise ValidationError("candidate source document changed")
        self._prepared_replay_proposals[proposal.candidate_id] = (
            copy.deepcopy(proposal),
            succeeded,
        )

    def discard_replay_candidate(self, candidate_id: str) -> None:
        """Forget a prepared candidate after cancellation, failure, or staleness."""
        self._prepared_replay_proposals.pop(candidate_id, None)

    @staticmethod
    def _replay_grant_payload(grant: ReplayCommitGrant) -> bytes:
        """Serialize every source and candidate binding covered by a grant."""
        return json.dumps(
            {
                "document_id": grant.document_id,
                "file_id": grant.file_id,
                "revision": grant.revision,
                "session_identity": grant.session_identity,
                "candidate_id": grant.candidate_id,
                "generation": grant.generation,
                "digest": grant.digest,
                "nonce": grant.nonce,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def _validate_replay_candidate(self, proposal: ReplayCandidateProposal) -> bool:
        """Validate source binding, complete history, IDs, and final archive."""
        from mycad.commands.validation import normalize_params, validate_params
        from mycad.core.persistence import document_payload

        self._ensure_healthy()
        cached_entry = self._prepared_replay_proposals.get(proposal.candidate_id)
        if cached_entry is None:
            raise ValidationError("candidate proposal is no longer prepared")
        cached, succeeded = cached_entry
        if not succeeded:
            raise ValidationError("candidate has no successful current preview")
        if proposal != cached:
            raise ValidationError("candidate proposal changed after its successful preview")
        if (
            proposal.document_id != self._document.document_id
            or proposal.file_id != self._document.file_id
            or proposal.revision != self._document.revision
        ):
            raise ValidationError("candidate source document changed")
        if proposal.digest != replay_digest(proposal.archive_version, proposal.commands):
            raise ValidationError("candidate digest does not match its command history")

        source_commands = self._document.commands
        if len(proposal.commands) < len(source_commands):
            raise ValidationError("candidate history cannot remove source commands")
        identity_upgrade = proposal.identity_upgrade
        expected_active_ids = tuple(command.instance_id for command in source_commands)
        if identity_upgrade is not None:
            identities = (*identity_upgrade.active_ids, *identity_upgrade.redo_ids)
            if (
                identity_upgrade.document_id != self._document.document_id
                or identity_upgrade.revision != self._document.revision
                or not hmac.compare_digest(
                    identity_upgrade.signature, self._upgrade_signature(identity_upgrade)
                )
                or len(identity_upgrade.active_ids) != len(source_commands)
                or len(identity_upgrade.redo_ids) != len(self._redo_stack)
                or len(set(identities)) != len(identities)
            ):
                raise ValidationError("candidate identity upgrade is stale or invalid")
            for identity in identities:
                require_instance_id(identity)
            expected_active_ids = identity_upgrade.active_ids
        elif self._document.archive_version < 5 <= proposal.archive_version:
            raise ValidationError("candidate archive v5 requires a signed identity upgrade")

        expected_archive_version = max(
            self._document.archive_version,
            5 if identity_upgrade is not None else self._document.archive_version,
        )
        if proposal.archive_version in (6, 7, 8):
            expected_archive_version = max(expected_archive_version, proposal.archive_version)
        for index, original in enumerate(source_commands):
            candidate = proposal.commands[index]
            if (
                candidate.ordinal != index
                or candidate.id != original.id
                or candidate.version != original.version
                or candidate.timestamp_utc != original.timestamp_utc
                or candidate.confirmed_by != original.confirmed_by
                or candidate.instance_id != expected_active_ids[index]
                or candidate.amendments[: len(original.amendments)] != original.amendments
            ):
                raise ValidationError("candidate changed immutable source command audit data")
            spec = self._registry.get(candidate.id, candidate.version)
            validated = validate_params(
                spec, dict(candidate.params), defs=self._registry.schema_defs
            )
            if normalize_params(validated) != candidate.params:
                raise ValidationError("candidate command params are not normalized")
            if candidate.params == original.params:
                if candidate.amendments != original.amendments:
                    raise ValidationError("unchanged command has an unexpected amendment")
            elif (
                len(candidate.amendments) != len(original.amendments) + 1
                or candidate.amendments[-1].from_params != original.params
            ):
                raise ValidationError("edited command must append one amendment from old params")
            expected_archive_version = max(expected_archive_version, spec.min_archive_version)

        appended_commands = proposal.commands[len(source_commands) :]
        for index, command in enumerate(appended_commands, start=len(source_commands)):
            if command.ordinal != index or command.amendments:
                raise ValidationError("candidate appended command has invalid ordinal or audit")
            spec = self._registry.get(command.id, command.version)
            validated = validate_params(spec, dict(command.params), defs=self._registry.schema_defs)
            if normalize_params(validated) != command.params:
                raise ValidationError("candidate appended params are not normalized")
            expected_archive_version = max(expected_archive_version, spec.min_archive_version)

        if proposal.archive_version != expected_archive_version:
            raise ValidationError("candidate archive version does not match its command history")
        all_commands = proposal.commands
        if proposal.archive_version >= 5:
            identities = tuple(require_instance_id(command.instance_id) for command in all_commands)
            redo_values = (
                identity_upgrade.redo_ids
                if identity_upgrade is not None
                else tuple(command.instance_id for command in self._redo_stack)
            )
            redo_identities = tuple(require_instance_id(identity) for identity in redo_values)
            all_identities = (*identities, *redo_identities)
            if len(set(all_identities)) != len(all_identities):
                raise ValidationError("candidate command identities are not unique")
        elif any(command.instance_id is not None for command in all_commands):
            raise ValidationError("pre-v5 candidate commands cannot carry instance identities")

        archive_document = Document(
            self._registry,
            metadata=self._document.metadata_snapshot(),
            commands=all_commands,
            named_groups=self._document.named_groups,
            archive_version=proposal.archive_version,
            document_type=self._document.document_type,
            document_kind=self._document.document_kind,
            file_id=self._document.file_id,
            migration_origin=self._document.migration_origin,
            reference_locations=self._document.reference_locations,
            drawing_fillet_baseline=self._document.drawing_fillet_baseline,
            drawing_chamfer_angle_baseline=self._document.drawing_chamfer_angle_baseline,
        )
        document_payload(archive_document)
        return identity_upgrade is not None

    def authorize_replay_candidate(self, proposal: ReplayCandidateProposal) -> ReplayCommitGrant:
        """Sign a one-time grant for the latest successful candidate preview."""
        self._validate_replay_candidate(proposal)
        grant = ReplayCommitGrant(
            document_id=proposal.document_id,
            file_id=proposal.file_id,
            revision=proposal.revision,
            session_identity=proposal.session_identity,
            candidate_id=proposal.candidate_id,
            generation=proposal.generation,
            digest=proposal.digest,
            nonce=secrets.token_urlsafe(32),
            signature="pending",
        )
        signature = hmac.new(
            self._confirmation_secret,
            self._replay_grant_payload(grant),
            hashlib.sha256,
        ).hexdigest()
        return replace(grant, signature=signature)

    def commit_replay_candidate(
        self, proposal: ReplayCandidateProposal, grant: ReplayCommitGrant
    ) -> None:
        """Atomically apply a successful, source-bound candidate history."""
        identity_upgrade = self._validate_replay_candidate(proposal)
        expected_signature = hmac.new(
            self._confirmation_secret,
            self._replay_grant_payload(grant),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(grant.signature, expected_signature):
            raise ValidationError("replay candidate grant signature is invalid")
        if grant.nonce in self._consumed_replay_grant_nonces:
            raise ValidationError("replay candidate grant has already been consumed")
        if (
            grant.document_id != proposal.document_id
            or grant.file_id != proposal.file_id
            or grant.revision != proposal.revision
            or grant.session_identity != proposal.session_identity
            or grant.candidate_id != proposal.candidate_id
            or grant.generation != proposal.generation
            or grant.digest != proposal.digest
        ):
            raise ValidationError("replay candidate grant is bound to another proposal")

        source_commands = self._document.commands
        content_changed = len(proposal.commands) != len(source_commands) or any(
            proposal.commands[index].params != command.params
            or proposal.commands[index].amendments != command.amendments
            for index, command in enumerate(source_commands)
        )
        version_changed = proposal.archive_version != self._document.archive_version
        if not content_changed and not identity_upgrade and not version_changed:
            self._consumed_replay_grant_nonces.add(grant.nonce)
            self.discard_replay_candidate(proposal.candidate_id)
            return

        self._consumed_replay_grant_nonces.add(grant.nonce)
        operation_before = self._prepare_operation()
        document_snapshot = self._snapshot_state()
        redo_snapshot = copy.deepcopy(self._redo_stack)
        self._document.events.begin_transaction()
        try:
            if identity_upgrade:
                adopt_identities = cast(
                    "Callable[[tuple[str, ...]], None]",
                    getattr(self._document, "_adopt_command_identities"),  # noqa: B009
                )
                assert proposal.identity_upgrade is not None
                adopt_identities(proposal.identity_upgrade.active_ids)
                self._redo_stack = [
                    replace(command, instance_id=identity)
                    for command, identity in zip(
                        self._redo_stack,
                        proposal.identity_upgrade.redo_ids,
                        strict=True,
                    )
                ]
            if (
                proposal.archive_version in (6, 7, 8)
                and self._document.archive_version < proposal.archive_version
            ):
                adopt_version = cast(
                    "Callable[[int], None]",
                    getattr(self._document, "_adopt_archive_version"),  # noqa: B009
                )
                adopt_version(proposal.archive_version)
            if identity_upgrade:
                operation_before = self._operation_state()
            if content_changed:
                self._pop_commands(len(self._document.commands))
                for command in proposal.commands:
                    if command.ordinal >= len(source_commands):
                        self._document.events.emit(
                            "pre_command",
                            {"command_id": command.id, "command_version": command.version},
                        )
                    self._append_command(command)
                for index, (original, candidate) in enumerate(
                    zip(source_commands, proposal.commands, strict=False)
                ):
                    if (
                        original.params != candidate.params
                        or original.amendments != candidate.amendments
                    ):
                        self._document.events.emit(
                            "command_amended",
                            {
                                "ordinal": index,
                                "command_id": candidate.id,
                                "command_version": candidate.version,
                            },
                        )
                for command in proposal.commands[len(source_commands) :]:
                    self._document.events.emit(
                        "post_command",
                        {
                            "command_id": command.id,
                            "command_version": command.version,
                            "ordinal": command.ordinal,
                        },
                    )
            self._rebuild()
            if content_changed:
                self._redo_stack.clear()
            from mycad.core.persistence import document_payload

            document_payload(self._document)
            self._advance_document_revision()
            self.discard_replay_candidate(proposal.candidate_id)
            if identity_upgrade:
                self._invalidate_operations()
            if content_changed:
                if proposal.undo_appends_separately:
                    self._record_appended_operations(operation_before)
                else:
                    self._record_operation(operation_before)
            else:
                self._operation_revision = self._document.revision
            self._document.events.commit_transaction()
        except Exception as original:
            self._restore_and_rebuild(
                document_snapshot,
                redo_snapshot,
                original,
                "replay candidate commit",
            )
            raise

    def copy_for_document(self, document: Document) -> CommandBus:
        """Transfer redo to an identity-only session replacement with fresh grants."""
        self._ensure_healthy()
        if (
            document.commands != self._document.commands
            or document.archive_version < self._document.archive_version
        ):
            raise ValidationError("identity-only replacement must preserve command history")
        copied = CommandBus(document, self._registry, self._kernel, self._handlers)
        copied._redo_stack = copy.deepcopy(self._redo_stack)
        if self._operation_revision == self._document.revision:
            copied._operation_undo = copy.deepcopy(self._operation_undo)
            copied._operation_redo = copy.deepcopy(self._operation_redo)
        return copied

    def apply_identity_upgrade(self, proposal: IdentityUpgrade) -> None:
        """Adopt the signed IDs atomically; stale/cancelled proposals change nothing."""
        self._ensure_healthy()
        if (
            proposal.document_id != self._document.document_id
            or proposal.revision != self._document.revision
            or not hmac.compare_digest(proposal.signature, self._upgrade_signature(proposal))
        ):
            raise ValidationError("identity upgrade proposal is stale or invalid")
        identities = (*proposal.active_ids, *proposal.redo_ids)
        if (
            len(proposal.active_ids) != len(self._document.commands)
            or len(proposal.redo_ids) != len(self._redo_stack)
            or len(set(identities)) != len(identities)
        ):
            raise ValidationError("identity upgrade proposal has mismatched identities")
        for identity in identities:
            require_instance_id(identity)
        if self._document.archive_version >= 5:
            return
        snapshot, redo = self._snapshot_state(), copy.deepcopy(self._redo_stack)
        self._document.events.begin_transaction()
        rebuild_started = False
        try:
            adopt = cast(
                "Callable[[tuple[str, ...]], None]",
                getattr(self._document, "_adopt_command_identities"),  # noqa: B009
            )
            adopt(proposal.active_ids)
            self._redo_stack = [
                replace(command, instance_id=identity)
                for command, identity in zip(self._redo_stack, proposal.redo_ids, strict=True)
            ]
            from mycad.core.persistence import document_payload

            document_payload(self._document)
            rebuild_started = True
            self._rebuild()
            self._advance_document_revision()
            self._invalidate_operations()
            self._document.events.commit_transaction()
        except Exception as original:
            if rebuild_started:
                self._restore_and_rebuild(snapshot, redo, original, "identity upgrade")
            else:
                self._restore_without_rebuild(snapshot, redo, original, "identity upgrade")
            raise

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
        operation_before = self._prepare_operation()
        document_snapshot = self._snapshot_state()
        redo_snapshot = copy.deepcopy(self._redo_stack)
        handler_started = False

        def mark_handler_started() -> None:
            nonlocal handler_started
            handler_started = True

        self._document.events.begin_transaction()
        try:
            archive = params.get("archive")
            upgraded = False
            reference_version = (
                cast("Mapping[str, object]", archive).get("version")
                if isinstance(archive, Mapping)
                else None
            )
            if (
                command_id in ("reference.attach", "reference.update")
                and type(reference_version) is int
                and reference_version in (7, 8)
                and self._document.archive_version < reference_version
            ):
                from mycad.core.document_references import DocumentReference

                DocumentReference.from_mapping(params)
                if self._document.archive_version < 5:
                    identities = self.prepare_identity_upgrade()
                    adopt_ids = cast(
                        "Callable[[tuple[str, ...]], None]",
                        getattr(self._document, "_adopt_command_identities"),  # noqa: B009
                    )
                    adopt_ids(identities.active_ids)
                    self._redo_stack = [
                        replace(command, instance_id=identity)
                        for command, identity in zip(
                            self._redo_stack, identities.redo_ids, strict=True
                        )
                    ]
                adopt_version = cast(
                    "Callable[[int], None]",
                    getattr(self._document, "_adopt_archive_version"),  # noqa: B009
                )
                adopt_version(reference_version)
                operation_before = self._operation_state()
                handler_started = True
                self._rebuild()
                upgraded = True
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
            if upgraded:
                self._invalidate_operations()
            self._record_operation(operation_before)
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
        instance_id: str | None = None,
        on_handler_start: Callable[[], None] | None = None,
    ) -> object | None:
        """The ONE pipeline: validate -> normalize -> handler (fixed order)."""
        from mycad.commands.validation import normalize_params, validate_params

        if command_id == "sketch.create" and version is None and "support" not in params:
            version = 3
        if command_id == "sketch.constraint.add" and version is None:
            version = 3
        if command_id == "sketch.constraint.update" and version is None:
            version = 1
        if command_id == "drawing.sketch.revise" and version is None:
            version = 3
        if command_id == "drawing.tangency.add" and version is None:
            version = 1
        spec = self._registry.get(command_id, version)
        if (
            record
            and command_id.startswith("drawing.raster.")
            or "raster_batch" in params
            or "clipboard_styles" in params
        ) and self._document.document_type != "drawing2d":
            raise ValidationError("图纸图片只支持独立二维文档。")
        if (
            record
            and command_id
            in {
                "drawing.fillet_radius.set",
                "drawing.chamfer_values.set",
                "drawing.dimension_styles.set",
                "drawing.clipboard.prepare",
            }
            and self._document.document_type != "drawing2d"
        ):
            raise ValidationError("二维图纸设置只支持独立二维文档。")
        if (
            command_id.startswith("drawing.array.")
            or (
                command_id in ("sketch.create", "drawing.sketch.revise")
                and "associative_arrays" in params
            )
        ) and self._document.document_type != "drawing2d":
            raise ValidationError("关联阵列目前只支持独立二维文档。")
        if (
            spec.min_archive_version >= 5
            and spec.min_archive_version > self._document.archive_version
        ):
            raise ValidationError("command requires an explicit compatible archive upgrade")
        if self._document.archive_version >= 5:
            instance_id = uuid4().hex if record else require_instance_id(instance_id)
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
        if is_bound_hole(command_id, normalized) and self._document.archive_version < 5:
            raise ValidationError("bound face holes require explicit archive v5 identity upgrade")
        if is_bound_hole(command_id, normalized):
            validate_hole_binding(
                normalized, ordinal=self._document.command_count if record else None
            )
        if command_id in ("reference.attach", "reference.update"):
            from mycad.core.document_references import DocumentReference, validate_reference_tree

            reference = DocumentReference.from_mapping(normalized)
            if cast("int", reference.archive["version"]) > self._document.archive_version:
                raise ValidationError("reference requires a compatible archive upgrade")
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
            instance_id=instance_id,
        )
        if on_handler_start is not None:
            on_handler_start()
        try:
            result = handler.handle(normalized, ctx)
        except TopologyReferenceError as exc:
            if record and is_bound_hole(command_id, normalized) and exc.ordinal is None:
                raise TopologyReferenceError(
                    exc.message,
                    command_id=command_id,
                    ordinal=self._document.command_count,
                    reason=exc.reason,
                    parameter_path=exc.parameter_path,
                ) from exc
            raise
        if record:
            self._append_command(
                ExecutedCommand(
                    id=command_id,
                    version=spec.version,
                    params=dict(normalized),
                    ordinal=self._document.command_count,
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    confirmed_by=confirmed_by,
                    instance_id=instance_id,
                )
            )
            self._document.events.emit(
                "post_command",
                {
                    "command_id": command_id,
                    "command_version": spec.version,
                    "ordinal": self._document.command_count - 1,
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
            self._invalidate_operations()
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
            self._invalidate_operations()
            self._document.events.commit_transaction()
        except Exception as original:
            self._restore_and_rebuild(document_snapshot, redo_snapshot, original, "redo")
            raise

    def _reset_kernel(self) -> None:
        self._kernel.reset()
        if self._document.archive_version >= 7 and self._document.document_type == "drawing2d":
            if not isinstance(self._kernel, DrawingBaselineKernel):
                raise ValidationError("kernel does not support drawing baseline replay")
            self._kernel.set_drawing_fillet_baseline(self._document.drawing_fillet_baseline)
        if self._document.archive_version >= 8 and self._document.document_type == "drawing2d":
            if not isinstance(self._kernel, ChamferBaselineKernel):
                raise ValidationError("kernel does not support chamfer baseline replay")
            self._kernel.set_drawing_chamfer_angle_baseline(
                self._document.drawing_chamfer_angle_baseline
            )

    def _rebuild(self) -> None:
        """Reset the kernel, replay the history (record=False), notify once."""
        self._reset_kernel()
        for cmd in self._document.commands:
            try:
                self._execute_one(
                    cmd.id,
                    cmd.params,
                    cmd.confirmed_by,
                    version=cmd.version,
                    record=False,
                    instance_id=cmd.instance_id,
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

    def replay_for_candidate(self) -> ReplayFailure | None:
        """Replay a detached candidate and return its first structured failure."""
        self._ensure_healthy()
        self._reset_kernel()
        last_successful_ordinal: int | None = None
        for command in self._document.commands:
            try:
                self._execute_one(
                    command.id,
                    command.params,
                    command.confirmed_by,
                    version=command.version,
                    record=False,
                    instance_id=command.instance_id,
                )
            except Exception as exc:
                parameter_path = (
                    exc.parameter_path if isinstance(exc, TopologyReferenceError) else None
                )
                if isinstance(exc, TopologyReferenceError):
                    reason = exc.reason or exc.message
                elif isinstance(exc, MycadError):
                    reason = exc.message
                else:
                    reason = str(exc)
                if not reason.strip():
                    reason = type(exc).__name__
                return ReplayFailure(
                    command_id=command.id,
                    command_version=command.version,
                    instance_id=command.instance_id,
                    ordinal=command.ordinal,
                    parameter_path=parameter_path,
                    reason=reason,
                    last_successful_ordinal=last_successful_ordinal,
                )
            last_successful_ordinal = command.ordinal
        return None

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
        operation_before = self._prepare_operation()
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
            self._redo_stack.clear()
            self._record_operation(operation_before)
            self._document.events.commit_transaction()
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
        operation_before = self._prepare_operation()
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
        self._redo_stack.clear()
        self._record_operation(operation_before)
        self._document.events.commit_transaction()
