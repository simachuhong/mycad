# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Closed multi-loop offsets retain geometric branches and source metadata."""

from uuid import uuid4

import pytest

from mycad.core.sketch import PolylineEntity
from mycad.geom import drawing_offset


@pytest.mark.parametrize("reverse", [False, True])
def test_narrow_neck_splits_into_two_paths(reverse: bool) -> None:
    points = (
        (0, 0),
        (4, 0),
        (4, 1),
        (6, 1),
        (6, 0),
        (10, 0),
        (10, 4),
        (6, 4),
        (6, 3),
        (4, 3),
        (4, 4),
        (0, 4),
    )
    source = PolylineEntity(
        uuid4().hex, tuple(reversed(points)) if reverse else points, True, True, "construction"
    )
    result = drawing_offset.offset_closed_path(source, -1.1 if reverse else 1.1)
    assert len(result) == 2
    assert all(
        item.closed and item.construction and item.layer_name == "construction" for item in result
    )
    assert len({item.entity_id for item in result}) == 2
    boxes = sorted(
        (
            min(p[0] for p in item.points_mm),
            max(p[0] for p in item.points_mm),
            min(p[1] for p in item.points_mm),
            max(p[1] for p in item.points_mm),
        )
        for item in result
    )
    assert boxes[0] == pytest.approx((1.1, 2.9, 1.1, 2.9))
    assert boxes[1] == pytest.approx((7.1, 8.9, 1.1, 2.9))


@pytest.mark.parametrize("gap_type", [0, 1, 2])
def test_corner_modes_preserve_exact_geometry(gap_type: int) -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import ArcEntity, LineEntity

    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True)
    result = drawing_offset.offset_closed_path(source, -2, gap_type=gap_type)
    assert len(result) == 1
    path = result[0]
    curves = polyline_curve_segments(
        path.points_mm, path.bulges or (0.0,) * len(path.points_mm), True, path.entity_id
    )
    arcs = [item for item in curves if isinstance(item, ArcEntity)]
    assert len(arcs) == (4 if gap_type == 1 else 0)
    assert all(arc.radius_mm == pytest.approx(2) for arc in arcs)
    if gap_type == 2:
        diagonals = [
            line
            for line in curves
            if isinstance(line, LineEntity)
            and abs(line.start_mm[0] - line.end_mm[0]) > 1e-6
            and abs(line.start_mm[1] - line.end_mm[1]) > 1e-6
        ]
        assert len(diagonals) == 4
        assert all(
            abs(line.end_mm[0] - line.start_mm[0]) == pytest.approx(2 * (2 - 2**0.5))
            for line in diagonals
        )


def test_split_path_with_circular_bulge_preserves_arc_segments() -> None:
    source = PolylineEntity(
        uuid4().hex,
        (
            (0, 0),
            (4, 0),
            (4, 1),
            (6, 1),
            (6, 0),
            (10, 0),
            (10, 4),
            (6, 4),
            (6, 3),
            (4, 3),
            (4, 4),
            (0, 4),
        ),
        True,
        bulges=(0, 0, 0, 0, 0, 0, 0.2, 0, 0, 0, 0, 0),
    )
    result = drawing_offset.offset_closed_path(source, 1.1)
    assert len(result) == 2
    assert any(any(abs(bulge) > 1e-8 for bulge in item.bulges) for item in result)
    assert all(item.closed for item in result)


def test_invalid_curved_source_does_not_produce_offset() -> None:
    source = PolylineEntity(
        uuid4().hex,
        ((0, 0), (8, 8), (0, 8), (8, 0)),
        True,
        bulges=(0.1, 0, 0, 0),
    )
    with pytest.raises(ValueError):
        drawing_offset.offset_closed_path(source, -1)


def test_open_path_collapsed_segments_are_removed() -> None:
    source = PolylineEntity(uuid4().hex, ((0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (6, 4)))
    paths = drawing_offset.offset_closed_path(source, 2)
    assert len(paths) == 1
    assert not paths[0].closed
    for actual, expected in zip(paths[0].points_mm, ((0, 2), (0, 6), (6, 6)), strict=True):
        assert actual == pytest.approx(expected)


def test_curved_path_chamfer_preserves_original_offset_arc() -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import ArcEntity

    source = PolylineEntity(
        uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True, bulges=(0, 0, 0.2, 0)
    )
    source_segments = polyline_curve_segments(
        source.points_mm, source.bulges, True, source.entity_id
    )
    original = next(item for item in source_segments if isinstance(item, ArcEntity))
    result = drawing_offset.offset_closed_path(source, -2, 2)
    assert len(result) == 1
    path = result[0]
    curves = polyline_curve_segments(path.points_mm, path.bulges, True, path.entity_id)
    arcs = [item for item in curves if isinstance(item, ArcEntity)]
    assert len(arcs) == 1
    assert arcs[0].center_mm == pytest.approx(original.center_mm)
    assert arcs[0].radius_mm == pytest.approx(original.radius_mm + 2)


def test_reversed_curved_path_chamfer_preserves_arc_radius() -> None:
    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import ArcEntity

    source = PolylineEntity(
        uuid4().hex, ((0, 10), (10, 10), (10, 0), (0, 0)), True, bulges=(-0.2, 0, 0, 0)
    )
    original = next(
        item
        for item in polyline_curve_segments(source.points_mm, source.bulges, True, source.entity_id)
        if isinstance(item, ArcEntity)
    )
    path = drawing_offset.offset_closed_path(source, 2, 2)[0]
    arcs = [
        item
        for item in polyline_curve_segments(path.points_mm, path.bulges, True, path.entity_id)
        if isinstance(item, ArcEntity)
    ]
    assert len(arcs) == 1
    assert arcs[0].center_mm == pytest.approx(original.center_mm)
    assert arcs[0].radius_mm == pytest.approx(original.radius_mm + 2)


def test_open_curved_path_with_collapsed_segments_preserves_arc() -> None:
    source = PolylineEntity(
        uuid4().hex,
        ((0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (6, 4), (8, 4)),
        bulges=(0, 0, 0, 0, 0, 0.2),
    )
    paths = drawing_offset.offset_closed_path(source, 2)
    assert paths
    assert all(not path.closed for path in paths)
    assert any(path.bulges for path in paths)


def test_open_curved_self_crossing_is_rejected() -> None:
    source = PolylineEntity(uuid4().hex, ((0, 0), (8, 8), (0, 8), (8, 0)), bulges=(0.1, 0, 0))
    with pytest.raises(ValueError):
        drawing_offset.offset_closed_path(source, 1)
