# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Equivalent multi-rectangle edits across differently oriented sketch frames."""

import math
from dataclasses import replace
from uuid import uuid4

import pytest

from mycad import app
from mycad.core.cross_sketch_tangency import (
    CrossSketchRef,
    CrossSketchTangency,
    RectangleTransformEvidence,
    validate_tangency_component,
)
from mycad.core.sketch import CircleEntity, RectangleEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_edit import mirror_entities, rotate_entities


@pytest.mark.parametrize("operation", ["rotate45", "rotate90", "mirror"])
@pytest.mark.parametrize("opposite_normal", [False, True])
def test_equal_world_transforms_seed_connected_component_across_frames(
    operation: str, opposite_normal: bool
) -> None:
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    lower = RectangleEntity(uuid4().hex, (-10, 0), (10, -10))
    upper = (
        RectangleEntity(uuid4().hex, (10, 10), (-10, 20))
        if opposite_normal
        else RectangleEntity(uuid4().hex, (10, 10), (20, -10))
    )
    circle = CircleEntity(uuid4().hex, (0, 5), 5)
    rotated_frame = (
        WorkPlaneFrame((0, 0, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
        if opposite_normal
        else WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    sketches = (
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (lower,)),
        Sketch(uuid4().hex, rotated_frame, (upper,)),
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,)),
    )
    for sketch in sketches:
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    for source, owner, index in (
        (lower, sketches[0], 0),
        (upper, sketches[1], 0 if opposite_normal else 3),
    ):
        app.commit_cross_sketch_tangency(
            services,
            loaded,
            CrossSketchTangency(
                uuid4().hex,
                CrossSketchRef(owner.sketch_id, source.entity_id, index),
                CrossSketchRef(sketches[2].sketch_id, circle.entity_id),
                "line_left",
            ),
            session_identity=0,
        )
    before = services.kernel.sketches
    lower_sketch, upper_sketch, circle_sketch = before
    angle = 45 if operation == "rotate45" else 90
    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    if operation == "mirror":
        lower_changed = mirror_entities(lower_sketch.entities, (lower.entity_id,), (0, 0), (1, 0))
        upper_changed = mirror_entities(
            upper_sketch.entities,
            (upper.entity_id,),
            (0, 0),
            (1, 0) if opposite_normal else (0, 1),
        )
        lower_matrix = (1, 0, 0, -1, 0, 0)
        upper_matrix = (1, 0, 0, -1, 0, 0) if opposite_normal else (-1, 0, 0, 1, 0, 0)
    else:
        lower_changed = rotate_entities(lower_sketch.entities, (lower.entity_id,), (0, 0), angle)
        upper_changed = rotate_entities(
            upper_sketch.entities, (upper.entity_id,), (0, 0), -angle if opposite_normal else angle
        )
        lower_matrix = (cosine, -sine, sine, cosine, 0, 0)
        upper_matrix = (cosine, sine, -sine, cosine, 0, 0) if opposite_normal else lower_matrix
    proofs = (
        RectangleTransformEvidence(
            CrossSketchRef(lower_sketch.sketch_id, lower.entity_id), lower_matrix
        ),
        RectangleTransformEvidence(
            CrossSketchRef(upper_sketch.sketch_id, upper.entity_id), upper_matrix
        ),
    )
    app.commit_cross_sketch_edit(
        services,
        loaded,
        before,
        (
            replace(lower_sketch, entities=lower_changed),
            replace(upper_sketch, entities=upper_changed),
            circle_sketch,
        ),
        tuple(item.reference for item in proofs),
        session_identity=0,
        rectangle_transforms=proofs,
    )
    result = services.kernel.sketches
    validate_tangency_component(
        result, services.kernel.cross_sketch_tangencies, lower_sketch.sketch_id
    )
    assert result[0].entities == lower_changed and result[1].entities == upper_changed
    loaded.bus.undo()
    assert services.kernel.sketches == before
    loaded.bus.redo()
    assert services.kernel.sketches == result
