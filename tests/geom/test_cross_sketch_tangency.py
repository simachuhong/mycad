# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Disposable cross-sketch solver previews."""

import math
from dataclasses import replace
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    validate_tangency_component,
)
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    Sketch,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_two_sketch_solver_proposes_valid_tangency_without_mutating_sources() -> None:
    from mycad.geom.cross_sketch_tangency import solve_unconstrained_tangency

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    solved = solve_unconstrained_tangency((first, second), relation)
    validate_tangency_component(solved, (relation,), first.sketch_id)
    assert first.entities == (line,) and second.entities == (circle,)
    assert {item.sketch_id for item in solved} == {first.sketch_id, second.sketch_id}


def test_solver_preserves_unrelated_unconstrained_geometry() -> None:
    from mycad.geom.cross_sketch_tangency import solve_unconstrained_tangency

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    extra = CircleEntity(uuid4().hex, (10, 10), 1)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, extra))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    result = solve_unconstrained_tangency((first, second), relation)
    updated_first = next(sketch for sketch in result if sketch.sketch_id == first.sketch_id)
    assert extra in updated_first.entities
    validate_tangency_component(result, (relation,), first.sketch_id)


def test_solver_rejects_existing_constraints_until_supported() -> None:
    from mycad.geom.cross_sketch_tangency import solve_unconstrained_tangency

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (fixed,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    with pytest.raises(ValueError, match="已有约束"):
        solve_unconstrained_tangency((first, second), relation)


def test_solver_handles_connected_relations_as_one_component() -> None:
    from mycad.geom.cross_sketch_tangency import solve_unconstrained_component

    bottom = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    top = LineEntity(uuid4().hex, (-10, 6), (10, 6))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    lower_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (bottom,))
    upper_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (top,))
    circle_sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relations = (
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(lower_sketch.sketch_id, bottom.entity_id),
            CrossSketchRef(circle_sketch.sketch_id, circle.entity_id),
            "line_left",
        ),
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(upper_sketch.sketch_id, top.entity_id),
            CrossSketchRef(circle_sketch.sketch_id, circle.entity_id),
            "line_right",
        ),
    )
    inputs = (lower_sketch, circle_sketch, upper_sketch)
    result = solve_unconstrained_component(inputs, relations, lower_sketch.sketch_id)
    assert len(result) == 3
    validate_tangency_component(result, relations, lower_sketch.sketch_id)
    assert lower_sketch.entities == (bottom,) and upper_sketch.entities == (top,)


def test_solver_preserves_existing_fixed_horizontal_and_radius_constraints() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    horizontal = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(line.entity_id, "geometry"),)
    )
    radius = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 2, "mm"
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (fixed, horizontal))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (radius,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    result = solve_tangency_component((first, second), (relation,), first.sketch_id)
    validate_tangency_component(result, (relation,), first.sketch_id)
    solved_first = next(sketch for sketch in result if sketch.sketch_id == first.sketch_id)
    solved_second = next(sketch for sketch in result if sketch.sketch_id == second.sketch_id)
    solved_line, solved_circle = solved_first.entities[0], solved_second.entities[0]
    assert isinstance(solved_line, LineEntity) and isinstance(solved_circle, CircleEntity)
    assert solved_line.start_mm == pytest.approx(line.start_mm)
    assert solved_line.start_mm[1] == pytest.approx(solved_line.end_mm[1])
    assert solved_circle.radius_mm == pytest.approx(2)
    assert (
        solved_first.constraints == first.constraints
        and solved_second.constraints == second.constraints
    )


def test_cross_sketch_solver_keeps_unrelated_curved_polyline_with_local_constraint() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    curved = PolylineEntity(uuid4().hex, ((20, 0), (22, 0), (22, 2)), bulges=(1, 0))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, curved), (fixed,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    solved = solve_tangency_component((first, second), (relation,), first.sketch_id)
    validate_tangency_component(solved, (relation,), first.sketch_id)
    updated = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id)
    assert updated.entities[1] == curved
    assert updated.constraints == (fixed,)


def test_cross_sketch_solver_refreshes_unrelated_reference_dimension() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    curved = PolylineEntity(uuid4().hex, ((20, 0), (22, 0), (22, 2)), bulges=(1, 0))
    reference = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        False,
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, curved), (reference,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    solved = solve_tangency_component((first, second), (relation,), first.sketch_id)
    updated = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id)
    assert updated.entities[1] == curved
    solved_line = updated.entities[0]
    assert isinstance(solved_line, LineEntity)
    assert updated.constraints[0].value == pytest.approx(
        math.dist(solved_line.start_mm, solved_line.end_mm)
    )


@pytest.mark.parametrize("flipped", (False, True))
def test_cross_sketch_tangency_solves_linked_curved_polyline_vertices(
    tmp_path: Path, flipped: bool
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    curved = PolylineEntity(uuid4().hex, ((-15, 0), (-10, 0), (-10, 3)), bulges=(1, 0))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(curved.entity_id, "vertex", 0),)
    )
    joined = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(curved.entity_id, "vertex", 1),
            SketchGeometryReference(line.entity_id, "start"),
        ),
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, curved), (fixed, joined))
    frame = (
        WorkPlaneFrame((0, 0, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if flipped
        else WorkPlaneFrame.xy()
    )
    second = Sketch(uuid4().hex, frame, (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    solved = solve_tangency_component((first, second), (relation,), second.sketch_id)
    validate_tangency_component(solved, (relation,), first.sketch_id)
    updated = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id)
    moved_line, moved_curve = updated.entities
    assert isinstance(moved_line, LineEntity) and isinstance(moved_curve, PolylineEntity)
    assert moved_curve.points_mm[0] == pytest.approx(curved.points_mm[0])
    assert moved_curve.points_mm[1] == pytest.approx(moved_line.start_mm)
    assert moved_curve.bulges == curved.bulges
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    before = services.kernel.sketches
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    linked = services.kernel.sketches
    original, dragged, anchors = app.prepare_cross_sketch_drag(
        services, first.sketch_id, SketchGeometryReference(curved.entity_id, "vertex", 1), (-9, 1)
    )
    app.commit_cross_sketch_drag(services, loaded, original, dragged, anchors, session_identity=1)
    after = services.kernel.sketches
    updated = next(item for item in after if item.sketch_id == first.sketch_id)
    moved_line, moved_curve = updated.entities
    assert isinstance(moved_line, LineEntity) and isinstance(moved_curve, PolylineEntity)
    assert moved_curve.points_mm[1] == pytest.approx((-9, 1))
    assert moved_line.start_mm == pytest.approx(moved_curve.points_mm[1])
    validate_tangency_component(after, (relation,), first.sketch_id)
    path = tmp_path / "curved-vertex-cross.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == linked
    reopened.bus.undo()
    assert services.kernel.sketches == before
    reopened.bus.redo()
    assert services.kernel.sketches == linked
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("case", ("external_circle", "internal_circle", "external_polyline"))
def test_cross_sketch_polyline_arc_relations_preserve_finite_branch(case: str) -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curved,))
    if case == "external_polyline":
        other = PolylineEntity(uuid4().hex, ((3, -7), (7, -7), (7, -10)), bulges=(-1, 0))
        index = 0
    else:
        other = CircleEntity(uuid4().hex, (5, -3 if case == "internal_circle" else -7), 2)
        index = None
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, curved.entity_id, 0),
        CrossSketchRef(second.sketch_id, other.entity_id, index),
        "first_contains_second" if case == "internal_circle" else "external",
    )
    solved = solve_tangency_component((first, second), (relation,), first.sketch_id)
    validate_tangency_component(solved, (relation,), first.sketch_id)
    assert first.entities == (curved,) and second.entities == (other,)


def test_cross_sketch_straight_polyline_segment_tangent_to_arc() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    polyline = PolylineEntity(uuid4().hex, ((-5, -5), (15, -5), (15, -2)), bulges=(0, 0.5))
    arc = ArcEntity(uuid4().hex, (5, 0), 5, 180, 180)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, polyline.entity_id, 0),
        CrossSketchRef(second.sketch_id, arc.entity_id),
        "line_left",
    )
    solved = solve_tangency_component((first, second), (relation,), first.sketch_id)
    validate_tangency_component(solved, (relation,), first.sketch_id)
    updated = next(item for item in solved if item.sketch_id == first.sketch_id).entities[0]
    assert isinstance(updated, PolylineEntity)
    assert updated.bulges[0] == 0 and updated.bulges[1] == pytest.approx(0.5)


@pytest.mark.parametrize("flipped", (False, True))
def test_cross_sketch_polyline_arc_relation_commit_drag_and_replay(
    tmp_path: Path, flipped: bool
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, 6 if flipped else -6), (15, 6 if flipped else -6))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curved,))
    frame = (
        WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1))
        if flipped
        else WorkPlaneFrame.xy()
    )
    second = Sketch(uuid4().hex, frame, (line,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, curved.entity_id, 0),
        CrossSketchRef(second.sketch_id, line.entity_id),
        "line_right" if flipped else "line_left",
    )
    before = services.kernel.sketches
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    assert loaded.document.commands[-1].version == 3
    linked = services.kernel.sketches
    validate_tangency_component(linked, (relation,), first.sketch_id)
    owner = next(item for item in linked if item.sketch_id == first.sketch_id)
    original_arc = owner.entities[0]
    assert isinstance(original_arc, PolylineEntity)
    target = (original_arc.points_mm[1][0] + 1, original_arc.points_mm[1][1])
    original, solved, anchors = app.prepare_cross_sketch_drag(
        services, first.sketch_id, SketchGeometryReference(curved.entity_id, "vertex", 1), target
    )
    app.commit_cross_sketch_drag(services, loaded, original, solved, anchors, session_identity=1)
    after = services.kernel.sketches
    updated = next(item for item in after if item.sketch_id == first.sketch_id).entities[0]
    assert isinstance(updated, PolylineEntity)
    assert updated.points_mm[1] == pytest.approx(target)
    assert updated.bulges == original_arc.bulges
    validate_tangency_component(after, (relation,), first.sketch_id)
    path = tmp_path / "segment-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == (
        relation,
    )
    reopened.bus.undo()
    assert services.kernel.sketches == linked
    reopened.bus.undo()
    assert services.kernel.sketches == before and not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    reopened.bus.redo()
    assert services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == (
        relation,
    )


@pytest.mark.parametrize("curve_in_draft", (False, True))
def test_commit_draft_segment_cross_tangency_replays(tmp_path: Path, curve_in_draft: bool) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    saved_entity = line if curve_in_draft else curved
    draft_entity = curved if curve_in_draft else line
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_entity,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (draft_entity,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    source = SketchGeometryReference(
        saved_entity.entity_id,
        "geometry" if curve_in_draft else "segment",
        None if curve_in_draft else 0,
    )
    target = SketchGeometryReference(
        draft_entity.entity_id,
        "segment" if curve_in_draft else "geometry",
        0 if curve_in_draft else None,
    )
    app.commit_new_sketch(
        services, loaded, draft, session_identity=1, cross_tangent_pairs=((source, target),)
    )
    assert loaded.document.commands[-1].id == "sketch.create"
    assert loaded.document.commands[-1].version == 10
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == 1
    assert relations[0].first.segment_index == (None if curve_in_draft else 0)
    assert relations[0].second.segment_index == (0 if curve_in_draft else None)
    validate_tangency_component(services.kernel.sketches, relations, saved.sketch_id)
    after = services.kernel.sketches
    path = tmp_path / "draft-segment.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.sketches == (saved,) and not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


@pytest.mark.parametrize("initial", (False, True))
def test_mixed_timeline_commits_draft_segment_relation(initial: bool) -> None:
    from dataclasses import replace

    from mycad import app

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curved,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    pair = (
        SketchGeometryReference(curved.entity_id, "segment", 0),
        SketchGeometryReference(line.entity_id, "geometry"),
    )
    moved = replace(draft, entities=(replace(line, end_mm=(20, -5)),))
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((saved,), moved),),
        session_identity=1,
        initial_cross_pairs=(pair,) if initial else (),
        cross_pairs_by_step=((pair,),),
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert len(services.kernel.cross_sketch_tangencies) == 1
    assert loaded.document.commands[-1].version == (2 if initial else 5)
    after = services.kernel.sketches
    loaded.bus.undo()
    if initial:
        assert len(services.kernel.cross_sketch_tangencies) == 1
    else:
        assert not services.kernel.cross_sketch_tangencies
    loaded.bus.redo()
    assert services.kernel.sketches == after


def test_prepare_new_mixed_segment_tangency_is_disposable() -> None:
    from mycad import app

    services = app.build_app(discoverers=[])
    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -6), (15, -6))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curved,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(saved.sketch_id, curved.entity_id, 0),
        CrossSketchRef(draft.sketch_id, line.entity_id),
        "line_left",
    )
    solved_saved, solved_draft = app.prepare_mixed_draft_tangency(
        services, (saved,), draft, (), relation
    )
    validate_tangency_component((*solved_saved, solved_draft), (relation,), saved.sketch_id)
    assert saved.entities == (curved,) and draft.entities == (line,)
    assert services.kernel.sketches == ()


def test_mixed_segment_tangency_preserves_containment_when_draft_is_first() -> None:
    from mycad import app

    services = app.build_app(discoverers=[])
    circle = CircleEntity(uuid4().hex, (5, -3), 2)
    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curved,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(draft.sketch_id, curved.entity_id, 0),
        CrossSketchRef(saved.sketch_id, circle.entity_id),
        "first_contains_second",
    )
    solved_saved, solved_draft = app.prepare_mixed_draft_tangency(
        services, (saved,), draft, (), relation
    )
    pairs = ((circle.entity_id, SketchGeometryReference(curved.entity_id, "segment", 0)),)
    canonical = app.draft_cross_relations(solved_saved, solved_draft, pairs)
    assert len(canonical) == 1 and canonical[0].branch == "second_contains_first"
    validate_tangency_component((*solved_saved, solved_draft), canonical, saved.sketch_id)


@pytest.mark.parametrize("mode", ["changed", "ambiguous"])
def test_cross_sketch_segment_topology_change_is_rejected_without_relation_removal(
    mode: str,
) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curved,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, curved.entity_id, 0),
        CrossSketchRef(second.sketch_id, line.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = services.kernel.sketches
    source = next(item for item in before if item.sketch_id == first.sketch_id)
    entity = source.entities[0]
    assert isinstance(entity, PolylineEntity)
    altered = (
        replace(entity, points_mm=((0, 0), (5, -5), (10, 8), (15, 8)), bulges=(2**0.5 - 1, 0, 0))
        if mode == "changed"
        else replace(
            entity, points_mm=((0, 0), (10, 0), (0, 0), (10, 0), (10, 8)), bulges=(1, 0, 1, 0)
        )
    )
    state = replace(source, entities=(altered,)).to_state_mapping()
    revision = {
        "sketch_id": source.sketch_id,
        "base_state_sha256": source.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    history = tuple(loaded.document.commands)
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", {"revisions": [revision]}, "local", version=3)
    assert services.kernel.sketches == before and tuple(loaded.document.commands) == history
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.execute(
        "drawing.sketch.revise",
        {"revisions": [revision], "remove_tangencies": [relation.relation_id]},
        "local",
        version=3,
    )
    assert not services.kernel.cross_sketch_tangencies
    loaded.bus.undo()
    assert services.kernel.sketches == before and services.kernel.cross_sketch_tangencies == (
        relation,
    )


def test_cross_sketch_tangency_preserves_local_polyline_arc_tangency(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_arc_segment

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    curved = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)), bulges=(1, 0))
    circle = CircleEntity(uuid4().hex, (0, -3), 2)
    local = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(curved.entity_id, "segment", 0),
            SketchGeometryReference(line.entity_id, "geometry"),
        ),
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curved, line), (local,))
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
    original, solved, anchors = app.prepare_cross_sketch_drag(
        services, second.sketch_id, SketchGeometryReference(circle.entity_id, "center"), (0, -2)
    )
    app.commit_cross_sketch_drag(services, loaded, original, solved, anchors, session_identity=1)
    after = services.kernel.sketches
    updated = next(item for item in after if item.sketch_id == first.sketch_id)
    solved_arc, solved_line = updated.entities
    assert isinstance(solved_arc, PolylineEntity) and isinstance(solved_line, LineEntity)
    assert tangent_on_curves(solved_line, polyline_arc_segment(solved_arc, 0))
    validate_tangency_component(after, (relation,), first.sketch_id)
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(curved.entity_id, "segment", 0),), 6, "mm"
    )
    app.commit_cross_sketch_dimension(
        services, loaded, first.sketch_id, dimension, session_identity=1
    )
    dimensioned = services.kernel.sketches
    updated = next(item for item in dimensioned if item.sketch_id == first.sketch_id)
    solved_arc, solved_line = updated.entities
    assert isinstance(solved_arc, PolylineEntity) and isinstance(solved_line, LineEntity)
    assert polyline_arc_segment(solved_arc, 0).radius_mm == pytest.approx(6)
    assert tangent_on_curves(solved_line, polyline_arc_segment(solved_arc, 0))
    validate_tangency_component(dimensioned, (relation,), first.sketch_id)
    path = tmp_path / "polyline-local-cross.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == dimensioned
    reopened.bus.undo()
    assert services.kernel.sketches == after
    reopened.bus.redo()
    assert services.kernel.sketches == dimensioned


def test_cross_sketch_solver_rejects_constraints_on_curved_polyline() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    curved = PolylineEntity(uuid4().hex, ((20, 0), (22, 0), (22, 2)), bulges=(1, 0))
    unsupported = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(curved.entity_id, "segment", 0),)
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, curved), (unsupported,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    with pytest.raises(ValueError, match="不支持"):
        solve_tangency_component((first, second), (relation,), first.sketch_id)
    assert first.entities == (line, curved)


def test_cross_sketch_tangency_with_unrelated_curved_polyline_replays(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    curved = PolylineEntity(uuid4().hex, ((20, 0), (22, 0), (22, 2)), bulges=(1, 0))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, curved), (fixed,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    before = services.kernel.sketches
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    assert loaded.document.commands[-1].version == 2
    assert services.kernel.sketches[0].entities[1] == curved
    assert services.kernel.cross_sketch_tangencies == (relation,)
    path = tmp_path / "curved-cross-tangency.mc.json"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches[0].entities[1] == curved
    reopened.bus.undo()
    assert services.kernel.sketches == before
    assert not services.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert services.kernel.sketches[0].entities[1] == curved
    assert services.kernel.cross_sketch_tangencies == (relation,)


def test_curved_polyline_drag_preserves_unrelated_cross_sketch_relation(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    curved = PolylineEntity(uuid4().hex, ((20, 0), (22, 0), (22, 2)), bulges=(1, 0))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, curved), (fixed,))
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
    before = services.kernel.sketches
    original, solved, anchors = app.prepare_cross_sketch_drag(
        services, first.sketch_id, SketchGeometryReference(curved.entity_id, "vertex", 1), (24, 1)
    )
    assert services.kernel.sketches == before
    app.commit_cross_sketch_drag(services, loaded, original, solved, anchors, session_identity=1)
    after = services.kernel.sketches
    moved = next(item for item in after if item.sketch_id == first.sketch_id).entities[1]
    assert isinstance(moved, PolylineEntity)
    assert moved.points_mm[1] == (24, 1) and moved.bulges == curved.bulges
    assert loaded.document.commands[-1].version == 3
    validate_tangency_component(after, (relation,), first.sketch_id)
    history = tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="草图已变化"):
        app.commit_cross_sketch_drag(
            services, loaded, original, solved, anchors, session_identity=1
        )
    assert services.kernel.sketches == after and tuple(loaded.document.commands) == history
    path = tmp_path / "curved-handle.mc.json"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == before
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("updating", (False, True))
def test_solver_applies_new_radius_across_tangent_sketches(updating: bool) -> None:
    from dataclasses import replace

    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    fixed_start = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    fixed_end = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "end"),)
    )
    radius = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 3, "mm"
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (fixed_start, fixed_end))
    original_constraints = (replace(radius, value=2),) if updating else ()
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), original_constraints)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), second.sketch_id, radius
    )
    validate_tangency_component(solved, (relation,), second.sketch_id)
    solved_circle = next(sketch for sketch in solved if sketch.sketch_id == second.sketch_id)
    assert isinstance(solved_circle.entities[0], CircleEntity)
    assert solved_circle.entities[0].radius_mm == pytest.approx(3)
    assert solved_circle.constraints == (radius,)
    assert second.entities == (circle,) and second.constraints == original_constraints


@pytest.mark.parametrize("axis", ("aligned", "horizontal", "vertical"))
def test_solver_applies_linear_distance_across_tangent_sketches(axis: str) -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    vertical = axis == "vertical"
    line = LineEntity(uuid4().hex, (0, 0), (0, 10) if vertical else (10, 0))
    circle = CircleEntity(uuid4().hex, (-2, 5) if vertical else (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
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
        axis=axis,
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), first.sketch_id, dimension
    )
    validate_tangency_component(solved, (relation,), first.sketch_id)
    updated = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id)
    solved_line = updated.entities[0]
    assert isinstance(solved_line, LineEntity)
    if axis == "aligned":
        assert math.dist(solved_line.start_mm, solved_line.end_mm) == pytest.approx(15)
    else:
        coordinate = 1 if vertical else 0
        assert abs(
            solved_line.end_mm[coordinate] - solved_line.start_mm[coordinate]
        ) == pytest.approx(15)


def test_cross_sketch_radius_edit_keeps_ungrounded_circle_center() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 3, "mm"
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), second.sketch_id, dimension
    )
    updated = next(sketch for sketch in solved if sketch.sketch_id == second.sketch_id)
    solved_circle = updated.entities[0]
    assert isinstance(solved_circle, CircleEntity)
    assert solved_circle.center_mm == pytest.approx(circle.center_mm)
    validate_tangency_component(solved, (relation,), first.sketch_id)


@pytest.mark.parametrize("axis", ("ordinate_x", "ordinate_y"))
def test_cross_sketch_signed_ordinate_dimension(axis: str) -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    vertical = axis == "ordinate_y"
    line = LineEntity(uuid4().hex, (0, 10) if vertical else (10, 0), (0, 0))
    circle = CircleEntity(uuid4().hex, (2, 5) if vertical else (5, -2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        -15,
        "mm",
        axis=axis,
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), first.sketch_id, dimension
    )
    updated = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id)
    result = updated.entities[0]
    assert isinstance(result, LineEntity)
    index = 1 if vertical else 0
    assert result.end_mm[index] - result.start_mm[index] == pytest.approx(-15)
    validate_tangency_component(solved, (relation,), first.sketch_id)


def test_cross_sketch_arc_length_edit_keeps_tangency() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    arc = ArcEntity(uuid4().hex, (0, 2), 2, 180, 180)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, arc.entity_id),
        "line_left",
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "arc_length",
        (SketchGeometryReference(arc.entity_id, "geometry"),),
        8,
        "mm",
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), second.sketch_id, dimension
    )
    validate_tangency_component(solved, (relation,), first.sketch_id)
    result = next(sketch for sketch in solved if sketch.sketch_id == second.sketch_id).entities[0]
    assert isinstance(result, ArcEntity)
    assert result.radius_mm * abs(math.radians(result.sweep_angle_deg)) == pytest.approx(8)
    assert result.center_mm == pytest.approx(arc.center_mm)


def test_cross_sketch_angle_edit_keeps_tangency() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    other_line = LineEntity(uuid4().hex, (0, 0), (10, 10))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, other_line))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(other_line.entity_id, "geometry"),
        ),
        60,
        "deg",
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), first.sketch_id, dimension
    )
    validate_tangency_component(solved, (relation,), first.sketch_id)
    updated = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id)
    a, b = updated.entities
    assert isinstance(a, LineEntity) and isinstance(b, LineEntity)
    assert a == line
    angle_a = math.atan2(a.end_mm[1] - a.start_mm[1], a.end_mm[0] - a.start_mm[0])
    angle_b = math.atan2(b.end_mm[1] - b.start_mm[1], b.end_mm[0] - b.start_mm[0])
    assert math.degrees(angle_b - angle_a) == pytest.approx(60)


def test_cross_sketch_preserves_angle_in_opposite_normal_frame() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    reverse_frame = WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1))
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    other_line = LineEntity(uuid4().hex, (0, 0), (10, 10))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    angle = SketchConstraint(
        uuid4().hex,
        "angle",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(other_line.entity_id, "geometry"),
        ),
        45,
        "deg",
    )
    width = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        axis="horizontal",
    )
    first = Sketch(uuid4().hex, reverse_frame, (line, other_line), (angle, width))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right",
    )
    radius = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 3, "mm"
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), second.sketch_id, radius
    )
    validate_tangency_component(solved, (relation,), first.sketch_id)
    updated = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id)
    a, b = updated.entities
    assert isinstance(a, LineEntity) and isinstance(b, LineEntity)
    first_angle = math.atan2(a.end_mm[1] - a.start_mm[1], a.end_mm[0] - a.start_mm[0])
    second_angle = math.atan2(b.end_mm[1] - b.start_mm[1], b.end_mm[0] - b.start_mm[0])
    assert math.degrees(second_angle - first_angle) == pytest.approx(45)
    assert abs(a.end_mm[0] - a.start_mm[0]) == pytest.approx(20)


@pytest.mark.parametrize("anchor", ("auto", "start", "end", "symmetric"))
def test_cross_sketch_length_edit_respects_anchor(anchor: str) -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        15,
        "mm",
        anchor_mode=anchor,
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), first.sketch_id, dimension
    )
    updated = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id)
    result = updated.entities[0]
    assert isinstance(result, LineEntity)
    if anchor in ("auto", "start"):
        assert result.start_mm == pytest.approx(line.start_mm)
    elif anchor == "end":
        assert result.end_mm == pytest.approx(line.end_mm)
    else:
        assert tuple(
            (a + b) / 2 for a, b in zip(result.start_mm, result.end_mm, strict=True)
        ) == pytest.approx((0, 0))
    validate_tangency_component(solved, (relation,), first.sketch_id)


def test_solver_rejects_conflicting_existing_constraints_without_mutation() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    constraints = tuple(
        SketchConstraint(uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, kind),))
        for kind in ("start", "end")
    )
    fixed_center = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(circle.entity_id, "center"),)
    )
    fixed_radius = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 2, "mm"
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), constraints)
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (fixed_center, fixed_radius))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    with pytest.raises(ValueError):
        solve_tangency_component((first, second), (relation,), first.sketch_id)
    assert first.entities == (line,) and second.entities == (circle,)


def test_solver_namespaces_same_entity_identity_in_different_sketches() -> None:
    from mycad.geom.cross_sketch_tangency import solve_unconstrained_tangency

    shared_id = uuid4().hex
    line = LineEntity(shared_id, (-10, 0), (10, 0))
    circle = CircleEntity(shared_id, (0, 3), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, shared_id),
        CrossSketchRef(second.sketch_id, shared_id),
        "line_left",
    )
    result = solve_unconstrained_tangency((first, second), relation)
    validate_tangency_component(result, (relation,), first.sketch_id)
    assert all(sketch.entities[0].entity_id == shared_id for sketch in result)


def test_solver_preserves_local_constraints_across_opposite_plane_normals() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    flipped = WorkPlaneFrame((0, 0, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
    line = LineEntity(uuid4().hex, (10, 0), (-10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    horizontal = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(line.entity_id, "geometry"),)
    )
    first = Sketch(uuid4().hex, flipped, (line,), (fixed, horizontal))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right",
    )
    result = solve_tangency_component((first, second), (relation,), second.sketch_id)
    validate_tangency_component(result, (relation,), second.sketch_id)
    solved = next(sketch for sketch in result if sketch.sketch_id == first.sketch_id)
    solved_line = solved.entities[0]
    assert isinstance(solved_line, LineEntity)
    assert solved_line.start_mm == pytest.approx(line.start_mm)
    assert solved_line.start_mm[1] == pytest.approx(solved_line.end_mm[1])


def test_solver_maps_horizontal_constraint_across_quarter_turn() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    rotated = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (3, 0), 2)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    horizontal = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(line.entity_id, "geometry"),)
    )
    first = Sketch(uuid4().hex, rotated, (line,), (fixed, horizontal))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right",
    )
    result = solve_tangency_component((first, second), (relation,), second.sketch_id)
    validate_tangency_component(result, (relation,), second.sketch_id)
    solved = next(sketch for sketch in result if sketch.sketch_id == first.sketch_id)
    solved_line = solved.entities[0]
    assert isinstance(solved_line, LineEntity)
    assert solved_line.start_mm == pytest.approx(line.start_mm)
    assert solved_line.start_mm[1] == pytest.approx(solved_line.end_mm[1])


@pytest.mark.parametrize("angle", [math.pi / 4, -math.pi / 3])
@pytest.mark.parametrize("kind", ["horizontal", "vertical"])
@pytest.mark.parametrize("opposite_normal", [False, True])
def test_solver_preserves_axis_constraint_in_arbitrarily_rotated_frame(
    angle: float, kind: Literal["horizontal", "vertical"], opposite_normal: bool
) -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    cosine, sine = math.cos(angle), math.sin(angle)
    sign = -1 if opposite_normal else 1
    frame = WorkPlaneFrame(
        (0, 0, 0), (cosine, sine, 0), (-sign * sine, sign * cosine, 0), (0, 0, sign)
    )
    horizontal = kind == "horizontal"
    line = LineEntity(
        uuid4().hex, (-10, 0) if horizontal else (0, -10), (10, 0) if horizontal else (0, 10)
    )
    # Pick a point on the left side of the line in its own frame.
    local_center = (0, 3) if horizontal else (-3, 0)
    circle = CircleEntity(
        uuid4().hex,
        (
            local_center[0] * cosine - sign * local_center[1] * sine,
            local_center[0] * sine + sign * local_center[1] * cosine,
        ),
        2,
    )
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
    )
    axis = SketchConstraint(
        uuid4().hex, kind, (SketchGeometryReference(line.entity_id, "geometry"),)
    )
    first = Sketch(uuid4().hex, frame, (line,), (fixed, axis))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    result = solve_tangency_component((first, second), (relation,), second.sketch_id)
    validate_tangency_component(result, (relation,), second.sketch_id)
    solved = next(sketch for sketch in result if sketch.sketch_id == first.sketch_id)
    solved_line = solved.entities[0]
    assert isinstance(solved_line, LineEntity)
    assert solved_line.start_mm == pytest.approx(line.start_mm)
    index = 1 if horizontal else 0
    assert solved_line.start_mm[index] == pytest.approx(solved_line.end_mm[index], abs=1e-7)
    assert solved.constraints == first.constraints and first.entities == (line,)


def test_solver_preserves_rotated_polyline_segment_direction() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    angle = math.pi / 4
    c, s = math.cos(angle), math.sin(angle)
    frame = WorkPlaneFrame((0, 0, 0), (c, s, 0), (-s, c, 0), (0, 0, 1))
    polyline = PolylineEntity(uuid4().hex, ((-10, 0), (10, 0), (10, 5)))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(polyline.entity_id, "vertex", 0),)
    )
    horizontal = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(polyline.entity_id, "segment", 0),)
    )
    first = Sketch(uuid4().hex, frame, (polyline,), (fixed, horizontal))
    circle = CircleEntity(uuid4().hex, (-3 * s, 3 * c), 2)
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, polyline.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    result = solve_tangency_component((first, second), (relation,), second.sketch_id)
    validate_tangency_component(result, (relation,), second.sketch_id)
    updated = next(sketch for sketch in result if sketch.sketch_id == first.sketch_id)
    solved = updated.entities[0]
    assert isinstance(solved, PolylineEntity)
    assert solved.points_mm[0] == pytest.approx(polyline.points_mm[0])
    assert solved.points_mm[0][1] == pytest.approx(solved.points_mm[1][1], abs=1e-7)
    assert updated.constraints == first.constraints and len(updated.entities) == 1


@pytest.mark.parametrize("bulge", [0.5, -0.5])
@pytest.mark.parametrize("drive_arc", [False, True])
def test_curved_polyline_straight_constraint_and_cross_tangency_replay(
    tmp_path: Path, bulge: float, drive_arc: bool
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.polyline_curves import polyline_arc_segment

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    polyline = PolylineEntity(uuid4().hex, ((-10, -5), (-10, 0), (10, 0)), bulges=(bulge, 0))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(polyline.entity_id, "vertex", 1),)
    )
    horizontal = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(polyline.entity_id, "segment", 1),)
    )
    constraints = (fixed, horizontal)
    original_radius = polyline_arc_segment(polyline, 0).radius_mm
    if drive_arc:
        radius = SketchConstraint(
            uuid4().hex,
            "radius",
            (SketchGeometryReference(polyline.entity_id, "segment", 0),),
            original_radius,
            "mm",
        )
        constraints += (radius,)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,), constraints)
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, polyline.entity_id, 1),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = services.kernel.sketches
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(polyline.entity_id, "segment", 1),),
        25,
        "mm",
    )
    app.commit_cross_sketch_dimension(
        services, loaded, first.sketch_id, dimension, session_identity=1
    )
    after = services.kernel.sketches
    validate_tangency_component(after, (relation,), first.sketch_id)
    solved = next(item for item in after if item.sketch_id == first.sketch_id).entities[0]
    assert isinstance(solved, PolylineEntity)
    assert solved.points_mm[1] == pytest.approx(polyline.points_mm[1])
    assert solved.points_mm[1][1] == pytest.approx(solved.points_mm[2][1])
    assert math.dist(solved.points_mm[1], solved.points_mm[2]) == pytest.approx(25)
    if drive_arc:
        assert polyline_arc_segment(solved, 0).radius_mm == pytest.approx(original_radius)
        assert solved.bulges[0] * bulge > 0
        assert (abs(solved.bulges[0]) > 1) == (abs(bulge) > 1)
    else:
        assert solved.bulges == pytest.approx(polyline.bulges)
    path = tmp_path / "curved-line-cross.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == before
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("axis", ["horizontal", "vertical", "ordinate_x", "ordinate_y"])
def test_solver_uses_rotated_dimension_frame_for_cross_sketch_component(axis: str) -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    angle = math.pi / 4
    c, s = math.cos(angle), math.sin(angle)
    frame = WorkPlaneFrame((0, 0, 0), (c, s, 0), (-s, c, 0), (0, 0, 1))
    horizontal = axis in ("horizontal", "ordinate_x")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0) if horizontal else (0, 10))
    local_center = (5, 2) if horizontal else (-2, 5)
    circle = CircleEntity(
        uuid4().hex,
        (local_center[0] * c - local_center[1] * s, local_center[0] * s + local_center[1] * c),
        2,
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        10,
        "mm",
        axis=axis,
    )
    first = Sketch(uuid4().hex, frame, (line,), (dimension,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    result = solve_tangency_component((first, second), (relation,), second.sketch_id)
    validate_tangency_component(result, (relation,), second.sketch_id)
    updated = next(sketch for sketch in result if sketch.sketch_id == first.sketch_id)
    solved = updated.entities[0]
    assert isinstance(solved, LineEntity)
    coordinate = 0 if horizontal else 1
    assert solved.end_mm[coordinate] - solved.start_mm[coordinate] == pytest.approx(10)
    assert updated.constraints == (dimension,)


@pytest.mark.parametrize("reversed_line", [False, True])
@pytest.mark.parametrize("axis", ["horizontal", "ordinate_x"])
@pytest.mark.parametrize("opposite_normal", [False, True])
def test_solver_preserves_multiple_projected_dimension_frames(
    reversed_line: bool, axis: str, opposite_normal: bool
) -> None:
    from mycad.geom.cross_sketch_tangency import (
        solve_tangency_component,
        solve_tangency_component_constraint,
    )

    c = math.sqrt(0.5)
    normal_sign = -1 if opposite_normal else 1
    rotated = WorkPlaneFrame(
        (0, 0, 0), (c, c, 0), (-normal_sign * c, normal_sign * c, 0), (0, 0, normal_sign)
    )
    line1 = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    endpoints = ((-6 * c, 14 * c * normal_sign), (14 * c, -6 * c * normal_sign))
    start, end = endpoints[::-1] if reversed_line else endpoints
    line2 = LineEntity(uuid4().hex, start, end)
    circle = CircleEntity(uuid4().hex, (0, 2), 2)

    def length(line: LineEntity, value: float, projection_axis: str) -> SketchConstraint:
        return SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(line.entity_id, "geometry"),),
            value,
            "mm",
            axis=projection_axis,
        )

    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line1,), (length(line1, 20, "horizontal"),))
    second_value = -20 * c if reversed_line and axis == "ordinate_x" else 20 * c
    second = Sketch(uuid4().hex, rotated, (line2,), (length(line2, second_value, axis),))
    third = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relations = tuple(
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(sketch.sketch_id, line.entity_id),
            CrossSketchRef(third.sketch_id, circle.entity_id),
            "line_left" if sketch is first or reversed_line != opposite_normal else "line_right",
        )
        for sketch, line in ((first, line1), (second, line2))
    )
    before = (first, second, third)
    solved = solve_tangency_component(before, relations, third.sketch_id)
    validate_tangency_component(solved, relations, third.sketch_id)
    for source in (first, second):
        updated = next(sketch for sketch in solved if sketch.sketch_id == source.sketch_id)
        line = updated.entities[0]
        assert isinstance(line, LineEntity)
        delta = line.end_mm[0] - line.start_mm[0]
        measured = delta if source.constraints[0].axis.startswith("ordinate_") else abs(delta)
        assert measured == pytest.approx(source.constraints[0].value)
        assert updated.constraints == source.constraints
    assert before == (first, second, third)
    target = -18 * c if second_value < 0 else 18 * c
    revised_dimension = replace(second.constraints[0], value=target)
    revised = solve_tangency_component_constraint(
        solved, relations, second.sketch_id, revised_dimension
    )
    validate_tangency_component(revised, relations, second.sketch_id)
    revised_sketch = next(sketch for sketch in revised if sketch.sketch_id == second.sketch_id)
    revised_line = revised_sketch.entities[0]
    assert isinstance(revised_line, LineEntity)
    delta = revised_line.end_mm[0] - revised_line.start_mm[0]
    assert (delta if axis == "ordinate_x" else abs(delta)) == pytest.approx(target)


@pytest.mark.parametrize("value", [-3.0, 0.0, 3.0])
@pytest.mark.parametrize("anchor", ["start", "end", "symmetric"])
@pytest.mark.parametrize("quadrant", [1, 2, 3, 4])
def test_oblique_ordinate_dimension_keeps_signed_value(
    value: float, anchor: str, quadrant: int
) -> None:
    from mycad.geom.sketch_constraints import solve_sketch_constraint

    c = math.sqrt(0.5)
    direction = {1: (c, c), 2: (-c, c), 3: (-c, -c), 4: (c, -c)}[quadrant]
    dx, dy = direction
    line = LineEntity(uuid4().hex, (0, 0), (2 * dx - dy, 2 * dy + dx))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        value,
        "mm",
        axis="ordinate_x",
        anchor_mode=anchor,
    )
    result = solve_sketch_constraint(
        sketch, dimension, projection_axes={dimension.constraint_id: direction}
    )
    assert result.status == "success", result.message
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, LineEntity)
    delta = (solved.end_mm[0] - solved.start_mm[0]) * dx + (
        solved.end_mm[1] - solved.start_mm[1]
    ) * dy
    assert delta == pytest.approx(value, abs=1e-7)
    if anchor == "start":
        assert solved.start_mm == pytest.approx(line.start_mm)
    elif anchor == "end":
        assert solved.end_mm == pytest.approx(line.end_mm)
    else:
        assert tuple(
            (a + b) / 2 for a, b in zip(solved.start_mm, solved.end_mm, strict=True)
        ) == pytest.approx(
            tuple((a + b) / 2 for a, b in zip(line.start_mm, line.end_mm, strict=True))
        )


def test_multiple_projection_frames_commit_undo_and_reopen(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    c = math.sqrt(0.5)
    frame = WorkPlaneFrame((0, 0, 0), (c, c, 0), (-c, c, 0), (0, 0, 1))
    lower = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    upper = LineEntity(uuid4().hex, (-6 * c, 14 * c), (14 * c, -6 * c))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    lower_dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(lower.entity_id, "geometry"),),
        20,
        "mm",
        axis="horizontal",
    )
    upper_dim = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(upper.entity_id, "geometry"),),
        20 * c,
        "mm",
        axis="ordinate_x",
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (lower,), (lower_dim,))
    second = Sketch(uuid4().hex, frame, (upper,), (upper_dim,))
    third = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second, third):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relations = (
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(first.sketch_id, lower.entity_id),
            CrossSketchRef(third.sketch_id, circle.entity_id),
            "line_left",
        ),
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(second.sketch_id, upper.entity_id),
            CrossSketchRef(third.sketch_id, circle.entity_id),
            "line_right",
        ),
    )
    for relation in relations:
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = services.kernel.sketches
    changed = replace(upper_dim, value=18 * c)
    app.commit_cross_sketch_dimension(
        services, loaded, second.sketch_id, changed, session_identity=1
    )
    after = services.kernel.sketches
    validate_tangency_component(after, relations, second.sketch_id)
    assert next(sketch for sketch in after if sketch.sketch_id == second.sketch_id).constraints == (
        changed,
    )
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after
    path = tmp_path / "multiple-projections.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert services.kernel.sketches == before
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize(("axis", "value"), [("horizontal", 4.0), ("ordinate_x", -4.0)])
def test_oblique_dimension_conflict_keeps_fixed_geometry(axis: str, value: float) -> None:
    from mycad.geom.sketch_constraints import solve_sketch_constraint

    c = math.sqrt(0.5)
    line = LineEntity(uuid4().hex, (0, 0), (c, 3 * c))
    fixed = tuple(
        SketchConstraint(uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, point),))
        for point in ("start", "end")
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), fixed)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        value,
        "mm",
        axis=axis,
    )
    result = solve_sketch_constraint(
        sketch, dimension, projection_axes={dimension.constraint_id: (c, c)}
    )
    assert result.status != "success" and result.sketch is None
    assert sketch.entities == (line,) and sketch.constraints == fixed


@pytest.mark.parametrize("value", [-2.0, 0.0, 2.0])
def test_existing_oblique_ordinate_survives_another_relation(value: float) -> None:
    from mycad.geom.sketch_constraints import solve_sketch_constraint

    c = math.sqrt(0.5)
    end = ((value - 2) * c, (value + 2) * c)
    first = LineEntity(uuid4().hex, (0, 0), end)
    second = LineEntity(uuid4().hex, (5, 5), (5 + end[0], 5 + end[1]))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(first.entity_id, "geometry"),),
        value,
        "mm",
        axis="ordinate_x",
    )
    parallel = SketchConstraint(
        uuid4().hex,
        "parallel",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (dimension,))
    result = solve_sketch_constraint(
        sketch, parallel, projection_axes={dimension.constraint_id: (c, c)}
    )
    assert result.status == "success", result.message
    assert result.sketch is not None
    solved = result.sketch.entities[0]
    assert isinstance(solved, LineEntity)
    delta = (solved.end_mm[0] - solved.start_mm[0] + solved.end_mm[1] - solved.start_mm[1]) * c
    assert delta == pytest.approx(value, abs=1e-7)


def test_solver_preserves_existing_coincident_connection() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    connected = LineEntity(uuid4().hex, (10, 0), (10, 5))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    coincident = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(line.entity_id, "end"),
            SketchGeometryReference(connected.entity_id, "start"),
        ),
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, connected), (coincident,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    result = solve_tangency_component((first, second), (relation,), first.sketch_id)
    validate_tangency_component(result, (relation,), first.sketch_id)
    solved = next(sketch for sketch in result if sketch.sketch_id == first.sketch_id)
    first_line, second_line = solved.entities
    assert isinstance(first_line, LineEntity) and isinstance(second_line, LineEntity)
    assert first_line.end_mm == pytest.approx(second_line.start_mm)
    assert solved.constraints == first.constraints


@pytest.mark.parametrize("arc", (False, True))
def test_solver_preserves_existing_local_tangency(arc: bool) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    local_circle = (
        ArcEntity(uuid4().hex, (-4, 2), 2, 180, 180)
        if arc
        else CircleEntity(uuid4().hex, (-4, 2), 2)
    )
    other_circle = CircleEntity(uuid4().hex, (4, 3), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(local_circle.entity_id, "geometry"),
        ),
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, local_circle), (constraint,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other_circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, other_circle.entity_id),
        "line_left",
    )
    solved = solve_tangency_component((first, second), (relation,), first.sketch_id)
    validate_tangency_component(solved, (relation,), first.sketch_id)
    updated = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id)
    solved_line, solved_circle = updated.entities
    assert isinstance(solved_line, LineEntity) and isinstance(
        solved_circle, CircleEntity | ArcEntity
    )
    assert tangent_on_curves(solved_line, solved_circle)
    assert updated.constraints == (constraint,)


def test_solver_anchors_locally_constrained_entity_outside_cross_relation() -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_anchored

    line = LineEntity(uuid4().hex, (-10, 1), (10, 1))
    local_circle = CircleEntity(uuid4().hex, (0, 2), 2)
    other_circle = CircleEntity(uuid4().hex, (4, 2), 2)
    local = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(local_circle.entity_id, "geometry"),
        ),
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, local_circle), (local,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other_circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, local_circle.entity_id),
        CrossSketchRef(second.sketch_id, other_circle.entity_id),
        "external",
    )
    solved = solve_tangency_component_anchored(
        (first, second),
        (relation,),
        first.sketch_id,
        (CrossSketchRef(first.sketch_id, line.entity_id),),
    )
    validate_tangency_component(solved, (relation,), first.sketch_id)
    updated = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id)
    solved_line, solved_circle = updated.entities
    assert isinstance(solved_line, LineEntity) and isinstance(solved_circle, CircleEntity)
    assert solved_line == line and tangent_on_curves(solved_line, solved_circle)


@pytest.mark.parametrize("kind", ["parallel", "perpendicular"])
def test_solver_preserves_local_line_orientation_relationship(kind: str) -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    other = (
        LineEntity(uuid4().hex, (-10, 5), (10, 5))
        if kind == "parallel"
        else LineEntity(uuid4().hex, (10, 0), (10, 5))
    )
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    constraint = SketchConstraint.from_mapping(
        {
            "constraint_id": uuid4().hex,
            "kind": kind,
            "references": [
                SketchGeometryReference(line.entity_id, "geometry").to_mapping(),
                SketchGeometryReference(other.entity_id, "geometry").to_mapping(),
            ],
            "driving": True,
            "source": "user",
        }
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, other), (constraint,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    result = solve_tangency_component((first, second), (relation,), first.sketch_id)
    validate_tangency_component(result, (relation,), first.sketch_id)
    solved = next(sketch for sketch in result if sketch.sketch_id == first.sketch_id)
    first_line, second_line = solved.entities
    assert isinstance(first_line, LineEntity) and isinstance(second_line, LineEntity)
    a = (
        first_line.end_mm[0] - first_line.start_mm[0],
        first_line.end_mm[1] - first_line.start_mm[1],
    )
    b = (
        second_line.end_mm[0] - second_line.start_mm[0],
        second_line.end_mm[1] - second_line.start_mm[1],
    )
    residual = a[0] * b[1] - a[1] * b[0] if kind == "parallel" else a[0] * b[0] + a[1] * b[1]
    assert residual == pytest.approx(0, abs=1e-6)


def test_kernel_adds_tangency_atomically_and_rejects_breaking_revision() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import build_tangency_revisions
    from mycad.core.exceptions import ValidationError
    from mycad.geom.cross_sketch_tangency import solve_tangency_component
    from mycad.geom.kernel import BuildKernel

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    kernel = BuildKernel()
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    original = kernel.sketches
    solved = solve_tangency_component(original, (relation,), first.sketch_id)
    revisions = build_tangency_revisions(original, solved)
    kernel.apply(
        "drawing.tangency.add", {"relation": relation.to_mapping(), "revisions": revisions}
    )
    assert kernel.cross_sketch_tangencies == (relation,)
    validate_tangency_component(kernel.sketches, (relation,), first.sketch_id)
    current = next(sketch for sketch in kernel.sketches if sketch.sketch_id == second.sketch_id)
    solved_circle = current.entities[0]
    assert isinstance(solved_circle, CircleEntity)
    broken = replace(current, entities=(replace(solved_circle, center_mm=(100, 100)),))
    revision = build_tangency_revisions((current,), (broken,))[0]
    before = kernel.sketches
    with pytest.raises(ValidationError):
        kernel.apply("sketch.revise", revision)
    assert kernel.sketches == before and kernel.cross_sketch_tangencies == (relation,)


def test_kernel_batch_revises_related_sketches_together() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import build_tangency_revisions
    from mycad.core.sketch_edit import move_entities
    from mycad.geom.kernel import BuildKernel

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    kernel = BuildKernel()
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    kernel.apply("drawing.tangency.add", {"relation": relation.to_mapping(), "revisions": ()})
    original = kernel.sketches
    moved = tuple(
        replace(
            sketch, entities=move_entities(sketch.entities, (sketch.entities[0].entity_id,), (0, 5))
        )
        for sketch in original
    )
    revisions = build_tangency_revisions(original, moved)
    kernel.apply("drawing.sketch.revise", {"revisions": revisions})
    validate_tangency_component(kernel.sketches, (relation,), first.sketch_id)
    assert {sketch.sketch_id: sketch for sketch in kernel.sketches} == {
        sketch.sketch_id: sketch for sketch in moved
    }


def test_kernel_removes_tangency_before_allowing_source_deletion() -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.geom.kernel import BuildKernel

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    kernel = BuildKernel()
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    kernel.apply("drawing.tangency.add", {"relation": relation.to_mapping(), "revisions": ()})
    state = second.to_state_mapping()
    state["entities"] = []
    revision: dict[str, object] = {
        "sketch_id": second.sketch_id,
        "base_state_sha256": second.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    with pytest.raises(ValidationError):
        kernel.apply("sketch.revise", revision)
    kernel.apply("drawing.tangency.remove", {"relation_id": relation.relation_id})
    assert not kernel.cross_sketch_tangencies
    kernel.apply("sketch.revise", revision)
    assert next(s for s in kernel.sketches if s.sketch_id == second.sketch_id).entities == ()


def test_tangency_command_replays_undo_redo_and_archive(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.cross_sketch_tangency import build_tangency_revisions
    from mycad.core.persistence import save_document
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
    from mycad.geom.cross_sketch_tangency import solve_tangency_component

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    before = services.kernel.sketches
    solved = solve_tangency_component(before, (relation,), first.sketch_id)
    params: dict[str, object] = {
        "relation": relation.to_mapping(),
        "revisions": list(build_tangency_revisions(before, solved)),
    }
    candidate = app.create_replay_candidate(services, loaded, session_identity=17)
    candidate.stage(
        ReplayChangeSet(
            (),
            (ReplayAppend("drawing.tangency.add", 1, params, "local"),),
            False,
            target_archive_version=6,
        ),
        current_session_identity=17,
    )
    assert candidate.preview(current_session_identity=17).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=17), current_session_identity=17
    )
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.undo()
    assert not services.kernel.cross_sketch_tangencies and services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    path = tmp_path / "tangent.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert reopened.document.commands == loaded.document.commands
    assert services.kernel.cross_sketch_tangencies == (relation,)
    validate_tangency_component(services.kernel.sketches, (relation,), first.sketch_id)


def test_app_commits_tangency_in_one_undoable_transaction() -> None:
    from mycad import app

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    original = services.kernel.sketches
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    assert loaded.document.commands[-1].version == 1
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert len(loaded.document.commands) == 3
    validate_tangency_component(services.kernel.sketches, (relation,), first.sketch_id)
    loaded.bus.undo()
    assert services.kernel.sketches == original and not services.kernel.cross_sketch_tangencies


def test_app_commits_fillet_draft_and_saved_source_tangencies_atomically(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.circle_fillet import circle_fillet_notrim
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    loaded.bus.execute("sketch.create", source.to_mapping(version=3), "local")
    arc = circle_fillet_notrim(first, second, (2, 1), (8, 1), 4, uuid4().hex)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    app.commit_new_sketch(
        services,
        loaded,
        draft,
        session_identity=17,
        cross_tangent_pairs=((first.entity_id, arc.entity_id), (second.entity_id, arc.entity_id)),
    )
    assert len(services.kernel.cross_sketch_tangencies) == 2
    loaded.bus.undo()
    assert services.kernel.sketches == (source,) and not services.kernel.cross_sketch_tangencies
    loaded.bus.redo()
    assert len(services.kernel.cross_sketch_tangencies) == 2
    path = tmp_path / "fillet-cross.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert len(services.kernel.cross_sketch_tangencies) == 2


def test_tangency_command_rejects_unrelated_sketch_revision() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import build_tangency_revisions
    from mycad.core.exceptions import ValidationError
    from mycad.geom.kernel import BuildKernel

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    other_circle = CircleEntity(uuid4().hex, (30, 30), 3)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    unrelated = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other_circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    kernel = BuildKernel()
    for sketch in (first, second, unrelated):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    modified = replace(unrelated, entities=(replace(other_circle, radius_mm=4),))
    revisions = build_tangency_revisions((unrelated,), (modified,))
    before = kernel.sketches
    with pytest.raises(ValidationError):
        kernel.apply(
            "drawing.tangency.add", {"relation": relation.to_mapping(), "revisions": revisions}
        )
    assert kernel.sketches == before and not kernel.cross_sketch_tangencies


def test_tangency_command_rejects_deleting_other_entities() -> None:
    from mycad.core.exceptions import ValidationError
    from mycad.geom.kernel import BuildKernel

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    other = LineEntity(uuid4().hex, (-10, 4), (10, 4))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, other))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    kernel = BuildKernel()
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    state = Sketch(first.sketch_id, first.frame, (line,)).to_state_mapping()
    revision: dict[str, object] = {
        "sketch_id": first.sketch_id,
        "base_state_sha256": first.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    with pytest.raises(ValidationError):
        kernel.apply(
            "drawing.tangency.add", {"relation": relation.to_mapping(), "revisions": (revision,)}
        )
    assert kernel.sketches == (first, second) and not kernel.cross_sketch_tangencies


def test_batch_revision_can_atomically_add_and_remove_cross_tangencies() -> None:
    from dataclasses import replace

    from mycad.core.cross_sketch_tangency import build_tangency_revisions
    from mycad.geom.kernel import BuildKernel

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    kernel = BuildKernel()
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    tangent = replace(second, entities=(replace(circle, center_mm=(0, 2)),))
    revisions = build_tangency_revisions((second,), (tangent,))
    kernel.apply(
        "drawing.sketch.revise",
        {"revisions": revisions, "cross_tangencies": [relation.to_mapping()]},
    )
    assert kernel.cross_sketch_tangencies == (relation,)
    current = next(sketch for sketch in kernel.sketches if sketch.sketch_id == second.sketch_id)
    removed = replace(current, entities=())
    state = removed.to_state_mapping()
    removal = {
        "sketch_id": current.sketch_id,
        "base_state_sha256": current.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    kernel.apply(
        "drawing.sketch.revise",
        {"revisions": [removal], "remove_tangencies": [relation.relation_id]},
    )
    assert not kernel.cross_sketch_tangencies
    assert next(s for s in kernel.sketches if s.sketch_id == second.sketch_id).entities == ()


def test_batch_revision_can_add_inferred_local_and_cross_tangency_for_new_arc() -> None:
    from dataclasses import replace

    from mycad.core.command_identity import ExecutionContext
    from mycad.core.cross_sketch_tangency import infer_tangency_branch
    from mycad.core.exceptions import ValidationError
    from mycad.core.line_circle_fillet import line_circle_fillet_notrim
    from mycad.geom.kernel import BuildKernel

    line = LineEntity(uuid4().hex, (-20, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    arc = line_circle_fillet_notrim(line, circle, (-3, 0), (-1.3, 3.5), 2, uuid4().hex)
    local = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(arc.entity_id, "geometry"),
        ),
        source="inferred",
    )
    revised = replace(first, entities=(line, arc), constraints=(local,))
    state = revised.to_state_mapping()
    revision = {
        "sketch_id": first.sketch_id,
        "base_state_sha256": first.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(second.sketch_id, circle.entity_id),
        CrossSketchRef(first.sketch_id, arc.entity_id),
        infer_tangency_branch(circle, arc),
    )
    kernel = BuildKernel()
    for sketch in (first, second):
        kernel.apply("sketch.create", sketch.to_state_mapping())
    with pytest.raises(ValidationError):
        kernel.apply_with_context(
            "drawing.sketch.revise",
            {"revisions": [revision], "cross_tangencies": [relation.to_mapping()]},
            ExecutionContext("drawing.sketch.revise", 1),
        )
    kernel.apply_with_context(
        "drawing.sketch.revise",
        {"revisions": [revision], "cross_tangencies": [relation.to_mapping()]},
        ExecutionContext("drawing.sketch.revise", 2),
    )
    assert kernel.cross_sketch_tangencies == (relation,)
    assert next(s for s in kernel.sketches if s.sketch_id == first.sketch_id).constraints == (
        local,
    )


def test_solver_keeps_edited_line_fixed_while_other_sketch_follows() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_anchored

    line = LineEntity(uuid4().hex, (-10, 1), (10, 1))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    first_ref = CrossSketchRef(first.sketch_id, line.entity_id)
    relation = CrossSketchTangency(
        uuid4().hex,
        first_ref,
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    result = solve_tangency_component_anchored(
        (first, second), (relation,), first.sketch_id, (first_ref,)
    )
    validate_tangency_component(result, (relation,), first.sketch_id)
    solved = next(sketch for sketch in result if sketch.sketch_id == first.sketch_id)
    assert solved.entities == (line,)


def test_app_commits_anchored_cross_sketch_edit_as_one_history_step() -> None:
    from dataclasses import replace

    from mycad import app

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    first_ref = CrossSketchRef(first.sketch_id, line.entity_id)
    relation = CrossSketchTangency(
        uuid4().hex, first_ref, CrossSketchRef(second.sketch_id, circle.entity_id), "line_left"
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before = services.kernel.sketches
    moved_line = replace(line, start_mm=(-10, 1), end_mm=(10, 1))
    edited = tuple(
        replace(sketch, entities=(moved_line,)) if sketch.sketch_id == first.sketch_id else sketch
        for sketch in before
    )
    app.commit_cross_sketch_edit(
        services, loaded, before, edited, (first_ref,), session_identity=17
    )
    after = services.kernel.sketches
    assert next(s for s in after if s.sketch_id == first.sketch_id).entities == (moved_line,)
    validate_tangency_component(after, (relation,), first.sketch_id)
    loaded.bus.undo()
    assert services.kernel.sketches == before and services.kernel.cross_sketch_tangencies == (
        relation,
    )


def test_app_commits_cross_sketch_radius_as_one_history_step(tmp_path: Path) -> None:
    from copy import deepcopy
    from dataclasses import replace

    from mycad import app
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before = services.kernel.sketches
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 3, "mm"
    )
    app.commit_cross_sketch_dimension(
        services, loaded, second.sketch_id, dimension, session_identity=17
    )
    after = services.kernel.sketches
    validate_tangency_component(after, (relation,), first.sketch_id)
    changed = next(sketch for sketch in after if sketch.sketch_id == second.sketch_id)
    assert dimension in changed.constraints
    assert isinstance(changed.entities[0], CircleEntity)
    assert changed.entities[0].radius_mm == pytest.approx(3)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after
    with pytest.raises(ValidationError, match="操作已取消"):
        app.commit_cross_sketch_dimension(
            services,
            loaded,
            second.sketch_id,
            replace(dimension, value=4),
            session_identity=17,
            still_current=lambda: False,
        )
    assert services.kernel.sketches == after
    with pytest.raises(ValidationError, match="重新预览"):
        app.commit_cross_sketch_dimension(
            services,
            loaded,
            second.sketch_id,
            replace(dimension, value=4),
            session_identity=17,
            expected_sketches=after,
        )
    assert services.kernel.sketches == after
    app.commit_cross_sketch_dimension(
        services, loaded, second.sketch_id, replace(dimension, value=4), session_identity=17
    )
    updated = services.kernel.sketches
    changed = next(sketch for sketch in updated if sketch.sketch_id == second.sketch_id)
    assert isinstance(changed.entities[0], CircleEntity)
    assert changed.entities[0].radius_mm == pytest.approx(4)
    validate_tangency_component(updated, (relation,), first.sketch_id)
    path = tmp_path / "linked-dimension.my2d"
    save_document(loaded.document, path)
    forged = deepcopy(loaded.document.commands[-1].params)
    forged["dimension"] = {"sketch_id": second.sketch_id, "constraint": dimension.to_mapping()}
    loaded.bus.undo()
    assert services.kernel.sketches == after
    with pytest.raises(ValidationError, match="confirmed dimension"):
        loaded.bus.execute("drawing.sketch.revise", forged, "local", version=4)
    assert services.kernel.sketches == after
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == updated
    reopened.bus.undo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("axis", ("aligned", "horizontal", "vertical"))
def test_app_commits_cross_sketch_linear_dimension(axis: str) -> None:
    from mycad import app

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    vertical = axis == "vertical"
    line = LineEntity(uuid4().hex, (0, 0), (0, 10) if vertical else (10, 0))
    circle = CircleEntity(uuid4().hex, (-2, 5) if vertical else (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before = services.kernel.sketches
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(line.entity_id, "start"),
            SketchGeometryReference(line.entity_id, "end"),
        ),
        15,
        "mm",
        axis=axis,
    )
    app.commit_cross_sketch_dimension(
        services, loaded, first.sketch_id, dimension, session_identity=17
    )
    after = services.kernel.sketches
    validate_tangency_component(after, (relation,), first.sketch_id)
    assert (
        dimension in next(item for item in after if item.sketch_id == first.sketch_id).constraints
    )
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("kind", ("angle", "arc_length", "ordinate"))
def test_app_commits_more_cross_sketch_dimension_kinds(kind: str) -> None:
    from mycad import app

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    other = LineEntity(uuid4().hex, (0, 0), (10, 10))
    curve = (
        ArcEntity(uuid4().hex, (0, 2), 2, 180, 180)
        if kind == "arc_length"
        else CircleEntity(uuid4().hex, (0, 2), 2)
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, other) if kind == "angle" else (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, curve.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before = services.kernel.sketches
    if kind == "angle":
        dimension = SketchConstraint(
            uuid4().hex,
            "angle",
            (
                SketchGeometryReference(line.entity_id, "geometry"),
                SketchGeometryReference(other.entity_id, "geometry"),
            ),
            60,
            "deg",
        )
        target = first.sketch_id
    elif kind == "arc_length":
        dimension = SketchConstraint(
            uuid4().hex,
            "arc_length",
            (SketchGeometryReference(curve.entity_id, "geometry"),),
            8,
            "mm",
        )
        target = second.sketch_id
    else:
        dimension = SketchConstraint(
            uuid4().hex,
            "distance",
            (
                SketchGeometryReference(line.entity_id, "start"),
                SketchGeometryReference(line.entity_id, "end"),
            ),
            15,
            "mm",
            axis="ordinate_x",
        )
        target = first.sketch_id
    app.commit_cross_sketch_dimension(services, loaded, target, dimension, session_identity=17)
    after = services.kernel.sketches
    validate_tangency_component(after, (relation,), first.sketch_id)
    assert dimension in next(item for item in after if item.sketch_id == target).constraints
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after


def test_cross_sketch_dimension_refreshes_reference_annotation() -> None:
    from copy import deepcopy
    from typing import cast

    from mycad import app
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    annotation = SketchConstraint(
        uuid4().hex,
        "diameter",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        4,
        "mm",
        driving=False,
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (annotation,))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before = services.kernel.sketches
    radius = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 3, "mm"
    )
    app.commit_cross_sketch_dimension(
        services, loaded, second.sketch_id, radius, session_identity=17
    )
    after = services.kernel.sketches
    updated = next(item for item in after if item.sketch_id == second.sketch_id)
    reference = next(
        item for item in updated.constraints if item.constraint_id == annotation.constraint_id
    )
    assert reference.value == pytest.approx(6)
    assert radius in updated.constraints
    validate_tangency_component(after, (relation,), first.sketch_id)
    forged = deepcopy(loaded.document.commands[-1].params)
    revisions = cast("list[dict[str, object]]", forged["revisions"])
    target = next(item for item in revisions if item["sketch_id"] == second.sketch_id)
    annotations = cast("list[dict[str, object]]", target["constraints"])
    next(item for item in annotations if item["constraint_id"] == annotation.constraint_id)[
        "value"
    ] = 999
    loaded.bus.undo()
    assert services.kernel.sketches == before
    with pytest.raises(ValidationError, match="reference dimension value does not match geometry"):
        loaded.bus.execute("drawing.sketch.revise", forged, "local", version=4)
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after


def test_cross_sketch_radius_rebuilds_dependent_extrusion(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services)
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    loaded.bus.execute(
        "feature.extrude",
        {
            "profile": {"type": "sketch", "sketch_id": second.sketch_id},
            "distance": 5,
            "mode": "new",
        },
        "local",
        version=2,
    )
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    assert services.kernel.mass_properties().volume == pytest.approx(math.pi * 4 * 5)
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 3, "mm"
    )
    app.commit_cross_sketch_dimension(
        services, loaded, second.sketch_id, dimension, session_identity=17
    )
    assert services.kernel.mass_properties().volume == pytest.approx(math.pi * 9 * 5)
    path = tmp_path / "linked-extrusion.mc.json"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(math.pi * 4 * 5)
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(math.pi * 9 * 5)
    app.open_app_document(services, path)
    assert services.kernel.mass_properties().volume == pytest.approx(math.pi * 9 * 5)


def test_conflicting_cross_sketch_dimension_keeps_history_and_geometry() -> None:
    from mycad import app
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    existing = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 2, "mm"
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,), (existing,))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before, commands = services.kernel.sketches, tuple(loaded.document.commands)
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 3, "mm"
    )
    with pytest.raises(ValidationError):
        app.commit_cross_sketch_dimension(
            services, loaded, second.sketch_id, dimension, session_identity=17
        )
    assert services.kernel.sketches == before
    assert tuple(loaded.document.commands) == commands
    assert services.kernel.cross_sketch_tangencies == (relation,)


def test_cross_sketch_dimension_rejects_locked_geometry() -> None:
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (circle,),
        layers=SketchLayerTable((SketchLayer("0", locked=True),)),
    )
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 3, "mm"
    )
    with pytest.raises(ValueError, match="锁定"):
        solve_tangency_component_constraint(
            (first, second), (relation,), second.sketch_id, dimension
        )
    assert first.entities == (line,) and second.entities == (circle,)


def test_prepare_saved_cross_sketch_handle_drag_is_isolated() -> None:
    from mycad import app

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    original, solved, anchors = app.prepare_cross_sketch_drag(
        services, first.sketch_id, SketchGeometryReference(line.entity_id, "start"), (-10, 1)
    )
    assert {item.sketch_id: item for item in original} == {item.sketch_id: item for item in before}
    moved = next(item for item in solved if item.sketch_id == first.sketch_id).entities[0]
    assert isinstance(moved, LineEntity)
    assert moved.start_mm == pytest.approx((-10, 1))
    assert anchors == (CrossSketchRef(first.sketch_id, line.entity_id),)
    validate_tangency_component(solved, (relation,), first.sketch_id)
    assert services.kernel.sketches == before and tuple(loaded.document.commands) == history
    app.commit_cross_sketch_drag(services, loaded, original, solved, anchors, session_identity=17)
    assert {item.sketch_id: item for item in services.kernel.sketches} == {
        item.sketch_id: item for item in solved
    }
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert {item.sketch_id: item for item in services.kernel.sketches} == {
        item.sketch_id: item for item in solved
    }


@pytest.mark.parametrize("flipped", (False, True))
def test_cross_sketch_drag_preserves_tangency_across_workplane_orientation(flipped: bool) -> None:
    from mycad import app

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    frame = (
        WorkPlaneFrame((0, 0, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if flipped
        else WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2) if flipped else (2, 0), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, frame, (circle,))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before = services.kernel.sketches
    target = (1, 3) if flipped else (3, -1)
    original, solved, anchors = app.prepare_cross_sketch_drag(
        services, second.sketch_id, SketchGeometryReference(circle.entity_id, "center"), target
    )
    moved = next(item for item in solved if item.sketch_id == second.sketch_id).entities[0]
    assert isinstance(moved, CircleEntity) and moved.center_mm == pytest.approx(target)
    validate_tangency_component(solved, (relation,), second.sketch_id)
    app.commit_cross_sketch_drag(services, loaded, original, solved, anchors, session_identity=17)
    loaded.bus.undo()
    assert services.kernel.sketches == before


@pytest.mark.parametrize("kind", ("circle", "arc"))
def test_prepare_cross_sketch_curve_handle_drag(kind: str) -> None:
    from mycad import app

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    curve = (
        CircleEntity(uuid4().hex, (0, 2), 2)
        if kind == "circle"
        else ArcEntity(uuid4().hex, (0, 2), 2, 180, 180)
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (curve,))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, curve.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before = services.kernel.sketches
    reference = SketchGeometryReference(curve.entity_id, "center" if kind == "circle" else "start")
    target = (0.0, 3.0) if kind == "circle" else (-1.5, 2.0)
    original, solved, anchors = app.prepare_cross_sketch_drag(
        services, second.sketch_id, reference, target
    )
    assert services.kernel.sketches == before
    validate_tangency_component(solved, (relation,), second.sketch_id)
    app.commit_cross_sketch_drag(services, loaded, original, solved, anchors, session_identity=17)
    loaded.bus.undo()
    assert services.kernel.sketches == before


def test_prepare_drag_of_unrelated_entity_in_linked_sketch() -> None:
    from mycad import app

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    extra = CircleEntity(uuid4().hex, (15, 15), 1)
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, extra))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    original, solved, anchors = app.prepare_cross_sketch_drag(
        services, first.sketch_id, SketchGeometryReference(extra.entity_id, "center"), (16, 15)
    )
    moved = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id).entities[1]
    assert isinstance(moved, CircleEntity) and moved.center_mm == pytest.approx((16, 15))
    validate_tangency_component(solved, (relation,), first.sketch_id)
    app.commit_cross_sketch_drag(services, loaded, original, solved, anchors, session_identity=17)
    loaded.bus.undo()
    assert {item.sketch_id: item for item in services.kernel.sketches} == {
        item.sketch_id: item for item in original
    }


def test_saved_cross_sketch_drag_rejects_hidden_source() -> None:
    from mycad import app
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (circle,),
        layers=SketchLayerTable((SketchLayer("0", visible=False),)),
    )
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="隐藏"):
        app.prepare_cross_sketch_drag(
            services, second.sketch_id, SketchGeometryReference(circle.entity_id, "center"), (0, 3)
        )
    assert services.kernel.sketches == before and tuple(loaded.document.commands) == history


def test_saved_cross_sketch_drag_rejects_locked_annotation() -> None:
    from mycad import app
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    annotation = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        2,
        "mm",
        driving=False,
        layer_name="DIM",
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (circle,),
        (annotation,),
        SketchLayerTable((SketchLayer("0"), SketchLayer("DIM", locked=True))),
    )
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    with pytest.raises(ValidationError, match="标注"):
        app.prepare_cross_sketch_drag(
            services, second.sketch_id, SketchGeometryReference(circle.entity_id, "center"), (0, 3)
        )
    assert services.kernel.sketches == before and tuple(loaded.document.commands) == history


def test_mixed_handle_solve_rejects_locked_source_annotation() -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    annotation = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        layer_name="DIM",
    )
    saved = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (line,),
        (annotation,),
        SketchLayerTable((SketchLayer("0"), SketchLayer("DIM", locked=True))),
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    moved = replace(draft, entities=(replace(circle, center_mm=(0, 3)),))
    with pytest.raises(ValueError, match="标注"):
        app.solve_mixed_draft_tangencies(
            (saved,),
            draft,
            (saved,),
            moved,
            ((line.entity_id, circle.entity_id),),
            (),
            (CrossSketchRef(draft.sketch_id, circle.entity_id),),
        )
    assert saved.entities == (line,) and draft.entities == (circle,)


@pytest.mark.parametrize("side", ("saved", "draft"))
def test_prepare_mixed_handle_drag_preserves_pending_tangency(side: str) -> None:
    from mycad import app
    from mycad.core.fillet_curves import tangent_on_curves

    services = app.build_app(discoverers=[])
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    target = (
        CrossSketchRef(saved.sketch_id, line.entity_id)
        if side == "saved"
        else CrossSketchRef(draft.sketch_id, circle.entity_id)
    )
    reference = SketchGeometryReference(target.entity_id, "start" if side == "saved" else "center")
    point = (-10.0, 1.0) if side == "saved" else (0.0, 3.0)
    updated_saved, updated_draft, anchors = app.prepare_mixed_handle_drag(
        services,
        (saved,),
        draft,
        ((line.entity_id, circle.entity_id),),
        (),
        target,
        reference,
        point,
    )
    updated_line, updated_circle = updated_saved[0].entities[0], updated_draft.entities[0]
    assert isinstance(updated_line, LineEntity) and isinstance(updated_circle, CircleEntity)
    dragged = updated_line.start_mm if side == "saved" else updated_circle.center_mm
    assert dragged == pytest.approx(point)
    assert tangent_on_curves(updated_line, updated_circle)
    assert anchors == (target,)
    assert saved.entities == (line,) and draft.entities == (circle,)


@pytest.mark.parametrize("side", ("saved", "draft"))
def test_mixed_curved_polyline_drag_keeps_pending_tangency(side: str) -> None:
    from mycad import app

    services = app.build_app(discoverers=[])
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    curved = PolylineEntity(uuid4().hex, ((20, 0), (22, 0), (22, 2)), bulges=(1, 0))
    saved = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (line, *((curved,) if side == "saved" else ()))
    )
    draft = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (circle, *((curved,) if side == "draft" else ()))
    )
    target = CrossSketchRef(
        saved.sketch_id if side == "saved" else draft.sketch_id, curved.entity_id
    )
    updated_saved, updated_draft, anchors = app.prepare_mixed_handle_drag(
        services,
        (saved,),
        draft,
        ((line.entity_id, circle.entity_id),),
        (),
        target,
        SketchGeometryReference(curved.entity_id, "vertex", 1),
        (24, 1),
    )
    owner = updated_saved[0] if side == "saved" else updated_draft
    moved = owner.entities[1]
    assert isinstance(moved, PolylineEntity)
    assert moved.points_mm[1] == (24, 1) and moved.bulges == curved.bulges
    assert updated_saved[0].entities[0] == line and updated_draft.entities[0] == circle
    assert anchors == (target,)


@pytest.mark.parametrize("kind", ("concentric", "equal"))
def test_mixed_handle_drag_preserves_local_circle_relations(
    kind: Literal["concentric", "equal"],
) -> None:
    from mycad import app
    from mycad.core.fillet_curves import tangent_on_curves

    services = app.build_app(discoverers=[])
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    other = CircleEntity(uuid4().hex, (0, 2) if kind == "concentric" else (8, 5), 2)
    relation = SketchConstraint(
        uuid4().hex,
        kind,
        (
            SketchGeometryReference(circle.entity_id, "geometry"),
            SketchGeometryReference(other.entity_id, "geometry"),
        ),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle, other), (relation,))
    target = CrossSketchRef(draft.sketch_id, circle.entity_id)
    updated_saved, updated_draft, _ = app.prepare_mixed_handle_drag(
        services,
        (saved,),
        draft,
        ((line.entity_id, circle.entity_id),),
        (),
        target,
        SketchGeometryReference(circle.entity_id, "center"),
        (0, 3),
    )
    moved_line = updated_saved[0].entities[0]
    moved_circle, moved_other = updated_draft.entities
    assert isinstance(moved_line, LineEntity)
    assert isinstance(moved_circle, CircleEntity) and isinstance(moved_other, CircleEntity)
    assert moved_circle.center_mm == pytest.approx((0, 3))
    assert tangent_on_curves(moved_line, moved_circle)
    if kind == "concentric":
        assert moved_other.center_mm == pytest.approx(moved_circle.center_mm)
    else:
        assert moved_other.radius_mm == pytest.approx(moved_circle.radius_mm)


@pytest.mark.parametrize("kind", ("concentric", "equal"))
def test_saved_drag_local_circle_relation_replays_and_reopens(
    tmp_path: Path, kind: Literal["concentric", "equal"]
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.geom.sketch_constraints import solve_sketch_constraint

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    other = CircleEntity(uuid4().hex, (0, 2) if kind == "concentric" else (8, 5), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        kind,
        (
            SketchGeometryReference(circle.entity_id, "geometry"),
            SketchGeometryReference(other.entity_id, "geometry"),
        ),
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle, other))
    for sketch in (first, second):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    result = solve_sketch_constraint(second, constraint)
    assert result.status == "success"
    loaded.bus.execute("sketch.constraint.add", result.command_params(second, constraint), "local")
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before = services.kernel.sketches
    original, solved, anchors = app.prepare_cross_sketch_drag(
        services, second.sketch_id, SketchGeometryReference(circle.entity_id, "center"), (0, 3)
    )
    app.commit_cross_sketch_drag(services, loaded, original, solved, anchors, session_identity=17)
    path = tmp_path / "circle-relation.mc.json"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert {item.sketch_id: item for item in services.kernel.sketches} == {
        item.sketch_id: item for item in solved
    }
    app.open_app_document(services, path)
    assert {item.sketch_id: item for item in services.kernel.sketches} == {
        item.sketch_id: item for item in solved
    }


@pytest.mark.parametrize("kind", ("concentric", "equal"))
def test_save_draft_with_cross_tangency_and_local_circle_relation(
    tmp_path: Path, kind: Literal["concentric", "equal"]
) -> None:
    from mycad import app
    from mycad.commands.validation import validate_params
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    other = CircleEntity(uuid4().hex, (0, 2) if kind == "concentric" else (8, 5), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        kind,
        (
            SketchGeometryReference(circle.entity_id, "geometry"),
            SketchGeometryReference(other.entity_id, "geometry"),
        ),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle, other), (constraint,))
    with pytest.raises(ValidationError):
        validate_params(
            services.registry.get("sketch.create", version=8),
            draft.to_state_mapping(),
            defs=services.registry.schema_defs,
        )
    app.commit_new_sketch(services, loaded, saved, session_identity=17)
    app.commit_new_sketch(
        services,
        loaded,
        draft,
        session_identity=17,
        cross_tangent_pairs=((line.entity_id, circle.entity_id),),
    )
    assert len(services.kernel.cross_sketch_tangencies) == 1
    assert services.kernel.sketches[-1].constraints == (constraint,)
    path = tmp_path / "cross-local.mc.json"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert len(services.kernel.sketches) == 1
    loaded.bus.redo()
    app.open_app_document(services, path)
    assert services.kernel.sketches[-1].constraints == (constraint,)
    assert len(services.kernel.cross_sketch_tangencies) == 1


def test_save_draft_rejects_unsatisfied_local_circle_relation() -> None:
    from mycad import app
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (4, 0), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "concentric",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (constraint,))
    with pytest.raises(ValidationError, match="几何校验"):
        app.commit_new_sketch(services, loaded, sketch, session_identity=17)
    assert not services.kernel.sketches and not loaded.document.commands


@pytest.mark.parametrize("kind", ("horizontal", "coincident"))
def test_save_draft_with_user_line_relation_and_cross_tangency(
    tmp_path: Path, kind: Literal["horizontal", "coincident"]
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    saved_line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    draft_circle = CircleEntity(uuid4().hex, (0, 2), 2)
    draft_line = LineEntity(uuid4().hex, (-5, 8), (5, 8))
    other = LineEntity(uuid4().hex, (5, 8), (8, 10))
    refs = (
        (SketchGeometryReference(draft_line.entity_id, "geometry"),)
        if kind == "horizontal"
        else (
            SketchGeometryReference(draft_line.entity_id, "end"),
            SketchGeometryReference(other.entity_id, "start"),
        )
    )
    relation = SketchConstraint(uuid4().hex, kind, refs)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (draft_circle, draft_line, other), (relation,))
    app.commit_new_sketch(services, loaded, saved, session_identity=17)
    app.commit_new_sketch(
        services,
        loaded,
        draft,
        session_identity=17,
        cross_tangent_pairs=((saved_line.entity_id, draft_circle.entity_id),),
    )
    path = tmp_path / "local-lines.mc.json"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.sketches[-1].constraints == (relation,)


def test_save_draft_with_user_tangency_and_cross_tangency() -> None:
    from mycad import app

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    saved_line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    draft_line = LineEntity(uuid4().hex, (-5, 4), (5, 4))
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(draft_line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle, draft_line), (relation,))
    app.commit_new_sketch(services, loaded, saved, session_identity=17)
    app.commit_new_sketch(
        services,
        loaded,
        draft,
        session_identity=17,
        cross_tangent_pairs=((saved_line.entity_id, circle.entity_id),),
    )
    assert services.kernel.sketches[-1].constraints == (relation,)
    assert len(services.kernel.cross_sketch_tangencies) == 1


def test_mixed_handle_drag_propagates_local_coincidence() -> None:
    from mycad import app
    from mycad.core.fillet_curves import tangent_on_curves

    services = app.build_app(discoverers=[])
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    second = LineEntity(uuid4().hex, (10, 0), (10, 5))
    coincidence = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (coincidence,))
    saved_result, draft_result, anchors = app.prepare_mixed_handle_drag(
        services,
        (saved,),
        draft,
        ((circle.entity_id, first.entity_id),),
        (),
        CrossSketchRef(draft.sketch_id, second.entity_id),
        SketchGeometryReference(second.entity_id, "start"),
        (10, 1),
    )
    moved_first, moved_second = draft_result.entities
    moved_circle = saved_result[0].entities[0]
    assert isinstance(moved_first, LineEntity) and isinstance(moved_second, LineEntity)
    assert isinstance(moved_circle, CircleEntity)
    assert moved_first.end_mm == pytest.approx(moved_second.start_mm)
    assert moved_second.start_mm == pytest.approx((10, 1))
    assert tangent_on_curves(moved_first, moved_circle)
    assert {item.entity_id for item in anchors} == {first.entity_id, second.entity_id}


def test_handle_drag_solves_multiple_cross_sketch_tangencies() -> None:
    from mycad import app

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    lower = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    upper = LineEntity(uuid4().hex, (-10, 4), (10, 4))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (lower,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    third = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (upper,))
    for sketch in (first, second, third):
        loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    relations = (
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(first.sketch_id, lower.entity_id),
            CrossSketchRef(second.sketch_id, circle.entity_id),
            "line_left",
        ),
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(third.sketch_id, upper.entity_id),
            CrossSketchRef(second.sketch_id, circle.entity_id),
            "line_right",
        ),
    )
    for relation in relations:
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before = services.kernel.sketches
    original, solved, anchors = app.prepare_cross_sketch_drag(
        services, first.sketch_id, SketchGeometryReference(lower.entity_id, "start"), (-10, 1)
    )
    validate_tangency_component(solved, relations, first.sketch_id)
    app.commit_cross_sketch_drag(services, loaded, original, solved, anchors, session_identity=17)
    validate_tangency_component(services.kernel.sketches, relations, first.sketch_id)
    loaded.bus.undo()
    assert services.kernel.sketches == before


@pytest.mark.parametrize("fixed", (False, True))
def test_app_anchored_edit_resolves_local_tangent_and_cross_tangent(fixed: bool) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.exceptions import ValidationError
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.geom.sketch_constraints import solve_sketch_constraint

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    local_circle = CircleEntity(uuid4().hex, (-4, 2), 2)
    cross_circle = CircleEntity(uuid4().hex, (4, 2), 2)
    local = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(local_circle.entity_id, "geometry"),
        ),
        source="inferred",
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, local_circle), (local,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (cross_circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=17)
    if fixed:
        first = next(
            sketch for sketch in services.kernel.sketches if sketch.sketch_id == first.sketch_id
        )
        constraint = SketchConstraint(
            uuid4().hex, "fixed", (SketchGeometryReference(line.entity_id, "start"),)
        )
        result = solve_sketch_constraint(first, constraint)
        assert result.status == "success"
        loaded.bus.execute(
            "sketch.constraint.add", result.command_params(first, constraint), "local"
        )
    ref = CrossSketchRef(first.sketch_id, line.entity_id)
    relation = CrossSketchTangency(
        uuid4().hex, ref, CrossSketchRef(second.sketch_id, cross_circle.entity_id), "line_left"
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before = services.kernel.sketches
    moved = replace(line, start_mm=(-10, 1), end_mm=(10, 1))
    proposed = tuple(
        replace(sketch, entities=(moved, sketch.entities[1]))
        if sketch.sketch_id == first.sketch_id
        else sketch
        for sketch in before
    )
    if fixed:
        with pytest.raises(ValidationError, match="constraints"):
            app.commit_cross_sketch_edit(
                services, loaded, before, proposed, (ref,), session_identity=17
            )
        assert services.kernel.sketches == before
        return
    app.commit_cross_sketch_edit(services, loaded, before, proposed, (ref,), session_identity=17)
    result = services.kernel.sketches
    validate_tangency_component(result, (relation,), first.sketch_id)
    updated = next(sketch for sketch in result if sketch.sketch_id == first.sketch_id)
    solved_line, solved_circle = updated.entities
    assert isinstance(solved_line, LineEntity) and isinstance(solved_circle, CircleEntity)
    assert solved_line == moved and tangent_on_curves(solved_line, solved_circle)
    loaded.bus.undo()
    assert services.kernel.sketches == before


def test_mixed_draft_tangency_follows_anchored_saved_edit() -> None:
    from dataclasses import replace

    from mycad import app

    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    moved = replace(line, start_mm=(-10, 1), end_mm=(10, 1))
    proposed = replace(saved, entities=(moved,))
    solved_saved, solved_draft = app.solve_mixed_draft_tangencies(
        (saved,),
        draft,
        (proposed,),
        draft,
        ((line.entity_id, circle.entity_id),),
        (),
        (CrossSketchRef(saved.sketch_id, line.entity_id),),
    )
    assert solved_saved[0].entities == (moved,)
    assert solved_draft.entities != draft.entities
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(saved.sketch_id, line.entity_id),
        CrossSketchRef(draft.sketch_id, circle.entity_id),
        "line_left",
    )
    validate_tangency_component((*solved_saved, solved_draft), (relation,), saved.sketch_id)
    assert saved.entities == (line,) and draft.entities == (circle,)


def test_mixed_delete_removes_existing_cross_relation_atomically() -> None:
    from dataclasses import replace

    from mycad import app

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=17)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=17)
    before = services.kernel.sketches
    draft_line = LineEntity(uuid4().hex, (20, 0), (30, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (draft_line,))
    after = tuple(
        replace(sketch, entities=()) if sketch.sketch_id == first.sketch_id else sketch
        for sketch in before
    )
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        before,
        ((after, replace(draft, entities=())),),
        session_identity=17,
    )
    preview = candidate.preview(current_session_identity=17)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=17), current_session_identity=17
    )
    assert not services.kernel.cross_sketch_tangencies
    loaded.bus.undo()
    assert services.kernel.cross_sketch_tangencies == (relation,)


def test_endpoint_tangency_command_replays_and_rejects_invalid_contact(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    circle = CircleEntity(uuid4().hex, (0, 0), 2)
    arc = ArcEntity(uuid4().hex, (4, 0), 2, 90, 90)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, circle.entity_id),
        CrossSketchRef(second.sketch_id, arc.entity_id),
        "external",
        second_endpoint="end",
    )
    from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet

    def proposal(value: CrossSketchTangency) -> app.ReplayCandidateSession:
        candidate = app.create_replay_candidate(services, loaded, session_identity=0)
        candidate.stage(
            ReplayChangeSet(
                (),
                (
                    ReplayAppend(
                        "drawing.tangency.add",
                        4,
                        {"relation": value.to_mapping(), "revisions": []},
                        "local",
                    ),
                ),
                False,
                target_archive_version=6,
            ),
            current_session_identity=0,
        )
        return candidate

    invalid = proposal(replace(relation, second_endpoint="start"))
    assert invalid.preview(current_session_identity=0).state != "succeeded"
    assert not services.kernel.cross_sketch_tangencies
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.undo()
    assert not services.kernel.cross_sketch_tangencies
    loaded.bus.redo()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    path = tmp_path / "endpoint-tangent.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    validate_tangency_component(services.kernel.sketches, (relation,), first.sketch_id)


@pytest.mark.parametrize("reverse_arc", [False, True])
@pytest.mark.parametrize("polyline_source", [False, True])
@pytest.mark.parametrize("reflect_frame", [False, True])
def test_endpoint_connected_fillet_changes_sweep_when_source_radius_changes(
    reverse_arc: bool, polyline_source: bool, reflect_frame: bool
) -> None:
    from mycad.core.cross_sketch_tangency import project_tangent_entity
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    x = -math.sqrt(7)
    line = (
        PolylineEntity(uuid4().hex, ((-20, 0), (x, 0)))
        if polyline_source
        else LineEntity(uuid4().hex, (-20, 0), (x, 0))
    )
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    arc = ArcEntity(
        uuid4().hex,
        (x, 2),
        2,
        48.59037789072914 if reverse_arc else -90,
        -138.59037789072914 if reverse_arc else 138.59037789072914,
    )
    frame = (
        WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1))
        if reflect_frame
        else WorkPlaneFrame.xy()
    )
    projected_arc = project_tangent_entity(arc, WorkPlaneFrame.xy(), frame)
    assert isinstance(projected_arc, ArcEntity)
    arc = projected_arc
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    third = Sketch(uuid4().hex, frame, (arc,))
    relations = (
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(first.sketch_id, line.entity_id, 0 if polyline_source else None),
            CrossSketchRef(third.sketch_id, arc.entity_id),
            "line_left",
            first_endpoint="end",
            second_endpoint="end" if reverse_arc else "start",
        ),
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(second.sketch_id, circle.entity_id),
            CrossSketchRef(third.sketch_id, arc.entity_id),
            "external",
            second_endpoint="start" if reverse_arc else "end",
        ),
    )
    sketches = (first, second, third)
    validate_tangency_component(sketches, relations, first.sketch_id)
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 2.5, "mm"
    )
    solved = solve_tangency_component_constraint(sketches, relations, second.sketch_id, dimension)
    validate_tangency_component(solved, relations, first.sketch_id)
    updated = next(
        item for sketch in solved for item in sketch.entities if item.entity_id == arc.entity_id
    )
    assert isinstance(updated, ArcEntity)
    assert updated.sweep_angle_deg != pytest.approx(arc.sweep_angle_deg)
    updated = project_tangent_entity(updated, frame, WorkPlaneFrame.xy())
    assert isinstance(updated, ArcEntity)
    updated_line = next(
        item for sketch in solved for item in sketch.entities if item.entity_id == line.entity_id
    )
    assert isinstance(updated_line, LineEntity | PolylineEntity)
    line_end = (
        updated_line.end_mm if isinstance(updated_line, LineEntity) else updated_line.points_mm[-1]
    )
    angle = math.radians(updated.start_angle_deg + (updated.sweep_angle_deg if reverse_arc else 0))
    assert line_end == pytest.approx(
        (
            updated.center_mm[0] + updated.radius_mm * math.cos(angle),
            updated.center_mm[1] + updated.radius_mm * math.sin(angle),
        )
    )


def test_connected_two_arc_endpoints_remain_coincident_on_radius_edit() -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    first_arc = ArcEntity(uuid4().hex, (0, 0), 2, 0, 90)
    second_arc = ArcEntity(uuid4().hex, (4, 0), 2, 90, 90)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first_arc,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (second_arc,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, first_arc.entity_id),
        CrossSketchRef(second.sketch_id, second_arc.entity_id),
        "external",
        first_endpoint="start",
        second_endpoint="end",
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(first_arc.entity_id, "geometry"),),
        2.5,
        "mm",
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), first.sketch_id, dimension
    )
    validate_tangency_component(solved, (relation,), first.sketch_id)
    updated = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id).entities[0]
    assert isinstance(updated, ArcEntity) and updated.radius_mm == pytest.approx(2.5)


@pytest.mark.parametrize("reverse_arc", [False, True])
@pytest.mark.parametrize("reflected", [False, True])
def test_connected_polyline_arc_segment_changes_sweep_and_retains_endpoints(
    reverse_arc: bool, reflected: bool
) -> None:
    from mycad.core.cross_sketch_tangency import project_polyline_entity
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    x = -math.sqrt(7)
    sweep = 138.59037789072914
    end_angle = math.radians(-90 + sweep)
    start = (x, 0.0)
    end = (x + 2 * math.cos(end_angle), 2 + 2 * math.sin(end_angle))
    if reverse_arc:
        start, end = end, start
    polyline = PolylineEntity(
        uuid4().hex,
        (start, end),
        bulges=(math.tan(math.radians(-sweep if reverse_arc else sweep) / 4),),
    )
    line = LineEntity(uuid4().hex, (-20, 0), (x, 0))
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    frame = (
        WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1))
        if reflected
        else WorkPlaneFrame.xy()
    )
    polyline = project_polyline_entity(polyline, WorkPlaneFrame.xy(), frame)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    third = Sketch(uuid4().hex, frame, (polyline,))
    relations = (
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(first.sketch_id, line.entity_id),
            CrossSketchRef(third.sketch_id, polyline.entity_id, 0),
            "line_left",
            first_endpoint="end",
            second_endpoint="end" if reverse_arc else "start",
        ),
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(second.sketch_id, circle.entity_id),
            CrossSketchRef(third.sketch_id, polyline.entity_id, 0),
            "external",
            second_endpoint="start" if reverse_arc else "end",
        ),
    )
    sketches = (first, second, third)
    validate_tangency_component(sketches, relations, first.sketch_id)
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 2.5, "mm"
    )
    solved = solve_tangency_component_constraint(sketches, relations, second.sketch_id, dimension)
    validate_tangency_component(solved, relations, first.sketch_id)
    changed = next(
        item
        for sketch in solved
        for item in sketch.entities
        if item.entity_id == polyline.entity_id
    )
    assert isinstance(changed, PolylineEntity)
    assert changed.bulges[0] != pytest.approx(polyline.bulges[0])
    projected = project_polyline_entity(changed, frame, WorkPlaneFrame.xy())
    updated_line = next(
        item for sketch in solved for item in sketch.entities if item.entity_id == line.entity_id
    )
    assert isinstance(updated_line, LineEntity)
    assert updated_line.end_mm == pytest.approx(projected.points_mm[-1 if reverse_arc else 0])


def test_connected_polyline_arc_segment_replays_linked_dimension(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    x = -math.sqrt(7)
    sweep = 138.59037789072914
    angle = math.radians(-90 + sweep)
    line = LineEntity(uuid4().hex, (-20, 0), (x, 0))
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    polyline = PolylineEntity(
        uuid4().hex,
        ((x, 0), (x + 2 * math.cos(angle), 2 + 2 * math.sin(angle))),
        bulges=(math.tan(math.radians(sweep) / 4),),
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    third = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    relations = (
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(first.sketch_id, line.entity_id),
            CrossSketchRef(third.sketch_id, polyline.entity_id, 0),
            "line_left",
            first_endpoint="end",
            second_endpoint="start",
        ),
        CrossSketchTangency(
            uuid4().hex,
            CrossSketchRef(second.sketch_id, circle.entity_id),
            CrossSketchRef(third.sketch_id, polyline.entity_id, 0),
            "external",
            second_endpoint="end",
        ),
    )
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    for sketch in (first, second, third):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    for relation in relations:
        app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    before = services.kernel.sketches
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 2.5, "mm"
    )
    app.commit_cross_sketch_dimension(
        services, loaded, second.sketch_id, dimension, session_identity=0
    )
    after = services.kernel.sketches
    validate_tangency_component(after, services.kernel.cross_sketch_tangencies, first.sketch_id)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after
    path = tmp_path / "segment-endpoints.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.sketches == after
    assert set(services.kernel.cross_sketch_tangencies) == set(relations)
    validate_tangency_component(after, relations, first.sketch_id)


@pytest.mark.parametrize("reverse_first", [False, True])
@pytest.mark.parametrize("reverse_second", [False, True])
def test_two_polyline_arc_segment_endpoints_remain_connected(
    reverse_first: bool, reverse_second: bool
) -> None:
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    bulge = math.tan(math.pi / 8)
    first_points = ((2, 0), (0, 2))
    second_points = ((4, 2), (2, 0))
    first_arc = PolylineEntity(
        uuid4().hex,
        tuple(reversed(first_points)) if reverse_first else first_points,
        bulges=(-bulge if reverse_first else bulge,),
    )
    second_arc = PolylineEntity(
        uuid4().hex,
        tuple(reversed(second_points)) if reverse_second else second_points,
        bulges=(-bulge if reverse_second else bulge,),
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first_arc,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (second_arc,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, first_arc.entity_id, 0),
        CrossSketchRef(second.sketch_id, second_arc.entity_id, 0),
        "external",
        first_endpoint="end" if reverse_first else "start",
        second_endpoint="start" if reverse_second else "end",
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "radius",
        (SketchGeometryReference(first_arc.entity_id, "segment", 0),),
        2.5,
        "mm",
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), first.sketch_id, dimension
    )
    validate_tangency_component(solved, (relation,), first.sketch_id)
    updated = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id).entities[0]
    assert isinstance(updated, PolylineEntity)
    from mycad.core.polyline_curves import polyline_arc_segment

    assert polyline_arc_segment(updated, 0).radius_mm == pytest.approx(2.5)


def test_local_fillet_and_cross_sketch_tangency_replay_dimension(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    x = -math.sqrt(7)
    line = LineEntity(uuid4().hex, (-20, 0), (x, 0))
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    arc = ArcEntity(uuid4().hex, (x, 2), 2, -90, 138.59037789072914)
    other = CircleEntity(uuid4().hex, (4.2, 5), 2)
    local = (
        SketchConstraint(
            uuid4().hex,
            "tangent",
            (
                SketchGeometryReference(line.entity_id, "geometry"),
                SketchGeometryReference(arc.entity_id, "geometry"),
            ),
            source="inferred",
            first_endpoint="end",
            second_endpoint="start",
        ),
        SketchConstraint(
            uuid4().hex,
            "tangent",
            (
                SketchGeometryReference(circle.entity_id, "geometry"),
                SketchGeometryReference(arc.entity_id, "geometry"),
            ),
            source="inferred",
            second_endpoint="end",
        ),
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle, arc), local)
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, circle.entity_id),
        CrossSketchRef(second.sketch_id, other.entity_id),
        "external",
    )
    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    assert loaded.document.commands[-1].version == 5
    before = services.kernel.sketches
    dimension = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(circle.entity_id, "geometry"),), 2.5, "mm"
    )
    app.commit_cross_sketch_dimension(
        services, loaded, first.sketch_id, dimension, session_identity=0
    )
    after = services.kernel.sketches
    assert loaded.document.commands[-1].version == 9
    validate_tangency_component(after, (relation,), first.sketch_id)
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == after
    path = tmp_path / "mixed-local-cross.my2d"
    save_document(loaded.document, path)
    app.open_app_document(services, path)
    assert services.kernel.sketches == after


@pytest.mark.parametrize("shift_index", [False, True])
def test_mixed_timeline_rebinds_unchanged_saved_polyline_segment(
    tmp_path: Path, shift_index: bool
) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    old_pair = (SketchGeometryReference(source.entity_id, "segment", 0), line.entity_id)
    changed = PolylineEntity(
        source.entity_id,
        ((-5, 0), (0, 0), (10, 0), (10, 8)) if shift_index else ((0, 0), (10, 0), (10, 8), (15, 8)),
        bulges=(0, 1, 0) if shift_index else (1, 0, 0),
    )
    revised = replace(saved, entities=(changed,))
    new_pair = (
        SketchGeometryReference(source.entity_id, "segment", 1 if shift_index else 0),
        line.entity_id,
    )
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((revised,), draft),),
        session_identity=1,
        initial_cross_pairs=(old_pair,),
        cross_pairs_by_step=((new_pair,),),
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert len(relations) == 1 and relations[0].first.segment_index == (1 if shift_index else 0)
    validate_tangency_component(after, relations, saved.sketch_id)
    path = tmp_path / f"source-rebind-{shift_index}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.sketches == (saved, draft)
    assert services.kernel.cross_sketch_tangencies[0].first.segment_index == 0
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


def test_mixed_solver_rejects_ambiguous_proposed_segment_rebinding() -> None:
    from dataclasses import replace

    from mycad import app

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    changed = PolylineEntity(
        source.entity_id, ((0, 0), (10, 0), (0, 0), (10, 0), (10, 8)), bulges=(1, 0, 1, 0)
    )
    proposed = replace(saved, entities=(changed,))
    old_pair = (SketchGeometryReference(source.entity_id, "segment", 0), line.entity_id)
    new_pair = (SketchGeometryReference(source.entity_id, "segment", 2), line.entity_id)
    with pytest.raises(ValueError, match="唯一重绑定"):
        app.solve_mixed_draft_tangencies(
            (saved,),
            draft,
            (proposed,),
            draft,
            (old_pair,),
            (),
            (CrossSketchRef(saved.sketch_id, source.entity_id),),
            proposed_pairs=(new_pair,),
        )


@pytest.mark.parametrize("shift_index", [False, True])
def test_mixed_solver_rebinds_unchanged_saved_segment(shift_index: bool) -> None:
    from dataclasses import replace

    from mycad import app

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    changed = PolylineEntity(
        source.entity_id,
        ((-5, 0), (0, 0), (10, 0), (10, 8)) if shift_index else ((0, 0), (10, 0), (10, 8), (15, 8)),
        bulges=(0, 1, 0) if shift_index else (1, 0, 0),
    )
    proposed = replace(saved, entities=(changed,))
    old_pair = (SketchGeometryReference(source.entity_id, "segment", 0), line.entity_id)
    new_pair = (
        SketchGeometryReference(source.entity_id, "segment", 1 if shift_index else 0),
        line.entity_id,
    )
    solved_saved, solved_draft = app.solve_mixed_draft_tangencies(
        (saved,),
        draft,
        (proposed,),
        draft,
        (old_pair,),
        (),
        (CrossSketchRef(saved.sketch_id, source.entity_id),),
        proposed_pairs=(new_pair,),
    )
    relation = app.draft_cross_relations(solved_saved, solved_draft, (new_pair,))
    validate_tangency_component((*solved_saved, solved_draft), relation, saved.sketch_id)
    assert solved_saved[0].entities[0] == changed


@pytest.mark.parametrize("connected", [False, True])
def test_committed_tangency_segment_rebinds_atomically_and_replays(
    tmp_path: Path, connected: bool
) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = (
        LineEntity(uuid4().hex, (0, -5), (0, 0))
        if connected
        else LineEntity(uuid4().hex, (-5, -5), (15, -5))
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, line.entity_id),
        "line_right" if connected else "line_left",
        first_endpoint="start" if connected else None,
        second_endpoint="end" if connected else None,
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = services.kernel.sketches
    first = next(sketch for sketch in before if sketch.sketch_id == first.sketch_id)
    source = first.entities[0]
    assert isinstance(source, PolylineEntity)
    changed = PolylineEntity(
        source.entity_id, ((-5, 0), *source.points_mm), bulges=(0, *source.bulges)
    )
    revised = replace(first, entities=(changed,))
    state = revised.to_state_mapping()
    revision = {
        "sketch_id": first.sketch_id,
        "base_state_sha256": first.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    rebound = replace(relation, first=replace(relation.first, segment_index=1))
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [revision],
            "remove_tangencies": [relation.relation_id],
            "cross_tangencies": [rebound.to_mapping()],
        },
        "local",
        version=7 if connected else 5,
    )
    after = services.kernel.sketches
    assert services.kernel.cross_sketch_tangencies == (rebound,)
    validate_tangency_component(after, (rebound,), first.sketch_id)
    path = tmp_path / f"committed-rebind-{connected}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == (
        rebound,
    )
    reopened.bus.undo()
    assert services.kernel.sketches == before and services.kernel.cross_sketch_tangencies == (
        relation,
    )
    reopened.bus.redo()
    assert services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == (
        rebound,
    )


@pytest.mark.parametrize("case", ["wrong_segment", "ambiguous", "branch", "endpoint", "entity"])
def test_committed_tangency_rebind_rejects_invalid_mapping_atomically(case: str) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, line.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    current = next(item for item in before if item.sketch_id == first.sketch_id)
    original = current.entities[0]
    assert isinstance(original, PolylineEntity)
    if case == "ambiguous":
        changed = PolylineEntity(
            original.entity_id,
            (
                original.points_mm[0],
                original.points_mm[1],
                original.points_mm[0],
                original.points_mm[1],
                original.points_mm[2],
            ),
            bulges=(original.bulges[0], 0, original.bulges[0], 0),
        )
    else:
        changed = PolylineEntity(
            original.entity_id, ((-5, 0), *original.points_mm), bulges=(0, *original.bulges)
        )
    state = replace(current, entities=(changed,)).to_state_mapping()
    revision = {
        "sketch_id": current.sketch_id,
        "base_state_sha256": current.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    new_ref = replace(
        relation.first,
        segment_index=0 if case == "wrong_segment" else 1,
        entity_id=uuid4().hex if case == "entity" else source.entity_id,
    )
    rebound = replace(
        relation,
        first=new_ref,
        branch="line_right" if case == "branch" else relation.branch,
        first_endpoint="start" if case == "endpoint" else None,
    )
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {
                "revisions": [revision],
                "remove_tangencies": [relation.relation_id],
                "cross_tangencies": [rebound.to_mapping()],
            },
            "local",
            version=7,
        )
    assert services.kernel.sketches == before and tuple(loaded.document.commands) == history
    assert services.kernel.cross_sketch_tangencies == (relation,)


def test_mixed_timeline_rebinds_committed_tangency_and_replays(tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, line.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = services.kernel.sketches
    current = next(item for item in before if item.sketch_id == first.sketch_id)
    original = current.entities[0]
    assert isinstance(original, PolylineEntity)
    changed = PolylineEntity(
        original.entity_id, ((-5, 0), *original.points_mm), bulges=(0, *original.bulges)
    )
    updated = tuple(
        replace(item, entities=(changed,)) if item.sketch_id == current.sketch_id else item
        for item in before
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (30, 30), 1),))
    candidate = app.stage_mixed_drawing_timeline(
        services, loaded, draft, before, ((updated, draft),), session_identity=1
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    after = services.kernel.sketches
    rebound = replace(relation, first=replace(relation.first, segment_index=1))
    assert services.kernel.cross_sketch_tangencies == (rebound,)
    path = tmp_path / "mixed-committed-rebind.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == (
        rebound,
    )
    reopened.bus.undo()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    reopened.bus.redo()
    assert services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == (
        rebound,
    )


def test_linked_edit_rebinds_committed_tangency_and_replays(tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, line.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = services.kernel.sketches
    current = next(item for item in before if item.sketch_id == first.sketch_id)
    original = current.entities[0]
    assert isinstance(original, PolylineEntity)
    changed = PolylineEntity(
        original.entity_id, ((-5, 0), *original.points_mm), bulges=(0, *original.bulges)
    )
    proposed = tuple(
        replace(item, entities=(changed,)) if item.sketch_id == current.sketch_id else item
        for item in before
    )
    app.commit_cross_sketch_edit(
        services,
        loaded,
        before,
        proposed,
        (CrossSketchRef(first.sketch_id, source.entity_id),),
        session_identity=1,
    )
    after = services.kernel.sketches
    rebound = replace(relation, first=replace(relation.first, segment_index=1))
    assert services.kernel.cross_sketch_tangencies == (rebound,)
    path = tmp_path / "linked-committed-rebind.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == (
        rebound,
    )
    reopened.bus.undo()
    assert services.kernel.sketches == before and services.kernel.cross_sketch_tangencies == (
        relation,
    )
    reopened.bus.redo()
    assert services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == (
        rebound,
    )


def test_mixed_timeline_rebinds_committed_relation_across_two_steps() -> None:
    from dataclasses import replace

    from mycad import app

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 8)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (-5, -5), (15, -5))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, line.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = services.kernel.sketches
    current = next(item for item in before if item.sketch_id == first.sketch_id)
    original = current.entities[0]
    assert isinstance(original, PolylineEntity)
    once = PolylineEntity(
        original.entity_id, ((-5, 0), *original.points_mm), bulges=(0, *original.bulges)
    )
    twice = PolylineEntity(
        original.entity_id, ((-10, 0), *once.points_mm), bulges=(0, *once.bulges)
    )

    def with_source(entity: PolylineEntity) -> tuple[Sketch, ...]:
        return tuple(
            replace(item, entities=(entity,)) if item.sketch_id == first.sketch_id else item
            for item in before
        )

    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (30, 30), 1),))
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        before,
        ((with_source(once), draft), (with_source(twice), draft)),
        session_identity=1,
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert services.kernel.cross_sketch_tangencies[0].first.segment_index == 2
    loaded.bus.undo()
    assert services.kernel.cross_sketch_tangencies[0].first.segment_index == 1
    loaded.bus.undo()
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.redo()
    loaded.bus.redo()
    assert services.kernel.cross_sketch_tangencies[0].first.segment_index == 2


def test_closed_polyline_rotation_rejects_old_index_and_replays_rebinding(tmp_path: Path) -> None:
    from dataclasses import replace

    from mycad import app
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True)
    circle = CircleEntity(uuid4().hex, (5, 5), 5)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, polyline.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    current = next(sketch for sketch in before if sketch.sketch_id == first.sketch_id)
    source = current.entities[0]
    assert isinstance(source, PolylineEntity)
    rotated = replace(
        source,
        points_mm=(*source.points_mm[1:], source.points_mm[0]),
        bulges=(*source.bulges[1:], source.bulges[0]) if source.bulges else (),
    )
    state = replace(current, entities=(rotated,)).to_state_mapping()
    revision = {
        "sketch_id": current.sketch_id,
        "base_state_sha256": current.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    with pytest.raises(ValidationError, match="拓扑变化"):
        loaded.bus.execute("drawing.sketch.revise", {"revisions": [revision]}, "local", version=3)
    assert services.kernel.sketches == before and tuple(loaded.document.commands) == history
    assert services.kernel.cross_sketch_tangencies == (relation,)
    rebound = replace(relation, first=replace(relation.first, segment_index=3))
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [revision],
            "remove_tangencies": [relation.relation_id],
            "cross_tangencies": [rebound.to_mapping()],
        },
        "local",
        version=5,
    )
    after = services.kernel.sketches
    assert services.kernel.cross_sketch_tangencies == (rebound,)
    path = tmp_path / "rotated-closed-tangency.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == (
        rebound,
    )
    reopened.bus.undo()
    assert services.kernel.sketches == before and services.kernel.cross_sketch_tangencies == (
        relation,
    )
    reopened.bus.redo()
    assert services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == (
        rebound,
    )


def test_mixed_timeline_replays_inferred_vertex_rebind(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (30, 30), 1),))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    line = LineEntity(uuid4().hex, (0, 0), (-5, 0))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(source.entity_id, "vertex", 0),
            SketchGeometryReference(line.entity_id, "start"),
        ),
        source="inferred",
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, line), (relation,))
    changed = replace(source, points_mm=((-5, -5), *source.points_mm))
    rebound = replace(
        relation, references=(replace(relation.references[0], index=1), relation.references[1])
    )
    updated = replace(draft, entities=(changed, line), constraints=(rebound,))
    candidate = app.stage_mixed_drawing_timeline(
        services, loaded, draft, (saved,), (((saved,), updated),), session_identity=1
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    after = services.kernel.sketches
    assert next(item for item in after if item.sketch_id == draft.sketch_id).constraints == (
        rebound,
    )
    path = tmp_path / "mixed-vertex-rebind.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert next(
        item for item in services.kernel.sketches if item.sketch_id == draft.sketch_id
    ).constraints == (relation,)
    reopened.bus.redo()
    assert services.kernel.sketches == after


@pytest.mark.parametrize("case", ["legacy", "moved", "duplicate", "user", "metadata"])
def test_inferred_vertex_rebind_command_rejects_unproven_changes(case: str) -> None:
    from mycad import app
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    line = LineEntity(uuid4().hex, (0, 0), (-5, 0))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(source.entity_id, "vertex", 0),
            SketchGeometryReference(line.entity_id, "start"),
        ),
        source="user" if case == "user" else "inferred",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, line), (relation,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    current = before[0]
    source, line = current.entities
    assert isinstance(source, PolylineEntity) and isinstance(line, LineEntity)
    points = (
        ((-5, -5), (0, 0), (10, 0), (0, 0), (10, 10))
        if case == "duplicate"
        else ((-5, -5), (1, 0), (10, 0), (10, 10))
        if case == "moved"
        else ((-5, -5), *source.points_mm)
    )
    changed = replace(source, points_mm=points)
    changed_line = replace(line, start_mm=(1, 0)) if case == "moved" else line
    rebound = replace(
        relation,
        references=(replace(relation.references[0], index=1), relation.references[1]),
        source="user" if case == "metadata" else relation.source,
    )
    state = replace(
        current, entities=(changed, changed_line), constraints=(rebound,)
    ).to_state_mapping()
    revision = {
        "sketch_id": current.sketch_id,
        "base_state_sha256": current.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {"revisions": [revision]},
            "local",
            version=8 if case == "legacy" else 10,
        )
    assert services.kernel.sketches == before and tuple(loaded.document.commands) == history


def test_new_inferred_rebind_rejects_changed_other_tangent_source() -> None:
    from mycad import app
    from mycad.core.exceptions import ValidationError
    from mycad.core.replay_proposal import ReplayChangeSet

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    tangent = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(source.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
        source="inferred",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, circle), (tangent,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    if loaded.document.archive_version < 6:
        candidate = app.create_replay_candidate(services, loaded, session_identity=1)
        candidate.stage(
            ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=1
        )
        assert candidate.preview(current_session_identity=1).state == "succeeded"
        candidate.commit(
            candidate.authorize_commit(current_session_identity=1), current_session_identity=1
        )
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    changed = replace(source, points_mm=((-5, 0), *source.points_mm))
    moved_circle = replace(circle, center_mm=(6, 2))
    rebound = replace(
        tangent,
        references=(replace(tangent.references[0], index=1), tangent.references[1]),
    )
    state = replace(
        sketch, entities=(changed, moved_circle), constraints=(rebound,)
    ).to_state_mapping()
    revision = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": sketch.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    with pytest.raises(ValidationError, match="constraints"):
        loaded.bus.execute("drawing.sketch.revise", {"revisions": [revision]}, "local", version=32)
    assert services.kernel.sketches == before and tuple(loaded.document.commands) == history


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("case", ["valid", "legacy", "moved", "duplicate", "metadata"])
def test_user_vertex_rebind_requires_version_and_proof(batch: bool, case: str) -> None:
    from mycad import app
    from mycad.core.exceptions import ValidationError

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(source.entity_id, "vertex", 0),)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,), (fixed,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    current = before[0]
    points = (
        ((-5, -5), (1, 0), (10, 0), (10, 10))
        if case == "moved"
        else ((-5, -5), (0, 0), (10, 0), (0, 0), (10, 10))
        if case == "duplicate"
        else ((-5, -5), *source.points_mm)
    )
    changed = replace(source, points_mm=points)
    rebound = replace(
        fixed,
        references=(replace(fixed.references[0], index=1),),
        source="inferred" if case == "metadata" else "user",
    )
    state = replace(current, entities=(changed,), constraints=(rebound,)).to_state_mapping()
    revision = {
        "sketch_id": current.sketch_id,
        "base_state_sha256": current.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    command = "drawing.sketch.revise" if batch else "sketch.revise"
    version = (31 if batch else 5) if case == "legacy" else (32 if batch else 6)
    params = {"revisions": [revision]} if batch else revision
    if case != "valid":
        with pytest.raises(ValidationError):
            loaded.bus.execute(command, params, "local", version=version)
        assert services.kernel.sketches == before and tuple(loaded.document.commands) == history
    else:
        loaded.bus.execute(command, params, "local", version=version)
        assert services.kernel.sketches[0].constraints == (rebound,)
        loaded.bus.undo()
        assert services.kernel.sketches == before


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("changed_segment", [False, True])
def test_user_segment_rebind_requires_same_directed_geometry(
    batch: bool, changed_segment: bool
) -> None:
    from mycad import app
    from mycad.core.exceptions import ValidationError
    from mycad.core.replay_proposal import ReplayChangeSet

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    length = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(source.entity_id, "segment", 1),),
        10,
        "mm",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,), (length,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    if loaded.document.archive_version < 6:
        candidate = app.create_replay_candidate(services, loaded, session_identity=1)
        candidate.stage(
            ReplayChangeSet((), (), False, target_archive_version=6), current_session_identity=1
        )
        assert candidate.preview(current_session_identity=1).state == "succeeded"
        candidate.commit(
            candidate.authorize_commit(current_session_identity=1), current_session_identity=1
        )
    before, history = services.kernel.sketches, tuple(loaded.document.commands)
    current = before[0]
    end = (10, 11) if changed_segment else (10, 10)
    changed = replace(source, points_mm=((-5, -5), (0, 0), (10, 0), end))
    rebound = replace(length, references=(replace(length.references[0], index=2),))
    state = replace(current, entities=(changed,), constraints=(rebound,)).to_state_mapping()
    revision = {
        "sketch_id": current.sketch_id,
        "base_state_sha256": current.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    command = "drawing.sketch.revise" if batch else "sketch.revise"
    params = {"revisions": [revision]} if batch else revision
    if changed_segment:
        with pytest.raises(ValidationError):
            loaded.bus.execute(command, params, "local", version=32 if batch else 6)
        assert services.kernel.sketches == before and tuple(loaded.document.commands) == history
    else:
        loaded.bus.execute(command, params, "local", version=32 if batch else 6)
        assert services.kernel.sketches[0].constraints == (rebound,)


def test_mixed_tangent_solver_accepts_proven_user_polyline_rebind() -> None:
    from mycad import app
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (10, 20), (10, 30)))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(source.entity_id, "vertex", 4),)
    )
    local_circle = CircleEntity(uuid4().hex, (12, 25), 2)
    local_tangent = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(source.entity_id, "segment", 3),
            SketchGeometryReference(local_circle.entity_id, "geometry"),
        ),
        source="inferred",
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, local_circle), (fixed, local_tangent))
    circle = CircleEntity(uuid4().hex, (12, 25), 2)
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (30, 0), (40, 0)),))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 3),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right",
    )
    points, bulges = polyline_fillet_trimmed_segments(source, 2)
    rounded = replace(source, points_mm=points, bulges=bulges)
    rebound = replace(fixed, references=(replace(fixed.references[0], index=5),))
    rebound_tangent = replace(
        local_tangent,
        references=(replace(local_tangent.references[0], index=4), local_tangent.references[1]),
    )
    revised = replace(
        first, entities=(rounded, local_circle), constraints=(rebound, rebound_tangent)
    )
    solved, solved_draft = app.solve_mixed_draft_tangencies(
        (first, second),
        draft,
        (revised, second),
        draft,
        (),
        (relation,),
        (CrossSketchRef(first.sketch_id, source.entity_id),),
    )
    assert solved_draft == draft
    assert solved[0].constraints == (rebound, rebound_tangent)
    for invalid in (
        replace(revised, constraints=(replace(rebound, source="inferred"), rebound_tangent)),
        replace(
            revised,
            entities=(
                replace(rounded, points_mm=(*rounded.points_mm[:-1], (10, 31))),
                local_circle,
            ),
        ),
    ):
        with pytest.raises(ValueError, match="约束"):
            app.solve_mixed_draft_tangencies(
                (first, second),
                draft,
                (invalid, second),
                draft,
                (),
                (relation,),
                (CrossSketchRef(first.sketch_id, source.entity_id),),
            )


def test_mixed_timeline_replays_inferred_segment_endpoint_rebind(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (30, 30), 1),))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (0, -5), (0, 0))
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(source.entity_id, "segment", 0),
        ),
        source="inferred",
        first_endpoint="end",
        second_endpoint="start",
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, line), (relation,))
    changed = replace(source, points_mm=((0, 5), *source.points_mm), bulges=(0, *source.bulges))
    rebound = replace(
        relation, references=(relation.references[0], replace(relation.references[1], index=1))
    )
    updated = replace(draft, entities=(changed, line), constraints=(rebound,))
    candidate = app.stage_mixed_drawing_timeline(
        services, loaded, draft, (saved,), (((saved,), updated),), session_identity=1
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    after = services.kernel.sketches
    assert loaded.document.commands[-1].version == 10
    assert next(item for item in after if item.sketch_id == draft.sketch_id).constraints == (
        rebound,
    )
    path = tmp_path / "mixed-segment-rebind.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.sketches == after
    reopened.bus.undo()
    assert next(
        item for item in services.kernel.sketches if item.sketch_id == draft.sketch_id
    ).constraints == (relation,)
    reopened.bus.redo()
    assert services.kernel.sketches == after


def test_mixed_timeline_rebinds_local_and_cross_segment_relations_together(tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_document(services, document_type="drawing2d")
    circle = CircleEntity(uuid4().hex, (5, -7), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 5)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (0, -5), (0, 0))
    old_ref = SketchGeometryReference(source.entity_id, "segment", 0)
    new_ref = SketchGeometryReference(source.entity_id, "segment", 1)
    relation = SketchConstraint(
        uuid4().hex,
        "tangent",
        (SketchGeometryReference(line.entity_id, "geometry"), old_ref),
        source="inferred",
        first_endpoint="end",
        second_endpoint="start",
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, line), (relation,))
    changed = replace(source, points_mm=((0, 5), *source.points_mm), bulges=(0, *source.bulges))
    rebound = replace(relation, references=(relation.references[0], new_ref))
    updated = replace(draft, entities=(changed, line), constraints=(rebound,))
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((saved,), updated),),
        session_identity=1,
        initial_cross_pairs=((circle.entity_id, old_ref),),
        cross_pairs_by_step=(((circle.entity_id, new_ref),),),
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert loaded.document.commands[-1].version == 10
    assert len(relations) == 1 and relations[0].second.segment_index == 1
    assert next(item for item in after if item.sketch_id == draft.sketch_id).constraints == (
        rebound,
    )
    validate_tangency_component(after, relations, saved.sketch_id)
    path = tmp_path / "mixed-local-cross-rebind.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert services.kernel.cross_sketch_tangencies[0].second.segment_index == 0
    assert next(
        item for item in services.kernel.sketches if item.sketch_id == draft.sketch_id
    ).constraints == (relation,)
    reopened.bus.redo()
    assert (
        services.kernel.sketches == after and services.kernel.cross_sketch_tangencies == relations
    )


@pytest.mark.parametrize("angle_deg", [0, 30, 90, 180, 270])
@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("rectangle_anchored", [False, True])
def test_rectangle_edge_cross_sketch_solver_preserves_rectangle(
    angle_deg: int, opposite: bool, rectangle_anchored: bool
) -> None:
    from mycad.core.sketch import RectangleEntity
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_anchored

    angle = math.radians(angle_deg)
    frame = WorkPlaneFrame(
        (2, 1, 0),
        (math.cos(angle), math.sin(angle), 0),
        (math.sin(angle), -math.cos(angle), 0)
        if opposite
        else (-math.sin(angle), math.cos(angle), 0),
        (0, 0, -1 if opposite else 1),
    )
    rectangle = RectangleEntity(uuid4().hex, (-10, 0), (10, -10))
    center = frame.local_to_world((0, 3))
    circle = CircleEntity(uuid4().hex, (center[0], center[1]), 2)
    first = Sketch(uuid4().hex, frame, (rectangle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    rect_ref = CrossSketchRef(first.sketch_id, rectangle.entity_id, 0)
    circle_ref = CrossSketchRef(second.sketch_id, circle.entity_id)
    relation = CrossSketchTangency(uuid4().hex, rect_ref, circle_ref, "line_left")
    solved = solve_tangency_component_anchored(
        (first, second),
        (relation,),
        second.sketch_id,
        (rect_ref if rectangle_anchored else circle_ref,),
    )
    validate_tangency_component(solved, (relation,), second.sketch_id)
    changed_rectangle = next(
        sketch for sketch in solved if sketch.sketch_id == first.sketch_id
    ).entities[0]
    assert isinstance(changed_rectangle, RectangleEntity)
    assert changed_rectangle.entity_id == rectangle.entity_id
    if rectangle_anchored:
        assert changed_rectangle.first_corner_mm == pytest.approx(rectangle.first_corner_mm)
        assert changed_rectangle.opposite_corner_mm == pytest.approx(rectangle.opposite_corner_mm)
    assert first.entities == (rectangle,) and second.entities == (circle,)


@pytest.mark.parametrize("opposite", [False, True])
def test_rectangle_tangent_dimension_edit_keeps_local_rectangle(opposite: bool) -> None:
    from mycad.core.sketch import RectangleEntity
    from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint

    angle = math.pi / 6
    frame = WorkPlaneFrame(
        (2, 1, 0),
        (math.cos(angle), math.sin(angle), 0),
        (math.sin(angle), -math.cos(angle), 0)
        if opposite
        else (-math.sin(angle), math.cos(angle), 0),
        (0, 0, -1 if opposite else 1),
    )
    rectangle = RectangleEntity(uuid4().hex, (-10, 0), (10, -10))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(rectangle.entity_id, "segment", 0),),
        20,
        "mm",
    )
    center = frame.local_to_world((0, 2))
    circle = CircleEntity(uuid4().hex, (center[0], center[1]), 2)
    first = Sketch(uuid4().hex, frame, (rectangle,), (dimension,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, rectangle.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), first.sketch_id, replace(dimension, value=24)
    )
    validate_tangency_component(solved, (relation,), first.sketch_id)
    result = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id).entities[0]
    assert isinstance(result, RectangleEntity)
    assert abs(result.opposite_corner_mm[0] - result.first_corner_mm[0]) == pytest.approx(
        24, abs=1e-6
    )
    assert first.entities == (rectangle,)
