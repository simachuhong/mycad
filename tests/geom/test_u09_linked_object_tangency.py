# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Solve a new tangent constraint while preserving existing relations."""

from uuid import uuid4

from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    validate_tangency_component,
)
from mycad.core.fillet_curves import tangent_on_curves
from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.geom.cross_sketch_tangency import solve_tangency_component_constraint


def test_linked_component_solves_new_tangency() -> None:
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first_circle = CircleEntity(uuid4().hex, (5, 4), 2)
    second_circle = CircleEntity(uuid4().hex, (15, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, first_circle))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (second_circle,))
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, second_circle.entity_id),
        "line_left",
    )
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(first_circle.entity_id, "geometry"),
        ),
    )
    solved = solve_tangency_component_constraint(
        (first, second), (relation,), first.sketch_id, constraint, allow_tangency=True
    )
    result = next(sketch for sketch in solved if sketch.sketch_id == first.sketch_id)
    solved_line, solved_circle = result.entities
    assert isinstance(solved_line, LineEntity)
    assert isinstance(solved_circle, CircleEntity)
    assert tangent_on_curves(solved_line, solved_circle)
    assert constraint in result.constraints
    validate_tangency_component(solved, (relation,), first.sketch_id)


def test_mixed_draft_local_tangency_solves_existing_relation() -> None:
    from mycad import app

    services = app.build_app(discoverers=[])
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first_circle = CircleEntity(uuid4().hex, (5, 4), 2)
    linked_circle = CircleEntity(uuid4().hex, (15, 2), 2)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, first_circle))
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (linked_circle,))
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(first_circle.entity_id, "geometry"),
        ),
    )
    saved_result, draft_result = app.prepare_mixed_draft_local_tangency(
        services, (saved,), draft, ((linked_circle.entity_id, line.entity_id),), constraint
    )
    solved_line, solved_circle = draft_result.entities
    assert isinstance(solved_line, LineEntity) and isinstance(solved_circle, CircleEntity)
    assert tangent_on_curves(solved_line, solved_circle)
    assert constraint in draft_result.constraints
    assert (
        len(
            app.draft_cross_relations(
                saved_result, draft_result, ((linked_circle.entity_id, line.entity_id),)
            )
        )
        == 1
    )
