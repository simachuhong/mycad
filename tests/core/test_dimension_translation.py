# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Replay permits dimension placement changes only with the same rigid move."""

from dataclasses import replace
from uuid import uuid4

from mycad.core.dimension_translation import is_rigid_dimension_translation
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_edit import move_entities


def test_rigid_translation_handles_floating_point_roundoff() -> None:
    line = LineEntity(uuid4().hex, (0.1, 0), (1.1, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        1,
        "mm",
        position_mm=(0.3, 2),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    shifted = replace(dimension, position_mm=(0.3 + 0.1, 2))
    moved = replace(
        sketch,
        entities=move_entities(sketch.entities, (line.entity_id,), (0.1, 0)),
        constraints=(shifted,),
    )
    assert is_rigid_dimension_translation(dimension, shifted, sketch, moved)
    distorted = replace(moved, entities=(replace(line, start_mm=(0.2, 0), end_mm=(1.3, 0)),))
    assert not is_rigid_dimension_translation(dimension, shifted, sketch, distorted)
