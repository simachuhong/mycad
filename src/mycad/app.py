# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Composition root (T7c): the single place that knows every concrete type.

``build_app`` assembles the whole object graph — registry with the eight
built-in command specs, a geometry kernel, the format-provider registry and
the plugin manager. Desktop document sessions fork services so each editable
document owns its kernel; immutable registrations are shared.
"""

from __future__ import annotations

import importlib.metadata
import json
import math
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
from mycad.commands.registry import CommandRegistry
from mycad.core.associative_array import (
    ArrayEntityRef,
    AssociativeRectArray,
    erase_drawing_entities,
    has_interleaved_array_dependencies,
    has_internal_replacements,
    has_shared_replacement_anchor,
    propagate_array_changes,
    strip_erased_member_dimensions,
)
from mycad.core.bus import CommandBus
from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    DraftConnectedEndpoint,
    DraftTangentPair,
    RectangleTransformEvidence,
    build_tangency_revisions,
    draft_tangent_reference,
    has_rectangle_segment_tangency,
    infer_tangency_branch,
    is_retained_local_tangent_rebind,
    project_tangent_entity,
    rebind_committed_tangencies,
    rebind_committed_tangencies_for_edit,
    rebind_rectangle_constraints_for_sketch,
    relations_use_rectangle_segments,
    resolve_tangency_component,
    resolve_tangent_curve,
    split_transform_evidence,
    unique_unchanged_polyline_segment,
    validate_tangency_component,
)
from mycad.core.detached_dimension import DetachedDimension
from mycad.core.dimension_styles import DimensionStyleTable
from mycad.core.document import Document, ExecutedCommand
from mycad.core.document_kinds import DocumentKind, DocumentType, native_suffix
from mycad.core.document_migration import migrate_archive
from mycad.core.document_references import archive_fingerprint
from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
from mycad.core.drawing_groups import DrawingObjectRef
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.drawing_text import DrawingText, TextStyleTable
from mycad.core.exceptions import ValidationError
from mycad.core.geometric_tolerance import (
    AnnotationAttachment,
    DatumAttachment,
    DatumIdentifier,
    FeatureControlFrame,
)
from mycad.core.geometric_tolerance_copy import translate_frame
from mycad.core.handlers import BuiltinModelingHandler, CommandHandler
from mycad.core.identity import BodyId, TopologyId
from mycad.core.persistence import LoadedDocument, document_payload, load_document_payload
from mycad.core.persistence import open_document as _open_document
from mycad.core.replay_proposal import (
    ReplayAppend,
    ReplayCandidateProposal,
    ReplayCandidateState,
    ReplayChangeSet,
    ReplayCommitGrant,
    ReplayFailure,
)
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    EllipseEntity,
    PointEntity,
    PolylineEntity,
    Sketch,
    SketchEntity,
    SplineEntity,
    WorkPlaneFrame,
    new_sketch_identity,
)
from mycad.core.sketch_constraints import (
    DIMENSION_KINDS,
    SketchBranchChange,
    SketchConstraint,
    SketchGeometryReference,
)
from mycad.core.text_interchange import reconcile_text_style_ids, reconcile_text_styles
from mycad.core.viewport_protocol import (
    CandidateInteractionScene,
    PlanarFaceFrame,
    ViewportData,
    ViewportDatum,
    ViewportSketchData,
    ViewportSnapAnchor,
)
from mycad.formats.providers import DXF_PROVIDER, STEP_PROVIDER, STL_PROVIDER
from mycad.formats.registry import FormatProviderRegistry
from mycad.geom.cross_sketch_tangency import (
    solve_tangency_component,
    solve_tangency_component_anchored,
    solve_tangency_component_constraint,
)
from mycad.geom.drawing_worker import DrawingProjectionWorker
from mycad.geom.kernel import BuildKernel
from mycad.geom.sketch_branches import detect_branch_changes
from mycad.geom.sketch_constraints import validate_sketch_revision_geometry
from mycad.plugins.discovery import EntryPointDiscoverer
from mycad.plugins.loader import register_plugins
from mycad.plugins.manager import PluginManager
from mycad.plugins.types import DiscoveredPlugin, PluginDiscoverer

__all__ = [
    "AppServices",
    "build_app",
    "new_document",
    "open_app_document",
    "fork_app_services",
    "new_workspace_document",
    "open_session_documents",
    "open_session_bundle",
    "create_replay_candidate",
    "prepare_cross_sketch_tangency",
    "commit_cross_sketch_tangency",
    "commit_cross_sketch_edit",
    "prepare_cross_sketch_dimension",
    "commit_cross_sketch_dimension",
    "prepare_cross_sketch_drag",
    "commit_cross_sketch_drag",
    "prepare_mixed_handle_drag",
    "prepare_mixed_draft_tangency",
    "draft_cross_relations",
    "solve_mixed_draft_tangencies",
    "revisions_include_curved_polylines",
    "revisions_include_local_endpoint_constraints",
    "revisions_include_dimension_text",
    "revisions_include_dimension_styles",
    "revisions_include_dimension_tolerances",
    "revisions_include_projection_axes",
    "move_tolerance_selection",
    "stage_mixed_drawing_move",
    "stage_mixed_drawing_timeline",
    "ReplayCandidateSession",
    "ReplayCandidatePreview",
    "reference_parameters",
    "archive_plugin_identities",
    "preview_command",
    "preview_command_with_sketches",
    "interactive_selectors",
    "interactive_body_selectors",
]


@dataclass(frozen=True)
class AppServices:
    """Immutable service container assembled by ``build_app``.

    Exactly four members (pinned by contract): the command registry, the
    shared geometry kernel, the format-provider registry and the plugin
    manager. ``Document``/``CommandBus`` deliberately stay out — documents
    have a new/open lifecycle owned by the factory functions below.
    """

    registry: CommandRegistry
    kernel: BuildKernel
    formats: FormatProviderRegistry
    plugins: PluginManager


def drawing_collection_snapshot(services: AppServices) -> DrawingCollectionSnapshot:
    """Read a neutral collection projection from application services."""
    kernel = services.kernel
    return DrawingCollectionSnapshot(
        sketches=kernel.sketches,
        groups=kernel.drawing_groups,
        texts=kernel.drawing_texts,
        text_styles=kernel.drawing_text_styles,
        dimension_styles=kernel.drawing_dimension_styles,
        rasters=kernel.drawing_rasters,
        frames=kernel.drawing_tolerance_frames,
        datums=kernel.drawing_datum_identifiers,
        reference_dimensions=kernel.drawing_reference_dimensions,
        layers=kernel.drawing_layers,
        dimension_layer=kernel.dimension_layer,
        cross_tangencies=kernel.cross_sketch_tangencies,
        associative_arrays=kernel.associative_arrays,
        block_definitions=kernel.drawing_block_definitions,
        block_instances=kernel.drawing_block_instances,
        block_library_origins=kernel.drawing_block_library_origins,
    )


@dataclass(frozen=True)
class ReplayCandidatePreview:
    """Neutral display result from one isolated candidate generation."""

    state: ReplayCandidateState
    proposal: ReplayCandidateProposal
    viewport: ViewportData | None
    sketches: tuple[ViewportSketchData, ...]
    failure: ReplayFailure | None
    datums: tuple[ViewportDatum, ...] = ()
    snap_anchors: tuple[ViewportSnapAnchor, ...] = ()
    scene: CandidateInteractionScene | None = None
    failure_scene: CandidateInteractionScene | None = None


class ReplayCandidateSession:
    """Own one staged history proposal and its isolated replay resources."""

    def __init__(
        self,
        services: AppServices,
        loaded: LoadedDocument,
        *,
        session_identity: int,
    ) -> None:
        if type(session_identity) is not int or session_identity < 0:
            raise ValidationError("session_identity must be a non-negative integer")
        self._services = services
        self._loaded = loaded
        self._session_identity = session_identity
        self._source_document_id = loaded.document.document_id
        self._source_file_id = loaded.document.file_id
        self._source_revision = loaded.document.revision
        self._candidate_id = uuid4().hex
        self._generation = 0
        self._state: ReplayCandidateState = "ready"
        self._changes: ReplayChangeSet | None = None
        self._proposal: ReplayCandidateProposal | None = None
        self._latest_preview: ReplayCandidatePreview | None = None
        self._candidate_kernel: BuildKernel | None = None
        self._candidate_bus: CommandBus | None = None

    @property
    def state(self) -> ReplayCandidateState:
        """Current lifecycle state for the staged candidate."""
        return self._state

    @property
    def proposal(self) -> ReplayCandidateProposal | None:
        """Current frozen proposal, if one has been staged."""
        return self._proposal

    @property
    def staged_changes(self) -> ReplayChangeSet | None:
        """Return a detached copy of the staged command changes."""
        return deepcopy(self._changes)

    @property
    def latest_preview(self) -> ReplayCandidatePreview | None:
        """Latest completed candidate result, including an isolated failure prefix."""
        return self._latest_preview

    def _check_session(self, current_session_identity: int) -> None:
        if (
            type(current_session_identity) is not int
            or current_session_identity != self._session_identity
        ):
            raise ValidationError("candidate belongs to another application session")

    def _source_is_current(self) -> bool:
        document = self._loaded.document
        return (
            document.document_id == self._source_document_id
            and document.file_id == self._source_file_id
            and document.revision == self._source_revision
        )

    def is_scene_current(
        self, scene: CandidateInteractionScene, *, current_session_identity: int
    ) -> bool:
        """Reject a scene after stage, session change, cancellation or source edit."""
        preview = self._latest_preview
        return (
            current_session_identity == self._session_identity
            and self._state == "succeeded"
            and self._source_is_current()
            and preview is not None
            and preview.scene is scene
            and preview.proposal == self._proposal
        )

    def is_failure_scene_current(
        self, scene: CandidateInteractionScene, *, current_session_identity: int
    ) -> bool:
        """Keep a failed replay's isolated prefix separate from a successful scene."""
        preview = self._latest_preview
        return (
            current_session_identity == self._session_identity
            and self._state == "failed"
            and self._source_is_current()
            and preview is not None
            and preview.failure_scene is scene
            and preview.proposal == self._proposal
        )

    def _release_candidate(self) -> None:
        self._candidate_kernel = None
        self._candidate_bus = None
        self._latest_preview = None

    def stage(
        self,
        changes: ReplayChangeSet,
        *,
        current_session_identity: int,
    ) -> None:
        """Freeze a complete change set and invalidate prior result/pick state."""
        self._check_session(current_session_identity)
        if self._state in ("cancelled", "committed"):
            raise ValidationError(f"cannot stage a {self._state} candidate")
        if not self._source_is_current():
            self._state = "stale"
            self._proposal = None
            self._changes = None
            self._loaded.bus.discard_replay_candidate(self._candidate_id)
            self._release_candidate()
            raise ValidationError("candidate source document changed")
        next_generation = self._generation + 1
        proposal = self._loaded.bus.prepare_replay_proposal(
            changes,
            session_identity=self._session_identity,
            candidate_id=self._candidate_id,
            generation=next_generation,
        )
        self._release_candidate()
        self._generation = next_generation
        self._changes = changes
        self._proposal = proposal
        self._state = "ready"

    def _candidate_runtime(
        self,
        proposal: ReplayCandidateProposal,
        commands: tuple[ExecutedCommand, ...],
    ) -> tuple[BuildKernel, CommandBus]:
        registry = CommandRegistry(schema_defs=COMMAND_SCHEMA_DEFS)
        for spec in BUILTIN_COMMAND_SPECS:
            registry.register(spec)
        kernel = BuildKernel()
        _configure_reference_loader(kernel, registry, PluginManager(()))
        source = self._loaded.document
        document = Document(
            registry,
            metadata=source.metadata_snapshot(),
            commands=commands,
            named_groups=source.named_groups,
            archive_version=proposal.archive_version,
            document_type=source.document_type,
            document_kind=source.document_kind,
            file_id=source.file_id,
            migration_origin=source.migration_origin,
            reference_locations=source.reference_locations,
            drawing_fillet_baseline=source.drawing_fillet_baseline,
            drawing_chamfer_angle_baseline=source.drawing_chamfer_angle_baseline,
        )
        handlers = {
            (spec.id, spec.version): BuiltinModelingHandler(spec.id, spec.version)
            for spec in BUILTIN_COMMAND_SPECS
        }
        bus = CommandBus(document, registry, kernel, handlers)
        return kernel, bus

    @staticmethod
    def _first_unsupported_command(
        proposal: ReplayCandidateProposal,
    ) -> ReplayFailure | None:
        supported = frozenset((spec.id, spec.version) for spec in BUILTIN_COMMAND_SPECS)
        last_successful: int | None = None
        for command in proposal.commands:
            if (command.id, command.version) not in supported:
                return ReplayFailure(
                    command_id=command.id,
                    command_version=command.version,
                    instance_id=command.instance_id,
                    ordinal=command.ordinal,
                    parameter_path=None,
                    reason="unsupported-command",
                    last_successful_ordinal=last_successful,
                )
            last_successful = command.ordinal
        return None

    def _prefix_result(
        self,
        proposal: ReplayCandidateProposal,
        failure: ReplayFailure,
    ) -> tuple[
        BuildKernel,
        ViewportData | None,
        tuple[ViewportSketchData, ...],
        ReplayFailure,
    ]:
        current_failure = failure
        current_commands = proposal.commands
        while True:
            failed_position = next(
                (
                    index
                    for index, command in enumerate(current_commands)
                    if command.ordinal == current_failure.ordinal
                ),
                None,
            )
            if failed_position is None:
                kernel, _bus = self._candidate_runtime(proposal, ())
                return kernel, None, (), current_failure
            prefix = current_commands[:failed_position]
            kernel, bus = self._candidate_runtime(proposal, prefix)
            prefix_failure = bus.replay_for_candidate()
            if prefix_failure is not None:
                current_failure = prefix_failure
                current_commands = prefix
                continue
            snapshots = kernel.viewport_data()
            viewport = snapshots[-1] if snapshots else None
            return kernel, viewport, kernel.sketch_display_data(), current_failure

    def preview(self, *, current_session_identity: int) -> ReplayCandidatePreview:
        """Replay the complete frozen candidate off-model and return neutral output."""
        self._check_session(current_session_identity)
        if self._state in ("cancelled", "committed"):
            raise ValidationError(f"cannot preview a {self._state} candidate")
        proposal = self._proposal
        if proposal is None:
            raise ValidationError("stage candidate changes before preview")
        if not self._source_is_current():
            self._state = "stale"
            self._loaded.bus.discard_replay_candidate(self._candidate_id)
            self._release_candidate()
            result = ReplayCandidatePreview("stale", proposal, None, (), None)
            self._latest_preview = result
            return result

        self._generation += 1
        proposal = replace(proposal, generation=self._generation)
        self._proposal = proposal
        self._state = "previewing"
        self._release_candidate()
        self._loaded.bus.record_replay_candidate_preview(proposal, succeeded=False)

        failure = self._first_unsupported_command(proposal)
        kernel: BuildKernel | None = None
        bus: CommandBus | None = None
        viewport: ViewportData | None = None
        sketches: tuple[ViewportSketchData, ...] = ()
        if failure is None:
            kernel, bus = self._candidate_runtime(proposal, proposal.commands)
            changes = self._changes
            guard_ordinals = (
                [edit.ordinal for edit in changes.replacements]
                + [command.ordinal for command in proposal.commands[-len(changes.appends) :]]
                if changes is not None and changes.appends
                else [edit.ordinal for edit in changes.replacements]
                if changes is not None
                else []
            )
            failure = bus.replay_for_candidate(
                guard_from_ordinal=min(guard_ordinals) if guard_ordinals else None
            )
            if failure is None:
                snapshots = kernel.viewport_data()
                viewport = snapshots[-1] if snapshots else None
                sketches = kernel.sketch_display_data()
        if failure is not None:
            kernel, viewport, sketches, failure = self._prefix_result(proposal, failure)

        if proposal.generation != self._generation:
            return ReplayCandidatePreview("stale", proposal, None, (), failure)
        if not self._source_is_current():
            self._state = "stale"
            self._loaded.bus.discard_replay_candidate(self._candidate_id)
            self._release_candidate()
            return ReplayCandidatePreview("stale", proposal, None, (), failure)

        state: ReplayCandidateState = "failed" if failure is not None else "succeeded"
        self._loaded.bus.record_replay_candidate_preview(proposal, succeeded=state == "succeeded")
        self._state = state
        self._candidate_kernel = kernel
        self._candidate_bus = bus if failure is None else None
        datums = kernel.datum_display_data() if failure is None and kernel is not None else ()
        anchors = kernel.snap_anchor_data() if failure is None and kernel is not None else ()
        scene = (
            CandidateInteractionScene(
                proposal.document_id,
                proposal.file_id,
                proposal.revision,
                proposal.session_identity,
                proposal.candidate_id,
                proposal.generation,
                viewport,
                sketches,
                datums,
                anchors,
            )
            if state == "succeeded"
            else None
        )
        failure_scene = (
            CandidateInteractionScene(
                proposal.document_id,
                proposal.file_id,
                proposal.revision,
                proposal.session_identity,
                proposal.candidate_id,
                proposal.generation,
                viewport,
                sketches,
                kernel.datum_display_data(),
                kernel.snap_anchor_data(),
            )
            if state == "failed" and kernel is not None and viewport is not None
            else None
        )
        result = ReplayCandidatePreview(
            state, proposal, viewport, sketches, failure, datums, anchors, scene, failure_scene
        )
        self._latest_preview = result
        return result

    def drawing_collection_snapshot(
        self, *, current_session_identity: int
    ) -> DrawingCollectionSnapshot:
        """Return neutral collection state only from a current successful preview."""
        self._check_session(current_session_identity)
        kernel = self._candidate_kernel
        if self._state != "succeeded" or kernel is None or not self._source_is_current():
            raise ValidationError("candidate preview is unavailable or stale")
        return drawing_collection_snapshot(replace(self._services, kernel=kernel))

    def prepare_attached_collection_move(
        self,
        seeds: tuple[DrawingObjectRef, ...],
        frame: WorkPlaneFrame,
        delta: tuple[float, float],
        *,
        current_session_identity: int,
    ) -> ReplayAppend:
        """Prepare a group move using this candidate's annotation solver."""
        from mycad.core.cross_sketch_tangency import project_coplanar_vector
        from mycad.core.drawing_groups import expand_group_selection
        from mycad.core.drawing_transactions import prepare_collection_translation

        snapshot = self.drawing_collection_snapshot(
            current_session_identity=current_session_identity
        )
        selected = expand_group_selection(seeds, snapshot.groups)
        geometry = {
            (item.sketch_id, item.object_id) for item in selected if item.kind == "geometry"
        }
        dimensions = {
            (sketch.sketch_id, constraint.constraint_id)
            for sketch in snapshot.sketches
            for constraint in sketch.constraints
            if constraint.kind in DIMENSION_KINDS
            and any((sketch.sketch_id, ref.entity_id) in geometry for ref in constraint.references)
        } | {(item.sketch_id, item.object_id) for item in selected if item.kind == "dimension"}

        def target_moves(attachment: AnnotationAttachment | None) -> bool:
            if attachment is None:
                return False
            if attachment.kind == "frame":
                return DrawingObjectRef("tolerance", attachment.object_id) in selected
            if attachment.kind == "reference_dimension":
                return DrawingObjectRef("reference_dimension", attachment.object_id) in selected
            return (attachment.sketch_id, attachment.object_id) in dimensions

        def geometry_moves(attachment: DatumAttachment | None) -> bool:
            return (
                attachment is not None
                and (attachment.sketch_id, attachment.reference.entity_id) in geometry
            )

        if any(
            DrawingObjectRef("tolerance", item.frame_id) not in selected
            and (
                geometry_moves(item.leader_attachment)
                or target_moves(item.leader_annotation_attachment)
            )
            for item in snapshot.frames
        ) or any(
            DrawingObjectRef("datum", item.datum_id) not in selected
            and (geometry_moves(item.attachment) or target_moves(item.annotation_attachment))
            for item in snapshot.datums
        ):
            raise ValidationError("存在未选中的附着标注，暂不能执行此移动。")
        prepared = prepare_collection_translation(
            snapshot, seeds, frame, delta, allow_attached=True
        )
        has_selected_attachment = any(
            DrawingObjectRef("tolerance", item.frame_id) in selected
            and (
                item.leader_attachment is not None or item.leader_annotation_attachment is not None
            )
            for item in snapshot.frames
        ) or any(
            DrawingObjectRef("datum", item.datum_id) in selected
            and (item.attachment is not None or item.annotation_attachment is not None)
            for item in snapshot.datums
        )
        if not has_selected_attachment:
            return prepared
        prepared_operations = (
            cast("list[dict[str, object]]", prepared.params["operations"])
            if prepared.command_id == "drawing.objects.batch"
            else [
                {"id": prepared.command_id, "version": prepared.version, "params": prepared.params}
            ]
        )
        block_operations = [
            item for item in prepared_operations if item["id"] == "drawing.block_instance.update"
        ]
        kernel = self._candidate_kernel
        if kernel is None:
            raise ValidationError("暂存候选不可用。")
        try:
            drawing_delta = project_coplanar_vector(delta, frame, WorkPlaneFrame.xy())
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        result = move_tolerance_selection(
            replace(self._services, kernel=kernel),
            self._loaded,
            tuple(item.object_id for item in selected if item.kind == "geometry"),
            tuple(item.object_id for item in selected if item.kind == "tolerance"),
            tuple(item.object_id for item in selected if item.kind == "datum"),
            tuple(item.object_id for item in selected if item.kind == "reference_dimension"),
            drawing_delta,
            session_identity=current_session_identity,
            text_ids=tuple(item.object_id for item in selected if item.kind == "text"),
            raster_ids=tuple(item.object_id for item in selected if item.kind == "raster"),
            _geometry_refs=tuple(item for item in selected if item.kind == "geometry"),
            _prepare_only=True,
        )
        if not isinstance(result, tuple):
            raise ValidationError("无法准备附着标注移动。")
        items = cast(tuple[object, ...], result)
        if not all(isinstance(item, ReplayAppend) for item in items):
            raise ValidationError("无法准备附着标注移动。")
        appends = cast(tuple[ReplayAppend, ...], items)
        return ReplayAppend(
            "drawing.objects.batch",
            1,
            {
                "operations": [
                    {"id": item.command_id, "version": item.version, "params": item.params}
                    for item in appends
                ]
                + block_operations
            },
            "local",
        )

    def interactive_face_binding(
        self,
        identity: TopologyId,
        *,
        generation: int,
        current_session_identity: int,
    ) -> Mapping[str, object]:
        """Mint a persistent face binding from this generation's candidate kernel."""
        self._check_session(current_session_identity)
        if generation != self._generation or self._proposal is None:
            raise ValidationError("candidate pick belongs to an expired generation")
        if self._state != "succeeded" or self._candidate_kernel is None:
            raise ValidationError("candidate face picking requires a successful preview")
        if not self._source_is_current():
            self._state = "stale"
            self._loaded.bus.discard_replay_candidate(self._candidate_id)
            self._release_candidate()
            raise ValidationError("candidate source document changed")
        return self._candidate_kernel.interactive_face_binding(identity)

    def interactive_bound_face_frame(
        self,
        identity: TopologyId,
        *,
        generation: int,
        current_session_identity: int,
    ) -> WorkPlaneFrame:
        """Return the design-local frame only for a live candidate face pick."""
        self.interactive_face_binding(
            identity, generation=generation, current_session_identity=current_session_identity
        )
        kernel = self._candidate_kernel
        if kernel is None:
            raise ValidationError("candidate face picking requires a successful preview")
        return kernel.interactive_bound_face_frame(identity)

    def interactive_failure_face_binding(
        self,
        identity: TopologyId,
        *,
        generation: int,
        current_session_identity: int,
    ) -> Mapping[str, object]:
        """Bind an exact face in the current failure prefix without authorizing it."""
        self._check_session(current_session_identity)
        preview = self._latest_preview
        scene = preview.failure_scene if preview is not None else None
        if (
            scene is None
            or generation != self._generation
            or not self.is_failure_scene_current(
                scene, current_session_identity=current_session_identity
            )
            or self._candidate_kernel is None
        ):
            raise ValidationError("failure prefix face pick is no longer current")
        return self._candidate_kernel.interactive_face_binding(identity)

    def interactive_failure_bound_face_frame(
        self,
        identity: TopologyId,
        *,
        generation: int,
        current_session_identity: int,
    ) -> WorkPlaneFrame:
        """Return a failure prefix face frame only while its scene is current."""
        self.interactive_failure_face_binding(
            identity, generation=generation, current_session_identity=current_session_identity
        )
        kernel = self._candidate_kernel
        if kernel is None:
            raise ValidationError("failure prefix face pick is no longer current")
        return kernel.interactive_bound_face_frame(identity)

    def authorize_commit(self, *, current_session_identity: int) -> ReplayCommitGrant:
        """Authorize only the latest successful preview in this live session."""
        self._check_session(current_session_identity)
        proposal = self._proposal
        preview = self._latest_preview
        if (
            self._state != "succeeded"
            or proposal is None
            or preview is None
            or preview.state != "succeeded"
            or preview.proposal != proposal
        ):
            raise ValidationError("commit authorization requires the latest successful preview")
        if not self._source_is_current():
            self._state = "stale"
            self._loaded.bus.discard_replay_candidate(self._candidate_id)
            self._release_candidate()
            raise ValidationError("candidate source document changed")
        return self._loaded.bus.authorize_replay_candidate(proposal)

    def commit(
        self,
        grant: ReplayCommitGrant,
        *,
        current_session_identity: int,
        drawing_write_guard: str | None = None,
    ) -> None:
        """Commit this latest preview through its source Bus exactly once."""
        self._check_session(current_session_identity)
        proposal = self._proposal
        preview = self._latest_preview
        if (
            self._state != "succeeded"
            or proposal is None
            or preview is None
            or preview.state != "succeeded"
            or preview.proposal != proposal
        ):
            raise ValidationError("commit requires the latest successful preview")
        if not self._source_is_current():
            self._state = "stale"
            self._loaded.bus.discard_replay_candidate(self._candidate_id)
            self._release_candidate()
            raise ValidationError("candidate source document changed")
        self._loaded.bus.commit_replay_candidate(
            proposal, grant, drawing_write_guard=drawing_write_guard
        )
        self._state = "committed"
        self._release_candidate()

    def cancel(self) -> None:
        """Invalidate the candidate and release its native replay resources."""
        if self._state == "committed":
            raise ValidationError("cannot cancel a committed candidate")
        self._generation += 1
        self._loaded.bus.discard_replay_candidate(self._candidate_id)
        self._release_candidate()
        self._proposal = None
        self._changes = None
        self._state = "cancelled"


def create_replay_candidate(
    services: AppServices,
    loaded: LoadedDocument,
    *,
    session_identity: int,
) -> ReplayCandidateSession:
    """Create a session-bound isolated replay proposal lifecycle."""
    return ReplayCandidateSession(services, loaded, session_identity=session_identity)


def _draft_cross_relations(
    saved: Sequence[Sketch],
    sketch: Sketch,
    cross_tangent_pairs: Sequence[DraftTangentPair],
) -> tuple[CrossSketchTangency, ...]:
    cross_relations: list[CrossSketchTangency] = []
    pairs = tuple(
        (draft_tangent_reference(a), draft_tangent_reference(b)) for a, b in cross_tangent_pairs
    )
    if len(set(pairs)) != len(pairs):
        raise ValidationError("跨草图相切关系重复。")
    for (source_marker, draft_marker), (source_ref, draft_ref) in zip(
        cross_tangent_pairs, pairs, strict=True
    ):
        source_id, draft_id = source_ref.entity_id, draft_ref.entity_id
        owners = [
            (owner, entity)
            for owner in saved
            for entity in owner.entities
            if entity.entity_id == source_id
        ]
        targets = [entity for entity in sketch.entities if entity.entity_id == draft_id]
        if len(owners) != 1 or len(targets) != 1:
            raise ValidationError("跨草图相切来源不存在或身份不唯一。")
        owner, source = owners[0]
        target = targets[0]
        first_ref = CrossSketchRef(owner.sketch_id, source.entity_id, source_ref.index)
        second_ref = CrossSketchRef(sketch.sketch_id, target.entity_id, draft_ref.index)
        try:
            source_curve = resolve_tangent_curve(owner, first_ref)
            target_curve = resolve_tangent_curve(sketch, second_ref)
            projected = project_tangent_entity(target_curve, sketch.frame, owner.frame)
            branch = infer_tangency_branch(source_curve, projected)
        except ValueError as exc:
            raise ValidationError(str(exc), command_id="drawing.tangency.add") from exc
        cross_relations.append(
            CrossSketchTangency(
                uuid5(
                    NAMESPACE_URL,
                    f"mycad:tangency:{sketch.sketch_id}:{source_id}:{draft_id}"
                    + (
                        f":segments:{source_ref.index}:{draft_ref.index}"
                        if source_ref.index is not None or draft_ref.index is not None
                        else ""
                    ),
                ).hex,
                first_ref,
                second_ref,
                branch,
                source_marker.endpoint
                if isinstance(source_marker, DraftConnectedEndpoint)
                else None,
                draft_marker.endpoint if isinstance(draft_marker, DraftConnectedEndpoint) else None,
            )
        )
    return tuple(cross_relations)


def draft_cross_relations(
    saved: Sequence[Sketch], draft: Sketch, pairs: Sequence[DraftTangentPair]
) -> tuple[CrossSketchTangency, ...]:
    """Resolve the currently staged relations without changing the document."""
    return _draft_cross_relations(saved, draft, pairs)


def commit_new_sketch(
    services: AppServices,
    loaded: LoadedDocument,
    sketch: Sketch,
    *,
    session_identity: int,
    confirmed_by: str = "local",
    cross_tangent_pairs: tuple[DraftTangentPair, ...] = (),
    associative_arrays: tuple[AssociativeRectArray, ...] = (),
    imported_styles: DimensionStyleTable | None = None,
    imported_texts: tuple[DrawingText, ...] = (),
    imported_text_styles: TextStyleTable | None = None,
    imported_rasters: tuple[DrawingRaster, ...] = (),
    imported_tolerance_frames: tuple[FeatureControlFrame, ...] = (),
    imported_datums: tuple[DatumIdentifier, ...] = (),
    imported_reference_dimensions: tuple[DetachedDimension, ...] = (),
    preserve_existing_datum_refs: bool = False,
    imported_curve_ids: bool = False,
    persistent_batch: bool = False,
) -> object:
    """Commit a sketch, upgrading the archive for points or inferred tangencies."""
    has_tangency = any(item.kind == "tangent" for item in sketch.constraints)
    has_geometric_relations = any(
        item.kind in ("parallel", "perpendicular", "concentric", "equal", "fixed")
        or (
            item.source == "user"
            and item.kind in ("horizontal", "vertical", "coincident", "tangent")
        )
        for item in sketch.constraints
    )
    has_curves = any(
        isinstance(entity, PolylineEntity) and entity.bulges for entity in sketch.entities
    )
    has_ellipse = any(isinstance(entity, EllipseEntity) for entity in sketch.entities)
    has_curve_point_ids = any(
        isinstance(entity, PolylineEntity | SplineEntity) and entity.point_ids
        for entity in sketch.entities
    )
    if (
        not cross_tangent_pairs
        and imported_styles is None
        and not imported_texts
        and not imported_rasters
        and not imported_tolerance_frames
        and not imported_datums
        and not imported_reference_dimensions
        and imported_text_styles is None
        and not associative_arrays
        and not has_tangency
        and not has_geometric_relations
        and not has_curves
        and not has_curve_point_ids
        and not any(item.projection_axis is not None for item in sketch.constraints)
        and not any(item.text_override is not None for item in sketch.constraints)
        and not any(item.style_name is not None for item in sketch.constraints)
        and not any(item.tolerance is not None for item in sketch.constraints)
        and not any(isinstance(entity, PointEntity) for entity in sketch.entities)
    ):
        return loaded.bus.execute(
            "sketch.create",
            sketch.to_state_mapping(),
            confirmed_by,
            version=53 if has_ellipse else None,
        )
    layer_appends: tuple[ReplayAppend, ...] = ()
    text_appends: tuple[ReplayAppend, ...] = ()
    font_style_appends: tuple[ReplayAppend, ...] = ()
    working_text_styles = services.kernel.drawing_text_styles
    if (
        imported_styles is not None
        and imported_text_styles is not None
        and any(style.text_style_id is not None for style in imported_styles.styles)
    ):
        try:
            if imported_text_styles.current_id != working_text_styles.current_id or any(
                imported_text_styles.get(style.style_id) != style
                for style in working_text_styles.styles
            ):
                raise ValueError("导入字体时不能修改已有文字样式。")
            for style in imported_styles.styles:
                if style.text_style_id is not None:
                    imported_text_styles.get(style.text_style_id)
        except (KeyError, ValueError) as exc:
            raise ValidationError(str(exc), command_id="drawing.text_styles.set") from exc
        if imported_text_styles != working_text_styles:
            working_text_styles = imported_text_styles
            font_style_appends = (
                ReplayAppend(
                    "drawing.text_styles.set", 1, working_text_styles.to_mapping(), confirmed_by
                ),
            )
    raster_appends: tuple[ReplayAppend, ...] = ()
    tolerance_appends: tuple[ReplayAppend, ...] = ()
    reference_appends: tuple[ReplayAppend, ...] = ()
    if (
        imported_texts
        or imported_rasters
        or imported_tolerance_frames
        or imported_datums
        or imported_reference_dimensions
    ):
        layers = services.kernel.drawing_layers
        known_layers = {layer.name.casefold() for layer in layers.layers}
        for layer in sketch.layers.layers:
            if layer.name.casefold() not in known_layers:
                layers = layers.add(layer)
                known_layers.add(layer.name.casefold())
        if imported_styles is not None and not sketch.entities:
            layer_appends = (
                ReplayAppend(
                    "drawing.clipboard.prepare",
                    services.registry.get("drawing.clipboard.prepare").version,
                    {
                        "layers": layers.to_mapping(),
                        "dimension_layer": services.kernel.dimension_layer,
                        "clipboard_styles": imported_styles.to_mapping(),
                    },
                    confirmed_by,
                ),
            )
        elif layers != services.kernel.drawing_layers:
            layer_appends = (
                ReplayAppend(
                    "drawing.layers.set",
                    1,
                    {
                        "layers": layers.to_mapping(),
                        "dimension_layer": services.kernel.dimension_layer,
                    },
                    confirmed_by,
                ),
            )
        # Geometry must inherit the target layer definitions as well.
        sketch = replace(sketch, layers=layers)
        try:
            styles, imported_texts = reconcile_text_styles(
                imported_texts,
                imported_text_styles or working_text_styles,
                working_text_styles,
            )
            annotation_font_ids = tuple(
                item.text_style_id
                for item in (*imported_tolerance_frames, *imported_datums)
                if item.text_style_id is not None
            )
            styles, frame_font_map = reconcile_text_style_ids(
                annotation_font_ids, imported_text_styles or working_text_styles, styles
            )
        except (ValueError, KeyError) as exc:
            raise ValidationError(str(exc), command_id="drawing.text.batch") from exc
        identities = {text.text_id for text in services.kernel.drawing_texts}
        remapped: list[DrawingText] = []
        for text in imported_texts:
            identity = uuid4().hex if text.text_id in identities else text.text_id
            identities.add(identity)
            remapped.append(replace(text, text_id=identity))
        text_appends = (
            (
                ReplayAppend(
                    "drawing.text.batch",
                    1,
                    {
                        "add": [text.to_mapping() for text in remapped],
                        "styles": styles.to_mapping(),
                    },
                    confirmed_by,
                ),
            )
            if imported_texts or styles != working_text_styles
            else ()
        )
        image_identities = {image.image_id for image in services.kernel.drawing_rasters}
        images: list[DrawingRaster] = []
        for image in imported_rasters:
            identity = uuid4().hex if image.image_id in image_identities else image.image_id
            image_identities.add(identity)
            images.append(replace(image, image_id=identity))
        if images:
            raster_appends = (
                ReplayAppend(
                    "drawing.raster.batch",
                    services.registry.get("drawing.raster.batch").version,
                    {"action": "add", "images": [image.to_mapping(version=2) for image in images]},
                    confirmed_by,
                ),
            )
        datum_ids = (
            {datum.datum_id for datum in services.kernel.drawing_datum_identifiers}
            | {frame.frame_id for frame in services.kernel.drawing_tolerance_frames}
            | {item.dimension_id for item in services.kernel.drawing_reference_dimensions}
        )
        datum_map: dict[str, str] = {}
        datums: list[DatumIdentifier] = []
        for datum in imported_datums:
            if datum.datum_id in datum_map:
                raise ValidationError("导入的基准 ID 重复。", command_id="drawing.tolerance.batch")
            identity = uuid4().hex if datum.datum_id in datum_ids else datum.datum_id
            datum_ids.add(identity)
            datum_map[datum.datum_id] = identity
            datums.append(
                replace(
                    datum,
                    datum_id=identity,
                    text_style_id=(
                        frame_font_map[datum.text_style_id]
                        if datum.text_style_id is not None
                        else None
                    ),
                )
            )
        reference_ids = {
            dimension.dimension_id for dimension in services.kernel.drawing_reference_dimensions
        }
        reference_ids.update(datum_ids)
        references: list[DetachedDimension] = []
        reference_map: dict[str, str] = {}
        for dimension in imported_reference_dimensions:
            if dimension.dimension_id in reference_map:
                raise ValidationError(
                    "导入的参考尺寸 ID 重复。", command_id="drawing.reference_dimensions.batch"
                )
            identity = (
                uuid4().hex if dimension.dimension_id in reference_ids else dimension.dimension_id
            )
            reference_ids.add(identity)
            reference_map[dimension.dimension_id] = identity
            references.append(replace(dimension, dimension_id=identity))
        if references:
            reference_appends = (
                ReplayAppend(
                    "drawing.reference_dimensions.batch",
                    services.registry.get("drawing.reference_dimensions.batch").version,
                    {"add": [dimension.to_mapping() for dimension in references]},
                    confirmed_by,
                ),
            )
        existing_datums = {
            datum.datum_id: datum for datum in services.kernel.drawing_datum_identifiers
        }
        existing_datum_ids = set(existing_datums)
        source_datums = {datum.datum_id: datum for datum in imported_datums}
        frame_ids = {frame.frame_id for frame in services.kernel.drawing_tolerance_frames}
        frame_ids.update(reference_ids)
        frame_map: dict[str, str] = {}
        for frame in imported_tolerance_frames:
            if frame.frame_id in frame_map:
                raise ValidationError(
                    "导入的公差框 ID 重复。", command_id="drawing.tolerance.batch"
                )
            identity = uuid4().hex if frame.frame_id in frame_ids else frame.frame_id
            frame_ids.add(identity)
            frame_map[frame.frame_id] = identity

        def rebind_annotation(ref: AnnotationAttachment | None) -> AnnotationAttachment | None:
            if ref is None:
                return None
            if ref.kind == "frame":
                mapped = frame_map.get(ref.object_id)
            elif ref.kind == "reference_dimension":
                mapped = reference_map.get(ref.object_id)
            else:
                mapped = (
                    ref.object_id
                    if ref.sketch_id == sketch.sketch_id
                    and any(item.constraint_id == ref.object_id for item in sketch.constraints)
                    else None
                )
            if mapped is not None:
                return replace(ref, object_id=mapped)
            return ref if preserve_existing_datum_refs else None

        datums = [
            replace(datum, annotation_attachment=rebind_annotation(datum.annotation_attachment))
            for datum in datums
        ]
        frames: list[FeatureControlFrame] = []
        for frame in imported_tolerance_frames:
            for row in frame.rows:
                for ref in row.datums:
                    if ref.datum_id is None:
                        continue
                    source = source_datums.get(ref.datum_id)
                    if source is None and preserve_existing_datum_refs:
                        source = existing_datums.get(ref.datum_id)
                    if source is not None and source.label != ref.label:
                        raise ValidationError(
                            "导入的基准引用标签与目标基准不一致。",
                            command_id="drawing.tolerance.batch",
                        )
            identity = frame_map[frame.frame_id]
            rows = tuple(
                replace(
                    row,
                    datums=tuple(
                        replace(
                            ref,
                            datum_id=datum_map.get(
                                ref.datum_id,
                                ref.datum_id
                                if preserve_existing_datum_refs
                                and ref.datum_id in existing_datum_ids
                                else None,
                            )
                            if ref.datum_id is not None
                            else None,
                        )
                        for ref in row.datums
                    ),
                )
                for row in frame.rows
            )
            frames.append(
                replace(
                    frame,
                    frame_id=identity,
                    leader_annotation_attachment=rebind_annotation(
                        frame.leader_annotation_attachment
                    ),
                    rows=rows,
                    text_style_id=(
                        frame_font_map[frame.text_style_id]
                        if frame.text_style_id is not None
                        else None
                    ),
                )
            )
        if frames or datums:
            tolerance_appends = (
                ReplayAppend(
                    "drawing.tolerance.batch",
                    services.registry.get("drawing.tolerance.batch").version,
                    {
                        "add_frames": [frame.to_mapping() for frame in frames],
                        "add_datums": [datum.to_mapping() for datum in datums],
                    },
                    confirmed_by,
                ),
            )
    cross_relations = _draft_cross_relations(services.kernel.sketches, sketch, cross_tangent_pairs)
    candidate = create_replay_candidate(services, loaded, session_identity=session_identity)
    params = sketch.to_state_mapping()
    if imported_styles is not None:
        params["clipboard_styles"] = imported_styles.to_mapping()
    if cross_relations:
        params["cross_tangencies"] = [relation.to_mapping() for relation in cross_relations]
    if associative_arrays:
        params["associative_arrays"] = [array.to_mapping() for array in associative_arrays]
    appends = (
        font_style_appends
        + layer_appends
        + (
            (
                ReplayAppend(
                    "sketch.create",
                    (58 if imported_curve_ids else 57)
                    if has_curve_point_ids
                    else 54
                    if has_ellipse and imported_styles is not None
                    else 53
                    if has_ellipse
                    else 49
                    if imported_styles is not None
                    and any(style.text_style_id is not None for style in imported_styles.styles)
                    else 47
                    if imported_styles is not None
                    and (
                        any(item.tolerance is not None for item in sketch.constraints)
                        or any(
                            style.linear_tolerance.mode != "none"
                            or style.angular_tolerance.mode != "none"
                            for style in imported_styles.styles
                        )
                    )
                    else 46
                    if any(item.tolerance is not None for item in sketch.constraints)
                    and imported_styles is None
                    else 45
                    if imported_styles is not None
                    else 32
                    if any(item.style_name is not None for item in sketch.constraints)
                    else 30
                    if any(item.text_override is not None for item in sketch.constraints)
                    else 28
                    if any(item.projection_axis is not None for item in sketch.constraints)
                    else 27
                    if has_rectangle_segment_tangency(sketch)
                    or relations_use_rectangle_segments(
                        (*services.kernel.sketches, sketch), cross_relations
                    )
                    else 26
                    if any(
                        output.rotation_deg != 0
                        for array in associative_arrays
                        for output in array.extra_outputs
                    )
                    else 25
                    if any(
                        output.offset_mm != (0, 0)
                        for array in associative_arrays
                        for output in array.extra_outputs
                    )
                    else 24
                    if any(array.extra_outputs for array in associative_arrays)
                    else 23
                    if any(has_shared_replacement_anchor(array) for array in associative_arrays)
                    else 22
                    if has_interleaved_array_dependencies(
                        (*services.kernel.associative_arrays, *associative_arrays)
                    )
                    else 21
                    if any(has_internal_replacements(array) for array in associative_arrays)
                    else 20
                    if any(
                        member.replacement is not None
                        for array in associative_arrays
                        for member in array.members
                    )
                    else 19
                    if any(
                        member.erased_neighbors is not None
                        for array in associative_arrays
                        for member in array.members
                    )
                    else 18
                    if any(
                        member.erased_index is not None
                        for array in associative_arrays
                        for member in array.members
                    )
                    else 17
                    if any(
                        member.rotation_deg != 0
                        for array in associative_arrays
                        for member in array.members
                    )
                    else 16
                    if any(
                        member.offset_mm != (0, 0)
                        for array in associative_arrays
                        for member in array.members
                    )
                    else 15
                    if any(array.base_point is not None for array in associative_arrays)
                    else 14
                    if any(array.angle_deg != 0 for array in associative_arrays)
                    else 13
                    if any(c.first_endpoint or c.second_endpoint for c in sketch.constraints)
                    else 12
                    if any(r.first_endpoint or r.second_endpoint for r in cross_relations)
                    else 11
                    if associative_arrays
                    else 10
                    if any(
                        ref.segment_index is not None
                        for relation in cross_relations
                        for ref in (relation.first, relation.second)
                    )
                    else 9
                    if has_geometric_relations
                    else 8
                    if has_curves
                    else 7
                    if cross_relations
                    else 6
                    if has_tangency
                    else 5,
                    params,
                    confirmed_by,
                ),
            )
            if sketch.entities
            or not (
                imported_texts
                or imported_rasters
                or imported_tolerance_frames
                or imported_datums
                or imported_reference_dimensions
            )
            else ()
        )
        + text_appends
        + raster_appends
        + reference_appends
        + tolerance_appends
    )
    needs_batch = persistent_batch and len(appends) > 1
    if needs_batch:
        appends = (
            ReplayAppend(
                "drawing.objects.batch",
                1,
                {
                    "operations": [
                        {"id": item.command_id, "version": item.version, "params": item.params}
                        for item in appends
                    ]
                },
                confirmed_by,
            ),
        )
    target_version = 8 if needs_batch or imported_styles is not None or has_curve_point_ids else 6
    candidate.stage(
        ReplayChangeSet(
            (),
            appends,
            False,
            target_archive_version=target_version
            if loaded.document.archive_version < target_version
            else None,
        ),
        current_session_identity=session_identity,
    )
    preview = candidate.preview(current_session_identity=session_identity)
    if preview.state != "succeeded":
        raise ValidationError(preview.failure.reason if preview.failure else "草图预览失败。")
    grant = candidate.authorize_commit(current_session_identity=session_identity)
    return candidate.commit(grant, current_session_identity=session_identity)


def upgrade_selected_curve_identities(
    services: AppServices,
    loaded: LoadedDocument,
    entity_ids: tuple[str, ...],
    *,
    session_identity: int,
) -> object:
    """Upgrade selected legacy curves across sketches in one replayable operation."""
    from mycad.core.geometric_tolerance_topology import prepare_curve_identity_upgrade

    selected = set(entity_ids)
    if not selected or len(selected) != len(entity_ids):
        raise ValidationError("请选择需要升级的多段线或样条。")
    found: set[str] = set()
    appends: list[ReplayAppend] = []
    for sketch in services.kernel.sketches:
        chosen = tuple(item for item in sketch.entities if item.entity_id in selected)
        if not chosen:
            continue
        for item in chosen:
            if item.entity_id in found or not isinstance(item, PolylineEntity | SplineEntity):
                raise ValidationError("所选对象必须是身份唯一的多段线或样条。")
            found.add(item.entity_id)
        legacy = tuple(
            item.entity_id
            for item in chosen
            if isinstance(item, PolylineEntity | SplineEntity) and not item.point_ids
        )
        if not legacy:
            continue
        records = prepare_curve_identity_upgrade(sketch, legacy)
        appends.append(
            ReplayAppend(
                "drawing.curve_identity.upgrade",
                services.registry.get("drawing.curve_identity.upgrade").version,
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "records": [record.to_mapping() for record in records],
                },
                "local",
            )
        )
    if found != selected:
        raise ValidationError("所选曲线不存在或已改变，请重新选择。")
    if not appends:
        raise ValidationError("所选曲线均已有点身份。")
    candidate = create_replay_candidate(services, loaded, session_identity=session_identity)
    candidate.stage(
        ReplayChangeSet(
            (),
            tuple(appends),
            False,
            target_archive_version=6 if loaded.document.archive_version < 6 else None,
        ),
        current_session_identity=session_identity,
    )
    preview = candidate.preview(current_session_identity=session_identity)
    if preview.state != "succeeded":
        raise ValidationError(preview.failure.reason if preview.failure else "曲线身份升级失败。")
    return candidate.commit(
        candidate.authorize_commit(current_session_identity=session_identity),
        current_session_identity=session_identity,
    )


def repair_tolerance_annotation_identities(
    services: AppServices, loaded: LoadedDocument, *, session_identity: int
) -> object:
    """Repair legacy cross-kind identity collisions as one history operation."""
    from mycad.core.geometric_tolerance_identity import repair_annotation_identities

    frames, references = repair_annotation_identities(
        services.kernel.drawing_tolerance_frames,
        services.kernel.drawing_datum_identifiers,
        services.kernel.drawing_reference_dimensions,
    )
    appends: list[ReplayAppend] = []
    if references["remove"]:
        appends.append(
            ReplayAppend(
                "drawing.reference_dimensions.batch",
                services.registry.get("drawing.reference_dimensions.batch").version,
                references,
                "local",
            )
        )
    if frames["remove_frames"]:
        appends.append(
            ReplayAppend(
                "drawing.tolerance.batch",
                services.registry.get("drawing.tolerance.batch").version,
                frames,
                "local",
            )
        )
    if not appends:
        raise ValidationError("没有需要修复的标注身份。")
    candidate = create_replay_candidate(services, loaded, session_identity=session_identity)
    candidate.stage(
        ReplayChangeSet((), tuple(appends), False), current_session_identity=session_identity
    )
    preview = candidate.preview(current_session_identity=session_identity)
    if preview.state != "succeeded":
        raise ValidationError(
            preview.failure.reason if preview.failure else "标注身份修复预览失败。"
        )
    return candidate.commit(
        candidate.authorize_commit(current_session_identity=session_identity),
        current_session_identity=session_identity,
    )


def delete_tolerance_selection(
    services: AppServices,
    loaded: LoadedDocument,
    frame_ids: tuple[str, ...],
    datum_ids: tuple[str, ...],
    reference_ids: tuple[str, ...],
    *,
    session_identity: int,
    text_ids: tuple[str, ...] = (),
    raster_ids: tuple[str, ...] = (),
) -> object:
    """Remove selected drawing annotations and images in one history operation."""
    appends: list[ReplayAppend] = []
    if frame_ids or datum_ids:
        appends.append(
            ReplayAppend(
                "drawing.tolerance.batch",
                services.registry.get("drawing.tolerance.batch").version,
                {"remove_frames": list(frame_ids), "remove_datums": list(datum_ids)},
                "local",
            )
        )
    if reference_ids:
        appends.append(
            ReplayAppend(
                "drawing.reference_dimensions.batch",
                services.registry.get("drawing.reference_dimensions.batch").version,
                {"remove": list(reference_ids)},
                "local",
            )
        )
    if text_ids:
        appends.append(
            ReplayAppend(
                "drawing.text.batch",
                services.registry.get("drawing.text.batch").version,
                {"add": [], "update": [], "remove": list(text_ids)},
                "local",
            )
        )
    if raster_ids:
        appends.append(
            ReplayAppend(
                "drawing.raster.batch",
                services.registry.get("drawing.raster.batch").version,
                {"action": "remove", "image_ids": list(raster_ids)},
                "local",
            )
        )
    if not appends:
        raise ValidationError("没有可删除的标注。")
    candidate = create_replay_candidate(services, loaded, session_identity=session_identity)
    candidate.stage(
        ReplayChangeSet((), tuple(appends), False), current_session_identity=session_identity
    )
    preview = candidate.preview(current_session_identity=session_identity)
    if preview.state != "succeeded":
        raise ValidationError(preview.failure.reason if preview.failure else "混合删除预览失败。")
    return candidate.commit(
        candidate.authorize_commit(current_session_identity=session_identity),
        current_session_identity=session_identity,
    )


def move_tolerance_selection(
    services: AppServices,
    loaded: LoadedDocument,
    entity_ids: tuple[str, ...],
    frame_ids: tuple[str, ...],
    datum_ids: tuple[str, ...],
    reference_ids: tuple[str, ...],
    delta: tuple[float, float],
    *,
    session_identity: int,
    text_ids: tuple[str, ...] = (),
    raster_ids: tuple[str, ...] = (),
    _geometry_refs: tuple[DrawingObjectRef, ...] | None = None,
    _prepare_only: bool = False,
) -> object:
    """Move a supported geometry/annotation selection as one replay operation."""
    from mycad.core.cross_sketch_tangency import project_coplanar_vector
    from mycad.core.drawing_text import move_text
    from mycad.core.sketch_edit import move_entities

    dx, dy = delta
    if not math.isfinite(dx) or not math.isfinite(dy):
        raise ValidationError("移动位移必须是有限数值。")
    if _geometry_refs is None:
        selected = set(entity_ids)
        if len(selected) != len(entity_ids):
            raise ValidationError("图元身份重复。")
        matches = [
            (sketch.sketch_id, item.entity_id)
            for sketch in services.kernel.sketches
            for item in sketch.entities
            if item.entity_id in selected
        ]
        if len(matches) != len(selected) or {identity for _, identity in matches} != selected:
            raise ValidationError("所选图元不存在或身份不唯一。")
        selected_sources = set(matches)
    else:
        if (
            any(item.kind != "geometry" or item.sketch_id is None for item in _geometry_refs)
            or len(_geometry_refs) != len(set(_geometry_refs))
            or sorted(item.object_id for item in _geometry_refs) != sorted(entity_ids)
        ):
            raise ValidationError("图元身份或所属草图不一致。")
        selected_sources = {
            (cast("str", item.sketch_id), item.object_id) for item in _geometry_refs
        }

    def selected_ref(sketch_id: str, entity_id: str) -> bool:
        return (sketch_id, entity_id) in selected_sources

    if any(
        selected_ref(relation.first.sketch_id, relation.first.entity_id)
        != selected_ref(relation.second.sketch_id, relation.second.entity_id)
        for relation in services.kernel.cross_sketch_tangencies
    ):
        raise ValidationError("混合移动需要同时选择相切关联的全部图元。")
    if any(
        any(selected_ref(ref.sketch_id, ref.entity_id) for ref in array.sources)
        or any(
            selected_ref(member.target.sketch_id, member.target.entity_id)
            for member in array.members
        )
        or any(
            member.replacement is not None
            and selected_ref(
                member.replacement.source.sketch_id, member.replacement.source.entity_id
            )
            for member in array.members
        )
        or any(
            selected_ref(output.target.sketch_id, output.target.entity_id)
            or selected_ref(output.source.sketch_id, output.source.entity_id)
            for output in array.extra_outputs
        )
        for array in services.kernel.associative_arrays
    ):
        raise ValidationError("混合移动暂不支持关联阵列。")
    revisions: list[dict[str, object]] = []
    found: set[tuple[str, str]] = set()
    for sketch in services.kernel.sketches:
        identities = tuple(
            item.entity_id
            for item in sketch.entities
            if selected_ref(sketch.sketch_id, item.entity_id)
        )
        if not identities:
            continue
        try:
            local_delta = project_coplanar_vector(delta, WorkPlaneFrame.xy(), sketch.frame)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        for constraint in sketch.constraints:
            members = {ref.entity_id for ref in constraint.references}
            if members.intersection(identities) and not members.issubset(identities):
                raise ValidationError("混合移动需要同时选中关联尺寸或约束的全部图元。")
        found.update((sketch.sketch_id, identity) for identity in identities)
        moved_constraints = tuple(
            replace(
                constraint,
                position_mm=None
                if constraint.position_mm is None
                else (
                    constraint.position_mm[0] + local_delta[0],
                    constraint.position_mm[1] + local_delta[1],
                ),
                text_position_mm=None
                if constraint.text_position_mm is None
                else (
                    constraint.text_position_mm[0] + local_delta[0],
                    constraint.text_position_mm[1] + local_delta[1],
                ),
            )
            if any(ref.entity_id in identities for ref in constraint.references)
            else constraint
            for constraint in sketch.constraints
        )
        moved = replace(
            sketch,
            entities=move_entities(
                sketch.entities, identities, local_delta, preserve_rectangle_order=True
            ),
            constraints=moved_constraints,
        )
        state = moved.to_state_mapping()
        revisions.append(
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        )
    if found != selected_sources:
        raise ValidationError("所选图元不存在或身份不唯一。")
    frames = tuple(
        item for item in services.kernel.drawing_tolerance_frames if item.frame_id in frame_ids
    )
    datums = tuple(
        item for item in services.kernel.drawing_datum_identifiers if item.datum_id in datum_ids
    )
    references = tuple(
        item
        for item in services.kernel.drawing_reference_dimensions
        if item.dimension_id in reference_ids
    )
    texts = tuple(item for item in services.kernel.drawing_texts if item.text_id in text_ids)
    rasters = tuple(item for item in services.kernel.drawing_rasters if item.image_id in raster_ids)
    if (
        len(frames) != len(frame_ids)
        or len(datums) != len(datum_ids)
        or len(references) != len(reference_ids)
        or len(texts) != len(text_ids)
        or len(rasters) != len(raster_ids)
    ):
        raise ValidationError("所选标注不存在或身份重复。")
    for item in (*texts, *rasters):
        layer = services.kernel.drawing_layers.get(item.layer_name)
        if layer.locked or not layer.displayed:
            raise ValidationError("锁定或隐藏图层上的文字和图片不能移动。")

    def translated(point: tuple[float, float]) -> tuple[float, float]:
        return point[0] + dx, point[1] + dy

    def fixed_target_offsets(
        item: FeatureControlFrame | DatumIdentifier,
    ) -> tuple[tuple[float, float], ...]:
        from mycad.core.geometric_tolerance_geometry import (
            relocate_automatic_leader,
            relocate_box_aware_leader,
        )

        if item.leader_auto_route:
            target = (
                item.leader_target_mm if isinstance(item, FeatureControlFrame) else item.target_mm
            )
            if target is None:
                raise ValidationError("自动引线缺少附着目标。")
            try:
                position = translated(item.position_mm)
                if isinstance(item, DatumIdentifier) and item.route_algorithm_version >= 3:
                    assert item.box_size_mm is not None
                    return relocate_box_aware_leader(
                        item.position_mm,
                        item.leader_offsets,
                        position,
                        target,
                        item.box_size_mm,
                        orthogonal_box_side=item.route_algorithm_version >= 4,
                    )
                anchor = (
                    (
                        position[0] + item.leader_anchor_offset[0],
                        position[1] + item.leader_anchor_offset[1],
                    )
                    if isinstance(item, FeatureControlFrame)
                    and item.leader_anchor_offset is not None
                    else None
                )
                return relocate_automatic_leader(
                    item.position_mm, item.leader_offsets, position, target, anchor=anchor
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
        attachment = (
            item.leader_attachment if isinstance(item, FeatureControlFrame) else item.attachment
        )
        if item.leader_auto_normal and attachment is not None:
            return tuple((x - dx, y - dy) for x, y in item.leader_offsets)
        return item.leader_offsets

    def annotation_target_moves_before_batch(reference: AnnotationAttachment) -> bool:
        if reference.kind == "frame":
            return reference.object_id in frame_ids
        if reference.kind == "sketch_dimension":
            return any(
                sketch.sketch_id == reference.sketch_id
                and any(
                    constraint.constraint_id == reference.object_id
                    and any(
                        (sketch.sketch_id, item.entity_id) in selected_sources
                        for item in constraint.references
                    )
                    for constraint in sketch.constraints
                )
                for sketch in services.kernel.sketches
            )
        return False

    moved_frames = tuple(
        replace(
            translate_frame(frame, (dx, dy)),
            leader_target_mm=frame.leader_target_mm,
            leader_offsets=fixed_target_offsets(frame),
        )
        if (
            frame.leader_attachment is not None
            and (frame.leader_attachment.sketch_id, frame.leader_attachment.reference.entity_id)
            not in selected_sources
        )
        or (
            frame.leader_annotation_attachment is not None
            and not annotation_target_moves_before_batch(frame.leader_annotation_attachment)
        )
        else translate_frame(frame, (dx, dy))
        for frame in frames
    )
    moved_datums: list[DatumIdentifier] = []
    for datum in datums:
        attachment = datum.attachment
        geometry_moves = (
            attachment is not None
            and (attachment.sketch_id, attachment.reference.entity_id) in selected_sources
        )
        if datum.annotation_attachment is not None:
            target = (
                translated(datum.target_mm)
                if annotation_target_moves_before_batch(datum.annotation_attachment)
                else datum.target_mm
            )
        else:
            target = (
                translated(datum.target_mm)
                if attachment is None or geometry_moves
                else datum.target_mm
            )
        moved_datums.append(
            replace(
                datum,
                position_mm=translated(datum.position_mm),
                target_mm=target,
                leader_offsets=(
                    fixed_target_offsets(datum)
                    if attachment is not None and not geometry_moves
                    else datum.leader_offsets
                ),
            )
        )
    moved_references = tuple(
        replace(
            item,
            first_mm=translated(item.first_mm),
            second_mm=translated(item.second_mm),
            location_mm=translated(item.location_mm),
            vertex_mm=translated(item.vertex_mm) if item.vertex_mm is not None else None,
        )
        for item in references
    )
    # A selected target and its annotation move together.  Freeze automatic
    # routing during the intermediate geometry command; the final annotation
    # command restores the original constraints and translated path atomically.
    suspended_frames = [
        replace(
            frame,
            leader_auto_normal=False,
            leader_auto_route=False,
            route_avoid_crossing=False,
            route_track_target=False,
            route_algorithm_version=1,
        )
        for frame in frames
        if frame.leader_auto_route
        and frame.leader_attachment is not None
        and (frame.leader_attachment.sketch_id, frame.leader_attachment.reference.entity_id)
        in selected_sources
    ]
    suspended_datums = [
        replace(
            datum,
            leader_auto_normal=False,
            leader_auto_route=False,
            route_avoid_crossing=False,
            route_track_target=False,
            route_algorithm_version=1,
        )
        for datum in datums
        if datum.leader_auto_route
        and datum.attachment is not None
        and (datum.attachment.sketch_id, datum.attachment.reference.entity_id) in selected_sources
    ]
    appends: list[ReplayAppend] = []
    if suspended_frames or suspended_datums:
        appends.append(
            ReplayAppend(
                "drawing.tolerance.batch",
                services.registry.get("drawing.tolerance.batch").version,
                {
                    "update_frames": [item.to_mapping() for item in suspended_frames],
                    "update_datums": [item.to_mapping() for item in suspended_datums],
                },
                "local",
            )
        )
    if revisions:
        appends.append(
            ReplayAppend(
                "drawing.sketch.revise",
                services.registry.get("drawing.sketch.revise").version,
                {"revisions": revisions},
                "local",
            )
        )
    if moved_frames or moved_datums:
        appends.append(
            ReplayAppend(
                "drawing.tolerance.batch",
                services.registry.get("drawing.tolerance.batch").version,
                {
                    "update_frames": [item.to_mapping() for item in moved_frames],
                    "update_datums": [item.to_mapping() for item in moved_datums],
                },
                "local",
            )
        )
    if moved_references:
        appends.append(
            ReplayAppend(
                "drawing.reference_dimensions.batch",
                services.registry.get("drawing.reference_dimensions.batch").version,
                {"update": [item.to_mapping() for item in moved_references]},
                "local",
            )
        )
    if texts:
        appends.append(
            ReplayAppend(
                "drawing.text.batch",
                services.registry.get("drawing.text.batch").version,
                {
                    "add": [],
                    "update": [move_text(item, delta).to_mapping() for item in texts],
                    "remove": [],
                },
                "local",
            )
        )
    if rasters:
        appends.append(
            ReplayAppend(
                "drawing.raster.batch",
                services.registry.get("drawing.raster.batch").version,
                {
                    "action": "update",
                    "images": [
                        replace(item, origin_mm=translated(item.origin_mm)).to_mapping(version=2)
                        for item in rasters
                    ],
                },
                "local",
            )
        )
    if not appends:
        raise ValidationError("没有可移动的对象。")
    if _prepare_only:
        return tuple(appends)
    candidate = create_replay_candidate(services, loaded, session_identity=session_identity)
    candidate.stage(
        ReplayChangeSet((), tuple(appends), False), current_session_identity=session_identity
    )
    preview = candidate.preview(current_session_identity=session_identity)
    if preview.state != "succeeded":
        raise ValidationError(preview.failure.reason if preview.failure else "混合移动预览失败。")
    return candidate.commit(
        candidate.authorize_commit(current_session_identity=session_identity),
        current_session_identity=session_identity,
    )


def prepare_cross_sketch_tangency(
    services: AppServices, relation: CrossSketchTangency
) -> tuple[tuple[Sketch, ...], tuple[Sketch, ...]]:
    """Produce an isolated tangent solution for a proposed relation."""
    return prepare_cross_sketch_tangency_from_state(
        services.kernel.sketches, services.kernel.cross_sketch_tangencies, relation
    )


def prepare_cross_sketch_tangency_from_state(
    sketches: tuple[Sketch, ...],
    existing: tuple[CrossSketchTangency, ...],
    relation: CrossSketchTangency,
) -> tuple[tuple[Sketch, ...], tuple[Sketch, ...]]:
    """Solve a proposed relation against an isolated drawing state."""
    relations = (*existing, relation)
    try:
        original, _ = resolve_tangency_component(sketches, relations, relation.first.sketch_id)
        solved = solve_tangency_component(original, relations, relation.first.sketch_id)
        build_tangency_revisions(original, solved)
        return original, solved
    except ValueError as exc:
        raise ValidationError(str(exc), command_id="drawing.tangency.add") from exc


def commit_cross_sketch_tangency(
    services: AppServices,
    loaded: LoadedDocument,
    relation: CrossSketchTangency,
    *,
    session_identity: int,
    confirmed_by: str = "local",
    expected_original: tuple[Sketch, ...] | None = None,
    expected_solved: tuple[Sketch, ...] | None = None,
    still_current: Callable[[], bool] | None = None,
) -> object:
    """Solve and atomically commit one new relation and all affected sketch revisions."""
    try:
        original, solved = prepare_cross_sketch_tangency(services, relation)
        if expected_original is not None and {s.sketch_id: s for s in original} != {
            s.sketch_id: s for s in expected_original
        }:
            raise ValueError("草图已变化，请重新预览。")
        if expected_solved is not None and {s.sketch_id: s for s in solved} != {
            s.sketch_id: s for s in expected_solved
        }:
            raise ValueError("相切求解结果已变化，请重新预览。")
        revisions = build_tangency_revisions(original, solved)
    except ValueError as exc:
        raise ValidationError(str(exc), command_id="drawing.tangency.add") from exc
    candidate = create_replay_candidate(services, loaded, session_identity=session_identity)
    candidate.stage(
        ReplayChangeSet(
            (),
            (
                ReplayAppend(
                    "drawing.tangency.add",
                    13
                    if revisions_include_curve_point_ids(revisions)
                    else 12
                    if revisions_require_attachment_protection(services, revisions)
                    else 11
                    if revisions_include_ellipses(revisions)
                    else 10
                    if revisions_include_dimension_tolerances(revisions)
                    else 9
                    if revisions_include_dimension_styles(revisions)
                    else 8
                    if revisions_include_dimension_text(revisions)
                    else 7
                    if revisions_include_projection_axes(revisions)
                    else 6
                    if relations_use_rectangle_segments(original, (relation,))
                    else 5
                    if revisions_include_local_endpoint_constraints(revisions)
                    else 4
                    if relation.first_endpoint or relation.second_endpoint
                    else 3
                    if relation.first.segment_index is not None
                    or relation.second.segment_index is not None
                    else 2
                    if revisions_include_curved_polylines(revisions)
                    else 1,
                    {"relation": relation.to_mapping(), "revisions": list(revisions)},
                    confirmed_by,
                ),
            ),
            False,
            target_archive_version=(
                8
                if revisions_include_curve_point_ids(revisions)
                and loaded.document.archive_version < 8
                else 6
                if loaded.document.archive_version < 6
                else None
            ),
        ),
        current_session_identity=session_identity,
    )
    preview = candidate.preview(current_session_identity=session_identity)
    if preview.state != "succeeded":
        reason = preview.failure.reason if preview.failure else "跨草图相切预览失败。"
        candidate.cancel()
        raise ValidationError(reason, command_id="drawing.tangency.add")
    if still_current is not None and not still_current():
        candidate.cancel()
        raise ValidationError("相切预览已过期或已取消。", command_id="drawing.tangency.add")
    grant = candidate.authorize_commit(current_session_identity=session_identity)
    return candidate.commit(grant, current_session_identity=session_identity)


def _common_rectangle_transform(
    sketches: tuple[Sketch, ...], transforms: tuple[RectangleTransformEvidence, ...]
) -> RectangleTransformEvidence | None:
    """Choose a seed only if all local proofs describe the same world transform."""
    if not transforms:
        return None
    frames = {sketch.sketch_id: sketch.frame for sketch in sketches}
    common = sketches[0].frame

    def transformed_world(
        evidence: RectangleTransformEvidence, point: tuple[float, float]
    ) -> tuple[float, float, float]:
        frame = frames[evidence.reference.sketch_id]
        local = frame.world_to_local(common.local_to_world(point))
        return frame.local_to_world(evidence.apply(local))

    first = transforms[0]
    if all(
        candidate.reflected == first.reflected
        and all(
            math.dist(transformed_world(first, point), transformed_world(candidate, point)) <= 1e-7
            for point in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
        )
        for candidate in transforms[1:]
    ):
        return first
    return None


def _polyline_transform_seed(
    reference: CrossSketchRef, before: PolylineEntity, after: PolylineEntity
) -> RectangleTransformEvidence | None:
    """Infer a rigid initial guess only when the entire polyline confirms it."""
    if (
        len(before.points_mm) != len(after.points_mm)
        or len(before.bulges) != len(after.bulges)
        or replace(before, points_mm=after.points_mm, bulges=after.bulges) != after
    ):
        return None
    x0, y0 = before.points_mm[0]
    x1, y1 = after.points_mm[0]
    for old, new in zip(before.points_mm[1:], after.points_mm[1:], strict=True):
        ux, uy = old[0] - x0, old[1] - y0
        vx, vy = new[0] - x1, new[1] - y1
        length2 = ux * ux + uy * uy
        if length2 <= 1e-20:
            continue
        candidates: list[RectangleTransformEvidence] = []
        for reflected in (False, True):
            if reflected:
                a = (ux * vx - uy * vy) / length2
                b = (uy * vx + ux * vy) / length2
                c, d = b, -a
            else:
                a = (ux * vx + uy * vy) / length2
                c = (ux * vy - uy * vx) / length2
                b, d = -c, a
            if not math.isclose(a * a + c * c, 1.0, abs_tol=1e-9, rel_tol=0):
                continue
            tx, ty = x1 - a * x0 - b * y0, y1 - c * x0 - d * y0
            if not all(
                math.isclose(a * x + b * y + tx, target[0], abs_tol=1e-7, rel_tol=0)
                and math.isclose(c * x + d * y + ty, target[1], abs_tol=1e-7, rel_tol=0)
                for (x, y), target in zip(before.points_mm, after.points_mm, strict=True)
            ) or not all(
                math.isclose(-old_bulge if reflected else old_bulge, new_bulge, abs_tol=1e-10)
                for old_bulge, new_bulge in zip(before.bulges, after.bulges, strict=True)
            ):
                continue
            candidates.append(
                RectangleTransformEvidence(
                    CrossSketchRef(reference.sketch_id, reference.entity_id), (a, b, c, d, tx, ty)
                )
            )
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) == 2:
            rotation = candidates[0]
            a, b, c, d, _, _ = rotation.matrix
            if all(
                math.isclose(value, expected, abs_tol=1e-9, rel_tol=0)
                for value, expected in zip((a, b, c, d), (1, 0, 0, 1), strict=True)
            ):
                return rotation
        return None
    return None


def _solve_cross_sketch_edit(
    proposed: tuple[Sketch, ...],
    relations: tuple[CrossSketchTangency, ...],
    anchors: tuple[CrossSketchRef, ...],
    seed_transform: RectangleTransformEvidence | None = None,
) -> tuple[Sketch, ...]:
    """Keep an independent curved polyline outside the tangent solver."""
    by_id = {sketch.sketch_id: sketch for sketch in proposed}
    independent = all(
        any(
            isinstance(entity, PolylineEntity)
            and bool(entity.bulges)
            and entity.entity_id == anchor.entity_id
            for entity in by_id[anchor.sketch_id].entities
        )
        and not any(
            ref.entity_id == anchor.entity_id
            for constraint in by_id[anchor.sketch_id].constraints
            for ref in constraint.references
        )
        and not any(
            ref.sketch_id == anchor.sketch_id and ref.entity_id == anchor.entity_id
            for relation in relations
            for ref in (relation.first, relation.second)
        )
        for anchor in anchors
    )
    if independent:
        validate_tangency_component(proposed, relations, anchors[0].sketch_id)
        return proposed
    return solve_tangency_component_anchored(
        proposed, relations, anchors[0].sketch_id, anchors, seed_transform
    )


def commit_cross_sketch_edit(
    services: AppServices,
    loaded: LoadedDocument,
    original: tuple[Sketch, ...],
    proposed: tuple[Sketch, ...],
    anchors: tuple[CrossSketchRef, ...],
    *,
    session_identity: int,
    confirmed_by: str = "local",
    expected_sketches: tuple[Sketch, ...] | None = None,
    still_current: Callable[[], bool] | None = None,
    rectangle_transforms: tuple[RectangleTransformEvidence, ...] = (),
    polyline_transforms: tuple[RectangleTransformEvidence, ...] = (),
    line_transforms: tuple[RectangleTransformEvidence, ...] = (),
) -> object:
    """Commit a fixed user edit and the resulting connected-sketch solution atomically."""
    if not anchors:
        raise ValidationError("跨草图联动编辑缺少目标。")
    relations = services.kernel.cross_sketch_tangencies
    try:
        current_by_id: dict[str, Sketch] = {}
        selected_ids: set[str] = set()
        for anchor in anchors:
            current, component_relations = resolve_tangency_component(
                services.kernel.sketches, relations, anchor.sketch_id
            )
            current_by_id.update((sketch.sketch_id, sketch) for sketch in current)
            selected_ids.update(item.relation_id for item in component_relations)
        selected = tuple(item for item in relations if item.relation_id in selected_ids)
        if len(original) != len(current_by_id) or any(
            current_by_id.get(sketch.sketch_id) != sketch for sketch in original
        ):
            raise ValueError("草图已变化；请重新开始联动编辑。")
        base_by_id = {sketch.sketch_id: sketch for sketch in original}
        if rectangle_transforms:
            proposed = tuple(
                replace(
                    sketch,
                    constraints=rebind_rectangle_constraints_for_sketch(
                        base_by_id[sketch.sketch_id], sketch, rectangle_transforms
                    ),
                )
                for sketch in proposed
            )
        build_tangency_revisions(
            original, proposed, rectangle_transforms, allow_local_rebind=bool(rectangle_transforms)
        )
        anchor_keys = {(item.sketch_id, item.entity_id) for item in anchors}
        available = {
            (sketch.sketch_id, entity.entity_id)
            for sketch in original
            for entity in sketch.entities
        }
        if len(anchor_keys) != len(anchors) or not anchor_keys.issubset(available):
            raise ValueError("联动编辑目标不存在或重复。")
        if any(
            (item.reference.sketch_id, item.reference.entity_id) not in anchor_keys
            for item in rectangle_transforms
        ):
            raise ValueError("矩形变换依据必须对应所选编辑目标。")
        for sketch in proposed:
            base = base_by_id[sketch.sketch_id]
            if any(
                before != after and (sketch.sketch_id, before.entity_id) not in anchor_keys
                for before, after in zip(base.entities, sketch.entities, strict=True)
            ):
                raise ValueError("联动编辑包含未指定为目标的图元变更。")
        if any(
            (item.reference.sketch_id, item.reference.entity_id) not in anchor_keys
            for item in (*polyline_transforms, *line_transforms)
        ):
            raise ValueError("曲线变换依据必须对应所选编辑目标。")
        if (
            not polyline_transforms
            and not line_transforms
            and len(anchors) == 1
            and not rectangle_transforms
        ):
            anchor = anchors[0]
            before = next(
                entity
                for entity in base_by_id[anchor.sketch_id].entities
                if entity.entity_id == anchor.entity_id
            )
            after = next(
                entity
                for sketch in proposed
                if sketch.sketch_id == anchor.sketch_id
                for entity in sketch.entities
                if entity.entity_id == anchor.entity_id
            )
            if isinstance(before, PolylineEntity) and isinstance(after, PolylineEntity):
                proof = _polyline_transform_seed(anchor, before, after)
                if (
                    proof is not None
                    and proof.reflected
                    and any(
                        ref.sketch_id == anchor.sketch_id and ref.entity_id == anchor.entity_id
                        for relation in selected
                        for ref in (relation.first, relation.second)
                    )
                ):
                    polyline_transforms = (proof,)
        rebound = rebind_committed_tangencies(
            original, proposed, selected, rectangle_transforms, polyline_transforms, line_transforms
        )
        replacements = tuple(
            after for before, after in zip(selected, rebound, strict=True) if before != after
        )
        by_relation = {relation.relation_id: relation for relation in rebound}
        solve_relations = tuple(
            by_relation.get(relation.relation_id, relation) for relation in relations
        )
        candidates = {sketch.sketch_id: sketch for sketch in proposed}
        pending = list(anchors)
        while pending:
            anchor = pending.pop(0)
            component, component_relations = resolve_tangency_component(
                tuple(candidates.values()), solve_relations, anchor.sketch_id
            )
            identities = {item.sketch_id for item in component}
            component_anchors = (
                anchor,
                *(item for item in pending if item.sketch_id in identities),
            )
            pending = [item for item in pending if item.sketch_id not in identities]
            if not component_relations:
                continue
            component_transforms = tuple(
                item for item in rectangle_transforms if item.reference.sketch_id in identities
            )
            component_polyline_transforms = tuple(
                item for item in polyline_transforms if item.reference.sketch_id in identities
            )
            component_line_transforms = tuple(
                item for item in line_transforms if item.reference.sketch_id in identities
            )
            transform_proofs = (
                *component_transforms,
                *component_polyline_transforms,
                *component_line_transforms,
            )
            seed = _common_rectangle_transform(component, transform_proofs)
            if transform_proofs and seed is None:
                raise ValueError("关联目标的变换依据不一致。")
            if (
                seed is None
                and not component_transforms
                and not component_polyline_transforms
                and not component_line_transforms
                and len(component_anchors) == 1
            ):
                anchor = component_anchors[0]
                before = next(
                    entity
                    for entity in base_by_id[anchor.sketch_id].entities
                    if entity.entity_id == anchor.entity_id
                )
                after = next(
                    entity
                    for entity in candidates[anchor.sketch_id].entities
                    if entity.entity_id == anchor.entity_id
                )
                if isinstance(before, PolylineEntity) and isinstance(after, PolylineEntity):
                    seed = _polyline_transform_seed(anchor, before, after)
            solved_component = _solve_cross_sketch_edit(
                component,
                solve_relations,
                component_anchors,
                seed,
            )
            candidates.update((item.sketch_id, item) for item in solved_component)
        solved = tuple(
            validate_sketch_revision_geometry(
                base_by_id[sketch.sketch_id], candidates[sketch.sketch_id]
            )
            for sketch in proposed
        )
        revisions = build_tangency_revisions(
            original, solved, rectangle_transforms, allow_local_rebind=bool(rectangle_transforms)
        )
        if expected_sketches is not None and {item.sketch_id: item for item in solved} != {
            item.sketch_id: item for item in expected_sketches
        }:
            raise ValueError("联动求解结果已变化，请重新预览。")
        if not revisions:
            raise ValueError("联动编辑没有改变几何。")
    except (KeyError, ValueError) as exc:
        raise ValidationError(str(exc), command_id="drawing.sketch.revise") from exc
    candidate = create_replay_candidate(services, loaded, session_identity=session_identity)
    candidate.stage(
        ReplayChangeSet(
            (),
            (
                ReplayAppend(
                    "drawing.sketch.revise",
                    56
                    if revisions_require_normal_side_preservation(services, revisions)
                    else 55
                    if revisions_include_ellipses(revisions)
                    else 53
                    if revisions_include_dimension_tolerances(revisions)
                    else 50
                    if revisions_include_dimension_styles(revisions)
                    else 48
                    if revisions_include_dimension_text(revisions)
                    else 34
                    if line_transforms
                    else 33
                    if polyline_transforms
                    else 31
                    if revisions_include_projection_axes(revisions)
                    else 29
                    if rectangle_transforms
                    else 8
                    if revisions_include_local_endpoint_constraints(revisions)
                    else 7
                    if any(
                        relation.first_endpoint or relation.second_endpoint
                        for relation in replacements
                    )
                    else 5
                    if replacements
                    else 3
                    if revisions_include_curved_polylines(revisions)
                    else 2,
                    {
                        "revisions": list(revisions),
                        **(
                            {"line_transforms": [item.to_mapping() for item in line_transforms]}
                            if line_transforms
                            else {}
                        ),
                        **(
                            {
                                "polyline_transforms": [
                                    item.to_mapping() for item in polyline_transforms
                                ]
                            }
                            if polyline_transforms
                            else {}
                        ),
                        **(
                            {
                                "rectangle_transforms": [
                                    item.to_mapping() for item in rectangle_transforms
                                ]
                            }
                            if rectangle_transforms
                            else {}
                        ),
                        **(
                            {
                                "remove_tangencies": [
                                    relation.relation_id for relation in replacements
                                ],
                                "cross_tangencies": [
                                    relation.to_mapping() for relation in replacements
                                ],
                            }
                            if replacements
                            else {}
                        ),
                    },
                    confirmed_by,
                ),
            ),
            False,
            target_archive_version=6 if loaded.document.archive_version < 6 else None,
        ),
        current_session_identity=session_identity,
    )
    preview = candidate.preview(current_session_identity=session_identity)
    if preview.state != "succeeded":
        reason = preview.failure.reason if preview.failure else "跨草图联动预览失败。"
        candidate.cancel()
        raise ValidationError(reason, command_id="drawing.sketch.revise")
    if still_current is not None and not still_current():
        candidate.cancel()
        raise ValidationError(
            "联动编辑期间操作已取消或文档已切换", command_id="drawing.sketch.revise"
        )
    grant = candidate.authorize_commit(current_session_identity=session_identity)
    return candidate.commit(grant, current_session_identity=session_identity)


def prepare_cross_sketch_dimension(
    services: AppServices,
    sketch_id: str,
    constraint: SketchConstraint,
) -> tuple[dict[str, object], tuple[Sketch, ...], tuple[SketchBranchChange, ...]]:
    """Solve and freeze a dimension change without modifying the document."""
    return prepare_cross_sketch_dimension_from_state(
        services.kernel.sketches, services.kernel.cross_sketch_tangencies, sketch_id, constraint
    )


def prepare_cross_sketch_dimension_from_state(
    sketches: tuple[Sketch, ...],
    relations: tuple[CrossSketchTangency, ...],
    sketch_id: str,
    constraint: SketchConstraint,
) -> tuple[dict[str, object], tuple[Sketch, ...], tuple[SketchBranchChange, ...]]:
    """Solve against a supplied isolated drawing view without mutating its source."""
    try:
        original, _ = resolve_tangency_component(sketches, relations, sketch_id)
        solved = solve_tangency_component_constraint(
            original, relations, sketch_id, constraint, allow_tangency=constraint.kind == "tangent"
        )
        source = next(sketch for sketch in original if sketch.sketch_id == sketch_id)
        dimension_base = (
            source.with_updated_constraint(constraint, source.entities)
            if any(item.constraint_id == constraint.constraint_id for item in source.constraints)
            else source.with_constraint(constraint, source.entities)
        )
        if constraint.layer_name is not None:
            annotation_layer = dimension_base.layers.get(constraint.layer_name)
            if annotation_layer.locked or not annotation_layer.displayed:
                raise ValueError("尺寸标注位于锁定或隐藏图层。")
        _validate_cross_sketch_edit_layers(original, solved)
        adjusted = tuple(
            dimension_base if item.sketch_id == sketch_id else item for item in original
        )
        revisions = list(build_tangency_revisions(adjusted, solved))
        if not any(item["sketch_id"] == sketch_id for item in revisions):
            state = next(item for item in solved if item.sketch_id == sketch_id).to_state_mapping()
            revisions.append(
                {
                    "sketch_id": sketch_id,
                    "base_state_sha256": source.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            )
        for revision in revisions:
            if revision["sketch_id"] == sketch_id:
                revision["base_state_sha256"] = source.local_state_digest()
    except (KeyError, StopIteration, ValueError) as exc:
        raise ValidationError(str(exc), command_id="drawing.sketch.revise") from exc
    return (
        {
            "revisions": revisions,
            "dimension": {"sketch_id": sketch_id, "constraint": constraint.to_mapping()},
            "solver_id": "planegcs",
            "solver_version": importlib.metadata.version("planegcs"),
        },
        solved,
        tuple(
            change
            for before in original
            for after in solved
            if before.sketch_id == after.sketch_id
            for change in detect_branch_changes(before, after)
        ),
    )


def prepare_cross_sketch_drag(
    services: AppServices,
    sketch_id: str,
    reference: SketchGeometryReference,
    target_mm: tuple[float, float],
) -> tuple[tuple[Sketch, ...], tuple[Sketch, ...], tuple[CrossSketchRef, ...]]:
    """Preview an owned handle and all tangent sketches without changing history."""
    return prepare_cross_sketch_drag_from_state(
        services,
        services.kernel.sketches,
        services.kernel.cross_sketch_tangencies,
        sketch_id,
        reference,
        target_mm,
    )


def prepare_cross_sketch_drag_from_state(
    services: AppServices,
    sketches: tuple[Sketch, ...],
    relations: tuple[CrossSketchTangency, ...],
    sketch_id: str,
    reference: SketchGeometryReference,
    target_mm: tuple[float, float],
) -> tuple[tuple[Sketch, ...], tuple[Sketch, ...], tuple[CrossSketchRef, ...]]:
    """Preview a handle using a supplied isolated drawing state."""
    try:
        original, selected = resolve_tangency_component(sketches, relations, sketch_id)
        source = next(sketch for sketch in original if sketch.sketch_id == sketch_id)
        result = services.kernel.preview_sketch_drag(source, reference, target_mm)
        if result.status != "success" or result.sketch is None:
            raise ValueError(result.message or "控制点拖动无法满足约束。")
        local = result.sketch
        anchors = tuple(
            CrossSketchRef(sketch_id, before.entity_id)
            for before, after in zip(source.entities, local.entities, strict=True)
            if before != after
        )
        if not anchors:
            raise ValueError("控制点拖动没有改变几何。")
        proposed = tuple(local if sketch.sketch_id == sketch_id else sketch for sketch in original)
        solved = _solve_cross_sketch_edit(proposed, relations, anchors) if selected else proposed
        by_id = {sketch.sketch_id: sketch for sketch in original}
        solved = tuple(
            validate_sketch_revision_geometry(by_id[item.sketch_id], item) for item in solved
        )
        _validate_cross_sketch_edit_layers(original, solved)
        build_tangency_revisions(original, solved)
        return original, solved, anchors
    except (KeyError, StopIteration, ValueError) as exc:
        raise ValidationError(str(exc), command_id="drawing.sketch.revise") from exc


def _validate_cross_sketch_edit_layers(
    original: tuple[Sketch, ...], solved: tuple[Sketch, ...]
) -> None:
    before = {sketch.sketch_id: sketch for sketch in original}
    if len(before) != len(original) or {sketch.sketch_id for sketch in solved} != set(before):
        raise ValueError("拖动预览的草图身份不一致。")
    for sketch in solved:
        source = before[sketch.sketch_id]
        changed_ids: set[str] = set()
        for previous, updated in zip(source.entities, sketch.entities, strict=True):
            layer = source.layers.get(previous.layer_name)
            if previous != updated and (layer.locked or not layer.displayed):
                raise ValueError("拖动目标或关联图元位于锁定或隐藏图层。")
            if previous != updated:
                changed_ids.add(previous.entity_id)
        source_entities = {entity.entity_id: entity for entity in source.entities}
        for constraint in source.constraints:
            if constraint.kind not in DIMENSION_KINDS or not any(
                ref.entity_id in changed_ids for ref in constraint.references
            ):
                continue
            entity = source_entities[constraint.references[0].entity_id]
            layer = source.layers.get(constraint.layer_name or entity.layer_name)
            if layer.locked or not layer.displayed:
                raise ValueError("相关标注位于锁定或隐藏图层。")


def commit_cross_sketch_drag(
    services: AppServices,
    loaded: LoadedDocument,
    original: tuple[Sketch, ...],
    solved: tuple[Sketch, ...],
    anchors: tuple[CrossSketchRef, ...],
    *,
    session_identity: int,
    still_current: Callable[[], bool] | None = None,
) -> object:
    """Commit precisely the accepted linked handle preview as one edit."""
    by_id = {sketch.sketch_id: sketch for sketch in solved}
    keys = {(ref.sketch_id, ref.entity_id) for ref in anchors}
    if not anchors or len(by_id) != len(solved) or set(by_id) != {s.sketch_id for s in original}:
        raise ValidationError("拖动预览包含无效的草图或目标。")
    try:
        _validate_cross_sketch_edit_layers(original, solved)
    except (KeyError, ValueError) as exc:
        raise ValidationError(str(exc), command_id="drawing.sketch.revise") from exc
    proposed: list[Sketch] = []
    for base in original:
        updated = {entity.entity_id: entity for entity in by_id[base.sketch_id].entities}
        if set(updated) != {entity.entity_id for entity in base.entities}:
            raise ValidationError("拖动预览更改了图元身份。")
        proposed.append(
            replace(
                base,
                entities=tuple(
                    updated[entity.entity_id]
                    if (base.sketch_id, entity.entity_id) in keys
                    else entity
                    for entity in base.entities
                ),
            )
        )
    return commit_cross_sketch_edit(
        services,
        loaded,
        original,
        tuple(proposed),
        anchors,
        session_identity=session_identity,
        expected_sketches=solved,
        still_current=still_current,
    )


def commit_cross_sketch_dimension(
    services: AppServices,
    loaded: LoadedDocument,
    sketch_id: str,
    constraint: SketchConstraint,
    *,
    session_identity: int,
    confirmed_by: str = "local",
    still_current: Callable[[], bool] | None = None,
    expected_sketches: tuple[Sketch, ...] | None = None,
) -> object:
    """Commit a dimension and the linked tangent geometry in one replayable edit."""
    params, solved, _ = prepare_cross_sketch_dimension(services, sketch_id, constraint)
    if expected_sketches is not None and {item.sketch_id: item for item in solved} != {
        item.sketch_id: item for item in expected_sketches
    }:
        raise ValidationError("联动求解结果已变化，请重新预览", command_id="drawing.sketch.revise")
    candidate = create_replay_candidate(services, loaded, session_identity=session_identity)
    candidate.stage(
        ReplayChangeSet(
            (),
            (
                ReplayAppend(
                    "drawing.sketch.revise",
                    64
                    if revisions_include_curve_point_ids(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 56
                    if revisions_require_normal_side_preservation(
                        services, cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 55
                    if revisions_include_ellipses(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 53
                    if revisions_include_dimension_tolerances(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 50
                    if revisions_include_dimension_styles(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 48
                    if revisions_include_dimension_text(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 38
                    if constraint.kind == "tangent"
                    else 31
                    if revisions_include_projection_axes(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 9
                    if revisions_include_local_endpoint_constraints(
                        cast("Sequence[Mapping[str, object]]", params["revisions"])
                    )
                    else 4,
                    params,
                    confirmed_by,
                ),
            ),
            False,
            target_archive_version=(
                8
                if loaded.document.archive_version < 8
                and revisions_include_curve_point_ids(
                    cast("Sequence[Mapping[str, object]]", params["revisions"])
                )
                else 6
                if loaded.document.archive_version < 6
                else None
            ),
        ),
        current_session_identity=session_identity,
    )
    preview = candidate.preview(current_session_identity=session_identity)
    if preview.state != "succeeded":
        reason = preview.failure.reason if preview.failure else "跨草图尺寸预览失败。"
        candidate.cancel()
        raise ValidationError(reason, command_id="drawing.sketch.revise")
    if still_current is not None and not still_current():
        candidate.cancel()
        raise ValidationError(
            "尺寸求解期间操作已取消或文档已切换", command_id="drawing.sketch.revise"
        )
    grant = candidate.authorize_commit(current_session_identity=session_identity)
    return candidate.commit(grant, current_session_identity=session_identity)


def prepare_mixed_draft_local_tangency(
    services: AppServices,
    saved: tuple[Sketch, ...],
    draft: Sketch,
    pairs: tuple[DraftTangentPair, ...],
    constraint: SketchConstraint,
    *,
    existing_relations: tuple[CrossSketchTangency, ...] | None = None,
) -> tuple[tuple[Sketch, ...], Sketch]:
    """Solve a draft tangency together with its existing drawing relations."""
    if constraint.kind != "tangent":
        raise ValueError("需要对象相切约束。")
    existing = (
        *(
            services.kernel.cross_sketch_tangencies
            if existing_relations is None
            else existing_relations
        ),
        *_draft_cross_relations(saved, draft, pairs),
    )
    if not any(
        draft.sketch_id in (relation.first.sketch_id, relation.second.sketch_id)
        for relation in existing
    ):
        result = services.kernel.preview_sketch_constraint(draft, constraint)
        if result.status != "success" or result.sketch is None:
            raise ValueError(result.message or "对象相切求解失败。")
        return saved, result.sketch
    original = (*saved, draft)
    solved = solve_tangency_component_constraint(
        original, existing, draft.sketch_id, constraint, allow_tangency=True
    )
    by_id = {item.sketch_id: item for item in solved}
    result_saved = tuple(by_id.get(item.sketch_id, item) for item in saved)
    result_draft = by_id.get(draft.sketch_id, draft)
    _validate_cross_sketch_edit_layers(original, (*result_saved, result_draft))
    return result_saved, result_draft


def prepare_mixed_draft_tangency(
    services: AppServices,
    saved: tuple[Sketch, ...],
    draft: Sketch,
    pairs: tuple[DraftTangentPair, ...],
    relation: CrossSketchTangency,
    *,
    existing_relations: tuple[CrossSketchTangency, ...] | None = None,
) -> tuple[tuple[Sketch, ...], Sketch]:
    """Solve a new saved-to-draft tangency without changing either source."""
    if sum(ref.sketch_id == draft.sketch_id for ref in (relation.first, relation.second)) != 1:
        raise ValueError("新相切关系必须连接草稿和已保存草图。")
    existing = (
        *(
            services.kernel.cross_sketch_tangencies
            if existing_relations is None
            else existing_relations
        ),
        *_draft_cross_relations(saved, draft, pairs),
    )
    if any({item.first, item.second} == {relation.first, relation.second} for item in existing):
        raise ValueError("所选曲线已有跨草图相切关系。")
    original = (*saved, draft)
    solved = solve_tangency_component(original, (*existing, relation), relation.first.sketch_id)
    by_id = {item.sketch_id: item for item in solved}
    result_saved = tuple(by_id.get(item.sketch_id, item) for item in saved)
    result_draft = by_id.get(draft.sketch_id, draft)
    _validate_cross_sketch_edit_layers(original, (*result_saved, result_draft))
    return result_saved, result_draft


def solve_mixed_draft_tangencies(
    original_saved: tuple[Sketch, ...],
    original_draft: Sketch,
    proposed_saved: tuple[Sketch, ...],
    proposed_draft: Sketch,
    pairs: tuple[DraftTangentPair, ...],
    existing_relations: tuple[CrossSketchTangency, ...],
    anchors: tuple[CrossSketchRef, ...],
    *,
    proposed_pairs: tuple[DraftTangentPair, ...] | None = None,
    rectangle_transforms: tuple[RectangleTransformEvidence, ...] = (),
) -> tuple[tuple[Sketch, ...], Sketch]:
    """Solve a mixed edit in isolation, preserving its original tangent branches."""
    original = (*original_saved, original_draft)
    proposed = (*proposed_saved, proposed_draft)
    original_by_id = {sketch.sketch_id: sketch for sketch in original}
    all_transforms = rectangle_transforms
    rectangle_transforms, polyline_transforms, line_transforms = split_transform_evidence(
        original, all_transforms
    )
    if rectangle_transforms:
        proposed = tuple(
            replace(
                sketch,
                constraints=rebind_rectangle_constraints_for_sketch(
                    original_by_id[sketch.sketch_id], sketch, rectangle_transforms
                ),
            )
            for sketch in proposed
        )
        proposed_saved, proposed_draft = proposed[:-1], proposed[-1]
    build_tangency_revisions(
        original,
        proposed,
        rectangle_transforms,
        allow_local_rebind=bool(rectangle_transforms),
        allow_user_polyline_rebind=True,
        allow_inferred_polyline_rebind=True,
    )
    draft_relations = _draft_cross_relations(original_saved, original_draft, pairs)
    if proposed_pairs is not None:
        if len(proposed_pairs) != len(pairs):
            raise ValueError("重绑定相切关系数量不一致。")
        updated_saved = {sketch.sketch_id: sketch for sketch in proposed_saved}
        old_saved = {sketch.sketch_id: sketch for sketch in original_saved}
        rebound: list[CrossSketchTangency] = []
        for relation, old_pair, new_pair in zip(
            draft_relations, pairs, proposed_pairs, strict=True
        ):
            refs = tuple(draft_tangent_reference(item) for item in new_pair)
            old_refs = tuple(draft_tangent_reference(item) for item in old_pair)
            if any(
                item.reference.sketch_id == ref.sketch_id
                and item.reference.entity_id == ref.entity_id
                for item in all_transforms
                for ref in (relation.first, relation.second)
            ):
                changed = rebind_committed_tangencies(
                    original,
                    proposed,
                    (relation,),
                    rectangle_transforms,
                    polyline_transforms,
                    line_transforms,
                )[0]
                endpoints = tuple(
                    item.endpoint if isinstance(item, DraftConnectedEndpoint) else None
                    for item in new_pair
                )
                if (
                    (changed.first.segment_index, changed.second.segment_index)
                    != (refs[0].index, refs[1].index)
                    or (changed.first.entity_id, changed.second.entity_id)
                    != (refs[0].entity_id, refs[1].entity_id)
                    or (changed.first_endpoint, changed.second_endpoint) != endpoints
                ):
                    raise ValueError("矩形相切关系重绑定与变换依据不一致。")
                rebound.append(changed)
                continue
            if any(
                old.entity_id != new.entity_id or old.kind != new.kind
                for old, new in zip(old_refs, refs, strict=True)
            ):
                raise ValueError("重绑定不能改变相切图元身份。")
            if any(
                (old.endpoint if isinstance(old, DraftConnectedEndpoint) else None)
                != (new.endpoint if isinstance(new, DraftConnectedEndpoint) else None)
                for old, new in zip(old_pair, new_pair, strict=True)
            ):
                raise ValueError("重绑定不能改变相切端点。")
            old_sketches = (old_saved[relation.first.sketch_id], original_draft)
            new_sketches = (updated_saved[relation.first.sketch_id], proposed_draft)
            for old_ref, new_ref, old_sketch, new_sketch in zip(
                old_refs, refs, old_sketches, new_sketches, strict=True
            ):
                if old_ref.index == new_ref.index:
                    continue
                old_entity = next(
                    item for item in old_sketch.entities if item.entity_id == old_ref.entity_id
                )
                new_entity = next(
                    item for item in new_sketch.entities if item.entity_id == new_ref.entity_id
                )
                if (
                    not isinstance(old_entity, PolylineEntity)
                    or not isinstance(new_entity, PolylineEntity)
                    or old_ref.index is None
                    or unique_unchanged_polyline_segment(old_entity, new_entity, old_ref.index)
                    != new_ref.index
                ):
                    raise ValueError("无法唯一重绑定相切段。")
            rebound.append(
                replace(
                    relation,
                    first=replace(relation.first, segment_index=refs[0].index),
                    second=replace(relation.second, segment_index=refs[1].index),
                )
            )
        draft_relations = tuple(rebound)
    original_ids = {sketch.sketch_id for sketch in original}
    relevant = tuple(
        relation
        for relation in existing_relations
        if relation.first.sketch_id in original_ids and relation.second.sketch_id in original_ids
    )
    rebound_existing = rebind_committed_tangencies(
        original, proposed, relevant, rectangle_transforms, polyline_transforms, line_transforms
    )
    rebound_by_id = {relation.relation_id: relation for relation in rebound_existing}
    relations = (
        *(rebound_by_id.get(relation.relation_id, relation) for relation in existing_relations),
        *draft_relations,
    )
    if len({item.relation_id for item in relations}) != len(relations):
        raise ValueError("跨草图相切关系身份重复。")
    originals = {sketch.sketch_id: sketch for sketch in original}
    candidates = {sketch.sketch_id: sketch for sketch in proposed}
    anchor_keys = {(item.sketch_id, item.entity_id) for item in anchors}
    available = {
        (sketch.sketch_id, entity.entity_id) for sketch in original for entity in sketch.entities
    }
    if len(anchor_keys) != len(anchors) or not anchor_keys.issubset(available):
        raise ValueError("联动编辑目标不存在或重复。")
    for sketch in proposed:
        base = originals[sketch.sketch_id]
        if any(
            before != after and (sketch.sketch_id, before.entity_id) not in anchor_keys
            for before, after in zip(base.entities, sketch.entities, strict=True)
        ):
            raise ValueError("联动编辑包含未指定为目标的图元变更。")
    pending = list(anchors)
    while pending:
        anchor = pending.pop(0)
        if anchor.sketch_id not in candidates:
            raise ValueError("联动编辑目标不存在。")
        component, selected = resolve_tangency_component(
            tuple(candidates.values()), relations, anchor.sketch_id
        )
        identities = {item.sketch_id for item in component}
        component_anchors = (anchor, *(item for item in pending if item.sketch_id in identities))
        pending = [item for item in pending if item.sketch_id not in identities]
        relation_keys = {
            (ref.sketch_id, ref.entity_id)
            for relation in selected
            for ref in (relation.first, relation.second)
        }
        if not any((item.sketch_id, item.entity_id) in relation_keys for item in component_anchors):
            for sketch in component:
                if sketch != originals[sketch.sketch_id]:
                    candidates[sketch.sketch_id] = validate_sketch_revision_geometry(
                        originals[sketch.sketch_id], sketch
                    )
            continue
        component = _seed_mirrored_tangent_circles(
            component, originals, component_anchors, selected
        )
        component_transforms = tuple(
            item for item in all_transforms if item.reference.sketch_id in identities
        )
        solved = _solve_cross_sketch_edit(
            component,
            relations,
            component_anchors,
            _common_rectangle_transform(component, component_transforms),
        )
        for sketch in solved:
            validate_sketch_revision_geometry(originals[sketch.sketch_id], sketch)
            candidates[sketch.sketch_id] = sketch
    result = (
        tuple(candidates[sketch.sketch_id] for sketch in original_saved),
        candidates[original_draft.sketch_id],
    )
    _validate_cross_sketch_edit_layers(original, (*result[0], result[1]))
    return result


def prepare_mixed_handle_drag(
    services: AppServices,
    saved: tuple[Sketch, ...],
    draft: Sketch,
    pairs: tuple[DraftTangentPair, ...],
    relations: tuple[CrossSketchTangency, ...],
    target: CrossSketchRef,
    reference: SketchGeometryReference,
    target_mm: tuple[float, float],
) -> tuple[tuple[Sketch, ...], Sketch, tuple[CrossSketchRef, ...]]:
    """Preview a saved or draft handle together with staged relations."""
    if reference.entity_id != target.entity_id:
        raise ValueError("控制点与所选图元不一致。")
    owners = [item for item in (*saved, draft) if item.sketch_id == target.sketch_id]
    if (
        len(owners) != 1
        or sum(entity.entity_id == target.entity_id for entity in owners[0].entities) != 1
    ):
        raise ValueError("控制点来源不存在或身份不唯一。")
    source = owners[0]
    result = services.kernel.preview_sketch_drag(source, reference, target_mm)
    if result.status != "success" or result.sketch is None:
        raise ValueError(result.message or "控制点拖动无法满足约束。")
    anchors = tuple(
        CrossSketchRef(source.sketch_id, before.entity_id)
        for before, after in zip(source.entities, result.sketch.entities, strict=True)
        if before != after
    )
    if not anchors:
        raise ValueError("控制点未移动。")
    proposed = tuple(
        result.sketch if item.sketch_id == source.sketch_id else item for item in saved
    )
    proposed_draft = result.sketch if source.sketch_id == draft.sketch_id else draft
    solved_saved, solved_draft = solve_mixed_draft_tangencies(
        saved, draft, proposed, proposed_draft, pairs, relations, anchors
    )
    return solved_saved, solved_draft, anchors


def _seed_mirrored_tangent_circles(
    component: tuple[Sketch, ...],
    originals: Mapping[str, Sketch],
    anchors: tuple[CrossSketchRef, ...],
    relations: tuple[CrossSketchTangency, ...],
) -> tuple[Sketch, ...]:
    """Seed free circles by the rigid mirror of an anchored arc, when unambiguous."""
    if any(sketch.constraints for sketch in component):
        return component
    by_id = {sketch.sketch_id: sketch for sketch in component}
    anchor_keys = {(item.sketch_id, item.entity_id) for item in anchors}
    relation_keys = {
        (ref.sketch_id, ref.entity_id)
        for relation in relations
        for ref in (relation.first, relation.second)
    }
    mirrors: list[tuple[Sketch, ArcEntity, ArcEntity]] = []
    for anchor in anchors:
        sketch = by_id[anchor.sketch_id]
        before = next(
            e for e in originals[anchor.sketch_id].entities if e.entity_id == anchor.entity_id
        )
        after = next(e for e in sketch.entities if e.entity_id == anchor.entity_id)
        if (
            isinstance(before, ArcEntity)
            and isinstance(after, ArcEntity)
            and abs(before.sweep_angle_deg + after.sweep_angle_deg) < 1e-8
            and abs(before.radius_mm - after.radius_mm) < 1e-8
        ):
            mirrors.append((sketch, before, after))
    if len(mirrors) != 1:
        return component
    reference, before, after = mirrors[0]
    angle = math.radians(before.start_angle_deg + after.start_angle_deg)
    cosine, sine = math.cos(angle), math.sin(angle)

    def transformed(point: tuple[float, float]) -> tuple[float, float]:
        x, y = point[0] - before.center_mm[0], point[1] - before.center_mm[1]
        return (
            after.center_mm[0] + cosine * x + sine * y,
            after.center_mm[1] + sine * x - cosine * y,
        )

    result: list[Sketch] = []
    for sketch in component:
        entities: list[SketchEntity] = []
        for entity in sketch.entities:
            key = (sketch.sketch_id, entity.entity_id)
            if isinstance(entity, CircleEntity) and key in relation_keys and key not in anchor_keys:
                projected = project_tangent_entity(entity, sketch.frame, reference.frame)
                assert isinstance(projected, CircleEntity)
                reflected = replace(projected, center_mm=transformed(projected.center_mm))
                entity = project_tangent_entity(reflected, reference.frame, sketch.frame)
            entities.append(entity)
        result.append(replace(sketch, entities=tuple(entities)))
    return tuple(result)


def stage_mixed_drawing_move(
    services: AppServices,
    loaded: LoadedDocument,
    original_draft: Sketch,
    revisions: Sequence[Mapping[str, object]],
    *,
    session_identity: int,
    followup_steps: Sequence[Sequence[Mapping[str, object]]] = (),
    inferred_rebind_steps: Sequence[bool] = (),
    user_rebind_steps: Sequence[bool] = (),
) -> ReplayCandidateSession:
    """Stage draft creation followed by an atomic multi-sketch revision."""
    if loaded.document.document_type != "drawing2d":
        raise ValidationError("混合变换仅支持独立二维文档。")
    if (
        not revisions
        or sum(revision.get("sketch_id") == original_draft.sketch_id for revision in revisions) > 1
    ):
        raise ValidationError("混合变换必须包含修订，且草稿修订不能重复。")
    if inferred_rebind_steps and len(inferred_rebind_steps) != 1 + len(followup_steps):
        raise ValidationError("混合修订与推断引用重绑定历史不一致。")
    if user_rebind_steps and len(user_rebind_steps) != 1 + len(followup_steps):
        raise ValidationError("混合修订与用户引用重绑定历史不一致。")
    candidate = create_replay_candidate(services, loaded, session_identity=session_identity)

    def revision_version(step: Sequence[Mapping[str, object]], rebind: bool, user: bool) -> int:
        if revisions_require_normal_side_preservation(services, step):
            return 56
        if revisions_include_ellipses(step):
            return 55
        if revisions_include_dimension_tolerances(step):
            return 53
        if revisions_include_dimension_styles(step):
            return 50
        if revisions_include_dimension_text(step):
            return 48
        if user:
            return 32
        if revisions_include_projection_axes(step):
            return 31
        if rebind:
            return 10
        if revisions_include_local_endpoint_constraints(step):
            return 8
        if revisions_include_curved_polylines(step):
            return 3
        for revision in step:
            constraints = revision.get("constraints")
            if isinstance(constraints, list | tuple):
                for item in cast("Sequence[object]", constraints):
                    if isinstance(item, Mapping):
                        constraint = cast("Mapping[str, object]", item)
                        if (
                            constraint.get("kind") == "tangent"
                            and constraint.get("source") == "inferred"
                        ):
                            return 2
        return 1

    candidate.stage(
        ReplayChangeSet(
            (),
            (
                ReplayAppend(
                    "sketch.create",
                    53
                    if any(isinstance(entity, EllipseEntity) for entity in original_draft.entities)
                    else 46
                    if any(c.tolerance is not None for c in original_draft.constraints)
                    else 32
                    if any(c.style_name is not None for c in original_draft.constraints)
                    else 30
                    if any(c.text_override is not None for c in original_draft.constraints)
                    else 28
                    if any(c.projection_axis is not None for c in original_draft.constraints)
                    else 13
                    if any(
                        c.first_endpoint or c.second_endpoint for c in original_draft.constraints
                    )
                    else 9
                    if any(
                        constraint.kind
                        in ("parallel", "perpendicular", "concentric", "equal", "fixed")
                        or (
                            constraint.source == "user"
                            and constraint.kind
                            in ("horizontal", "vertical", "coincident", "tangent")
                        )
                        for constraint in original_draft.constraints
                    )
                    else 8
                    if any(
                        isinstance(entity, PolylineEntity) and entity.bulges
                        for entity in original_draft.entities
                    )
                    else 6
                    if any(
                        constraint.kind == "tangent" for constraint in original_draft.constraints
                    )
                    else 5
                    if any(isinstance(entity, PointEntity) for entity in original_draft.entities)
                    else 3,
                    original_draft.to_state_mapping(),
                    "local",
                ),
                ReplayAppend(
                    "drawing.sketch.revise",
                    revision_version(
                        revisions,
                        bool(inferred_rebind_steps and inferred_rebind_steps[0]),
                        bool(user_rebind_steps and user_rebind_steps[0]),
                    ),
                    {"revisions": list(revisions)},
                    "local",
                ),
                *(
                    ReplayAppend(
                        "drawing.sketch.revise",
                        revision_version(
                            step,
                            bool(inferred_rebind_steps and inferred_rebind_steps[index + 1]),
                            bool(user_rebind_steps and user_rebind_steps[index + 1]),
                        ),
                        {"revisions": list(step)},
                        "local",
                    )
                    for index, step in enumerate(followup_steps)
                ),
            ),
            False,
            target_archive_version=6 if loaded.document.archive_version < 6 else None,
            undo_appends_separately=True,
        ),
        current_session_identity=session_identity,
    )
    return candidate


def _affected_revision_sketches(
    services: AppServices, revisions: Sequence[Mapping[str, object]]
) -> set[str]:
    """Include sketches reached through associative-array propagation."""
    affected = {
        identity
        for revision in revisions
        if isinstance((identity := revision.get("sketch_id")), str)
    }
    while True:
        before = len(affected)
        for array in services.kernel.associative_arrays:
            if any(source.sketch_id in affected for source in array.sources):
                affected.update(member.target.sketch_id for member in array.members)
                affected.update(output.target.sketch_id for output in array.extra_outputs)
            for member in array.members:
                replacement = member.replacement
                if replacement is not None and (
                    replacement.source.sketch_id in affected
                    or (
                        replacement.anchor_source is not None
                        and replacement.anchor_source.sketch_id in affected
                    )
                ):
                    affected.add(member.target.sketch_id)
            for output in array.extra_outputs:
                if (
                    output.source.sketch_id in affected
                    or output.anchor_source.sketch_id in affected
                ):
                    affected.add(output.target.sketch_id)
        if len(affected) == before:
            return affected


def revisions_require_attachment_protection(
    services: AppServices, revisions: Sequence[Mapping[str, object]]
) -> bool:
    """Whether a changed sketch has attached datum or frame geometry."""
    sketch_ids = _affected_revision_sketches(services, revisions)
    return any(
        attachment is not None and attachment.sketch_id in sketch_ids
        for item in (
            *services.kernel.drawing_datum_identifiers,
            *services.kernel.drawing_tolerance_frames,
        )
        for attachment in (
            item.attachment if isinstance(item, DatumIdentifier) else item.leader_attachment,
        )
    )


def exact_attached_polyline_reorder_maps(
    services: AppServices, before: Sequence[Sketch], after: Sequence[Sketch]
) -> tuple[tuple[dict[str, object], ...], bool, int]:
    """Derive maps only for uniquely identifiable, unchanged polyline paths."""
    from mycad.core.geometric_tolerance_topology import (
        PolylineTopologyMap,
        associative_topology_entities,
        has_internal_reorder_dependents,
        rebind_array_base,
        simple_array_reorder_chain,
        simple_array_reorder_members,
        stable_array_base_ids,
        validate_topology_constraint_rebinding,
    )

    associated = associative_topology_entities(services.kernel.associative_arrays, ())
    attachments = {
        (attachment.sketch_id, attachment.reference.entity_id)
        for item in (
            *services.kernel.drawing_datum_identifiers,
            *services.kernel.drawing_tolerance_frames,
        )
        for attachment in (
            item.attachment if isinstance(item, DatumIdentifier) else item.leader_attachment,
        )
        if attachment is not None
    }
    tangent_entities = {
        (reference.sketch_id, reference.entity_id)
        for relation in services.kernel.cross_sketch_tangencies
        for reference in (relation.first, relation.second)
    }
    after_by_id = {sketch.sketch_id: sketch for sketch in after}
    records: list[dict[str, object]] = []
    requires_base_rebind = False
    array_proof_version = 0
    for original in before:
        revised = after_by_id.get(original.sketch_id)
        if revised is None:
            continue
        revised_entities = {entity.entity_id: entity for entity in revised.entities}
        constrained = {
            reference.entity_id
            for constraint in (*original.constraints, *revised.constraints)
            for reference in constraint.references
        }
        for source in original.entities:
            if not isinstance(source, PolylineEntity):
                continue
            key = (original.sketch_id, source.entity_id)
            target = revised_entities.get(source.entity_id)
            if (
                not isinstance(target, PolylineEntity)
                or source.points_mm == target.points_mm
                or len(source.points_mm) != len(target.points_mm)
                or len(set(target.points_mm)) != len(target.points_mm)
            ):
                continue
            positions = {point: index for index, point in enumerate(target.points_mm)}
            try:
                if source.entity_id in constrained:
                    validate_topology_constraint_rebinding(
                        original, revised, frozenset((source.entity_id,))
                    )
                mapping = PolylineTopologyMap(
                    source.entity_id,
                    tuple(positions[point] for point in source.points_mm),
                    len(target.points_mm),
                    source.closed,
                )
                mapping.validate_exact_reorder(source, target)
                members: tuple[tuple[ArrayEntityRef, ArrayEntityRef], ...] = ()
                changed_bases: set[str] = set()
                chain_proof_version = 0
                if key in associated:
                    stable_bases = set(
                        stable_array_base_ids(
                            services.kernel.associative_arrays,
                            before,
                            after,
                            {key: mapping},
                        )
                    )
                    for array in services.kernel.associative_arrays:
                        base = array.base_point
                        if base is None or base.source is None:
                            continue
                        if (base.source.sketch_id, base.source.entity_id) != key:
                            continue
                        updated_array = rebind_array_base(array, original, revised, mapping)
                        if updated_array != array:
                            stable_bases.add(array.array_id)
                            changed_bases.add(array.array_id)
                    try:
                        members = simple_array_reorder_members(
                            services.kernel.associative_arrays,
                            frozenset((key,)),
                            stable_anchor_sources=(
                                frozenset((key,))
                                if source.points_mm[0] == target.points_mm[0]
                                else frozenset()
                            ),
                            stable_base_arrays=frozenset(stable_bases),
                            allow_stable_replacements=True,
                            allow_stable_extra_outputs=True,
                            allow_reordered_extra_outputs=True,
                            allow_independent_extra_sources=True,
                            allow_replacement_source=True,
                        )
                        if has_internal_reorder_dependents(
                            services.kernel.associative_arrays, members
                        ):
                            raise ValueError("阵列内部来源需要逐层证明。")
                    except ValueError:
                        stable_anchors: frozenset[tuple[str, str]] = (
                            frozenset((key,))
                            if source.points_mm[0] == target.points_mm[0]
                            else frozenset()
                        )
                        stable_vertices = {
                            key: frozenset(
                                index
                                for index, new_index in enumerate(mapping.old_to_new)
                                if index == new_index
                            )
                        }
                        for proof_version in range(66, 77):
                            try:
                                members = simple_array_reorder_chain(
                                    services.kernel.associative_arrays,
                                    frozenset((key,)),
                                    stable_anchor_sources=(
                                        stable_anchors if proof_version >= 67 else frozenset()
                                    ),
                                    allow_stable_bases=proof_version >= 68,
                                    stable_base_vertices=(
                                        stable_vertices if proof_version >= 69 else None
                                    ),
                                    allow_base_rebinding=proof_version >= 70,
                                    allow_unchanged_replacements=proof_version >= 71,
                                    allow_reordered_replacements=proof_version >= 72,
                                    allow_extra_outputs=proof_version >= 73,
                                    allow_simultaneous_replacements=proof_version >= 74,
                                    defer_affected_dependencies=proof_version >= 75,
                                    allow_mixed_replacement_extras=proof_version >= 76,
                                    known_stable_base_arrays=(
                                        frozenset(stable_bases)
                                        if proof_version >= 75
                                        else frozenset()
                                    ),
                                )
                            except ValueError:
                                continue
                            chain_proof_version = proof_version
                            break
                        else:
                            raise ValueError("阵列拓扑无法安全证明。")

                member_keys = {(member.sketch_id, member.entity_id) for _source, member in members}
                if key not in attachments and not member_keys & (attachments | tangent_entities):
                    continue
                if key in associated and chain_proof_version:
                    array_proof_version = max(array_proof_version, chain_proof_version)
                if member_keys & tangent_entities:
                    first, second = mapping.old_to_new[:2]
                    segment_count = mapping.new_count if mapping.closed else mapping.new_count - 1
                    forward = (
                        first is not None
                        and second is not None
                        and first < segment_count
                        and (first + 1) % mapping.new_count == second
                    )
                    array_proof_version = max(array_proof_version, 77 if forward else 78)
                    if any(
                        key
                        in {
                            (relation.first.sketch_id, relation.first.entity_id),
                            (relation.second.sketch_id, relation.second.entity_id),
                        }
                        and any(
                            (ref.sketch_id, ref.entity_id) in member_keys
                            for ref in (relation.first, relation.second)
                        )
                        for relation in services.kernel.cross_sketch_tangencies
                    ):
                        array_proof_version = max(array_proof_version, 79)
                if key in associated and changed_bases:
                    requires_base_rebind = True
                if key in associated and any(
                    member.replacement is not None
                    and (
                        member.replacement.source.sketch_id,
                        member.replacement.source.entity_id,
                    )
                    == key
                    for array in services.kernel.associative_arrays
                    for member in array.members
                ):
                    array_proof_version = max(array_proof_version, 65)
                if key in associated and any(
                    any((ref.sketch_id, ref.entity_id) == key for ref in array.sources)
                    and any(member.replacement is not None for member in array.members)
                    for array in services.kernel.associative_arrays
                ):
                    array_proof_version = max(array_proof_version, 59)
                if key in associated and any(
                    any((ref.sketch_id, ref.entity_id) == key for ref in array.sources)
                    and array.extra_outputs
                    for array in services.kernel.associative_arrays
                ):
                    array_proof_version = max(array_proof_version, 60)
                if key in associated and any(
                    any(
                        (output.source.sketch_id, output.source.entity_id) == key
                        for output in array.extra_outputs
                    )
                    for array in services.kernel.associative_arrays
                ):
                    array_proof_version = max(array_proof_version, 61)
                if key in associated and any(
                    any(
                        (output.source.sketch_id, output.source.entity_id) == key
                        for output in array.extra_outputs
                    )
                    and all((ref.sketch_id, ref.entity_id) != key for ref in array.sources)
                    for array in services.kernel.associative_arrays
                ):
                    array_proof_version = max(array_proof_version, 62)
            except (KeyError, ValueError):
                continue
            records.append({"sketch_id": original.sketch_id, "mapping": mapping.to_mapping()})
    if len(records) > 1 and services.kernel.associative_arrays:
        combined_maps = {
            (cast("str", record["sketch_id"]), mapping.entity_id): mapping
            for record in records
            for mapping in (PolylineTopologyMap.from_mapping(record["mapping"]),)
        }
        original_by_id = {sketch.sketch_id: sketch for sketch in before}
        combined_stable: set[tuple[str, str]] = set()
        for sketch_id, entity_id in combined_maps:
            old_sketch = original_by_id[sketch_id]
            new_sketch = after_by_id[sketch_id]
            old = next(item for item in old_sketch.entities if item.entity_id == entity_id)
            new = next(item for item in new_sketch.entities if item.entity_id == entity_id)
            if (
                isinstance(old, PolylineEntity)
                and isinstance(new, PolylineEntity)
                and old.points_mm[0] == new.points_mm[0]
            ):
                combined_stable.add((sketch_id, entity_id))
        vertices = {
            key: frozenset(
                index for index, new_index in enumerate(mapping.old_to_new) if index == new_index
            )
            for key, mapping in combined_maps.items()
        }

        def prove_combined(*, simultaneous: bool, defer: bool = False, mixed: bool = False) -> None:
            edges = simple_array_reorder_chain(
                services.kernel.associative_arrays,
                frozenset(combined_maps),
                stable_anchor_sources=frozenset(combined_stable),
                allow_stable_bases=True,
                stable_base_vertices=vertices,
                allow_base_rebinding=True,
                allow_unchanged_replacements=True,
                allow_reordered_replacements=True,
                allow_extra_outputs=True,
                allow_simultaneous_replacements=simultaneous,
                defer_affected_dependencies=defer,
                allow_mixed_replacement_extras=mixed,
                known_stable_base_arrays=(
                    stable_array_base_ids(
                        services.kernel.associative_arrays, before, after, combined_maps
                    )
                    if defer
                    else frozenset()
                ),
            )
            targets = [target for _source, target in edges]
            if len(targets) != len(set(targets)):
                raise ValueError("链式阵列依赖顺序不明确。")

        try:
            prove_combined(simultaneous=False)
        except ValueError:
            try:
                prove_combined(simultaneous=True)
            except ValueError:
                try:
                    prove_combined(simultaneous=True, defer=True)
                except ValueError:
                    try:
                        prove_combined(simultaneous=True, defer=True, mixed=True)
                    except ValueError:
                        pass
                    else:
                        array_proof_version = max(array_proof_version, 76)
                else:
                    array_proof_version = max(array_proof_version, 75)
            else:
                array_proof_version = max(array_proof_version, 74)
    return tuple(records), requires_base_rebind, array_proof_version


def revisions_require_normal_side_preservation(
    services: AppServices, revisions: Sequence[Mapping[str, object]]
) -> bool:
    """Whether a changed sketch owns geometry with a constrained annotation leader."""
    sketch_ids = _affected_revision_sketches(services, revisions)
    for item in (
        *services.kernel.drawing_datum_identifiers,
        *services.kernel.drawing_tolerance_frames,
    ):
        attachment = (
            item.attachment if isinstance(item, DatumIdentifier) else item.leader_attachment
        )
        surface = item.surface_indication
        if (
            attachment is not None
            and attachment.sketch_id in sketch_ids
            and (item.leader_auto_normal or (surface is not None and surface.auto_normal))
        ):
            return True
    return False


def revisions_include_curved_polylines(revisions: Sequence[Mapping[str, object]]) -> bool:
    """Determine whether frozen revisions require the curved-polyline schema."""
    for revision in revisions:
        raw = revision.get("entities")
        if not isinstance(raw, list | tuple):
            continue
        for value in cast("Sequence[object]", raw):
            if isinstance(value, Mapping) and cast("Mapping[str, object]", value).get("bulges"):
                return True
    return False


def sketch_has_curve_point_ids(sketch: Sketch) -> bool:
    """Whether a frozen sketch requires identity-aware command versions."""
    return any(
        isinstance(entity, PolylineEntity | SplineEntity) and bool(entity.point_ids)
        for entity in sketch.entities
    )


def revisions_include_curve_point_ids(revisions: Sequence[Mapping[str, object]]) -> bool:
    """Detect identity-bearing curve data in a frozen multi-sketch solution."""
    for revision in revisions:
        raw = revision.get("entities")
        if not isinstance(raw, list | tuple):
            continue
        for value in cast("Sequence[object]", raw):
            if isinstance(value, Mapping) and cast("Mapping[str, object]", value).get("point_ids"):
                return True
    return False


def revisions_include_ellipses(revisions: Sequence[Mapping[str, object]]) -> bool:
    """Identify revisions that require the ellipse-capable entity schema."""
    for revision in revisions:
        raw = revision.get("entities")
        if isinstance(raw, list | tuple) and any(
            isinstance(value, Mapping)
            and cast("Mapping[str, object]", value).get("kind") == "ellipse"
            for value in cast("Sequence[object]", raw)
        ):
            return True
    return False


def revisions_include_local_endpoint_constraints(
    revisions: Sequence[Mapping[str, object]],
) -> bool:
    """Identify frozen sketches carrying explicitly connected local tangencies."""
    for revision in revisions:
        raw = revision.get("constraints")
        if isinstance(raw, list | tuple) and any(
            isinstance(value, Mapping) and ("first_endpoint" in value or "second_endpoint" in value)
            for value in cast("Sequence[object]", raw)
        ):
            return True
    return False


def revisions_include_dimension_styles(revisions: Sequence[Mapping[str, object]]) -> bool:
    """Identify revisions carrying a drawing dimension style reference."""
    for revision in revisions:
        raw = revision.get("constraints")
        if isinstance(raw, list | tuple) and any(
            isinstance(value, Mapping) and "style_name" in value
            for value in cast("Sequence[object]", raw)
        ):
            return True
    return False


def revisions_include_dimension_tolerances(revisions: Sequence[Mapping[str, object]]) -> bool:
    """Identify revisions requiring structured dimension-tolerance fields."""
    for revision in revisions:
        raw = revision.get("constraints")
        if isinstance(raw, list | tuple) and any(
            isinstance(value, Mapping) and "tolerance" in value
            for value in cast("Sequence[object]", raw)
        ):
            return True
    return False


def revisions_include_dimension_text(revisions: Sequence[Mapping[str, object]]) -> bool:
    """Identify revisions carrying display text that needs the new schema."""
    for revision in revisions:
        raw = revision.get("constraints")
        if isinstance(raw, list | tuple) and any(
            isinstance(value, Mapping) and "text_override" in value
            for value in cast("Sequence[object]", raw)
        ):
            return True
    return False


def revisions_include_projection_axes(revisions: Sequence[Mapping[str, object]]) -> bool:
    """Identify frozen revisions requiring explicit dimension projection axes."""
    for revision in revisions:
        raw = revision.get("constraints")
        if isinstance(raw, list | tuple) and any(
            isinstance(value, Mapping) and "projection_axis" in value
            for value in cast("Sequence[object]", raw)
        ):
            return True
    return False


def stage_mixed_drawing_timeline(
    services: AppServices,
    loaded: LoadedDocument,
    original_draft: Sketch,
    original_saved: Sequence[Sketch],
    steps: Sequence[tuple[Sequence[Sketch], Sketch]],
    *,
    session_identity: int,
    cross_pairs_by_step: Sequence[tuple[DraftTangentPair, ...]] = (),
    initial_cross_pairs: tuple[DraftTangentPair, ...] = (),
    arrays_by_step: Sequence[tuple[AssociativeRectArray, ...]] = (),
    initial_associative_arrays: tuple[AssociativeRectArray, ...] | None = None,
    rectangle_transforms_by_step: Sequence[tuple[RectangleTransformEvidence, ...]] = (),
) -> ReplayCandidateSession:
    """Stage each retained draft edit as its own replayable history step."""
    current_saved = {sketch.sketch_id: sketch for sketch in services.kernel.sketches}
    prior = {sketch.sketch_id: sketch for sketch in original_saved}
    if (
        not prior
        or len(prior) != len(original_saved)
        or any(current_saved.get(identity) != sketch for identity, sketch in prior.items())
    ):
        raise ValidationError("已提交草图已变化，请重新开始混合变换。")
    if original_draft.sketch_id in prior or not steps:
        raise ValidationError("混合变换缺少有效的草稿或操作。")
    if cross_pairs_by_step and len(cross_pairs_by_step) != len(steps):
        raise ValidationError("混合变换与跨草图关系历史不一致。")
    if arrays_by_step and len(arrays_by_step) != len(steps):
        raise ValidationError("混合变换与关联阵列历史不一致。")
    if rectangle_transforms_by_step and len(rectangle_transforms_by_step) != len(steps):
        raise ValidationError("混合变换与矩形变换依据历史不一致。")
    prior[original_draft.sketch_id] = original_draft
    batches: list[list[dict[str, object]]] = []
    inferred_rebind_steps: list[bool] = []
    user_rebind_steps: list[bool] = []
    extended_rebind_steps: list[int] = []
    trimmed_circle_steps: list[bool] = []
    local_tangent_rebind_steps: list[bool] = []
    local_tangent_fragment_steps: list[bool] = []
    local_split_line_steps: list[bool] = []
    local_split_arc_steps: list[bool] = []
    changes: list[tuple[tuple[CrossSketchTangency, ...], tuple[str, ...]]] = []
    array_changes: list[tuple[AssociativeRectArray, ...]] = []
    erasure_changes: list[tuple[ArrayEntityRef, ...]] = []
    extra_erasure_steps: list[bool] = []
    erased_dimension_steps: list[bool] = []
    rectangle_tangency_steps: list[bool] = []
    local_tangency_steps: list[SketchConstraint | None] = []
    rectangle_transform_steps: list[
        tuple[
            tuple[RectangleTransformEvidence, ...],
            tuple[RectangleTransformEvidence, ...],
            tuple[RectangleTransformEvidence, ...],
        ]
    ] = []
    initial_ids = {entity.entity_id for entity in original_draft.entities}
    initial_arrays = (
        initial_associative_arrays
        if initial_associative_arrays is not None
        else tuple(
            array
            for array in (arrays_by_step[0] if arrays_by_step else ())
            if all(
                member.target.sketch_id == original_draft.sketch_id
                and member.target.entity_id in initial_ids
                for member in array.members
            )
            and all(
                output.target.sketch_id == original_draft.sketch_id
                and output.target.entity_id in initial_ids
                for output in array.extra_outputs
            )
        )
    )
    previous_arrays = {array.array_id: array for array in initial_arrays}
    tracked_arrays: tuple[AssociativeRectArray, ...] = (
        *services.kernel.associative_arrays,
        *initial_arrays,
    )
    initial_relations = _draft_cross_relations(original_saved, original_draft, initial_cross_pairs)
    existing_relations = services.kernel.cross_sketch_tangencies
    previous_committed = existing_relations
    previous_relations = {
        relation.relation_id: relation for relation in (*existing_relations, *initial_relations)
    }
    for index, (saved, draft) in enumerate(steps):
        transforms = rectangle_transforms_by_step[index] if rectangle_transforms_by_step else ()
        rectangle_proofs, polyline_proofs, line_proofs = split_transform_evidence(
            tuple(prior.values()), transforms
        )
        current_arrays = {
            array.array_id: array for array in (arrays_by_step[index] if arrays_by_step else ())
        }
        if len(current_arrays) != len(arrays_by_step[index] if arrays_by_step else ()):
            raise ValidationError("混合草稿中的关联阵列被移除或修改；请撤销后重试。")
        added_arrays = tuple(
            array for key, array in current_arrays.items() if key not in previous_arrays
        )
        after = {sketch.sketch_id: sketch for sketch in saved}
        if len(after) != len(saved) or set(after) != set(prior) - {original_draft.sketch_id}:
            raise ValidationError("混合变换的已提交草图集合发生变化。")
        if draft.sketch_id != original_draft.sketch_id:
            raise ValidationError("混合变换的草稿身份发生变化。")
        after[draft.sketch_id] = draft
        erased_members = tuple(
            member.target
            for array in tracked_arrays
            for member in array.members
            if member.erased_index is None
            and member.target.sketch_id in after
            and all(
                entity.entity_id != member.target.entity_id
                for entity in after[member.target.sketch_id].entities
            )
        )
        erased_outputs = tuple(
            output.target
            for array in tracked_arrays
            for output in array.extra_outputs
            if output.target.sketch_id in after
            and all(
                entity.entity_id != output.target.entity_id
                for entity in after[output.target.sketch_id].entities
            )
        )
        erased_members = (*erased_members, *erased_outputs)
        removes_member_dimension = False
        if erased_members:
            try:
                before_erasure = tuple(prior.values())
                stripped = strip_erased_member_dimensions(
                    before_erasure, tuple(after.values()), erased_members
                )
                removes_member_dimension = stripped != before_erasure
                _, tracked_arrays = erase_drawing_entities(stripped, tracked_arrays, erased_members)
            except (KeyError, ValueError) as exc:
                raise ValidationError(str(exc)) from exc
        expected_arrays = {array.array_id: array for array in tracked_arrays}
        if any(current_arrays.get(key) != expected_arrays.get(key) for key in previous_arrays):
            raise ValidationError("混合草稿中的关联阵列被移除或修改；请撤销后重试。")
        if current_arrays:
            try:
                states = tuple(after.values())
                propagate_array_changes(states, states, tuple(current_arrays.values()))
            except (KeyError, ValueError) as exc:
                raise ValidationError(f"混合草稿的关联阵列不一致：{exc}") from exc
        submitted = after
        if tracked_arrays and not erased_members and not added_arrays:
            targets = {
                (ref.sketch_id, ref.entity_id)
                for array in tracked_arrays
                for ref in (
                    *(member.target for member in array.members if member.erased_index is None),
                    *(output.target for output in array.extra_outputs),
                )
            }
            restored: dict[str, Sketch] = {}
            for identity, sketch in after.items():
                original_entities = {
                    entity.entity_id: entity for entity in prior[identity].entities
                }
                restored[identity] = replace(
                    sketch,
                    entities=tuple(
                        original_entities.get(entity.entity_id, entity)
                        if (identity, entity.entity_id) in targets
                        else entity
                        for entity in sketch.entities
                    ),
                )
            if restored != after:
                try:
                    propagated = propagate_array_changes(
                        tuple(prior.values()), tuple(restored.values()), tracked_arrays
                    )
                    if {sketch.sketch_id: sketch for sketch in propagated} == after:
                        submitted = restored
                except (KeyError, ValueError):
                    pass
        revisions: list[dict[str, object]] = []
        for identity, revised in submitted.items():
            before = prior[identity]
            if (before.frame, before.layers, before.support_face) != (
                revised.frame,
                revised.layers,
                revised.support_face,
            ):
                raise ValidationError("混合变换暂存期间不能改变草图坐标系或图层表。")
            if before == revised:
                continue
            data = revised.to_state_mapping()
            revisions.append(
                {
                    "sketch_id": identity,
                    "base_state_sha256": before.local_state_digest(),
                    "entities": data["entities"],
                    "constraints": data["constraints"],
                }
            )
        revised_ids = {cast("str", revision["sketch_id"]) for revision in revisions}
        for evidence in transforms:
            identity = evidence.reference.sketch_id
            if identity in revised_ids:
                continue
            unchanged = submitted[identity]
            state = unchanged.to_state_mapping()
            revisions.append(
                {
                    "sketch_id": identity,
                    "base_state_sha256": prior[identity].local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            )
            revised_ids.add(identity)
        surviving = {
            (sketch.sketch_id, entity.entity_id)
            for sketch in after.values()
            for entity in sketch.entities
        }
        surviving_committed = tuple(
            relation
            for relation in previous_committed
            if all(
                (ref.sketch_id, ref.entity_id) in surviving
                for ref in (relation.first, relation.second)
            )
        )
        try:
            previous_committed, extended_rebind = rebind_committed_tangencies_for_edit(
                tuple(prior.values()),
                tuple(after.values()),
                surviving_committed,
                rectangle_proofs,
                polyline_proofs,
                line_proofs,
            )
        except ValueError as exc:
            raise ValidationError(str(exc), command_id="drawing.sketch.revise") from exc
        current_relations = {relation.relation_id: relation for relation in previous_committed}
        rebound_draft_ids: set[str] = set()
        for relation in _draft_cross_relations(
            saved, draft, cross_pairs_by_step[index] if cross_pairs_by_step else ()
        ):
            if previous_relations:
                candidates = [
                    old
                    for old in previous_relations.values()
                    if old.first.sketch_id == relation.first.sketch_id
                    and old.second.sketch_id == relation.second.sketch_id
                    and (
                        old.first.entity_id == relation.first.entity_id
                        or old.second.entity_id == relation.second.entity_id
                    )
                    and old.relation_id not in rebound_draft_ids
                ]
                matches: list[tuple[CrossSketchTangency, int]] = []
                for old in candidates:
                    try:
                        rebindings, extended_pending = rebind_committed_tangencies_for_edit(
                            tuple(prior.values()),
                            tuple(after.values()),
                            (old,),
                            rectangle_proofs,
                            polyline_proofs,
                            line_proofs,
                        )
                        rebound = rebindings[0]
                    except ValueError:
                        continue
                    if replace(rebound, relation_id=relation.relation_id) == relation:
                        matches.append((old, extended_pending))
                if len(matches) > 1:
                    raise ValidationError("暂存相切关系身份不唯一，无法重绑定。")
                if matches:
                    old, extended_pending = matches[0]
                    extended_rebind = max(extended_rebind, extended_pending)
                    relation = replace(relation, relation_id=old.relation_id)
                    rebound_draft_ids.add(relation.relation_id)
            current_relations[relation.relation_id] = relation
        additions = tuple(
            relation
            for identity, relation in current_relations.items()
            if previous_relations.get(identity) != relation
        )
        removals = tuple(
            identity
            for identity, relation in previous_relations.items()
            if current_relations.get(identity) != relation
        )
        if not revisions and (additions or removals or added_arrays):
            state = draft.to_state_mapping()
            revisions.append(
                {
                    "sketch_id": draft.sketch_id,
                    "base_state_sha256": prior[draft.sketch_id].local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            )
        if revisions:
            batches.append(revisions)
            previous_constraint_ids = {
                item.constraint_id for item in prior[draft.sketch_id].constraints
            }
            new_local_tangencies = tuple(
                item
                for item in draft.constraints
                if item.constraint_id not in previous_constraint_ids
                and item.source == "user"
                and item.kind == "tangent"
            )
            if len(new_local_tangencies) > 1:
                raise ValidationError("一次暂存操作只能添加一个对象相切约束。")
            local_tangency_steps.append(new_local_tangencies[0] if new_local_tangencies else None)
            inferred_rebind_steps.append(
                any(
                    old.source == "inferred" and old.references != new.references
                    for identity in after
                    for old in prior[identity].constraints
                    for new in after[identity].constraints
                    if old.constraint_id == new.constraint_id
                )
            )
            user_rebind_steps.append(
                any(
                    old.source == "user" and old.references != new.references
                    for identity in after
                    for old in prior[identity].constraints
                    for new in after[identity].constraints
                    if old.constraint_id == new.constraint_id
                )
            )
            extended_rebind_steps.append(extended_rebind)
            local_tangent_rebind_steps.append(
                any(
                    old.constraint_id == new.constraint_id
                    and is_retained_local_tangent_rebind(old, new, prior[identity], after[identity])
                    for identity in after
                    for old in prior[identity].constraints
                    for new in after[identity].constraints
                )
            )
            local_tangent_fragment_steps.append(
                any(
                    old.constraint_id == new.constraint_id
                    and is_retained_local_tangent_rebind(old, new, prior[identity], after[identity])
                    and any(
                        a.entity_id != b.entity_id
                        for a, b in zip(old.references, new.references, strict=True)
                    )
                    for identity in after
                    for old in prior[identity].constraints
                    for new in after[identity].constraints
                )
            )
            local_split_line_steps.append(
                any(
                    old.constraint_id == new.constraint_id
                    and is_retained_local_tangent_rebind(
                        old, new, prior[identity], after[identity], allow_split_lines=True
                    )
                    and not is_retained_local_tangent_rebind(
                        old, new, prior[identity], after[identity]
                    )
                    for identity in after
                    for old in prior[identity].constraints
                    for new in after[identity].constraints
                )
            )
            local_split_arc_steps.append(
                any(
                    old.constraint_id == new.constraint_id
                    and is_retained_local_tangent_rebind(
                        old,
                        new,
                        prior[identity],
                        after[identity],
                        allow_split_lines=True,
                        allow_split_arcs=True,
                    )
                    and not is_retained_local_tangent_rebind(
                        old, new, prior[identity], after[identity], allow_split_lines=True
                    )
                    for identity in after
                    for old in prior[identity].constraints
                    for new in after[identity].constraints
                )
            )
            original_circles = {
                (identity, entity.entity_id)
                for identity, sketch in prior.items()
                for entity in sketch.entities
                if isinstance(entity, CircleEntity)
            }
            trimmed_circle_steps.append(
                any(
                    isinstance(entity, ArcEntity)
                    and (identity, entity.entity_id) in original_circles
                    for identity, sketch in after.items()
                    for entity in sketch.entities
                )
            )
            changes.append((additions, removals))
            array_changes.append(added_arrays)
            erasure_changes.append(erased_members)
            extra_erasure_steps.append(bool(erased_outputs))
            erased_dimension_steps.append(removes_member_dimension)
            rectangle_tangency_steps.append(
                any(has_rectangle_segment_tangency(sketch) for sketch in after.values())
                or relations_use_rectangle_segments(tuple(after.values()), additions)
            )
            rectangle_transform_steps.append((rectangle_proofs, polyline_proofs, line_proofs))
        previous_relations = current_relations
        previous_arrays = current_arrays
        tracked_arrays = (*tracked_arrays, *added_arrays)
        prior = after
    if not batches:
        raise ValidationError("混合变换没有产生修改。")
    if (
        initial_arrays
        or initial_relations
        or has_rectangle_segment_tangency(original_draft)
        or any(rectangle_tangency_steps)
        or any(additions or removals for additions, removals in changes)
        or any(array_changes)
        or any(erasure_changes)
        or any(any(group) for groups in rectangle_transform_steps for group in groups)
        or any(extended_rebind_steps)
        or any(trimmed_circle_steps)
        or any(local_tangent_rebind_steps)
        or any(local_split_line_steps)
        or any(local_split_arc_steps)
        or any(item is not None for item in local_tangency_steps)
    ):
        initial_params = original_draft.to_state_mapping()
        if initial_arrays:
            initial_params["associative_arrays"] = [array.to_mapping() for array in initial_arrays]
        if initial_relations:
            initial_params["cross_tangencies"] = [
                relation.to_mapping() for relation in initial_relations
            ]
        appends: list[ReplayAppend] = [
            ReplayAppend(
                "sketch.create",
                53
                if any(isinstance(entity, EllipseEntity) for entity in original_draft.entities)
                else 32
                if any(item.style_name is not None for item in original_draft.constraints)
                else 30
                if any(item.text_override is not None for item in original_draft.constraints)
                else 28
                if any(item.projection_axis is not None for item in original_draft.constraints)
                else 27
                if has_rectangle_segment_tangency(original_draft)
                or relations_use_rectangle_segments(
                    (*original_saved, original_draft), initial_relations
                )
                else 26
                if any(
                    output.rotation_deg != 0
                    for array in initial_arrays
                    for output in array.extra_outputs
                )
                else 25
                if any(
                    output.offset_mm != (0, 0)
                    for array in initial_arrays
                    for output in array.extra_outputs
                )
                else 24
                if any(array.extra_outputs for array in initial_arrays)
                else 23
                if any(has_shared_replacement_anchor(array) for array in initial_arrays)
                else 22
                if has_interleaved_array_dependencies(
                    (*services.kernel.associative_arrays, *initial_arrays)
                )
                else 21
                if any(has_internal_replacements(array) for array in initial_arrays)
                else 20
                if any(
                    member.replacement is not None
                    for array in initial_arrays
                    for member in array.members
                )
                else 19
                if any(
                    member.erased_neighbors is not None
                    for array in initial_arrays
                    for member in array.members
                )
                else 18
                if any(
                    member.erased_index is not None
                    for array in initial_arrays
                    for member in array.members
                )
                else 17
                if any(
                    member.rotation_deg != 0 for array in initial_arrays for member in array.members
                )
                else 16
                if any(
                    member.offset_mm != (0, 0)
                    for array in initial_arrays
                    for member in array.members
                )
                else 15
                if any(array.base_point is not None for array in initial_arrays)
                else 14
                if any(array.angle_deg != 0 for array in initial_arrays)
                else 13
                if any(c.first_endpoint or c.second_endpoint for c in original_draft.constraints)
                else 12
                if any(r.first_endpoint or r.second_endpoint for r in initial_relations)
                else 11
                if initial_arrays
                else 10
                if any(
                    ref.segment_index is not None
                    for relation in initial_relations
                    for ref in (relation.first, relation.second)
                )
                else 9
                if any(
                    constraint.kind in ("parallel", "perpendicular", "concentric", "equal", "fixed")
                    or (
                        constraint.source == "user"
                        and constraint.kind in ("horizontal", "vertical", "coincident", "tangent")
                    )
                    for constraint in original_draft.constraints
                )
                else 8
                if any(
                    isinstance(entity, PolylineEntity) and entity.bulges
                    for entity in original_draft.entities
                )
                else 7
                if initial_relations
                else 6
                if any(c.kind == "tangent" for c in original_draft.constraints)
                else 5
                if any(isinstance(e, PointEntity) for e in original_draft.entities)
                else 3,
                initial_params,
                "local",
            )
        ]
        version_arrays = (*services.kernel.associative_arrays, *initial_arrays)
        for (
            revisions,
            (
                additions,
                removals,
            ),
            added_arrays,
            inferred_rebind,
            user_rebind,
            extended_rebind,
            trimmed_circle,
            local_tangent_rebind,
            (local_tangent_fragment, local_split_line, local_split_arc),
            erased_members,
            erased_extra,
            erased_dimension,
            rectangle_tangency,
            local_tangency,
            transform_groups,
        ) in zip(
            batches,
            changes,
            array_changes,
            inferred_rebind_steps,
            user_rebind_steps,
            extended_rebind_steps,
            trimmed_circle_steps,
            local_tangent_rebind_steps,
            zip(
                local_tangent_fragment_steps,
                local_split_line_steps,
                local_split_arc_steps,
                strict=True,
            ),
            erasure_changes,
            extra_erasure_steps,
            erased_dimension_steps,
            rectangle_tangency_steps,
            local_tangency_steps,
            rectangle_transform_steps,
            strict=True,
        ):
            version_arrays = (*version_arrays, *added_arrays)
            rectangle_transforms, polyline_transforms, line_transforms = transform_groups
            params: dict[str, object] = {"revisions": revisions}
            if local_tangency is not None:
                if additions or removals or added_arrays or erased_members or any(transform_groups):
                    raise ValidationError("对象相切须作为独立的暂存操作。")
                params["dimension"] = {
                    "sketch_id": original_draft.sketch_id,
                    "constraint": local_tangency.to_mapping(),
                }
                params["solver_id"] = "planegcs"
                params["solver_version"] = importlib.metadata.version("planegcs")
            if additions:
                params["cross_tangencies"] = [item.to_mapping() for item in additions]
            if removals:
                params["remove_tangencies"] = list(removals)
            if added_arrays:
                params["associative_arrays"] = [array.to_mapping() for array in added_arrays]
            if erased_members:
                params["erase_array_members"] = [ref.to_mapping() for ref in erased_members]
            if rectangle_transforms:
                params["rectangle_transforms"] = [
                    item.to_mapping() for item in rectangle_transforms
                ]
            if polyline_transforms:
                params["polyline_transforms"] = [item.to_mapping() for item in polyline_transforms]
            if line_transforms:
                params["line_transforms"] = [item.to_mapping() for item in line_transforms]
            appends.append(
                ReplayAppend(
                    "drawing.sketch.revise",
                    56
                    if revisions_require_normal_side_preservation(services, revisions)
                    else 55
                    if revisions_include_ellipses(revisions)
                    else 53
                    if revisions_include_dimension_tolerances(revisions)
                    else 50
                    if revisions_include_dimension_styles(revisions)
                    else 48
                    if revisions_include_dimension_text(revisions)
                    else max(46, extended_rebind)
                    if local_split_arc
                    else max(45, extended_rebind)
                    if local_split_line
                    else max(42, extended_rebind)
                    if local_tangent_fragment
                    else max(41, extended_rebind)
                    if local_tangent_rebind
                    else max(39, extended_rebind)
                    if trimmed_circle
                    else 38
                    if local_tangency is not None
                    else extended_rebind
                    if extended_rebind
                    else 34
                    if line_transforms
                    else 33
                    if polyline_transforms
                    else 32
                    if user_rebind
                    else 31
                    if revisions_include_projection_axes(revisions)
                    else 30
                    if rectangle_transforms
                    and any(
                        item.reference.sketch_id == original_draft.sketch_id
                        for item in rectangle_transforms
                    )
                    else 29
                    if rectangle_transforms
                    else 27
                    if rectangle_tangency
                    else 26
                    if erased_dimension
                    else 25
                    if any(
                        output.rotation_deg != 0
                        for array in added_arrays
                        for output in array.extra_outputs
                    )
                    else 24
                    if any(
                        output.offset_mm != (0, 0)
                        for array in added_arrays
                        for output in array.extra_outputs
                    )
                    else 23
                    if erased_extra
                    else 22
                    if any(array.extra_outputs for array in added_arrays)
                    else 21
                    if any(has_shared_replacement_anchor(array) for array in added_arrays)
                    else 20
                    if erased_members
                    else 19
                    if added_arrays and has_interleaved_array_dependencies(version_arrays)
                    else 18
                    if any(has_internal_replacements(array) for array in added_arrays)
                    else 17
                    if any(
                        member.replacement is not None
                        for array in added_arrays
                        for member in array.members
                    )
                    else 16
                    if any(
                        member.erased_neighbors is not None
                        for array in added_arrays
                        for member in array.members
                    )
                    else 15
                    if any(
                        member.erased_index is not None
                        for array in added_arrays
                        for member in array.members
                    )
                    else 14
                    if any(
                        member.rotation_deg != 0
                        for array in added_arrays
                        for member in array.members
                    )
                    else 13
                    if any(
                        member.offset_mm != (0, 0)
                        for array in added_arrays
                        for member in array.members
                    )
                    else 12
                    if any(array.base_point is not None for array in added_arrays)
                    else 11
                    if any(array.angle_deg != 0 for array in added_arrays)
                    else 10
                    if inferred_rebind
                    else 8
                    if revisions_include_local_endpoint_constraints(revisions)
                    else 7
                    if any(r.first_endpoint or r.second_endpoint for r in additions)
                    else 6
                    if added_arrays
                    else 5
                    if any(
                        ref.segment_index is not None
                        for relation in additions
                        for ref in (relation.first, relation.second)
                    )
                    else 3
                    if revisions_include_curved_polylines(revisions)
                    else 2,
                    params,
                    "local",
                )
            )
        candidate = create_replay_candidate(services, loaded, session_identity=session_identity)
        candidate.stage(
            ReplayChangeSet(
                (),
                tuple(appends),
                False,
                target_archive_version=6 if loaded.document.archive_version < 6 else None,
                undo_appends_separately=True,
            ),
            current_session_identity=session_identity,
        )
        return candidate
    return stage_mixed_drawing_move(
        services,
        loaded,
        original_draft,
        batches[0],
        session_identity=session_identity,
        followup_steps=batches[1:],
        inferred_rebind_steps=inferred_rebind_steps,
        user_rebind_steps=user_rebind_steps,
    )


def build_app(discoverers: Sequence[PluginDiscoverer] | None = None) -> AppServices:
    """Assemble the application services (the layering exception in person).

    The eight built-in commands are registered by explicit Python calls —
    never via entry_points (that group is reserved for third-party
    plugins). ``discoverers`` selects the discovery source: ``None``
    builds the default entry-point discoverer (real third-party
    discovery), an explicit empty sequence disables discovery entirely,
    and any given discoverers are chained in order; the chained results
    go through the loader (per-entry conflict isolation) before the
    plugin manager is built.
    """
    discoverers = (EntryPointDiscoverer(),) if discoverers is None else tuple(discoverers)
    registry = CommandRegistry(schema_defs=COMMAND_SCHEMA_DEFS)
    for spec in BUILTIN_COMMAND_SPECS:
        registry.register(spec)
    kernel = BuildKernel()
    formats = FormatProviderRegistry([STEP_PROVIDER, STL_PROVIDER, DXF_PROVIDER])
    discovered: tuple[DiscoveredPlugin, ...] = ()
    for discoverer in discoverers:
        discovered += tuple(discoverer.discover())
    loaded = register_plugins(registry, formats, discovered)
    plugins = PluginManager(loaded)
    _configure_reference_loader(kernel, registry, plugins)
    return AppServices(registry=registry, kernel=kernel, formats=formats, plugins=plugins)


def handlers_for(services: AppServices) -> dict[tuple[str, int], CommandHandler]:
    """Public forwarding entry for ``_handler_map`` (phase-1 UI same-source consumption).

    The private bridge is consumed by the CLI via getattr (with an acknowledgment
    comment); the UI is prohibited from adding another granting comment, so this
    opens a public re-export — the assembly source of truth is still only this function.
    """
    return _handler_map(services.registry, services.plugins)


def archive_plugin_identities(
    services: AppServices,
) -> dict[tuple[str, int], dict[str, str]]:
    """Return package/API provenance for commands contributed by loaded plugins."""
    identities: dict[tuple[str, int], dict[str, str]] = {}
    for plugin in services.plugins.loaded():
        manifest = plugin.manifest
        if manifest is None:
            continue
        for contribution in plugin.commands:
            identities[(contribution.spec.id, contribution.spec.version)] = {
                "distribution": plugin.distribution_name or "unavailable",
                "plugin_id": manifest.id or "unavailable",
                "plugin_version": manifest.version or "unavailable",
                "api_version": manifest.api_version or "unavailable",
            }
    return identities


def _handler_map(
    registry: CommandRegistry, plugins: PluginManager
) -> dict[tuple[str, int], CommandHandler]:
    """Assemble the per-document handler map from the registry and plugins.

    Every registered builtin gets one ``BuiltinModelingHandler`` per
    command id (the T6 dispatch rule). Plugin contributions then
    overlay: a non-None ``handler_factory`` supplies the plugin's own
    handler, while a None factory falls back to a
    ``BuiltinModelingHandler`` — third-party-declared ordinary modeling
    commands execute through the builtin path.
    """
    handlers: dict[tuple[str, int], CommandHandler] = {
        (spec.id, spec.version): BuiltinModelingHandler(spec.id, spec.version)
        for spec in registry.all_specs()
    }
    for contribution in plugins.command_contributions():
        key = (contribution.spec.id, contribution.spec.version)
        if contribution.handler_factory is not None:
            handlers[key] = contribution.handler_factory()
        else:
            handlers[key] = BuiltinModelingHandler(*key)
    return handlers


def new_document(
    services: AppServices,
    *,
    confirmed_by: str | None = None,
    document_type: DocumentType = "part",
) -> LoadedDocument:
    """Build a fresh ``Document``/``CommandBus`` pair from shared services.

    The handler map is assembled here (not in ``build_app``) so plugin
    command contributions registered after startup are picked up by every
    new document. The shared kernel is reset exactly once, after the bus
    is assembled and before returning, so the new document starts from
    empty geometry without relying on caller discipline. ``confirmed_by``
    is a forward parameter: the phase-0 Document constructor takes no such
    argument (it rides on individual executed commands instead), so it is
    accepted and unused until a later phase wires it.
    """
    handlers = _handler_map(services.registry, services.plugins)
    document = Document(
        services.registry,
        archive_version=8 if document_type == "drawing2d" else 1,
        document_type=document_type,
        document_kind="drawing" if document_type == "drawing2d" else "part",
        drawing_fillet_baseline=0.0 if document_type == "drawing2d" else 1.0,
        drawing_chamfer_angle_baseline=0.0 if document_type == "drawing2d" else 45.0,
    )
    bus = CommandBus(document, services.registry, services.kernel, handlers)
    services.kernel.reset()
    if document_type == "drawing2d":
        services.kernel.set_drawing_fillet_baseline(document.drawing_fillet_baseline)
        services.kernel.set_drawing_chamfer_angle_baseline(document.drawing_chamfer_angle_baseline)
    return LoadedDocument(document=document, bus=bus)


def fork_app_services(services: AppServices) -> AppServices:
    """Share immutable registrations while isolating all mutable geometry."""
    kernel = BuildKernel()
    _configure_reference_loader(kernel, services.registry, services.plugins)
    return AppServices(services.registry, kernel, services.formats, services.plugins)


def _configure_reference_loader(
    kernel: BuildKernel,
    registry: CommandRegistry,
    plugins: PluginManager,
) -> None:
    def replay(archive: Mapping[str, object]) -> BuildKernel:
        candidate = BuildKernel()
        _configure_reference_loader(candidate, registry, plugins)
        load_document_payload(
            dict(archive),
            registry=registry,
            kernel=candidate,
            handlers=_handler_map(registry, plugins),
        )
        return candidate

    kernel.set_reference_loader(replay)


def reference_parameters(
    source: Document,
    *,
    object_id: str = "",
    path: str = "",
    reference_id: str | None = None,
) -> dict[str, object]:
    archive = document_payload(source)
    return {
        "reference_id": reference_id or uuid4().hex,
        "file_id": source.file_id,
        "kind": source.document_kind,
        "path": path,
        "object_id": object_id,
        "fingerprint": archive_fingerprint(archive),
        "archive": archive,
    }


def copy_app_document(
    services: AppServices, source: Document, *, source_bus: CommandBus | None = None
) -> tuple[AppServices, LoadedDocument]:
    """Prepare an identity-only replacement for the owning session entry.

    No geometry changes: the old editable entry is replaced only after the
    copy is written. It must not be added as a second entry sharing this kernel.
    """
    document = Document(
        services.registry,
        metadata=source.metadata_snapshot(),
        commands=source.commands,
        named_groups=source.named_groups,
        archive_version=max(4, source.archive_version),
        document_type=source.document_type,
        document_kind=source.document_kind,
        file_id=uuid4().hex,
        migration_origin=source.migration_origin,
        reference_locations=source.reference_locations,
        drawing_fillet_baseline=source.drawing_fillet_baseline,
        drawing_chamfer_angle_baseline=source.drawing_chamfer_angle_baseline,
    )
    bus = (
        source_bus.copy_for_document(document)
        if source_bus is not None
        else CommandBus(document, services.registry, services.kernel, handlers_for(services))
    )
    return services, LoadedDocument(document, bus)


@dataclass(frozen=True)
class SessionOpenResult:
    documents: tuple[tuple[AppServices, LoadedDocument], ...]
    migrated: bool
    reference_messages: tuple[str, ...] = ()


def _reference_content_fingerprint(archive: Mapping[str, object]) -> str:
    return archive_fingerprint(
        {k: v for k, v in archive.items() if k not in ("provenance", "reference_locations")}
    )


def reference_association_status(
    services: AppServices,
    loaded: LoadedDocument,
    path: Path | None,
    *,
    locations: Mapping[str, str] | None = None,
    live_documents: Mapping[str, Document] | None = None,
) -> tuple[str, ...]:
    """Inspect locators without adopting external geometry or changing history."""
    messages: list[str] = []
    for reference in services.kernel.document_references:
        locators = loaded.document.reference_locations if locations is None else locations
        locator = locators.get(reference.file_id, reference.path)
        source_path = Path(locator) if locator else None
        if source_path is not None and not source_path.is_absolute():
            source_path = path.parent / source_path if path is not None else None
        label = Path(locator).name if locator else reference.file_id[:8]
        if source_path is None:
            state = "尚未定位"
        else:
            try:
                root: object = json.loads(source_path.read_text(encoding="utf-8"))
                if not isinstance(root, dict):
                    state = "源文件无效"
                elif cast("dict[str, object]", root).get("file_id") != reference.file_id:
                    state = "身份不匹配"
                elif cast("dict[str, object]", root).get("document_kind") != reference.kind:
                    state = "种类不匹配"
                elif _reference_content_fingerprint(
                    cast("dict[str, object]", root)
                ) != _reference_content_fingerprint(reference.archive):
                    state = "来源文件已变更，尚未更新关联"
                else:
                    state = "关联有效"
            except FileNotFoundError:
                state = "来源文件缺失"
            except (OSError, ValueError):
                state = "来源无法读取"
        live = (live_documents or {}).get(reference.file_id)
        if live is not None and _reference_content_fingerprint(
            document_payload(live)
        ) != _reference_content_fingerprint(reference.archive):
            state += "；已打开的来源包含尚未采用的修改"
        messages.append(f"{label}：{state}；当前使用已保存的采用版本。")
    return tuple(messages)


def separate_internal_sketch(
    services: AppServices, sketch_id: str
) -> tuple[AppServices, LoadedDocument]:
    """Copy a confirmed internal sketch to an independent editable document."""
    linked_ids = {r.reference_id for r in services.kernel.document_references if r.kind == "sketch"}
    if sketch_id in linked_ids:
        raise ValidationError("请先解除来源关联，再分离为独立二维文档。")
    sketch = next((s for s in services.kernel.sketches if s.sketch_id == sketch_id), None)
    if sketch is None:
        raise ValidationError("找不到已完成的内部草图。")
    isolated = fork_app_services(services)
    loaded = new_workspace_document(isolated, kind="sketch")
    detached = replace(sketch, sketch_id=new_sketch_identity(), support_face=None)
    commit_new_sketch(isolated, loaded, detached, session_identity=0)
    return isolated, loaded


def open_session_bundle(services: AppServices, path: Path) -> SessionOpenResult:
    if path.suffix.lower() == ".masm":
        from mycad.core.exceptions import ValidationError

        raise ValidationError(".masm 装配文档尚未实现。")
    candidate_services = fork_app_services(services)
    original = open_app_document(candidate_services, path)
    if original.document.archive_version >= 4:
        from mycad.core.document_kinds import native_suffix
        from mycad.core.exceptions import ValidationError

        if path.suffix.lower() in (".my2d", ".my3d") and path.suffix.lower() != native_suffix(
            original.document.document_kind
        ):
            raise ValidationError("native suffix does not match document kind")
        return SessionOpenResult(
            ((candidate_services, original),),
            migrated=False,
            reference_messages=reference_association_status(candidate_services, original, path),
        )
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("archive must be an object")
    provenance = document_payload(
        new_workspace_document(fork_app_services(services), kind="part").document
    )["provenance"]
    candidates: list[tuple[AppServices, LoadedDocument]] = []
    for payload in migrate_archive(cast("dict[str, object]", raw), provenance):
        isolated = fork_app_services(services)
        loaded = load_document_payload(
            payload,
            registry=services.registry,
            kernel=isolated.kernel,
            handlers=handlers_for(isolated),
        )
        candidates.append((isolated, loaded))
    return SessionOpenResult(tuple(candidates), migrated=True)


def open_session_documents(
    services: AppServices, path: Path
) -> tuple[tuple[AppServices, LoadedDocument], ...]:
    return open_session_bundle(services, path).documents


def new_workspace_document(services: AppServices, *, kind: DocumentKind) -> LoadedDocument:
    document = Document(
        services.registry,
        archive_version=4 if kind == "part" else 8,
        document_kind=kind,
        document_type="part" if kind == "part" else "drawing2d",
        drawing_fillet_baseline=1.0 if kind == "part" else 0.0,
        drawing_chamfer_angle_baseline=45.0 if kind == "part" else 0.0,
    )
    bus = CommandBus(document, services.registry, services.kernel, handlers_for(services))
    services.kernel.reset()
    if kind != "part":
        services.kernel.set_drawing_fillet_baseline(document.drawing_fillet_baseline)
        services.kernel.set_drawing_chamfer_angle_baseline(document.drawing_chamfer_angle_baseline)
    return LoadedDocument(document, bus)


def open_app_document(services: AppServices, path: Path) -> LoadedDocument:
    """Open an archive with isolated replay, then commit its geometry once.

    ``core.persistence.open_document`` deliberately operates on the kernel it
    receives. Give it a fresh candidate so malformed or unreplayable archives
    cannot reset or partially overwrite the currently bound application
    kernel. Only after parsing, validation, and full replay succeed do we
    prepare the active bus and transfer the finished geometry into the stable
    service kernel.
    """
    if path.suffix.lower() == ".masm":
        raise ValidationError(".masm 装配文档尚未实现。")
    handlers = _handler_map(services.registry, services.plugins)
    candidate_kernel = BuildKernel()
    _configure_reference_loader(candidate_kernel, services.registry, services.plugins)
    candidate = _open_document(
        path,
        registry=services.registry,
        kernel=candidate_kernel,
        handlers=handlers,
    )
    if (
        candidate.document.archive_version >= 4
        and path.suffix.lower() in (".my2d", ".my3d")
        and path.suffix.lower() != native_suffix(candidate.document.document_kind)
    ):
        raise ValidationError("native suffix does not match document kind")
    active_bus = CommandBus(candidate.document, services.registry, services.kernel, handlers)
    services.kernel.replace_state_from(candidate_kernel)
    return LoadedDocument(document=candidate.document, bus=active_bus)


def interactive_selectors(
    services: AppServices,
    kind: str,
    topology_ids: Sequence[TopologyId],
) -> tuple[dict[str, object], ...]:
    """Translate runtime viewport picks into backend-neutral command locators."""

    if kind == "face":
        return tuple(
            services.kernel.interactive_face_selector(identity) for identity in topology_ids
        )
    if kind == "edge":
        return tuple(
            services.kernel.interactive_edge_selector(identity) for identity in topology_ids
        )
    raise ValueError(f"interactive modeling does not accept {kind!r} selections")


def interactive_body_selectors(
    services: AppServices, body_ids: Sequence[BodyId]
) -> tuple[dict[str, object], ...]:
    """Convert viewport body picks into replayable geometric selectors."""

    return tuple(services.kernel.interactive_body_selector(identity) for identity in body_ids)


def interactive_face_frame(services: AppServices, identity: TopologyId) -> PlanarFaceFrame:
    """Supply a neutral axis for the selected current face's pull handle."""
    return services.kernel.interactive_face_frame(identity)


def preview_command(
    services: AppServices,
    commands: Sequence[ExecutedCommand],
    command_id: str,
    params: Mapping[str, object],
    *,
    source_archive_version: int | None = None,
) -> ViewportData:
    """Return the solid snapshot of an isolated candidate command."""
    return preview_command_with_sketches(
        services, commands, command_id, params, source_archive_version=source_archive_version
    )[0]


def preview_command_with_sketches(
    services: AppServices,
    commands: Sequence[ExecutedCommand],
    command_id: str,
    params: Mapping[str, object],
    *,
    source_archive_version: int | None = None,
    source_document_type: DocumentType = "part",
    source_document_kind: DocumentKind | None = None,
    source_drawing_fillet_baseline: float = 1.0,
    source_drawing_chamfer_angle_baseline: float = 45.0,
    command_version: int | None = None,
    target_archive_version: int | None = None,
) -> tuple[ViewportData, tuple[ViewportSketchData, ...]]:
    """Replay a candidate command on an isolated document and kernel.

    The active application's kernel, Document, and CommandBus are never
    touched. The normal Bus pipeline validates parameters and calls only
    built-in handlers here; plugin handlers are excluded so a preview cannot
    run arbitrary extension code. All writes remain confined to the scratch
    document.
    """
    scratch_kernel = BuildKernel()
    _configure_reference_loader(scratch_kernel, services.registry, PluginManager(()))
    archive_version = max(
        5 if any(c.instance_id is not None for c in commands) else 1,
        max(
            (services.registry.get(c.id, c.version).min_archive_version for c in commands),
            default=1,
        ),
    )
    if source_archive_version is not None:
        if (
            type(source_archive_version) is not int
            or not archive_version <= source_archive_version <= 8
        ):
            raise ValidationError("preview source archive version is inconsistent")
        archive_version = source_archive_version
    scratch_document = Document(
        services.registry,
        commands=commands,
        archive_version=archive_version,
        document_type=source_document_type,
        document_kind=source_document_kind,
        drawing_fillet_baseline=source_drawing_fillet_baseline,
        drawing_chamfer_angle_baseline=source_drawing_chamfer_angle_baseline,
    )
    builtin_handlers = {
        (spec.id, spec.version): BuiltinModelingHandler(spec.id, spec.version)
        for spec in BUILTIN_COMMAND_SPECS
    }
    scratch_bus = CommandBus(
        scratch_document,
        services.registry,
        scratch_kernel,
        builtin_handlers,
    )
    for command in commands:
        if (command.id, command.version) not in builtin_handlers:
            raise ValueError(
                f"临时预览暂不支持重放非内置命令 {command.id!r}（历史序号 {command.ordinal}）"
            )
    rebuild = cast("Callable[[], None]", getattr(scratch_bus, "_rebuild"))  # noqa: B009
    rebuild()
    if target_archive_version is not None and target_archive_version > archive_version:
        if target_archive_version not in (6, 7, 8) or command_version is None:
            raise ValidationError(
                "preview upgrade requires an explicit command version and archive v6, v7 or v8"
            )
        candidate = create_replay_candidate(
            services, LoadedDocument(scratch_document, scratch_bus), session_identity=0
        )
        candidate.stage(
            ReplayChangeSet(
                (),
                (ReplayAppend(command_id, command_version, params, "preview"),),
                False,
                target_archive_version=target_archive_version,
            ),
            current_session_identity=0,
        )
        preview = candidate.preview(current_session_identity=0)
        if preview.state != "succeeded" or preview.viewport is None:
            raise ValidationError(
                str(preview.failure or "candidate command produced no viewport geometry")
            )
        return preview.viewport, preview.sketches
    scratch_bus.execute(command_id, params, confirmed_by="preview", version=command_version)
    snapshots = scratch_kernel.viewport_data()
    if not snapshots:
        raise ValueError("candidate command produced no viewport geometry")
    return snapshots[-1], scratch_kernel.sketch_display_data()


def create_drawing_worker() -> DrawingProjectionWorker:
    """Create an owned, explicitly closed background engineering projection service."""
    return DrawingProjectionWorker()
