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


@pytest.mark.parametrize("invalid", ("center", "radius", "lost_contact", "old_version"))
def test_tangent_circle_trim_revision_rejects_invalid_conversion(invalid: str) -> None:
    from mycad.core.sketch import ArcEntity, CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    line = LineEntity(uuid4().hex, (-10, 5), (10, 5))
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle, line), constraints=(constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    arc = ArcEntity(
        circle.entity_id,
        (1, 0) if invalid == "center" else (0, 0),
        6 if invalid == "radius" else 5,
        180 if invalid == "lost_contact" else 270,
        90 if invalid == "lost_contact" else 180,
    )
    state = replace(sketch, entities=(arc, line)).to_state_mapping()
    revision = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": sketch.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise",
            {"revisions": [revision]},
            "local",
            version=38 if invalid == "old_version" else 39,
        )
    assert services.kernel.sketches == (sketch,)


def test_staged_tangent_fragment_rebind_preserves_relation_identity() -> None:
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchGeometryReference
    from mycad.core.sketch_edit import trim_curve_at

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    cutter = LineEntity(uuid4().hex, (2, -2), (2, 2))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline, cutter))
    source_ref = SketchGeometryReference(circle.entity_id, "geometry")
    old_ref = SketchGeometryReference(polyline.entity_id, "segment", 0)
    old_pair = (source_ref, old_ref)
    old_relation = app.draft_cross_relations((saved,), draft, (old_pair,))[0]
    edited = trim_curve_at(
        (*draft.entities, circle),
        (3.5, 0),
        hit_tolerance_mm=0.1,
        target_entity_id=polyline.entity_id,
    )
    revised = replace(
        draft, entities=tuple(item for item in edited if item.entity_id != circle.entity_id)
    )
    new_ref = SketchGeometryReference(revised.entities[1].entity_id, "segment", 0)
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        (saved,),
        (((saved,), revised),),
        session_identity=0,
        initial_cross_pairs=(old_pair,),
        cross_pairs_by_step=(((source_ref, new_ref),),),
    )
    preview = candidate.preview(current_session_identity=0)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=0), current_session_identity=0
    )
    relation = services.kernel.cross_sketch_tangencies[0]
    assert relation.relation_id == old_relation.relation_id
    assert relation.second.entity_id == new_ref.entity_id
    loaded.bus.undo()
    assert services.kernel.cross_sketch_tangencies == (old_relation,)
    loaded.bus.redo()
    assert services.kernel.cross_sketch_tangencies == (relation,)


def test_saved_tangent_fragment_requires_unique_proof_and_version_43() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_edit import trim_curve_at

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    cutter = LineEntity(uuid4().hex, (2, -2), (2, 2))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline, cutter))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, polyline.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    before = services.kernel.sketches
    edited = trim_curve_at(
        (*first.entities, circle),
        (3.5, 0),
        hit_tolerance_mm=0.1,
        target_entity_id=polyline.entity_id,
    )
    entities = tuple(item for item in edited if item.entity_id != circle.entity_id)
    revised = replace(first, entities=entities)
    new_relation = replace(relation, first=replace(relation.first, entity_id=entities[1].entity_id))

    def params(item: Sketch) -> dict[str, object]:
        state = item.to_state_mapping()
        revision = {
            "sketch_id": first.sketch_id,
            "base_state_sha256": first.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }
        return {
            "revisions": [revision],
            "remove_tangencies": [relation.relation_id],
            "cross_tangencies": [new_relation.to_mapping()],
        }

    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params(revised), "local", version=42)
    duplicate = replace(entities[1], entity_id=uuid4().hex)
    ambiguous = replace(revised, entities=(*revised.entities, duplicate))
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params(ambiguous), "local", version=43)
    assert services.kernel.sketches == before
    loaded.bus.execute("drawing.sketch.revise", params(revised), "local", version=43)
    assert services.kernel.cross_sketch_tangencies == (new_relation,)


def test_split_line_tangent_rebind_requires_version_44_and_unique_proof() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_edit import break_entity_at_point

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    fragments = break_entity_at_point(line, (4, 0))
    revised = replace(first, entities=fragments)
    rebound = replace(relation, first=replace(relation.first, entity_id=fragments[1].entity_id))

    def params(sketch: Sketch) -> dict[str, object]:
        state = sketch.to_state_mapping()
        return {
            "revisions": [
                {
                    "sketch_id": first.sketch_id,
                    "base_state_sha256": first.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ],
            "remove_tangencies": [relation.relation_id],
            "cross_tangencies": [rebound.to_mapping()],
        }

    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params(revised), "local", version=43)
    duplicate = replace(fragments[1], entity_id=uuid4().hex)
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise",
            params(replace(revised, entities=(*fragments, duplicate))),
            "local",
            version=44,
        )
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.execute("drawing.sketch.revise", params(revised), "local", version=44)
    assert services.kernel.cross_sketch_tangencies == (rebound,)
    loaded.bus.undo()
    assert services.kernel.cross_sketch_tangencies == (relation,)


def test_split_line_tangent_rebind_rejects_off_axis_history() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (10, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    prefix = replace(line, end_mm=(4, 0.0003))
    suffix = replace(line, entity_id=uuid4().hex, start_mm=(4, 0.0003))
    revised = replace(first, entities=(prefix, suffix))
    rebound = replace(relation, first=replace(relation.first, entity_id=suffix.entity_id))
    state = revised.to_state_mapping()
    params = {
        "revisions": [
            {
                "sketch_id": first.sketch_id,
                "base_state_sha256": first.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ],
        "remove_tangencies": [relation.relation_id],
        "cross_tangencies": [rebound.to_mapping()],
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=44)
    assert services.kernel.sketches == (first, second)
    assert services.kernel.cross_sketch_tangencies == (relation,)


def test_local_split_line_tangent_rebind_requires_version_45() -> None:
    from mycad.core.cross_sketch_tangency import rebind_retained_local_tangencies
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_edit import break_entity_at_point

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle), constraints=(constraint,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    fragments = break_entity_at_point(line, (4, 0))
    revised = replace(sketch, entities=(*fragments, circle))
    revised = replace(
        revised,
        constraints=rebind_retained_local_tangencies(
            sketch, revised, allow_fragment_rebind=True, allow_split_lines=True
        ),
    )
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
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", params, "local", version=44)
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=45)
    assert services.kernel.sketches == (revised,)
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)


def test_tangent_fragment_rebind_requires_unique_proof_and_version_42() -> None:
    from mycad.core.cross_sketch_tangency import rebind_retained_local_tangencies
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_edit import trim_curve_at

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    cutter = LineEntity(uuid4().hex, (2, -2), (2, 2))
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(polyline.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (polyline, circle, cutter), constraints=(constraint,)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    entities = trim_curve_at(
        sketch.entities, (3.5, 0), hit_tolerance_mm=0.1, target_entity_id=polyline.entity_id
    )
    revised = replace(sketch, entities=entities)
    rebound = rebind_retained_local_tangencies(sketch, revised, allow_fragment_rebind=True)
    assert rebound[0].references[0].entity_id != polyline.entity_id
    revised = replace(revised, constraints=rebound)

    def revision(item: Sketch) -> dict[str, object]:
        state = item.to_state_mapping()
        return {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }

    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise", {"revisions": [revision(revised)]}, "local", version=41
        )
    duplicate = replace(entities[1], entity_id=uuid4().hex)
    ambiguous = replace(revised, entities=(*revised.entities, duplicate))
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise", {"revisions": [revision(ambiguous)]}, "local", version=42
        )
    assert services.kernel.sketches == (sketch,)
    loaded.bus.execute(
        "drawing.sketch.revise", {"revisions": [revision(revised)]}, "local", version=42
    )
    assert services.kernel.sketches == (revised,)


def test_trimmed_local_tangent_requires_proven_version_41_rebind() -> None:
    from mycad.core.cross_sketch_tangency import rebind_retained_local_tangencies
    from mycad.core.sketch import CircleEntity, PolylineEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_edit import trim_curve_at

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    circle = CircleEntity(uuid4().hex, (5, -2), 2)
    cutter = LineEntity(uuid4().hex, (8, -1), (8, 11))
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(polyline.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (polyline, circle, cutter), constraints=(constraint,)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    entities = trim_curve_at(
        sketch.entities, (6.5, 0), hit_tolerance_mm=0.1, target_entity_id=polyline.entity_id
    )
    revised = replace(sketch, entities=entities)
    rebound = rebind_retained_local_tangencies(sketch, revised)
    assert rebound[0].references[0].index != 0

    def revision(item: Sketch) -> dict[str, object]:
        state = item.to_state_mapping()
        return {
            "sketch_id": sketch.sketch_id,
            "base_state_sha256": sketch.local_state_digest(),
            "entities": state["entities"],
            "constraints": state["constraints"],
        }

    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise", {"revisions": [revision(revised)]}, "local", version=41
        )
    assert services.kernel.sketches == (sketch,)
    revised = replace(revised, constraints=rebound)
    with pytest.raises(ValidationError):
        loaded.bus.execute(
            "drawing.sketch.revise", {"revisions": [revision(revised)]}, "local", version=40
        )
    loaded.bus.execute(
        "drawing.sketch.revise", {"revisions": [revision(revised)]}, "local", version=41
    )
    assert services.kernel.sketches == (revised,)


def test_trimmed_tangent_polyline_requires_version_40() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity, PolylineEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    polyline = PolylineEntity(uuid4().hex, ((0, -5), (0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, polyline.entity_id, 1),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    before = services.kernel.sketches
    shortened = replace(polyline, points_mm=((0, -5), (0, 0), (8, 0)))
    state = replace(first, entities=(shortened,)).to_state_mapping()
    revision = {
        "sketch_id": first.sketch_id,
        "base_state_sha256": first.local_state_digest(),
        "entities": state["entities"],
        "constraints": state["constraints"],
    }
    with pytest.raises(ValidationError):
        loaded.bus.execute("drawing.sketch.revise", {"revisions": [revision]}, "local", version=39)
    assert services.kernel.sketches == before
    loaded.bus.execute("drawing.sketch.revise", {"revisions": [revision]}, "local", version=40)
    assert services.kernel.sketches[0].entities == (shortened,)
    assert services.kernel.cross_sketch_tangencies == (relation,)


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


@pytest.mark.parametrize("arc_source", [False, True])
def test_mixed_tangent_extension_followed_by_draft_edit_replays(
    tmp_path: Path, arc_source: bool
) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import CircleEntity, PolylineEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(0.2, 0))
    circle = CircleEntity(uuid4().hex, (5, -3) if arc_source else (12, 5), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0 if arc_source else 1),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "external" if arc_source else "line_right",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    saved = services.kernel.sketches
    draft_circle = CircleEntity(uuid4().hex, (30, 30), 1)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (draft_circle,))
    closed, _ = polyline_segment_fillet(source, 0, 1, 0, first_pick=(0, 0), second_pick=(10, 10))
    updated_saved = tuple(
        replace(sketch, entities=(closed,)) if sketch.sketch_id == first.sketch_id else sketch
        for sketch in saved
    )
    moved_draft = replace(draft, entities=(replace(draft_circle, center_mm=(35, 30)),))
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        saved,
        ((updated_saved, draft), (updated_saved, moved_draft)),
        session_identity=1,
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert loaded.document.commands[-2].version == (36 if arc_source else 35)
    after, relations = services.kernel.sketches, services.kernel.cross_sketch_tangencies
    assert relations[0].relation_id == relation.relation_id and relations[
        0
    ].first.segment_index == (1 if arc_source else 2)
    path = tmp_path / "mixed-tangent-extension.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=())
    reopened = app.open_app_document(restored, path)
    assert (
        restored.kernel.sketches == after and restored.kernel.cross_sketch_tangencies == relations
    )
    reopened.bus.undo()
    assert restored.kernel.sketches == (*updated_saved, draft)
    reopened.bus.undo()
    assert restored.kernel.sketches == (*saved, draft)
    assert restored.kernel.cross_sketch_tangencies == (relation,)
    reopened.bus.redo()
    reopened.bus.redo()
    assert (
        restored.kernel.sketches == after and restored.kernel.cross_sketch_tangencies == relations
    )


@pytest.mark.parametrize("reflected", [False, True])
def test_trimmed_arc_tangency_replays_across_rotated_frames(
    tmp_path: Path, reflected: bool
) -> None:
    import math

    from mycad.core.cross_sketch_tangency import (
        CrossSketchRef,
        CrossSketchTangency,
        project_tangent_entity,
    )
    from mycad.core.polyline_curves import polyline_arc_segment
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import CircleEntity, PolylineEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (9.12, -0.04)), bulges=(0.6, 0))
    arc = polyline_arc_segment(source, 0)

    def point(ratio: float) -> tuple[float, float]:
        angle = math.radians(arc.start_angle_deg + ratio * arc.sweep_angle_deg)
        return (
            arc.center_mm[0] + arc.radius_mm * math.cos(angle),
            arc.center_mm[1] + arc.radius_mm * math.sin(angle),
        )

    contact = point(0.1)
    scale = (arc.radius_mm + 1) / arc.radius_mm
    center = tuple(c + (p - c) * scale for c, p in zip(arc.center_mm, contact, strict=True))
    circle = CircleEntity(uuid4().hex, (center[0], center[1]), 1)
    frame = (
        WorkPlaneFrame((10, 5, 0), (0, 1, 0), (1, 0, 0), (0, 0, -1))
        if reflected
        else WorkPlaneFrame((10, 5, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    projected = project_tangent_entity(circle, WorkPlaneFrame.xy(), frame)
    assert isinstance(projected, CircleEntity)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    second = Sketch(uuid4().hex, frame, (projected,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, source.entity_id, 0),
        CrossSketchRef(second.sketch_id, projected.entity_id),
        "external",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    before = services.kernel.sketches
    closed, _ = polyline_segment_fillet(
        source, 0, 1, 0, first_pick=point(0.05), second_pick=source.points_mm[-1]
    )
    state = replace(first, entities=(closed,)).to_state_mapping()
    params = {
        "revisions": [
            {
                "sketch_id": first.sketch_id,
                "base_state_sha256": first.local_state_digest(),
                "entities": state["entities"],
                "constraints": state["constraints"],
            }
        ]
    }
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=37)
    after = services.kernel.sketches
    assert services.kernel.cross_sketch_tangencies == (relation,)
    path = tmp_path / "rotated-trimmed-arc.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=())
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.sketches == after and restored.kernel.cross_sketch_tangencies == (
        relation,
    )
    reopened.bus.undo()
    assert restored.kernel.sketches == before
    with pytest.raises(ValidationError):
        reopened.bus.execute("drawing.sketch.revise", params, "local", version=36)
    assert restored.kernel.sketches == before and restored.kernel.cross_sketch_tangencies == (
        relation,
    )
    reopened.bus.redo()
    assert restored.kernel.sketches == after and restored.kernel.cross_sketch_tangencies == (
        relation,
    )


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


def test_staged_draft_edit_keeps_unchanged_saved_source_and_separate_undo() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0.0, 0.0), (10.0, 0.0))
    point = PointEntity(uuid4().hex, (20.0, 10.0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (point,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), confirmed_by="local")
    moved = replace(draft, entities=(replace(point, position_mm=(22.0, 13.0)),))
    before = loaded.document.commands
    candidate = app.stage_mixed_drawing_timeline(
        services, loaded, draft, (saved,), (((saved,), moved),), session_identity=1
    )
    assert candidate.preview(current_session_identity=1).state == "succeeded"
    assert loaded.document.commands == before
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert services.kernel.sketches == (saved, moved)
    loaded.bus.undo()
    assert services.kernel.sketches == (saved, draft)
    loaded.bus.redo()
    assert services.kernel.sketches == (saved, moved)


def test_staged_draft_edit_rejects_stale_unchanged_saved_source() -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    point = PointEntity(uuid4().hex, (20, 10))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (point,))
    loaded.bus.execute("sketch.create", saved.to_state_mapping(), confirmed_by="local")
    changed = replace(saved, entities=(replace(line, end_mm=(11, 0)),))
    frozen = changed.to_state_mapping()
    update = app.create_replay_candidate(services, loaded, session_identity=1)
    update.stage(
        ReplayChangeSet(
            (),
            (
                ReplayAppend(
                    "sketch.revise",
                    1,
                    {
                        "sketch_id": saved.sketch_id,
                        "base_state_sha256": saved.local_state_digest(),
                        "entities": frozen["entities"],
                        "constraints": frozen["constraints"],
                    },
                    "local",
                ),
            ),
            False,
            6,
        ),
        current_session_identity=1,
    )
    assert update.preview(current_session_identity=1).state == "succeeded"
    update.commit(update.authorize_commit(current_session_identity=1), current_session_identity=1)
    before = loaded.document.commands
    moved = replace(draft, entities=(replace(point, position_mm=(22, 13)),))
    with pytest.raises(ValidationError, match="已提交草图已变化"):
        app.stage_mixed_drawing_timeline(
            services, loaded, draft, (saved,), (((saved,), moved),), session_identity=1
        )
    assert loaded.document.commands == before
    assert services.kernel.sketches == (changed,)


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


def test_rectangle_segment_tangency_uses_new_sketch_version(tmp_path: Path) -> None:
    from mycad.core.sketch import CircleEntity, RectangleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (-10, 0), (10, -10))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    tangent = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(rectangle.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
        source="inferred",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle, circle), (tangent,))
    upgrade = app.create_replay_candidate(services, loaded, session_identity=1)
    upgrade.stage(ReplayChangeSet((), (), False, 6), current_session_identity=1)
    assert upgrade.preview(current_session_identity=1).state == "succeeded"
    upgrade.commit(upgrade.authorize_commit(current_session_identity=1), current_session_identity=1)
    with pytest.raises(ValidationError, match="矩形边相切约束需要新版草图命令"):
        loaded.bus.execute("sketch.create", sketch.to_state_mapping(), "local", version=26)
    assert not services.kernel.sketches
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    assert loaded.document.commands[-1].version == 27
    assert services.kernel.sketches == (sketch,)
    path = tmp_path / "rectangle-tangent.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (sketch,)
    reopened.bus.undo()
    assert not reopened_services.kernel.sketches
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (sketch,)


def test_mixed_draft_with_rectangle_tangency_uses_versioned_replay() -> None:
    from mycad.core.sketch import CircleEntity, RectangleEntity
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    saved_line = LineEntity(uuid4().hex, (30, 0), (40, 0))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    rectangle = RectangleEntity(uuid4().hex, (-10, 0), (10, -10))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    tangent = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(rectangle.entity_id, "segment", 0),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
        source="inferred",
    )
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle, circle), (tangent,))
    moved_line = replace(saved_line, start_mm=(31, 0), end_mm=(41, 0))
    moved = replace(saved, entities=(moved_line,))
    candidate = app.stage_mixed_drawing_timeline(
        services, loaded, draft, (saved,), (((moved,), draft),), session_identity=1
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert [item.version for item in loaded.document.commands[-2:]] == [27, 27]
    assert services.kernel.sketches == (moved, draft)
    loaded.bus.undo()
    assert services.kernel.sketches == (saved, draft)
    loaded.bus.redo()
    assert services.kernel.sketches == (moved, draft)


def test_cross_sketch_rectangle_edge_tangency_version_and_replay(tmp_path: Path) -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity, RectangleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (-10, 0), (10, -10))
    circle = CircleEntity(uuid4().hex, (0, 3), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, rectangle.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    command = loaded.document.commands[-1]
    assert command.id == "drawing.tangency.add" and command.version == 6
    solved = services.kernel.sketches
    loaded.bus.undo()
    with pytest.raises(ValidationError, match="矩形边相切关系需要新版修订命令"):
        loaded.bus.execute("drawing.tangency.add", dict(command.params), "local", version=5)
    assert services.kernel.sketches == (first, second)
    loaded.bus.redo()
    assert services.kernel.sketches == solved
    path = tmp_path / "cross-rectangle-tangent.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == solved
    assert reopened_services.kernel.cross_sketch_tangencies == (relation,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (first, second)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == solved


def test_rectangle_cross_tangency_new_sketch_version_rejects_old_replay() -> None:
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity, RectangleEntity

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (-10, 0), (10, -10))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    upgrade = app.create_replay_candidate(services, loaded, session_identity=1)
    upgrade.stage(ReplayChangeSet((), (), False, 6), current_session_identity=1)
    assert upgrade.preview(current_session_identity=1).state == "succeeded"
    upgrade.commit(upgrade.authorize_commit(current_session_identity=1), current_session_identity=1)
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(saved.sketch_id, rectangle.entity_id, 0),
        CrossSketchRef(draft.sketch_id, circle.entity_id),
        "line_left",
    )
    params = {**draft.to_state_mapping(), "cross_tangencies": [relation.to_mapping()]}
    with pytest.raises(ValidationError, match="矩形边相切关系需要新版草图命令"):
        loaded.bus.execute("sketch.create", params, "local", version=26)
    assert services.kernel.sketches == (saved,)
    loaded.bus.execute("sketch.create", params, "local", version=27)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.undo()
    assert services.kernel.sketches == (saved,)
    loaded.bus.redo()
    assert services.kernel.cross_sketch_tangencies == (relation,)
