# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Explicit dimension axes must replay and reject tampered solved geometry."""

import math
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    project_coplanar_entity,
    validate_tangency_component,
)
from mycad.core.persistence import save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    Sketch,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_create_with_projection_axis_replays_and_undoes(tmp_path: Path) -> None:
    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10 * q,
        "mm",
        axis="horizontal",
        projection_axis=(q, q),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet(
            (), (ReplayAppend("sketch.create", 28, sketch.to_state_mapping(), "local"),), False, 6
        ),
        current_session_identity=1,
    )
    result = candidate.preview(current_session_identity=1)
    assert result.state == "succeeded", result.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert services.kernel.sketches == (sketch,)
    path = tmp_path / "axis.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.undo()
    assert not reopened_services.kernel.sketches
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (sketch,)


def test_commit_curved_sketch_selects_projection_axis_version(tmp_path: Path) -> None:
    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    path = PolylineEntity(uuid4().hex, ((20, 0), (30, 0)), bulges=(0.5,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10 * q,
        "mm",
        axis="horizontal",
        projection_axis=(q, q),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, path), (dimension,))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    assert loaded.document.commands[-1].version == 28
    assert services.kernel.sketches == (sketch,)
    target = tmp_path / "axis-curved.my2d"
    save_document(loaded.document, target)
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, target)
    assert reopened_services.kernel.sketches == (sketch,)


def test_replayed_projection_constraint_rejects_tampered_solution(tmp_path: Path) -> None:
    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        axis="horizontal",
        projection_axis=(q, q),
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    solved = services.kernel.preview_sketch_constraint(sketch, dimension)
    assert solved.status == "success" and solved.sketch is not None
    params = solved.command_params(sketch, dimension, local_frame=True)
    tampered = deepcopy(params)
    entities = tampered["solution_entities"]
    assert isinstance(entities, list) and isinstance(entities[0], dict)
    entities[0]["end_mm"] = [100.0, 0.0]
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet(
            (), (ReplayAppend("sketch.constraint.add", 6, tampered, "local"),), False, 6
        ),
        current_session_identity=1,
    )
    assert candidate.preview(current_session_identity=1).state != "succeeded"
    assert services.kernel.sketches == (sketch,)
    candidate = app.create_replay_candidate(services, loaded, session_identity=1)
    candidate.stage(
        ReplayChangeSet((), (ReplayAppend("sketch.constraint.add", 6, params, "local"),), False, 6),
        current_session_identity=1,
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    accepted = services.kernel.sketches
    assert accepted[0].constraints == (dimension,)
    path = tmp_path / "axis-constraint.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == accepted
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == accepted


@pytest.mark.parametrize("engineering", [False, True])
def test_cross_sketch_dimension_selects_projection_version(
    tmp_path: Path, engineering: bool
) -> None:
    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10 * q,
        "mm",
        axis="horizontal",
        projection_axis=(q, q),
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    services = app.build_app(discoverers=())
    loaded = app.new_workspace_document(services, kind="drawing" if engineering else "sketch")
    if engineering:
        part_services = app.fork_app_services(services)
        part = app.new_workspace_document(part_services, kind="part")
        part.bus.execute("feature.box", {"size_x": 3, "size_y": 4, "size_z": 5}, "local")
        loaded.bus.execute("reference.attach", app.reference_parameters(part.document), "local")
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = services.kernel.sketches
    commands = loaded.document.commands
    revised = replace(dimension, value=8)
    params, _solved, _branches = app.prepare_cross_sketch_dimension(
        services, first.sketch_id, revised
    )
    _viewport, previews = app.preview_command_with_sketches(
        services,
        commands,
        "drawing.sketch.revise",
        params,
        source_archive_version=loaded.document.archive_version,
        source_document_type=loaded.document.document_type,
        source_document_kind=loaded.document.document_kind,
        source_drawing_fillet_baseline=loaded.document.drawing_fillet_baseline,
        source_drawing_chamfer_angle_baseline=loaded.document.drawing_chamfer_angle_baseline,
        command_version=31,
    )
    assert previews and loaded.document.commands == commands and services.kernel.sketches == before
    app.commit_cross_sketch_dimension(
        services, loaded, first.sketch_id, revised, session_identity=1
    )
    assert loaded.document.commands[-1].version == 31
    after = services.kernel.sketches
    path = tmp_path / "cross-axis.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == after


@pytest.mark.parametrize("opposite", [False, True])
def test_projected_dimension_on_endpoint_linked_arc_replays(tmp_path: Path, opposite: bool) -> None:
    q = math.sqrt(0.5)
    sign = -1 if opposite else 1
    frame = WorkPlaneFrame((5, 7, 0), (q, q, 0), (-sign * q, sign * q, 0), (0, 0, sign))
    line = project_coplanar_entity(
        LineEntity(uuid4().hex, (-10, 0), (0, 0)), WorkPlaneFrame.xy(), frame
    )
    arc = ArcEntity(uuid4().hex, (0, 2), 2, 270, 90)
    first = Sketch(uuid4().hex, frame, (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, arc.entity_id),
        "line_right" if opposite else "line_left",
        first_endpoint="end",
        second_endpoint="start",
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        8,
        "mm",
        axis="horizontal",
        projection_axis=(q, -sign * q),
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = services.kernel.sketches
    app.commit_cross_sketch_dimension(
        services, loaded, first.sketch_id, dimension, session_identity=1
    )
    assert loaded.document.commands[-1].version == 31
    after = services.kernel.sketches
    validate_tangency_component(after, services.kernel.cross_sketch_tangencies, first.sketch_id)
    path = tmp_path / "endpoint-axis.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after
    reopened_services = app.build_app(discoverers=())
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == after


@pytest.mark.parametrize("fixed_end", ["start", "end"])
def test_projected_tangent_dimension_preserves_fixed_endpoint_on_replay(
    tmp_path: Path, fixed_end: Literal["start", "end"]
) -> None:
    q = math.sqrt(0.5)
    frame = WorkPlaneFrame((5, 7, 0), (q, q, 0), (q, -q, 0), (0, 0, -1))
    line = project_coplanar_entity(
        LineEntity(uuid4().hex, (-10, 0), (10, 0)), WorkPlaneFrame.xy(), frame
    )
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, fixed_end),)
    )
    first = Sketch(uuid4().hex, frame, (line,), (fixed,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right",
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        15,
        "mm",
        axis="horizontal",
        projection_axis=(q, q),
    )
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = services.kernel.sketches
    app.commit_cross_sketch_dimension(
        services, loaded, first.sketch_id, dimension, session_identity=1
    )
    after = services.kernel.sketches
    updated = next(sketch for sketch in after if sketch.sketch_id == first.sketch_id)
    result = updated.entities[0]
    assert isinstance(result, LineEntity)
    assert getattr(result, f"{fixed_end}_mm") == pytest.approx(getattr(line, f"{fixed_end}_mm"))
    validate_tangency_component(after, services.kernel.cross_sketch_tangencies, first.sketch_id)
    path = tmp_path / "fixed-endpoint-axis.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches == after


@pytest.mark.parametrize("axis_on_draft", [False, True])
def test_mixed_timeline_selects_projection_revision_version(
    tmp_path: Path, axis_on_draft: bool
) -> None:
    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10 * q,
        "mm",
        axis="horizontal",
        projection_axis=(q, q),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), () if axis_on_draft else (dimension,))
    draft_line = LineEntity(uuid4().hex, (20, 0), (30, 0))
    draft_dimension = replace(
        dimension, references=(SketchGeometryReference(draft_line.entity_id, "geometry"),)
    )
    draft = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (draft_line,), (draft_dimension,) if axis_on_draft else ()
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
    assert loaded.document.commands[-1].version == 31
    if axis_on_draft:
        assert loaded.document.commands[-2].version == 28
    after = services.kernel.sketches
    path = tmp_path / "mixed-axis.my2d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    loaded.bus.undo()
    assert services.kernel.sketches == (saved,)
    loaded.bus.redo()
    loaded.bus.redo()
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches == after


def test_preview_projection_axis_from_old_archive_does_not_modify_document(tmp_path: Path) -> None:
    from mycad.core.document import Document

    q = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        8,
        "mm",
        axis="horizontal",
        projection_axis=(q, q),
    )
    services = app.build_app(discoverers=())
    legacy = Document(services.registry, archive_version=3, document_type="drawing2d")
    path = tmp_path / "legacy.my2d"
    save_document(legacy, path)
    loaded = app.open_app_document(services, path)
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    assert loaded.document.archive_version == 3
    before = tuple(loaded.document.commands)
    result = services.kernel.preview_sketch_constraint(sketch, dimension)
    assert result.status == "success"
    _viewport, previews = app.preview_command_with_sketches(
        services,
        before,
        "sketch.constraint.add",
        result.command_params(sketch, dimension, local_frame=True),
        source_archive_version=3,
        command_version=6,
        target_archive_version=6,
    )
    assert previews
    assert tuple(loaded.document.commands) == before
    assert loaded.document.archive_version == 3
    assert services.kernel.sketches == (sketch,)
