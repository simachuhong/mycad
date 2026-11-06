# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Part-sketch draft annotations retain their constraint identity and units."""

from uuid import uuid4

from mycad.core.sketch import CircleEntity, LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.ui.part_sketch_dimensions import draft_dimension_leaders, draft_dimensions


def test_all_supported_draft_dimension_labels_keep_id_and_explicit_position() -> None:
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    circle = CircleEntity(uuid4().hex, (20, 0), 5)
    line_ref = SketchGeometryReference(first.entity_id, "geometry")
    line2_ref = SketchGeometryReference(second.entity_id, "geometry")
    start = SketchGeometryReference(first.entity_id, "start")
    end = SketchGeometryReference(first.entity_id, "end")
    circle_ref = SketchGeometryReference(circle.entity_id, "geometry")
    dimensions = (
        SketchConstraint(uuid4().hex, "length", (line_ref,), 10, "mm"),
        SketchConstraint(uuid4().hex, "distance", (start, end), 10, "mm", text_position_mm=(3, 4)),
        SketchConstraint(uuid4().hex, "angle", (line_ref, line2_ref), 90, "deg"),
        SketchConstraint(uuid4().hex, "radius", (circle_ref,), 5, "mm"),
        SketchConstraint(uuid4().hex, "diameter", (circle_ref,), 10, "mm", driving=False),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second, circle), dimensions)
    labels = {item.constraint_id: item for item in draft_dimensions(sketch)}
    assert set(labels) == {item.constraint_id for item in dimensions}
    assert labels[dimensions[1].constraint_id].position == (3, 4, 0)
    assert "90.00°" in labels[dimensions[2].constraint_id].text
    assert "R5.00 mm" in labels[dimensions[3].constraint_id].text
    assert labels[dimensions[4].constraint_id].text == "⌀10.00 mm [参考]"
    leaders = {
        item.constraint_id: item for item in draft_dimension_leaders(sketch, tuple(labels.values()))
    }
    assert dimensions[0].constraint_id in leaders
    assert len(leaders[dimensions[0].constraint_id].segments) >= 3
    assert dimensions[3].constraint_id in leaders
    assert (
        labels[dimensions[3].constraint_id].position
        in leaders[dimensions[3].constraint_id].segments[-1]
    )
    assert len(leaders[dimensions[2].constraint_id].segments) >= 8
