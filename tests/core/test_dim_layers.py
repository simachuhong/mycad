# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DIM membership and freeze state remain neutral, durable and independent."""

from dataclasses import replace
from uuid import uuid4

import pytest

from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import SketchLayer


def test_freeze_and_visibility_are_independent_and_legacy_defaults_survive() -> None:
    layer = SketchLayer("DIM", visible=False, frozen=True)
    thawed = replace(layer, frozen=False)
    assert not thawed.visible
    assert not thawed.displayed
    assert SketchLayer.from_mapping(layer.to_mapping()) == layer
    legacy = SketchLayer("0").to_mapping()
    assert "frozen" not in legacy
    assert not SketchLayer.from_mapping(legacy).frozen


def test_new_dimension_can_create_dim_without_moving_its_geometry() -> None:
    line = LineEntity(uuid4().hex, (0, 0), (30, 0))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        30,
        "mm",
        driving=False,
        layer_name="DIM",
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint,))
    assert sketch.layers.get("DIM").displayed
    assert sketch.entities[0].layer_name == "0"
    assert Sketch.from_mapping(sketch.to_mapping(version=3)) == sketch
    assert SketchConstraint.from_mapping(constraint.to_mapping()) == constraint


def test_legacy_dimension_membership_is_not_silently_migrated() -> None:
    constraint = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(uuid4().hex, "geometry"),), 10, "mm"
    )
    assert constraint.layer_name is None
    assert "layer_name" not in constraint.to_mapping()


def test_geometric_relations_cannot_be_moved_to_annotation_layers() -> None:
    with pytest.raises(ValueError, match="dimension"):
        SketchConstraint(
            uuid4().hex,
            "horizontal",
            (SketchGeometryReference(uuid4().hex, "geometry"),),
            layer_name="DIM",
        )


def test_nonexistent_custom_dimension_layer_is_rejected() -> None:
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    constraint = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        layer_name="unknown",
    )
    with pytest.raises(ValueError, match="layer"):
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (constraint,))
