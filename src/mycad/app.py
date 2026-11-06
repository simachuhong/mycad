# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Composition root (T7c): the single place that knows every concrete type.

``build_app`` assembles the whole object graph — registry with the eight
built-in command specs, a geometry kernel, the format-provider registry and
the plugin manager. Desktop document sessions fork services so each editable
document owns its kernel; immutable registrations are shared.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast
from uuid import uuid4

from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
from mycad.commands.registry import CommandRegistry
from mycad.core.bus import CommandBus
from mycad.core.document import Document, ExecutedCommand
from mycad.core.document_kinds import DocumentKind, DocumentType, native_suffix
from mycad.core.document_migration import migrate_archive
from mycad.core.document_references import archive_fingerprint
from mycad.core.exceptions import ValidationError
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
from mycad.core.sketch import PointEntity, Sketch, WorkPlaneFrame, new_sketch_identity
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
from mycad.geom.drawing_worker import DrawingProjectionWorker
from mycad.geom.kernel import BuildKernel
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
            failure = bus.replay_for_candidate()
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

    def commit(self, grant: ReplayCommitGrant, *, current_session_identity: int) -> None:
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
        self._loaded.bus.commit_replay_candidate(proposal, grant)
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


def commit_new_sketch(
    services: AppServices,
    loaded: LoadedDocument,
    sketch: Sketch,
    *,
    session_identity: int,
    confirmed_by: str = "local",
) -> object:
    """Commit a sketch, replaying an archive upgrade only when points require it."""
    if not any(isinstance(entity, PointEntity) for entity in sketch.entities):
        return loaded.bus.execute("sketch.create", sketch.to_state_mapping(), confirmed_by)
    candidate = create_replay_candidate(services, loaded, session_identity=session_identity)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("sketch.create", 5, sketch.to_state_mapping(), confirmed_by),),
            False,
            target_archive_version=6 if loaded.document.archive_version < 6 else None,
        ),
        current_session_identity=session_identity,
    )
    preview = candidate.preview(current_session_identity=session_identity)
    if preview.state != "succeeded":
        raise ValidationError(preview.failure.reason if preview.failure else "草图预览失败。")
    grant = candidate.authorize_commit(current_session_identity=session_identity)
    return candidate.commit(grant, current_session_identity=session_identity)


def stage_mixed_drawing_move(
    services: AppServices,
    loaded: LoadedDocument,
    original_draft: Sketch,
    revisions: Sequence[Mapping[str, object]],
    *,
    session_identity: int,
    followup_steps: Sequence[Sequence[Mapping[str, object]]] = (),
) -> ReplayCandidateSession:
    """Stage draft creation followed by an atomic multi-sketch revision."""
    if loaded.document.document_type != "drawing2d":
        raise ValidationError("混合变换仅支持独立二维文档。")
    if (
        not revisions
        or sum(revision.get("sketch_id") == original_draft.sketch_id for revision in revisions) > 1
    ):
        raise ValidationError("混合变换必须包含修订，且草稿修订不能重复。")
    candidate = create_replay_candidate(services, loaded, session_identity=session_identity)
    candidate.stage(
        ReplayChangeSet(
            (),
            (
                ReplayAppend(
                    "sketch.create",
                    5
                    if any(isinstance(entity, PointEntity) for entity in original_draft.entities)
                    else 3,
                    original_draft.to_state_mapping(),
                    "local",
                ),
                ReplayAppend("drawing.sketch.revise", 1, {"revisions": list(revisions)}, "local"),
                *(
                    ReplayAppend("drawing.sketch.revise", 1, {"revisions": list(step)}, "local")
                    for step in followup_steps
                ),
            ),
            False,
            target_archive_version=6 if loaded.document.archive_version < 6 else None,
            undo_appends_separately=True,
        ),
        current_session_identity=session_identity,
    )
    return candidate


def stage_mixed_drawing_timeline(
    services: AppServices,
    loaded: LoadedDocument,
    original_draft: Sketch,
    original_saved: Sequence[Sketch],
    steps: Sequence[tuple[Sequence[Sketch], Sketch]],
    *,
    session_identity: int,
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
    prior[original_draft.sketch_id] = original_draft
    batches: list[list[dict[str, object]]] = []
    for saved, draft in steps:
        after = {sketch.sketch_id: sketch for sketch in saved}
        if len(after) != len(saved) or set(after) != set(prior) - {original_draft.sketch_id}:
            raise ValidationError("混合变换的已提交草图集合发生变化。")
        if draft.sketch_id != original_draft.sketch_id:
            raise ValidationError("混合变换的草稿身份发生变化。")
        after[draft.sketch_id] = draft
        revisions: list[dict[str, object]] = []
        for identity, revised in after.items():
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
        if revisions:
            batches.append(revisions)
        prior = after
    if not batches:
        raise ValidationError("混合变换没有产生修改。")
    if not any(item["sketch_id"] != original_draft.sketch_id for item in batches[0]):
        raise ValidationError("混合变换必须包含已提交图元。")
    return stage_mixed_drawing_move(
        services,
        loaded,
        original_draft,
        batches[0],
        session_identity=session_identity,
        followup_steps=batches[1:],
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
        archive_version=3 if document_type == "drawing2d" else 1,
        document_type=document_type,
    )
    bus = CommandBus(document, services.registry, services.kernel, handlers)
    services.kernel.reset()
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


def reference_association_status(
    services: AppServices,
    loaded: LoadedDocument,
    path: Path | None,
    *,
    locations: Mapping[str, str] | None = None,
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
                else:
                    state = "关联有效"
            except FileNotFoundError:
                state = "来源文件缺失"
            except (OSError, ValueError):
                state = "来源无法读取"
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
        archive_version=4,
        document_kind=kind,
        document_type="part" if kind == "part" else "drawing2d",
    )
    bus = CommandBus(document, services.registry, services.kernel, handlers_for(services))
    services.kernel.reset()
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
            or not archive_version <= source_archive_version <= 6
        ):
            raise ValidationError("preview source archive version is inconsistent")
        archive_version = source_archive_version
    scratch_document = Document(
        services.registry, commands=commands, archive_version=archive_version
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
    scratch_bus.execute(command_id, params, confirmed_by="preview")
    snapshots = scratch_kernel.viewport_data()
    if not snapshots:
        raise ValueError("candidate command produced no viewport geometry")
    return snapshots[-1], scratch_kernel.sketch_display_data()


def create_drawing_worker() -> DrawingProjectionWorker:
    """Create an owned, explicitly closed background engineering projection service."""
    return DrawingProjectionWorker()
