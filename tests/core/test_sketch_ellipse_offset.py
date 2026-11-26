# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact neutral ellipse data for sketch OFFSET."""

import math
from typing import cast

import pytest


def test_ellipse_arc_keeps_rotation_and_signed_parameter_direction() -> None:
    from mycad.core.sketch import EllipseEntity

    entity = EllipseEntity("44444444444444448444444444444444", (10, 20), 6, 3, 90, 0, -90)
    assert not entity.closed
    assert entity.point_at(0) == pytest.approx((10, 26))
    assert entity.point_at(1) == pytest.approx((13, 20))
    middle = entity.point_at(0.5)
    assert middle == pytest.approx((10 + 3 / math.sqrt(2), 20 + 6 / math.sqrt(2)))


def test_ellipse_rejects_degenerate_and_nonfinite_geometry() -> None:
    from mycad.core.sketch import EllipseEntity

    identity = "44444444444444448444444444444444"
    assert EllipseEntity(identity, (0, 0), 4, 2, 0, 0, 360).closed
    for major, minor, sweep in ((4, 0, 90), (4, 5, 90), (4, 2, 0), (4, 2, 361)):
        with pytest.raises(ValueError):
            EllipseEntity(identity, (0, 0), major, minor, 0, 0, sweep)
    with pytest.raises(ValueError):
        EllipseEntity(identity, (0, 0), 4, 2, math.nan, 0, 90)


def test_ellipse_transformations_preserve_exact_arc_geometry() -> None:
    from mycad.core.sketch import EllipseEntity, SketchEntity
    from mycad.core.sketch_edit import (
        copy_entities,
        mirror_entities,
        move_entities,
        rotate_entities,
        scale_entities,
    )

    source = EllipseEntity("44444444444444448444444444444444", (2, 3), 6, 3, 35, 15, -100)
    entities = (cast("SketchEntity", source),)
    selected = (source.entity_id,)
    moved = move_entities(entities, selected, (4, -2))[0]
    rotated = rotate_entities(entities, selected, (0, 0), 90)[0]
    mirrored = mirror_entities(entities, selected, (0, 0), (1, 0))[0]
    scaled = scale_entities(entities, selected, (0, 0), 2)[0]
    copies = copy_entities(entities, selected, (4, -2))
    assert all(
        isinstance(item, EllipseEntity) for item in (moved, rotated, mirrored, scaled, copies[1])
    )
    assert isinstance(moved, EllipseEntity)
    assert isinstance(rotated, EllipseEntity)
    assert isinstance(mirrored, EllipseEntity)
    assert isinstance(scaled, EllipseEntity)
    for parameter in (0, 0.5, 1):
        x, y = source.point_at(parameter)
        assert moved.point_at(parameter) == pytest.approx((x + 4, y - 2))
        assert rotated.point_at(parameter) == pytest.approx((-y, x))
        assert mirrored.point_at(parameter) == pytest.approx((x, -y))
        assert scaled.point_at(parameter) == pytest.approx((2 * x, 2 * y))
    assert copies[1].entity_id != source.entity_id


def test_ellipse_offset_requires_geometry_adapter() -> None:
    from mycad.core.sketch import EllipseEntity, SketchEntity
    from mycad.core.sketch_edit import offset_entities

    ellipse = EllipseEntity("44444444444444448444444444444444", (0, 0), 6, 3)
    with pytest.raises(ValueError, match="几何"):
        offset_entities((cast("SketchEntity", ellipse),), (ellipse.entity_id,), 1)


def test_new_sketch_command_schema_accepts_ellipse_without_changing_old_version() -> None:
    from mycad.builtin_commands.ellipse_specs import with_ellipse_entities
    from mycad.builtin_commands.specs import BUILTIN_COMMAND_SPECS
    from mycad.commands.validation import schema_matches
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    old = next(s for s in BUILTIN_COMMAND_SPECS if s.id == "sketch.create" and s.version == 3)
    new = next(
        s for s in BUILTIN_COMMAND_SPECS if s.id == "sketch.create" and s.version == 53
    ).params_schema
    params = Sketch("55555555555545558555555555555555", WorkPlaneFrame.xy(), ()).to_state_mapping()
    params["entities"] = [
        {
            "entity_id": "44444444444444448444444444444444",
            "kind": "ellipse",
            "center_mm": [1, 2],
            "major_radius_mm": 6,
            "minor_radius_mm": 3,
            "rotation_deg": 25,
            "start_angle_deg": 10,
            "sweep_angle_deg": -90,
            "construction": False,
            "layer_name": "0",
        }
    ]
    assert not schema_matches(old.params_schema, params)
    assert schema_matches(new, params)
    assert schema_matches(with_ellipse_entities(new), params)


def test_revision_schema_augmentation_reaches_nested_entities() -> None:
    from mycad.builtin_commands.ellipse_specs import with_ellipse_entities
    from mycad.builtin_commands.specs import BUILTIN_COMMAND_SPECS
    from mycad.commands.validation import schema_matches

    old = next(
        s for s in BUILTIN_COMMAND_SPECS if s.id == "drawing.sketch.revise" and s.version == 54
    )
    params = {
        "revisions": [
            {
                "sketch_id": "55555555555545558555555555555555",
                "base_state_sha256": "0" * 64,
                "constraints": [],
                "entities": [
                    {
                        "entity_id": "44444444444444448444444444444444",
                        "kind": "ellipse",
                        "center_mm": [1, 2],
                        "major_radius_mm": 6,
                        "minor_radius_mm": 3,
                        "rotation_deg": 25,
                        "start_angle_deg": 10,
                        "sweep_angle_deg": -90,
                        "construction": False,
                        "layer_name": "0",
                    }
                ],
            }
        ]
    }
    assert not schema_matches(old.params_schema, params)
    assert schema_matches(with_ellipse_entities(old.params_schema), params)


def test_sketch_ellipse_mapping_requires_version_six() -> None:
    from mycad.core.sketch import EllipseEntity, Sketch, WorkPlaneFrame

    ellipse = EllipseEntity("44444444444444448444444444444444", (2, 3), 6, 3, 35, 15, -100)
    sketch = Sketch("55555555555545558555555555555555", WorkPlaneFrame.xy(), (ellipse,))
    with pytest.raises(ValueError, match="version 6"):
        sketch.to_mapping(version=5)
    mapping = sketch.to_mapping(version=6)
    assert Sketch.from_mapping(mapping) == sketch
    assert sketch.to_state_mapping() == mapping


def test_ellipse_projects_into_rotated_or_reflected_coplanar_frame() -> None:
    from mycad.core.cross_sketch_tangency import project_coplanar_entity
    from mycad.core.sketch import EllipseEntity, WorkPlaneFrame

    ellipse = EllipseEntity("44444444444444448444444444444444", (2, 3), 6, 3, 35, 15, -100)
    source = WorkPlaneFrame.xy()
    target = WorkPlaneFrame((3, -1, 0), (0, 1, 0), (1, 0, 0), (0, 0, -1))
    result = project_coplanar_entity(ellipse, source, target)
    assert isinstance(result, EllipseEntity)
    for parameter in (0, 0.3, 1):
        expected = source.local_to_world(ellipse.point_at(parameter))
        assert target.local_to_world(result.point_at(parameter)) == pytest.approx(expected)


def test_ellipse_paper_projection_keeps_analytic_geometry() -> None:
    from uuid import uuid4

    from mycad.core.drawing_projection import DrawingProjectionRequest, EllipseCurve
    from mycad.core.drawing_sketch import project_sketch
    from mycad.core.sketch import EllipseEntity, Sketch, WorkPlaneFrame

    ellipse = EllipseEntity(uuid4().hex, (2, 3), 6, 3, 35, 15, -100)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (ellipse,))
    request = DrawingProjectionRequest(
        uuid4(), "source", 1, source="sketch", sketch_id=sketch.sketch_id
    )
    result = project_sketch(sketch, request)
    assert len(result.curves) == 1
    assert result.curves[0].geometry == EllipseCurve((2, 3), 6, 3, 35, 15, -100)
