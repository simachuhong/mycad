# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Draft collections stage on isolated replay candidates."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
from mycad.core.drawing_text import DrawingText
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.replay_proposal import ReplayAppend
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.drawing_collection_session import DrawingCollectionSession


def test_collection_preview_payload_contains_changed_objects_and_dependent_dimensions() -> None:
    from mycad.core.drawing_collection_preview import collection_preview_payload
    from mycad.core.drawing_transactions import prepare_collection_translation
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (0, 8), (2, 8))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(first.entity_id, "geometry"),), 2, "mm"
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (dimension,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", first.entity_id, draft.sketch_id)
    operation = prepare_collection_translation(session.snapshot, (ref,), draft.frame, (0, 3))
    preview = session.preview_operation(operation)
    payload = collection_preview_payload(session.snapshot, preview)
    assert len(payload.sketches) == 1
    assert payload.sketches[0].entities == (replace(first, start_mm=(0, 3), end_mm=(2, 3)),)
    assert payload.sketches[0].constraints == (dimension,)
    assert payload.groups == () and payload.texts == ()
    assert session.snapshot.sketches[-1] == draft and loaded.document.commands == ()
    session.cancel()


def test_preview_operation_is_isolated_and_reuses_frozen_copy_identities() -> None:
    from mycad.core.drawing_transactions import prepare_collection_copy

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    session.guard_document_writes()
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    group = DrawingGroup(uuid4().hex, (ref,))
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    checkpoint, original = session.checkpoint(), session.snapshot
    operation = prepare_collection_copy(original, (ref,), draft.frame, (0, 3))
    preview = session.preview_operation(operation)
    assert len(preview.groups) == 2
    assert len(preview.sketches[-1].entities) == 2
    assert session.snapshot == original and session.checkpoint() == checkpoint
    assert loaded.document.commands == () and services.kernel.sketches == ()
    with pytest.raises(ValidationError):
        session.preview_operation(
            ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
        )
    assert session.snapshot == original and session.checkpoint() == checkpoint
    session.stage(operation)
    assert session.snapshot == preview
    session.cancel()


def test_empty_session_commit_does_not_persist_dummy_sketch() -> None:
    from mycad.core.exceptions import InvalidHistoryError

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    session.guard_document_writes()
    session.commit()
    assert loaded.document.commands == ()
    assert services.kernel.sketches == ()
    with pytest.raises(InvalidHistoryError, match="history has no commands"):
        loaded.bus.undo_operation()


def test_conflicting_group_rename_preserves_candidate_and_history() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    ref = DrawingObjectRef("geometry", line.entity_id, draft.sketch_id)
    first = DrawingGroup(uuid4().hex, (ref,), name="Alpha")
    second = DrawingGroup(uuid4().hex, (ref,), name="Beta")
    for group in (first, second):
        session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    checkpoint = session.checkpoint()
    with pytest.raises(ValidationError):
        session.stage(
            ReplayAppend(
                "drawing.group.update", 1, replace(second, name="alpha").to_mapping(), "local"
            )
        )
    assert session.snapshot.groups == (first, second)
    assert session.checkpoint() == checkpoint
    assert loaded.document.commands == ()
    session.cancel()


def test_empty_initial_draft_is_retained_when_later_steps_reference_it() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    saved_line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", saved_line.entity_id, saved.sketch_id),)
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    new_line = LineEntity(uuid4().hex, (0, 5), (2, 5))
    state = replace(draft, entities=(new_line,)).to_state_mapping()
    session.stage(
        ReplayAppend(
            "drawing.sketch.revise",
            79,
            {
                "revisions": [
                    {
                        "sketch_id": draft.sketch_id,
                        "base_state_sha256": draft.local_state_digest(),
                        "entities": state["entities"],
                        "constraints": state["constraints"],
                    }
                ]
            },
            "local",
        )
    )
    session.commit()
    assert services.kernel.sketches[-1].entities == (new_line,)
    loaded.bus.undo_operation()
    assert services.kernel.sketches[-1].entities == ()
    assert services.kernel.drawing_groups == (group,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_groups == ()


def test_empty_projection_commit_failure_preserves_candidate_and_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import Never

    from mycad.core.persistence import LoadedDocument

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    session.guard_document_writes()
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("geometry", line.entity_id, saved.sketch_id),)
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    before = loaded.document.commands
    original_factory = app.create_replay_candidate

    def fail_preview(**_kwargs: object) -> Never:
        raise ValidationError("故意模拟候选失败")

    def failing_factory(
        services: app.AppServices, document: LoadedDocument, *, session_identity: int
    ) -> app.ReplayCandidateSession:
        candidate = original_factory(services, document, session_identity=session_identity)
        monkeypatch.setattr(candidate, "preview", fail_preview)
        return candidate

    with monkeypatch.context() as patch:
        patch.setattr(app, "create_replay_candidate", failing_factory)
        with pytest.raises(ValidationError, match="故意模拟"):
            session.commit()
    assert loaded.document.commands == before
    assert session.snapshot.groups == (group,)
    with pytest.raises(ValidationError, match="暂存"):
        loaded.bus.undo_operation()
    session.commit()
    assert services.kernel.drawing_groups == (group,)
    assert services.kernel.sketches == (saved,)


def test_draft_group_timeline_undo_redo_commit_and_reopen(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    a = LineEntity(uuid4().hex, (0, 0), (1, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (a,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    b = LineEntity(uuid4().hex, (2, 0), (3, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (b,))
    draft_command = ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local")
    before = loaded.document.commands
    session = DrawingCollectionSession(services, loaded, draft_command, session_identity=1)
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", a.entity_id, saved.sketch_id),
            DrawingObjectRef("geometry", b.entity_id, draft.sketch_id),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    text = DrawingText(uuid4().hex, "A", (1, 2))
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    assert loaded.document.commands == before
    assert session.snapshot.groups == (group,)
    assert session.snapshot.texts == (text,)
    session.undo()
    assert session.snapshot.texts == ()
    assert session.snapshot.groups == (group,)
    session.redo()
    assert session.snapshot.texts == (text,)
    session.commit()
    assert services.kernel.drawing_groups == (group,)
    path = tmp_path / "timeline.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_texts == ()
    assert services.kernel.drawing_groups == (group,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == ()
    assert draft in services.kernel.sketches


@pytest.mark.parametrize("commit", [False, True])
def test_group_block_combined_timeline_cancel_or_reopen(tmp_path: Path, commit: bool) -> None:
    from mycad.core.drawing_block_transactions import prepare_block_create, prepare_block_explode
    from mycad.core.drawing_blocks import BlockInstance, expand_block
    from mycad.core.drawing_transactions import prepare_collection_copy
    from mycad.ui.drawing_block_editor import DrawingBlockEditorSession

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    a = LineEntity(uuid4().hex, (0, 0), (2, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (a,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    original = app.drawing_collection_snapshot(services)
    original_history = tuple(loaded.document.commands)
    b = LineEntity(uuid4().hex, (0, 2), (2, 2))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (b,))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=1,
    )
    refs = (
        DrawingObjectRef("geometry", a.entity_id, saved.sketch_id),
        DrawingObjectRef("geometry", b.entity_id, draft.sketch_id),
    )
    group = DrawingGroup(uuid4().hex, refs, name="Original")
    states = [session.snapshot]
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    states.append(session.snapshot)
    session.stage(prepare_collection_copy(session.snapshot, (refs[0],), saved.frame, (10, 0)))
    states.append(session.snapshot)
    session.stage(
        prepare_block_create(session.snapshot, (refs[0],), "Symbol", (0, 0), convert_sources=True)
    )
    states.append(session.snapshot)
    assert len(states[-1].groups) == 2 and len(states[-1].block_instances) == 1
    assert tuple(loaded.document.commands) == original_history
    for expected in reversed(states[:-1]):
        session.undo()
        assert session.snapshot == expected
    for expected in states[1:]:
        session.redo()
        assert session.snapshot == expected
    if not commit:
        session.cancel()
        assert tuple(loaded.document.commands) == original_history
        assert app.drawing_collection_snapshot(services) == original
        return
    session.commit()
    assert app.drawing_collection_snapshot(services) == states[-1]
    instance = states[-1].block_instances[0]
    definition = states[-1].block_definitions[0]
    second = BlockInstance(uuid4().hex, definition.definition_id, (20, 0), 30, 2)
    loaded.bus.execute("drawing.block_instance.insert", second.to_mapping(), "local")
    inserted = app.drawing_collection_snapshot(services)
    editor = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    member = definition.entities[0]
    assert isinstance(member, LineEntity)
    editor.set_members((replace(member, end_mm=(4, 0)), *definition.entities[1:]), definition.texts)
    editor.save()
    edited = app.drawing_collection_snapshot(services)
    assert len(edited.block_instances) == 2 and edited.block_definitions[0] != definition
    assert (
        expand_block(edited.block_definitions[0], instance, edited.text_styles).entities
        != expand_block(definition, instance, edited.text_styles).entities
    )
    assert (
        expand_block(edited.block_definitions[0], second, edited.text_styles).entities
        != expand_block(definition, second, edited.text_styles).entities
    )
    operation = prepare_block_explode(edited, instance.instance_id)
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    exploded = app.drawing_collection_snapshot(services)
    assert len(exploded.block_instances) == 1 and exploded.block_instances[0] == second
    path = tmp_path / "combined.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert app.drawing_collection_snapshot(services) == exploded
    expected_states = [*states, inserted, edited, exploded]
    for expected in reversed(expected_states[:-1]):
        reopened.bus.undo_operation()
        assert app.drawing_collection_snapshot(services) == expected
    for expected in expected_states[1:]:
        reopened.bus.redo_operation()
        assert app.drawing_collection_snapshot(services) == expected


def test_failed_stage_and_cancel_leave_source_unchanged() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (1, 0)),))
    before = loaded.document.commands
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    text = DrawingText(uuid4().hex, "ok", (0, 0))
    session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    with pytest.raises(ValidationError):
        session.stage(ReplayAppend("drawing.text.add", 1, text.to_mapping(), "local"))
    assert session.snapshot.texts == (text,)
    assert loaded.document.commands == before
    session.cancel()
    assert loaded.document.commands == before
    assert services.kernel.sketches == ()


def test_collection_session_rejects_switched_application_session() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (1, 0)),))
    active_session = [1]
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
        session_identity_provider=lambda: active_session[0],
    )
    active_session[0] = 2
    with pytest.raises(ValidationError, match="会话"):
        _ = session.snapshot
    with pytest.raises(ValidationError, match="会话"):
        session.commit()
    session.cancel()
    assert loaded.document.commands == ()


def test_collection_session_rejects_stale_document_without_losing_source() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (1, 0)),))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    revision = loaded.document.revision
    text = DrawingText(uuid4().hex, "external", (0, 0))
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    with pytest.raises(ValidationError, match="回滚"):
        session.rebind_after_failed_commit(revision, 1)
    with pytest.raises(ValidationError, match="回滚"):
        session.retry_failed_commit_recovery()
    with pytest.raises(ValidationError, match="变化"):
        session.undo()
    with pytest.raises(ValidationError, match="变化"):
        session.commit()
    session.cancel()
    assert services.kernel.drawing_texts == (text,)
    assert services.kernel.sketches == ()


def test_canvas_checkpoints_restore_collection_steps_and_discard_redo_branch() -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (1, 0)),))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    a = DrawingText(uuid4().hex, "first", (0, 0))
    b = DrawingText(uuid4().hex, "second", (1, 0))
    session.stage(ReplayAppend("drawing.text.add", 1, a.to_mapping(), "local"))
    checkpoint = session.checkpoint()
    session.stage(ReplayAppend("drawing.text.add", 1, b.to_mapping(), "local"))
    assert session.snapshot.texts == (a, b)
    session.restore(checkpoint)
    assert session.snapshot.texts == (a,)
    replacement = DrawingText(uuid4().hex, "branch", (2, 0))
    session.stage(ReplayAppend("drawing.text.add", 1, replacement.to_mapping(), "local"))
    with pytest.raises(ValidationError):
        session.redo()
    assert session.snapshot.texts == (a, replacement)
    assert services.kernel.drawing_texts == ()


def test_staged_mixed_group_move_and_copy_are_independent_history_steps(tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (5, 0), (7, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (second,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    before = loaded.document.commands
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", first.entity_id, saved.sketch_id),
            DrawingObjectRef("geometry", second.entity_id, draft.sketch_id),
        ),
    )
    session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
    moved_saved = replace(saved, entities=(replace(first, start_mm=(0, 3), end_mm=(2, 3)),))
    moved_draft = replace(draft, entities=(replace(second, start_mm=(5, 3), end_mm=(7, 3)),))

    def revision(old: Sketch, new: Sketch) -> dict[str, object]:
        state = new.to_state_mapping()
        return {
            "sketch_id": old.sketch_id,
            "base_state_sha256": old.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }

    session.stage(
        ReplayAppend(
            "drawing.sketch.revise",
            52,
            {"revisions": [revision(saved, moved_saved), revision(draft, moved_draft)]},
            "local",
        )
    )
    copy_a = replace(first, entity_id=uuid4().hex, start_mm=(0, 6), end_mm=(2, 6))
    copy_b = replace(second, entity_id=uuid4().hex, start_mm=(5, 6), end_mm=(7, 6))
    copied_saved = replace(moved_saved, entities=(*moved_saved.entities, copy_a))
    copied_draft = replace(moved_draft, entities=(*moved_draft.entities, copy_b))
    copy_group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", copy_a.entity_id, saved.sketch_id),
            DrawingObjectRef("geometry", copy_b.entity_id, draft.sketch_id),
        ),
    )
    session.stage(
        ReplayAppend(
            "drawing.objects.batch",
            1,
            {
                "operations": [
                    {
                        "id": "drawing.sketch.revise",
                        "version": 52,
                        "params": {
                            "revisions": [
                                revision(moved_saved, copied_saved),
                                revision(moved_draft, copied_draft),
                            ]
                        },
                    },
                    {"id": "drawing.group.create", "version": 1, "params": copy_group.to_mapping()},
                ]
            },
            "local",
        )
    )
    assert loaded.document.commands == before
    assert session.snapshot.groups == (group, copy_group)
    session.undo()
    assert session.snapshot.sketches == (moved_saved, moved_draft)
    session.undo()
    assert session.snapshot.sketches == (saved, draft)
    session.redo()
    session.redo()
    assert session.snapshot.groups == (group, copy_group)
    session.commit()
    path = tmp_path / "mixed-group.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (moved_saved, moved_draft)
    assert services.kernel.drawing_groups == (group,)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (saved, draft)


def test_collection_snapshot_exposes_existing_associative_arrays() -> None:
    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (5, 0), (7, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    source = ArrayEntityRef(saved.sketch_id, first.entity_id)
    target = ArrayEntityRef(saved.sketch_id, second.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, saved.frame, 1, 2, 0, 5, (source,), (ArrayMember(source, target, 0, 1),)
    )
    app.commit_new_sketch(services, loaded, saved, session_identity=1, associative_arrays=(array,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 2), (2, 2)),))
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
    )
    assert session.snapshot.associative_arrays == (array,)
    assert session.snapshot.cross_tangencies == ()
    from mycad.core.drawing_transactions import prepare_simple_collection_move

    independent = DrawingObjectRef("geometry", draft.entities[0].entity_id, draft.sketch_id)
    operation = prepare_simple_collection_move(
        session.snapshot, (independent,), draft.frame, (0, 1)
    )
    session.stage(operation)
    with pytest.raises(ValidationError, match="阵列"):
        prepare_simple_collection_move(
            session.snapshot,
            (DrawingObjectRef("geometry", first.entity_id, saved.sketch_id),),
            draft.frame,
            (0, 1),
        )
    session.cancel()


def test_collection_rebind_rejects_wrong_or_changed_source() -> None:
    from dataclasses import replace

    from mycad.core.drawing_text import DrawingText

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (0, 0), (1, 0)),))
    active_session = [1]
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 3, draft.to_mapping(version=3), "local"),
        session_identity=1,
        session_identity_provider=lambda: active_session[0],
    )
    active_session[0] = 2
    with pytest.raises(ValidationError, match="文档"):
        session.rebind_workspace(services, replace(loaded), 2)
    text = DrawingText(uuid4().hex, "new", (0, 0))
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="变化"):
        session.rebind_workspace(services, loaded, 2)
    assert loaded.document.commands == before
    assert services.kernel.drawing_texts == (text,)
    session.cancel()
