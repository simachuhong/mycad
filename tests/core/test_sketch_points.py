# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Point entities have stable, versioned neutral state."""

from typing import cast

import pytest

from mycad.core.sketch import PointEntity, Sketch, SketchEntity, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.core.sketch_edit import copy_entities, move_entities, move_sketch_handle, offset_entities


def test_point_retains_identity_and_position() -> None:
    point = PointEntity("a1" * 16, (2, -3))
    assert point.entity_id == "a1" * 16
    assert point.position_mm == (2, -3)


def test_point_sketch_uses_new_mapping_without_changing_old_formats() -> None:
    point = PointEntity("a1" * 16, (2, -3))
    sketch = Sketch("b2" * 16, WorkPlaneFrame.xy(), (cast("SketchEntity", point),))
    with pytest.raises(ValueError, match="version 4"):
        sketch.to_mapping(version=3)
    assert Sketch.from_mapping(sketch.to_mapping(version=4)) == sketch


def test_point_rejects_nonfinite_coordinate() -> None:
    with pytest.raises(ValueError):
        PointEntity("a1" * 16, (float("nan"), 0))


def test_point_edit_adapters_preserve_identity_and_reject_offset() -> None:
    point = PointEntity("a1" * 16, (2, -3))
    entities = (cast("SketchEntity", point),)
    moved = move_entities(entities, (point.entity_id,), (4, 5))
    assert moved == (PointEntity(point.entity_id, (6, 2)),)
    dragged = move_sketch_handle(
        entities, SketchGeometryReference(point.entity_id, "vertex", 0), (8, 9)
    )
    assert dragged == (PointEntity(point.entity_id, (8, 9)),)
    copied = copy_entities(entities, (point.entity_id,), (1, 1))
    assert len(copied) == 2 and copied[1].entity_id != point.entity_id
    with pytest.raises(ValueError, match="点不支持偏移"):
        offset_entities(entities, (point.entity_id,), 1)
