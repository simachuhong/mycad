# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Display-only dimension text survives the real command and archive path."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.persistence import save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_created_dimension_text_replays_and_undoes(tmp_path: Path) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        text_override="宽 <> mm",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    assert loaded.document.commands[-1].version == 30
    assert services.kernel.sketches == (sketch,)
    target = tmp_path / "text.my2d"
    save_document(loaded.document, target)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, target)
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.undo()
    assert not reopened_services.kernel.sketches
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (sketch,)


@pytest.mark.parametrize("text_on_draft", [False, True])
def test_mixed_move_with_text_dimensions_replays(tmp_path: Path, text_on_draft: bool) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        text_override="尺寸 <>",
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), () if text_on_draft else (dim,))
    draft_line = LineEntity(uuid4().hex, (20, 0), (30, 0))
    draft_dim = replace(
        dim, references=(SketchGeometryReference(draft_line.entity_id, "geometry"),)
    )
    draft = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (draft_line,), (draft_dim,) if text_on_draft else ()
    )
    moved_saved = replace(saved, entities=(replace(line, start_mm=(2, 3), end_mm=(12, 3)),))
    moved_draft = replace(draft, entities=(replace(draft_line, start_mm=(22, 3), end_mm=(32, 3)),))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    candidate = app.stage_mixed_drawing_timeline(
        services, loaded, draft, (saved,), (((moved_saved,), moved_draft),), session_identity=1
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert loaded.document.commands[-1].version == 48
    if text_on_draft:
        assert loaded.document.commands[-2].version == 30
    result = services.kernel.sketches
    path = tmp_path / "mixed-text.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches == result


def test_text_override_constraint_add_and_update_replay(tmp_path: Path) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        text_override="宽 <> mm",
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    for command, version, target in (
        ("sketch.constraint.add", 7, dimension),
        ("sketch.constraint.update", 5, replace(dimension, text_override="宽度 <> mm")),
    ):
        current = services.kernel.sketches[0]
        solve = (
            services.kernel.preview_sketch_constraint(current, target)
            if command.endswith("add")
            else services.kernel.preview_sketch_constraint_update(current, target)
        )
        assert solve.status == "success"
        candidate = app.create_replay_candidate(services, loaded, session_identity=1)
        candidate.stage(
            ReplayChangeSet(
                (),
                (
                    ReplayAppend(
                        command,
                        version,
                        solve.command_params(current, target, local_frame=True),
                        "local",
                    ),
                ),
                False,
                6 if loaded.document.archive_version < 6 else None,
            ),
            current_session_identity=1,
        )
        preview = candidate.preview(current_session_identity=1)
        assert preview.state == "succeeded", preview.failure
        candidate.commit(
            candidate.authorize_commit(current_session_identity=1), current_session_identity=1
        )
    result = services.kernel.sketches
    path = tmp_path / "edit-text.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == result
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0].constraints[0].text_override == "宽 <> mm"
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == result
