# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Contracts for isolated replay proposal values and canonical digests."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from importlib import import_module
from typing import Protocol, cast

import pytest

from mycad.commands.demo import demo_registry
from mycad.core.bus import CommandBus
from mycad.core.command_identity import IdentityUpgrade
from mycad.core.document import CommandAmendment, Document, ExecutedCommand
from mycad.core.exceptions import TopologyReferenceError, ValidationError
from mycad.core.handlers import BuiltinModelingHandler, CommandHandler, HandlerContext
from mycad.core.persistence import document_payload
from mycad.core.replay_proposal import (
    ReplayAppend,
    ReplayCandidateProposal,
    ReplayChangeSet,
    ReplayEdit,
    ReplayFailure,
    replay_digest,
)
from tests.core.test_persistence import FakeKernel


class _HasParams(Protocol):
    params: Mapping[str, object]


class _HasCommands(Protocol):
    commands: tuple[ExecutedCommand, ...]


class _ReplayProposalAPI(Protocol):
    replay_digest: Callable[[int, Sequence[ExecutedCommand]], str]
    ReplayEdit: Callable[..., object]
    ReplayAppend: Callable[..., object]
    ReplayCandidateProposal: Callable[..., object]


def _api() -> _ReplayProposalAPI:
    return cast("_ReplayProposalAPI", import_module("mycad.core.replay_proposal"))


def _constructor(name: str) -> Callable[..., object]:
    return cast("Callable[..., object]", getattr(_api(), name))


def _replay_digest(archive_version: int, commands: Sequence[ExecutedCommand]) -> str:
    return _api().replay_digest(archive_version, commands)


def _command(
    *,
    params: dict[str, object] | None = None,
    instance_id: str | None = None,
    amendments: tuple[CommandAmendment, ...] = (),
) -> ExecutedCommand:
    return ExecutedCommand(
        id="feature.box",
        version=1,
        params=params if params is not None else {"width": 20.0},
        ordinal=0,
        timestamp_utc="2026-11-02T00:00:00Z",
        confirmed_by="user",
        amendments=amendments,
        instance_id=instance_id,
    )


def _proposal_kwargs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "document_id": "document-a",
        "file_id": "file-a",
        "revision": 4,
        "session_identity": 3,
        "candidate_id": "candidate-a",
        "generation": 1,
        "archive_version": 4,
        "commands": (_command(),),
        "identity_upgrade": None,
        "digest": "0" * 64,
    }
    values.update(overrides)
    return values


def _make_bus(
    *,
    commands: tuple[ExecutedCommand, ...] = (),
    archive_version: int = 1,
    kernel: FakeKernel | None = None,
) -> tuple[Document, CommandBus, FakeKernel]:
    registry = demo_registry()
    document = Document(registry, commands=commands, archive_version=archive_version)
    active_kernel = kernel or FakeKernel()
    bus = CommandBus(
        document,
        registry,
        active_kernel,
        {
            "feature.box": BuiltinModelingHandler("feature.box"),
            "feature.cylinder": BuiltinModelingHandler("feature.cylinder"),
        },
    )
    return document, bus, active_kernel


def _redo_stack(bus: CommandBus) -> list[ExecutedCommand]:
    return cast("list[ExecutedCommand]", getattr(bus, "_redo_stack"))  # noqa: B009


def _mark_candidate_success(bus: CommandBus, proposal: object) -> None:
    assert isinstance(proposal, ReplayCandidateProposal)
    bus.record_replay_candidate_preview(proposal, succeeded=True)


def test_candidate_commit_rejects_changed_undo_boundaries() -> None:
    document, bus, _kernel = _make_bus()
    proposal = bus.prepare_replay_proposal(
        ReplayChangeSet(
            (),
            (ReplayAppend("feature.cylinder", 1, {"radius": 2, "height": 3}, "user"),),
            False,
        ),
        session_identity=1,
        candidate_id="candidate",
        generation=1,
    )
    bus.record_replay_candidate_preview(proposal, succeeded=True)
    grant = bus.authorize_replay_candidate(proposal)

    with pytest.raises(ValidationError):
        bus.commit_replay_candidate(replace(proposal, undo_appends_separately=True), grant)

    assert not document.commands


class _ContextRecordingHandler(CommandHandler):
    command_id = "feature.cylinder"

    def __init__(self) -> None:
        self.contexts: list[tuple[int, str | None]] = []

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> None:
        self.contexts.append((ctx.command_version, ctx.instance_id))


def test_replay_digest_is_canonical_and_covers_command_identity_and_amendments() -> None:
    first = _command(params={"height": 8.0, "nested": {"a": 1, "b": [2, 3]}})
    reordered = _command(params={"nested": {"b": [2, 3], "a": 1}, "height": 8.0})
    baseline = _replay_digest(4, (first,))
    assert baseline == _replay_digest(4, (reordered,))
    assert baseline != _replay_digest(4, (_command(params={"height": 9.0}),))
    assert baseline != _replay_digest(5, (first,))
    assert baseline != _replay_digest(4, (_command(params=first.params, instance_id="a" * 32),))

    amendment = CommandAmendment(
        at="2026-11-02T01:00:00Z",
        actor="user",
        from_params={"width": 10.0},
        reason="repair upstream feature",
    )
    amended = _command(params=first.params, amendments=(amendment,))
    assert baseline != _replay_digest(4, (amended,))


def test_replay_values_copy_nested_inputs_before_freezing() -> None:
    edit_params: dict[str, object] = {"profile": {"points": [1, 2]}}
    append_params: dict[str, object] = {"binding": {"instance_id": "abc"}}
    command_params: dict[str, object] = {"nested": {"values": [3, 4]}}
    edit = cast("_HasParams", _api().ReplayEdit(0, edit_params, "user", "fix sketch"))
    append = cast(
        "_HasParams",
        _api().ReplayAppend("feature.box", 1, append_params, "user"),
    )
    proposal = cast(
        "_HasCommands",
        _api().ReplayCandidateProposal(
            **_proposal_kwargs(commands=(_command(params=command_params),))
        ),
    )

    edit_profile = cast("dict[str, object]", edit_params["profile"])
    cast("list[int]", edit_profile["points"]).append(9)
    append_binding = cast("dict[str, object]", append_params["binding"])
    append_binding["instance_id"] = "changed"
    command_nested = cast("dict[str, object]", command_params["nested"])
    cast("list[int]", command_nested["values"]).append(5)

    frozen_edit_profile = cast("Mapping[str, object]", edit.params["profile"])
    frozen_append_binding = cast("Mapping[str, object]", append.params["binding"])
    frozen_command_nested = cast("Mapping[str, object]", proposal.commands[0].params["nested"])
    assert frozen_edit_profile["points"] == [1, 2]
    assert frozen_append_binding["instance_id"] == "abc"
    assert frozen_command_nested["values"] == [3, 4]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("revision", -1),
        ("revision", True),
        ("session_identity", -1),
        ("session_identity", False),
        ("generation", -1),
        ("generation", True),
    ],
)
def test_proposal_rejects_invalid_revision_session_or_generation(field: str, value: object) -> None:
    proposal_type = _constructor("ReplayCandidateProposal")
    with pytest.raises(ValidationError):
        proposal_type(**_proposal_kwargs(**{field: value}))


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), {1, 2}])
def test_replay_digest_rejects_values_outside_finite_json_data(bad_value: object) -> None:
    with pytest.raises(ValidationError):
        _replay_digest(4, (_command(params={"unsupported": bad_value}),))


def test_prepare_replay_proposal_normalizes_edits_and_appends_without_source_mutation() -> None:
    document, bus, kernel = _make_bus()
    bus.execute("feature.cylinder", {"radius": 4, "height": 6}, "original")
    original = document.commands[0]
    document.mark_clean()
    before = document_payload(document)
    revision = document.revision
    source_geometry = list(kernel.applied)
    changes = ReplayChangeSet(
        replacements=(ReplayEdit(0, {"radius": 5, "height": 6}, "alice", "resize"),),
        appends=(ReplayAppend("feature.cylinder", 1, {"radius": 2, "height": 3}, None),),
        upgrade_to_v5=False,
    )

    proposal = bus.prepare_replay_proposal(
        changes, session_identity=7, candidate_id="candidate-1", generation=1
    )

    edited, appended = proposal.commands
    assert edited.id == original.id
    assert edited.version == original.version
    assert edited.ordinal == original.ordinal
    assert edited.timestamp_utc == original.timestamp_utc
    assert edited.confirmed_by == original.confirmed_by
    assert edited.params == {
        "radius": 5,
        "height": 6,
        "center": [0.0, 0.0, 0.0],
        "mode": "new",
    }
    assert len(edited.amendments) == 1
    assert edited.amendments[0].from_params == original.params
    assert edited.amendments[0].actor == "alice"
    assert edited.amendments[0].reason == "resize"
    assert appended.params == {
        "radius": 2,
        "height": 3,
        "center": [0.0, 0.0, 0.0],
        "mode": "new",
    }
    assert appended.ordinal == 1
    assert appended.instance_id is None
    assert appended.confirmed_by is None
    assert appended.timestamp_utc
    assert proposal.digest == replay_digest(proposal.archive_version, proposal.commands)
    assert document_payload(document) == before
    assert document.revision == revision
    assert not document.is_dirty
    assert kernel.applied == source_geometry
    assert not _redo_stack(bus)


@pytest.mark.parametrize("ordinals", [(0, 0), (1,)])
def test_prepare_replay_proposal_rejects_duplicate_or_out_of_range_edits(
    ordinals: tuple[int, ...],
) -> None:
    document, bus, _kernel = _make_bus()
    bus.execute("feature.cylinder", {"radius": 4, "height": 6})
    before = document_payload(document)
    changes = ReplayChangeSet(
        replacements=tuple(
            ReplayEdit(ordinal, {"radius": 5, "height": 6}, "alice", "resize")
            for ordinal in ordinals
        ),
        appends=(),
        upgrade_to_v5=False,
    )

    with pytest.raises(ValidationError):
        bus.prepare_replay_proposal(
            changes, session_identity=7, candidate_id="candidate-1", generation=1
        )

    assert document_payload(document) == before


def test_candidate_upgrade_uses_exact_signed_active_and_redo_ids() -> None:
    document, bus, _kernel = _make_bus(archive_version=4)
    bus.execute("feature.cylinder", {"radius": 4, "height": 6})
    bus.execute("feature.cylinder", {"radius": 5, "height": 6})
    bus.undo()
    upgrade: IdentityUpgrade = bus.prepare_identity_upgrade()
    changes = ReplayChangeSet(
        replacements=(),
        appends=(ReplayAppend("feature.cylinder", 1, {"radius": 2, "height": 3}, None),),
        upgrade_to_v5=True,
    )

    proposal = bus.prepare_replay_proposal(
        changes, session_identity=11, candidate_id="candidate-v5", generation=2
    )
    proposal_again = bus.prepare_replay_proposal(
        changes, session_identity=11, candidate_id="candidate-v5", generation=3
    )

    assert proposal.identity_upgrade == upgrade
    assert proposal.identity_upgrade is not None
    assert proposal.identity_upgrade.active_ids == upgrade.active_ids
    assert proposal.identity_upgrade.redo_ids == upgrade.redo_ids
    assert proposal.commands[0].instance_id == upgrade.active_ids[0]
    assert proposal_again.identity_upgrade == upgrade
    assert proposal_again.commands[0].instance_id == upgrade.active_ids[0]
    assert proposal.commands[1].instance_id is not None
    assert len(proposal.commands[1].instance_id) == 32
    assert proposal.archive_version == 5
    assert document.archive_version == 4
    assert document.commands[0].instance_id is None
    assert _redo_stack(bus)[0].instance_id is None


def test_replay_for_candidate_returns_structured_failure_location_and_path() -> None:
    source_document, _source_bus, source_kernel = _make_bus()
    source_bus = _source_bus
    source_bus.execute("feature.cylinder", {"radius": 4, "height": 6})
    source_bus.execute("feature.cylinder", {"radius": 5, "height": 6})
    before = document_payload(source_document)
    source_revision = source_document.revision
    source_geometry = list(source_kernel.applied)

    def fail_second(_n: int, _command_id: str, params: dict[str, object]) -> Exception | None:
        if params.get("radius") == 5:
            return TopologyReferenceError(
                "wrong /text/path", reason="invalid-reference", parameter_path="radius"
            )
        return None

    candidate_kernel = FakeKernel()
    candidate_kernel.fail_when = fail_second
    candidate_document, candidate_bus, _ = _make_bus(
        commands=source_document.commands,
        archive_version=source_document.archive_version,
        kernel=candidate_kernel,
    )

    failure = candidate_bus.replay_for_candidate()

    assert isinstance(failure, ReplayFailure)
    assert failure.command_id == "feature.cylinder"
    assert failure.command_version == 1
    assert failure.instance_id is None
    assert failure.ordinal == 1
    assert failure.parameter_path == "radius"
    assert failure.reason == "invalid-reference"
    assert failure.last_successful_ordinal == 0
    assert candidate_document.commands == source_document.commands
    assert document_payload(source_document) == before
    assert source_document.revision == source_revision
    assert source_kernel.applied == source_geometry


@pytest.mark.parametrize("message", ["", "   "])
def test_replay_for_candidate_normalizes_empty_exception_reason(message: str) -> None:
    command = ExecutedCommand(
        id="feature.cylinder",
        version=1,
        params={"radius": 4, "height": 6},
        ordinal=0,
        timestamp_utc="2026-11-02T00:00:00Z",
        confirmed_by=None,
    )
    kernel = FakeKernel()
    kernel.fail_when = lambda _n, _command_id, _params: RuntimeError(message)
    _document, bus, _kernel = _make_bus(commands=(command,), kernel=kernel)

    failure = bus.replay_for_candidate()

    assert failure is not None
    assert failure.reason == "RuntimeError"
    assert failure.ordinal == 0
    assert failure.last_successful_ordinal is None


@pytest.mark.parametrize(("failed_ordinal", "failed_radius"), [(0, 2), (1, 3), (2, 4)])
def test_replay_candidate_failure_stops_at_each_history_position(
    failed_ordinal: int,
    failed_radius: int,
) -> None:
    source_document, source_bus, source_kernel = _make_bus()
    for radius in (2, 3, 4):
        source_bus.execute("feature.cylinder", {"radius": radius, "height": 6})
    source_payload = document_payload(source_document)
    source_geometry = list(source_kernel.applied)
    candidate_kernel = FakeKernel()

    def fail_at_target(_n: int, _command_id: str, params: dict[str, object]) -> Exception | None:
        if params.get("radius") == failed_radius:
            return TopologyReferenceError(
                "candidate geometry rejected",
                reason="injected-failure",
                parameter_path="radius",
            )
        return None

    candidate_kernel.fail_when = fail_at_target
    candidate_document, candidate_bus, _ = _make_bus(
        commands=source_document.commands,
        archive_version=source_document.archive_version,
        kernel=candidate_kernel,
    )

    failure = candidate_bus.replay_for_candidate()

    assert failure is not None
    assert failure.ordinal == failed_ordinal
    assert failure.last_successful_ordinal == (failed_ordinal - 1 if failed_ordinal else None)
    assert failure.parameter_path == "radius"
    assert len(candidate_kernel.applied) == failed_ordinal
    assert candidate_document.commands == source_document.commands
    assert document_payload(source_document) == source_payload
    assert source_kernel.applied == source_geometry


def test_replay_for_candidate_uses_recorded_version_and_instance_identity() -> None:
    registry = demo_registry()
    command = ExecutedCommand(
        id="feature.cylinder",
        version=1,
        params={"radius": 4, "height": 6},
        ordinal=0,
        timestamp_utc="2026-11-02T00:00:00Z",
        confirmed_by=None,
        instance_id="a" * 32,
    )
    document = Document(registry, commands=(command,), archive_version=5)
    kernel = FakeKernel()
    kernel.applied.append(("stale", {}))
    handler = _ContextRecordingHandler()
    bus = CommandBus(document, registry, kernel, {"feature.cylinder": handler})

    assert bus.replay_for_candidate() is None

    assert handler.contexts == [(1, "a" * 32)]
    assert kernel.applied == []


def test_replay_candidate_grant_rejects_tampering_and_is_consumed_once() -> None:
    document, bus, kernel = _make_bus()
    bus.execute("feature.cylinder", {"radius": 4, "height": 6}, "original")
    document.mark_clean()
    before = document_payload(document)
    revision = document.revision
    geometry = list(kernel.applied)
    proposal = bus.prepare_replay_proposal(
        ReplayChangeSet(
            (ReplayEdit(0, {"radius": 5, "height": 6}, "alice", "repair"),),
            (),
            False,
        ),
        session_identity=17,
        candidate_id="grant-candidate",
        generation=2,
    )
    with pytest.raises(ValidationError):
        bus.authorize_replay_candidate(proposal)
    _mark_candidate_success(bus, proposal)
    grant = bus.authorize_replay_candidate(proposal)
    tampered = (
        replace(proposal, document_id="other-document"),
        replace(proposal, file_id="other-file"),
        replace(proposal, revision=proposal.revision + 1),
        replace(proposal, session_identity=proposal.session_identity + 1),
        replace(proposal, generation=proposal.generation + 1),
        replace(proposal, digest="f" * 64),
        replace(proposal, identity_upgrade=IdentityUpgrade("x", 0, (), (), "bad")),
    )

    with pytest.raises(ValidationError):
        bus.commit_replay_candidate(proposal, replace(grant, signature="0" * 64))
    for changed in tampered:
        with pytest.raises(ValidationError):
            bus.commit_replay_candidate(changed, grant)
        assert document_payload(document) == before
        assert document.revision == revision
        assert kernel.applied == geometry

    bus.commit_replay_candidate(proposal, grant)
    committed = document.commands[0]
    assert committed.params["radius"] == 5
    assert committed.amendments[-1].actor == "alice"
    assert document.revision == revision + 1
    with pytest.raises(ValidationError):
        bus.commit_replay_candidate(proposal, grant)


def test_replay_candidate_commit_is_atomic_and_clears_redo_once() -> None:
    document, bus, kernel = _make_bus()
    bus.execute("feature.cylinder", {"radius": 4, "height": 6}, "original")
    bus.execute("feature.cylinder", {"radius": 2, "height": 3}, "original")
    bus.undo()
    document.mark_clean()
    revision = document.revision
    events: list[str] = []
    callbacks: list[Callable[[Mapping[str, object]], None]] = []
    for event_name in ("command_amended", "post_command", "geometry_rebuilt"):

        def callback(_payload: Mapping[str, object], *, name: str = event_name) -> None:
            events.append(name)

        callbacks.append(callback)
        document.events.subscribe(event_name, callback)
    proposal = bus.prepare_replay_proposal(
        ReplayChangeSet(
            (ReplayEdit(0, {"radius": 5, "height": 6}, "alice", "repair"),),
            (ReplayAppend("feature.cylinder", 1, {"radius": 3, "height": 4}, None),),
            False,
        ),
        session_identity=18,
        candidate_id="atomic-candidate",
        generation=1,
    )
    _mark_candidate_success(bus, proposal)
    grant = bus.authorize_replay_candidate(proposal)

    bus.commit_replay_candidate(proposal, grant)

    assert [command.id for command in document.commands] == [
        "feature.cylinder",
        "feature.cylinder",
    ]
    assert len(document.commands[0].amendments) == 1
    assert [event for event in events if event == "command_amended"] == ["command_amended"]
    assert [event for event in events if event == "post_command"] == ["post_command"]
    assert events.count("geometry_rebuilt") == 1
    assert document.revision == revision + 1
    assert document.is_dirty
    assert not _redo_stack(bus)
    assert kernel.applied[-1][0] == "feature.cylinder"


def test_identity_only_candidate_commit_preserves_upgraded_redo() -> None:
    document, bus, _kernel = _make_bus(archive_version=4)
    bus.execute("feature.cylinder", {"radius": 4, "height": 6})
    bus.execute("feature.cylinder", {"radius": 5, "height": 6})
    bus.undo()
    document.mark_clean()
    revision = document.revision
    before_redo = _redo_stack(bus)
    proposal = bus.prepare_replay_proposal(
        ReplayChangeSet((), (), True),
        session_identity=19,
        candidate_id="identity-candidate",
        generation=1,
    )
    _mark_candidate_success(bus, proposal)
    grant = bus.authorize_replay_candidate(proposal)

    bus.commit_replay_candidate(proposal, grant)

    assert document.archive_version == 5
    assert document.revision == revision + 1
    assert document.is_dirty
    identity_upgrade = proposal.identity_upgrade
    assert identity_upgrade is not None
    assert document.commands[0].instance_id == identity_upgrade.active_ids[0]
    assert len(_redo_stack(bus)) == len(before_redo)
    assert _redo_stack(bus)[0].instance_id == identity_upgrade.redo_ids[0]
    bus.redo()
    assert document.commands[1].instance_id == identity_upgrade.redo_ids[0]


def test_replay_candidate_commit_failure_restores_source_and_discards_events() -> None:
    kernel = FakeKernel()
    document, bus, _ = _make_bus(kernel=kernel)
    bus.execute("feature.cylinder", {"radius": 4, "height": 6}, "original")
    bus.execute("feature.cylinder", {"radius": 2, "height": 3}, "original")
    bus.undo()
    document.mark_clean()
    before = document_payload(document)
    revision = document.revision
    dirty = document.is_dirty
    redo = _redo_stack(bus)
    geometry = list(kernel.applied)
    events: list[str] = []
    callbacks: list[Callable[[Mapping[str, object]], None]] = []
    for event_name in ("command_amended", "post_command", "geometry_rebuilt"):

        def callback(_payload: Mapping[str, object], *, name: str = event_name) -> None:
            events.append(name)

        callbacks.append(callback)
        document.events.subscribe(event_name, callback)
    proposal = bus.prepare_replay_proposal(
        ReplayChangeSet(
            (ReplayEdit(0, {"radius": 5, "height": 6}, "alice", "repair"),),
            (ReplayAppend("feature.cylinder", 1, {"radius": 3, "height": 4}, None),),
            False,
        ),
        session_identity=20,
        candidate_id="rollback-candidate",
        generation=1,
    )
    _mark_candidate_success(bus, proposal)
    grant = bus.authorize_replay_candidate(proposal)
    failure_once = True

    def fail_new_radius(_n: int, _command_id: str, params: dict[str, object]) -> Exception | None:
        nonlocal failure_once
        if params.get("radius") == 5 and failure_once:
            failure_once = False
            return RuntimeError("injected commit rebuild failure")
        return None

    kernel.fail_when = fail_new_radius
    with pytest.raises(RuntimeError, match="injected commit rebuild failure"):
        bus.commit_replay_candidate(proposal, grant)

    assert document_payload(document) == before
    assert document.revision == revision
    assert document.is_dirty is dirty
    assert _redo_stack(bus) == redo
    assert kernel.applied == geometry
    assert "command_amended" not in events
    assert "post_command" not in events
    assert events == ["geometry_rebuilt"]


def test_failed_identity_upgrade_commit_restores_v4_active_and_redo_history() -> None:
    kernel = FakeKernel()
    document, bus, _kernel = _make_bus(archive_version=4, kernel=kernel)
    bus.execute("feature.cylinder", {"radius": 4, "height": 6}, "original")
    bus.execute("feature.cylinder", {"radius": 2, "height": 3}, "redo item")
    bus.undo()
    document.mark_clean()
    before = document_payload(document)
    before_revision = document.revision
    before_dirty = document.is_dirty
    before_geometry = list(kernel.applied)
    before_redo = tuple(_redo_stack(bus))
    proposal = bus.prepare_replay_proposal(
        ReplayChangeSet(
            (ReplayEdit(0, {"radius": 5, "height": 6}, "alice", "repair"),),
            (ReplayAppend("feature.cylinder", 1, {"radius": 3, "height": 4}, None),),
            True,
        ),
        session_identity=22,
        candidate_id="upgrade-rollback-candidate",
        generation=1,
    )
    _mark_candidate_success(bus, proposal)
    grant = bus.authorize_replay_candidate(proposal)
    failure_once = True

    def fail_new_radius(_n: int, _command_id: str, params: dict[str, object]) -> Exception | None:
        nonlocal failure_once
        if params.get("radius") == 5 and failure_once:
            failure_once = False
            return RuntimeError("injected upgraded commit failure")
        return None

    kernel.fail_when = fail_new_radius
    with pytest.raises(RuntimeError, match="injected upgraded commit failure"):
        bus.commit_replay_candidate(proposal, grant)

    assert document_payload(document) == before
    assert document.archive_version == 4
    assert document.revision == before_revision
    assert document.is_dirty is before_dirty
    assert document.commands[0].instance_id is None
    assert document.commands[0].amendments == ()
    assert tuple(_redo_stack(bus)) == before_redo
    assert _redo_stack(bus)[0].instance_id is None
    assert kernel.applied == before_geometry


def test_replay_candidate_grant_cannot_cross_to_another_bus() -> None:
    document, bus, _kernel = _make_bus()
    bus.execute("feature.cylinder", {"radius": 4, "height": 6})
    proposal = bus.prepare_replay_proposal(
        ReplayChangeSet(
            (ReplayEdit(0, {"radius": 5, "height": 6}, "alice", "repair"),),
            (),
            False,
        ),
        session_identity=21,
        candidate_id="cross-bus-candidate",
        generation=1,
    )
    _mark_candidate_success(bus, proposal)
    grant = bus.authorize_replay_candidate(proposal)

    other_document, other_bus, other_kernel = _make_bus(
        commands=document.commands,
        archive_version=document.archive_version,
    )
    other_proposal = other_bus.prepare_replay_proposal(
        ReplayChangeSet(
            (ReplayEdit(0, {"radius": 5, "height": 6}, "alice", "repair"),),
            (),
            False,
        ),
        session_identity=21,
        candidate_id="cross-bus-candidate",
        generation=1,
    )
    _mark_candidate_success(other_bus, other_proposal)
    before = document_payload(other_document)
    geometry = list(other_kernel.applied)

    with pytest.raises(ValidationError):
        other_bus.commit_replay_candidate(other_proposal, grant)

    assert document_payload(other_document) == before
    assert other_kernel.applied == geometry
