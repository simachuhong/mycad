# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Proof that a split line uniquely retains a tangent contact."""

from dataclasses import replace
from uuid import uuid4

import pytest

from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    rebind_retained_local_tangencies,
    unique_split_arc_relation_fragment,
    unique_split_line_relation_fragment,
)
from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_edit import break_entity_at_point
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable


def test_line_split_contact_proof_rejects_ambiguity_and_tampering() -> None:
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (8, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    ref = CrossSketchRef(first.sketch_id, line.entity_id)
    other = CrossSketchRef(second.sketch_id, circle.entity_id)
    relation = CrossSketchTangency(uuid4().hex, ref, other, "line_left")
    before = (first, second)
    prefix, suffix = break_entity_at_point(line, (4, 0))
    assert isinstance(suffix, LineEntity)
    updated = (replace(first, entities=(prefix, suffix)), second)
    assert unique_split_line_relation_fragment(before, updated, relation, ref) == replace(
        ref, entity_id=suffix.entity_id
    )
    broken = replace(suffix, end_mm=(9, 0))
    assert (
        unique_split_line_relation_fragment(
            before, (replace(first, entities=(prefix, broken)), second), relation, ref
        )
        is None
    )
    prefix, suffix = break_entity_at_point(line, (8, 0))
    assert (
        unique_split_line_relation_fragment(
            before, (replace(first, entities=(prefix, suffix)), second), relation, ref
        )
        is None
    )


def test_local_line_split_tangent_rejects_ambiguous_contact() -> None:
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
    fragments = break_entity_at_point(line, (8, 0))
    revised = replace(sketch, entities=(*fragments, circle))
    with pytest.raises(ValueError, match="无法唯一确定"):
        rebind_retained_local_tangencies(sketch, revised, allow_split_lines=True)


def test_local_line_split_tangent_preserves_named_layer() -> None:
    line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="A")
    circle = CircleEntity(uuid4().hex, (8, 2), 2, layer_name="A")
    constraint = SketchConstraint(
        uuid4().hex,
        "tangent",
        (
            SketchGeometryReference(line.entity_id, "geometry"),
            SketchGeometryReference(circle.entity_id, "geometry"),
        ),
    )
    layers = SketchLayerTable().add(SketchLayer("A"))
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (line, circle), constraints=(constraint,), layers=layers
    )
    fragments = break_entity_at_point(line, (4, 0))
    revised = replace(sketch, entities=(*fragments, circle))
    rebound = rebind_retained_local_tangencies(sketch, revised, allow_split_lines=True)
    assert rebound[0].references[0].entity_id == fragments[1].entity_id


def test_arc_split_contact_proof_rejects_ambiguity_and_tampering() -> None:
    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, 180)
    circle = CircleEntity(uuid4().hex, (0, 7), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (arc,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    ref = CrossSketchRef(first.sketch_id, arc.entity_id)
    other = CrossSketchRef(second.sketch_id, circle.entity_id)
    relation = CrossSketchTangency(uuid4().hex, ref, other, "external")
    before = (first, second)
    prefix, suffix = break_entity_at_point(arc, (5, 5))
    assert isinstance(suffix, ArcEntity)
    result = unique_split_arc_relation_fragment(
        before, (replace(first, entities=(prefix, suffix)), second), relation, ref
    )
    assert result == replace(ref, entity_id=suffix.entity_id)
    altered = replace(suffix, sweep_angle_deg=suffix.sweep_angle_deg - 1)
    assert (
        unique_split_arc_relation_fragment(
            before, (replace(first, entities=(prefix, altered)), second), relation, ref
        )
        is None
    )
    prefix, suffix = break_entity_at_point(arc, (0, 5))
    assert (
        unique_split_arc_relation_fragment(
            before, (replace(first, entities=(prefix, suffix)), second), relation, ref
        )
        is None
    )


def test_line_split_proof_rejects_off_axis_shared_point_near_endpoint_contact() -> None:
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (10, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    ref = CrossSketchRef(first.sketch_id, line.entity_id)
    relation = CrossSketchTangency(
        uuid4().hex, ref, CrossSketchRef(second.sketch_id, circle.entity_id), "line_left"
    )
    prefix, suffix = break_entity_at_point(line, (4, 0))
    assert isinstance(prefix, LineEntity) and isinstance(suffix, LineEntity)
    prefix = replace(prefix, end_mm=(4, 0.0003))
    suffix = replace(suffix, start_mm=(4, 0.0003))
    assert unique_split_line_relation_fragment(
        (first, second), (replace(first, entities=(prefix, suffix)), second), relation, ref
    ) is None
