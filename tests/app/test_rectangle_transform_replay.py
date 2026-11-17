# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Versioned replay of transformed rectangle tangency references."""

import math
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    RectangleTransformEvidence,
    build_tangency_revisions,
    rebind_committed_tangencies,
    validate_tangency_component,
)
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch import CircleEntity, PolylineEntity, RectangleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_edit import mirror_entities, rotate_entities


@pytest.mark.parametrize("reflected", [False, True])
def test_rectangle_transform_revision_replays_and_rejects_tampering(
    tmp_path: Path, reflected: bool
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (-3, 0), (7, -4))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
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
    original = services.kernel.sketches
    first, second = original
    rectangle = first.entities[0]
    circle = second.entities[0]
    assert isinstance(rectangle, RectangleEntity) and isinstance(circle, CircleEntity)
    entities = (rectangle, circle)
    ids = (rectangle.entity_id, circle.entity_id)
    transformed_rectangle, transformed_circle = (
        mirror_entities(entities, ids, (0, 0), (1, 0))
        if reflected
        else rotate_entities(entities, ids, (0, 0), 90)
    )
    updated = (
        replace(first, entities=(transformed_rectangle,)),
        replace(second, entities=(transformed_circle,)),
    )
    evidence = RectangleTransformEvidence(
        CrossSketchRef(first.sketch_id, rectangle.entity_id),
        (1, 0, 0, -1, 0, 0) if reflected else (0, -1, 1, 0, 0, 0),
    )
    rebound = rebind_committed_tangencies(original, updated, (relation,), (evidence,))[0]
    params = {
        "revisions": list(build_tangency_revisions(original, updated)),
        "remove_tangencies": [relation.relation_id],
        "cross_tangencies": [rebound.to_mapping()],
        "rectangle_transforms": [evidence.to_mapping()],
    }
    wrong = replace(rebound, branch="line_right" if rebound.branch == "line_left" else "line_left")
    for altered in (
        {**params, "cross_tangencies": [wrong.to_mapping()]},
        {
            **params,
            "rectangle_transforms": [replace(evidence, matrix=(1, 0, 0, 1, 0, 0)).to_mapping()],
        },
        {**params, "cross_tangencies": []},
    ):
        with pytest.raises(ValidationError):
            loaded.bus.execute("drawing.sketch.revise", altered, "local", version=28)
        assert services.kernel.sketches == original
        assert services.kernel.cross_sketch_tangencies == (relation,)
    loaded.bus.execute("drawing.sketch.revise", params, "local", version=28)
    assert services.kernel.sketches == updated
    assert services.kernel.cross_sketch_tangencies == (rebound,)
    validate_tangency_component(updated, (rebound,), first.sketch_id)
    path = tmp_path / "rotated-rectangle.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == updated
    assert reopened_services.kernel.cross_sketch_tangencies == (rebound,)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == original
    assert reopened_services.kernel.cross_sketch_tangencies == (relation,)
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == updated
    assert reopened_services.kernel.cross_sketch_tangencies == (rebound,)


@pytest.mark.parametrize(
    ("mode", "local_dimension"),
    [("rotate90", False), ("rotate45", False), ("rotate45", True), ("mirror", False)],
)
def test_rectangle_transform_edit_solves_linked_circle(
    tmp_path: Path, mode: str, local_dimension: bool
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (-3, 0), (7, -4))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    constraints = (
        (
            SketchConstraint(
                uuid4().hex,
                "length",
                (SketchGeometryReference(rectangle.entity_id, "segment", 0),),
                10,
                "mm",
            ),
        )
        if local_dimension
        else ()
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,), constraints)
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
    original = services.kernel.sketches
    first, second = original
    rectangle = first.entities[0]
    assert isinstance(rectangle, RectangleEntity)
    changed = (
        mirror_entities((rectangle,), (rectangle.entity_id,), (0, 0), (1, 0))
        if mode == "mirror"
        else rotate_entities(
            (rectangle,), (rectangle.entity_id,), (0, 0), 45 if mode == "rotate45" else 90
        )
    )
    cosine, sine = math.cos(math.radians(45)), math.sin(math.radians(45))
    evidence = RectangleTransformEvidence(
        CrossSketchRef(first.sketch_id, rectangle.entity_id),
        (1, 0, 0, -1, 0, 0)
        if mode == "mirror"
        else (cosine, -sine, sine, cosine, 0, 0)
        if mode == "rotate45"
        else (0, -1, 1, 0, 0, 0),
    )
    app.commit_cross_sketch_edit(
        services,
        loaded,
        original,
        (replace(first, entities=changed), second),
        (CrossSketchRef(first.sketch_id, rectangle.entity_id),),
        session_identity=1,
        rectangle_transforms=(evidence,),
    )
    assert loaded.document.commands[-1].version == 29
    solved = services.kernel.sketches
    assert solved[0].entities == changed
    if mode == "rotate45":
        assert isinstance(solved[0].entities[0], PolylineEntity)
    if local_dimension:
        assert solved[0].constraints == constraints
    rebound = services.kernel.cross_sketch_tangencies
    validate_tangency_component(solved, rebound, first.sketch_id)
    path = tmp_path / "linked-transform.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == solved
    assert reopened_services.kernel.cross_sketch_tangencies == rebound
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == original
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == solved


def test_local_dimension_rebind_replays_and_rejects_wrong_edge(tmp_path: Path) -> None:
    from copy import deepcopy
    from typing import cast

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, -10))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(rectangle.entity_id, "segment", 0),),
        10,
        "mm",
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,), (dimension,))
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
    original = services.kernel.sketches
    first, second = original
    rotated = rotate_entities(first.entities, (rectangle.entity_id,), (0, 0), 90)
    evidence = RectangleTransformEvidence(
        CrossSketchRef(first.sketch_id, rectangle.entity_id), (0, -1, 1, 0, 0, 0)
    )
    app.commit_cross_sketch_edit(
        services,
        loaded,
        original,
        (replace(first, entities=rotated), second),
        (CrossSketchRef(first.sketch_id, rectangle.entity_id),),
        session_identity=1,
        rectangle_transforms=(evidence,),
    )
    solved = services.kernel.sketches
    assert solved[0].constraints[0].references[0].index == 3
    command = loaded.document.commands[-1]
    assert command.version == 29
    path = tmp_path / "dimension-rebound.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == solved
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == original
    with pytest.raises(ValidationError):
        reopened.bus.execute("drawing.sketch.revise", deepcopy(command.params), "local", version=28)
    assert reopened_services.kernel.sketches == original
    tampered = deepcopy(command.params)
    revisions = cast("list[dict[str, object]]", tampered["revisions"])
    first_revision = next(item for item in revisions if item["sketch_id"] == first.sketch_id)
    constraints = cast("list[dict[str, object]]", first_revision["constraints"])
    refs = cast("list[dict[str, object]]", constraints[0]["references"])
    refs[0]["index"] = 0
    with pytest.raises(ValidationError, match="本地约束"):
        reopened.bus.execute("drawing.sketch.revise", tampered, "local", version=29)
    assert reopened_services.kernel.sketches == original
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == solved


def test_fixed_rectangle_corner_transform_replays(tmp_path: Path) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    circle = CircleEntity(uuid4().hex, (5, -2), 2)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(rectangle.entity_id, "end"),)
    )
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,), (fixed,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, rectangle.entity_id, 0),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_right",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=1)
    original = services.kernel.sketches
    first, second = original
    changed = rotate_entities(first.entities, (rectangle.entity_id,), (10, 10), 90)
    evidence = RectangleTransformEvidence(
        CrossSketchRef(first.sketch_id, rectangle.entity_id), (0, -1, 1, 0, 20, 0)
    )
    app.commit_cross_sketch_edit(
        services,
        loaded,
        original,
        (replace(first, entities=changed), second),
        (CrossSketchRef(first.sketch_id, rectangle.entity_id),),
        session_identity=1,
        rectangle_transforms=(evidence,),
    )
    solved = services.kernel.sketches
    assert solved[0].constraints[0].references[0].kind == "vertex"
    path = tmp_path / "fixed-corner.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == solved
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == original
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == solved


def test_mixed_timeline_replays_rectangle_transform_evidence(tmp_path: Path) -> None:
    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_edit import move_entities

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, -10))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
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
    saved = services.kernel.sketches
    first, second = saved
    line = LineEntity(uuid4().hex, (20, 0), (25, 0))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    changed_rectangle, changed_circle, changed_line = rotate_entities(
        (first.entities[0], second.entities[0], line),
        (rectangle.entity_id, circle.entity_id, line.entity_id),
        (0, 0),
        90,
    )
    updated_saved = (
        replace(first, entities=(changed_rectangle,)),
        replace(second, entities=(changed_circle,)),
    )
    updated_draft = replace(draft, entities=(changed_line,))
    evidence = RectangleTransformEvidence(
        CrossSketchRef(first.sketch_id, rectangle.entity_id), (0, -1, 1, 0, 0, 0)
    )
    moved_saved = tuple(
        replace(
            sketch,
            entities=move_entities(
                sketch.entities,
                tuple(entity.entity_id for entity in sketch.entities),
                (2, 3),
                preserve_rectangle_order=True,
            ),
        )
        for sketch in updated_saved
    )
    moved_draft = replace(
        updated_draft,
        entities=move_entities(updated_draft.entities, (line.entity_id,), (2, 3)),
    )
    with pytest.raises(ValidationError, match="矩形变换依据历史"):
        app.stage_mixed_drawing_timeline(
            services,
            loaded,
            draft,
            saved,
            ((updated_saved, updated_draft), (moved_saved, moved_draft)),
            session_identity=1,
            rectangle_transforms_by_step=((evidence,),),
        )
    with pytest.raises(ValidationError):
        app.stage_mixed_drawing_timeline(
            services,
            loaded,
            draft,
            saved,
            ((updated_saved, updated_draft),),
            session_identity=1,
            rectangle_transforms_by_step=((replace(evidence, matrix=(1, 0, 0, 1, 0, 0)),),),
        )
    assert services.kernel.sketches == saved
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        saved,
        ((updated_saved, updated_draft), (moved_saved, moved_draft)),
        session_identity=1,
        rectangle_transforms_by_step=((evidence,), ()),
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    assert loaded.document.commands[-2].version == 29
    assert services.kernel.sketches == (*moved_saved, moved_draft)
    validate_tangency_component(
        services.kernel.sketches, services.kernel.cross_sketch_tangencies, first.sketch_id
    )
    path = tmp_path / "mixed-rectangle-transform.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (*moved_saved, moved_draft)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (*updated_saved, updated_draft)
    reopened.bus.undo()
    assert reopened_services.kernel.sketches == (*saved, draft)
    reopened.bus.redo()
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (*moved_saved, moved_draft)


@pytest.mark.parametrize("operation", ["rotate45", "rotate90", "mirror"])
def test_mixed_timeline_preserves_distinct_tangencies_to_same_curve(
    tmp_path: Path, operation: str
) -> None:
    from mycad.core.cross_sketch_tangency import map_transformed_rectangle_segments

    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, -20))
    circle = CircleEntity(uuid4().hex, (5, -5), 5)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=1)
    original_saved = services.kernel.sketches
    circle_ref = SketchGeometryReference(circle.entity_id, "geometry")
    initial_pairs = tuple(
        (SketchGeometryReference(rectangle.entity_id, "segment", index), circle_ref)
        for index in (0, 3)
    )
    original_relations = app.draft_cross_relations(original_saved, draft, initial_pairs)
    angle = 45 if operation == "rotate45" else 90
    transformed_rectangle, transformed_circle = (
        mirror_entities(
            (rectangle, circle), (rectangle.entity_id, circle.entity_id), (0, 0), (1, 0)
        )
        if operation == "mirror"
        else rotate_entities(
            (rectangle, circle), (rectangle.entity_id, circle.entity_id), (0, 0), angle
        )
    )
    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    evidence = RectangleTransformEvidence(
        CrossSketchRef(saved.sketch_id, rectangle.entity_id),
        (1, 0, 0, -1, 0, 0) if operation == "mirror" else (cosine, -sine, sine, cosine, 0, 0),
    )
    mapping = map_transformed_rectangle_segments(rectangle, transformed_rectangle, evidence.apply)
    new_pairs = tuple(
        (SketchGeometryReference(rectangle.entity_id, "segment", mapping[index][0]), circle_ref)
        for index in (0, 3)
    )
    changed_saved = (replace(saved, entities=(transformed_rectangle,)),)
    changed_draft = replace(draft, entities=(transformed_circle,))
    candidate = app.stage_mixed_drawing_timeline(
        services,
        loaded,
        draft,
        original_saved,
        ((changed_saved, changed_draft),),
        session_identity=1,
        initial_cross_pairs=initial_pairs,
        cross_pairs_by_step=(new_pairs,),
        rectangle_transforms_by_step=((evidence,),),
    )
    preview = candidate.preview(current_session_identity=1)
    assert preview.state == "succeeded", preview.failure
    candidate.commit(
        candidate.authorize_commit(current_session_identity=1), current_session_identity=1
    )
    relations = services.kernel.cross_sketch_tangencies
    assert {item.relation_id for item in relations} == {
        item.relation_id for item in original_relations
    }
    validate_tangency_component(services.kernel.sketches, relations, saved.sketch_id)
    path = tmp_path / "two-rectangle-tangencies.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.cross_sketch_tangencies == relations
    reopened.bus.undo()
    assert {
        item.relation_id: item for item in reopened_services.kernel.cross_sketch_tangencies
    } == {item.relation_id: item for item in original_relations}
    reopened.bus.redo()
    assert reopened_services.kernel.cross_sketch_tangencies == relations
