# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Drawing group commands are replayable and validate member identities."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
from mycad.core.drawing_text import DrawingText
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame


def test_group_commands_replay_and_reject_missing_members(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    text = DrawingText(uuid4().hex, "A", (1, 2))
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("text", text.text_id),), name="A")
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    updated = replace(group, description="detail")
    loaded.bus.execute("drawing.group.update", updated.to_mapping(), "local")
    path = tmp_path / "group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups == (updated,)
    reopened.bus.undo()
    assert services.kernel.drawing_groups == (group,)
    reopened.bus.redo()
    reopened.bus.execute("drawing.group.remove", {"group_id": group.group_id}, "local")
    assert services.kernel.drawing_groups == ()
    with pytest.raises(ValidationError):
        reopened.bus.execute(
            "drawing.group.create",
            DrawingGroup(uuid4().hex, (DrawingObjectRef("text", uuid4().hex),)).to_mapping(),
            "local",
        )
    assert services.kernel.drawing_groups == ()


def test_group_create_rejects_uuid_alias_without_rewriting_existing_id(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    text = DrawingText(uuid4().hex, "A", (1, 2))
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    identity = uuid4()
    group = DrawingGroup(str(identity), (DrawingObjectRef("text", text.text_id),))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    before = tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="identity"):
        loaded.bus.execute(
            "drawing.group.create", replace(group, group_id=identity.hex).to_mapping(), "local"
        )
    assert tuple(loaded.document.commands) == before
    assert services.kernel.drawing_groups == (group,)
    path = tmp_path / "group-identity.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups == (group,)
    reopened.bus.undo()
    assert services.kernel.drawing_groups == ()
    reopened.bus.redo()
    assert services.kernel.drawing_groups == (group,)


@pytest.mark.parametrize("kind", ["part", "drawing"])
def test_groups_are_only_available_in_independent_sketch(kind: str) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="part")
    if kind == "drawing":
        loaded = app.new_workspace_document(services, kind="drawing")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("text", uuid4().hex),))
    with pytest.raises(ValidationError, match="二维组.*独立二维草图"):
        loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")


@pytest.mark.parametrize("kind", ["part", "drawing"])
def test_collection_batch_reports_its_document_restriction(kind: str) -> None:
    services = app.build_app(discoverers=[])
    loaded = (
        app.new_document(services, document_type="part")
        if kind == "part"
        else app.new_workspace_document(services, kind="drawing")
    )
    before = tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="二维对象组合操作.*独立二维草图"):
        loaded.bus.execute("drawing.objects.batch", {"operations": []}, "local")
    assert tuple(loaded.document.commands) == before


def test_deleting_member_cleans_group_and_undo_restores_it() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    text = DrawingText(uuid4().hex, "A", (1, 2))
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("text", text.text_id),))
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    loaded.bus.execute("drawing.text.remove", {"text_id": text.text_id}, "local")
    assert services.kernel.drawing_groups == ()
    loaded.bus.undo()
    assert services.kernel.drawing_groups == (group,)


def test_array_sources_and_members_cannot_be_grouped() -> None:
    from mycad.core.drawing_object_refs import validate_new_group_array_members

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (5, 0), (7, 0))
    other = LineEntity(uuid4().hex, (0, 5), (2, 5))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second, other))
    source = ArrayEntityRef(sketch.sketch_id, first.entity_id)
    target = ArrayEntityRef(sketch.sketch_id, second.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (source,), (ArrayMember(source, target, 0, 1),)
    )
    validate_new_group_array_members(
        (DrawingObjectRef("geometry", first.entity_id, uuid4().hex),), (array,)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1, associative_arrays=(array,))
    existing = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", other.entity_id, sketch.sketch_id),)
    )
    loaded.bus.execute("drawing.group.create", existing.to_mapping(), "local")
    before, history = app.drawing_collection_snapshot(services), tuple(loaded.document.commands)
    for entity in (first, second):
        group = DrawingGroup(
            uuid4().hex, (DrawingObjectRef("geometry", entity.entity_id, sketch.sketch_id),)
        )
        with pytest.raises(ValidationError, match="阵列"):
            loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
        with pytest.raises(ValidationError, match="阵列"):
            loaded.bus.execute(
                "drawing.group.update",
                replace(existing, members=(*existing.members, *group.members)).to_mapping(),
                "local",
            )
        assert app.drawing_collection_snapshot(services) == before
        assert tuple(loaded.document.commands) == history


@pytest.mark.parametrize("grouped", ["source", "member"])
def test_adding_array_after_group_is_rejected_atomically(grouped: str) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (5, 0), (7, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    selected = first if grouped == "source" else second
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", selected.entity_id, sketch.sketch_id),)
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    origin = ArrayEntityRef(sketch.sketch_id, first.entity_id)
    target = ArrayEntityRef(sketch.sketch_id, second.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 5, (origin,), (ArrayMember(origin, target, 0, 1),)
    )
    before, history = app.drawing_collection_snapshot(services), tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="阵列"):
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    assert app.drawing_collection_snapshot(services) == before
    assert tuple(loaded.document.commands) == history
    loaded.bus.execute("drawing.group.remove", {"group_id": group.group_id}, "local")
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    assert services.kernel.associative_arrays == (array,)


@pytest.mark.parametrize("array_first", [False, True])
def test_array_replacement_source_cannot_be_grouped(array_first: bool) -> None:
    from mycad.core.associative_array import ArrayReplacement
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = CircleEntity(uuid4().hex, (5, 0), 2)
    replacement = CircleEntity(uuid4().hex, (20, 4), 2)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target, replacement))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    first, second, replacement_ref = (
        ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in sketch.entities
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (first,),
        (ArrayMember(first, second, 0, 1, replacement=ArrayReplacement(replacement_ref)),),
    )
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", replacement.entity_id, sketch.sketch_id),)
    )
    if array_first:
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
        from mycad.core.drawing_object_refs import validate_new_group_array_members

        with pytest.raises(ValidationError, match="阵列"):
            validate_new_group_array_members(group.members, (array,))
        command, params = "drawing.group.create", group.to_mapping()
    else:
        loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
        command, params = "drawing.array.add", {"array": array.to_mapping()}
    before, history = app.drawing_collection_snapshot(services), tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="阵列"):
        loaded.bus.execute(command, params, "local")
    assert app.drawing_collection_snapshot(services) == before
    assert tuple(loaded.document.commands) == history


@pytest.mark.parametrize("array_first", [False, True])
def test_array_extra_output_source_cannot_be_grouped(array_first: bool) -> None:
    from mycad.core.associative_array import ArrayExtraOutput

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    lines = tuple(
        LineEntity(uuid4().hex, (x, y), (x + 2, y)) for x, y in ((0, 0), (5, 0), (20, 20), (3, -3))
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    refs = tuple(ArrayEntityRef(sketch.sketch_id, line.entity_id) for line in lines)
    output = ArrayExtraOutput(refs[2], refs[3], refs[0], 0, 1, (2, 3))
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (refs[0],),
        (ArrayMember(refs[0], refs[1], 0, 1),),
        extra_outputs=(output,),
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", lines[2].entity_id, sketch.sketch_id),)
    )
    if array_first:
        loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
        from mycad.core.drawing_object_refs import validate_new_group_array_members

        with pytest.raises(ValidationError, match="阵列"):
            validate_new_group_array_members(group.members, (array,))
        command, params = "drawing.group.create", group.to_mapping()
    else:
        loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
        command, params = "drawing.array.add", {"array": array.to_mapping()}
    before, history = app.drawing_collection_snapshot(services), tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="阵列"):
        loaded.bus.execute(command, params, "local")
    assert app.drawing_collection_snapshot(services) == before
    assert tuple(loaded.document.commands) == history


def test_legacy_array_replacement_group_reopens_but_new_conflicts_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.associative_array import ArrayReplacement
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.core.sketch import CircleEntity
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    source = LineEntity(uuid4().hex, (0, 0), (2, 0))
    target = CircleEntity(uuid4().hex, (5, 0), 2)
    replacement = CircleEntity(uuid4().hex, (20, 4), 2)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, target, replacement))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    first, second, replacement_ref = (
        ArrayEntityRef(sketch.sketch_id, item.entity_id) for item in sketch.entities
    )
    array = AssociativeRectArray(
        uuid4().hex,
        sketch.frame,
        1,
        2,
        0,
        5,
        (first,),
        (ArrayMember(first, second, 0, 1, replacement=ArrayReplacement(replacement_ref)),),
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    ref = DrawingObjectRef("geometry", replacement.entity_id, sketch.sketch_id)
    old_group = DrawingGroup(uuid4().hex, (ref,))

    def old_admission(_before: frozenset[tuple[str, str, str, str]]) -> None:
        pass

    with monkeypatch.context() as patch:
        patch.setattr(loaded.bus, "_guard_new_group_array_conflicts", old_admission)
        loaded.bus.execute("drawing.group.create", old_group.to_mapping(), "local")
    path = tmp_path / "legacy-array-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_groups == (old_group,)
    text = DrawingText(uuid4().hex, "Independent", (0, 20))
    reopened.bus.execute("drawing.text.add", text.to_mapping(), "local")
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        reopened,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    checkpoint = session.checkpoint()
    with pytest.raises(ValidationError, match="阵列"):
        session.stage(
            ReplayAppend(
                "drawing.group.create", 1, DrawingGroup(uuid4().hex, (ref,)).to_mapping(), "local"
            )
        )
    assert session.checkpoint() == checkpoint and session.snapshot.groups == (old_group,)
    session.cancel()


def test_group_survives_optimized_sketch_rebuild() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),)
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    moved = replace(sketch, entities=(replace(line, start_mm=(1, 0), end_mm=(3, 0)),))
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
    assert services.kernel.drawing_groups == (group,)
    loaded.bus.undo()
    assert services.kernel.drawing_groups == (group,)
    loaded.bus.redo()
    assert services.kernel.drawing_groups == (group,)
