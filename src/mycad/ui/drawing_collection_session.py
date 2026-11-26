# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Session-local collection operations backed by isolated replay candidates."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from mycad import app
from mycad.core.drawing_groups import DrawingObjectRef
from mycad.core.drawing_object_refs import unmapped_group_memberships
from mycad.core.drawing_object_refs import unmapped_group_replacements as find_unmapped_replacements
from mycad.core.exceptions import ValidationError
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet

if TYPE_CHECKING:
    from mycad.core.drawing_collection_clipboard import DrawingCollectionClipboard
    from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
    from mycad.core.persistence import LoadedDocument
    from mycad.core.sketch import Point2D, Sketch, SketchEntity, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint

_ALLOWED = frozenset(
    {
        "drawing.objects.batch",
        "drawing.group.create",
        "drawing.group.update",
        "drawing.group.remove",
        "drawing.block_library.bind",
        "drawing.block.create",
        "drawing.block.update",
        "drawing.block.remove",
        "drawing.block_instance.insert",
        "drawing.block_instance.update",
        "drawing.block_instance.remove",
        "drawing.block_instance.explode",
        "drawing.sketch.revise",
        "drawing.tangency.add",
        "drawing.tangency.remove",
        "sketch.constraint.add",
        "sketch.constraint.update",
        "drawing.text.add",
        "drawing.text.update",
        "drawing.text.remove",
        "drawing.text.batch",
        "drawing.raster.batch",
        "drawing.tolerance.batch",
        "drawing.reference_dimensions.batch",
    }
)


def unmapped_group_replacements(
    before: DrawingCollectionSnapshot,
    after: DrawingCollectionSnapshot,
    operation: ReplayAppend,
) -> tuple[DrawingObjectRef, ...]:
    """Find removed group geometry when a revision supplies no explicit mapping."""
    return find_unmapped_replacements(
        before.sketches,
        before.groups,
        after.sketches,
        operation.command_id,
        operation.params,
    )


@dataclass(frozen=True, slots=True)
class DrawingCollectionCheckpoint:
    """Frozen operation history retained by one canvas undo state."""

    owner: str
    draft: str
    steps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DrawingCollectionTransformPreview:
    """A frozen candidate operation and the exact state it was prepared against."""

    checkpoint: DrawingCollectionCheckpoint
    seeds: frozenset[DrawingObjectRef]
    frame: WorkPlaneFrame
    displacement: Point2D
    copy_source: bool
    operation: ReplayAppend
    payload: DrawingCollectionClipboard


@dataclass(frozen=True, slots=True)
class DrawingCollectionPastePreview:
    """A paste candidate with identities shared by preview and commit."""

    checkpoint: DrawingCollectionCheckpoint
    frame: WorkPlaneFrame
    displacement: Point2D
    source: DrawingCollectionClipboard
    operation: ReplayAppend
    payload: DrawingCollectionClipboard


@dataclass(frozen=True, slots=True)
class DrawingCollectionAffinePreview:
    """Read-only candidate projection for a rotation or uniform scale."""

    checkpoint: DrawingCollectionCheckpoint
    seeds: frozenset[DrawingObjectRef]
    frame: WorkPlaneFrame
    kind: str
    center: Point2D
    value: float
    copy_source: bool
    operation: ReplayAppend
    payload: DrawingCollectionClipboard


@dataclass(frozen=True, slots=True)
class DrawingCollectionMirrorPreview:
    """A mirrored candidate and its frozen geometry or copy identities."""

    checkpoint: DrawingCollectionCheckpoint
    seeds: frozenset[DrawingObjectRef]
    frame: WorkPlaneFrame
    start: Point2D
    end: Point2D
    copy_source: bool
    operation: ReplayAppend
    payload: DrawingCollectionClipboard


def _encode_operation(operation: ReplayAppend) -> str:
    return json.dumps(
        {
            "id": operation.command_id,
            "version": operation.version,
            "params": operation.params,
            "confirmed_by": operation.confirmed_by,
        },
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )


def _decode_operation(value: str) -> ReplayAppend:
    item = json.loads(value)
    return ReplayAppend(item["id"], item["version"], item["params"], item["confirmed_by"])


def _contains_identity(value: object, identity: str) -> bool:
    if isinstance(value, str):
        return value == identity
    if isinstance(value, dict):
        return any(
            _contains_identity(item, identity)
            for item in cast("dict[object, object]", value).values()
        )
    if isinstance(value, list | tuple):
        return any(_contains_identity(item, identity) for item in cast("Sequence[object]", value))
    return False


class DrawingCollectionSession:
    """Keep a draft and each collection edit detached until a candidate commits."""

    def __init__(
        self,
        services: app.AppServices,
        loaded: LoadedDocument,
        draft: ReplayAppend,
        *,
        session_identity: int,
        session_identity_provider: Callable[[], int] | None = None,
    ) -> None:
        if loaded.document.document_kind != "sketch" or draft.command_id != "sketch.create":
            raise ValidationError("二维暂存需要独立草图文档及草图创建命令。")
        self._services = services
        self._loaded = loaded
        self._draft = deepcopy(draft)
        self._session_identity = session_identity
        self._session_identity_provider = session_identity_provider
        self._identity = uuid4().hex
        self._revision = loaded.document.revision
        self._steps: tuple[ReplayAppend, ...] = ()
        self._redo: tuple[ReplayAppend, ...] = ()
        self._candidate: app.ReplayCandidateSession | None = None
        self._snapshot: DrawingCollectionSnapshot | None = None
        self._closed = False
        self._write_guard: str | None = None
        self._committed_with_write_guard = False
        self._save_recovery_failed = False
        self._pending_commit_canvas_rebind: tuple[int, int] | None = None
        self._rebuild(())

    def guard_document_writes(self) -> None:
        """Prevent source writes while this session owns the visible draft."""
        self._check()
        if self._write_guard is not None:
            raise ValidationError("二维暂存写入保护已启用。")
        self._write_guard = self._loaded.bus.acquire_drawing_write_guard()

    def _check(self, *, allow_pending_canvas_rebind: bool = False) -> None:
        if self._closed:
            raise ValidationError("二维暂存会话已关闭。")
        if (
            self._session_identity_provider is not None
            and self._session_identity_provider() != self._session_identity
        ):
            raise ValidationError("应用会话已变化，请重新开始暂存操作。")
        if self._loaded.document.revision != self._revision:
            raise ValidationError("源文档已变化，请重新开始暂存操作。")
        if self._pending_commit_canvas_rebind is not None and not allow_pending_canvas_rebind:
            raise ValidationError("二维暂存画布尚未恢复，请再次完成草稿重试。")

    @property
    def snapshot(self) -> DrawingCollectionSnapshot:
        self._check()
        if self._snapshot is None:
            raise ValidationError("二维暂存快照不可用。")
        return self._snapshot

    @property
    def has_staged_operations(self) -> bool:
        """Report draft ownership without consulting the active workspace."""
        return (not self._closed or self._save_recovery_failed) and bool(self._steps)

    def retain_failed_save_recovery(self) -> None:
        """Keep an unsuccessfully recovered draft visible as unsaved work."""
        if self._closed:
            self._save_recovery_failed = True
            if self._write_guard is None:
                self._write_guard = self._loaded.bus.acquire_drawing_write_guard()

    def restore_save_checkpoint(self, checkpoint: str, expected_revision: int) -> None:
        """Restore the source checkpoint while retaining the session's write protection."""
        self._loaded.bus.restore_save_checkpoint(
            checkpoint, expected_revision=expected_revision, drawing_write_guard=self._write_guard
        )

    def discard_failed_save_recovery(self) -> None:
        """Release retained protection when the user discards a failed save."""
        if not self._closed:
            self.cancel()
            return
        if self._save_recovery_failed and self._closed and self._write_guard is not None:
            self._loaded.bus.release_drawing_write_guard(self._write_guard)
            self._write_guard = None
            self._save_recovery_failed = False

    def rebind_workspace(
        self, services: app.AppServices, loaded: LoadedDocument, session_identity: int
    ) -> None:
        """Rebuild the candidate when its original live document becomes active again."""
        if self._closed or services is not self._services or loaded is not self._loaded:
            raise ValidationError("二维暂存所属文档已变化。")
        if self._loaded.document.revision != self._revision:
            raise ValidationError("源文档已变化，请保留或取消原暂存。")
        if (
            self._session_identity_provider is not None
            and self._session_identity_provider() != session_identity
        ):
            raise ValidationError("应用会话已变化，无法恢复二维暂存。")
        previous = self._session_identity
        self._session_identity = session_identity
        pending_rebind = self._pending_commit_canvas_rebind
        self._pending_commit_canvas_rebind = None
        try:
            self._rebuild(self._steps)
        except Exception:
            self._session_identity = previous
            raise
        finally:
            self._pending_commit_canvas_rebind = pending_rebind

    def rebind_after_failed_commit(self, source_revision: int, session_identity: int) -> None:
        """Rebuild an open draft after its candidate was rolled back by the Bus."""
        if (
            self._closed
            or self._revision != source_revision
            or self._session_identity != session_identity
            or (
                self._session_identity_provider is not None
                and self._session_identity_provider() != session_identity
            )
            or not self._loaded.bus.candidate_rolled_back_from(source_revision)
        ):
            raise ValidationError("无法验证二维暂存提交的回滚状态。")
        self._revision = self._loaded.document.revision
        try:
            self._rebuild(self._steps)
        except Exception:
            self._revision = source_revision
            raise
        self._pending_commit_canvas_rebind = (source_revision, self._revision)

    def complete_failed_commit_canvas_rebind(self, revisions: tuple[int, int]) -> None:
        """Acknowledge canvas history rebinding after candidate recovery."""
        self._check(allow_pending_canvas_rebind=True)
        if self._pending_commit_canvas_rebind != revisions:
            raise ValidationError("二维暂存画布恢复状态已变化。")
        self._pending_commit_canvas_rebind = None

    def retry_failed_commit_recovery(self) -> tuple[int, int] | None:
        """Retry a verified rollback recovery before finishing the retained draft."""
        if self._pending_commit_canvas_rebind is not None:
            self._check(allow_pending_canvas_rebind=True)
            return self._pending_commit_canvas_rebind
        if self._revision == self._loaded.document.revision:
            return None
        previous = self._revision
        try:
            self.rebind_after_failed_commit(previous, self._session_identity)
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(f"二维暂存恢复失败：{exc}") from exc
        return previous, self._revision

    def restore_after_save_failure(
        self,
        services: app.AppServices,
        loaded: LoadedDocument,
        previous_revision: int,
        revision: int,
        session_identity: int,
    ) -> None:
        """Recreate a committed candidate after the Bus restored its save checkpoint."""
        if not self._closed:
            if (
                services is not self._services
                or loaded is not self._loaded
                or self._revision != previous_revision
                or loaded.document.revision != revision
                or (
                    self._session_identity_provider is not None
                    and self._session_identity_provider() != session_identity
                )
            ):
                raise ValidationError("无法恢复所属文档的二维暂存会话。")
            if self._revision == revision and self._session_identity == session_identity:
                self._check()
                return
            old_revision, old_identity = self._revision, self._session_identity
            self._revision, self._session_identity = revision, session_identity
            try:
                self._rebuild(self._steps)
            except Exception:
                self._revision, self._session_identity = old_revision, old_identity
                raise
            return
        if (
            self._candidate is not None
            or services is not self._services
            or loaded is not self._loaded
            or self._revision != previous_revision
            or loaded.document.revision != revision
            or (
                self._session_identity_provider is not None
                and self._session_identity_provider() != session_identity
            )
        ):
            raise ValidationError("无法恢复所属文档的二维暂存会话。")
        old_identity = self._session_identity
        self._closed = False
        self._revision = revision
        self._session_identity = session_identity
        try:
            self._rebuild(self._steps)
            if self._committed_with_write_guard and self._write_guard is None:
                self.guard_document_writes()
        except Exception:
            if self._candidate is not None:
                self._candidate.cancel()
            self._candidate = None
            self._snapshot = None
            self._closed = True
            self._revision = previous_revision
            self._session_identity = old_identity
            raise
        self._committed_with_write_guard = False
        self._save_recovery_failed = False

    def _build_candidate(
        self, steps: tuple[ReplayAppend, ...]
    ) -> tuple[app.ReplayCandidateSession, DrawingCollectionSnapshot]:
        self._check()
        candidate = app.create_replay_candidate(
            self._services, self._loaded, session_identity=self._session_identity
        )
        try:
            candidate.stage(
                ReplayChangeSet(
                    (),
                    (self._draft, *steps),
                    False,
                    target_archive_version=8,
                    undo_appends_separately=True,
                ),
                current_session_identity=self._session_identity,
            )
            preview = candidate.preview(current_session_identity=self._session_identity)
            if preview.state != "succeeded":
                raise ValidationError(str(preview.failure or "暂存候选预览失败。"))
            snapshot = candidate.drawing_collection_snapshot(
                current_session_identity=self._session_identity
            )
        except Exception:
            candidate.cancel()
            raise
        return candidate, snapshot

    def _rebuild(self, steps: tuple[ReplayAppend, ...]) -> None:
        candidate, snapshot = self._build_candidate(steps)
        if self._candidate is not None:
            self._candidate.cancel()
        self._candidate = candidate
        self._snapshot = snapshot

    def stage(self, operation: ReplayAppend) -> tuple[tuple[str, DrawingObjectRef], ...]:
        self._check()
        if operation.command_id not in _ALLOWED:
            raise ValidationError("暂存会话不支持此操作。")
        before = self.snapshot
        steps = (*self._steps, deepcopy(operation))
        self._rebuild(steps)
        self._steps, self._redo = steps, ()
        return unmapped_group_memberships(
            before.sketches,
            before.groups,
            self.snapshot.sketches,
            operation.command_id,
            operation.params,
        )

    def preview_operation(self, operation: ReplayAppend) -> DrawingCollectionSnapshot:
        """Evaluate a frozen operation in a disposable candidate without changing history."""
        self._check()
        if operation.command_id not in _ALLOWED:
            raise ValidationError("暂存会话不支持此操作。")
        candidate, snapshot = self._build_candidate((*self._steps, deepcopy(operation)))
        candidate.cancel()
        return snapshot

    def prepare_affine_copy(
        self,
        seeds: tuple[DrawingObjectRef, ...],
        frame: WorkPlaneFrame,
        center: Point2D,
        kind: str,
        value: float,
    ) -> ReplayAppend:
        """Freeze a copy and its transform as one replayable document operation."""
        from mycad.core.drawing_transactions import (
            prepare_collection_copy,
            prepare_collection_rotation,
            prepare_collection_scale,
        )
        from mycad.core.sketch_constraints import DIMENSION_KINDS

        def references(snapshot: DrawingCollectionSnapshot) -> tuple[DrawingObjectRef, ...]:
            return (
                *(
                    DrawingObjectRef("geometry", item.entity_id, sketch.sketch_id)
                    for sketch in snapshot.sketches
                    for item in sketch.entities
                ),
                *(
                    DrawingObjectRef("dimension", item.constraint_id, sketch.sketch_id)
                    for sketch in snapshot.sketches
                    for item in sketch.constraints
                    if item.kind in DIMENSION_KINDS
                ),
                *(DrawingObjectRef("text", item.text_id) for item in snapshot.texts),
                *(DrawingObjectRef("raster", item.image_id) for item in snapshot.rasters),
                *(DrawingObjectRef("tolerance", item.frame_id) for item in snapshot.frames),
                *(DrawingObjectRef("datum", item.datum_id) for item in snapshot.datums),
                *(
                    DrawingObjectRef("reference_dimension", item.dimension_id)
                    for item in snapshot.reference_dimensions
                ),
                *(
                    DrawingObjectRef("block_instance", item.instance_id)
                    for item in snapshot.block_instances
                ),
            )

        before = self.snapshot
        copy = prepare_collection_copy(before, seeds, frame, (0, 0))
        if (kind == "scale" and value == 1) or (kind == "rotate" and value % 360 == 0):
            return copy
        copied = self.preview_operation(copy)
        existing = frozenset(references(before))
        copied_refs = tuple(ref for ref in references(copied) if ref not in existing)
        if kind == "rotate":
            transform = prepare_collection_rotation(copied, copied_refs, frame, center, value)
        elif kind == "scale":
            transform = prepare_collection_scale(copied, copied_refs, frame, center, value)
        else:
            raise ValidationError("不支持的组副本变换。")
        operations = [
            *cast("list[object]", copy.params["operations"]),
            *cast("list[object]", transform.params["operations"]),
        ]
        return ReplayAppend("drawing.objects.batch", 1, {"operations": operations}, "local")

    def prepare_draft_with_cross_tangencies(
        self,
        draft_sketch_id: str,
        entities: tuple[SketchEntity, ...],
        constraints: tuple[SketchConstraint, ...],
        pairs: tuple[app.DraftTangentPair, ...],
        member_mapping: dict[str, tuple[str, ...]] | None = None,
    ) -> ReplayAppend:
        """Prepare a draft edit and its new saved-source relations as one operation."""
        from dataclasses import replace

        from mycad.core.drawing_transactions import prepare_grouped_sketch_replacements

        snapshot = self.snapshot
        draft = next(
            (item for item in snapshot.sketches if item.sketch_id == draft_sketch_id), None
        )
        if draft is None:
            raise ValidationError("暂存草稿不存在。")
        target = replace(draft, entities=entities, constraints=constraints)
        saved = tuple(item for item in snapshot.sketches if item.sketch_id != draft_sketch_id)
        cross_tangencies = app.draft_cross_relations(saved, target, pairs)
        mapping = {
            DrawingObjectRef("geometry", identity, draft_sketch_id): tuple(
                DrawingObjectRef("geometry", result, draft_sketch_id) for result in results
            )
            for identity, results in (member_mapping or {}).items()
        }
        return prepare_grouped_sketch_replacements(
            (draft,), (target,), snapshot.groups, mapping, cross_tangencies=cross_tangencies
        )

    def validate_draft_dependencies(
        self,
        draft_sketch_id: str,
        pairs: tuple[app.DraftTangentPair, ...],
        arrays: tuple[app.AssociativeRectArray, ...],
    ) -> None:
        """Require legacy canvas dependency lists to match the staged candidate."""
        snapshot = self.snapshot
        draft = next(
            (item for item in snapshot.sketches if item.sketch_id == draft_sketch_id), None
        )
        if draft is None:
            raise ValidationError("暂存草稿不存在。")
        saved = tuple(item for item in snapshot.sketches if item.sketch_id != draft_sketch_id)
        try:
            relations = app.draft_cross_relations(saved, draft, pairs)
        except (ValidationError, ValueError) as exc:
            raise ValidationError(f"草稿关联无效：{exc}") from exc
        if any(item not in snapshot.cross_tangencies for item in relations) or any(
            item not in snapshot.associative_arrays for item in arrays
        ):
            raise ValidationError("草稿关联与暂存结果不一致，请先同步或撤销关联修改。")

    def prepare_attached_move(
        self,
        seeds: tuple[DrawingObjectRef, ...],
        frame: WorkPlaneFrame,
        delta: tuple[float, float],
    ) -> ReplayAppend:
        self._check()
        if self._candidate is None:
            raise ValidationError("暂存候选不可用。")
        return self._candidate.prepare_attached_collection_move(
            seeds, frame, delta, current_session_identity=self._session_identity
        )

    def undo(self) -> None:
        self._check()
        if not self._steps:
            raise ValidationError("没有可撤销的暂存操作。")
        self._rebuild(self._steps[:-1])
        self._redo = (*self._redo, self._steps[-1])
        self._steps = self._steps[:-1]

    def redo(self) -> None:
        self._check()
        if not self._redo:
            raise ValidationError("没有可重做的暂存操作。")
        steps = (*self._steps, self._redo[-1])
        self._rebuild(steps)
        self._steps, self._redo = steps, self._redo[:-1]

    def checkpoint(self) -> DrawingCollectionCheckpoint:
        self._check()
        return DrawingCollectionCheckpoint(
            self._identity,
            _encode_operation(self._draft),
            tuple(_encode_operation(operation) for operation in self._steps),
        )

    def rebase_draft(
        self,
        sketch: Sketch,
        *,
        cross_tangent_pairs: tuple[app.DraftTangentPair, ...] | None = None,
        associative_arrays: tuple[app.AssociativeRectArray, ...] | None = None,
    ) -> None:
        """Restore a canvas history state preceding the creation of this session."""
        self._check()
        if self._steps or self._draft.params.get("sketch_id") != sketch.sketch_id:
            raise ValidationError("不能在已有暂存操作上替换草稿基线。")
        params = deepcopy(dict(self._draft.params))
        params.update(sketch.to_state_mapping())
        if cross_tangent_pairs is not None:
            if cross_tangent_pairs:
                saved = tuple(
                    item for item in self.snapshot.sketches if item.sketch_id != sketch.sketch_id
                )
                params["cross_tangencies"] = [
                    relation.to_mapping()
                    for relation in app.draft_cross_relations(saved, sketch, cross_tangent_pairs)
                ]
            else:
                params.pop("cross_tangencies", None)
        if associative_arrays is not None:
            if associative_arrays:
                params["associative_arrays"] = [array.to_mapping() for array in associative_arrays]
            else:
                params.pop("associative_arrays", None)
        draft = ReplayAppend(
            self._draft.command_id,
            self._draft.version,
            params,
            self._draft.confirmed_by,
        )
        previous = self._draft
        self._draft = draft
        try:
            self._rebuild(())
        except Exception:
            self._draft = previous
            raise
        self._redo = ()

    def adopt_mixed_history(
        self,
        initial_draft: Sketch,
        original_saved: tuple[Sketch, ...],
        steps: tuple[tuple[tuple[Sketch, ...], Sketch], ...],
        *,
        cross_pairs_by_step: tuple[tuple[app.DraftTangentPair, ...], ...],
        initial_cross_pairs: tuple[app.DraftTangentPair, ...],
        arrays_by_step: tuple[tuple[app.AssociativeRectArray, ...], ...],
        initial_arrays: tuple[app.AssociativeRectArray, ...],
        transforms_by_step: tuple[tuple[app.RectangleTransformEvidence, ...], ...],
    ) -> tuple[DrawingCollectionCheckpoint, ...]:
        """Import a validated legacy mixed timeline without committing the source."""
        self._check()
        if self._steps or self._write_guard is not None:
            raise ValidationError("已有暂存操作，不能导入混合历史。")
        candidate = app.stage_mixed_drawing_timeline(
            self._services,
            self._loaded,
            initial_draft,
            original_saved,
            steps,
            session_identity=self._session_identity,
            cross_pairs_by_step=cross_pairs_by_step,
            initial_cross_pairs=initial_cross_pairs,
            arrays_by_step=arrays_by_step,
            initial_associative_arrays=initial_arrays,
            rectangle_transforms_by_step=transforms_by_step,
        )
        try:
            preview = candidate.preview(current_session_identity=self._session_identity)
            changes = candidate.staged_changes
            if preview.state != "succeeded" or changes is None:
                raise ValidationError(str(preview.failure or "混合历史预览失败。"))
            appends = changes.appends
            if (
                changes.replacements
                or not appends
                or appends[0].command_id != "sketch.create"
                or appends[0].params.get("sketch_id") != self._draft.params.get("sketch_id")
                or any(item.command_id not in _ALLOWED for item in appends[1:])
                or len(appends) != len(steps) + 1
            ):
                raise ValidationError("混合历史与撤销步骤无法一一对应。")
            previous = self._draft
            self._draft = deepcopy(appends[0])
            pending_candidate: app.ReplayCandidateSession | None = None
            try:
                candidate_steps = tuple(deepcopy(item) for item in appends[1:])
                checkpoints: list[DrawingCollectionCheckpoint] = []
                final_snapshot: DrawingCollectionSnapshot | None = None
                for count in range(len(candidate_steps) + 1):
                    next_candidate, final_snapshot = self._build_candidate(candidate_steps[:count])
                    if pending_candidate is not None:
                        pending_candidate.cancel()
                    pending_candidate = next_candidate
                    checkpoints.append(
                        DrawingCollectionCheckpoint(
                            self._identity,
                            _encode_operation(self._draft),
                            tuple(_encode_operation(item) for item in candidate_steps[:count]),
                        )
                    )
                assert pending_candidate is not None and final_snapshot is not None
            except Exception:
                self._draft = previous
                if pending_candidate is not None:
                    pending_candidate.cancel()
                raise
            if self._candidate is not None:
                self._candidate.cancel()
            self._candidate = pending_candidate
            self._snapshot = final_snapshot
            self._steps, self._redo = candidate_steps, ()
            return tuple(checkpoints)
        finally:
            candidate.cancel()

    def restore(self, checkpoint: DrawingCollectionCheckpoint) -> None:
        self._check()
        if checkpoint.owner != self._identity:
            raise ValidationError("暂存检查点属于其他会话。")
        try:
            draft = _decode_operation(checkpoint.draft)
            steps = tuple(_decode_operation(value) for value in checkpoint.steps)
        except (TypeError, ValueError, KeyError) as exc:
            raise ValidationError("暂存检查点无效。") from exc
        if (
            draft.command_id != "sketch.create"
            or draft.version != self._draft.version
            or draft.confirmed_by != self._draft.confirmed_by
            or draft.params.get("sketch_id") != self._draft.params.get("sketch_id")
            or any(step.command_id not in _ALLOWED for step in steps)
        ):
            raise ValidationError("暂存检查点包含不支持的操作。")
        previous = self._draft
        self._draft = draft
        try:
            self._rebuild(steps)
        except Exception:
            self._draft = previous
            raise
        self._steps, self._redo = steps, ()

    def commit(self) -> None:
        self._check()
        candidate = self._candidate
        if candidate is None:
            raise ValidationError("暂存候选不可用。")
        if not self._draft.params.get("entities") and not self._steps:
            self.cancel()
            return
        original_candidate = candidate
        # An empty canvas is still needed as a transient projection.  When the
        # operation history can replay without it, do not persist a dummy sketch.
        draft_id = self._draft.params.get("sketch_id")
        can_omit_draft = (
            not self._draft.params.get("entities")
            and isinstance(draft_id, str)
            and not any(_contains_identity(operation.params, draft_id) for operation in self._steps)
        )
        if can_omit_draft:
            without_draft = app.create_replay_candidate(
                self._services, self._loaded, session_identity=self._session_identity
            )
            try:
                without_draft.stage(
                    ReplayChangeSet(
                        (),
                        self._steps,
                        False,
                        target_archive_version=8,
                        undo_appends_separately=True,
                    ),
                    current_session_identity=self._session_identity,
                )
                preview = without_draft.preview(current_session_identity=self._session_identity)
                if preview.state != "succeeded":
                    raise ValidationError(str(preview.failure or "无草稿候选预览失败。"))
                candidate = without_draft
            except Exception:
                without_draft.cancel()
                raise
        try:
            grant = candidate.authorize_commit(current_session_identity=self._session_identity)
            candidate.commit(
                grant,
                current_session_identity=self._session_identity,
                drawing_write_guard=self._write_guard,
            )
        except Exception:
            if candidate is not original_candidate:
                candidate.cancel()
            raise
        if candidate is not original_candidate:
            original_candidate.cancel()
        self._committed_with_write_guard = self._write_guard is not None
        if self._write_guard is not None:
            self._loaded.bus.release_drawing_write_guard(self._write_guard)
            self._write_guard = None
        self._closed = True
        self._candidate = None
        self._snapshot = None

    def cancel(self) -> None:
        if self._closed:
            raise ValidationError("二维暂存会话已关闭。")
        if self._candidate is not None:
            self._candidate.cancel()
        if self._write_guard is not None:
            self._loaded.bus.release_drawing_write_guard(self._write_guard)
            self._write_guard = None
        self._closed = True
        self._candidate = None
        self._snapshot = None
