# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A drawing sketch revision must replay and undo like other document commands."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import LineEntity, PointEntity, Sketch, WorkPlaneFrame


def test_drawing_sketch_revision_can_be_committed_undone_and_redone() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    moved = replace(line, start_mm=(2.0, 3.0), end_mm=(12.0, 3.0))
    updated = replace(sketch, entities=(moved,))
    frozen = updated.to_mapping(version=3)
    params = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": sketch.local_state_digest(),
        "entities": frozen["entities"],
        "constraints": frozen["constraints"],
    }
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet((), (ReplayAppend("sketch.revise", 1, params, "local"),), False, 6),
        current_session_identity=1,
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert services.kernel.sketches[0].entities == (moved,)
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == (line,)
    loaded.bus.redo()
    assert services.kernel.sketches[0].entities == (moved,)


def test_revision_can_remove_every_entity_and_reopen_undo(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), confirmed_by="local")
    params: dict[str, object] = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": sketch.local_state_digest(),
        "entities": [],
        "constraints": [],
    }
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet((), (ReplayAppend("sketch.revise", 1, params, "local"),), False, 6),
        current_session_identity=1,
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert services.kernel.sketches[0].entities == ()
    path = tmp_path / "empty-sketch.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == ()
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0].entities == (line,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches[0].entities == ()


def test_multi_sketch_revision_failure_preserves_all_sources() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    sketches = tuple(
        Sketch(
            uuid4().hex,
            WorkPlaneFrame.xy(),
            (LineEntity(uuid4().hex, (0.0, y), (10.0, y)),),
        )
        for y in (0.0, 10.0)
    )
    for sketch in sketches:
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    revisions: list[dict[str, object]] = []
    for index, sketch in enumerate(sketches):
        line = sketch.entities[0]
        assert isinstance(line, LineEntity)
        moved = replace(line, start_mm=(2.0, line.start_mm[1]), end_mm=(12.0, line.end_mm[1]))
        frozen = replace(sketch, entities=(moved,)).to_mapping(version=3)
        revisions.append(
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest() if index == 0 else "0" * 64,
                "entities": frozen["entities"],
                "constraints": frozen["constraints"],
            }
        )
    before = loaded.document.commands
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("drawing.sketch.revise", 1, {"revisions": revisions}, "local"),),
            False,
            6,
        ),
        current_session_identity=1,
    )
    assert candidate.preview(current_session_identity=1).state == "failed"
    assert services.kernel.sketches == sketches
    assert loaded.document.commands == before
    upgrade = app.create_replay_candidate(services, loaded, session_identity=1)
    upgrade.stage(ReplayChangeSet((), (), False, 6), current_session_identity=1)
    assert upgrade.preview(current_session_identity=1).state == "succeeded"
    upgrade.commit(upgrade.authorize_commit(current_session_identity=1), current_session_identity=1)
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="stale"):
        loaded.bus.execute("drawing.sketch.revise", {"revisions": revisions}, confirmed_by="local")
    assert services.kernel.sketches == sketches
    assert loaded.document.commands == before


def test_staged_mixed_move_replays_and_undoes_after_reopen(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    saved_line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    draft_line = LineEntity(uuid4().hex, (20.0, 0.0), (30.0, 0.0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (draft_line,))
    loaded.bus.execute("sketch.create", saved.to_mapping(version=3), confirmed_by="local")
    revisions: list[dict[str, object]] = []
    for sketch, line in ((saved, saved_line), (draft, draft_line)):
        moved = replace(
            line,
            start_mm=(line.start_mm[0] + 2.0, 3.0),
            end_mm=(line.end_mm[0] + 2.0, 3.0),
        )
        data = replace(sketch, entities=(moved,)).to_state_mapping()
        revisions.append(
            {
                "sketch_id": sketch.sketch_id,
                "base_state_sha256": sketch.local_state_digest(),
                "entities": data["entities"],
                "constraints": data["constraints"],
            }
        )
    candidate = app.stage_mixed_drawing_move(services, loaded, draft, revisions, session_identity=1)
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    path = tmp_path / "mixed.mc.json"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (saved, draft)


def test_staged_mixed_move_requires_exactly_one_draft_revision() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    before = loaded.document.commands
    with pytest.raises(ValidationError, match="草稿"):
        app.stage_mixed_drawing_move(services, loaded, draft, (), session_identity=1)
    assert loaded.document.commands == before


def test_staged_mixed_move_supports_draft_points() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    point = PointEntity(uuid4().hex, (20.0, 10.0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (point,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), confirmed_by="local")
    moved_saved = replace(saved, entities=(replace(line, start_mm=(2.0, 3.0), end_mm=(12.0, 3.0)),))
    moved_draft = replace(draft, entities=(replace(point, position_mm=(22.0, 13.0)),))
    candidate = app.stage_mixed_drawing_timeline(
        services, loaded, draft, (saved,), (((moved_saved,), moved_draft),), session_identity=1
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert services.kernel.sketches == (moved_saved, moved_draft)
    loaded.bus.undo()
    assert services.kernel.sketches == (saved, draft)


def test_staged_mixed_move_keeps_followup_edit_as_separate_undo(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    saved_line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    draft_line = LineEntity(uuid4().hex, (20.0, 0.0), (30.0, 0.0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (draft_line,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), confirmed_by="local")

    moved_saved = replace(
        saved, entities=(replace(saved_line, start_mm=(2.0, 3.0), end_mm=(12.0, 3.0)),)
    )
    moved_draft = replace(
        draft, entities=(replace(draft_line, start_mm=(22.0, 3.0), end_mm=(32.0, 3.0)),)
    )
    added = LineEntity(uuid4().hex, (50.0, 0.0), (60.0, 0.0))
    final_draft = replace(moved_draft, entities=(*moved_draft.entities, added))
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((moved_saved,), moved_draft), ((moved_saved,), final_draft)),
        session_identity=1,
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    path = tmp_path / "timeline.mc.json"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (moved_saved, moved_draft)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (saved, draft)
