# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral sketch values validate geometry and preserve durable identities."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace

import pytest

from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
    SketchSupportFace,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

SKETCH_ID = "0a0a0a0a0a0a4a0a8a0a0a0a0a0a0a0a"
ENTITY_IDS = (
    "1b1b1b1b1b1b4b1b8b1b1b1b1b1b1b1b",
    "2c2c2c2c2c2c4c2c8c2c2c2c2c2c2c2c",
    "3d3d3d3d3d3d4d3d8d3d3d3d3d3d3d3d",
    "4e4e4e4e4e4e4e4e8e4e4e4e4e4e4e4e",
    "5f5f5f5f5f5f4f5f8f5f5f5f5f5f5f5f",
)


def test_oblique_workplane_maps_local_coordinates_to_world_without_qt_or_occt() -> None:
    frame = WorkPlaneFrame(
        origin_mm=(10.0, 20.0, 30.0),
        u_axis=(1.0, 0.0, 0.0),
        v_axis=(0.0, 0.0, -1.0),
        normal=(0.0, 1.0, 0.0),
    )

    assert frame.local_to_world((4.0, 5.0)) == (14.0, 20.0, 25.0)
    assert frame.world_to_local((14.0, 20.0, 25.0)) == (4.0, 5.0)


def test_all_initial_entity_types_round_trip_with_stable_ids_and_construction_flag() -> None:
    sketch = Sketch(
        sketch_id=SKETCH_ID,
        frame=WorkPlaneFrame.xy(),
        entities=(
            LineEntity(ENTITY_IDS[0], (0.0, 0.0), (10.0, 0.0)),
            PolylineEntity(
                ENTITY_IDS[1],
                ((0.0, 0.0), (20.0, 0.0), (20.0, 10.0)),
                closed=True,
            ),
            CircleEntity(ENTITY_IDS[2], (5.0, 5.0), 2.0),
            ArcEntity(ENTITY_IDS[3], (5.0, 5.0), 4.0, 15.0, -90.0),
            RectangleEntity(ENTITY_IDS[4], (-5.0, -3.0), (5.0, 3.0), construction=True),
        ),
    )

    restored = Sketch.from_mapping(sketch.to_mapping())

    assert restored == sketch
    assert restored.entities[0].entity_id == ENTITY_IDS[0]
    assert restored.entities[-1].construction is True
    arc = restored.entities[3]
    assert isinstance(arc, ArcEntity)
    assert math.isclose(arc.sweep_angle_deg, -90.0)


def test_sketch_v2_round_trip_preserves_layer_style_and_entity_assignment() -> None:
    layer = SketchLayer(
        "DIMENSIONS",
        color_rgb=(210, 30, 60),
        linetype="DASHED",
        lineweight_mm=0.35,
        visible=False,
        locked=True,
    )
    entity = LineEntity(ENTITY_IDS[0], (0.0, 0.0), (10.0, 0.0), layer_name="DIMENSIONS")
    sketch = Sketch(
        SKETCH_ID,
        WorkPlaneFrame.xy(),
        (entity,),
        layers=SketchLayerTable().add(layer),
    )

    restored = Sketch.from_mapping(sketch.to_mapping())

    assert restored.entities[0].layer_name == "DIMENSIONS"
    assert restored.layers.get("dimensions") == layer


def test_sketch_v1_mapping_defaults_entities_to_default_layer() -> None:
    entity = LineEntity(ENTITY_IDS[0], (0.0, 0.0), (10.0, 0.0))
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (entity,))

    restored = Sketch.from_mapping(sketch.to_mapping(version=1))

    assert restored.entities[0].layer_name == "0"
    assert tuple(layer.name for layer in restored.layers.layers) == ("0",)


def test_face_attached_sketch_round_trips_selector_and_requires_v2() -> None:
    support = SketchSupportFace.from_mapping(
        {
            "surface": "plane",
            "axis": "+Z",
            "center_mm": [5.0, 5.0, 10.0],
            "rank": 0,
        }
    )
    frame = WorkPlaneFrame.from_planar_face(
        (5.0, 5.0, 10.0),
        (0.0, 0.0, 1.0),
    )
    sketch = Sketch(
        SKETCH_ID,
        frame,
        (LineEntity(ENTITY_IDS[0], (0.0, 0.0), (10.0, 0.0)),),
        support_face=support,
    )

    restored = Sketch.from_mapping(sketch.to_mapping())

    assert restored.support_face == support
    assert restored.frame == frame
    with pytest.raises(ValueError, match="version 1"):
        sketch.to_mapping(version=1)


def test_face_attached_workplane_builds_a_right_handed_frame_for_oblique_normal() -> None:
    frame = WorkPlaneFrame.from_planar_face(
        (2.0, 3.0, 4.0),
        (0.0, 1.0, 1.0),
        u_hint=(1.0, 0.0, 0.0),
    )

    assert frame.origin_mm == (2.0, 3.0, 4.0)
    assert frame.normal == pytest.approx((0.0, 2**-0.5, 2**-0.5))
    assert frame.u_axis == pytest.approx((1.0, 0.0, 0.0))
    assert frame.v_axis == pytest.approx((0.0, 2**-0.5, -(2**-0.5)))


def test_sketch_rejects_entity_reference_to_missing_layer() -> None:
    entity = LineEntity(ENTITY_IDS[0], (0.0, 0.0), (10.0, 0.0), layer_name="MISSING")

    with pytest.raises(ValueError, match="missing layer"):
        Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (entity,))


@pytest.mark.parametrize(
    ("entity_factory", "message"),
    [
        (lambda: LineEntity(ENTITY_IDS[0], (1.0, 2.0), (1.0, 2.0)), "distinct"),
        (lambda: CircleEntity(ENTITY_IDS[0], (0.0, 0.0), 0.0), "positive"),
        (lambda: ArcEntity(ENTITY_IDS[0], (0.0, 0.0), 2.0, 0.0, 0.0), "sweep"),
        (
            lambda: PolylineEntity(ENTITY_IDS[0], ((0.0, 0.0), (1.0, 0.0)), closed=True),
            "at least 3",
        ),
        (
            lambda: RectangleEntity(ENTITY_IDS[0], (0.0, 0.0), (5.0, 0.0)),
            "nonzero width and height",
        ),
    ],
)
def test_degenerate_sketch_entities_are_rejected(
    entity_factory: Callable[[], SketchEntity], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (entity_factory(),))


def test_duplicate_entity_identity_is_rejected_instead_of_retargeting_references() -> None:
    entity = LineEntity(ENTITY_IDS[0], (0.0, 0.0), (1.0, 0.0))

    with pytest.raises(ValueError, match="unique"):
        Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (entity, entity))


def test_self_intersecting_closed_polyline_is_rejected_with_geometry_context() -> None:
    with pytest.raises(ValueError, match="self-intersect"):
        PolylineEntity(
            ENTITY_IDS[0],
            ((0.0, 0.0), (10.0, 10.0), (0.0, 8.0), (9.0, 0.0)),
            closed=True,
        )


def test_sketch_mapping_rejects_an_unknown_geometry_kind() -> None:
    raw = {
        "sketch_id": SKETCH_ID,
        "frame": WorkPlaneFrame.xy().to_mapping(),
        "entities": [
            {"entity_id": ENTITY_IDS[0], "kind": "unsupported-curve", "construction": False}
        ],
    }

    with pytest.raises(ValueError, match="unsupported geometry kind"):
        Sketch.from_mapping(raw)


def test_dimension_revision_preserves_identity_order_and_other_constraints() -> None:
    dimension = SketchConstraint(
        ENTITY_IDS[1], "radius", (SketchGeometryReference(ENTITY_IDS[0], "geometry"),), 5.0, "mm"
    )
    fixed = SketchConstraint(
        ENTITY_IDS[2], "fixed", (SketchGeometryReference(ENTITY_IDS[0], "center"),)
    )
    entity = CircleEntity(ENTITY_IDS[0], (0.0, 0.0), 5.0)
    sketch = Sketch(SKETCH_ID, WorkPlaneFrame.xy(), (entity,), (dimension, fixed))
    revised = replace(dimension, value=7.0)
    result = sketch.with_updated_constraint(revised, (replace(entity, radius_mm=7.0),))
    assert result.constraints == (revised, fixed)
    assert result.entities[0].entity_id == entity.entity_id
    assert sketch.constraints == (dimension, fixed)
    with pytest.raises(ValueError, match="missing"):
        sketch.with_updated_constraint(
            replace(revised, constraint_id=ENTITY_IDS[3]), sketch.entities
        )
    with pytest.raises(ValueError, match="kind|references"):
        sketch.with_updated_constraint(replace(revised, kind="diameter"), sketch.entities)
    with pytest.raises(ValueError, match="dimension"):
        sketch.with_updated_constraint(fixed, sketch.entities)
