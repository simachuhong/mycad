# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Drawing styles follow command history, with isolated document state."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_drawing_styles_are_isolated_replayable_and_undoable(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    initial = services.kernel.drawing_dimension_styles
    styles = DimensionStyleTable(
        (DimensionStyle("标准", 2, 1), DimensionStyle("加工图", 3, 2)), "加工图"
    )
    loaded.bus.execute("drawing.dimension_styles.set", styles.to_mapping(), "local")
    assert services.kernel.drawing_dimension_styles == styles
    loaded.bus.undo()
    assert services.kernel.drawing_dimension_styles == initial
    loaded.bus.redo()
    target = tmp_path / "styles.my2d"
    save_document(loaded.document, target)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, target)
    assert reopened_services.kernel.drawing_dimension_styles == styles
    other = app.build_app(discoverers=())
    app.new_document(other, document_type="drawing2d")
    assert other.kernel.drawing_dimension_styles == initial
    reopened.bus.undo()
    assert reopened_services.kernel.drawing_dimension_styles == initial


def test_drawing_styles_reject_invalid_current_atomically() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    before = services.kernel.drawing_dimension_styles
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.dimension_styles.set",
            {"styles": [{"name": "A", "precision": 2, "scale": 1}], "current": "missing"},
            "local",
        )
    assert services.kernel.drawing_dimension_styles == before
    assert not loaded.document.commands


def test_drawing_styles_are_restricted_to_independent_drawings() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services)
    table = DimensionStyleTable((DimensionStyle("标准"),), "标准")
    with pytest.raises(ValidationError, match="独立二维"):
        loaded.bus.execute("drawing.dimension_styles.set", table.to_mapping(), "local")
    assert not loaded.document.commands


def test_style_update_changes_linked_dimensions_and_rejects_used_style_deletion(
    tmp_path: Path,
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    styles = DimensionStyleTable((DimensionStyle("标准"), DimensionStyle("加工图", 3, 2)), "加工图")
    loaded.bus.execute("drawing.dimension_styles.set", styles.to_mapping(), "local")
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    linked = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        precision=3,
        scale=2,
        text_override="宽 <> mm",
        style_name="加工图",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (linked,))
    loaded.bus.execute("sketch.create", sketch.to_state_mapping(), "local", version=32)
    edited = DimensionStyleTable((DimensionStyle("标准"), DimensionStyle("加工图", 1, 3)), "加工图")
    loaded.bus.execute("drawing.dimension_styles.set", edited.to_mapping(), "local")
    result = services.kernel.sketches[0].constraints[0]
    assert (result.precision, result.scale, result.style_name) == (1, 3, "加工图")
    assert result.value == 25 and result.driving and result.text_override == "宽 <> mm"
    count = loaded.document.command_count
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.dimension_styles.set",
            DimensionStyleTable((DimensionStyle("标准"),), "标准").to_mapping(),
            "local",
        )
    assert loaded.document.command_count == count
    assert services.kernel.sketches[0].constraints[0] == result
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)
    loaded.bus.redo()
    target = tmp_path / "linked-styles.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, target)
    assert reopened.kernel.sketches[0].constraints[0] == result


@pytest.mark.parametrize(("style_name", "precision"), [("不存在", 2), ("标准", 3)])
def test_create_rejects_missing_or_inconsistent_dimension_style(
    style_name: str, precision: int
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        style_name=style_name,
        precision=precision,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    with pytest.raises(ValidationError):
        loaded.bus.execute("sketch.create", sketch.to_state_mapping(), "local", version=32)
    assert not loaded.document.commands and not services.kernel.sketches


def test_mixed_move_preserves_dimension_style_reference(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        style_name="标准",
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    draft_line = LineEntity(uuid4().hex, (30, 0), (40, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (draft_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    assert loaded.document.commands[-1].version == 32
    moved_saved = replace(saved, entities=(replace(line, start_mm=(2, 3), end_mm=(27, 3)),))
    moved_draft = replace(draft, entities=(replace(draft_line, start_mm=(32, 3), end_mm=(42, 3)),))
    candidate = app.stage_mixed_drawing_timeline(
        services, loaded, draft, (saved,), (((moved_saved,), moved_draft),), session_identity=1
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert loaded.document.commands[-1].version == 50
    result = services.kernel.sketches
    target = tmp_path / "styled-move.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, target)
    assert reopened.kernel.sketches == result


def test_driving_dimension_regeneration_retains_named_style_history() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    original_table = DimensionStyleTable(
        (DimensionStyle("标准"), DimensionStyle("加工图", 3, 2)), "加工图"
    )
    loaded.bus.execute("drawing.dimension_styles.set", original_table.to_mapping(), "local")
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        style_name="加工图",
        precision=3,
        scale=2,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    changed_table = DimensionStyleTable(
        (DimensionStyle("标准"), DimensionStyle("加工图", 1, 3)), "加工图"
    )
    loaded.bus.execute("drawing.dimension_styles.set", changed_table.to_mapping(), "local")
    current = services.kernel.sketches[0]
    changed_dimension = replace(current.constraints[0], value=30)
    solve = services.kernel.preview_sketch_constraint_update(current, changed_dimension)
    assert solve.status == "success"
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet(
            (),
            (
                ReplayAppend(
                    "sketch.constraint.update",
                    6,
                    solve.command_params(current, changed_dimension, local_frame=True),
                    "local",
                ),
            ),
            False,
        ),
        current_session_identity=1,
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert services.kernel.drawing_dimension_styles == changed_table
    assert services.kernel.sketches[0].constraints[0].value == 30
    assert services.kernel.sketches[0].constraints[0].style_name == "加工图"
