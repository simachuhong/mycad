# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Deterministic, CAD-backend-free sketch edit geometry."""

from __future__ import annotations

import math
from collections.abc import Callable
from uuid import uuid4

import pytest

from mycad.core import sketch_edit
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    RectangleEntity,
    SketchEntity,
)
from mycad.core.sketch_edit import (
    circular_array_entities,
    copy_entities,
    extend_line_at,
    linear_array_entities,
    mirror_entities,
    move_entities,
    offset_entities,
    rotate_entities,
    split_line_at,
    trim_curve_at,
    trim_line_at,
)


def _line(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    construction: bool = False,
    layer_name: str = "0",
) -> LineEntity:
    return LineEntity(uuid4().hex, start, end, construction=construction, layer_name=layer_name)


def test_trim_removes_clicked_side_and_preserves_surviving_entity_identity() -> None:
    target = _line((0.0, 0.0), (20.0, 0.0))
    cutter = _line((10.0, -5.0), (10.0, 5.0))

    result = trim_line_at((target, cutter), (15.0, 0.0), hit_tolerance_mm=0.5)

    assert len(result) == 2
    trimmed = result[0]
    assert isinstance(trimmed, LineEntity)
    assert trimmed.entity_id == target.entity_id
    assert trimmed.start_mm == (0.0, 0.0)
    assert trimmed.end_mm == pytest.approx((10.0, 0.0))
    assert result[1] == cutter


def test_trim_middle_interval_splits_and_assigns_a_new_identity_to_new_fragment() -> None:
    target = _line((0.0, 0.0), (20.0, 0.0))
    first_cutter = _line((5.0, -5.0), (5.0, 5.0))
    second_cutter = _line((15.0, -5.0), (15.0, 5.0))

    result = trim_line_at((target, first_cutter, second_cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    fragments = tuple(item for item in result if isinstance(item, LineEntity))
    assert len(fragments) == 4
    retained_fragments = fragments[:2]
    assert retained_fragments[0].start_mm == (0.0, 0.0)
    assert retained_fragments[0].end_mm == pytest.approx((5.0, 0.0))
    assert retained_fragments[1].start_mm == pytest.approx((15.0, 0.0))
    assert retained_fragments[1].end_mm == (20.0, 0.0)
    assert retained_fragments[0].entity_id == target.entity_id
    assert retained_fragments[1].entity_id != target.entity_id
    assert len({entity.entity_id for entity in fragments}) == len(fragments)
    assert result[2:] == (first_cutter, second_cutter)


def test_trim_open_polyline_segment_splits_path_and_preserves_prefix_identity() -> None:
    target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (2.0, 0.0), (20.0, 0.0)), construction=True)
    first_cutter = _line((5.0, -5.0), (5.0, 5.0))
    second_cutter = _line((15.0, -5.0), (15.0, 5.0))

    result = trim_curve_at((target, first_cutter, second_cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    first, second = result[:2]
    assert isinstance(first, PolylineEntity)
    assert isinstance(second, PolylineEntity)
    assert first.entity_id == target.entity_id
    assert first.points_mm == ((0.0, 0.0), (2.0, 0.0), (5.0, 0.0))
    assert second.entity_id != target.entity_id
    assert second.points_mm == ((15.0, 0.0), (20.0, 0.0))
    assert first.construction and second.construction
    assert not first.closed and not second.closed
    assert result[2:] == (first_cutter, second_cutter)


def test_trim_open_polyline_rejects_closed_paths_or_missing_intersections() -> None:
    closed = PolylineEntity(
        uuid4().hex,
        ((0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)),
        closed=True,
    )
    cutter = _line((5.0, -5.0), (5.0, 5.0))
    closed_entities: tuple[SketchEntity, ...] = (closed, cutter)
    with pytest.raises(ValueError, match="闭合多段线"):
        trim_curve_at(closed_entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    assert closed_entities == (closed, cutter)

    open_path = PolylineEntity(uuid4().hex, ((0.0, 0.0), (20.0, 0.0)))
    open_entities: tuple[SketchEntity, ...] = (open_path,)
    with pytest.raises(ValueError, match="交点"):
        trim_curve_at(open_entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    assert open_entities == (open_path,)


def test_trim_open_polyline_uses_circle_intersections_as_cutters() -> None:
    target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (20.0, 0.0)))
    first_cutter = CircleEntity(uuid4().hex, (5.0, 5.0), 5.0)
    second_cutter = CircleEntity(uuid4().hex, (15.0, 5.0), 5.0)

    result = trim_curve_at((target, first_cutter, second_cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    first, second = result[:2]
    assert isinstance(first, PolylineEntity)
    assert isinstance(second, PolylineEntity)
    assert first.points_mm[-1] == pytest.approx((5.0, 0.0))
    assert second.points_mm[0] == pytest.approx((15.0, 0.0))


@pytest.mark.parametrize(
    ("click", "cutter_x", "expected_points"),
    [
        ((2.0, 0.0), 5.0, ((5.0, 0.0), (10.0, 0.0), (20.0, 0.0))),
        ((18.0, 0.0), 15.0, ((0.0, 0.0), (10.0, 0.0), (15.0, 0.0))),
    ],
)
def test_trim_open_polyline_terminal_interval_to_single_intersection(
    click: tuple[float, float],
    cutter_x: float,
    expected_points: tuple[tuple[float, float], ...],
) -> None:
    target = PolylineEntity(
        uuid4().hex,
        ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0)),
        construction=True,
    )
    cutter = _line((cutter_x, -5.0), (cutter_x, 5.0))

    result = trim_curve_at((target, cutter), click, hit_tolerance_mm=0.5)

    trimmed = result[0]
    assert isinstance(trimmed, PolylineEntity)
    assert trimmed.entity_id == target.entity_id
    assert trimmed.points_mm == expected_points
    assert trimmed.construction
    assert result[1] == cutter


def test_trim_open_polyline_single_intersection_on_internal_segment_splits_path() -> None:
    target = PolylineEntity(
        uuid4().hex,
        ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (20.0, 10.0)),
        construction=True,
    )
    cutter = _line((15.0, -5.0), (15.0, 5.0))

    result = trim_curve_at((target, cutter), (12.0, 0.0), hit_tolerance_mm=0.5)

    prefix, suffix = result[:2]
    assert isinstance(prefix, PolylineEntity)
    assert isinstance(suffix, PolylineEntity)
    assert prefix.entity_id == target.entity_id
    assert prefix.points_mm == ((0.0, 0.0), (10.0, 0.0))
    assert suffix.entity_id != target.entity_id
    assert suffix.points_mm == ((15.0, 0.0), (20.0, 0.0), (20.0, 10.0))
    assert prefix.construction and suffix.construction
    assert result[2] == cutter


@pytest.mark.parametrize(
    ("click", "message"),
    (((5.0, 0.0), "不明确"), ((0.0, 0.0), "区间|顶点|交点")),
)
def test_trim_open_polyline_rejects_intersection_and_vertex_clicks_without_mutation(
    click: tuple[float, float], message: str
) -> None:
    target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (20.0, 0.0)))
    cutter = _line((5.0, -5.0), (5.0, 5.0))
    entities: tuple[SketchEntity, ...] = (target, cutter)

    with pytest.raises(ValueError, match=message):
        trim_curve_at(entities, click, hit_tolerance_mm=0.5)

    assert entities == (target, cutter)


def test_trim_open_polyline_filters_arc_cutters_to_their_valid_sweeps() -> None:
    target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (20.0, 0.0)))
    first_cutter = ArcEntity(uuid4().hex, (5.0, 5.0), 5.0, 250.0, 40.0)
    second_cutter = ArcEntity(uuid4().hex, (15.0, 5.0), 5.0, 250.0, 40.0)

    result = trim_curve_at((target, first_cutter, second_cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    first, second = result[:2]
    assert isinstance(first, PolylineEntity)
    assert isinstance(second, PolylineEntity)
    assert first.points_mm[-1] == pytest.approx((5.0, 0.0))
    assert second.points_mm[0] == pytest.approx((15.0, 0.0))


def test_trim_preserves_original_direction_and_ignores_construction_cutters() -> None:
    target = _line((20.0, 0.0), (0.0, 0.0))
    cutter = LineEntity(uuid4().hex, (10.0, -5.0), (10.0, 5.0), construction=True)

    with pytest.raises(ValueError, match="交点"):
        trim_line_at((target, cutter), (5.0, 0.0), hit_tolerance_mm=0.5)

    regular_cutter = _line((10.0, -5.0), (10.0, 5.0))
    result = trim_line_at((target, regular_cutter), (5.0, 0.0), hit_tolerance_mm=0.5)

    retained = result[0]
    assert isinstance(retained, LineEntity)
    assert retained.entity_id == target.entity_id
    assert retained.start_mm == (20.0, 0.0)
    assert retained.end_mm == pytest.approx((10.0, 0.0))


def test_extend_line_end_to_nearest_intersection_preserves_identity() -> None:
    target = _line((0.0, 0.0), (20.0, 0.0))
    near_cutter = _line((30.0, -5.0), (30.0, 5.0))
    far_cutter = _line((40.0, -5.0), (40.0, 5.0))

    result = extend_line_at((target, near_cutter, far_cutter), (20.0, 0.0), hit_tolerance_mm=0.5)

    extended = result[0]
    assert isinstance(extended, LineEntity)
    assert extended.entity_id == target.entity_id
    assert extended.start_mm == (0.0, 0.0)
    assert extended.end_mm == (30.0, 0.0)
    assert result[1:] == (near_cutter, far_cutter)


def test_extend_line_start_to_intersection_and_reject_invalid_targets() -> None:
    target = _line((0.0, 0.0), (20.0, 0.0))
    cutter = _line((-5.0, -5.0), (-5.0, 5.0))

    result = extend_line_at((target, cutter), (0.0, 0.0), hit_tolerance_mm=0.5)

    extended = result[0]
    assert isinstance(extended, LineEntity)
    assert extended.start_mm == (-5.0, 0.0)
    assert extended.end_mm == (20.0, 0.0)

    with pytest.raises(ValueError, match="端点"):
        extend_line_at((target, cutter), (10.0, 0.0), hit_tolerance_mm=0.5)
    with pytest.raises(ValueError, match="交点"):
        extend_line_at((target,), (20.0, 0.0), hit_tolerance_mm=0.5)


@pytest.mark.parametrize("cutter_kind", ("circle", "arc"))
def test_extend_line_to_nearest_valid_circular_cutter_hit(cutter_kind: str) -> None:
    target = _line((0.0, 0.0), (10.0, 0.0))
    cutter: CircleEntity | ArcEntity = (
        CircleEntity(uuid4().hex, (15.0, 0.0), 2.0)
        if cutter_kind == "circle"
        else ArcEntity(uuid4().hex, (15.0, 0.0), 2.0, 90.0, 180.0)
    )

    result = extend_line_at((target, cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    extended = result[0]
    assert isinstance(extended, LineEntity)
    assert extended.entity_id == target.entity_id
    assert extended.end_mm == pytest.approx((13.0, 0.0))
    assert result[1] == cutter


@pytest.mark.parametrize(
    ("at_start", "expected_points", "cutters"),
    [
        (
            True,
            ((-5.0, 0.0), (2.0, 0.0), (20.0, 0.0)),
            (_line((-5.0, -5.0), (-5.0, 5.0)), _line((-10.0, -5.0), (-10.0, 5.0))),
        ),
        (
            False,
            ((0.0, 0.0), (2.0, 0.0), (25.0, 0.0)),
            (_line((25.0, -5.0), (25.0, 5.0)), _line((30.0, -5.0), (30.0, 5.0))),
        ),
    ],
)
def test_extend_open_polyline_terminal_endpoint_to_nearest_straight_hit(
    at_start: bool,
    expected_points: tuple[tuple[float, float], ...],
    cutters: tuple[LineEntity, LineEntity],
) -> None:
    target = PolylineEntity(
        uuid4().hex,
        ((0.0, 0.0), (2.0, 0.0), (20.0, 0.0)),
        construction=True,
    )
    endpoint = target.points_mm[0] if at_start else target.points_mm[-1]

    result = sketch_edit.extend_curve_at((target, *cutters), endpoint, hit_tolerance_mm=0.5)

    extended = result[0]
    assert isinstance(extended, PolylineEntity)
    assert extended.entity_id == target.entity_id
    assert extended.points_mm == expected_points
    assert not extended.closed
    assert extended.construction
    assert result[1:] == cutters


@pytest.mark.parametrize("cutter_kind", ("circle", "arc"))
def test_extend_open_polyline_terminal_endpoint_to_circular_cutter(cutter_kind: str) -> None:
    target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (2.0, 0.0)))
    cutter: CircleEntity | ArcEntity = (
        CircleEntity(uuid4().hex, (5.0, 0.0), 1.0)
        if cutter_kind == "circle"
        else ArcEntity(uuid4().hex, (5.0, 0.0), 1.0, 90.0, 180.0)
    )

    result = sketch_edit.extend_curve_at(
        (target, cutter), target.points_mm[-1], hit_tolerance_mm=0.5
    )

    extended = result[0]
    assert isinstance(extended, PolylineEntity)
    assert extended.entity_id == target.entity_id
    assert extended.points_mm[0] == (0.0, 0.0)
    assert extended.points_mm[-1] == pytest.approx((4.0, 0.0))
    assert result[1] == cutter


def test_extend_open_polyline_rejects_closed_internal_and_no_hit_without_mutation() -> None:
    open_target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)))
    closed_target = PolylineEntity(
        uuid4().hex,
        ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)),
        closed=True,
    )
    cutter = _line((15.0, -5.0), (15.0, 5.0))
    construction_cutter = _line((15.0, -5.0), (15.0, 5.0), construction=True)
    no_hit = (open_target,)
    construction_only: tuple[SketchEntity, ...] = (open_target, construction_cutter)
    closed_entities: tuple[SketchEntity, ...] = (closed_target, cutter)
    internal_entities: tuple[SketchEntity, ...] = (open_target, cutter)

    with pytest.raises(ValueError, match="开放多段线端点"):
        sketch_edit.extend_curve_at(closed_entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    with pytest.raises(ValueError, match="端点"):
        sketch_edit.extend_curve_at(internal_entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    with pytest.raises(ValueError, match="交点"):
        sketch_edit.extend_curve_at(no_hit, (10.0, 10.0), hit_tolerance_mm=0.5)
    with pytest.raises(ValueError, match="交点"):
        sketch_edit.extend_curve_at(construction_only, (10.0, 10.0), hit_tolerance_mm=0.5)

    assert closed_entities == (closed_target, cutter)
    assert internal_entities == (open_target, cutter)
    assert no_hit == (open_target,)
    assert construction_only == (open_target, construction_cutter)


def test_extend_counterclockwise_arc_start_to_nearest_outside_intersection() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 0.0, 90.0)
    cutter = _line((5.0, -10.0), (5.0, 10.0))

    result = sketch_edit.extend_curve_at((arc, cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    extended = result[0]
    assert isinstance(extended, ArcEntity)
    assert extended.entity_id == arc.entity_id
    assert extended.start_angle_deg == pytest.approx(300.0)
    assert extended.sweep_angle_deg == pytest.approx(150.0)
    assert result[1] == cutter


def test_extend_clockwise_arc_end_to_nearest_outside_intersection() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 90.0, -90.0)
    cutter = _line((-10.0, -5.0), (10.0, -5.0))

    result = sketch_edit.extend_curve_at((arc, cutter), (10.0, 0.0), hit_tolerance_mm=0.5)

    extended = result[0]
    assert isinstance(extended, ArcEntity)
    assert extended.entity_id == arc.entity_id
    assert extended.start_angle_deg == pytest.approx(90.0)
    assert extended.sweep_angle_deg == pytest.approx(-120.0)
    assert result[1] == cutter


def test_extend_arc_rejects_endpoint_without_outside_intersection() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 0.0, 90.0)
    cutter = _line((5.0, 0.0), (15.0, 0.0))
    entities: tuple[SketchEntity, ...] = (arc, cutter)

    with pytest.raises(ValueError, match="延伸方向上没有交点"):
        sketch_edit.extend_curve_at(entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    assert entities == (arc, cutter)


def test_extend_arc_rejects_closing_to_a_full_circle() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 0.0, 350.0)
    cutter = _line((10.0, -5.0), (10.0, 5.0))
    entities: tuple[SketchEntity, ...] = (arc, cutter)
    end = (
        10.0 * math.cos(math.radians(350.0)),
        10.0 * math.sin(math.radians(350.0)),
    )

    with pytest.raises(ValueError, match="整圆"):
        sketch_edit.extend_curve_at(entities, end, hit_tolerance_mm=0.5)
    assert entities == (arc, cutter)


def test_split_line_at_nearest_intersection_preserves_first_fragment_identity() -> None:
    target = _line((0.0, 0.0), (20.0, 0.0))
    first_cutter = _line((5.0, -5.0), (5.0, 5.0))
    second_cutter = _line((15.0, -5.0), (15.0, 5.0))

    result = split_line_at((target, first_cutter, second_cutter), (13.0, 0.0), hit_tolerance_mm=0.5)

    first, second = result[:2]
    assert isinstance(first, LineEntity)
    assert isinstance(second, LineEntity)
    assert first.entity_id == target.entity_id
    assert first.start_mm == (0.0, 0.0)
    assert first.end_mm == pytest.approx((15.0, 0.0))
    assert second.start_mm == pytest.approx((15.0, 0.0))
    assert second.end_mm == (20.0, 0.0)
    assert second.entity_id != target.entity_id
    assert result[2:] == (first_cutter, second_cutter)


def test_split_line_rejects_missing_intersection_without_mutating_input() -> None:
    target = _line((0.0, 0.0), (20.0, 0.0))
    entities = (target,)
    with pytest.raises(ValueError, match="交点"):
        split_line_at(entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    assert entities == (target,)


def test_split_open_polyline_segment_keeps_prefix_identity_and_new_suffix_identity() -> None:
    target = PolylineEntity(uuid4().hex, ((0.0, 0.0), (2.0, 0.0), (20.0, 0.0)), construction=True)
    first_cutter = _line((5.0, -5.0), (5.0, 5.0))
    second_cutter = _line((15.0, -5.0), (15.0, 5.0))

    result = sketch_edit.split_entity_at(
        (target, first_cutter, second_cutter), (13.0, 0.0), hit_tolerance_mm=0.5
    )

    first, second = result[:2]
    assert isinstance(first, PolylineEntity)
    assert isinstance(second, PolylineEntity)
    assert first.entity_id == target.entity_id
    assert first.points_mm == ((0.0, 0.0), (2.0, 0.0), (15.0, 0.0))
    assert not first.closed
    assert first.construction
    assert second.entity_id != target.entity_id
    assert second.points_mm == ((15.0, 0.0), (20.0, 0.0))
    assert not second.closed
    assert second.construction
    assert result[2:] == (first_cutter, second_cutter)


def test_split_closed_polyline_rejects_without_mutating_input() -> None:
    target = PolylineEntity(
        uuid4().hex,
        ((0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)),
        closed=True,
    )
    cutter = _line((5.0, -5.0), (5.0, 5.0))
    entities: tuple[SketchEntity, ...] = (target, cutter)

    with pytest.raises(ValueError, match="闭合多段线"):
        sketch_edit.split_entity_at(entities, (10.0, 0.0), hit_tolerance_mm=0.5)
    assert entities == (target, cutter)


@pytest.mark.parametrize(
    ("entities", "point", "message"),
    [
        ((_line((0.0, 0.0), (20.0, 0.0)),), (10.0, 0.0), "交点"),
        (
            (_line((0.0, 0.0), (20.0, 0.0)), _line((10.0, -5.0), (10.0, 5.0))),
            (10.0, 0.0),
            "不明确",
        ),
        (
            (
                _line((0.0, 0.0), (20.0, 0.0)),
                _line((0.0, 1.0), (20.0, 1.0)),
                _line((5.0, -5.0), (5.0, 5.0)),
            ),
            (10.0, 0.5),
            "不明确",
        ),
    ],
)
def test_trim_rejects_missing_ambiguous_or_intersection_clicks(
    entities: tuple[SketchEntity, ...], point: tuple[float, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        trim_line_at(entities, point, hit_tolerance_mm=0.5)


def test_move_and_copy_transform_all_entity_kinds_without_mutating_input() -> None:
    line = _line((0.0, 0.0), (2.0, 0.0))
    polyline = PolylineEntity(uuid4().hex, ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)))
    circle = CircleEntity(uuid4().hex, (2.0, 2.0), 1.0)
    arc = ArcEntity(uuid4().hex, (3.0, 3.0), 2.0, 30.0, 90.0)
    rectangle = RectangleEntity(uuid4().hex, (0.0, 0.0), (2.0, 1.0))
    entities: tuple[SketchEntity, ...] = (line, polyline, circle, arc, rectangle)
    selected = tuple(entity.entity_id for entity in entities)

    moved = move_entities(entities, selected, (5.0, -2.0))
    copied = copy_entities(entities, selected, (5.0, -2.0))

    assert entities[0] == line
    assert isinstance(moved[0], LineEntity)
    assert moved[0].entity_id == line.entity_id
    assert moved[0].start_mm == (5.0, -2.0)
    assert isinstance(moved[1], PolylineEntity)
    assert moved[1].points_mm == ((5.0, -2.0), (6.0, -2.0), (6.0, -1.0))
    assert isinstance(moved[2], CircleEntity)
    assert moved[2].center_mm == (7.0, 0.0)
    assert isinstance(moved[3], ArcEntity)
    assert moved[3].center_mm == (8.0, 1.0)
    assert isinstance(moved[4], RectangleEntity)
    assert moved[4].first_corner_mm == (5.0, -2.0)
    assert copied[:5] == entities
    clones = copied[5:]
    assert len(clones) == len(entities)
    assert {entity.entity_id for entity in clones}.isdisjoint(selected)
    assert isinstance(clones[0], LineEntity)
    assert clones[0].start_mm == (5.0, -2.0)


def test_draft_transforms_preserve_layer_assignment_on_originals_and_copies() -> None:
    entity = LineEntity(
        uuid4().hex,
        (0.0, 0.0),
        (10.0, 0.0),
        layer_name="OUTLINE",
    )

    moved = move_entities((entity,), (entity.entity_id,), (0.0, 5.0))[0]
    copied = copy_entities((entity,), (entity.entity_id,), (0.0, 5.0))[1]
    offset = offset_entities((entity,), (entity.entity_id,), 2.0)[1]

    assert moved.layer_name == "OUTLINE"
    assert copied.layer_name == "OUTLINE"
    assert offset.layer_name == "OUTLINE"


@pytest.mark.parametrize("operation", ("trim", "split", "extend"))
def test_line_edit_fragments_keep_the_source_layer(operation: str) -> None:
    if operation == "trim":
        target = _line((0.0, 0.0), (20.0, 0.0), layer_name="OUTLINE")
        cutters = (_line((5.0, -5.0), (5.0, 5.0)), _line((15.0, -5.0), (15.0, 5.0)))
        result = trim_curve_at((target, *cutters), (10.0, 0.0), hit_tolerance_mm=0.5)
        fragments = result[:2]
    elif operation == "split":
        target = _line((0.0, 0.0), (20.0, 0.0), layer_name="OUTLINE")
        cutters = (_line((5.0, -5.0), (5.0, 5.0)), _line((15.0, -5.0), (15.0, 5.0)))
        result = split_line_at((target, *cutters), (13.0, 0.0), hit_tolerance_mm=0.5)
        fragments = result[:2]
    else:
        target = _line((0.0, 0.0), (5.0, 0.0), layer_name="OUTLINE")
        cutter = _line((10.0, -5.0), (10.0, 5.0))
        result = extend_line_at((target, cutter), (5.0, 0.0), hit_tolerance_mm=0.5)
        fragments = result[:1]

    assert all(entity.layer_name == "OUTLINE" for entity in fragments)


def test_rotate_and_mirror_preserve_identity_and_curve_orientation() -> None:
    arc = ArcEntity(uuid4().hex, (2.0, 0.0), 1.0, 0.0, 90.0)
    rectangle = RectangleEntity(uuid4().hex, (0.0, 0.0), (2.0, 1.0))
    entities: tuple[SketchEntity, ...] = (arc, rectangle)
    selected = (arc.entity_id, rectangle.entity_id)

    rotated = rotate_entities(entities, selected, (0.0, 0.0), 90.0)
    mirrored = mirror_entities(entities, selected, (0.0, 0.0), (0.0, 1.0))

    assert isinstance(rotated[0], ArcEntity)
    assert rotated[0].entity_id == arc.entity_id
    assert rotated[0].center_mm == pytest.approx((0.0, 2.0))
    assert rotated[0].start_angle_deg == pytest.approx(90.0)
    assert rotated[0].sweep_angle_deg == 90.0
    assert isinstance(rotated[1], RectangleEntity)
    assert rotated[1].entity_id == rectangle.entity_id
    assert rotated[1].first_corner_mm == pytest.approx((-1.0, 0.0))
    assert rotated[1].opposite_corner_mm == pytest.approx((0.0, 2.0))

    assert isinstance(mirrored[0], ArcEntity)
    assert mirrored[0].center_mm == (-2.0, 0.0)
    assert mirrored[0].start_angle_deg == pytest.approx(180.0)
    assert mirrored[0].sweep_angle_deg == -90.0
    assert isinstance(mirrored[1], RectangleEntity)
    assert mirrored[1].entity_id == rectangle.entity_id
    assert mirrored[1].first_corner_mm == (-2.0, 0.0)
    assert mirrored[1].opposite_corner_mm == (0.0, 1.0)

    oblique = rotate_entities(entities, (rectangle.entity_id,), (0.0, 0.0), 45.0)
    assert isinstance(oblique[1], PolylineEntity)
    assert oblique[1].entity_id == rectangle.entity_id
    assert oblique[1].closed


def test_linear_and_circular_arrays_include_original_and_allocate_fresh_ids() -> None:
    source = CircleEntity(uuid4().hex, (10.0, 0.0), 2.0, construction=True)
    entities: tuple[SketchEntity, ...] = (source,)

    linear = linear_array_entities(entities, (source.entity_id,), count=3, step_mm=(0.0, 5.0))
    circular = circular_array_entities(
        entities, (source.entity_id,), count=4, center_mm=(0.0, 0.0), total_angle_deg=360.0
    )

    assert len(linear) == 3
    assert linear[0] == source
    assert [item.center_mm for item in linear if isinstance(item, CircleEntity)] == [
        (10.0, 0.0),
        (10.0, 5.0),
        (10.0, 10.0),
    ]
    assert len({item.entity_id for item in linear}) == 3
    assert all(item.construction for item in linear)
    assert len(circular) == 4
    circular_circles = [item for item in circular if isinstance(item, CircleEntity)]
    assert [item.center_mm for item in circular_circles] == [
        pytest.approx((10.0, 0.0)),
        pytest.approx((0.0, 10.0)),
        pytest.approx((-10.0, 0.0)),
        pytest.approx((0.0, -10.0)),
    ]
    assert len({item.entity_id for item in circular}) == 4


@pytest.mark.parametrize(
    ("operation", "args", "match"),
    [
        (move_entities, (("missing",), (1.0, 0.0)), "选择"),
        (move_entities, ((), (1.0, 0.0)), "至少"),
        (move_entities, (("selected", "selected"), (1.0, 0.0)), "重复"),
        (move_entities, (("selected",), (math.inf, 0.0)), "finite"),
    ],
)
def test_entity_transform_rejects_invalid_selection_and_coordinates(
    operation: Callable[..., object], args: tuple[object, ...], match: str
) -> None:
    entity = _line((0.0, 0.0), (1.0, 0.0))
    with pytest.raises(ValueError, match=match):
        operation((entity,), *args)


def test_arrays_reject_count_below_two_and_zero_mirror_axis() -> None:
    entity = _line((0.0, 0.0), (1.0, 0.0))
    with pytest.raises(ValueError, match="至少为 2"):
        linear_array_entities((entity,), (entity.entity_id,), count=1, step_mm=(1.0, 0.0))
    with pytest.raises(ValueError, match="镜像轴"):
        mirror_entities((entity,), (entity.entity_id,), (1.0, 1.0), (1.0, 1.0))


def test_offset_supports_lines_curves_and_open_or_closed_polylines() -> None:
    line = _line((0.0, 0.0), (10.0, 0.0))
    open_path = PolylineEntity(uuid4().hex, ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0)))
    closed_path = PolylineEntity(
        uuid4().hex, ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)), closed=True
    )
    circle = CircleEntity(uuid4().hex, (20.0, 0.0), 5.0)
    counterclockwise_arc = ArcEntity(uuid4().hex, (30.0, 0.0), 5.0, 0.0, 90.0)
    clockwise_arc = ArcEntity(uuid4().hex, (40.0, 0.0), 5.0, 0.0, -90.0)
    entities: tuple[SketchEntity, ...] = (
        line,
        open_path,
        closed_path,
        circle,
        counterclockwise_arc,
        clockwise_arc,
    )

    result = offset_entities(entities, tuple(item.entity_id for item in entities), 1.0)
    offsets = result[len(entities) :]

    assert result[: len(entities)] == entities
    assert len(offsets) == len(entities)
    assert len({entity.entity_id for entity in offsets}) == len(offsets)
    assert isinstance(offsets[0], LineEntity)
    assert offsets[0].start_mm == (0.0, 1.0)
    assert offsets[0].end_mm == (10.0, 1.0)
    assert isinstance(offsets[1], PolylineEntity)
    assert offsets[1].points_mm == ((0.0, 1.0), (9.0, 1.0), (9.0, 10.0))
    assert isinstance(offsets[2], PolylineEntity)
    assert offsets[2].points_mm == ((1.0, 1.0), (9.0, 1.0), (9.0, 9.0), (1.0, 9.0))
    assert offsets[2].closed
    assert isinstance(offsets[3], CircleEntity)
    assert offsets[3].radius_mm == 6.0
    assert isinstance(offsets[4], ArcEntity)
    assert offsets[4].radius_mm == 4.0
    assert isinstance(offsets[5], ArcEntity)
    assert offsets[5].radius_mm == 6.0


def test_offset_follows_signed_left_normal_and_rejects_collapsed_results() -> None:
    clockwise = PolylineEntity(
        uuid4().hex, ((0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)), closed=True
    )
    outward = offset_entities((clockwise,), (clockwise.entity_id,), 1.0)[1]
    assert isinstance(outward, PolylineEntity)
    assert outward.points_mm == ((-1.0, -1.0), (-1.0, 11.0), (11.0, 11.0), (11.0, -1.0))

    counterclockwise = PolylineEntity(
        uuid4().hex, ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)), closed=True
    )
    with pytest.raises(ValueError, match="距离过大"):
        offset_entities((counterclockwise,), (counterclockwise.entity_id,), 6.0)
    with pytest.raises(ValueError, match="非零"):
        offset_entities((counterclockwise,), (counterclockwise.entity_id,), 0.0)


def test_trim_circle_at_line_intersections_keeps_the_untrimmed_major_arc() -> None:
    circle = CircleEntity(uuid4().hex, (0.0, 0.0), 10.0)
    first_cutter = _line((5.0, -10.0), (5.0, 10.0))
    second_cutter = _line((-5.0, -10.0), (-5.0, 10.0))

    result = trim_curve_at((circle, first_cutter, second_cutter), (0.0, 10.0), hit_tolerance_mm=0.5)

    trimmed = result[0]
    assert isinstance(trimmed, ArcEntity)
    assert trimmed.entity_id == circle.entity_id
    assert trimmed.center_mm == circle.center_mm
    assert trimmed.radius_mm == circle.radius_mm
    assert trimmed.start_angle_deg == pytest.approx(120.0)
    assert trimmed.sweep_angle_deg == pytest.approx(300.0)
    assert result[1:] == (first_cutter, second_cutter)


def test_trim_circle_against_circle_intersections_keeps_complementary_arc() -> None:
    circle = CircleEntity(uuid4().hex, (0.0, 0.0), 10.0)
    cutter = CircleEntity(uuid4().hex, (10.0, 0.0), 10.0)

    result = trim_curve_at((circle, cutter), (0.0, 10.0), hit_tolerance_mm=0.5)

    trimmed = result[0]
    assert isinstance(trimmed, ArcEntity)
    assert trimmed.entity_id == circle.entity_id
    assert trimmed.start_angle_deg == pytest.approx(300.0)
    assert trimmed.sweep_angle_deg == pytest.approx(120.0)
    assert result[1] == cutter


def test_trim_circle_ignores_construction_cutters() -> None:
    circle = CircleEntity(uuid4().hex, (0.0, 0.0), 10.0)
    cutters = (
        _line((5.0, -10.0), (5.0, 10.0), construction=True),
        _line((-5.0, -10.0), (-5.0, 10.0), construction=True),
    )

    with pytest.raises(ValueError, match="至少需要两个唯一曲线交点"):
        trim_curve_at((circle, *cutters), (0.0, 10.0), hit_tolerance_mm=0.5)


def test_trim_circle_ignores_circle_intersections_outside_cutter_arc() -> None:
    circle = CircleEntity(uuid4().hex, (0.0, 0.0), 10.0)
    cutter = ArcEntity(uuid4().hex, (10.0, 0.0), 10.0, 100.0, 60.0)

    with pytest.raises(ValueError, match="至少需要两个唯一曲线交点"):
        trim_curve_at((circle, cutter), (0.0, 10.0), hit_tolerance_mm=0.5)


def test_trim_arc_splits_at_nearest_curve_intersections_and_preserves_direction() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 30.0, 300.0)
    cutter = _line((5.0, -10.0), (5.0, 10.0))

    result = trim_curve_at((arc, cutter), (-10.0, 0.0), hit_tolerance_mm=0.5)

    first, second = result[:2]
    assert isinstance(first, ArcEntity)
    assert isinstance(second, ArcEntity)
    assert first.entity_id == arc.entity_id
    assert first.start_angle_deg == 30.0
    assert first.sweep_angle_deg == pytest.approx(30.0)
    assert second.entity_id != arc.entity_id
    assert second.start_angle_deg == pytest.approx(300.0)
    assert second.sweep_angle_deg == pytest.approx(30.0)
    assert result[2] == cutter


def test_trim_clockwise_arc_preserves_negative_sweep_for_both_fragments() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 330.0, -300.0)
    cutter = _line((5.0, -10.0), (5.0, 10.0))

    result = trim_curve_at((arc, cutter), (-10.0, 0.0), hit_tolerance_mm=0.5)

    first, second = result[:2]
    assert isinstance(first, ArcEntity)
    assert isinstance(second, ArcEntity)
    assert first.entity_id == arc.entity_id
    assert first.start_angle_deg == pytest.approx(330.0)
    assert first.sweep_angle_deg == pytest.approx(-30.0)
    assert second.entity_id != arc.entity_id
    assert second.start_angle_deg == pytest.approx(60.0)
    assert second.sweep_angle_deg == pytest.approx(-30.0)


def test_trim_curve_rejects_missing_intersections_and_endpoint_clicks_without_mutation() -> None:
    arc = ArcEntity(uuid4().hex, (0.0, 0.0), 10.0, 0.0, -180.0)
    tangent = _line((10.0, -5.0), (10.0, 5.0))
    entities: tuple[SketchEntity, ...] = (arc, tangent)

    with pytest.raises(ValueError, match="至少需要一个内部"):
        trim_curve_at(entities, (0.0, -10.0), hit_tolerance_mm=0.5)
    assert entities == (arc, tangent)

    cutters = (_line((5.0, -10.0), (5.0, 10.0)),)
    with pytest.raises(ValueError, match="端点"):
        trim_curve_at((arc, *cutters), (10.0, 0.0), hit_tolerance_mm=0.5)


@pytest.mark.parametrize(
    ("points", "distance", "message"),
    [
        (((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)), 6.0, "反转"),
        (((0.0, 0.0), (10.0, 10.0), (0.0, 10.0), (10.0, 0.0)), 0.5, "自交"),
        (
            ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0), (5.0, 0.0)),
            1.0,
            "交叠",
        ),
        (((0.0, 0.0), (1e-10, 0.0), (10.0, 10.0)), 1.0, "过短"),
        (((0.0, 0.0), (10.0, 0.0), (0.0, 0.0), (0.0, 10.0)), 1.0, "没有唯一交点"),
    ],
)
def test_offset_open_paths_reject_reversal_crossing_short_edges_and_nonunique_corners(
    points: tuple[tuple[float, float], ...],
    distance: float,
    message: str,
) -> None:
    path = PolylineEntity(uuid4().hex, points)
    with pytest.raises(ValueError, match=message):
        offset_entities((path,), (path.entity_id,), distance)
    assert path.points_mm == points


@pytest.mark.parametrize("rectangle", [False, True])
@pytest.mark.parametrize("wrap_click", [False, True])
@pytest.mark.parametrize("split", [False, True])
def test_closed_path_edits_preserve_perimeter_order(
    rectangle: bool, wrap_click: bool, split: bool
) -> None:
    target = (
        RectangleEntity(uuid4().hex, (0.0, 0.0), (20.0, 20.0), layer_name="outline")
        if rectangle
        else PolylineEntity(
            uuid4().hex,
            ((0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)),
            closed=True,
            layer_name="outline",
        )
    )
    cutters = (_line((5.0, -2.0), (5.0, 2.0)), _line((15.0, -2.0), (15.0, 2.0)))
    long_path = ((15.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0), (0.0, 0.0), (5.0, 0.0))
    short_path = ((5.0, 0.0), (15.0, 0.0))
    clicked, retained = (long_path, short_path) if wrap_click else (short_path, long_path)
    operation = sketch_edit.split_entity_at if split else trim_curve_at
    result = operation(
        (target, *cutters), (0.0, 10.0) if wrap_click else (10.0, 0.0), hit_tolerance_mm=0.5
    )
    fragments = result[:-2]
    expected = (clicked, retained) if split else (retained,)
    assert len(fragments) == len(expected)
    for fragment, points in zip(fragments, expected, strict=True):
        assert isinstance(fragment, PolylineEntity)
        assert fragment.points_mm == points
        assert not fragment.closed
        assert fragment.layer_name == "outline"
    assert fragments[0].entity_id == target.entity_id
    assert len({item.entity_id for item in result}) == len(result)
    assert result[-2:] == cutters
    total_length = sum(
        math.dist(first, second)
        for points in expected
        for first, second in zip(points, points[1:], strict=False)
    )
    assert total_length == (80.0 if split else 10.0 if wrap_click else 70.0)
