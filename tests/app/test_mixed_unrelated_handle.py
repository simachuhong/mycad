# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Unrelated mixed-edit anchors cannot conceal changes to tangent sources."""

from dataclasses import replace
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.cross_sketch_tangency import CrossSketchRef
from mycad.core.sketch import CircleEntity, LineEntity, PointEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference


def test_unanchored_tangent_source_change_is_rejected() -> None:
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    point = PointEntity(uuid4().hex, (30, 5))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, point))
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    altered = replace(
        saved,
        entities=(replace(line, start_mm=(-10, 1)), replace(point, position_mm=(32, 8))),
    )
    with pytest.raises(ValueError, match="未指定为目标"):
        app.solve_mixed_draft_tangencies(
            (saved,),
            draft,
            (altered,),
            draft,
            ((line.entity_id, circle.entity_id),),
            (),
            (CrossSketchRef(saved.sketch_id, point.entity_id),),
        )


@pytest.mark.parametrize("same_component", [True, False])
def test_unrelated_anchor_cannot_violate_its_fixed_constraint(same_component: bool) -> None:
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    point = PointEntity(uuid4().hex, (30, 5))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(point.entity_id, "vertex", 0),)
    )
    saved = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (line, point) if same_component else (point,), (fixed,)
    )
    other = () if same_component else (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)),)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    altered = replace(
        saved,
        entities=(line, replace(point, position_mm=(32, 8)))
        if same_component
        else (replace(point, position_mm=(32, 8)),),
    )
    with pytest.raises(ValueError, match="violates existing constraints"):
        app.solve_mixed_draft_tangencies(
            (*other, saved),
            draft,
            (*other, altered),
            draft,
            ((line.entity_id, circle.entity_id),),
            (),
            (CrossSketchRef(saved.sketch_id, point.entity_id),),
        )


@pytest.mark.parametrize("same_component", [True, False])
def test_unrelated_anchor_refreshes_reference_dimension(same_component: bool) -> None:
    line = LineEntity(uuid4().hex, (-10, 0), (10, 0))
    first = PointEntity(uuid4().hex, (30, 5))
    second = PointEntity(uuid4().hex, (33, 9))
    circle = CircleEntity(uuid4().hex, (0, 2), 2)
    dimension = SketchConstraint(
        uuid4().hex,
        "distance",
        (
            SketchGeometryReference(first.entity_id, "vertex", 0),
            SketchGeometryReference(second.entity_id, "vertex", 0),
        ),
        5,
        "mm",
        driving=False,
    )
    saved = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (line, first, second) if same_component else (first, second),
        (dimension,),
    )
    other = () if same_component else (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)),)
    draft = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    altered = replace(
        saved,
        entities=(line, replace(first, position_mm=(30, 9)), second)
        if same_component
        else (replace(first, position_mm=(30, 9)), second),
    )
    result, resulting_draft = app.solve_mixed_draft_tangencies(
        (*other, saved),
        draft,
        (*other, altered),
        draft,
        ((line.entity_id, circle.entity_id),),
        (),
        (CrossSketchRef(saved.sketch_id, first.entity_id),),
    )
    assert result[-1].constraints[0].value == pytest.approx(3)
    assert result[0].entities[0] == line
    assert resulting_draft == draft
