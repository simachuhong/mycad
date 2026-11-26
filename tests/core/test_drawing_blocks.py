# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent 2D block values and deterministic expansion."""

from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

import pytest

from mycad.core.drawing_blocks import BlockDefinition, BlockInstance, expand_block
from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable
from mycad.core.sketch import (
    ArcEntity,
    EllipseEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    SketchEntity,
    SplineEntity,
)


def test_block_expansion_uses_instance_transform_layers_and_stable_identities() -> None:
    line = LineEntity(uuid4().hex, (1, 0), (3, 0))
    text = DrawingText(uuid4().hex, "A", (1, 1), kind="mtext", box_width_mm=3)
    definition = BlockDefinition(uuid4().hex, "Example", (line,), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 20), 90, 2, "Detail")
    styles = TextStyleTable((TextStyle(height_mm=4),), "standard")
    result = expand_block(definition, instance, styles)
    assert len(result.entities) == len(result.texts) == 1
    geometry = result.entities[0]
    assert isinstance(geometry, LineEntity)
    assert geometry.start_mm == pytest.approx((10, 22))
    assert geometry.end_mm == pytest.approx((10, 26))
    assert geometry.layer_name == "Detail"
    transformed_text = result.texts[0]
    assert transformed_text.position_mm == pytest.approx((8, 22))
    assert transformed_text.rotation_deg == pytest.approx(90)
    assert transformed_text.height_mm == pytest.approx(8)
    assert transformed_text.box_width_mm == pytest.approx(6)
    assert transformed_text.layer_name == "Detail"
    assert expand_block(definition, instance, styles) == result
    other = expand_block(
        definition,
        BlockInstance(uuid4().hex, definition.definition_id, (10, 20), 90, 2, "Detail"),
        styles,
    )
    assert other.entities[0].entity_id != geometry.entity_id
    assert other.texts[0].text_id != transformed_text.text_id


def test_block_expansion_preserves_curves_and_nonzero_layers() -> None:
    point_ids = tuple(uuid4().hex for _ in range(4))
    arc = ArcEntity(uuid4().hex, (0, 0), 2, 30, 90, layer_name="Other")
    ellipse = EllipseEntity(uuid4().hex, (1, 0), 3, 1, 20)
    spline = SplineEntity(uuid4().hex, ((0, 0), (1, 0), (1, 1), (2, 1)), point_ids=point_ids)
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (2, 1))
    definition = BlockDefinition(uuid4().hex, "Curves", (arc, ellipse, spline, rectangle), ())
    assert BlockDefinition.from_mapping(definition.to_mapping()) == definition
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), 45, 2, "Insert")
    expanded = expand_block(definition, instance, TextStyleTable())
    result_arc, result_ellipse, result_spline, result_rectangle = expanded.entities
    assert isinstance(result_arc, ArcEntity) and result_arc.radius_mm == pytest.approx(4)
    assert result_arc.start_angle_deg == pytest.approx(75) and result_arc.layer_name == "Other"
    assert isinstance(
        result_ellipse, EllipseEntity
    ) and result_ellipse.major_radius_mm == pytest.approx(6)
    assert result_ellipse.minor_radius_mm == pytest.approx(
        2
    ) and result_ellipse.rotation_deg == pytest.approx(65)
    assert isinstance(result_spline, SplineEntity)
    assert len(result_spline.point_ids) == 4 and not set(result_spline.point_ids) & set(point_ids)
    assert isinstance(result_rectangle, PolylineEntity) and result_rectangle.closed
    second = expand_block(
        definition,
        BlockInstance(uuid4().hex, definition.definition_id, (0, 0), 45, 2, "Insert"),
        TextStyleTable(),
    )
    assert isinstance(second.entities[2], SplineEntity)
    assert not set(result_spline.point_ids) & set(second.entities[2].point_ids)


@pytest.mark.parametrize("scale", [0, -1, float("nan"), float("inf"), True])
def test_block_instance_rejects_invalid_scale(scale: float) -> None:
    with pytest.raises(ValueError):
        BlockInstance(uuid4().hex, uuid4().hex, (0, 0), 0, scale, "0")


def test_block_instance_rejects_invalid_coordinate_and_rotation() -> None:
    with pytest.raises(ValueError):
        BlockInstance(uuid4().hex, uuid4().hex, (10**1000, 0))
    with pytest.raises(ValueError):
        BlockInstance(uuid4().hex, uuid4().hex, (0, 0), float("nan"))


def test_block_values_roundtrip_and_reject_invalid_records() -> None:
    line = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="Detail")
    text = DrawingText(uuid4().hex, "label", (1, 1))
    definition = BlockDefinition(uuid4().hex, "Shared", (line,), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (3, 4), 15, 2, "Detail")
    assert BlockDefinition.from_mapping(definition.to_mapping()) == definition
    assert BlockInstance.from_mapping(instance.to_mapping()) == instance
    with pytest.raises(ValueError):
        BlockDefinition.from_mapping({**definition.to_mapping(), "unexpected": True})
    with pytest.raises(ValueError):
        BlockInstance.from_mapping({**instance.to_mapping(), "scale": -1})
    with pytest.raises(ValueError):
        expand_block(definition, BlockInstance(uuid4().hex, uuid4().hex, (0, 0)), TextStyleTable())


@pytest.mark.parametrize("kind", ["geometry", "text"])
def test_block_definition_rejects_member_uuid_aliases(kind: str) -> None:
    identity = uuid4().hex
    if kind == "geometry":
        item = LineEntity(identity, (0, 0), (2, 0))
        with pytest.raises(ValueError, match="duplicate block geometry identity"):
            BlockDefinition(
                uuid4().hex, "Block", (item, replace(item, entity_id=str(UUID(identity)))), ()
            )
    else:
        text = DrawingText(identity, "A", (0, 0))
        with pytest.raises(ValueError, match="duplicate block text identity"):
            BlockDefinition(
                uuid4().hex, "Block", (), (text, replace(text, text_id=str(UUID(identity))))
            )


def test_block_definition_preserves_existing_member_identity_representations() -> None:
    identity = str(uuid4())
    line = LineEntity(identity, (0, 0), (2, 0))
    text = DrawingText(UUID(identity).hex, "A", (0, 0))
    definition = BlockDefinition(uuid4().hex, "Block", (line,), (text,))
    restored = BlockDefinition.from_mapping(definition.to_mapping())
    assert restored == definition
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    assert expand_block(restored, instance, TextStyleTable()) == expand_block(
        definition, instance, TextStyleTable()
    )


def test_block_definition_is_immutable_and_rejects_duplicate_members() -> None:
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    source = [line]
    definition = BlockDefinition(
        uuid4().hex, "Shared", cast("tuple[SketchEntity, ...]", source), ()
    )
    source.clear()
    assert definition.entities == (line,)
    with pytest.raises(ValueError):
        BlockDefinition(uuid4().hex, "Shared", (line, line), ())
    with pytest.raises(ValueError):
        BlockDefinition(uuid4().hex, "Shared", (), ())


def test_block_definition_normalizes_coplanar_geometry_and_base_point() -> None:
    from mycad.core.drawing_blocks import make_block_definition
    from mycad.core.sketch import WorkPlaneFrame

    frame = WorkPlaneFrame((10, 20, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    line = LineEntity(uuid4().hex, (1, 2), (3, 2))
    text = DrawingText(uuid4().hex, "A", (8, 21))
    definition = make_block_definition(uuid4().hex, "Projected", ((line, frame),), (text,), (8, 21))
    local_line = definition.entities[0]
    assert isinstance(local_line, LineEntity)
    assert local_line.start_mm == pytest.approx((0, 0))
    assert local_line.end_mm == pytest.approx((0, 2))
    assert definition.texts[0].position_mm == pytest.approx((0, 0))
    reverse = WorkPlaneFrame((0, 0, 0), (1, 0, 0), (0, -1, 0), (0, 0, -1))
    with pytest.raises(ValueError, match="方向|同向"):
        make_block_definition(uuid4().hex, "Bad", ((line, reverse),), (), (0, 0))
    offset = WorkPlaneFrame((0, 0, 1), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    with pytest.raises(ValueError):
        make_block_definition(uuid4().hex, "Bad", ((line, offset),), (), (0, 0))


def test_collection_state_validates_block_definitions_instances_and_groups() -> None:
    from dataclasses import replace

    from mycad.core.drawing_collection_state import DrawingCollectionState
    from mycad.core.drawing_groups import DrawingGroup, DrawingGroupTable, DrawingObjectRef

    line = LineEntity(uuid4().hex, (0, 0), (1, 0))
    definition = BlockDefinition(uuid4().hex, "Shared", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    state = DrawingCollectionState(DrawingGroupTable((group,)), (definition,), (instance,))
    assert state.block_definitions == (definition,) and state.block_instances == (instance,)
    with pytest.raises(ValueError, match="名称|name"):
        replace(
            state,
            block_definitions=(
                definition,
                replace(definition, definition_id=uuid4().hex, name="shared"),
            ),
        )
    with pytest.raises(ValueError, match="定义|definition"):
        replace(state, block_definitions=())
    with pytest.raises(ValueError, match="实例|instance"):
        replace(state, block_instances=())
    with pytest.raises(ValueError, match="身份|identity"):
        replace(state, block_instances=(instance, instance))


def test_block_derived_identity_preserves_actual_uuid_representation() -> None:
    source_id = uuid4()
    first = LineEntity(source_id.hex, (0, 0), (1, 0))
    second = LineEntity(str(source_id), (0, 1), (1, 1))
    definition = BlockDefinition(uuid4().hex, "Aliases", (first, second), ())
    instance_id = uuid4()
    first_instance = BlockInstance(instance_id.hex, definition.definition_id, (0, 0))
    second_instance = BlockInstance(str(instance_id), definition.definition_id, (0, 0))
    first_result = expand_block(definition, first_instance, TextStyleTable())
    second_result = expand_block(definition, second_instance, TextStyleTable())
    assert first_result.entities[0].entity_id != first_result.entities[1].entity_id
    assert not {item.entity_id for item in first_result.entities}.intersection(
        item.entity_id for item in second_result.entities
    )


def test_rotated_far_from_origin_rectangle_block_expands_with_area() -> None:
    import math

    rectangle = RectangleEntity(uuid4().hex, (1e9, 1e9), (1e9 + 1, 1e9 + 2))
    definition = BlockDefinition(uuid4().hex, "Far rectangle", (rectangle,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 7), 30)
    result = expand_block(definition, instance, TextStyleTable())
    entity = result.entities[0]
    assert isinstance(entity, PolylineEntity) and entity.closed
    lengths = [
        math.dist(entity.points_mm[index], entity.points_mm[(index + 1) % 4]) for index in range(4)
    ]
    assert lengths == pytest.approx((1, 2, 1, 2), abs=1e-6)
    assert expand_block(definition, instance, TextStyleTable()) == result


def test_rotated_extreme_rectangle_block_retains_finite_vertices() -> None:
    import math

    rectangle = RectangleEntity(uuid4().hex, (0, 0), (1e200, 1e200))
    definition = BlockDefinition(uuid4().hex, "Extreme", (rectangle,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), 30)
    entity = expand_block(definition, instance, TextStyleTable()).entities[0]
    assert isinstance(entity, PolylineEntity) and entity.closed
    assert all(math.isfinite(value) for point in entity.points_mm for value in point)
