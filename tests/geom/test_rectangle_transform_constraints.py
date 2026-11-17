# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Geometry validation for local constraints after rectangle transformation."""

from dataclasses import replace
from uuid import uuid4

import pytest

from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    RectangleTransformEvidence,
    rebind_rectangle_local_constraints,
)
from mycad.core.sketch import RectangleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_edit import rotate_entities
from mycad.geom.sketch_constraints import validate_sketch_revision_geometry


def test_transformed_rectangle_still_rejects_violated_local_horizontal_constraint() -> None:
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 5))
    horizontal = SketchConstraint(
        uuid4().hex, "horizontal", (SketchGeometryReference(rectangle.entity_id, "segment", 0),)
    )
    original = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,), (horizontal,))
    rotated = rotate_entities((rectangle,), (rectangle.entity_id,), (0, 0), 45)
    with pytest.raises(ValueError, match="violates existing constraints"):
        validate_sketch_revision_geometry(original, replace(original, entities=rotated))


@pytest.mark.parametrize("center,allowed", [((10, 10), True), ((0, 0), False)])
def test_fixed_corner_rebind_compares_its_original_position(
    center: tuple[float, float], allowed: bool
) -> None:
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    fixed = SketchConstraint(
        uuid4().hex, "fixed", (SketchGeometryReference(rectangle.entity_id, "end"),)
    )
    original = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (rectangle,), (fixed,))
    rotated = rotate_entities((rectangle,), (rectangle.entity_id,), center, 90)
    evidence = RectangleTransformEvidence(
        CrossSketchRef(original.sketch_id, rectangle.entity_id),
        (0, -1, 1, 0, center[0] + center[1], center[1] - center[0]),
    )
    constraints = rebind_rectangle_local_constraints(original, rotated[0], evidence)
    revised = replace(original, entities=rotated, constraints=constraints)
    assert constraints[0].references != fixed.references
    if allowed:
        assert validate_sketch_revision_geometry(original, revised) == revised
    else:
        with pytest.raises(ValueError, match="violates existing constraints"):
            validate_sketch_revision_geometry(original, revised)
