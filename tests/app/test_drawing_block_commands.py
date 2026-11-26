# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Persisted block definitions and instances use the normal command pipeline."""

from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest

from mycad import app
from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
from mycad.core.drawing_text import DrawingText
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame


def test_block_instances_share_definition_and_reopen_with_undo(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Fastener", (line,), ())
    first = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    second = BlockInstance(uuid4().hex, definition.definition_id, (20, 10), 90, 2)
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", first.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", second.to_mapping(), "local")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", first.instance_id),))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    updated = replace(definition, entities=(replace(line, end_mm=(4, 0)),))
    loaded.bus.execute("drawing.block.update", updated.to_mapping(), "local")
    assert services.kernel.drawing_block_definitions == (updated,)
    assert services.kernel.drawing_block_instances == (first, second)
    snapshot = app.drawing_collection_snapshot(services)
    assert snapshot.block_definitions == (updated,) and snapshot.block_instances == (first, second)
    path = tmp_path / "blocks.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.drawing_block_definitions == (updated,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == (first, second)
    reopened.bus.redo_operation()
    assert services.kernel.drawing_block_definitions == (updated,)


@pytest.mark.parametrize("kind", ["definition", "instance"])
def test_block_rejects_uuid_alias_without_rewriting_existing_identity(
    tmp_path: Path, kind: str
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition_id, instance_id = uuid4(), uuid4()
    definition = BlockDefinition(
        str(definition_id), "Block", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(str(instance_id), definition.definition_id, (1, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    before = tuple(loaded.document.commands)
    if kind == "definition":
        command = "drawing.block.create"
        params = replace(definition, definition_id=definition_id.hex, name="Other").to_mapping()
    else:
        command = "drawing.block_instance.insert"
        params = replace(instance, instance_id=instance_id.hex).to_mapping()
    with pytest.raises(ValidationError, match="identity"):
        loaded.bus.execute(command, params, "local")
    assert tuple(loaded.document.commands) == before
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == (instance,)
    assert services.kernel.drawing_groups == (group,)
    path = tmp_path / "block-identity.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == (instance,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == ()
    reopened.bus.redo_operation()
    assert services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("kind", ["geometry", "text"])
def test_block_update_rejects_duplicate_member_uuid_alias_atomically(kind: str) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    text = DrawingText(uuid4().hex, "A", (0, 1))
    definition = BlockDefinition(uuid4().hex, "Block", (line,), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (1, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    history = tuple(loaded.document.commands)
    params = definition.to_mapping()
    if kind == "geometry":
        members = cast("list[dict[str, object]]", params["entities"])
        alias = dict(members[0], entity_id=str(UUID(line.entity_id)))
    else:
        members = cast("list[dict[str, object]]", params["texts"])
        alias = dict(members[0], text_id=str(UUID(text.text_id)))
    members.append(alias)
    with pytest.raises(ValidationError, match="duplicate block"):
        loaded.bus.execute("drawing.block.update", params, "local")
    assert tuple(loaded.document.commands) == history
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == (instance,)


def test_block_commands_reject_conflicts_and_cleanup_group_members() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(
        uuid4().hex, "Block", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    history = tuple(loaded.document.commands)
    duplicate = replace(definition, definition_id=uuid4().hex, name="block")
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.block.create", duplicate.to_mapping(), "local")
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.block.remove", {"definition_id": definition.definition_id}, "local"
        )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.block_instance.update", {**instance.to_mapping(), "scale": 0}, "local"
        )
    assert tuple(loaded.document.commands) == history
    assert services.kernel.drawing_groups == (group,)
    loaded.bus.execute(
        "drawing.block_instance.remove", {"instance_id": instance.instance_id}, "local"
    )
    assert services.kernel.drawing_groups == () and services.kernel.drawing_block_definitions == (
        definition,
    )
    loaded.bus.undo_operation()
    assert services.kernel.drawing_groups == (
        group,
    ) and services.kernel.drawing_block_instances == (instance,)


def test_block_state_survives_optimized_sketch_rebuild() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 4))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    revised = replace(sketch, entities=(replace(line, start_mm=(1, 0), end_mm=(3, 0)),))
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
        version=52,
    )
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == (instance,)


@pytest.mark.parametrize("kind", ["part", "drawing"])
def test_block_commands_require_independent_sketch(kind: str) -> None:
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet

    services = app.build_app(discoverers=[])
    loaded = (
        app.new_document(services, document_type="part")
        if kind == "part"
        else app.new_workspace_document(services, kind="drawing")
    )
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ())
    with pytest.raises(ValidationError, match="二维块.*独立二维草图"):
        loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    try:
        with pytest.raises(ValidationError):
            candidate.stage(
                ReplayChangeSet(
                    (),
                    (ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local"),),
                    False,
                    target_archive_version=8,
                ),
                current_session_identity=1,
            )
    finally:
        candidate.cancel()


def test_block_batch_is_atomic_across_reopen_and_failure(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(
        uuid4().hex, "Atomic", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5))
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    operations = [
        {"id": "drawing.block.create", "version": 1, "params": definition.to_mapping()},
        {"id": "drawing.block_instance.insert", "version": 1, "params": instance.to_mapping()},
        {"id": "drawing.group.create", "version": 1, "params": group.to_mapping()},
    ]
    duplicate = replace(definition, definition_id=uuid4().hex)
    failing = [
        *operations,
        {"id": "drawing.block.create", "version": 1, "params": duplicate.to_mapping()},
    ]
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.objects.batch", {"operations": failing}, "local")
    assert loaded.document.commands == ()
    assert services.kernel.drawing_groups == ()
    assert services.kernel.drawing_block_definitions == ()
    assert services.kernel.drawing_block_instances == ()
    loaded.bus.execute("drawing.objects.batch", {"operations": operations}, "local")
    path = tmp_path / "block-batch.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == (instance,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == ()
    assert services.kernel.drawing_block_definitions == ()
    assert services.kernel.drawing_block_instances == ()
    reopened.bus.redo_operation()
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.drawing_block_instances == (instance,)


@pytest.mark.parametrize("commit", [False, True])
def test_block_commands_share_draft_timeline_and_cancel(tmp_path: Path, commit: bool) -> None:
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    definition = BlockDefinition(uuid4().hex, "Draft block", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5))
    session.stage(ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local"))
    session.stage(ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local"))
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    assert session.snapshot.groups == (group,) and session.snapshot.block_instances == (instance,)
    assert loaded.document.commands == () and services.kernel.drawing_block_definitions == ()
    session.undo()
    assert session.snapshot.groups == () and session.snapshot.block_instances == (instance,)
    session.undo()
    assert session.snapshot.block_instances == () and session.snapshot.block_definitions == (
        definition,
    )
    session.redo()
    session.redo()
    assert session.snapshot.groups == (group,) and session.snapshot.block_instances == (instance,)
    if not commit:
        session.cancel()
        assert loaded.document.commands == () and services.kernel.drawing_block_instances == ()
        return
    session.commit()
    path = tmp_path / "draft-block.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups == (group,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == () and services.kernel.drawing_block_instances == (
        instance,
    )
    reopened.bus.undo_operation()
    assert (
        services.kernel.drawing_block_instances == ()
        and services.kernel.drawing_block_definitions == (definition,)
    )
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == ()


def test_block_layers_and_styles_are_protected_and_locked_instances_reject_changes() -> None:
    from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Detail")).add(SketchLayer("Insert"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    styles = TextStyleTable((TextStyle(), TextStyle(style_id="custom", name="Custom")), "standard")
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local")
    text = DrawingText(uuid4().hex, "T", (1, 0), style_id="custom", layer_name="Detail")
    definition = BlockDefinition(
        uuid4().hex, "Layered", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), (text,)
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), layer_name="Insert")
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    history = tuple(loaded.document.commands)
    for name in ("Detail", "Insert"):
        with pytest.raises(ValidationError, match="块"):
            loaded.bus.execute(
                "drawing.layers.set",
                {"layers": layers.remove(name).to_mapping(), "dimension_layer": "DIM"},
                "local",
            )
    with pytest.raises(ValidationError, match="块"):
        loaded.bus.execute("drawing.text_styles.set", TextStyleTable().to_mapping(), "local")
    assert tuple(loaded.document.commands) == history
    locked = layers.replace(replace(layers.get("Insert"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    history = tuple(loaded.document.commands)
    for command, params in (
        ("drawing.block_instance.update", replace(instance, insertion_mm=(2, 0)).to_mapping()),
        ("drawing.block_instance.remove", {"instance_id": instance.instance_id}),
        ("drawing.block.update", replace(definition, name="Changed").to_mapping()),
    ):
        with pytest.raises(ValidationError, match="锁定"):
            loaded.bus.execute(command, params, "local")
    assert tuple(loaded.document.commands) == history
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == (instance,)


def test_unreferenced_block_resources_can_be_removed_atomically_and_reopened(
    tmp_path: Path,
) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    original_layers = services.kernel.drawing_layers
    layers = original_layers.add(SketchLayer("Detail")).add(SketchLayer("Insert"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    original_styles = services.kernel.drawing_text_styles
    styles = TextStyleTable(
        (*original_styles.styles, TextStyle(style_id="custom", name="Custom")),
        original_styles.current_id,
    )
    loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local")
    text = DrawingText(uuid4().hex, "T", (1, 0), style_id="custom", layer_name="Detail")
    definition = BlockDefinition(uuid4().hex, "ResourceBlock", (), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5), layer_name="Insert")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    history = tuple(loaded.document.commands)
    operations = [
        {
            "id": "drawing.block_instance.remove",
            "version": 1,
            "params": {"instance_id": instance.instance_id},
        },
        {
            "id": "drawing.block.remove",
            "version": 1,
            "params": {"definition_id": definition.definition_id},
        },
        {"id": "drawing.text_styles.set", "version": 1, "params": original_styles.to_mapping()},
        {
            "id": "drawing.layers.set",
            "version": 1,
            "params": {"layers": original_layers.to_mapping(), "dimension_layer": "DIM"},
        },
    ]
    with pytest.raises(ValidationError, match="块"):
        loaded.bus.execute(
            "drawing.objects.batch", {"operations": [operations[2], *operations[:2]]}, "local"
        )
    assert app.drawing_collection_snapshot(services) == before
    assert tuple(loaded.document.commands) == history
    loaded.bus.execute("drawing.objects.batch", {"operations": operations}, "local")
    after = app.drawing_collection_snapshot(services)
    assert not after.block_definitions and not after.block_instances and not after.groups
    assert after.layers == original_layers and after.text_styles == original_styles
    path = tmp_path / "resource-cleanup.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert app.drawing_collection_snapshot(services) == after
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


@pytest.mark.parametrize("restriction", ["locked", "hidden", "frozen"])
def test_group_operations_reject_restricted_block_member_layer_atomically(
    tmp_path: Path, restriction: str
) -> None:
    from mycad.core.drawing_transactions import (
        prepare_collection_copy,
        prepare_collection_delete,
        prepare_collection_rotation,
        prepare_collection_scale,
        prepare_collection_translation,
    )
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Member"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    inner = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="Member")
    definition = BlockDefinition(uuid4().hex, "LayeredMember", (inner,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    text = DrawingText(uuid4().hex, "Label", (8, 8))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    ref = DrawingObjectRef("text", text.text_id)
    group = DrawingGroup(
        uuid4().hex, (ref, DrawingObjectRef("block_instance", instance.instance_id))
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    member = layers.get("Member")
    restricted = layers.replace(
        replace(member, **({"visible": False} if restriction == "hidden" else {restriction: True}))
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": restricted.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    before = app.drawing_collection_snapshot(services)
    history = tuple(loaded.document.commands)
    for prepare in (
        lambda: prepare_collection_translation(before, (ref,), WorkPlaneFrame.xy(), (1, 2)),
        lambda: prepare_collection_copy(before, (ref,), WorkPlaneFrame.xy(), (1, 2)),
        lambda: prepare_collection_rotation(before, (ref,), WorkPlaneFrame.xy(), (0, 0), 45),
        lambda: prepare_collection_scale(before, (ref,), WorkPlaneFrame.xy(), (0, 0), 2),
        lambda: prepare_collection_delete(before, (ref,)),
    ):
        with pytest.raises(ValidationError, match="锁定|隐藏|冻结"):
            prepare()
        assert app.drawing_collection_snapshot(services) == before
        assert tuple(loaded.document.commands) == history
    loaded.bus.undo_operation()
    unlocked = app.drawing_collection_snapshot(services)
    move = prepare_collection_translation(unlocked, (ref,), WorkPlaneFrame.xy(), (1, 2))
    loaded.bus.execute(move.command_id, move.params, "local", version=move.version)
    moved = app.drawing_collection_snapshot(services)
    assert moved.block_instances == (replace(instance, insertion_mm=(6, 7)),)
    assert moved.texts == (replace(text, position_mm=(9, 10)),) and moved.groups == (group,)
    path = tmp_path / "member-layer.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == unlocked
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == moved


def test_block_zero_layer_inherits_instance_layer_for_lock_checks() -> None:
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Insert"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), layer_name="Insert")
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    locked = layers.replace(replace(layers.get("0"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    updated = replace(definition, entities=(replace(line, end_mm=(4, 0)),))
    loaded.bus.execute("drawing.block.update", updated.to_mapping(), "local")
    moved = replace(instance, insertion_mm=(5, 0))
    loaded.bus.execute("drawing.block_instance.update", moved.to_mapping(), "local")
    assert services.kernel.drawing_block_definitions == (updated,)
    assert services.kernel.drawing_block_instances == (moved,)


def test_block_batch_then_optimized_sketch_revision_survives_reopen(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    operations = [
        {"id": "sketch.create", "version": 58, "params": sketch.to_state_mapping()},
        {"id": "drawing.block.create", "version": 1, "params": definition.to_mapping()},
        {"id": "drawing.block_instance.insert", "version": 1, "params": instance.to_mapping()},
        {"id": "drawing.group.create", "version": 1, "params": group.to_mapping()},
    ]
    loaded.bus.execute("drawing.objects.batch", {"operations": operations}, "local")
    changed = replace(sketch, entities=(replace(line, start_mm=(1, 0), end_mm=(3, 0)),))
    state = changed.to_state_mapping()
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
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == (instance,)
    path = tmp_path / "block-batch-revision.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_groups == (
        group,
    ) and services.kernel.drawing_block_instances == (instance,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == () and services.kernel.drawing_groups == ()
    assert (
        services.kernel.drawing_block_definitions == ()
        and services.kernel.drawing_block_instances == ()
    )


def test_convert_group_to_block_is_staged_atomically_and_undoes_after_reopen(
    tmp_path: Path,
) -> None:
    from mycad.core.drawing_block_transactions import prepare_block_create
    from mycad.core.drawing_text import DrawingText
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    lines = (LineEntity(uuid4().hex, (1, 1), (3, 1)), LineEntity(uuid4().hex, (1, 1), (1, 4)))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "Label", (2, 2))
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in lines
    ) + (DrawingObjectRef("text", text.text_id),)
    group = DrawingGroup(uuid4().hex, refs)
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    operation = prepare_block_create(before, (refs[0],), "Symbol", (1, 1), convert_sources=True)
    preview = session.preview_operation(operation)
    assert session.snapshot == before and loaded.document.commands == ()
    assert len(preview.block_definitions) == len(preview.block_instances) == 1
    instance = preview.block_instances[0]
    definition = preview.block_definitions[0]
    assert instance.insertion_mm == (1, 1) and instance.definition_id == definition.definition_id
    assert preview.groups[0].members == (DrawingObjectRef("block_instance", instance.instance_id),)
    assert preview.sketches[-1].entities == () and preview.texts == ()
    assert len(definition.entities) == 2 and len(definition.texts) == 1
    assert {item.entity_id for item in definition.entities}.isdisjoint(
        item.entity_id for item in lines
    )
    session.stage(operation)
    assert session.snapshot == preview
    session.undo()
    assert session.snapshot == before
    session.redo()
    assert session.snapshot == preview
    session.commit()
    path = tmp_path / "convert-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_block_instances == (instance,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == (group,)
    assert (
        services.kernel.drawing_block_definitions == ()
        and services.kernel.drawing_block_instances == ()
    )
    assert services.kernel.sketches[-1].entities == lines and services.kernel.drawing_texts == (
        text,
    )


def test_convert_overlapping_groups_requires_identical_memberships_and_roundtrips(
    tmp_path: Path,
) -> None:
    from mycad.core.drawing_block_transactions import prepare_block_create
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    lines = (LineEntity(uuid4().hex, (0, 0), (2, 0)), LineEntity(uuid4().hex, (0, 0), (0, 3)))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    refs = tuple(DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in lines)
    first = DrawingGroup(uuid4().hex, refs, name="First")
    second = DrawingGroup(uuid4().hex, refs, name="Second")
    incompatible = DrawingGroup(uuid4().hex, (refs[0],), name="Partial", selectable=False)
    for group in (first, second, incompatible):
        session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before, checkpoint = session.snapshot, session.checkpoint()
    with pytest.raises(ValidationError, match="归属"):
        prepare_block_create(before, (refs[0],), "Shared", (0, 0), convert_sources=True)
    assert session.snapshot == before and session.checkpoint() == checkpoint
    assert loaded.document.commands == ()
    session.undo()
    valid = session.snapshot
    operation = prepare_block_create(valid, (refs[0],), "Shared", (0, 0), convert_sources=True)
    preview = session.preview_operation(operation)
    instance = preview.block_instances[0]
    assert all(
        group.members == (DrawingObjectRef("block_instance", instance.instance_id),)
        for group in preview.groups
    )
    session.stage(operation)
    session.commit()
    path = tmp_path / "overlap-conversion.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == valid
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == preview
    exchange = tmp_path / "overlap-conversion.dxf"
    write_sketches_dxf(
        (),
        exchange,
        drawing_layers=preview.layers,
        groups=preview.groups,
        block_definitions=preview.block_definitions,
        block_instances=preview.block_instances,
    )
    imported = read_sketch_dxf(exchange)
    assert len(imported.groups) == 2 and len(imported.block_instances) == 1
    assert all(
        group.members
        == (DrawingObjectRef("block_instance", imported.block_instances[0].instance_id),)
        for group in imported.groups
    )


def test_convert_coplanar_sketches_projects_to_one_block_and_reopens(tmp_path: Path) -> None:
    from mycad.core.drawing_block_transactions import prepare_block_create
    from mycad.core.drawing_blocks import expand_block
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (1, 2), (3, 2))
    rotated = WorkPlaneFrame((10, 20, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    sketches = (
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,)),
        Sketch(uuid4().hex, rotated, (second,)),
    )
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    refs = tuple(
        DrawingObjectRef("geometry", sketch.entities[0].entity_id, sketch.sketch_id)
        for sketch in sketches
    )
    group = DrawingGroup(uuid4().hex, refs, name="Coplanar")
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    empty = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, empty.to_state_mapping(), "local"),
        session_identity=1,
    )
    operation = prepare_block_create(
        session.snapshot, (refs[0],), "Projected", (5, 7), convert_sources=True
    )
    preview = session.preview_operation(operation)
    assert app.drawing_collection_snapshot(services) == before
    definition, instance = preview.block_definitions[0], preview.block_instances[0]
    assert instance.insertion_mm == (5, 7)
    expansion = expand_block(definition, instance, preview.text_styles)
    assert all(isinstance(item, LineEntity) for item in expansion.entities)
    assert [
        (item.start_mm, item.end_mm) for item in expansion.entities if isinstance(item, LineEntity)
    ] == [((0, 0), (2, 0)), ((8, 21), (8, 23))]
    assert preview.groups[0].members == (DrawingObjectRef("block_instance", instance.instance_id),)
    session.stage(operation)
    session.commit()
    saved = tmp_path / "coplanar-conversion.my2d"
    save_document(loaded.document, saved)
    reopened = app.open_app_document(services, saved)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    after = app.drawing_collection_snapshot(services)
    assert after.block_instances == (instance,)
    exchange = tmp_path / "coplanar-conversion.dxf"
    write_sketches_dxf(
        (),
        exchange,
        block_definitions=after.block_definitions,
        block_instances=after.block_instances,
        groups=after.groups,
        drawing_layers=after.layers,
    )
    imported = read_sketch_dxf(exchange)
    imported_expansion = expand_block(
        imported.block_definitions[0],
        imported.block_instances[0],
        imported.text_styles or after.text_styles,
    )
    assert [
        (item.start_mm, item.end_mm)
        for item in imported_expansion.entities
        if isinstance(item, LineEntity)
    ] == [((0, 0), (2, 0)), ((8, 21), (8, 23))]
    assert imported.groups[0].members == (
        DrawingObjectRef("block_instance", imported.block_instances[0].instance_id),
    )


def test_keep_block_sources_creates_definition_without_reassigning_groups() -> None:
    from mycad.core.drawing_block_transactions import prepare_block_create
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 1), (3, 1))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    operation = prepare_block_create(
        session.snapshot, (ref,), "Kept", (1, 1), convert_sources=False
    )
    session.stage(operation)
    assert session.snapshot.sketches[-1] == draft and session.snapshot.groups == (group,)
    assert len(session.snapshot.block_definitions) == 1 and session.snapshot.block_instances == ()
    assert session.snapshot.block_definitions[0].entities[0].entity_id != line.entity_id
    session.undo()
    assert session.snapshot.block_definitions == () and session.snapshot.groups == (group,)
    session.cancel()


def test_kept_sources_definition_edit_insert_explode_and_reopen(tmp_path: Path) -> None:
    from mycad.core.drawing_block_transactions import prepare_block_create, prepare_block_explode
    from mycad.core.drawing_blocks import expand_block
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.drawing_block_editor import DrawingBlockEditorSession
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    source = LineEntity(uuid4().hex, (1, 1), (3, 1))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", source.entity_id, draft.sketch_id)
    session.stage(
        prepare_block_create(session.snapshot, (ref,), "Kept", (1, 1), convert_sources=False)
    )
    session.commit()
    retained = app.drawing_collection_snapshot(services)
    definition = retained.block_definitions[0]
    assert retained.block_instances == () and retained.sketches[-1].entities == (source,)
    member = definition.entities[0]
    assert isinstance(member, LineEntity)
    editor = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    editor.set_members((replace(member, end_mm=(4, 0)),), ())
    editor.save()
    edited = app.drawing_collection_snapshot(services)
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10), 90, 2)
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    inserted = app.drawing_collection_snapshot(services)
    expansion = expand_block(edited.block_definitions[0], instance, inserted.text_styles)
    expanded_line = expansion.entities[0]
    assert isinstance(expanded_line, LineEntity)
    assert expanded_line.end_mm == pytest.approx((10, 18))
    operation = prepare_block_explode(inserted, instance.instance_id)
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    exploded = app.drawing_collection_snapshot(services)
    assert exploded.block_instances == () and exploded.block_definitions == edited.block_definitions
    assert any(source in sketch.entities for sketch in exploded.sketches)
    exploded_lines = [
        item
        for sketch in exploded.sketches
        for item in sketch.entities
        if isinstance(item, LineEntity) and item.entity_id != source.entity_id
    ]
    assert len(exploded_lines) == 1
    assert exploded_lines[0].start_mm == pytest.approx(expanded_line.start_mm)
    assert exploded_lines[0].end_mm == pytest.approx(expanded_line.end_mm)
    path = tmp_path / "kept-edit-explode.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert app.drawing_collection_snapshot(services) == exploded
    for expected in (inserted, edited, retained):
        reopened.bus.undo_operation()
        assert app.drawing_collection_snapshot(services) == expected
    for expected in (edited, inserted, exploded):
        reopened.bus.redo_operation()
        assert app.drawing_collection_snapshot(services) == expected


@pytest.mark.parametrize("kind", ["polyline", "spline", "rotated_rectangle"])
def test_new_block_definition_assigns_legacy_curve_point_ids(tmp_path: Path, kind: str) -> None:
    import math

    from mycad.core.drawing_block_transactions import prepare_block_create
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.core.sketch import PolylineEntity, RectangleEntity, SketchEntity, SplineEntity
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    entity: SketchEntity
    frame = WorkPlaneFrame.xy()
    if kind == "polyline":
        entity = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)))
    elif kind == "spline":
        entity = SplineEntity(uuid4().hex, ((0, 0), (1, 0), (2, 1), (3, 1)))
    else:
        entity = RectangleEntity(uuid4().hex, (0, 0), (2, 1))
        c = math.sqrt(0.5)
        frame = WorkPlaneFrame((0, 0, 0), (c, c, 0), (-c, c, 0), (0, 0, 1))
    draft = Sketch(uuid4().hex, frame, (entity,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", entity.entity_id, draft.sketch_id)
    operation = prepare_block_create(session.snapshot, (ref,), "New", (0, 0), convert_sources=False)
    session.stage(operation)
    member = session.snapshot.block_definitions[0].entities[0]
    assert isinstance(member, PolylineEntity | SplineEntity)
    assert len(member.point_ids) == (3 if kind == "polyline" else 4)
    assert len(set(member.point_ids)) == len(member.point_ids)
    session.commit()
    path = tmp_path / f"new-{kind}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_block_definitions[0].entities == (member,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == ()
    reopened.bus.redo_operation()
    assert services.kernel.drawing_block_definitions[0].entities == (member,)


def test_block_conversion_rejects_dependencies_and_conflicting_group_memberships() -> None:
    from mycad.core.drawing_block_transactions import prepare_block_create
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (2, 0), (2, 3))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (relation,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    refs = tuple(
        DrawingObjectRef("geometry", item.entity_id, draft.sketch_id) for item in (first, second)
    )
    snapshot = session.snapshot
    with pytest.raises(ValidationError, match="约束"):
        prepare_block_create(snapshot, refs, "B", (0, 0), convert_sources=True)
    # Keeping sources copies their current geometry and does not retain constraints.
    session.stage(prepare_block_create(snapshot, (refs[0],), "Kept", (0, 0), convert_sources=False))
    assert len(session.snapshot.block_definitions) == 1 and session.snapshot.sketches[-1] == draft
    session.undo()
    unconstrained = replace(draft, constraints=())
    group = DrawingGroup(uuid4().hex, (refs[0],), selectable=False)
    conflict = replace(snapshot, sketches=(unconstrained,), groups=(group,))
    with pytest.raises(ValidationError, match="归属"):
        prepare_block_create(conflict, refs, "B", (0, 0), convert_sources=True)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(first.entity_id, "start")
        ),
    )
    attached = replace(snapshot, sketches=(unconstrained,), datums=(datum,))
    with pytest.raises(ValidationError, match="附着"):
        prepare_block_create(attached, (refs[0],), "B", (0, 0), convert_sources=True)
    assert session.snapshot == snapshot and loaded.document.commands == ()
    session.cancel()


def test_block_conversion_rejects_array_and_cross_sketch_tangency() -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.drawing_block_transactions import prepare_block_create
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.core.sketch import CircleEntity
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    copy = LineEntity(uuid4().hex, (0, 4), (10, 4))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, copy))
    other = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    source = ArrayEntityRef(draft.sketch_id, line.entity_id)
    target = ArrayEntityRef(draft.sketch_id, copy.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, draft.frame, 1, 2, 0, 4, (source,), (ArrayMember(source, target, 0, 1),)
    )
    array_snapshot = replace(session.snapshot, associative_arrays=(array,))
    with pytest.raises(ValidationError, match="阵列"):
        prepare_block_create(array_snapshot, (ref,), "B", (0, 0), convert_sources=True)
    kept = prepare_block_create(array_snapshot, (ref,), "B", (0, 0), convert_sources=False)
    assert kept.command_id == "drawing.objects.batch"
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(draft.sketch_id, line.entity_id),
        CrossSketchRef(other.sketch_id, circle.entity_id),
        "line_left",
    )
    tangent_snapshot = replace(
        session.snapshot, sketches=(draft, other), cross_tangencies=(relation,)
    )
    with pytest.raises(ValidationError, match="约束"):
        prepare_block_create(tangent_snapshot, (ref,), "B", (0, 0), convert_sources=True)
    assert session.snapshot.block_definitions == () and loaded.document.commands == ()
    session.cancel()


@pytest.mark.parametrize("selected_kind", ["source", "member"])
def test_keep_array_geometry_creates_independent_block_without_changing_array(
    tmp_path: Path, selected_kind: str
) -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.drawing_block_transactions import prepare_block_create
    from mycad.core.drawing_blocks import expand_block
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    member = LineEntity(uuid4().hex, (4, 0), (14, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, member))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    source_ref = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    member_ref = ArrayEntityRef(sketch.sketch_id, member.entity_id)
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        4,
        (source_ref,),
        (ArrayMember(source_ref, member_ref, 0, 1),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    before = app.drawing_collection_snapshot(services)
    selected = source if selected_kind == "source" else member
    ref = DrawingObjectRef("geometry", selected.entity_id, sketch.sketch_id)
    with pytest.raises(ValidationError, match="阵列"):
        prepare_block_create(before, (ref,), "B", (0, 0), convert_sources=True)
    assert app.drawing_collection_snapshot(services) == before
    prepared = prepare_block_create(before, (ref,), "B", (0, 0), convert_sources=False)
    loaded.bus.execute(prepared.command_id, prepared.params, "local", version=prepared.version)
    after = app.drawing_collection_snapshot(services)
    assert after.associative_arrays == before.associative_arrays
    assert after.sketches == before.sketches and not after.block_instances
    copied = after.block_definitions[0].entities[0]
    assert isinstance(copied, LineEntity)
    assert copied.entity_id != selected.entity_id
    assert (copied.start_mm, copied.end_mm) == (selected.start_mm, selected.end_mm)
    instance = BlockInstance(uuid4().hex, after.block_definitions[0].definition_id, (20, 10))
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    inserted = app.drawing_collection_snapshot(services)
    loaded.bus.execute(
        "drawing.array.move", {"array_id": array.array_id, "displacement": [2, 3]}, "local"
    )
    moved = app.drawing_collection_snapshot(services)
    assert moved.sketches[0].entities == (
        replace(source, start_mm=(2, 3), end_mm=(12, 3)),
        replace(member, start_mm=(6, 3), end_mm=(16, 3)),
    )
    assert moved.block_definitions == after.block_definitions
    assert moved.block_instances == (instance,)
    expansion = expand_block(moved.block_definitions[0], instance, moved.text_styles)
    expanded = expansion.entities[0]
    assert isinstance(expanded, LineEntity)
    assert expanded.start_mm == (selected.start_mm[0] + 20, selected.start_mm[1] + 10)
    exchange = tmp_path / f"array-{selected_kind}-snapshot.dxf"
    write_sketches_dxf(
        moved.sketches,
        exchange,
        drawing_layers=moved.layers,
        block_definitions=moved.block_definitions,
        block_instances=moved.block_instances,
    )
    imported = read_sketch_dxf(exchange)
    imported_expansion = expand_block(
        imported.block_definitions[0],
        imported.block_instances[0],
        imported.text_styles or moved.text_styles,
    )
    imported_line = imported_expansion.entities[0]
    assert isinstance(imported_line, LineEntity) and imported_line.start_mm == expanded.start_mm
    path = tmp_path / f"array-{selected_kind}-kept.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == inserted
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == after
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == inserted
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == moved


def test_keep_geometry_with_constraints_tangency_and_attached_datum(tmp_path: Path) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.drawing_block_transactions import prepare_block_create
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (2, 4),
        (0, 0),
        attachment=DatumAttachment(
            first.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=28
    )
    before = app.drawing_collection_snapshot(services)
    ref = DrawingObjectRef("geometry", line.entity_id, first.sketch_id)
    with pytest.raises(ValidationError, match="尺寸|约束"):
        prepare_block_create(before, (ref,), "Snapshot", (0, 0), convert_sources=True)
    assert app.drawing_collection_snapshot(services) == before
    prepared = prepare_block_create(before, (ref,), "Snapshot", (0, 0), convert_sources=False)
    loaded.bus.execute(prepared.command_id, prepared.params, "local", version=prepared.version)
    after = app.drawing_collection_snapshot(services)
    assert after.sketches == before.sketches and after.cross_tangencies == (relation,)
    assert after.datums == (datum,) and not after.block_instances
    copied = after.block_definitions[0].entities[0]
    assert isinstance(copied, LineEntity) and copied.entity_id != line.entity_id
    assert (copied.start_mm, copied.end_mm) == (line.start_mm, line.end_mm)
    path = tmp_path / "keep-associated-geometry.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_convert_text_only_group_to_block() -> None:
    from mycad.core.drawing_block_transactions import prepare_block_create
    from mycad.core.drawing_text import DrawingText
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "Only text", (3, 2))
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    ref = DrawingObjectRef("text", text.text_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    session.stage(
        prepare_block_create(session.snapshot, (ref,), "Text", (3, 2), convert_sources=True)
    )
    assert session.snapshot.texts == () and session.snapshot.block_definitions[0].entities == ()
    assert session.snapshot.block_definitions[0].texts[0].position_mm == (0, 0)
    assert session.snapshot.groups[0].members == (
        DrawingObjectRef("block_instance", session.snapshot.block_instances[0].instance_id),
    )
    session.undo()
    assert session.snapshot.texts == (text,) and session.snapshot.groups == (group,)
    session.cancel()


def test_group_moves_block_instance_and_geometry_atomically(tmp_path: Path) -> None:
    from mycad.core.drawing_transactions import prepare_collection_translation
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    ref = DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (ref, DrawingObjectRef("block_instance", instance.instance_id))
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    operation = prepare_collection_translation(session.snapshot, (ref,), draft.frame, (2, 3))
    session.stage(operation)
    assert session.snapshot.block_instances == (replace(instance, insertion_mm=(7, 8)),)
    moved = session.snapshot.sketches[0].entities[0]
    assert isinstance(moved, LineEntity) and moved.start_mm == (2, 3)
    session.commit()
    path = tmp_path / "move-block-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_instances == (instance,)
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("layer_change", [{"locked": True}, {"visible": False}, {"frozen": True}])
def test_group_move_rejects_unavailable_block_layer_before_staging(
    layer_change: dict[str, bool],
) -> None:
    from mycad.core.drawing_transactions import prepare_collection_translation
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Insert"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), layers=layers)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5), layer_name="Insert")
    session.stage(ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local"))
    session.stage(ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local"))
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (ref, DrawingObjectRef("block_instance", instance.instance_id))
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    checkpoint = session.checkpoint()
    changed_layers = layers.replace(replace(layers.get("Insert"), **layer_change))
    blocked = replace(session.snapshot, layers=changed_layers)
    with pytest.raises(ValidationError, match="图层"):
        prepare_collection_translation(blocked, (ref,), draft.frame, (2, 3))
    assert session.checkpoint() == checkpoint and session.snapshot.block_instances == (instance,)
    assert session.snapshot.sketches[-1] == draft
    session.cancel()


@pytest.mark.parametrize("action", ["rotate", "scale"])
@pytest.mark.parametrize("plane", ["parallel", "tilted"])
def test_block_transform_rejects_non_coplanar_workplane(action: str, plane: str) -> None:
    from mycad.core.drawing_transactions import (
        prepare_collection_rotation,
        prepare_collection_scale,
    )

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Block", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    snapshot = app.drawing_collection_snapshot(services)
    history = tuple(loaded.document.commands)
    frame = (
        replace(WorkPlaneFrame.xy(), origin_mm=(0, 0, 2))
        if plane == "parallel"
        else WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, 0, 1), (0, -1, 0))
    )
    ref = DrawingObjectRef("block_instance", instance.instance_id)
    with pytest.raises(ValidationError, match="共面"):
        if action == "rotate":
            prepare_collection_rotation(snapshot, (ref,), frame, (1, 1), 90)
        else:
            prepare_collection_scale(snapshot, (ref,), frame, (1, 1), 2)
    assert tuple(loaded.document.commands) == history
    assert app.drawing_collection_snapshot(services) == snapshot


def test_block_scale_uses_coplanar_rotated_workplane_center() -> None:
    from mycad.core.drawing_transactions import prepare_collection_scale

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(
        uuid4().hex, "Block", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    frame = WorkPlaneFrame((10, 20, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    operation = prepare_collection_scale(
        app.drawing_collection_snapshot(services),
        (DrawingObjectRef("block_instance", instance.instance_id),),
        frame,
        (2, 3),
        2,
    )
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    result = services.kernel.drawing_block_instances[0]
    assert result.insertion_mm == pytest.approx((3, -12)) and result.scale == 2
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_instances == (instance,)


@pytest.mark.parametrize("operation_kind", ["scale", "rotate"])
def test_small_block_transform_remains_effective_and_undoes_after_reopen(
    tmp_path: Path, operation_kind: str
) -> None:
    from mycad.core.drawing_transactions import (
        prepare_collection_rotation,
        prepare_collection_scale,
    )

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (1e10, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    snapshot = app.drawing_collection_snapshot(services)
    ref = DrawingObjectRef("block_instance", instance.instance_id)
    operation = (
        prepare_collection_scale(snapshot, (ref,), WorkPlaneFrame.xy(), (0, 0), 1 + 1e-11)
        if operation_kind == "scale"
        else prepare_collection_rotation(snapshot, (ref,), WorkPlaneFrame.xy(), (0, 0), 1e-11)
    )
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    transformed = services.kernel.drawing_block_instances[0]
    if operation_kind == "scale":
        assert transformed.insertion_mm[0] > instance.insertion_mm[0] + 0.05
        assert transformed.scale == 1 + 1e-11
    else:
        assert transformed.insertion_mm[1] > 0.001
        assert transformed.rotation_deg == 1e-11
    path = tmp_path / "small-transform.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_block_instances == (transformed,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_instances == (instance,)


@pytest.mark.parametrize(
    ("operation_kind", "value"),
    [("scale", 1), ("scale", 0), ("scale", -1), ("rotate", 0), ("rotate", 360), ("rotate", -360)],
)
def test_noop_or_invalid_block_transform_does_not_change_state(
    operation_kind: str, value: float
) -> None:
    from mycad.core.drawing_transactions import (
        prepare_collection_rotation,
        prepare_collection_scale,
    )
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    snapshot = app.drawing_collection_snapshot(services)
    history = tuple(loaded.document.commands)
    ref = DrawingObjectRef("block_instance", instance.instance_id)
    with pytest.raises(ValidationError):
        prepare = (
            prepare_collection_scale if operation_kind == "scale" else prepare_collection_rotation
        )
        prepare(snapshot, (ref,), WorkPlaneFrame.xy(), (0, 0), value)
    assert app.drawing_collection_snapshot(services) == snapshot
    assert tuple(loaded.document.commands) == history


@pytest.mark.parametrize("action", ["copy", "rotate", "scale", "delete"])
def test_group_block_and_geometry_operations_are_atomic(tmp_path: Path, action: str) -> None:
    from mycad.core.drawing_transactions import (
        prepare_collection_copy,
        prepare_collection_delete,
        prepare_collection_rotation,
        prepare_collection_scale,
    )
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    session.stage(ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local"))
    session.stage(ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local"))
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (ref, DrawingObjectRef("block_instance", instance.instance_id))
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    if action == "copy":
        operation = prepare_collection_copy(before, (ref,), draft.frame, (2, 3))
    elif action == "rotate":
        operation = prepare_collection_rotation(before, (ref,), draft.frame, (0, 0), 90)
    elif action == "scale":
        operation = prepare_collection_scale(before, (ref,), draft.frame, (0, 0), 2)
    else:
        operation = prepare_collection_delete(before, (ref,))
    session.stage(operation)
    result = session.snapshot
    assert result.block_definitions == (definition,)
    if action == "copy":
        assert len(result.block_instances) == len(result.groups) == 2
        duplicate = next(
            item for item in result.block_instances if item.instance_id != instance.instance_id
        )
        assert duplicate.definition_id == definition.definition_id and duplicate.insertion_mm == (
            7,
            8,
        )
        assert (
            DrawingObjectRef("block_instance", duplicate.instance_id) in result.groups[-1].members
        )
    elif action == "delete":
        assert (
            result.block_instances == ()
            and result.groups == ()
            and result.sketches[-1].entities == ()
        )
    elif action == "rotate":
        assert result.block_instances[0].insertion_mm == pytest.approx((-5, 5))
        assert result.block_instances[0].rotation_deg == pytest.approx(90)
    else:
        assert result.block_instances[0].insertion_mm == pytest.approx((10, 10))
        assert result.block_instances[0].scale == pytest.approx(2)
    session.undo()
    assert session.snapshot == before
    session.redo()
    session.commit()
    path = tmp_path / f"block-group-{action}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_instances == (instance,)
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.sketches[-1] == draft


@pytest.mark.parametrize("action", ["move", "copy", "rotate", "scale"])
def test_overlapping_groups_do_not_expand_through_block_instance(action: str) -> None:
    from mycad.core.drawing_transactions import (
        prepare_collection_copy,
        prepare_collection_rotation,
        prepare_collection_scale,
        prepare_collection_translation,
    )
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    other = LineEntity(uuid4().hex, (0, 10), (2, 10))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, other))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    session.stage(ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local"))
    session.stage(ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local"))
    first_ref = DrawingObjectRef("geometry", first.entity_id, draft.sketch_id)
    other_ref = DrawingObjectRef("geometry", other.entity_id, draft.sketch_id)
    block_ref = DrawingObjectRef("block_instance", instance.instance_id)
    first_group = DrawingGroup(uuid4().hex, (first_ref, block_ref))
    second_group = DrawingGroup(uuid4().hex, (block_ref, other_ref))
    for group in (first_group, second_group):
        session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    if action == "move":
        operation = prepare_collection_translation(before, (first_ref,), draft.frame, (0, 3))
    elif action == "copy":
        operation = prepare_collection_copy(before, (first_ref,), draft.frame, (0, 3))
    elif action == "rotate":
        operation = prepare_collection_rotation(before, (first_ref,), draft.frame, (0, 0), 90)
    else:
        operation = prepare_collection_scale(before, (first_ref,), draft.frame, (0, 0), 2)
    session.stage(operation)
    result = session.snapshot
    assert (
        next(item for item in result.sketches[-1].entities if item.entity_id == other.entity_id)
        == other
    )
    if action == "copy":
        assert len(result.groups) == 3 and len(result.block_instances) == 2
        assert result.groups[2].members[0].kind == "geometry"
        assert other_ref not in result.groups[2].members
    else:
        assert result.groups == (first_group, second_group)
        assert result.block_instances[0] != instance
    session.undo()
    assert session.snapshot == before
    session.cancel()


def test_group_mirror_rejects_block_instances_without_partial_changes() -> None:
    from mycad.core.drawing_transactions import (
        prepare_collection_mirror,
        prepare_collection_mirror_copy,
    )
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    session.stage(ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local"))
    session.stage(ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local"))
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex, (ref, DrawingObjectRef("block_instance", instance.instance_id))
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before, checkpoint = session.snapshot, session.checkpoint()
    for prepare in (prepare_collection_mirror, prepare_collection_mirror_copy):
        with pytest.raises(ValidationError, match="镜像"):
            prepare(before, (ref,), draft.frame, (0, 0), (1, 0))
    assert session.snapshot == before and session.checkpoint() == checkpoint
    session.cancel()


def test_group_move_with_attached_datum_also_moves_block_instance() -> None:
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    session.stage(ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local"))
    session.stage(ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local"))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            ref,
            DrawingObjectRef("datum", datum.datum_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = session.snapshot
    operation = session.prepare_attached_move((ref,), draft.frame, (0, 3))
    session.stage(operation)
    assert session.snapshot.block_instances == (replace(instance, insertion_mm=(5, 8)),)
    assert session.snapshot.datums[0].target_mm == (0, 3)
    assert session.snapshot.sketches[-1].entities[0] == replace(
        line, start_mm=(0, 3), end_mm=(2, 3)
    )
    session.undo()
    assert session.snapshot == before
    session.stage(
        ReplayAppend(
            "drawing.group.update", 1, replace(group, selectable=False).to_mapping(), "local"
        )
    )
    block_ref = DrawingObjectRef("block_instance", instance.instance_id)
    session.stage(session.prepare_attached_move((block_ref,), draft.frame, (0, 3)))
    assert session.snapshot.block_instances == (replace(instance, insertion_mm=(5, 8)),)
    assert session.snapshot.datums == (datum,) and session.snapshot.sketches[-1] == draft
    session.cancel()


@pytest.mark.parametrize("restriction", ["locked", "hidden", "frozen"])
@pytest.mark.parametrize("restricted_member", ["Instance", "Picture"])
def test_attached_mixed_group_move_rejects_restricted_member_layer_atomically(
    restriction: str, restricted_member: str, tmp_path: Path
) -> None:
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Instance")).add(SketchLayer("Picture"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,), layers=layers)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    definition = BlockDefinition(
        uuid4().hex, "Mixed", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5), layer_name="Instance")
    session.stage(ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local"))
    session.stage(ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local"))
    image = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (8, 2),
        2,
        2,
        layer_name="Picture",
    )
    session.stage(
        ReplayAppend(
            "drawing.raster.batch",
            2,
            {"action": "add", "images": [image.to_mapping(version=2)]},
            "local",
        )
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            draft.sketch_id, SketchGeometryReference(source.entity_id, "start")
        ),
    )
    session.stage(
        ReplayAppend("drawing.tolerance.batch", 28, {"add_datums": [datum.to_mapping()]}, "local")
    )
    ref = DrawingObjectRef("geometry", source.entity_id, draft.sketch_id)
    group = DrawingGroup(
        uuid4().hex,
        (
            ref,
            DrawingObjectRef("datum", datum.datum_id),
            DrawingObjectRef("raster", image.image_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    layer = layers.get(restricted_member)
    restricted = layers.replace(
        replace(layer, **({"visible": False} if restriction == "hidden" else {restriction: True}))
    )
    session.stage(
        ReplayAppend(
            "drawing.objects.batch",
            1,
            {
                "operations": [
                    {
                        "id": "drawing.layers.set",
                        "version": 1,
                        "params": {"layers": restricted.to_mapping(), "dimension_layer": "DIM"},
                    }
                ]
            },
            "local",
        )
    )
    before, checkpoint, history = (
        session.snapshot,
        session.checkpoint(),
        tuple(loaded.document.commands),
    )
    with pytest.raises(ValidationError, match="锁定|隐藏|冻结"):
        session.prepare_attached_move((ref,), draft.frame, (0, 3))
    assert session.checkpoint() == checkpoint and session.snapshot == before
    assert tuple(loaded.document.commands) == history
    session.undo()
    session.stage(session.prepare_attached_move((ref,), draft.frame, (0, 3)))
    assert session.snapshot.block_instances == (replace(instance, insertion_mm=(5, 8)),)
    assert session.snapshot.datums[0].target_mm == (0, 3)
    assert session.snapshot.rasters == (replace(image, origin_mm=(8, 5)),)
    assert session.snapshot.sketches[-1].entities[0] == replace(
        source, start_mm=(0, 3), end_mm=(2, 3)
    )
    moved = session.snapshot
    session.commit()
    path = tmp_path / f"restricted-block-{restriction}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_instances == (instance,)
    assert services.kernel.drawing_datum_identifiers == (datum,)
    assert services.kernel.drawing_rasters == (image,)
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == moved


def test_block_derived_geometry_cannot_become_persistent_external_association() -> None:
    from mycad.core.drawing_blocks import expand_block
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    inner = LineEntity(uuid4().hex, (0, 0), (5, 0))
    definition = BlockDefinition(uuid4().hex, "B", (inner,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    derived = expand_block(definition, instance, services.kernel.drawing_text_styles).entities[0]
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(derived.entity_id, "geometry"),), 5, "mm"
    )
    state = sketch.to_state_mapping()
    params = {
        "revisions": [
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": state["entities"],
                "constraints": [dimension.to_mapping()],
            }
        ]
    }
    history = tuple(loaded.document.commands)
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=79)
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (15, 12),
        (10, 10),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(derived.entity_id, "start")
        ),
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=28
        )
    assert tuple(loaded.document.commands) == history
    assert services.kernel.sketches == (sketch,) and services.kernel.drawing_datum_identifiers == ()


def test_explode_grouped_instance_is_atomic_and_undoes_after_reopen(tmp_path: Path) -> None:
    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.drawing_text import DrawingText

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    text = DrawingText(uuid4().hex, "Label", (1, 0))
    definition = BlockDefinition(uuid4().hex, "Symbol", (line,), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 20), 90, 2)
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    marker = DrawingText(uuid4().hex, "Marker", (0, 0))
    loaded.bus.execute("drawing.text.add", marker.to_mapping(), "local")
    instance_ref = DrawingObjectRef("block_instance", instance.instance_id)
    marker_ref = DrawingObjectRef("text", marker.text_id)
    group = DrawingGroup(uuid4().hex, (instance_ref,))
    overlap = DrawingGroup(uuid4().hex, (marker_ref, instance_ref), selectable=False)
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    loaded.bus.execute("drawing.group.create", overlap.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    operation = prepare_block_explode(before, instance.instance_id)
    assert operation.command_id == "drawing.block_instance.explode" and operation.version == 1
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    assert loaded.document.commands[-1].id == "drawing.block_instance.explode"
    after = app.drawing_collection_snapshot(services)
    assert after.block_definitions == (definition,) and after.block_instances == ()
    entity = after.sketches[-1].entities[0]
    assert isinstance(entity, LineEntity)
    assert entity.start_mm == pytest.approx((10, 20)) and entity.end_mm == pytest.approx((10, 24))
    assert entity.entity_id != line.entity_id
    exploded_text = next(item for item in after.texts if item.text_id != marker.text_id)
    assert exploded_text.text_id != text.text_id
    assert exploded_text.position_mm == pytest.approx((10, 22))
    assert after.groups[0].members == (
        DrawingObjectRef("geometry", entity.entity_id, after.sketches[-1].sketch_id),
        DrawingObjectRef("text", exploded_text.text_id),
    )
    assert after.groups[1] == replace(overlap, members=(marker_ref, *after.groups[0].members))
    path = tmp_path / "explode.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_block_editor_local_history_save_and_stale_session_preserves_edits() -> None:
    from mycad.ui.drawing_block_editor import DrawingBlockEditorSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Edit", (line,), ())
    instances = tuple(BlockInstance(uuid4().hex, definition.definition_id, (x, 0)) for x in (5, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for instance in instances:
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    revised = replace(definition, entities=(replace(line, end_mm=(3, 0)),))
    history = tuple(loaded.document.commands)
    editor.set_members(revised.entities, revised.texts)
    assert editor.dirty and tuple(loaded.document.commands) == history
    assert editor.undo() and editor.definition == definition
    assert editor.redo() and editor.definition == revised
    editor.save()
    assert not editor.dirty and services.kernel.drawing_block_definitions == (revised,)
    assert services.kernel.drawing_block_instances == instances
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (definition,)
    editor.set_members((replace(line, end_mm=(4, 0)),), ())
    with pytest.raises(ValidationError, match="变化|过期"):
        editor.save()
    assert editor.dirty and editor.definition.entities == (replace(line, end_mm=(4, 0)),)
    assert services.kernel.drawing_block_definitions == (definition,)


def test_block_editor_locked_instance_save_keeps_local_changes() -> None:
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.drawing_block_editor import DrawingBlockEditorSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Insert"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Locked", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), layer_name="Insert")
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    locked = layers.replace(replace(layers.get("Insert"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    editor = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    editor.set_members((replace(line, end_mm=(4, 0)),), ())
    history = tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="锁定"):
        editor.save()
    assert editor.dirty and editor.definition.entities == (replace(line, end_mm=(4, 0)),)
    assert services.kernel.drawing_block_definitions == (definition,)
    assert tuple(loaded.document.commands) == history


def test_block_editor_rejects_save_after_document_switch() -> None:
    from mycad.ui.drawing_block_editor import DrawingBlockEditorSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Switch", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    editor = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: False
    )
    editor.set_members((replace(line, end_mm=(4, 0)),), ())
    before = tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="过期"):
        editor.save()
    assert editor.dirty and tuple(loaded.document.commands) == before


def test_block_editor_allows_temporarily_empty_content_but_cannot_save_it() -> None:
    from mycad.ui.drawing_block_editor import DrawingBlockEditorSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "EditEmpty", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    editor = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    editor.set_members((), ())
    assert editor.entities == () and editor.texts == () and editor.dirty
    with pytest.raises(ValidationError):
        editor.save()
    assert editor.dirty and services.kernel.drawing_block_definitions == (definition,)
    assert editor.undo() and editor.definition == definition
    assert editor.redo() and editor.entities == ()
    replacement = LineEntity(uuid4().hex, (0, 0), (4, 0))
    editor.set_members((replacement,), ())
    editor.save()
    assert services.kernel.drawing_block_definitions[0].entities == (replacement,)


def test_block_explode_distinguishes_colliding_geometry_and_text_ids(tmp_path: Path) -> None:
    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.drawing_blocks import expand_block
    from mycad.core.drawing_text import DrawingText

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    shared_id = uuid4().hex
    line = LineEntity(shared_id, (0, 0), (2, 0))
    text = DrawingText(shared_id, "Text", (1, 1))
    definition = BlockDefinition(uuid4().hex, "TypedIdentity", (line,), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5), 90, 2)
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    expansion = expand_block(definition, instance, before.text_styles)
    assert expansion.entities[0].entity_id != expansion.texts[0].text_id
    operation = prepare_block_explode(before, instance.instance_id)
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    after = app.drawing_collection_snapshot(services)
    geometry = next(item for item in after.groups[0].members if item.kind == "geometry")
    text_ref = next(item for item in after.groups[0].members if item.kind == "text")
    assert geometry.object_id != text_ref.object_id
    assert after.sketches[0].entities[0].entity_id == geometry.object_id
    assert after.texts[0].text_id == text_ref.object_id
    assert after.texts[0].position_mm == pytest.approx(expansion.texts[0].position_mm)
    path = tmp_path / "typed-block-ids.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert app.drawing_collection_snapshot(services) == after
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_explode_rejects_reused_or_duplicate_ids_atomically() -> None:
    from copy import deepcopy
    from typing import cast

    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.drawing_text import DrawingText

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    text = DrawingText(uuid4().hex, "Label", (0, 1))
    definition = BlockDefinition(uuid4().hex, "B", (line,), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (1, 1))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    existing = DrawingText(uuid4().hex, "Existing", (4, 4))
    loaded.bus.execute("drawing.text.add", existing.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    history = tuple(loaded.document.commands)
    operation = prepare_block_explode(before, instance.instance_id)
    repeated = deepcopy(operation.params)
    geometry = cast("list[dict[str, object]]", repeated["geometry_ids"])
    geometry[0]["entity_id"] = line.entity_id
    with pytest.raises(ValidationError):
        loaded.bus.execute(operation.command_id, repeated, "local", version=1)
    duplicate = dict(deepcopy(operation.params))
    duplicate["text_ids"] = [
        cast("list[dict[str, object]]", duplicate["geometry_ids"])[0]["entity_id"]
    ]
    with pytest.raises(ValidationError):
        loaded.bus.execute(operation.command_id, duplicate, "local", version=1)
    collision = dict(deepcopy(operation.params))
    collision["text_ids"] = [existing.text_id]
    with pytest.raises(ValidationError):
        loaded.bus.execute(operation.command_id, collision, "local", version=1)
    assert (
        tuple(loaded.document.commands) == history
        and app.drawing_collection_snapshot(services) == before
    )


def test_explode_rejects_definition_change_after_preparation() -> None:
    from mycad.core.drawing_block_transactions import prepare_block_explode

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Changing", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (1, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    operation = prepare_block_explode(
        app.drawing_collection_snapshot(services), instance.instance_id
    )
    changed = replace(definition, entities=(replace(line, end_mm=(5, 0)),))
    loaded.bus.execute("drawing.block.update", changed.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    history = tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="变化|过期"):
        loaded.bus.execute(
            operation.command_id, operation.params, "local", version=operation.version
        )
    assert (
        app.drawing_collection_snapshot(services) == before
        and tuple(loaded.document.commands) == history
    )


def test_explode_curve_ids_survive_optimized_rebuild_and_reopen(tmp_path: Path) -> None:
    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.sketch import PolylineEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    curve = PolylineEntity(
        uuid4().hex, ((0, 0), (2, 0), (2, 2)), point_ids=tuple(uuid4().hex for _ in range(3))
    )
    definition = BlockDefinition(uuid4().hex, "Curve", (curve,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 5), 90, 2)
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    operation = prepare_block_explode(
        app.drawing_collection_snapshot(services), instance.instance_id
    )
    loaded.bus.execute(operation.command_id, operation.params, "local", version=1)
    exploded = services.kernel.sketches[-1].entities[0]
    assert isinstance(exploded, PolylineEntity) and len(exploded.point_ids) == 3
    assert set(exploded.point_ids).isdisjoint(curve.point_ids)
    revised = replace(sketch, entities=(replace(line, end_mm=(4, 0)),))
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
        version=52,
    )
    assert len(services.kernel.sketches) == 2 and services.kernel.sketches[-1].entities == (
        exploded,
    )
    path = tmp_path / "curve-explode.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.sketches) == 2 and services.kernel.sketches[-1].entities == (
        exploded,
    )
    reopened.bus.undo_operation()
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_instances == (instance,)
    reopened.bus.redo_operation()
    assert services.kernel.sketches[-1].entities == (exploded,)


def test_grouped_explode_with_text_survives_optimized_rebuild_and_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Callable
    from typing import cast

    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.sketch import PolylineEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (4, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    curve = PolylineEntity(
        uuid4().hex, ((0, 0), (2, 0), (2, 2)), point_ids=tuple(uuid4().hex for _ in range(3))
    )
    text = DrawingText(uuid4().hex, "Inside", (1, 1))
    definition = BlockDefinition(uuid4().hex, "GroupedCurve", (curve,), (text,))
    instances = (
        BlockInstance(uuid4().hex, definition.definition_id, (10, 5), 90, 2),
        BlockInstance(uuid4().hex, definition.definition_id, (20, 5)),
    )
    external = DrawingText(uuid4().hex, "Outside", (3, 3))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for instance in instances:
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute("drawing.text.add", external.to_mapping(), "local")
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("block_instance", instances[0].instance_id),
            DrawingObjectRef("text", external.text_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    operation = prepare_block_explode(before, instances[0].instance_id)
    loaded.bus.execute(operation.command_id, operation.params, "local", version=1)
    exploded = app.drawing_collection_snapshot(services)
    assert exploded.block_definitions == (definition,) and exploded.block_instances == (
        instances[1],
    )
    members = exploded.groups[0].members
    assert tuple(ref.kind for ref in members) == ("geometry", "text", "text")
    assert members[-1] == DrawingObjectRef("text", external.text_id)
    created_sketch = next(
        item for item in exploded.sketches if item.sketch_id == members[0].sketch_id
    )
    generated = created_sketch.entities[0]
    assert isinstance(generated, PolylineEntity) and generated.entity_id == members[0].object_id
    assert len(generated.point_ids) == 3 and set(generated.point_ids).isdisjoint(curve.point_ids)
    assert any(item.text_id == members[1].object_id for item in exploded.texts)
    regenerate = cast(
        "Callable[..., object]", vars(type(services.kernel))["_regenerate_with_sketches"]
    )
    calls = 0

    def track(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return regenerate(services.kernel, *args, **kwargs)

    monkeypatch.setattr(services.kernel, "_regenerate_with_sketches", track)
    revised = replace(sketch, entities=(replace(line, end_mm=(6, 0)),))
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
    assert calls == 1
    rebuilt = app.drawing_collection_snapshot(services)
    assert rebuilt.groups == exploded.groups and rebuilt.block_instances == exploded.block_instances
    assert (
        rebuilt.block_definitions == exploded.block_definitions and rebuilt.texts == exploded.texts
    )
    assert (
        next(item for item in rebuilt.sketches if item.sketch_id == created_sketch.sketch_id)
        == created_sketch
    )
    path = tmp_path / "grouped-explode-rebuild.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert app.drawing_collection_snapshot(services) == rebuilt
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == exploded
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == exploded
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == rebuilt


@pytest.mark.parametrize("kind", ["legacy_polyline", "legacy_spline", "rotated_rectangle"])
def test_explode_assigns_point_ids_to_curves_without_source_ids(tmp_path: Path, kind: str) -> None:
    from typing import cast

    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.sketch import PolylineEntity, RectangleEntity, SketchEntity, SplineEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    member: SketchEntity
    if kind == "legacy_polyline":
        member = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)))
    elif kind == "legacy_spline":
        member = SplineEntity(uuid4().hex, ((0, 0), (1, 0), (2, 1), (3, 1)))
    else:
        member = RectangleEntity(uuid4().hex, (0, 0), (2, 1))
    definition = BlockDefinition(uuid4().hex, "Curve", (member,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 5), 45, 2)
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    operation = prepare_block_explode(
        app.drawing_collection_snapshot(services), instance.instance_id
    )
    frozen = cast("list[dict[str, object]]", operation.params["geometry_ids"])[0]
    point_ids = cast("list[str]", frozen["point_ids"])
    assert len(point_ids) == (3 if kind == "legacy_polyline" else 4)
    assert len(set(point_ids)) == len(point_ids)
    loaded.bus.execute(operation.command_id, operation.params, "local", version=1)
    exploded = services.kernel.sketches[-1].entities[0]
    assert isinstance(exploded, PolylineEntity | SplineEntity)
    assert exploded.point_ids == tuple(point_ids)
    path = tmp_path / f"{kind}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches[-1].entities == (exploded,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_instances == (instance,)
    reopened.bus.redo_operation()
    assert services.kernel.sketches[-1].entities == (exploded,)


def test_older_explode_with_missing_curve_point_ids_remains_replayable(tmp_path: Path) -> None:
    from copy import deepcopy
    from typing import cast

    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.sketch import PolylineEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    curve = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)))
    definition = BlockDefinition(uuid4().hex, "Legacy", (curve,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    operation = prepare_block_explode(
        app.drawing_collection_snapshot(services), instance.instance_id
    )
    old_params = deepcopy(operation.params)
    cast("list[dict[str, object]]", old_params["geometry_ids"])[0]["point_ids"] = []
    loaded.bus.execute(operation.command_id, old_params, "local", version=1)
    entity = services.kernel.sketches[-1].entities[0]
    assert isinstance(entity, PolylineEntity) and not entity.point_ids
    path = tmp_path / "old-explode.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.sketches[-1].entities == (entity,)


def test_explode_command_cannot_be_nested_or_carry_arbitrary_operations() -> None:
    from mycad.core.drawing_block_transactions import prepare_block_explode

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(
        uuid4().hex, "Guard", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    operation = prepare_block_explode(
        app.drawing_collection_snapshot(services), instance.instance_id
    )
    history = tuple(loaded.document.commands)
    before = app.drawing_collection_snapshot(services)
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.objects.batch",
            {
                "operations": [
                    {"id": operation.command_id, "version": 1, "params": operation.params}
                ]
            },
            "local",
        )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            operation.command_id, {**operation.params, "operations": []}, "local", version=1
        )
    assert (
        tuple(loaded.document.commands) == history
        and app.drawing_collection_snapshot(services) == before
    )


@pytest.mark.parametrize("kind", ["part", "drawing"])
def test_explode_command_rejects_non_2d_documents(kind: str) -> None:
    services = app.build_app(discoverers=[])
    loaded = (
        app.new_document(services, document_type="part")
        if kind == "part"
        else app.new_workspace_document(services, kind="drawing")
    )
    params: dict[str, object] = {
        "instance_id": uuid4().hex,
        "source_digest": "0" * 64,
        "sketch_id": None,
        "geometry_ids": [],
        "text_ids": [],
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.block_instance.explode", params, "local", version=1)
    assert loaded.document.commands == ()


@pytest.mark.parametrize("operation", ["insert", "update", "definition", "insert_overflow"])
def test_block_rejects_unrenderable_instance_expansion_atomically(operation: str) -> None:
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    circle = CircleEntity(uuid4().hex, (2, 0), 1)
    definition = BlockDefinition(uuid4().hex, "Small", (circle,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), scale=1e-6)
    if operation not in {"insert", "insert_overflow"}:
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    before = tuple(loaded.document.commands)
    state = app.drawing_collection_snapshot(services)
    with pytest.raises(ValidationError):
        if operation in {"insert", "insert_overflow"}:
            bad = replace(instance, scale=1e308 if operation == "insert_overflow" else 1e-15)
            loaded.bus.execute("drawing.block_instance.insert", bad.to_mapping(), "local")
        elif operation == "update":
            bad = replace(instance, scale=1e-15)
            loaded.bus.execute("drawing.block_instance.update", bad.to_mapping(), "local")
        else:
            bad_definition = replace(definition, entities=(replace(circle, radius_mm=1e-7),))
            loaded.bus.execute("drawing.block.update", bad_definition.to_mapping(), "local")
    assert tuple(loaded.document.commands) == before
    assert app.drawing_collection_snapshot(services) == state


def test_text_style_change_rejects_unrenderable_block_atomically() -> None:
    from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    text = DrawingText(uuid4().hex, "Label", (0, 0))
    definition = BlockDefinition(uuid4().hex, "Text block", (), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), scale=2)
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    before = tuple(loaded.document.commands)
    state = app.drawing_collection_snapshot(services)
    styles = TextStyleTable((TextStyle(height_mm=1e308),), "standard")
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local")
    assert tuple(loaded.document.commands) == before
    assert app.drawing_collection_snapshot(services) == state


def test_far_offset_rectangle_block_insert_and_explode_survive_reopen(tmp_path: Path) -> None:
    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance, expand_block
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (1e9, 1e9), (1e9 + 1, 1e9 + 2))
    definition = BlockDefinition(uuid4().hex, "Far", (rectangle,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 7), 30)
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    expanded = expand_block(definition, instance, before.text_styles).entities[0]
    assert isinstance(expanded, PolylineEntity)
    operation = prepare_block_explode(before, instance.instance_id)
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    after = app.drawing_collection_snapshot(services)
    assert len(after.sketches) == 1 and len(after.sketches[0].entities) == 1
    exploded = after.sketches[0].entities[0]
    assert isinstance(exploded, PolylineEntity) and exploded.points_mm == expanded.points_mm
    assert after.groups[0].members == (
        DrawingObjectRef("geometry", exploded.entity_id, after.sketches[0].sketch_id),
    )
    path = tmp_path / "far-rectangle-block.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after
