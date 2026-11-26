# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A drawing composite is a single durable and atomic history step."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.bus import CommandBus
from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
from mycad.core.drawing_text import DrawingText
from mycad.core.exceptions import ValidationError
from mycad.core.handlers import HandlerContext
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame


@pytest.mark.parametrize(
    "command_id",
    (
        "drawing.group.create",
        "drawing.block.create",
        "drawing.block_instance.insert",
        "drawing.block_instance.explode",
        "drawing.objects.batch",
    ),
)
def test_missing_collection_command_is_reported_before_replay(
    tmp_path: Path, command_id: str
) -> None:
    from mycad.commands.registry import CommandRegistry
    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.exceptions import UnknownCommandError
    from mycad.core.persistence import open_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    text = DrawingText(uuid4().hex, "Text", (0, 0))
    if command_id == "drawing.group.create":
        loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
        group = DrawingGroup(uuid4().hex, (DrawingObjectRef("text", text.text_id),))
        loaded.bus.execute(command_id, group.to_mapping(), "local")
    elif command_id in {
        "drawing.block.create",
        "drawing.block_instance.insert",
        "drawing.block_instance.explode",
    }:
        definition = BlockDefinition(uuid4().hex, "Symbol", (), (text,))
        loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
        if command_id != "drawing.block.create":
            instance = BlockInstance(uuid4().hex, definition.definition_id, (1, 2))
            loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
            if command_id == "drawing.block_instance.explode":
                operation = prepare_block_explode(
                    app.drawing_collection_snapshot(services), instance.instance_id
                )
                loaded.bus.execute(
                    operation.command_id, operation.params, "local", version=operation.version
                )
    else:
        loaded.bus.execute(
            command_id,
            {"operations": [{"id": "drawing.text.add", "version": 1, "params": text.to_mapping()}]},
            "local",
        )
    path = tmp_path / "new-command.my2d"
    save_document(loaded.document, path)
    before = app.drawing_collection_snapshot(services)
    legacy = CommandRegistry(services.registry.schema_defs)
    for spec in services.registry.all_specs():
        if spec.id != command_id:
            legacy.register(spec)
    with pytest.raises(
        UnknownCommandError, match="ordinal.*" + command_id.replace(".", r"\.")
    ) as exc:
        open_document(
            path, registry=legacy, kernel=services.kernel, handlers=app.handlers_for(services)
        )
    assert exc.value.identifier == command_id
    assert app.drawing_collection_snapshot(services) == before


def test_grouped_sketch_replacement_remaps_removed_identity_and_reopens(tmp_path: Path) -> None:
    from mycad.core.drawing_transactions import prepare_grouped_sketch_replacements

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    old = LineEntity(uuid4().hex, (0, 0), (10, 0))
    other = LineEntity(uuid4().hex, (0, 2), (10, 2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (old, other))
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, sketch.sketch_id) for item in (old, other)
    )
    groups = (
        DrawingGroup(uuid4().hex, refs, name="one", selectable=False),
        DrawingGroup(uuid4().hex, (refs[0],), name="two", selectable=False),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local", version=3)
    for group in groups:
        loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    pieces = (
        LineEntity(uuid4().hex, (0, 0), (4, 0)),
        LineEntity(uuid4().hex, (6, 0), (10, 0)),
    )
    revised = replace(sketch, entities=pieces)
    piece_refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, sketch.sketch_id) for item in pieces
    )
    operation = prepare_grouped_sketch_replacements(
        (sketch,), (revised,), groups, {refs[0]: piece_refs, refs[1]: ()}
    )
    events: list[object] = []
    loaded.document.events.subscribe("post_command", events.append)
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    assert len(events) == 1 and "unmapped_group_members" not in cast("dict[str, object]", events[0])
    expected = tuple(replace(group, members=piece_refs) for group in groups)
    assert services.kernel.sketches == (revised,)
    assert services.kernel.drawing_groups == expected
    path = tmp_path / "replacement.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == (revised,)
    assert services.kernel.drawing_groups == expected
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == groups
    reopened.bus.redo_operation()
    assert services.kernel.sketches == (revised,) and services.kernel.drawing_groups == expected
    later = replace(revised, entities=(replace(pieces[0], end_mm=(3, 0)), pieces[1]))
    state = later.to_state_mapping()
    reopened.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": revised.sketch_id,
                    "base_state_sha256": revised.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=79,
    )
    assert services.kernel.sketches == (later,) and services.kernel.drawing_groups == expected


@pytest.mark.parametrize(
    "mode",
    [
        "direct",
        "single",
        "batch",
        "batch_renamed",
        "batch_renamed_after",
        "batch_mapped_after",
        "batch_removed_renamed_after",
    ],
)
def test_unmapped_group_replacement_emits_committed_warning_and_undoes(
    tmp_path: Path, mode: str
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    old = LineEntity(uuid4().hex, (0, 0), (4, 0))
    other = LineEntity(uuid4().hex, (0, 1), (4, 1))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (old, other))
    ref = DrawingObjectRef("geometry", old.entity_id, sketch.sketch_id)
    retained = DrawingObjectRef("geometry", other.entity_id, sketch.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref, retained), selectable=False)
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local", version=3)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    replacement = LineEntity(uuid4().hex, (0, 0), (2, 0))
    revised = replace(sketch, entities=(replacement, other))
    state = revised.to_mapping(version=3) if mode == "single" else revised.to_state_mapping()
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ]
    }
    events: list[dict[str, object]] = []

    def record(payload: object) -> None:
        events.append(dict(cast("dict[str, object]", payload)))

    loaded.document.events.subscribe("post_command", record)
    if mode not in {"direct", "single"}:
        invalid = {
            "operations": [
                {"id": "drawing.sketch.revise", "version": 79, "params": params},
                {"id": "drawing.group.remove", "version": 1, "params": {"group_id": uuid4().hex}},
            ]
        }
        with pytest.raises(ValidationError):
            loaded.bus.execute("drawing.objects.batch", invalid, "local")
    elif mode == "single":
        invalid_single = deepcopy(cast("list[dict[str, object]]", params["revisions"])[0])
        invalid_single["base_state_sha256"] = "0" * 64
        with pytest.raises(ValidationError):
            loaded.bus.execute("sketch.revise", invalid_single, "local", version=1)
    else:
        invalid = deepcopy(params)
        cast("list[dict[str, object]]", invalid["revisions"])[0]["base_state_sha256"] = "0" * 64
        with pytest.raises(ValidationError):
            loaded.bus.execute("drawing.sketch.revise", invalid, "local", version=79)
    assert not events and services.kernel.drawing_groups == (group,)
    if mode not in {"direct", "single"}:
        operations: list[dict[str, object]] = []
        if mode == "batch_renamed":
            operations.append(
                {
                    "id": "drawing.group.update",
                    "version": 1,
                    "params": replace(group, name="Renamed").to_mapping(),
                }
            )
        if mode == "batch_removed_renamed_after":
            operations.append(
                {
                    "id": "drawing.group.update",
                    "version": 1,
                    "params": replace(group, members=(retained,)).to_mapping(),
                }
            )
        operations.append({"id": "drawing.sketch.revise", "version": 79, "params": params})
        if mode in {"batch_renamed_after", "batch_removed_renamed_after"}:
            operations.append(
                {
                    "id": "drawing.group.update",
                    "version": 1,
                    "params": replace(group, members=(retained,), name="Renamed").to_mapping(),
                }
            )
        if mode == "batch_mapped_after":
            new_ref = DrawingObjectRef("geometry", replacement.entity_id, sketch.sketch_id)
            operations.append(
                {
                    "id": "drawing.group.update",
                    "version": 1,
                    "params": replace(group, members=(new_ref, retained)).to_mapping(),
                }
            )
        loaded.bus.execute(
            "drawing.objects.batch",
            {"operations": operations},
            "local",
        )
    elif mode == "single":
        loaded.bus.execute(
            "sketch.revise",
            cast("list[dict[str, object]]", params["revisions"])[0],
            "local",
            version=1,
        )
    else:
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=79)
    assert len(events) == 1
    if mode == "batch_mapped_after":
        assert "unmapped_group_members" not in events[0]
        expected_members = (
            DrawingObjectRef("geometry", replacement.entity_id, sketch.sketch_id),
            retained,
        )
    elif mode == "batch_removed_renamed_after":
        assert "unmapped_group_members" not in events[0]
        expected_members = (retained,)
    else:
        assert events[0]["unmapped_group_members"] == [ref.to_mapping()]
        expected_members = (retained,)
    assert services.kernel.drawing_groups == (
        replace(
            group,
            members=expected_members,
            name="Renamed"
            if mode in {"batch_renamed", "batch_renamed_after", "batch_removed_renamed_after"}
            else None,
        ),
    )
    path = tmp_path / "unmapped-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("merge", [False, True])
def test_replacement_into_existing_geometry_reports_missing_mapping(
    tmp_path: Path, merge: bool
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (2, 0), (4, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, sketch.sketch_id) for item in (first, second)
    )
    group = DrawingGroup(uuid4().hex, refs)
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local", version=3)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    survivor = replace(first, end_mm=(4, 0)) if merge else first
    revised = replace(sketch, entities=(survivor,))
    state = revised.to_state_mapping()
    events: list[dict[str, object]] = []

    def record(payload: object) -> None:
        events.append(dict(cast("dict[str, object]", payload)))

    loaded.document.events.subscribe("post_command", record)
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=79,
    )
    assert services.kernel.drawing_groups == (replace(group, members=(refs[0],)),)
    if merge:
        assert events[0]["unmapped_group_members"] == [refs[1].to_mapping()]
    else:
        assert "unmapped_group_members" not in events[0]
    path = tmp_path / "existing-geometry-replacement.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == (group,)
    reopened.bus.redo_operation()
    assert services.kernel.sketches == (revised,)


def test_unrelated_sketch_edit_does_not_report_deleted_member_as_replaced() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    removed = LineEntity(uuid4().hex, (0, 0), (2, 0))
    kept = LineEntity(uuid4().hex, (0, 1), (2, 1))
    other = LineEntity(uuid4().hex, (0, 2), (2, 2))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (removed, kept))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other,))
    group = DrawingGroup(
        uuid4().hex,
        tuple(
            DrawingObjectRef("geometry", item.entity_id, first.sketch_id)
            for item in (removed, kept)
        ),
    )
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local", version=3)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    revisions: list[dict[str, object]] = []
    for source, target in (
        (first, replace(first, entities=(kept,))),
        (second, replace(second, entities=(replace(other, end_mm=(3, 2)),))),
    ):
        state = target.to_state_mapping()
        revisions.append(
            {
                "sketch_id": source.sketch_id,
                "base_state_sha256": source.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        )
    events: list[dict[str, object]] = []

    def record(payload: object) -> None:
        events.append(dict(cast("dict[str, object]", payload)))

    loaded.document.events.subscribe("post_command", record)
    loaded.bus.execute("drawing.sketch.revise", {"revisions": revisions}, "local", version=79)
    assert "unmapped_group_members" not in events[0]
    assert services.kernel.drawing_groups == (replace(group, members=(group.members[1],)),)


@pytest.mark.parametrize("explicitly_remove_one", [False, True])
def test_ambiguous_batch_replacement_reports_each_removed_group_member(
    tmp_path: Path,
    explicitly_remove_one: bool,
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (4, 0))
    second = LineEntity(uuid4().hex, (0, 1), (4, 1))
    retained = LineEntity(uuid4().hex, (0, 2), (4, 2))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second, retained))
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, sketch.sketch_id)
        for item in (first, second, retained)
    )
    group = DrawingGroup(uuid4().hex, refs)
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local", version=3)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    replacement = LineEntity(uuid4().hex, (0, 0), (2, 0))
    revised = replace(sketch, entities=(replacement, retained))
    state = revised.to_state_mapping()
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ]
    }
    new_ref = DrawingObjectRef("geometry", replacement.entity_id, sketch.sketch_id)
    updated = replace(group, members=(new_ref, refs[2]))
    events: list[dict[str, object]] = []

    def record(payload: object) -> None:
        events.append(dict(cast("dict[str, object]", payload)))

    loaded.document.events.subscribe("post_command", record)
    operations: list[dict[str, object]] = []
    if explicitly_remove_one:
        operations.append(
            {
                "id": "drawing.group.update",
                "version": 1,
                "params": replace(group, members=(refs[0], refs[2])).to_mapping(),
            }
        )
    operations.extend(
        (
            {"id": "drawing.sketch.revise", "version": 79, "params": params},
            {"id": "drawing.group.update", "version": 1, "params": updated.to_mapping()},
        )
    )
    loaded.bus.execute("drawing.objects.batch", {"operations": operations}, "local")
    assert services.kernel.drawing_groups == (updated,)
    if explicitly_remove_one:
        assert "unmapped_group_members" not in events[0]
    else:
        assert events[0]["unmapped_group_members"] == [refs[0].to_mapping(), refs[1].to_mapping()]
    path = tmp_path / "ambiguous-replacement.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == (group,)
    reopened.bus.redo_operation()
    assert services.kernel.sketches == (revised,) and services.kernel.drawing_groups == (updated,)


@pytest.mark.parametrize("failure", ["none", "rebuild", "validate"])
@pytest.mark.parametrize("as_batch", [False, True])
def test_candidate_commit_reports_unmapped_group_replacement_only_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, as_batch: bool
) -> None:
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    old = LineEntity(uuid4().hex, (0, 0), (4, 0))
    other = LineEntity(uuid4().hex, (0, 1), (4, 1))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (old, other))
    old_ref = DrawingObjectRef("geometry", old.entity_id, sketch.sketch_id)
    other_ref = DrawingObjectRef("geometry", other.entity_id, sketch.sketch_id)
    group = DrawingGroup(uuid4().hex, (old_ref, other_ref), selectable=False)
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local", version=3)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    new = LineEntity(uuid4().hex, (0, 0), (2, 0))
    revised = replace(sketch, entities=(new, other)).to_state_mapping()
    operation = ReplayAppend(
        "drawing.sketch.revise",
        79,
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": revised["entities"],
                    "constraints": revised["constraints"],
                }
            ]
        },
        "local",
    )
    if as_batch:
        operation = ReplayAppend(
            "drawing.objects.batch",
            1,
            {
                "operations": [
                    {"id": operation.command_id, "version": 79, "params": operation.params}
                ]
            },
            "local",
        )
    events: list[object] = []
    order: list[str] = []

    def pre(_payload: object) -> None:
        order.append("pre")

    def post(payload: object) -> None:
        order.append("post")
        events.append(payload)

    def rebuilt(_payload: object) -> None:
        order.append("rebuilt")

    loaded.document.events.subscribe("pre_command", pre)
    loaded.document.events.subscribe("post_command", post)
    loaded.document.events.subscribe("geometry_rebuilt", rebuilt)
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(ReplayChangeSet((), (operation,), False), current_session_identity=1)
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    assert events == [] and order == [] and services.kernel.drawing_groups == (group,)
    grant = candidate.authorize_commit(current_session_identity=1)
    if failure == "rebuild":
        rebuild_attr = "_rebuild"
        original_rebuild = cast("Callable[..., object]", getattr(loaded.bus, rebuild_attr))
        attempts = 0

        def fail_once(**kwargs: object) -> object:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("simulated commit rebuild failure")
            return original_rebuild(**kwargs)

        monkeypatch.setattr(loaded.bus, "_rebuild", fail_once)
        with pytest.raises(RuntimeError, match="simulated commit rebuild failure"):
            candidate.commit(grant, current_session_identity=1)
        assert events == [] and order == ["rebuilt"] and loaded.bus.is_healthy
        assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == (group,)
        return
    if failure == "validate":
        from mycad.core import persistence
        from mycad.core.document import Document

        original_payload = persistence.document_payload
        calls = 0

        def fail_payload(document: object) -> object:
            nonlocal calls
            calls += 1
            if document is loaded.document:
                raise RuntimeError("simulated final validation failure")
            return original_payload(cast("Document", document))

        monkeypatch.setattr(persistence, "document_payload", fail_payload)
        with pytest.raises(RuntimeError, match="simulated final validation failure"):
            candidate.commit(grant, current_session_identity=1)
        assert calls >= 2
        assert events == [] and order == ["rebuilt"] and loaded.bus.is_healthy
        assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == (group,)
        return
    candidate.commit(grant, current_session_identity=1)
    assert len(events) == 1
    assert order == ["pre", "post", "rebuilt"]
    assert cast("dict[str, object]", events[0])["unmapped_group_members"] == [old_ref.to_mapping()]
    assert services.kernel.drawing_groups == (replace(group, members=(other_ref,)),)
    path = tmp_path / "candidate-unmapped.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("existing_identity", [False, True])
def test_candidate_reports_unmapped_group_created_in_earlier_staged_step(
    tmp_path: Path, existing_identity: bool
) -> None:
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    old = LineEntity(uuid4().hex, (0, 0), (4, 0))
    other = LineEntity(uuid4().hex, (0, 1), (4, 1))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (old, other))
    old_ref = DrawingObjectRef("geometry", old.entity_id, sketch.sketch_id)
    other_ref = DrawingObjectRef("geometry", other.entity_id, sketch.sketch_id)
    group = DrawingGroup(uuid4().hex, (old_ref, other_ref), selectable=False)
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local", version=3)
    new = (
        replace(other, end_mm=(6, 1))
        if existing_identity
        else LineEntity(uuid4().hex, (0, 0), (2, 0))
    )
    revised = replace(
        sketch, entities=(new,) if existing_identity else (new, other)
    ).to_state_mapping()
    steps = (
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"),
        ReplayAppend(
            "drawing.sketch.revise",
            79,
            {
                "revisions": [
                    {
                        "sketch_id": sketch.sketch_id,
                        "base_state_sha256": sketch.local_state_digest(),
                        "entities": revised["entities"],
                        "constraints": revised["constraints"],
                    }
                ]
            },
            "local",
        ),
        ReplayAppend(
            "drawing.group.update",
            1,
            replace(group, members=(other_ref,), description="updated").to_mapping(),
            "local",
        ),
    )
    events: list[object] = []
    loaded.document.events.subscribe("post_command", events.append)
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet((), steps, False, undo_appends_separately=True), current_session_identity=1
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded" and not events
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == ()
    assert len(loaded.document.commands) == 1
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert len(events) == 3
    assert "unmapped_group_members" not in cast("dict[str, object]", events[0])
    assert cast("dict[str, object]", events[1])["unmapped_group_members"] == [old_ref.to_mapping()]
    assert cast("dict[str, object]", events[1])["unmapped_group_memberships"] == [
        {"group_id": group.group_id, "member": old_ref.to_mapping()}
    ]
    assert cast("dict[str, object]", events[2])["transaction_unmapped_group_memberships"] == [
        {"group_id": group.group_id, "member": old_ref.to_mapping()}
    ]
    path = tmp_path / "candidate-staged-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (replace(group, members=(other_ref,)),)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == (group,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == ()


def test_partial_mapping_of_overlapping_groups_reports_unmapped_membership(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    old = LineEntity(uuid4().hex, (0, 0), (4, 0))
    other = LineEntity(uuid4().hex, (0, 1), (4, 1))
    replacement = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (old, other))
    old_ref, other_ref, new_ref = (
        DrawingObjectRef("geometry", item.entity_id, sketch.sketch_id)
        for item in (old, other, replacement)
    )
    first = DrawingGroup(uuid4().hex, (old_ref, other_ref), name="First", selectable=False)
    second = DrawingGroup(uuid4().hex, (old_ref, other_ref), name="Second", selectable=False)
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local", version=3)
    for group in (first, second):
        loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    intermediate = replace(sketch, entities=(old, other, replacement))
    final = replace(sketch, entities=(other, replacement))

    def revision(source: Sketch, target: Sketch) -> dict[str, object]:
        state = target.to_state_mapping()
        return {
            "revisions": [
                {
                    "sketch_id": source.sketch_id,
                    "base_state_sha256": source.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        }

    events: list[object] = []
    loaded.document.events.subscribe("post_command", events.append)
    loaded.bus.execute(
        "drawing.objects.batch",
        {
            "operations": [
                {
                    "id": "drawing.sketch.revise",
                    "version": 79,
                    "params": revision(sketch, intermediate),
                },
                {
                    "id": "drawing.group.update",
                    "version": 1,
                    "params": replace(first, members=(new_ref, other_ref)).to_mapping(),
                },
                {
                    "id": "drawing.sketch.revise",
                    "version": 79,
                    "params": revision(intermediate, final),
                },
            ]
        },
        "local",
    )
    assert len(events) == 1
    assert cast("dict[str, object]", events[0])["unmapped_group_members"] == [old_ref.to_mapping()]
    assert cast("dict[str, object]", events[0])["unmapped_group_memberships"] == [
        {"group_id": second.group_id, "member": old_ref.to_mapping()}
    ]
    assert services.kernel.drawing_groups == (
        replace(first, members=(new_ref, other_ref)),
        replace(second, members=(other_ref,)),
    )
    path = tmp_path / "partial-overlap.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_groups == (first, second)


def test_grouped_replacement_failure_rolls_back_intermediate_geometry_and_groups() -> None:
    from mycad.core.drawing_transactions import prepare_grouped_sketch_replacements

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    old = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (old,))
    ref = DrawingObjectRef("geometry", old.entity_id, sketch.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,), selectable=False)
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local", version=3)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    new = LineEntity(uuid4().hex, (0, 0), (4, 0))
    replacement = DrawingObjectRef("geometry", new.entity_id, sketch.sketch_id)
    operation = prepare_grouped_sketch_replacements(
        (sketch,), (replace(sketch, entities=(new,)),), (group,), {ref: (replacement,)}
    )
    actions = list(cast("list[dict[str, object]]", operation.params["operations"]))
    actions.insert(
        -1, {"id": "drawing.group.remove", "version": 1, "params": {"group_id": uuid4().hex}}
    )
    commands = loaded.document.commands
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.objects.batch", {"operations": actions}, "local")
    assert loaded.document.commands == commands
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == (group,)


def test_grouped_replacement_rejects_unknown_target_and_frame_change() -> None:
    from mycad.core.drawing_transactions import prepare_grouped_sketch_replacements

    old = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (old,))
    ref = DrawingObjectRef("geometry", old.entity_id, sketch.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    unknown = DrawingObjectRef("geometry", uuid4().hex, sketch.sketch_id)
    with pytest.raises(ValidationError, match="不存在"):
        prepare_grouped_sketch_replacements((sketch,), (sketch,), (group,), {ref: (unknown,)})
    moved_frame = replace(sketch.frame, origin_mm=(0, 0, 1))
    with pytest.raises(ValidationError, match="平面"):
        prepare_grouped_sketch_replacements(
            (sketch,), (replace(sketch, frame=moved_frame),), (group,), {ref: (ref,)}
        )


def test_v7_collection_batch_requires_candidate_upgrade_and_preserves_audit(tmp_path: Path) -> None:
    import json

    from mycad.core.document import Document
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet

    services = app.build_app(discoverers=[])
    old = Document(
        services.registry, archive_version=7, document_type="drawing2d", document_kind="sketch"
    )
    old_path = tmp_path / "old.my2d"
    save_document(old, old_path)
    old_payload = json.loads(old_path.read_text(encoding="utf-8"))
    loaded = app.open_app_document(services, old_path)
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local", version=3)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),)
    )
    definition = BlockDefinition(
        uuid4().hex, "Symbol", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    batch = {
        "operations": [
            {"id": "drawing.group.create", "version": 1, "params": group.to_mapping()},
            {"id": "drawing.block.create", "version": 1, "params": definition.to_mapping()},
            {"id": "drawing.block_instance.insert", "version": 1, "params": instance.to_mapping()},
        ]
    }
    before, history = app.drawing_collection_snapshot(services), tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="upgrade|升级"):
        loaded.bus.execute("drawing.objects.batch", batch, "local", version=1)
    assert loaded.document.archive_version == 7 and tuple(loaded.document.commands) == history
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("drawing.objects.batch", 1, batch, "local"),),
            False,
            target_archive_version=8,
        ),
        current_session_identity=1,
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded" and app.drawing_collection_snapshot(services) == before
    assert loaded.document.archive_version == 7 and tuple(loaded.document.commands) == history
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert loaded.document.archive_version == 8
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == (instance,)
    upgraded = tmp_path / "upgraded.my2d"
    save_document(loaded.document, upgraded)
    payload = json.loads(upgraded.read_text(encoding="utf-8"))
    assert set(payload) == set(old_payload)
    assert payload.get("named_groups") == old_payload.get("named_groups")
    entry = payload["commands"][-1]
    assert {"id", "version", "params", "ordinal", "timestamp_utc", "confirmed_by"}.issubset(entry)
    assert entry["id"] == "drawing.objects.batch" and entry["version"] == 1
    assert entry["confirmed_by"] == "local" and entry["params"] == batch
    reopened = app.open_app_document(services, upgraded)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert services.kernel.drawing_groups == (
        group,
    ) and services.kernel.drawing_block_instances == (instance,)


def test_batch_children_keep_versions_and_context_through_failure_and_replay(
    tmp_path: Path,
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    text = DrawingText(uuid4().hex, "A", (1, 2))
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("text", text.text_id),
        ),
    )
    operations = [
        {"id": "sketch.create", "version": 3, "params": sketch.to_mapping(version=3)},
        {"id": "drawing.text.add", "version": 1, "params": text.to_mapping()},
        {"id": "drawing.group.create", "version": 1, "params": group.to_mapping()},
    ]
    loaded.bus.execute("drawing.objects.batch", {"operations": operations}, "local", version=1)
    parent = loaded.document.commands[-1]
    expected = tuple((item["id"], item["version"]) for item in operations)
    contexts = services.kernel.execution_contexts
    assert tuple((item.command_id, item.command_version) for item in contexts) == expected
    assert all(item.instance_id == parent.instance_id for item in contexts)
    before = app.drawing_collection_snapshot(services)
    invalid_text = DrawingText(uuid4().hex, "B", (0, 0))
    invalid = [
        {"id": "drawing.text.add", "version": 1, "params": invalid_text.to_mapping()},
        {"id": "drawing.group.remove", "version": 1, "params": {"group_id": uuid4().hex}},
    ]
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.objects.batch", {"operations": invalid}, "local", version=1)
    assert app.drawing_collection_snapshot(services) == before
    assert services.kernel.execution_contexts == contexts
    assert len(loaded.document.commands) == 1
    revised = replace(sketch, entities=(replace(line, end_mm=(12, 0)),))
    state = revised.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=79,
    )
    after = app.drawing_collection_snapshot(services)
    assert after.groups == (group,) and after.sketches == (revised,)
    contexts = services.kernel.execution_contexts
    assert tuple((item.command_id, item.command_version) for item in contexts) == (
        *expected,
        ("drawing.sketch.revise", 79),
    )
    assert contexts[-1].instance_id == loaded.document.commands[-1].instance_id
    path = tmp_path / "batch-context.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert app.drawing_collection_snapshot(services) == after
    assert services.kernel.execution_contexts == contexts
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.undo_operation()
    assert not services.kernel.sketches and not services.kernel.drawing_groups
    reopened.bus.redo_operation()
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after
    assert services.kernel.execution_contexts == contexts


def test_batch_reopens_and_undoes_all_members_as_one(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    text = DrawingText(uuid4().hex, "A", (1, 2))
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("text", text.text_id),
        ),
    )
    operations = [
        {"id": "sketch.create", "version": 3, "params": sketch.to_mapping(version=3)},
        {"id": "drawing.text.add", "version": 1, "params": text.to_mapping()},
        {"id": "drawing.group.create", "version": 1, "params": group.to_mapping()},
    ]
    loaded.bus.execute("drawing.objects.batch", {"operations": operations}, "local")
    assert len(loaded.document.commands) == 1
    path = tmp_path / "batch.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_groups == (group,)
    reopened.bus.undo()
    assert services.kernel.sketches == ()
    assert services.kernel.drawing_texts == ()
    assert services.kernel.drawing_groups == ()
    reopened.bus.redo()
    assert services.kernel.drawing_groups == (group,)


def test_batch_text_styles_roll_back_and_reopen_with_text(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    original = services.kernel.drawing_text_styles
    styles = TextStyleTable((*original.styles, TextStyle("new", "New")), original.current_id)
    text = DrawingText(uuid4().hex, "A", (0, 0), style_id="new")
    operations = [
        {"id": "drawing.text_styles.set", "version": 1, "params": styles.to_mapping()},
        {"id": "drawing.text.add", "version": 1, "params": text.to_mapping()},
    ]
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.objects.batch",
            {
                "operations": [
                    *operations,
                    {
                        "id": "drawing.group.remove",
                        "version": 1,
                        "params": {"group_id": uuid4().hex},
                    },
                ]
            },
            "local",
        )
    assert services.kernel.drawing_text_styles == original
    assert services.kernel.drawing_texts == () and not loaded.document.commands
    loaded.bus.execute("drawing.objects.batch", {"operations": operations}, "local")
    path = tmp_path / "text-style-batch.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_text_styles == styles
    assert services.kernel.drawing_texts == (text,)
    reopened.bus.undo()
    assert services.kernel.drawing_text_styles == original
    assert services.kernel.drawing_texts == ()
    reopened.bus.redo()
    assert services.kernel.drawing_text_styles == styles
    assert services.kernel.drawing_texts == (text,)


def test_batch_rejects_nested_or_unknown_steps_without_partial_changes() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    text = DrawingText(uuid4().hex, "A", (0, 0))
    first = {"id": "drawing.text.add", "version": 1, "params": text.to_mapping()}
    bad_operations: tuple[dict[str, object], ...] = (
        {"id": "drawing.objects.batch", "version": 1, "params": {"operations": []}},
        {"id": "feature.box", "version": 1, "params": {}},
        {"id": "drawing.text.add", "version": 999, "params": text.to_mapping()},
    )
    for bad in bad_operations:
        with pytest.raises(ValidationError):
            loaded.bus.execute("drawing.objects.batch", {"operations": [first, bad]}, "local")
        assert services.kernel.drawing_texts == ()
        assert loaded.document.commands == ()


def test_batch_rejects_overridden_child_handler_before_calling_it() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    calls: list[str] = []

    class Override:
        command_id = "drawing.text.add"

        def handle(self, params: object, ctx: HandlerContext) -> None:
            calls.append(ctx.command_id)

    handlers = app.handlers_for(services)
    handlers[("drawing.text.add", 1)] = Override()
    bus = CommandBus(loaded.document, services.registry, services.kernel, handlers)
    text = DrawingText(uuid4().hex, "A", (0, 0))
    operation = {"id": "drawing.text.add", "version": 1, "params": text.to_mapping()}
    with pytest.raises(ValidationError, match="处理器"):
        bus.execute("drawing.objects.batch", {"operations": [operation]}, "local")
    assert calls == []
    assert loaded.document.commands == ()


def test_batch_then_sketch_revision_preserves_all_objects_after_reopen(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    text = DrawingText(uuid4().hex, "A", (1, 2))
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("text", text.text_id),
        ),
    )
    operations = [
        {"id": "sketch.create", "version": 3, "params": sketch.to_mapping(version=3)},
        {"id": "drawing.text.add", "version": 1, "params": text.to_mapping()},
        {"id": "drawing.group.create", "version": 1, "params": group.to_mapping()},
    ]
    loaded.bus.execute("drawing.objects.batch", {"operations": operations}, "local")
    moved = replace(sketch, entities=(replace(line, start_mm=(2, 0), end_mm=(12, 0)),))
    state = moved.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=52,
    )
    assert services.kernel.sketches == (moved,)
    assert services.kernel.drawing_texts == (text,)
    assert services.kernel.drawing_groups == (group,)
    path = tmp_path / "batch-then-revise.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == (moved,)
    assert services.kernel.drawing_groups == (group,)
    reopened.bus.undo()
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_texts == (text,)
    assert services.kernel.drawing_groups == (group,)


def test_explicit_local_tangent_removal_preserves_other_topology_and_replays(
    tmp_path: Path,
) -> None:
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circles = (
        CircleEntity(uuid4().hex, (-3, 2), 2),
        CircleEntity(uuid4().hex, (3, 2), 2),
    )
    relations = tuple(
        SketchConstraint(
            uuid4().hex,
            "tangent",
            (
                SketchGeometryReference(line.entity_id, "geometry"),
                SketchGeometryReference(circle.entity_id, "geometry"),
            ),
        )
        for circle in circles
    )
    original = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, *circles), relations)
    app.commit_new_sketch(services, loaded, original, session_identity=1)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, original.sketch_id),)
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    modified = replace(original, constraints=(relations[1],))
    data = modified.to_state_mapping()
    base_revision: dict[str, object] = {
        "sketch_id": original.sketch_id,
        "base_state_sha256": original.local_state_digest(),
        "entities": data["entities"],
        "constraints": data["constraints"],
    }
    before = tuple(loaded.document.commands)
    for removals in (
        [],
        [uuid4().hex],
        [relations[0].constraint_id] * 2,
        [relations[1].constraint_id],
    ):
        revision = {**base_revision, "removed_local_tangencies": removals}
        with pytest.raises(ValidationError):
            loaded.bus.execute(
                "drawing.sketch.revise", {"revisions": [revision]}, "local", version=80
            )
        assert tuple(loaded.document.commands) == before and services.kernel.sketches == (original,)
    revision = {**base_revision, "removed_local_tangencies": [relations[0].constraint_id]}
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", {"revisions": [revision]}, "local", version=79)
    loaded.bus.execute("drawing.sketch.revise", {"revisions": [revision]}, "local", version=80)
    assert services.kernel.sketches == (modified,) and services.kernel.drawing_groups == (group,)
    path = tmp_path / "explicit-tangent-removal.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == (modified,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (original,)
    reopened.bus.redo_operation()
    assert services.kernel.sketches == (modified,)


def test_group_delete_rejects_locked_implicit_tangent_constraint() -> None:
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Related"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2, layer_name="Related")
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(circle.entity_id, "geometry"),
            SketchGeometryReference(line.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle), (relation,), layers)
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    ref = DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    snapshot = app.drawing_collection_snapshot(services)
    blocked = replace(
        snapshot,
        layers=replace(
            layers,
            layers=tuple(
                replace(layer, locked=True) if layer.name == "Related" else layer
                for layer in layers.layers
            ),
        ),
    )
    with pytest.raises(ValidationError, match="锁定|隐藏"):
        prepare_collection_delete(blocked, (ref,))
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == (group,)


def test_tangent_removal_batch_survives_later_sketch_rebuild(tmp_path: Path) -> None:
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.geometric_tolerance_topology import new_curve_point_identities
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    curve_id = uuid4().hex
    curve = PolylineEntity(
        curve_id,
        ((0, 20), (2, 20), (2, 22)),
        point_ids=new_curve_point_identities(curve_id, "polyline", 3),
    )
    original = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle, curve), (relation,))
    other_line = LineEntity(uuid4().hex, (0, 10), (2, 10))
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other_line,))
    for sketch in (original, other):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, original.sketch_id),)
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    operation = prepare_collection_delete(
        app.drawing_collection_snapshot(services),
        (),
        extra_constraints=((original.sketch_id, relation.constraint_id),),
    )
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    without_relation = replace(original, constraints=())
    assert services.kernel.sketches == (without_relation, other)
    moved_other = replace(other, entities=(replace(other_line, end_mm=(4, 10)),))
    state = moved_other.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": other.sketch_id,
                    "base_state_sha256": other.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=79,
    )
    assert services.kernel.sketches == (without_relation, moved_other)
    assert services.kernel.drawing_groups == (group,)
    path = tmp_path / "tangent-removal-rebuild.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == (without_relation, moved_other)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (without_relation, other)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (original, other)
    reopened.bus.redo_operation()
    reopened.bus.redo_operation()
    assert services.kernel.sketches == (without_relation, moved_other)
    assert services.kernel.drawing_groups == (group,)


def test_v7_tangent_removal_requires_explicit_upgrade_candidate(tmp_path: Path) -> None:
    from mycad.core.document import Document
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.replay_proposal import ReplayChangeSet
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    old = Document(
        services.registry, archive_version=7, document_type="drawing2d", document_kind="sketch"
    )
    path = tmp_path / "old-tangent.my2d"
    save_document(old, path)
    loaded = app.open_app_document(services, path)
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle), (relation,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    assert loaded.document.archive_version == 7
    operation = prepare_collection_delete(
        app.drawing_collection_snapshot(services),
        (),
        extra_constraints=((sketch.sketch_id, relation.constraint_id),),
    )
    history = tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="upgrade|升级"):
        loaded.bus.execute(
            operation.command_id, operation.params, "local", version=operation.version
        )
    assert loaded.document.archive_version == 7 and tuple(loaded.document.commands) == history
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet((), (operation,), False, target_archive_version=8),
        current_session_identity=1,
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    assert loaded.document.archive_version == 7 and services.kernel.sketches == (sketch,)
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert loaded.document.archive_version == 8
    assert services.kernel.sketches == (replace(sketch, constraints=()),)
    upgraded = tmp_path / "upgraded-tangent.my2d"
    save_document(loaded.document, upgraded)
    reopened = app.open_app_document(services, upgraded)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)
    reopened.bus.redo_operation()
    assert services.kernel.sketches == (replace(sketch, constraints=()),)


def test_block_and_tangent_batch_failure_rolls_back_then_reopens(tmp_path: Path) -> None:
    from copy import deepcopy

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_transactions import prepare_collection_delete
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    tangent = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle), (tangent,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    definition = BlockDefinition(
        uuid4().hex, "Symbol", (LineEntity(uuid4().hex, (0, 0), (3, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 8))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    ref = DrawingObjectRef("block_instance", instance.instance_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    before, history = app.drawing_collection_snapshot(services), tuple(loaded.document.commands)
    operation = prepare_collection_delete(
        before, (ref,), extra_constraints=((sketch.sketch_id, tangent.constraint_id),)
    )
    steps = deepcopy(cast("list[dict[str, object]]", operation.params["operations"]))
    assert [item["id"] for item in steps] == [
        "drawing.block_instance.remove",
        "drawing.sketch.revise",
    ]
    params = cast("dict[str, object]", steps[1]["params"])
    revisions = cast("list[dict[str, object]]", params["revisions"])
    revisions[0]["removed_local_tangencies"] = [uuid4().hex]
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.objects.batch", {"operations": steps}, "local", version=1)
    assert app.drawing_collection_snapshot(services) == before
    assert tuple(loaded.document.commands) == history
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    after = app.drawing_collection_snapshot(services)
    assert after.groups == () and after.block_instances == ()
    assert after.block_definitions == (definition,) and after.sketches[0].constraints == ()
    path = tmp_path / "block-tangent-batch.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert app.drawing_collection_snapshot(services) == after
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_late_candidate_failure_restores_existing_undo_and_redo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (4, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local", version=3)
    member = DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id)
    existing = DrawingGroup(uuid4().hex, (member,), name="Original")
    loaded.bus.execute("drawing.group.create", existing.to_mapping(), "local")
    loaded.bus.undo_operation()
    before = loaded.document.commands
    revision = loaded.document.revision
    new_group = DrawingGroup(uuid4().hex, (member,), name="Candidate")
    steps = (
        ReplayAppend("drawing.group.create", 1, new_group.to_mapping(), "local"),
        ReplayAppend(
            "drawing.group.update",
            1,
            replace(new_group, description="changed").to_mapping(),
            "local",
        ),
    )
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet((), steps, False, undo_appends_separately=True), current_session_identity=1
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    grant = candidate.authorize_commit(current_session_identity=1)
    record = cast(
        "Callable[[object, object], None]", vars(type(loaded.bus))["_record_appended_operations"]
    )

    def fail_after_record(state: object) -> None:
        record(loaded.bus, state)
        raise RuntimeError("simulated late candidate history failure")

    monkeypatch.setattr(loaded.bus, "_record_appended_operations", fail_after_record)
    with pytest.raises(RuntimeError, match="late candidate history failure"):
        candidate.commit(grant, current_session_identity=1)
    assert loaded.document.commands == before and loaded.document.revision > revision
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == ()
    loaded.bus.redo_operation()
    assert services.kernel.drawing_groups == (existing,)
    loaded.bus.undo_operation()
    loaded.bus.undo_operation()
    assert services.kernel.sketches == () and services.kernel.drawing_groups == ()


def test_late_group_redo_failure_does_not_create_phantom_undo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (4, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local", version=3)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),), name="G"
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    archive = tmp_path / "late-redo.my2d"
    save_document(loaded.document, archive)
    reopened = app.open_app_document(services, archive)
    reopened.bus.undo()
    before = reopened.document.commands
    record = cast("Callable[[object, object], None]", vars(type(reopened.bus))["_record_operation"])

    def fail_after_record(state: object) -> None:
        record(reopened.bus, state)
        raise RuntimeError("simulated late redo failure")

    monkeypatch.setattr(reopened.bus, "_record_operation", fail_after_record)
    with pytest.raises(RuntimeError, match="late redo failure"):
        reopened.bus.redo_operation()
    assert reopened.document.commands == before
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == ()
    monkeypatch.undo()
    reopened.bus.redo_operation()
    assert services.kernel.drawing_groups == (group,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == () and services.kernel.sketches == (sketch,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == ()


def test_late_batch_failure_restores_objects_and_previous_redo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    original_text = DrawingText(uuid4().hex, "previous", (0, 0))
    loaded.bus.execute("drawing.text.add", original_text.to_mapping(), "local")
    loaded.bus.undo_operation()
    original = app.drawing_collection_snapshot(services)
    history = loaded.document.commands
    line = LineEntity(uuid4().hex, (0, 0), (4, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    text = DrawingText(uuid4().hex, "batch", (1, 2))
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("text", text.text_id),
        ),
    )
    operations = [
        {"id": "sketch.create", "version": 3, "params": sketch.to_mapping(version=3)},
        {"id": "drawing.text.add", "version": 1, "params": text.to_mapping()},
        {"id": "drawing.group.create", "version": 1, "params": group.to_mapping()},
    ]
    record = cast("Callable[[object, object], None]", vars(type(loaded.bus))["_record_operation"])

    def fail_after_record(state: object) -> None:
        record(loaded.bus, state)
        raise RuntimeError("simulated late batch failure")

    monkeypatch.setattr(loaded.bus, "_record_operation", fail_after_record)
    with pytest.raises(RuntimeError, match="late batch failure"):
        loaded.bus.execute("drawing.objects.batch", {"operations": operations}, "local")
    assert loaded.document.commands == history
    assert app.drawing_collection_snapshot(services) == original
    monkeypatch.undo()
    loaded.bus.redo_operation()
    assert services.kernel.drawing_texts == (original_text,)
    loaded.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == original
    loaded.bus.execute("drawing.objects.batch", {"operations": operations}, "local")
    complete = app.drawing_collection_snapshot(services)
    path = tmp_path / "late-batch.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == original
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == complete
