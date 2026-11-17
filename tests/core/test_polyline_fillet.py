# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Whole-polyline fillets in no-trim mode."""

import math
from typing import cast
from uuid import uuid4

import pytest

from mycad.core.sketch import ArcEntity, LineEntity, PolylineEntity


def _test_curve_point(curve: LineEntity | ArcEntity, ratio: float) -> tuple[float, float]:
    if isinstance(curve, LineEntity):
        return (
            curve.start_mm[0] + ratio * (curve.end_mm[0] - curve.start_mm[0]),
            curve.start_mm[1] + ratio * (curve.end_mm[1] - curve.start_mm[1]),
        )
    angle = math.radians(curve.start_angle_deg + ratio * curve.sweep_angle_deg)
    return (
        curve.center_mm[0] + curve.radius_mm * math.cos(angle),
        curve.center_mm[1] + curve.radius_mm * math.sin(angle),
    )


def _test_curve_tangent(curve: LineEntity | ArcEntity, ratio: float) -> tuple[float, float]:
    if isinstance(curve, LineEntity):
        dx, dy = curve.end_mm[0] - curve.start_mm[0], curve.end_mm[1] - curve.start_mm[1]
        length = math.hypot(dx, dy)
        return dx / length, dy / length
    angle = math.radians(curve.start_angle_deg + ratio * curve.sweep_angle_deg)
    sign = 1 if curve.sweep_angle_deg > 0 else -1
    return -sign * math.sin(angle), sign * math.cos(angle)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("bulge", [-0.2, 0.2])
def test_zero_radius_whole_polyline_removes_non_tangent_arc_between_converging_lines(
    reverse: bool, bulge: float
) -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    points = ((0.0, 0.0), (8.0, 0.0), (10.0, 2.0), (10.0, 10.0))
    if reverse:
        points = tuple(reversed(points))
        bulge = -bulge
    source = PolylineEntity(uuid4().hex, points, bulges=(0, bulge, 0))
    result, bulges = polyline_fillet_trimmed_segments(source, 0)
    expected = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0))
    assert result == (tuple(reversed(expected)) if reverse else expected)
    assert bulges == (0, 0)


def test_zero_radius_whole_polyline_retains_nonconverging_arc() -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    source = PolylineEntity(uuid4().hex, ((0, 0), (8, 0), (10, 2), (10, -5)), bulges=(0, 0.2, 0))
    points, bulges = polyline_fillet_trimmed_segments(source, 0)
    assert points == source.points_mm and bulges == source.bulges


def test_zero_radius_whole_closed_polyline_removes_non_tangent_arc_at_seam() -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    source = PolylineEntity(
        uuid4().hex,
        ((10, 2), (10, 10), (0, 10), (0, 0), (8, 0)),
        closed=True,
        bulges=(0, 0, 0, 0, 0.2),
    )
    points, bulges = polyline_fillet_trimmed_segments(source, 0)
    assert len(points) == 4 and set(points) == {(10, 0), (10, 10), (0, 10), (0, 0)}
    assert bulges == (0, 0, 0, 0)


def test_zero_radius_whole_closed_three_segment_path_never_becomes_degenerate() -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    source = PolylineEntity(
        uuid4().hex, ((0, 0), (10, 0), (5, 10)), closed=True, bulges=(0, 0.2, 0)
    )
    points, bulges = polyline_fillet_trimmed_segments(source, 0)
    assert len(points) >= 3
    PolylineEntity(source.entity_id, points, closed=True, bulges=bulges)


def test_zero_radius_whole_polyline_removes_multiple_non_tangent_arcs() -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    source = PolylineEntity(
        uuid4().hex,
        ((0, 0), (8, 0), (10, 2), (10, 8), (12, 10), (20, 10)),
        bulges=(0, 0.2, 0, -0.2, 0),
    )
    points, bulges = polyline_fillet_trimmed_segments(source, 0)
    assert points == ((0, 0), (10, 0), (10, 10), (20, 10))
    assert bulges == (0, 0, 0)


@pytest.mark.parametrize("both_arcs", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_zero_radius_whole_polyline_removes_tangent_fillet_between_mixed_segments(
    both_arcs: bool, reverse: bool
) -> None:
    from dataclasses import replace

    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    quarter = 2**0.5 - 1
    points = (
        ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0))
        if both_arcs
        else ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0))
    )
    bulges = (quarter, quarter) if both_arcs else (0.0, quarter)
    if reverse:
        points = tuple(reversed(points))
        bulges = tuple(-value for value in reversed(bulges))
    original = PolylineEntity(uuid4().hex, points, bulges=bulges)
    rounded_points, rounded_bulges = polyline_fillet_trimmed_segments(original, 1)
    rounded = replace(original, points_mm=rounded_points, bulges=rounded_bulges)
    restored_points, restored_bulges = polyline_fillet_trimmed_segments(rounded, 0)
    assert len(restored_points) == len(points)
    for actual, expected in zip(restored_points, points, strict=True):
        assert actual == pytest.approx(expected)
    assert restored_bulges == pytest.approx(bulges)


def test_zero_radius_whole_polyline_keeps_non_tangent_arc_with_curved_neighbour() -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    original = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (5, 5)), bulges=(0, 2**0.5 - 1))
    points, bulges = polyline_fillet_trimmed_segments(original, 1)
    modified = PolylineEntity(
        original.entity_id, points, bulges=(bulges[0], bulges[1] * 1.2, bulges[2])
    )
    restored_points, restored_bulges = polyline_fillet_trimmed_segments(modified, 0)
    assert restored_points == modified.points_mm and restored_bulges == modified.bulges


@pytest.mark.parametrize("reverse_selection", [False, True])
def test_selected_adjacent_segments_round_only_their_corner(reverse_selection: bool) -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    indices = (1, 0) if reverse_selection else (0, 1)
    result, arc = polyline_segment_fillet(source, *indices, 2)
    assert arc is None and result.entity_id == source.entity_id
    assert result.points_mm[0] == (0, 0) and result.points_mm[-2:] == ((10, 10), (20, 10))
    assert result.points_mm[1] == pytest.approx((8, 0))
    assert result.points_mm[2] == pytest.approx((10, 2))
    assert result.bulges == pytest.approx((0, 2**0.5 - 1, 0, 0))


@pytest.mark.parametrize("radius", [0.0, 1.0])
def test_selected_segments_replace_only_intervening_arc(radius: float) -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments, polyline_segment_fillet

    original = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    points, bulges = polyline_fillet_trimmed_segments(
        PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10))), 2
    )
    rounded = PolylineEntity(original.entity_id, (*points, (20, 10)), bulges=(*bulges, 0))
    result, arc = polyline_segment_fillet(rounded, 0, 2, radius)
    assert arc is None and result.points_mm[-2:] == ((10, 10), (20, 10))
    if radius:
        assert result.points_mm[1] == pytest.approx((9, 0))
        assert result.points_mm[2] == pytest.approx((10, 1))
    else:
        assert result.points_mm[1] == pytest.approx((10, 0))
        assert not any(result.bulges)


@pytest.mark.parametrize("angle", [0.0, 0.23, 1.1])
def test_selected_existing_fillet_with_same_radius_is_a_noop(angle: float) -> None:
    import math

    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments, polyline_segment_fillet

    c, s = math.cos(angle), math.sin(angle)
    points = tuple(
        (100 + x * c - y * s, -50 + x * s + y * c) for x, y in ((0, 0), (10, 0), (10, 10))
    )
    source = PolylineEntity(uuid4().hex, points)
    vertices, bulges = polyline_fillet_trimmed_segments(source, 2)
    rounded = PolylineEntity(source.entity_id, vertices, bulges=bulges)
    result, _ = polyline_segment_fillet(rounded, 0, 2, 2)
    assert result == rounded


def test_selected_segments_notrim_leaves_source_and_adds_one_arc() -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    result, arc = polyline_segment_fillet(source, 1, 0, 2, trim=False)
    assert result == source and arc is not None and arc.radius_mm == pytest.approx(2)


def test_selected_segments_notrim_rejects_contacts_outside_source() -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments, polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    points, bulges = polyline_fillet_trimmed_segments(source, 2)
    rounded = PolylineEntity(source.entity_id, points, bulges=bulges)
    with pytest.raises(ValueError, match="切点"):
        polyline_segment_fillet(rounded, 0, 2, 1, trim=False)


def test_selected_segments_do_not_replace_arc_when_lines_diverge() -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (5, 5), (5, 10)), bulges=(0, 0.4, 0))
    with pytest.raises(ValueError, match="收敛"):
        polyline_segment_fillet(source, 0, 2, 1)


def test_selected_closed_segments_across_start_keep_other_sides() -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True)
    result, _ = polyline_segment_fillet(source, 3, 0, 2)
    assert result.closed and len(result.points_mm) == 5 and len(result.bulges) == 5
    assert (10, 0) in result.points_mm and (10, 10) in result.points_mm
    assert sum(value != 0 for value in result.bulges) == 1


@pytest.mark.parametrize("radius", [0.0, 2.0])
@pytest.mark.parametrize("reverse_selection", [False, True])
def test_selecting_open_polyline_end_segments_closes_path(
    radius: float, reverse_selection: bool
) -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10), (0, 3)))
    indices = (3, 0) if reverse_selection else (0, 3)
    result, arc = polyline_segment_fillet(source, *indices, radius)
    assert arc is None and result.closed and result.entity_id == source.entity_id
    assert result.points_mm[1:4] == ((10, 0), (10, 10), (0, 10))
    if radius:
        assert result.points_mm[0] == pytest.approx((2, 0))
        assert result.points_mm[-1] == pytest.approx((0, 2))
        assert result.bulges[-1] == pytest.approx(2**0.5 - 1)
    else:
        assert result.points_mm[0] == pytest.approx((0, 0))
        assert not result.bulges


@pytest.mark.parametrize("reverse", [False, True])
def test_selected_segments_preserve_unrelated_curved_segment(reverse: bool) -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    points = ((0, 0), (10, 0), (10, 10), (20, 10))
    source = PolylineEntity(
        uuid4().hex,
        tuple(reversed(points)) if reverse else points,
        bulges=(-0.5, 0, 0) if reverse else (0, 0, 0.5),
    )
    indices = (1, 2) if reverse else (0, 1)
    result, _ = polyline_segment_fillet(source, *indices, 2)
    assert len(result.points_mm) == 5
    assert result.bulges[0 if reverse else -1] == (-0.5 if reverse else 0.5)
    assert result.points_mm[0 if reverse else -1] == (20, 10)


def test_selected_parallel_segments_with_intervening_segment_are_rejected() -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10), (20, 20)))
    with pytest.raises(ValueError, match="平行"):
        polyline_segment_fillet(source, 0, 2, 1)


def test_selected_segments_with_multiple_intervening_segments_are_rejected() -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10), (20, 20), (30, 20)))
    with pytest.raises(ValueError, match="相邻"):
        polyline_segment_fillet(source, 0, 3, 1)


def test_open_three_segment_polyline_can_close_by_fillet() -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (1, 3)))
    result, _ = polyline_segment_fillet(source, 0, 2, 1)
    assert result.closed and len(result.points_mm) == 4
    assert result.points_mm[1:3] == ((10, 0), (10, 10))
    assert result.bulges[-1] != 0


@pytest.mark.parametrize("trim", [False, True])
@pytest.mark.parametrize("radius", [0.0, 2.0])
def test_open_parallel_end_segments_use_half_gap_radius(trim: bool, radius: float) -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)))
    result, arc = polyline_segment_fillet(source, 0, 2, radius, trim=trim)
    if trim:
        assert result.closed and abs(result.bulges[-1]) == pytest.approx(1)
        assert arc is None
    else:
        assert result == source and arc is not None
        assert arc.radius_mm == pytest.approx(5)


@pytest.mark.parametrize("reverse_selection", [False, True])
def test_open_two_segment_polyline_closes_when_picked_near_open_ends(
    reverse_selection: bool,
) -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    indices = (1, 0) if reverse_selection else (0, 1)
    picks = ((10, 9), (1, 0)) if reverse_selection else ((1, 0), (10, 9))
    result, _ = polyline_segment_fillet(
        source, *indices, 2, first_pick=picks[0], second_pick=picks[1]
    )
    assert result.closed and result.points_mm[1] == (10, 0)
    assert result.points_mm[0] == pytest.approx((8, 0))
    assert result.points_mm[-1] == pytest.approx((10, 2))
    assert result.bulges[-1] == pytest.approx(1 - 2**0.5)


def test_open_two_segment_zero_radius_cannot_make_degenerate_closed_path() -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    with pytest.raises(ValueError, match="非退化"):
        polyline_segment_fillet(source, 0, 1, 0, first_pick=(1, 0), second_pick=(10, 9))


def test_open_polyline_with_middle_arc_can_close_or_replace_by_pick() -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(
        uuid4().hex, ((0, 0), (8, 0), (10, 2), (10, 10)), bulges=(0, 2**0.5 - 1, 0)
    )
    closed, _ = polyline_segment_fillet(source, 0, 2, 5, first_pick=(1, 0), second_pick=(10, 9))
    assert closed.closed and closed.points_mm[0] == pytest.approx((5, 0))
    assert closed.points_mm[-1] == pytest.approx((10, 5))
    assert closed.bulges[1] == source.bulges[1]
    retained, new_arc = polyline_segment_fillet(
        source, 0, 2, 5, trim=False, first_pick=(1, 0), second_pick=(10, 9)
    )
    assert retained == source and new_arc is not None and new_arc.radius_mm == pytest.approx(5)
    replaced, _ = polyline_segment_fillet(source, 0, 2, 1, first_pick=(7, 0), second_pick=(10, 3))
    assert not replaced.closed and replaced.points_mm[1] == pytest.approx((9, 0))


def test_selected_closed_segments_reject_two_equally_valid_paths() -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, 10), (0, 10)),
        True,
        bulges=(0, 0.5, 0, -0.5),
    )
    with pytest.raises(ValueError, match="不明确"):
        polyline_segment_fillet(source, 0, 2, 1)


@pytest.mark.parametrize("closed, count", [(False, 2), (True, 4)])
def test_polyline_fillet_keeps_original_and_builds_each_corner(closed: bool, count: int) -> None:
    from mycad.core.polyline_fillet import polyline_fillet_notrim

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed, True)
    arcs = polyline_fillet_notrim(source, 2, layer_name="rounds")
    assert len(arcs) == count
    assert len({arc.entity_id for arc in arcs}) == count
    assert all(
        arc.radius_mm == 2 and arc.construction and arc.layer_name == "rounds" for arc in arcs
    )
    assert source.points_mm == ((0, 0), (10, 0), (10, 10), (0, 10))


def test_no_trim_polyline_fillet_keeps_non_overlapping_corners() -> None:
    from mycad.core.polyline_fillet import polyline_fillet_notrim

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 3), (20, 3)))
    arcs = polyline_fillet_notrim(source, 2)
    assert len(arcs) == 1


def test_trimmed_polyline_keeps_unavailable_corner_and_rounds_eligible_one() -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 3), (20, 3)))
    vertices, bulges = polyline_fillet_trimmed_segments(source, 2)
    assert len(vertices) == 5 and len(bulges) == 4
    assert sum(value != 0 for value in bulges) == 1
    assert vertices[1] == pytest.approx((8, 0))
    assert vertices[2] == pytest.approx((10, 2))
    assert vertices[3] == pytest.approx((10, 3))


@pytest.mark.parametrize("reverse", [False, True])
def test_trimmed_closed_polyline_keeps_one_exact_arc_per_corner(reverse: bool) -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    points = ((0, 0), (10, 0), (10, 10), (0, 10))
    source = PolylineEntity(uuid4().hex, tuple(reversed(points)) if reverse else points, True)
    vertices, bulges = polyline_fillet_trimmed_segments(source, 2)
    assert len(vertices) == len(bulges) == 8
    assert all(abs(value) == pytest.approx(2**0.5 - 1) for value in bulges[::2])
    assert all(value == 0 for value in bulges[1::2])
    assert all((value < 0) == reverse for value in bulges[::2])


def test_trimmed_open_polyline_retains_endpoints_and_bulge_direction() -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, -10)))
    vertices, bulges = polyline_fillet_trimmed_segments(source, 2)
    assert len(vertices) == 4 and len(bulges) == 3
    assert vertices[0] == source.points_mm[0] and vertices[-1] == source.points_mm[-1]
    assert vertices[1] == pytest.approx((8, 0))
    assert vertices[2] == pytest.approx((10, -2))
    assert bulges == pytest.approx((0, 1 - 2**0.5, 0))


@pytest.mark.parametrize("radius", [0.0, 1.0])
def test_existing_polyline_fillet_can_be_removed_or_replaced(radius: float) -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    vertices, bulges = polyline_fillet_trimmed_segments(source, 2)
    rounded = PolylineEntity(source.entity_id, vertices, bulges=bulges)
    new_vertices, new_bulges = polyline_fillet_trimmed_segments(rounded, radius)
    if radius == 0:
        assert len(new_vertices) == len(source.points_mm)
        for actual, expected in zip(new_vertices, source.points_mm, strict=True):
            assert actual == pytest.approx(expected)
        assert new_bulges == (0.0, 0.0)
    else:
        assert new_vertices[1] == pytest.approx((9, 0))
        assert new_vertices[2] == pytest.approx((10, 1))
        assert new_bulges == pytest.approx((0, 2**0.5 - 1, 0))


def test_existing_polyline_fillet_survives_unusable_new_radius() -> None:
    from mycad.core.polyline_fillet import polyline_fillet_notrim, polyline_fillet_trimmed_segments

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    vertices, bulges = polyline_fillet_trimmed_segments(source, 2)
    rounded = PolylineEntity(source.entity_id, vertices, bulges=bulges)
    changed, changed_bulges = polyline_fillet_trimmed_segments(rounded, 100)
    assert changed == rounded.points_mm
    assert changed_bulges == rounded.bulges
    with pytest.raises(ValueError, match="没有可圆角"):
        polyline_fillet_notrim(rounded, 100)


@pytest.mark.parametrize("reverse", [False, True])
def test_existing_neighbour_fillet_remains_when_new_radius_conflicts(reverse: bool) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_notrim, polyline_fillet_trimmed_segments
    from mycad.core.sketch import ArcEntity

    points = ((0, 0), (10, 0), (10, 6), (20, 6))
    source = PolylineEntity(uuid4().hex, tuple(reversed(points)) if reverse else points)
    vertices, bulges = polyline_fillet_trimmed_segments(source, 1)
    rounded = PolylineEntity(source.entity_id, vertices, bulges=bulges)
    changed, changed_bulges = polyline_fillet_trimmed_segments(rounded, 4)
    segments = polyline_curve_segments(changed, changed_bulges, False, source.entity_id)
    arcs = [segment for segment in segments if isinstance(segment, ArcEntity)]
    assert sorted(arc.radius_mm for arc in arcs) == pytest.approx([1, 4])
    assert all(
        tangent_on_curves(first, second)
        for first, second in zip(segments, segments[1:], strict=False)
    )
    separate = polyline_fillet_notrim(rounded, 4)
    assert len(separate) == 1 and separate[0].radius_mm == pytest.approx(4)


@pytest.mark.parametrize("reverse", [False, True])
def test_closed_polyline_keeps_infeasible_existing_fillet_at_wrap(reverse: bool) -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    points = ((0, 0), (10, 0), (10, 6), (0, 6))
    source = PolylineEntity(uuid4().hex, tuple(reversed(points)) if reverse else points, True)
    vertices, bulges = polyline_fillet_trimmed_segments(source, 1)
    rounded = PolylineEntity(source.entity_id, vertices, True, bulges=bulges)
    changed, changed_bulges = polyline_fillet_trimmed_segments(rounded, 100)
    assert changed == rounded.points_mm
    assert changed_bulges == rounded.bulges


def test_infeasible_existing_fillet_does_not_block_other_corners() -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_notrim, polyline_fillet_trimmed_segments
    from mycad.core.sketch import ArcEntity

    source = PolylineEntity(
        uuid4().hex,
        ((0, 0), (3, 0), (4, 1), (4, 20), (24, 20)),
        bulges=(0, 2**0.5 - 1, 0, 0),
    )
    points, bulges = polyline_fillet_trimmed_segments(source, 5)
    segments = polyline_curve_segments(points, bulges, False, source.entity_id)
    assert sorted(
        segment.radius_mm for segment in segments if isinstance(segment, ArcEntity)
    ) == pytest.approx([1, 5])
    separate = polyline_fillet_notrim(source, 5)
    assert len(separate) == 1 and separate[0].radius_mm == pytest.approx(5)


@pytest.mark.parametrize("reverse", [False, True])
def test_no_trim_keeps_new_arc_on_same_circle_as_disjoint_original_arc(reverse: bool) -> None:
    import math

    from mycad.core.polyline_fillet import polyline_fillet_notrim

    quarter = 2**0.5 - 1
    points = ((-2, 0), (0, 2), (2, 10), (2, -2), (-10, -2))
    source = PolylineEntity(
        uuid4().hex,
        tuple(reversed(points)) if reverse else points,
        bulges=(0, 0, 0, quarter) if reverse else (-quarter, 0, 0, 0),
    )
    arcs = polyline_fillet_notrim(source, 2)
    assert len(arcs) == 2
    shared_support = [arc for arc in arcs if math.dist(arc.center_mm, (0, 0)) < 1e-8]
    assert len(shared_support) == 1
    assert shared_support[0].sweep_angle_deg == pytest.approx(90 if reverse else -90)


@pytest.mark.parametrize("reverse", [False, True])
def test_no_trim_keeps_new_arc_coincident_with_unrelated_original_arc(reverse: bool) -> None:
    from mycad.core.polyline_fillet import polyline_fillet_notrim

    quarter = 2**0.5 - 1
    points = ((2, 0), (0, -2), (2, 10), (2, -2), (-10, -2))
    source = PolylineEntity(
        uuid4().hex,
        tuple(reversed(points)) if reverse else points,
        bulges=(0, 0, 0, quarter) if reverse else (-quarter, 0, 0, 0),
    )
    arcs = polyline_fillet_notrim(source, 2)
    assert len(arcs) == 1
    assert arcs[0].center_mm == pytest.approx((0, 0))
    assert arcs[0].radius_mm == pytest.approx(2)
    assert arcs[0].sweep_angle_deg == pytest.approx(90 if reverse else -90)


@pytest.mark.parametrize("start", range(5))
def test_closed_no_trim_tracks_new_arcs_across_start_vertex(start: int) -> None:
    import math

    from mycad.core.polyline_fillet import polyline_fillet_notrim

    points = ((-2, 0), (0, 2), (2, 10), (2, -2), (-10, -2))
    bulges = (1 - 2**0.5, 0, 0, 0, 0)
    source = PolylineEntity(
        uuid4().hex,
        points[start:] + points[:start],
        True,
        bulges=bulges[start:] + bulges[:start],
    )
    arcs = polyline_fillet_notrim(source, 2)
    assert len(arcs) == 3
    assert any(math.dist(arc.center_mm, (0, 0)) < 1e-8 for arc in arcs)


def test_reapplying_existing_fillet_radius_keeps_exact_vertices() -> None:
    import math

    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    angle = -0.930877428585891
    c, s = math.cos(angle), math.sin(angle)
    points = tuple(
        (-13.962750801980391 + x * c - y * s, -9.265827282085155 + x * s + y * c)
        for x, y in ((0, 0), (10, 0), (10, 10))
    )
    source = PolylineEntity(uuid4().hex, points)
    vertices, bulges = polyline_fillet_trimmed_segments(source, 2)
    rounded = PolylineEntity(source.entity_id, vertices, bulges=bulges)
    changed, changed_bulges = polyline_fillet_trimmed_segments(rounded, 2)
    assert changed == rounded.points_mm
    assert changed_bulges == rounded.bulges


def test_polyline_fillet_trims_existing_arc_and_rounds_straight_corner() -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_notrim, polyline_fillet_trimmed_segments
    from mycad.core.sketch import ArcEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (10, 0), (10, 10)), bulges=(1, 0, 0))
    vertices, bulges = polyline_fillet_trimmed_segments(source, 2)
    segments = polyline_curve_segments(vertices, bulges, False, source.entity_id)
    first = segments[0]
    assert isinstance(first, ArcEntity)
    assert first.center_mm == pytest.approx((1, 0)) and first.radius_mm == pytest.approx(1)
    assert sum(value != 0 for value in bulges) == 3
    restored_points, restored_bulges = polyline_fillet_trimmed_segments(source, 0)
    assert restored_points == source.points_mm and restored_bulges == source.bulges
    separate = polyline_fillet_notrim(source, 2)
    assert len(separate) == 2 and all(arc.radius_mm == pytest.approx(2) for arc in separate)


@pytest.mark.parametrize("reverse", [False, True])
def test_polyline_fillet_rounds_line_arc_junction(reverse: bool) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_notrim, polyline_fillet_trimmed_segments
    from mycad.core.sketch import ArcEntity, LineEntity

    points = ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0))
    quarter = 2**0.5 - 1
    source = PolylineEntity(
        uuid4().hex,
        tuple(reversed(points)) if reverse else points,
        bulges=(-quarter, 0) if reverse else (0, quarter),
    )
    vertices, bulges = polyline_fillet_trimmed_segments(source, 1)
    segments = polyline_curve_segments(vertices, bulges, False, source.entity_id)
    assert len(segments) == 3
    assert sum(isinstance(segment, LineEntity) for segment in segments) == 1
    arcs = [segment for segment in segments if isinstance(segment, ArcEntity)]
    assert sorted(arc.radius_mm for arc in arcs) == pytest.approx([1, 5])
    assert tangent_on_curves(segments[0], segments[1])
    assert tangent_on_curves(segments[1], segments[2])
    separate = polyline_fillet_notrim(source, 1)
    assert len(separate) == 1 and separate[0].radius_mm == pytest.approx(1)

    rounded = PolylineEntity(source.entity_id, vertices, bulges=bulges)
    changed_points, changed_bulges = polyline_fillet_trimmed_segments(rounded, 0.5)
    changed = polyline_curve_segments(changed_points, changed_bulges, False, source.entity_id)
    assert sorted(
        segment.radius_mm for segment in changed if isinstance(segment, ArcEntity)
    ) == pytest.approx([0.5, 5])


@pytest.mark.parametrize("reverse", [False, True])
def test_polyline_fillet_rounds_arc_arc_junction(reverse: bool) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_notrim, polyline_fillet_trimmed_segments
    from mycad.core.sketch import ArcEntity

    points = ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0))
    quarter = 2**0.5 - 1
    source = PolylineEntity(
        uuid4().hex,
        tuple(reversed(points)) if reverse else points,
        bulges=(-quarter, -quarter) if reverse else (quarter, quarter),
    )
    vertices, bulges = polyline_fillet_trimmed_segments(source, 1)
    segments = polyline_curve_segments(vertices, bulges, False, source.entity_id)
    assert len(segments) == 3 and all(isinstance(segment, ArcEntity) for segment in segments)
    assert sorted(
        segment.radius_mm for segment in segments if isinstance(segment, ArcEntity)
    ) == pytest.approx([1, 5, 5])
    assert tangent_on_curves(segments[0], segments[1])
    assert tangent_on_curves(segments[1], segments[2])
    separate = polyline_fillet_notrim(source, 1)
    assert len(separate) == 1 and separate[0].radius_mm == pytest.approx(1)
    rounded = PolylineEntity(source.entity_id, vertices, bulges=bulges)
    changed_points, changed_bulges = polyline_fillet_trimmed_segments(rounded, 0.5)
    changed = polyline_curve_segments(changed_points, changed_bulges, False, source.entity_id)
    assert sorted(
        segment.radius_mm for segment in changed if isinstance(segment, ArcEntity)
    ) == pytest.approx([0.5, 5, 5])


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_polyline_fillet_rounds_consecutive_arc_junctions(closed: bool, reverse: bool) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_notrim, polyline_fillet_trimmed_segments
    from mycad.core.sketch import ArcEntity

    points = ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0), (20.0, 0.0))
    quarter = 2**0.5 - 1
    count = len(points) if closed else len(points) - 1
    source = PolylineEntity(
        uuid4().hex,
        tuple(reversed(points)) if reverse else points,
        closed=closed,
        bulges=(((-quarter if reverse else quarter),) * count),
    )
    vertices, bulges = polyline_fillet_trimmed_segments(source, 1)
    segments = polyline_curve_segments(vertices, bulges, closed, source.entity_id)
    expected_corners = 4 if closed else 2
    assert len(segments) == count + expected_corners
    assert all(isinstance(segment, ArcEntity) for segment in segments)
    for index in range(len(segments) if closed else len(segments) - 1):
        assert tangent_on_curves(segments[index], segments[(index + 1) % len(segments)])
    separate = polyline_fillet_notrim(source, 1)
    assert len(separate) == expected_corners
    assert all(arc.radius_mm == pytest.approx(1) for arc in separate)
    rounded = PolylineEntity(source.entity_id, vertices, closed=closed, bulges=bulges)
    repeated_points, repeated_bulges = polyline_fillet_trimmed_segments(rounded, 1)
    assert len(repeated_points) == len(vertices)
    for actual, expected in zip(repeated_points, vertices, strict=True):
        assert actual == pytest.approx(expected)
    assert repeated_bulges == pytest.approx(bulges)


def test_polyline_fillet_preserves_already_smooth_line_arc_junction() -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    quarter = 2**0.5 - 1
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (15, 5)), bulges=(0, quarter))
    points, bulges = polyline_fillet_trimmed_segments(source, 1)
    assert points == source.points_mm and bulges == source.bulges


def test_polyline_fillet_handles_two_arc_line_corners_on_shared_segment() -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    quarter = 2**0.5 - 1
    source = PolylineEntity(
        uuid4().hex,
        ((0, 0), (5, 5), (15, 5), (10, 10)),
        bulges=(quarter, 0, quarter),
    )
    vertices, bulges = polyline_fillet_trimmed_segments(source, 1)
    segments = polyline_curve_segments(vertices, bulges, False, source.entity_id)
    assert len(segments) == 5
    assert all(
        tangent_on_curves(first, second)
        for first, second in zip(segments, segments[1:], strict=False)
    )


@pytest.mark.parametrize("bulge", [0.0, float("nan"), float("inf")])
def test_bulge_arc_rejects_zero_or_nonfinite_bulge(bulge: float) -> None:
    from mycad.core.polyline_curves import bulge_arc

    with pytest.raises(ValueError):
        bulge_arc((0, 0), (2, 0), bulge, uuid4().hex)


@pytest.mark.parametrize("bulge, expected_y", [(1.0, -1.0), (-1.0, 1.0)])
def test_bulge_arc_recovers_signed_semicircle(bulge: float, expected_y: float) -> None:
    import math

    from mycad.core.polyline_curves import bulge_arc

    arc = bulge_arc((0, 0), (2, 0), bulge, uuid4().hex)
    middle = math.radians(arc.start_angle_deg + arc.sweep_angle_deg / 2)
    assert arc.center_mm == pytest.approx((1, 0))
    assert arc.radius_mm == pytest.approx(1)
    assert arc.center_mm[1] + arc.radius_mm * math.sin(middle) == pytest.approx(expected_y)
    assert arc.sweep_angle_deg == pytest.approx(180 * bulge)


def test_trimmed_concave_polyline_reconstructs_the_fillet_arcs() -> None:
    import math

    from mycad.core.polyline_curves import bulge_arc
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (5, 10), (5, 5), (0, 5)), True)
    vertices, bulges = polyline_fillet_trimmed_segments(source, 1)
    assert any(value < 0 for value in bulges) and any(value > 0 for value in bulges)
    for index, bulge in enumerate(bulges):
        if not bulge:
            continue
        start, end = vertices[index], vertices[(index + 1) % len(vertices)]
        arc = bulge_arc(start, end, bulge, uuid4().hex)
        end_angle = math.radians(arc.start_angle_deg + arc.sweep_angle_deg)
        assert arc.radius_mm == pytest.approx(1)
        assert (
            arc.center_mm[0] + arc.radius_mm * math.cos(end_angle),
            arc.center_mm[1] + arc.radius_mm * math.sin(end_angle),
        ) == pytest.approx(end)


def test_bulged_path_builds_exact_segments_and_preserves_metadata() -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import ArcEntity, LineEntity

    identity = uuid4().hex
    segments = polyline_curve_segments(
        ((0, 0), (2, 0), (2, 2)), (1, 0), False, identity, construction=True, layer_name="A"
    )
    assert len(segments) == 2
    assert isinstance(segments[0], ArcEntity) and isinstance(segments[1], LineEntity)
    assert segments[0].radius_mm == pytest.approx(1)
    assert segments[1].start_mm == (2, 0) and segments[1].end_mm == (2, 2)
    assert all(
        item.entity_id == identity and item.construction and item.layer_name == "A"
        for item in segments
    )


@pytest.mark.parametrize("bulges", [(0,), (0, 0, 0), (float("nan"), 0)])
def test_bulged_path_rejects_invalid_segment_bulges(bulges: tuple[float, ...]) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments

    with pytest.raises(ValueError):
        polyline_curve_segments(((0, 0), (2, 0), (2, 2)), bulges, False, uuid4().hex)


def test_curved_polyline_round_trips_through_versioned_sketch_mapping() -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    entity = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)), bulges=(1.0, 0.0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    with pytest.raises(ValueError, match="version 5"):
        sketch.to_mapping(version=4)
    encoded = sketch.to_mapping(version=5)
    encoded_entities = cast("list[dict[str, object]]", encoded["entities"])
    assert encoded_entities[0]["bulges"] == [1.0, 0.0]
    assert Sketch.from_mapping(encoded) == sketch
    assert sketch.to_state_mapping() == encoded


@pytest.mark.parametrize("bulges", [(1.0,), (1.0, 0.0, 0.0), (float("nan"), 0.0), (True, 0.0)])
def test_polyline_entity_rejects_invalid_bulges(bulges: tuple[float, ...]) -> None:
    with pytest.raises(ValueError):
        PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)), bulges=bulges)


def test_zero_bulges_preserve_legacy_sketch_encoding() -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    identity = uuid4().hex
    straight = PolylineEntity(identity, ((0, 0), (2, 0), (2, 2)))
    zeroed = PolylineEntity(identity, ((0, 0), (2, 0), (2, 2)), bulges=(0.0, 0.0))
    assert zeroed == straight
    encoded = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (zeroed,)).to_mapping(version=3)
    encoded_entities = cast("list[dict[str, object]]", encoded["entities"])
    assert encoded_entities[0] == {
        "entity_id": identity,
        "kind": "polyline",
        "points_mm": [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0]],
        "closed": False,
        "construction": False,
        "layer_name": "0",
    }


def test_curved_polyline_rigid_transforms_preserve_exact_bulges() -> None:
    from mycad.core.sketch_edit import (
        copy_entities,
        mirror_entities,
        move_entities,
        rotate_entities,
    )

    source = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)), bulges=(1.0, 0.0))
    selected = (source.entity_id,)
    moved = move_entities((source,), selected, (3, 4))[0]
    rotated = rotate_entities((source,), selected, (0, 0), 90)[0]
    mirrored = mirror_entities((source,), selected, (0, 0), (1, 0))[0]
    copied = copy_entities((source,), selected, (3, 4))[1]
    assert isinstance(moved, PolylineEntity) and moved.bulges == source.bulges
    assert isinstance(rotated, PolylineEntity) and rotated.bulges == source.bulges
    assert isinstance(mirrored, PolylineEntity) and mirrored.bulges == (-1.0, 0.0)
    assert isinstance(copied, PolylineEntity) and copied.bulges == source.bulges
    assert copied.entity_id != source.entity_id


def test_curved_polyline_offset_is_rejected_until_exact_offset_is_supported() -> None:
    from mycad.core.sketch_edit import offset_entities

    source = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)), bulges=(1.0, 0.0))
    with pytest.raises(ValueError, match="圆弧"):
        offset_entities((source,), (source.entity_id,), 1)


@pytest.mark.parametrize("operation", ["trim_curve_at", "extend_curve_at", "split_entity_at"])
def test_line_edit_rejects_curved_polyline_instead_of_using_chords(operation: str) -> None:
    from mycad.core import sketch_edit

    source = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)), bulges=(1.0, 0.0))
    method = getattr(sketch_edit, operation)
    with pytest.raises(ValueError, match="圆弧"):
        method((source,), (1, -1), hit_tolerance_mm=0.2, target_entity_id=source.entity_id)


def test_curved_polyline_sampling_follows_arc_and_preserves_endpoints() -> None:
    from mycad.core.polyline_curves import polyline_sampled_points

    source = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)), bulges=(1.0, 0.0))
    points = polyline_sampled_points(source)
    assert points[0] == source.points_mm[0] and points[-1] == source.points_mm[-1]
    assert min(point[1] for point in points) == pytest.approx(-1.0)
    assert source.points_mm[1] in points


def test_curved_polyline_requires_new_command_schema_versions() -> None:
    from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
    from mycad.commands.validation import validate_params
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    entity = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)), bulges=(1, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    params = sketch.to_state_mapping()
    for version in (3, 5, 6, 7):
        spec = next(
            item
            for item in BUILTIN_COMMAND_SPECS
            if item.id == "sketch.create" and item.version == version
        )
        with pytest.raises(ValidationError):
            validate_params(spec, params, defs=COMMAND_SCHEMA_DEFS)
    create = next(
        item for item in BUILTIN_COMMAND_SPECS if item.id == "sketch.create" and item.version == 8
    )
    assert (
        validate_params(create, params, defs=COMMAND_SCHEMA_DEFS)["entities"] == params["entities"]
    )
    revision: dict[str, object] = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": "0" * 64,
        "entities": params["entities"],
        "constraints": [],
    }
    old = next(
        item
        for item in BUILTIN_COMMAND_SPECS
        if item.id == "drawing.sketch.revise" and item.version == 2
    )
    with pytest.raises(ValidationError):
        validate_params(old, {"revisions": [revision]}, defs=COMMAND_SCHEMA_DEFS)
    new = next(
        item
        for item in BUILTIN_COMMAND_SPECS
        if item.id == "drawing.sketch.revise" and item.version == 3
    )
    assert validate_params(new, {"revisions": [revision]}, defs=COMMAND_SCHEMA_DEFS)["revisions"]


def test_cross_tangency_schema_version_preserves_curved_polylines() -> None:
    from mycad.builtin_commands import BUILTIN_COMMAND_SPECS, COMMAND_SCHEMA_DEFS
    from mycad.commands.validation import validate_params
    from mycad.core.exceptions import ValidationError
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    entity = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)), bulges=(1, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,))
    state = sketch.to_state_mapping()
    revision: dict[str, object] = {
        "sketch_id": sketch.sketch_id,
        "base_state_sha256": "0" * 64,
        "entities": state["entities"],
        "constraints": [],
    }
    params: dict[str, object] = {
        "relation": {
            "relation_id": uuid4().hex,
            "first": {"sketch_id": sketch.sketch_id, "entity_id": uuid4().hex},
            "second": {"sketch_id": uuid4().hex, "entity_id": uuid4().hex},
            "branch": "line_left",
        },
        "revisions": [revision],
    }
    old = next(
        s for s in BUILTIN_COMMAND_SPECS if s.id == "drawing.tangency.add" and s.version == 1
    )
    with pytest.raises(ValidationError):
        validate_params(old, params, defs=COMMAND_SCHEMA_DEFS)
    new = next(
        s for s in BUILTIN_COMMAND_SPECS if s.id == "drawing.tangency.add" and s.version == 2
    )
    assert validate_params(new, params, defs=COMMAND_SCHEMA_DEFS)["revisions"] == [revision]


@pytest.mark.parametrize("both_arcs", [False, True])
@pytest.mark.parametrize("reverse_path", [False, True])
@pytest.mark.parametrize("reverse_selection", [False, True])
@pytest.mark.parametrize("trim", [False, True])
def test_selected_adjacent_mixed_segments_round_only_their_junction(
    both_arcs: bool, reverse_path: bool, reverse_selection: bool, trim: bool
) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import ArcEntity

    quarter = 2**0.5 - 1
    points = (
        ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0))
        if both_arcs
        else ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0))
    )
    bulges = (quarter, quarter) if both_arcs else (0, quarter)
    if reverse_path:
        points = tuple(reversed(points))
        bulges = tuple(-value for value in reversed(bulges))
    source = PolylineEntity(uuid4().hex, points, bulges=bulges)
    selected = (1, 0) if reverse_selection else (0, 1)
    result, fillet = polyline_segment_fillet(source, *selected, 1, trim=trim)
    if trim:
        assert fillet is None and result.entity_id == source.entity_id
        parts = polyline_curve_segments(result.points_mm, result.bulges, False, result.entity_id)
        assert len(parts) == 3
        assert tangent_on_curves(parts[0], parts[1]) and tangent_on_curves(parts[1], parts[2])
        assert (
            result.points_mm[0] == source.points_mm[0]
            and result.points_mm[-1] == source.points_mm[-1]
        )
    else:
        assert result == source and isinstance(fillet, ArcEntity)
        originals = polyline_curve_segments(
            source.points_mm, source.bulges, False, source.entity_id
        )
        assert all(tangent_on_curves(segment, fillet) for segment in originals)


def test_selected_adjacent_mixed_segments_zero_radius_is_noop() -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (5, 5)), bulges=(0, 2**0.5 - 1))
    assert polyline_segment_fillet(source, 0, 1, 0) == (source, None)
    with pytest.raises(ValueError, match="零半径"):
        polyline_segment_fillet(source, 0, 1, 0, trim=False)


@pytest.mark.parametrize("reverse_path", [False, True])
@pytest.mark.parametrize("trim", [False, True])
def test_selected_mixed_segments_across_closed_seam(reverse_path: bool, trim: bool) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import ArcEntity

    points = ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0), (20.0, 0.0))
    quarter = 2**0.5 - 1
    source = PolylineEntity(
        uuid4().hex,
        tuple(reversed(points)) if reverse_path else points,
        True,
        bulges=((-quarter if reverse_path else quarter),) * 4,
    )
    result, separate = polyline_segment_fillet(source, 3, 0, 1, trim=trim)
    if trim:
        assert result.closed and len(result.points_mm) == 5 and separate is None
        parts = polyline_curve_segments(result.points_mm, result.bulges, True, result.entity_id)
        assert tangent_on_curves(parts[-1], parts[0]) and tangent_on_curves(parts[0], parts[1])
    else:
        assert result == source and isinstance(separate, ArcEntity)
        parts = polyline_curve_segments(source.points_mm, source.bulges, True, source.entity_id)
        assert tangent_on_curves(parts[-1], separate) and tangent_on_curves(parts[0], separate)


def test_selected_nonadjacent_mixed_segments_fail_without_modifying_source() -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(
        uuid4().hex, ((0, 0), (10, 0), (10, 5), (20, 5), (20, 10)), bulges=(0.5, 0, 0, 0)
    )
    with pytest.raises(ValueError, match="相邻"):
        polyline_segment_fillet(source, 0, 2, 1, first_pick=(5, -2.5), second_pick=(15, 5))
    assert source.points_mm == ((0, 0), (10, 0), (10, 5), (20, 5), (20, 10))


@pytest.mark.parametrize("first_bulge,last_bulge", [(0.2, 0), (0, 0.2), (0.2, 0.2)])
@pytest.mark.parametrize("reverse_path", [False, True])
@pytest.mark.parametrize("reverse_selection", [False, True])
@pytest.mark.parametrize("trim", [False, True])
def test_open_polyline_mixed_end_segments_close_or_create_fillet(
    first_bulge: float, last_bulge: float, reverse_path: bool, reverse_selection: bool, trim: bool
) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import ArcEntity

    points = ((-2, 0), (10, 0), (10, 10), (0, 10), (0, -2))
    bulges = (first_bulge, 0, 0, last_bulge)
    if reverse_path:
        points = tuple(reversed(points))
        bulges = tuple(-value for value in reversed(bulges))
    source = PolylineEntity(uuid4().hex, points, bulges=bulges)
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(segments[0], 0.1), _test_curve_point(segments[-1], 0.9))
    indices = (0, len(segments) - 1)
    if reverse_selection:
        indices, picks = (indices[1], indices[0]), (picks[1], picks[0])
    result, separate = polyline_segment_fillet(
        source, *indices, 1, trim=trim, first_pick=picks[0], second_pick=picks[1]
    )
    if trim:
        assert result.closed and separate is None and result.entity_id == source.entity_id
        assert result.points_mm[1:-1] == source.points_mm[1:-1]
        parts = polyline_curve_segments(result.points_mm, result.bulges, True, result.entity_id)
        assert tangent_on_curves(parts[-2], parts[-1]) and tangent_on_curves(parts[-1], parts[0])
    else:
        assert result == source and isinstance(separate, ArcEntity)
        assert tangent_on_curves(segments[-1], separate) and tangent_on_curves(
            segments[0], separate
        )


@pytest.mark.parametrize("first_bulge,last_bulge", [(0.2, 0), (0, 0.2), (0.2, 0.2)])
@pytest.mark.parametrize("reverse_path", [False, True])
def test_open_polyline_mixed_end_segments_zero_radius_closes(
    first_bulge: float, last_bulge: float, reverse_path: bool
) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_segment_fillet

    points = ((0, 0), (10, 0), (10, 10), (0, 10), (0, 3))
    bulges = (first_bulge, 0, 0, last_bulge)
    if reverse_path:
        points = tuple(reversed(points))
        bulges = tuple(-value for value in reversed(bulges))
    source = PolylineEntity(uuid4().hex, points, bulges=bulges)
    result, separate = polyline_segment_fillet(source, 0, 3, 0)
    assert result.closed and separate is None and result.entity_id == source.entity_id
    assert result.points_mm[1:] == source.points_mm[1:-1]
    assert (
        len(polyline_curve_segments(result.points_mm, result.bulges, True, result.entity_id)) == 4
    )
    with pytest.raises(ValueError, match="零半径"):
        polyline_segment_fillet(source, 0, 3, 0, trim=False)


@pytest.mark.parametrize("first_bulge,last_bulge", [(0.2, 0), (0, 0.2), (0.2, 0.2), (-0.2, -0.2)])
@pytest.mark.parametrize("reverse_selection", [False, True])
@pytest.mark.parametrize("reverse_path", [False, True])
def test_zero_radius_closes_two_mixed_segments(
    first_bulge: float, last_bulge: float, reverse_selection: bool, reverse_path: bool
) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments, polyline_sampled_points
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import polyline_self_intersection

    points = ((0, 0), (10, 0), (10, 10))
    bulges = (first_bulge, last_bulge)
    if reverse_path:
        points = tuple(reversed(points))
        bulges = tuple(-value for value in reversed(bulges))
    source = PolylineEntity(uuid4().hex, points, bulges=bulges)
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    indices = (1, 0) if reverse_selection else (0, 1)
    picks = (_test_curve_point(segments[0], 0.1), _test_curve_point(segments[1], 0.9))
    if reverse_selection:
        picks = (picks[1], picks[0])
    result, separate = polyline_segment_fillet(
        source, *indices, 0, first_pick=picks[0], second_pick=picks[1]
    )
    assert result.closed and separate is None and result.entity_id == source.entity_id
    assert len(result.points_mm) == 3 and source.points_mm[1] in result.points_mm
    curves = polyline_curve_segments(result.points_mm, result.bulges, True, result.entity_id)
    assert len(curves) == 3
    assert polyline_self_intersection(polyline_sampled_points(result)[:-1], closed=True) is None
    assert any(isinstance(curve, ArcEntity) for curve in curves)
    original_arc = next(curve for curve in segments if isinstance(curve, ArcEntity))
    split = curves[:2] if bulges[0] else curves[1:]
    assert all(isinstance(curve, ArcEntity) for curve in split)
    for curve in split:
        assert isinstance(curve, ArcEntity)
        assert curve.center_mm == pytest.approx(original_arc.center_mm)
        assert curve.radius_mm == pytest.approx(original_arc.radius_mm)
        assert math.copysign(1, curve.sweep_angle_deg) == math.copysign(
            1, original_arc.sweep_angle_deg
        )


@pytest.mark.parametrize("reverse_path", [False, True])
@pytest.mark.parametrize("reverse_selection", [False, True])
def test_zero_radius_closure_does_not_discard_picked_arc_side(
    reverse_path: bool, reverse_selection: bool
) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_segment_fillet

    points = ((0, 0), (10, 0), (5.7147, 6.573))
    bulges = (-0.6, 0.0)
    if reverse_path:
        points = tuple(reversed(points))
        bulges = tuple(-bulge for bulge in reversed(bulges))
    source = PolylineEntity(uuid4().hex, points, bulges=bulges)
    curves = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(curves[0], 0.05), _test_curve_point(curves[1], 0.95))
    indices = (0, 1)
    if reverse_selection:
        indices = (1, 0)
        picks = (picks[1], picks[0])
    with pytest.raises(ValueError, match="保留"):
        polyline_segment_fillet(source, *indices, 0, first_pick=picks[0], second_pick=picks[1])
    assert not source.closed


@pytest.mark.parametrize("reverse_path", [False, True])
@pytest.mark.parametrize("reverse_selection", [False, True])
def test_zero_radius_closure_preserves_original_arc_when_midpoint_would_split_it(
    reverse_path: bool, reverse_selection: bool
) -> None:
    from mycad.core.cross_sketch_tangency import unique_unchanged_polyline_segment
    from mycad.core.polyline_curves import polyline_curve_segments, polyline_sampled_points
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import polyline_self_intersection

    points = ((0, 0), (10, 0), (3.7376, 9.017))
    bulges = (0.6, 0.9)
    if reverse_path:
        points = tuple(reversed(points))
        bulges = tuple(-bulge for bulge in reversed(bulges))
    source = PolylineEntity(uuid4().hex, points, bulges=bulges)
    curves = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    picks = (_test_curve_point(curves[0], 0.05), _test_curve_point(curves[1], 0.95))
    indices = (0, 1)
    if reverse_selection:
        indices = (1, 0)
        picks = (picks[1], picks[0])
    result, _ = polyline_segment_fillet(
        source, *indices, 0, first_pick=picks[0], second_pick=picks[1]
    )
    assert result.closed
    assert unique_unchanged_polyline_segment(source, result, 1 if reverse_path else 0) == (
        2 if reverse_path else 1
    )
    assert unique_unchanged_polyline_segment(source, result, 0) == 1
    assert unique_unchanged_polyline_segment(source, result, 1) == 2
    assert polyline_self_intersection(polyline_sampled_points(result)[:-1], closed=True) is None


def test_zero_radius_two_segment_tangent_intersection_is_degenerate() -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((-1, 0), (1, 0), (1, 5)), bulges=(1, 0))
    with pytest.raises(ValueError, match="非退化"):
        polyline_segment_fillet(source, 0, 1, 0, first_pick=(-1, 0), second_pick=(1, 5))
    assert not source.closed


@pytest.mark.parametrize("first_bulge,last_bulge", [(0.2, 0), (0, 0.2), (0.2, 0.2)])
@pytest.mark.parametrize("reverse_selection", [False, True])
def test_open_two_mixed_segments_choose_closure_or_shared_corner_by_picks(
    first_bulge: float, last_bulge: float, reverse_selection: bool
) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(
        uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(first_bulge, last_bulge)
    )
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    indices = (1, 0) if reverse_selection else (0, 1)
    outer = (_test_curve_point(segments[0], 0.1), _test_curve_point(segments[1], 0.9))
    inner = (_test_curve_point(segments[0], 0.75), _test_curve_point(segments[1], 0.25))
    if reverse_selection:
        outer, inner = (outer[1], outer[0]), (inner[1], inner[0])
    closed, arc = polyline_segment_fillet(
        source, *indices, 1, first_pick=outer[0], second_pick=outer[1]
    )
    assert closed.closed and arc is None and len(closed.points_mm) == 3
    assert closed.points_mm[1] == source.points_mm[1]
    parts = polyline_curve_segments(closed.points_mm, closed.bulges, True, closed.entity_id)
    assert tangent_on_curves(parts[-2], parts[-1]) and tangent_on_curves(parts[-1], parts[0])
    rounded, arc = polyline_segment_fillet(
        source, *indices, 1, first_pick=inner[0], second_pick=inner[1]
    )
    assert not rounded.closed and arc is None and len(rounded.points_mm) == 4
    sharp, separate = polyline_segment_fillet(
        source, *indices, 0, first_pick=outer[0], second_pick=outer[1]
    )
    assert sharp.closed and separate is None


@pytest.mark.parametrize("first_bulge,last_bulge", [(0.2, 0), (0, 0.2), (0.2, 0.2)])
def test_mixed_end_fillet_extends_sources_only_when_trimming(
    first_bulge: float, last_bulge: float
) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments, polyline_sampled_points
    from mycad.core.polyline_fillet import polyline_segment_fillet
    from mycad.core.sketch import polyline_self_intersection

    source = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (10, 10), (0, 10), (0, 3)),
        bulges=(first_bulge, 0, 0, last_bulge),
    )
    closed, separate = polyline_segment_fillet(source, 0, 3, 1)
    assert closed.closed and separate is None and closed.points_mm[1:-1] == source.points_mm[1:-1]
    parts = polyline_curve_segments(closed.points_mm, closed.bulges, True, closed.entity_id)
    for first, second in ((parts[-2], parts[-1]), (parts[-1], parts[0])):
        before, after = _test_curve_tangent(first, 1), _test_curve_tangent(second, 0)
        assert sum(a * b for a, b in zip(before, after, strict=True)) > 1 - 1e-8
    assert polyline_self_intersection(polyline_sampled_points(closed)[:-1], closed=True) is None
    with pytest.raises(ValueError, match="不修剪模式"):
        polyline_segment_fillet(source, 0, 3, 1, trim=False)
    assert not source.closed


@pytest.mark.parametrize("first_bulge,last_bulge", [(0.2, 0), (0, 0.2), (0.2, 0.2)])
def test_open_two_mixed_segments_notrim_returns_continuous_major_arc(
    first_bulge: float, last_bulge: float
) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(
        uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(first_bulge, last_bulge)
    )
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    retained, arc = polyline_segment_fillet(
        source,
        0,
        1,
        1,
        trim=False,
        first_pick=_test_curve_point(segments[0], 0.1),
        second_pick=_test_curve_point(segments[1], 0.9),
    )
    assert retained == source and isinstance(arc, ArcEntity)
    assert abs(arc.sweep_angle_deg) > 180
    assert all(tangent_on_curves(segment, arc) for segment in segments)


@pytest.mark.parametrize("both_arcs", [False, True])
@pytest.mark.parametrize("reverse_path", [False, True])
@pytest.mark.parametrize("reverse_selection", [False, True])
@pytest.mark.parametrize("radius", [0.0, 0.5, 1.0])
def test_selected_mixed_segments_replace_existing_tangent_fillet(
    both_arcs: bool, reverse_path: bool, reverse_selection: bool, radius: float
) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments, polyline_segment_fillet

    quarter = 2**0.5 - 1
    points = (
        ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0))
        if both_arcs
        else ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0))
    )
    bulges = (quarter, quarter) if both_arcs else (0, quarter)
    if reverse_path:
        points = tuple(reversed(points))
        bulges = tuple(-value for value in reversed(bulges))
    original = PolylineEntity(uuid4().hex, points, bulges=bulges)
    vertices, rounded_bulges = polyline_fillet_trimmed_segments(original, 1)
    source = PolylineEntity(original.entity_id, vertices, bulges=rounded_bulges)
    indices = (2, 0) if reverse_selection else (0, 2)
    result, separate = polyline_segment_fillet(source, *indices, radius)
    assert separate is None and result.entity_id == source.entity_id
    if radius == 1:
        assert result == source
    elif radius == 0:
        assert len(result.points_mm) == 3
        for actual, expected in zip(result.points_mm, original.points_mm, strict=True):
            assert actual == pytest.approx(expected)
        assert result.bulges == pytest.approx(original.bulges)
    else:
        parts = polyline_curve_segments(result.points_mm, result.bulges, False, result.entity_id)
        assert len(parts) == 3
        assert tangent_on_curves(parts[0], parts[1]) and tangent_on_curves(parts[1], parts[2])
        assert isinstance(parts[1], ArcEntity) and parts[1].radius_mm == pytest.approx(radius)


@pytest.mark.parametrize("both_arcs", [False, True])
@pytest.mark.parametrize("radius", [0.5, 1.0, 1.5])
def test_selected_mixed_existing_fillet_notrim_requires_finite_contacts(
    both_arcs: bool, radius: float
) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments, polyline_segment_fillet

    quarter = 2**0.5 - 1
    points = (
        ((5.0, -5.0), (10.0, 0.0), (15.0, 5.0))
        if both_arcs
        else ((0.0, 0.0), (10.0, 0.0), (5.0, 5.0))
    )
    original = PolylineEntity(
        uuid4().hex, points, bulges=(quarter, quarter) if both_arcs else (0, quarter)
    )
    vertices, bulges = polyline_fillet_trimmed_segments(original, 1)
    source = PolylineEntity(original.entity_id, vertices, bulges=bulges)
    if radius < 1:
        with pytest.raises(ValueError, match="不修剪"):
            polyline_segment_fillet(source, 0, 2, radius, trim=False)
        return
    result, fillet = polyline_segment_fillet(source, 0, 2, radius, trim=False)
    assert result == source and isinstance(fillet, ArcEntity)
    parts = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    assert tangent_on_curves(parts[0], fillet) and tangent_on_curves(parts[2], fillet)
    assert fillet.radius_mm == pytest.approx(radius)


@pytest.mark.parametrize("both_arcs", [False, True])
def test_replacing_one_mixed_fillet_preserves_other_rounded_corner(both_arcs: bool) -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments, polyline_segment_fillet

    quarter = 2**0.5 - 1
    points = (
        ((5, -5), (10, 0), (15, 5), (20, 0)) if both_arcs else ((0, 0), (10, 0), (5, 5), (5, 15))
    )
    source = PolylineEntity(
        uuid4().hex, points, bulges=(quarter, quarter, quarter) if both_arcs else (0, quarter, 0)
    )
    vertices, bulges = polyline_fillet_trimmed_segments(source, 1)
    rounded = PolylineEntity(source.entity_id, vertices, bulges=bulges)
    changed, _ = polyline_segment_fillet(rounded, 0, 2, 0.5)
    assert changed.points_mm[-3:] == rounded.points_mm[-3:]
    assert changed.bulges[-2:] == pytest.approx(rounded.bulges[-2:])


@pytest.mark.parametrize("reverse_selection", [False, True])
@pytest.mark.parametrize("radius", [0.0, 0.5, 1.0])
def test_replace_mixed_fillet_across_closed_seam(reverse_selection: bool, radius: float) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_segment_fillet

    quarter = 2**0.5 - 1
    original = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (5, 5), (-5, 5), (-5, -5)),
        True,
        bulges=(0, quarter, 0, 0, 0),
    )
    rounded, _ = polyline_segment_fillet(original, 0, 1, 1)
    source = PolylineEntity(
        original.entity_id,
        (*rounded.points_mm[1:], rounded.points_mm[0]),
        True,
        bulges=(*rounded.bulges[1:], rounded.bulges[0]),
    )
    indices = (
        (1, len(source.points_mm) - 1) if reverse_selection else (len(source.points_mm) - 1, 1)
    )
    result, separate = polyline_segment_fillet(source, *indices, radius)
    assert result.closed and result.entity_id == source.entity_id and separate is None
    assert all(point in result.points_mm for point in ((-5, 5), (-5, -5)))
    if radius == 1:
        assert result == source
    elif radius == 0:
        assert len(result.points_mm) == len(source.points_mm) - 1
    else:
        parts = polyline_curve_segments(result.points_mm, result.bulges, True, result.entity_id)
        assert tangent_on_curves(parts[0], parts[1]) and tangent_on_curves(parts[1], parts[2])
        assert isinstance(parts[1], ArcEntity) and parts[1].radius_mm == pytest.approx(radius)


def test_selected_mixed_segments_reject_non_tangent_intermediate_arc() -> None:
    from mycad.core.polyline_fillet import polyline_fillet_trimmed_segments, polyline_segment_fillet

    original = PolylineEntity(
        uuid4().hex,
        ((0, 0), (10, 0), (5, 5), (5, 15)),
        bulges=(0, 2**0.5 - 1, 0),
    )
    points, bulges = polyline_fillet_trimmed_segments(original, 1)
    invalid_bulges = (bulges[0], bulges[1] * 1.2, *bulges[2:])
    source = PolylineEntity(original.entity_id, points, bulges=invalid_bulges)
    with pytest.raises(ValueError, match="相切圆角"):
        polyline_segment_fillet(source, 0, 2, 0.5)
    assert source.points_mm == points and source.bulges == invalid_bulges


@pytest.mark.parametrize("reverse_selection", [False, True])
@pytest.mark.parametrize("radius", [0.0, 1.0])
def test_selected_lines_replace_intervening_straight_segment(
    reverse_selection: bool, radius: float
) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (8, 0), (10, 2), (10, 10), (15, 10)))
    indices = (2, 0) if reverse_selection else (0, 2)
    result, arc = polyline_segment_fillet(source, *indices, radius)
    assert arc is None and result.entity_id == source.entity_id
    assert result.points_mm[-1] == source.points_mm[-1]
    if radius == 0:
        assert result.points_mm == ((0, 0), (10, 0), (10, 10), (15, 10))
    else:
        parts = polyline_curve_segments(result.points_mm, result.bulges, False, result.entity_id)
        assert isinstance(parts[1], ArcEntity) and parts[1].radius_mm == pytest.approx(radius)
        assert tangent_on_curves(parts[0], parts[1]) and tangent_on_curves(parts[1], parts[2])


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("reverse_selection", [False, True])
def test_selected_lines_skip_straight_segment_notrim_finite_contacts(
    closed: bool, reverse_selection: bool
) -> None:
    from mycad.core.fillet_curves import tangent_on_curves
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (8, 0), (10, 2), (10, 10), (0, 10)), closed)
    indices = (2, 0) if reverse_selection else (0, 2)
    with pytest.raises(ValueError, match="不修剪"):
        polyline_segment_fillet(source, *indices, 1, trim=False)
    unchanged, arc = polyline_segment_fillet(source, *indices, 3, trim=False)
    assert unchanged == source and isinstance(arc, ArcEntity)
    parts = polyline_curve_segments(
        source.points_mm,
        source.bulges or (0.0,) * (len(source.points_mm) if closed else len(source.points_mm) - 1),
        source.closed,
        source.entity_id,
    )
    assert tangent_on_curves(parts[0], arc) and tangent_on_curves(parts[2], arc)


@pytest.mark.parametrize("radius", [0.0, 1.0])
def test_selected_lines_skip_straight_segment_across_closed_seam(radius: float) -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((8, 0), (10, 2), (10, 10), (0, 10), (0, 0)), True)
    result, arc = polyline_segment_fillet(source, 4, 1, radius)
    assert result.closed and result.entity_id == source.entity_id and arc is None
    assert (0, 10) in result.points_mm
    assert len(result.points_mm) == (4 if radius == 0 else 5)


@pytest.mark.parametrize("radius", [0.0, 1.0])
def test_three_segment_open_path_pick_selects_replacement_or_closure(radius: float) -> None:
    from mycad.core.polyline_fillet import polyline_segment_fillet

    source = PolylineEntity(uuid4().hex, ((0, 0), (8, 0), (10, 2), (10, 10)))
    replacement, _ = polyline_segment_fillet(
        source, 0, 2, radius, first_pick=(6, 0), second_pick=(10, 4)
    )
    assert not replacement.closed
    with pytest.raises(ValueError, match="无法保留"):
        polyline_segment_fillet(source, 0, 2, radius, first_pick=(1, 0), second_pick=(10, 9))
