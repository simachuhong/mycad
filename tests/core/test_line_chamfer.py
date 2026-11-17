# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent 2D chamfers use picked sides of finite lines."""

from uuid import uuid4

import pytest

from mycad.core.line_chamfer import line_chamfer
from mycad.core.sketch import LineEntity


def _line(a: tuple[float, float], b: tuple[float, float]) -> LineEntity:
    return LineEntity(uuid4().hex, a, b)


def test_line_chamfer_distances_trim_and_extend() -> None:
    first, second = _line((3, 0), (10, 0)), _line((0, 4), (0, 10))
    a, b, edge = line_chamfer(first, second, (8, 0), (0, 8), 2, 3, uuid4().hex)
    assert a.start_mm == pytest.approx((2, 0)) and a.end_mm == first.end_mm
    assert b.start_mm == pytest.approx((0, 3)) and b.end_mm == second.end_mm
    assert edge is not None and edge.start_mm == pytest.approx((2, 0))
    assert edge.end_mm == pytest.approx((0, 3))
    assert a.entity_id == first.entity_id and b.entity_id == second.entity_id


def test_line_chamfer_angle_no_trim_and_zero_corner() -> None:
    first, second = _line((0, 0), (10, 0)), _line((0, 0), (0, 10))
    a, b, edge = line_chamfer(
        first, second, (8, 0), (0, 8), 2, 0, uuid4().hex, angle_deg=45, trim=False
    )
    assert (a, b) == (first, second)
    assert edge is not None and edge.start_mm == pytest.approx((2, 0))
    assert edge.end_mm == pytest.approx((0, 2))
    a, b, edge = line_chamfer(first, second, (8, 0), (0, 8), 0, 0, uuid4().hex)
    assert (a, b, edge) == (first, second, None)


@pytest.mark.parametrize("first_distance,second_distance", [(-1, 1), (11, 1), (float("nan"), 1)])
def test_line_chamfer_rejects_invalid_or_too_large(
    first_distance: float, second_distance: float
) -> None:
    first, second = _line((0, 0), (10, 0)), _line((0, 0), (0, 10))
    with pytest.raises(ValueError):
        line_chamfer(first, second, (8, 0), (0, 8), first_distance, second_distance, uuid4().hex)


def test_angle_chamfer_uses_angle_from_first_line_at_oblique_corner() -> None:
    first = _line((0, 0), (10, 0))
    second = _line((0, 0), (5, 5 * 3**0.5))
    _, _, edge = line_chamfer(
        first, second, (8, 0), (4, 4 * 3**0.5), 2, 0, uuid4().hex, angle_deg=30
    )
    assert edge is not None and edge.end_mm == pytest.approx((0.5, 3**0.5 / 2))


def test_polyline_chamfer_all_open_and_closed() -> None:
    from mycad.core.line_chamfer import polyline_chamfer
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    result, edges = polyline_chamfer(source, 2, 3, tuple(uuid4().hex for _ in source.points_mm))
    assert result.entity_id == source.entity_id and not edges
    assert result.points_mm == ((0, 0), (8, 0), (10, 3), (10, 10))
    square = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), closed=True)
    result, edges = polyline_chamfer(square, 2, 2, tuple(uuid4().hex for _ in square.points_mm))
    assert result.closed and len(result.points_mm) == 8 and not edges
    assert result.points_mm[:2] == ((0, 2), (2, 0))


def test_polyline_chamfer_notrim_and_skip_short_segments() -> None:
    from mycad.core.line_chamfer import polyline_chamfer
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    identities = tuple(uuid4().hex for _ in source.points_mm)
    result, edges = polyline_chamfer(source, 2, 2, identities, trim=False)
    assert result == source and len(edges) == 1 and edges[0].entity_id == identities[1]
    short = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 1), (20, 1)))
    result, _ = polyline_chamfer(short, 2, 2, tuple(uuid4().hex for _ in short.points_mm))
    assert result.points_mm == short.points_mm


def test_polyline_chamfer_selected_corner_respects_pick_order() -> None:
    from mycad.core.line_chamfer import polyline_chamfer
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (20, 10)))
    identities = tuple(uuid4().hex for _ in source.points_mm)
    result, _ = polyline_chamfer(source, 2, 3, identities, corner_indices=(1,), reverse=True)
    assert result.points_mm == ((0, 0), (7, 0), (10, 2), (10, 10), (20, 10))


def test_zero_angle_and_distance_join_lines_at_intersection() -> None:
    first = _line((2, 0), (10, 0))
    second = _line((0, 3), (0, 10))
    a, b, edge = line_chamfer(first, second, (8, 0), (0, 8), 0, 0, uuid4().hex, angle_deg=0)
    assert edge is None and a.start_mm == (0, 0) and b.start_mm == (0, 0)


def test_chamfer_joins_polyline_and_line_and_preserves_polyline_identity() -> None:
    from mycad.core.polyline_fillet import chamfer_joined_paths
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    other = _line((15, -10), (15, -2))
    joined, edge = chamfer_joined_paths(source, 0, other, None, (5, 0), (15, -8), 2, 3, uuid4().hex)
    assert edge is not None and joined is not None and joined.entity_id == source.entity_id
    assert joined.points_mm == ((0, 0), (13, 0), (15, -3), (15, -10))


def test_chamfer_two_polylines_and_untrimmed_retain_identity() -> None:
    from mycad.core.polyline_fillet import chamfer_joined_paths
    from mycad.core.sketch import PolylineEntity

    first = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    second = PolylineEntity(uuid4().hex, ((15, -10), (15, -2), (20, -2)))
    joined, edge = chamfer_joined_paths(first, 0, second, 0, (5, 0), (15, -8), 2, 3, uuid4().hex)
    assert joined is not None and joined.entity_id == first.entity_id
    assert joined.points_mm == ((0, 0), (13, 0), (15, -3), (15, -10))
    untrimmed, separate = chamfer_joined_paths(
        first, 0, second, 0, (5, 0), (15, -8), 2, 3, uuid4().hex, trim=False
    )
    assert untrimmed is None and separate is not None
    assert (
        edge is not None and separate.start_mm == edge.start_mm and separate.end_mm == edge.end_mm
    )


def test_rectangle_chamfer_creates_closed_polyline_on_same_layer() -> None:
    from mycad.core.line_chamfer import rectangle_chamfer
    from mycad.core.sketch import RectangleEntity

    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 10), layer_name="profile")
    identity = uuid4().hex
    result, edges = rectangle_chamfer(
        rectangle, 2, 2, identity, tuple(uuid4().hex for _ in range(4))
    )
    assert result.entity_id == identity and result.closed and result.layer_name == "profile"
    assert len(result.points_mm) == 8 and not edges


def test_polyline_chamfer_replaces_one_intervening_arc() -> None:
    from mycad.core.line_chamfer import polyline_chamfer_between
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(
        uuid4().hex, ((0, 0), (8, 0), (10, 2), (10, 10)), bulges=(0, 2**0.5 - 1, 0)
    )
    changed, edge = polyline_chamfer_between(source, 0, 2, (4, 0), (10, 6), 2, 3, uuid4().hex)
    assert changed.points_mm == ((0, 0), (8, 0), (10, 3), (10, 10))
    assert not changed.bulges and edge is None
    unchanged, edge = polyline_chamfer_between(
        source, 0, 2, (4, 0), (10, 6), 2, 3, uuid4().hex, trim=False
    )
    assert unchanged == source and edge is not None


def test_polyline_chamfer_closes_open_ends() -> None:
    from mycad.core.line_chamfer import polyline_chamfer_close
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (2, 2)))
    result, edge = polyline_chamfer_close(source, 0, 2, (2, 0), (3, 3), 2, 2, uuid4().hex)
    assert result.closed and result.entity_id == source.entity_id and edge is None
    assert result.points_mm[0] == pytest.approx((2, 0))
    assert result.points_mm[-1] == pytest.approx((2**0.5, 2**0.5))
    untouched, edge = polyline_chamfer_close(
        source, 0, 2, (2, 0), (3, 3), 2, 2, uuid4().hex, trim=False
    )
    assert untouched == source and edge is not None


def test_polyline_separated_chamfer_rejects_picks_that_would_discard_outer_path() -> None:
    from mycad.core.line_chamfer import polyline_chamfer_between
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (12, 0), (10, 2), (10, 10)))
    with pytest.raises(ValueError, match="保留侧"):
        polyline_chamfer_between(source, 0, 2, (11, 0), (10, 6), 1, 2, uuid4().hex)


def test_closed_polyline_chamfer_between_segments_across_seam() -> None:
    from mycad.core.line_chamfer import polyline_chamfer_between
    from mycad.core.sketch import PolylineEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5), (10, 5), (10, -5)), closed=True)
    result, edge = polyline_chamfer_between(source, 4, 1, (8, -4), (5, 4), 1, 1, uuid4().hex)
    assert edge is None and result.closed and result.entity_id == source.entity_id
    assert (0, 0) not in result.points_mm and (5, 0) not in result.points_mm
    assert (5, 5) in result.points_mm and (10, -5) in result.points_mm
