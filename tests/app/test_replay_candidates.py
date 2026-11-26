# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Isolated candidate lifecycle tests at the app composition boundary."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from mycad import app
from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.core.bus import CommandBus
from mycad.core.document import Document, ExecutedCommand
from mycad.core.exceptions import TopologyReferenceError, ValidationError
from mycad.core.handlers import BuiltinModelingHandler, CommandHandler, HandlerContext
from mycad.core.persistence import LoadedDocument, document_payload, save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet, ReplayEdit


def _loaded() -> tuple[app.AppServices, LoadedDocument]:
    services = app.build_app(discoverers=[])
    return services, app.new_workspace_document(services, kind="part")


def _no_changes(*, upgrade_to_v5: bool = False) -> ReplayChangeSet:
    return ReplayChangeSet((), (), upgrade_to_v5)


def _redo(bus: CommandBus) -> list[ExecutedCommand]:
    return cast("list[ExecutedCommand]", getattr(bus, "_redo_stack"))  # noqa: B009


def _watch_source_events(loaded: LoadedDocument) -> list[Mapping[str, object]]:
    events: list[Mapping[str, object]] = []
    for name in ("pre_command", "post_command", "command_amended", "geometry_rebuilt"):
        loaded.document.events.subscribe(name, events.append)
    return events


def test_candidate_snap_anchors_are_isolated_and_expire_with_source() -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    source_anchors = services.kernel.snap_anchor_data()
    candidate = app.create_replay_candidate(services, loaded, session_identity=24)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("feature.box", 1, {"size_x": 30, "size_y": 20, "size_z": 4}, "local"),),
            False,
        ),
        current_session_identity=24,
    )
    preview = candidate.preview(current_session_identity=24)
    anchors = preview.snap_anchors
    assert max(a.point[0] for a in anchors) == pytest.approx(15)
    assert max(a.point[0] for a in source_anchors) == pytest.approx(5)
    scene = preview.scene
    assert scene is not None
    assert scene.viewport == preview.viewport
    assert scene.snap_anchors == preview.snap_anchors
    assert scene.document_id == loaded.document.document_id
    assert scene.candidate_id == preview.proposal.candidate_id
    assert scene.generation == preview.proposal.generation
    assert scene.matches(
        loaded.document.document_id,
        loaded.document.revision,
        24,
        scene.candidate_id,
        scene.generation,
    )
    assert not scene.matches(
        loaded.document.document_id, loaded.document.revision, 24, "another", scene.generation
    )
    assert not scene.matches(
        loaded.document.document_id,
        loaded.document.revision,
        24,
        scene.candidate_id,
        scene.generation + 1,
    )
    loaded.bus.execute("feature.box", {"size_x": 3, "size_y": 3, "size_z": 2})
    stale = candidate.preview(current_session_identity=24)
    assert stale.state == "stale"
    assert stale.snap_anchors == ()
    assert stale.scene is None


def test_staged_changes_are_detached_from_candidate() -> None:
    services, loaded = _loaded()
    candidate = app.create_replay_candidate(services, loaded, session_identity=9)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("feature.box", 1, {"size_x": 10, "size_y": 10, "size_z": 4}, "local"),),
            False,
        ),
        current_session_identity=9,
    )
    staged = candidate.staged_changes
    assert staged is not None
    cast("dict[str, object]", staged.appends[0].params)["size_x"] = 99
    assert candidate.staged_changes is not None
    assert candidate.staged_changes.appends[0].params["size_x"] == 10
    preview = candidate.preview(current_session_identity=9)
    assert preview.state == "succeeded"
    assert preview.proposal.commands[-1].params["size_x"] == 10
    candidate.cancel()
    assert candidate.staged_changes is None


def test_candidate_preview_reuses_staged_identity_and_cancel_preserves_v4_redo() -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    loaded.bus.execute("feature.cylinder", {"radius": 4, "height": 2})
    loaded.bus.undo()
    loaded.document.mark_clean()
    source_events = _watch_source_events(loaded)
    before_payload = document_payload(loaded.document)
    before_commands = loaded.document.commands
    before_redo = _redo(loaded.bus)
    before_dirty = loaded.document.is_dirty
    before_revision = loaded.document.revision
    before_viewport = services.kernel.viewport_data()
    before_volume = services.kernel.mass_properties().volume

    candidate = app.create_replay_candidate(services, loaded, session_identity=41)
    candidate.stage(_no_changes(upgrade_to_v5=True), current_session_identity=41)
    assert candidate.state == "ready"
    first = candidate.preview(current_session_identity=41)
    second = candidate.preview(current_session_identity=41)

    assert first.state == second.state == "succeeded"
    assert candidate.state == "succeeded"
    assert first.proposal.generation < second.proposal.generation
    assert first.proposal.digest == second.proposal.digest
    assert first.proposal.commands == second.proposal.commands
    assert first.proposal.commands[0].instance_id == second.proposal.commands[0].instance_id
    assert first.proposal.identity_upgrade is not None
    assert len(first.proposal.identity_upgrade.redo_ids) == len(before_redo)
    assert all(identity is not None for identity in first.proposal.identity_upgrade.redo_ids)
    assert before_redo[0].instance_id is None
    assert loaded.document.archive_version == 4
    assert loaded.document.commands == before_commands
    assert _redo(loaded.bus) == before_redo
    assert loaded.document.is_dirty is before_dirty
    assert loaded.document.revision == before_revision
    assert document_payload(loaded.document) == before_payload
    assert services.kernel.viewport_data() == before_viewport
    assert services.kernel.mass_properties().volume == pytest.approx(before_volume)
    assert source_events == []

    candidate.cancel()
    assert candidate.state == "cancelled"
    assert loaded.document.archive_version == 4
    assert loaded.document.commands == before_commands
    assert _redo(loaded.bus) == before_redo
    assert loaded.document.revision == before_revision
    assert source_events == []


def test_candidate_rejects_wrong_session_and_becomes_stale_after_source_change() -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    candidate = app.create_replay_candidate(services, loaded, session_identity=51)
    candidate.stage(_no_changes(), current_session_identity=51)

    with pytest.raises(ValidationError):
        candidate.preview(current_session_identity=52)
    assert candidate.state == "ready"

    loaded.bus.execute("feature.cylinder", {"radius": 2, "height": 3})
    stale = candidate.preview(current_session_identity=51)

    assert stale.state == "stale"
    assert stale.viewport is None
    assert candidate.state == "stale"
    assert len(loaded.document.commands) == 2


class _PluginHandler(CommandHandler):
    command_id = "plugin.test"

    def __init__(self) -> None:
        self.calls = 0

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> object | None:
        self.calls += 1
        return None


def test_candidate_rejects_plugin_history_before_running_its_handler() -> None:
    services, _empty = _loaded()
    spec = CommandSpec(
        id="plugin.test",
        version=1,
        summary_en="Plugin command",
        label_zh="插件命令",
        params_schema={"type": "object", "properties": {}, "additionalProperties": False},
        cli=CliSyntax(("plugin-test",)),
    )
    services.registry.register(spec)
    plugin_handler = _PluginHandler()
    document = Document(
        services.registry,
        commands=(
            ExecutedCommand(
                id=spec.id,
                version=spec.version,
                params={},
                ordinal=0,
                timestamp_utc="2026-11-02T00:00:00Z",
                confirmed_by="test",
            ),
        ),
        archive_version=4,
    )
    source_bus = CommandBus(
        document, services.registry, services.kernel, {("plugin.test", 1): plugin_handler}
    )
    loaded = LoadedDocument(document, source_bus)
    candidate = app.create_replay_candidate(services, loaded, session_identity=61)
    candidate.stage(_no_changes(), current_session_identity=61)

    preview = candidate.preview(current_session_identity=61)

    assert preview.state == "failed"
    assert preview.failure is not None
    assert preview.failure.command_id == "plugin.test"
    assert preview.failure.ordinal == 0
    assert preview.failure.last_successful_ordinal is None
    assert plugin_handler.calls == 0


def test_unsupported_command_failure_uses_actual_replayed_prefix_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, _empty = _loaded()
    plugin_spec = CommandSpec(
        id="plugin.test",
        version=1,
        summary_en="Plugin command",
        label_zh="插件命令",
        params_schema={"type": "object", "properties": {}, "additionalProperties": False},
        cli=CliSyntax(("plugin-test",)),
    )
    services.registry.register(plugin_spec)
    document = Document(
        services.registry,
        commands=(
            ExecutedCommand(
                id="feature.box",
                version=1,
                params={"size_x": 20, "size_y": 20, "size_z": 6},
                ordinal=0,
                timestamp_utc="2026-11-02T00:00:00Z",
                confirmed_by=None,
            ),
            ExecutedCommand(
                id="plugin.test",
                version=1,
                params={},
                ordinal=1,
                timestamp_utc="2026-11-02T00:00:00Z",
                confirmed_by=None,
            ),
        ),
        archive_version=4,
    )
    loaded = LoadedDocument(document, CommandBus(document, services.registry, services.kernel, {}))
    original_handler = BuiltinModelingHandler

    class _BrokenPrefixHandler:
        command_id = "feature.box"

        def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> object | None:
            raise RuntimeError("broken prefix")

    def candidate_handler(command_id: str, version: int = 1) -> CommandHandler:
        if command_id == "feature.box":
            return _BrokenPrefixHandler()
        return original_handler(command_id, version)

    monkeypatch.setattr(app, "BuiltinModelingHandler", candidate_handler)
    candidate = app.create_replay_candidate(services, loaded, session_identity=62)
    candidate.stage(_no_changes(), current_session_identity=62)

    preview = candidate.preview(current_session_identity=62)

    assert preview.state == "failed"
    assert preview.failure is not None
    assert preview.failure.command_id == "feature.box"
    assert preview.failure.ordinal == 0
    assert preview.failure.reason == "broken prefix"
    assert preview.failure.last_successful_ordinal is None
    assert preview.viewport is None


class _MutateThenFailHandler:
    command_id = "feature.cylinder"

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> None:
        ctx.kernel.apply(self.command_id, params)
        raise RuntimeError("fail after changing candidate geometry")


def test_unsupported_command_failure_rebuilds_prefix_before_mutating_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, _empty = _loaded()
    plugin_spec = CommandSpec(
        id="plugin.test",
        version=1,
        summary_en="Plugin command",
        label_zh="插件命令",
        params_schema={"type": "object", "properties": {}, "additionalProperties": False},
        cli=CliSyntax(("plugin-test",)),
    )
    services.registry.register(plugin_spec)
    document = Document(
        services.registry,
        commands=(
            ExecutedCommand(
                id="feature.box",
                version=1,
                params={"size_x": 20, "size_y": 20, "size_z": 6},
                ordinal=0,
                timestamp_utc="2026-11-02T00:00:00Z",
                confirmed_by=None,
            ),
            ExecutedCommand(
                id="feature.cylinder",
                version=1,
                params={"radius": 2, "height": 3},
                ordinal=1,
                timestamp_utc="2026-11-02T00:00:00Z",
                confirmed_by=None,
            ),
            ExecutedCommand(
                id="plugin.test",
                version=1,
                params={},
                ordinal=2,
                timestamp_utc="2026-11-02T00:00:00Z",
                confirmed_by=None,
            ),
        ),
        archive_version=4,
    )
    loaded = LoadedDocument(document, CommandBus(document, services.registry, services.kernel, {}))
    original_handler = BuiltinModelingHandler

    def candidate_handler(command_id: str, version: int = 1) -> CommandHandler:
        if command_id == "feature.cylinder":
            return _MutateThenFailHandler()
        return original_handler(command_id, version)

    monkeypatch.setattr(app, "BuiltinModelingHandler", candidate_handler)
    candidate = app.create_replay_candidate(services, loaded, session_identity=73)
    candidate.stage(_no_changes(), current_session_identity=73)

    preview = candidate.preview(current_session_identity=73)

    assert preview.state == "failed"
    assert preview.failure is not None
    assert preview.failure.command_id == "feature.cylinder"
    assert preview.failure.ordinal == 1
    assert preview.failure.last_successful_ordinal == 0
    assert preview.viewport is not None
    assert preview.viewport.state_id == "feature.box:0"


@pytest.mark.parametrize("message", ["", "   "])
def test_empty_exception_message_returns_failed_preview_and_preserves_source(
    monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    source = document_payload(loaded.document)
    source_revision = loaded.document.revision
    original_handler = BuiltinModelingHandler

    class _MessageFailureHandler:
        command_id = "feature.cylinder"

        def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> object | None:
            raise RuntimeError(message)

    def candidate_handler(command_id: str, version: int = 1) -> CommandHandler:
        if command_id == "feature.cylinder":
            return _MessageFailureHandler()
        return original_handler(command_id, version)

    monkeypatch.setattr(app, "BuiltinModelingHandler", candidate_handler)
    candidate = app.create_replay_candidate(services, loaded, session_identity=72)
    candidate.stage(
        ReplayChangeSet(
            (), (ReplayAppend("feature.cylinder", 1, {"radius": 2, "height": 3}, None),), False
        ),
        current_session_identity=72,
    )

    preview = candidate.preview(current_session_identity=72)

    assert preview.state == "failed"
    assert preview.failure is not None
    assert preview.failure.reason == "RuntimeError"
    assert candidate.state == "failed"
    assert document_payload(loaded.document) == source
    assert loaded.document.revision == source_revision


def test_failed_candidate_returns_prefix_rebuilt_without_partial_failure_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    source_viewport = services.kernel.viewport_data()
    source_volume = services.kernel.mass_properties().volume
    original_handler = BuiltinModelingHandler

    def candidate_handler(command_id: str, version: int = 1) -> CommandHandler:
        if command_id == "feature.cylinder":
            return _MutateThenFailHandler()
        return original_handler(command_id, version)

    monkeypatch.setattr(app, "BuiltinModelingHandler", candidate_handler)
    candidate = app.create_replay_candidate(services, loaded, session_identity=71)
    candidate.stage(
        ReplayChangeSet(
            (), (ReplayAppend("feature.cylinder", 1, {"radius": 2, "height": 3}, None),), True
        ),
        current_session_identity=71,
    )

    preview = candidate.preview(current_session_identity=71)

    assert preview.state == "failed"
    assert preview.failure is not None
    assert preview.failure.ordinal == 1
    assert preview.failure.last_successful_ordinal == 0
    assert preview.viewport is not None
    assert preview.viewport.state_id == "feature.box:0"
    assert preview.scene is None and preview.failure_scene is not None
    assert candidate.is_failure_scene_current(preview.failure_scene, current_session_identity=71)
    binding = candidate.interactive_failure_face_binding(
        preview.viewport.faces[0].topology_id,
        generation=preview.proposal.generation,
        current_session_identity=71,
    )
    assert binding["source_instance_id"] == preview.proposal.commands[0].instance_id
    with pytest.raises(TopologyReferenceError):
        candidate.interactive_failure_face_binding(
            source_viewport[-1].faces[0].topology_id,
            generation=preview.proposal.generation,
            current_session_identity=71,
        )
    with pytest.raises(ValidationError):
        candidate.authorize_commit(current_session_identity=71)
    assert services.kernel.viewport_data() == source_viewport
    assert services.kernel.mass_properties().volume == pytest.approx(source_volume)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    assert not candidate.is_failure_scene_current(
        preview.failure_scene, current_session_identity=71
    )
    with pytest.raises(ValidationError):
        candidate.interactive_failure_face_binding(
            preview.viewport.faces[0].topology_id,
            generation=preview.proposal.generation,
            current_session_identity=71,
        )


def test_candidate_pick_is_local_and_expires_when_generation_changes() -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    candidate = app.create_replay_candidate(services, loaded, session_identity=81)
    candidate.stage(_no_changes(upgrade_to_v5=True), current_session_identity=81)
    preview = candidate.preview(current_session_identity=81)
    assert preview.viewport is not None
    candidate_pick = preview.viewport.faces[0].topology_id
    source_pick = services.kernel.viewport_data()[-1].faces[0].topology_id

    with pytest.raises(TopologyReferenceError):
        candidate.interactive_face_binding(
            source_pick,
            generation=preview.proposal.generation,
            current_session_identity=81,
        )
    binding = candidate.interactive_face_binding(
        candidate_pick,
        generation=preview.proposal.generation,
        current_session_identity=81,
    )
    assert binding["kind"] == "bound_face"

    candidate.stage(
        ReplayChangeSet(
            (ReplayEdit(0, {"size_x": 12, "size_y": 20, "size_z": 6}, "alice", "resize"),),
            (),
            True,
        ),
        current_session_identity=81,
    )
    with pytest.raises(ValidationError):
        candidate.interactive_face_binding(
            candidate_pick,
            generation=preview.proposal.generation,
            current_session_identity=81,
        )


def test_invalid_stage_keeps_the_previous_succeeded_candidate_intact() -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    candidate = app.create_replay_candidate(services, loaded, session_identity=85)
    candidate.stage(_no_changes(upgrade_to_v5=True), current_session_identity=85)
    preview = candidate.preview(current_session_identity=85)
    assert preview.viewport is not None
    identity = preview.viewport.faces[0].topology_id
    previous_proposal = candidate.proposal
    invalid_changes = ReplayChangeSet(
        (
            ReplayEdit(0, {"size_x": 12, "size_y": 20, "size_z": 6}, "alice", "first"),
            ReplayEdit(0, {"size_x": 14, "size_y": 20, "size_z": 6}, "alice", "second"),
        ),
        (),
        True,
    )

    with pytest.raises(ValidationError):
        candidate.stage(invalid_changes, current_session_identity=85)

    assert candidate.state == "succeeded"
    assert candidate.proposal == previous_proposal
    assert (
        candidate.interactive_face_binding(
            identity,
            generation=preview.proposal.generation,
            current_session_identity=85,
        )["kind"]
        == "bound_face"
    )


def test_delayed_preview_result_does_not_replace_a_newer_staged_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    candidate = app.create_replay_candidate(services, loaded, session_identity=91)
    initial = ReplayChangeSet(
        (ReplayEdit(0, {"size_x": 11, "size_y": 10, "size_z": 4}, "alice", "first"),),
        (),
        False,
    )
    newer = ReplayChangeSet(
        (ReplayEdit(0, {"size_x": 12, "size_y": 10, "size_z": 4}, "alice", "second"),),
        (),
        False,
    )
    candidate.stage(initial, current_session_identity=91)
    replay = CommandBus.replay_for_candidate

    def stage_while_replay_finishes(bus: CommandBus) -> object | None:
        assert candidate.state == "previewing"
        result = replay(bus)
        candidate.stage(newer, current_session_identity=91)
        return result

    monkeypatch.setattr(CommandBus, "replay_for_candidate", stage_while_replay_finishes)

    delayed = candidate.preview(current_session_identity=91)

    assert delayed.state == "stale"
    assert candidate.state == "ready"
    assert candidate.proposal is not None
    assert candidate.proposal.digest != delayed.proposal.digest


def test_cancel_during_preview_invalidates_the_delayed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    candidate = app.create_replay_candidate(services, loaded, session_identity=95)
    candidate.stage(_no_changes(), current_session_identity=95)
    replay = CommandBus.replay_for_candidate

    def cancel_while_replay_finishes(bus: CommandBus) -> object | None:
        assert candidate.state == "previewing"
        result = replay(bus)
        candidate.cancel()
        return result

    monkeypatch.setattr(CommandBus, "replay_for_candidate", cancel_while_replay_finishes)

    delayed = candidate.preview(current_session_identity=95)

    assert delayed.state == "stale"
    assert candidate.state == "cancelled"
    assert candidate.proposal is None


def test_candidate_commit_requires_latest_success_and_current_session() -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    revision = loaded.document.revision
    candidate = app.create_replay_candidate(services, loaded, session_identity=101)
    candidate.stage(
        ReplayChangeSet(
            (ReplayEdit(0, {"size_x": 12, "size_y": 10, "size_z": 4}, "alice", "resize"),),
            (),
            False,
        ),
        current_session_identity=101,
    )

    with pytest.raises(ValidationError):
        candidate.authorize_commit(current_session_identity=101)
    preview = candidate.preview(current_session_identity=101)
    assert preview.state == "succeeded"
    with pytest.raises(ValidationError):
        candidate.authorize_commit(current_session_identity=102)

    first_grant = candidate.authorize_commit(current_session_identity=101)
    with pytest.raises(ValidationError):
        candidate.commit(first_grant, current_session_identity=102)
    second_preview = candidate.preview(current_session_identity=101)
    assert second_preview.state == "succeeded"
    with pytest.raises(ValidationError):
        candidate.commit(first_grant, current_session_identity=101)

    grant = candidate.authorize_commit(current_session_identity=101)
    candidate.commit(grant, current_session_identity=101)

    assert candidate.state == "committed"
    assert loaded.document.commands[0].params["size_x"] == 12
    assert len(loaded.document.commands[0].amendments) == 1
    assert loaded.document.revision == revision + 1
    with pytest.raises(ValidationError):
        candidate.cancel()


def test_composite_candidate_undo_keeps_upgraded_identities_and_audit() -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    candidate = app.create_replay_candidate(services, loaded, session_identity=105)
    candidate.stage(
        ReplayChangeSet(
            (ReplayEdit(0, {"size_x": 12, "size_y": 10, "size_z": 4}, "alice", "resize"),),
            (ReplayAppend("feature.cylinder", 1, {"radius": 2, "height": 3}, "alice"),),
            True,
        ),
        current_session_identity=105,
    )
    assert candidate.preview(current_session_identity=105).state == "succeeded"
    grant = candidate.authorize_commit(current_session_identity=105)
    candidate.commit(grant, current_session_identity=105)
    amended = loaded.document.commands
    identity = amended[0].instance_id
    assert identity is not None

    loaded.bus.undo_operation()

    assert loaded.document.archive_version >= 5
    assert len(loaded.document.commands) == 1
    assert loaded.document.commands[0].instance_id == identity
    assert loaded.document.commands[0].params["size_x"] == 10
    assert not loaded.document.commands[0].amendments
    loaded.bus.redo_operation()
    assert loaded.document.commands == amended


def test_saved_session_keeps_revision_undo_but_reopen_starts_from_saved_commands(
    tmp_path: Path,
) -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    loaded.bus.edit_and_replay(0, {"size_x": 12, "size_y": 10, "size_z": 4}, "alice", "resize")
    saved_commands = loaded.document.commands
    archive = tmp_path / "part.mc.json"
    save_document(loaded.document, archive)
    loaded.document.mark_clean()

    loaded.bus.undo_operation()
    assert loaded.document.commands[0].params["size_x"] == 10
    assert loaded.document.is_dirty
    loaded.bus.redo_operation()
    assert loaded.document.commands == saved_commands

    reopened = app.open_app_document(services, archive)
    assert reopened.document.commands == saved_commands
    reopened.bus.undo_operation()
    assert not reopened.document.commands


def test_candidate_commit_rejects_mutated_proposal_without_source_changes() -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    candidate = app.create_replay_candidate(services, loaded, session_identity=102)
    candidate.stage(
        ReplayChangeSet(
            (ReplayEdit(0, {"size_x": 12, "size_y": 10, "size_z": 4}, "alice", "resize"),),
            (),
            False,
        ),
        current_session_identity=102,
    )
    preview = candidate.preview(current_session_identity=102)
    assert preview.state == "succeeded"
    original_payload = document_payload(loaded.document)
    original_revision = loaded.document.revision
    assert candidate.proposal is not None
    candidate.proposal.commands[0].params["size_x"] = 99

    with pytest.raises(ValidationError):
        candidate.authorize_commit(current_session_identity=102)

    assert document_payload(loaded.document) == original_payload
    assert loaded.document.revision == original_revision


def test_candidate_authorization_rejects_a_stale_source_revision() -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    candidate = app.create_replay_candidate(services, loaded, session_identity=103)
    candidate.stage(_no_changes(), current_session_identity=103)
    assert candidate.preview(current_session_identity=103).state == "succeeded"
    grant = candidate.authorize_commit(current_session_identity=103)
    loaded.bus.execute("feature.cylinder", {"radius": 2, "height": 3})
    before = document_payload(loaded.document)
    revision = loaded.document.revision

    with pytest.raises(ValidationError):
        candidate.commit(grant, current_session_identity=103)

    assert candidate.state == "stale"
    assert document_payload(loaded.document) == before
    assert loaded.document.revision == revision


def test_candidate_bound_face_frame_uses_design_coordinates_and_expires() -> None:
    services, loaded = _loaded()
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    source_commands = loaded.document.commands
    candidate = app.create_replay_candidate(services, loaded, session_identity=94)
    candidate.stage(_no_changes(upgrade_to_v5=True), current_session_identity=94)
    preview = candidate.preview(current_session_identity=94)
    assert preview.viewport is not None
    face = preview.viewport.faces[0].topology_id
    binding = candidate.interactive_face_binding(
        face, generation=preview.proposal.generation, current_session_identity=94
    )
    frame = candidate.interactive_bound_face_frame(
        face, generation=preview.proposal.generation, current_session_identity=94
    )
    source_face = services.kernel.viewport_data()[-1].faces[0].topology_id
    with pytest.raises(TopologyReferenceError):
        candidate.interactive_bound_face_frame(
            source_face, generation=preview.proposal.generation, current_session_identity=94
        )
    normal_by_role = {
        "box.+X": (1.0, 0.0, 0.0),
        "box.-X": (-1.0, 0.0, 0.0),
        "box.+Y": (0.0, 1.0, 0.0),
        "box.-Y": (0.0, -1.0, 0.0),
        "box.+Z": (0.0, 0.0, 1.0),
        "box.-Z": (0.0, 0.0, -1.0),
    }
    assert frame.normal == pytest.approx(normal_by_role[str(binding["role"])])
    assert frame.local_to_world((0.0, 0.0)) == pytest.approx(frame.origin_mm)
    assert loaded.document.commands == source_commands
    candidate.stage(_no_changes(upgrade_to_v5=True), current_session_identity=94)
    with pytest.raises(ValidationError):
        candidate.interactive_bound_face_frame(
            face, generation=preview.proposal.generation, current_session_identity=94
        )


def test_candidate_cylinder_bound_frames_cover_only_planar_end_faces() -> None:
    from mycad.core.sketch import WorkPlaneFrame

    services, loaded = _loaded()
    loaded.bus.execute("feature.cylinder", {"radius": 10, "height": 6, "center": [4, 5, 2]})
    candidate = app.create_replay_candidate(services, loaded, session_identity=95)
    candidate.stage(_no_changes(upgrade_to_v5=True), current_session_identity=95)
    preview = candidate.preview(current_session_identity=95)
    assert preview.viewport is not None
    frames: dict[str, WorkPlaneFrame] = {}
    rejected = 0
    for face in preview.viewport.faces:
        try:
            binding = candidate.interactive_face_binding(
                face.topology_id,
                generation=preview.proposal.generation,
                current_session_identity=95,
            )
            frame = candidate.interactive_bound_face_frame(
                face.topology_id,
                generation=preview.proposal.generation,
                current_session_identity=95,
            )
        except TopologyReferenceError:
            rejected += 1
            continue
        frames[str(binding["role"])] = frame
    assert set(frames) == {"cylinder.top", "cylinder.bottom"}
    assert frames["cylinder.top"].origin_mm == pytest.approx((4, 5, 5))
    assert frames["cylinder.bottom"].origin_mm == pytest.approx((4, 5, -1))
    assert frames["cylinder.top"].normal == pytest.approx((0, 0, 1))
    assert frames["cylinder.bottom"].normal == pytest.approx((0, 0, -1))
    assert rejected > 0
    assert loaded.document.archive_version == 4
    candidate.cancel()
