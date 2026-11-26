# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Spline offset fitting keeps a verified geometric approximation bound."""

import math
from typing import Protocol, cast

import pytest

from mycad.geom import offset_spline


def _bezier(points: tuple[tuple[float, float], ...], t: float) -> tuple[float, float]:
    work: list[tuple[float, float]] = list(points)
    while len(work) > 1:
        work = [
            ((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1])
            for a, b in zip(work, work[1:], strict=False)
        ]
    return work[0]


def test_quintic_to_cubic_preserves_endpoints_and_certified_bound() -> None:
    control = ((0.0, 0.0), (2.0, 3.0), (4.0, -2.0), (6.0, 4.0), (8.0, -1.0), (10.0, 0.0))
    pieces = offset_spline.reduce_bezier(control, 0.001)
    assert len(pieces) > 1
    assert pieces[0][0] == control[0]
    assert pieces[-1][-1] == control[-1]
    assert all(a[-1] == b[0] for a, b in zip(pieces, pieces[1:], strict=False))
    # The implementation recursively bisects; the public bound is verified separately
    # against the original curve using the returned piece parameter intervals.
    for points, start, end in offset_spline.reduce_bezier_with_intervals(control, 0.001):
        for i in range(101):
            t = i / 100
            assert (
                math.dist(_bezier(control, start + t * (end - start)), _bezier(points, t)) <= 0.001
            )
    with pytest.raises(ValueError):
        offset_spline.reduce_bezier(control, 0.0)


def test_spline_offset_preserves_distance_endpoints_and_layer() -> None:
    from uuid import uuid4

    from mycad.core.sketch import Sketch, SplineEntity, WorkPlaneFrame
    from mycad.geom.sketch_profiles import spline_edge

    source = SplineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5), (10, 5)), layer_name="splines")
    copies = offset_spline.offset_spline(source, 1.0)
    assert copies and all(item.layer_name == "splines" for item in copies)
    assert copies[0].control_points_mm[0] == pytest.approx((0, 1), abs=0.001)
    assert copies[-1].control_points_mm[-1] == pytest.approx((10, 6), abs=0.001)
    assert all(
        a.control_points_mm[-1] == pytest.approx(b.control_points_mm[0], abs=1e-7)
        for a, b in zip(copies, copies[1:], strict=False)
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), ())

    class DistanceToPoint(Protocol):
        def distance_to(self, other: tuple[float, float, float]) -> float: ...

    original = cast("DistanceToPoint", spline_edge(sketch, source))
    for piece in copies:
        for point in piece.sampled_points()[::8]:
            assert original.distance_to((point[0], point[1], 0)) == pytest.approx(1.0, abs=0.001)


def test_offset_connected_spline_pieces_as_one_path() -> None:
    from uuid import uuid4

    from mycad.core.sketch import SplineEntity

    source = SplineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5), (10, 5)))
    first = offset_spline.offset_spline(source, 1)
    assert len(first) > 1
    second = offset_spline.offset_spline_path(first, 1)
    assert second[0].control_points_mm[0] == pytest.approx((0, 2), abs=0.003)
    assert second[-1].control_points_mm[-1] == pytest.approx((10, 7), abs=0.003)
    assert all(
        math.dist(left.control_points_mm[-1], right.control_points_mm[0]) < 1e-6
        for left, right in zip(second, second[1:], strict=False)
    )


def test_spline_offset_preserves_disconnected_branches_in_source_order() -> None:
    from uuid import uuid4

    from mycad.core.sketch import SplineEntity

    source = SplineEntity(
        uuid4().hex,
        (
            (0, 0),
            (2, -0.30887313143051287),
            (4, -14.544001272786543),
            (6, -11.928687954497818),
            (8, -2.1618404888753933),
            (10, -14.31667550479806),
            (12, 0.8198072473745395),
            (14, 0),
        ),
        layer_name="splines",
    )
    copies = offset_spline.offset_spline(source, 1)
    gaps = [
        math.dist(left.control_points_mm[-1], right.control_points_mm[0])
        for left, right in zip(copies, copies[1:], strict=False)
    ]
    assert sum(gap > 0.001 for gap in gaps) == 1
    assert all(gap < 1e-6 or gap > 0.001 for gap in gaps)
    assert copies[0].control_points_mm[0] == pytest.approx((0.152627, 0.988284), abs=0.001)
    assert copies[-1].control_points_mm[-1] == pytest.approx((14.379277, 0.925283), abs=0.001)
    assert all(piece.layer_name == "splines" for piece in copies)


def test_multibranch_offset_tracks_reversed_source_direction() -> None:
    from uuid import uuid4

    from mycad.core.sketch import SplineEntity

    source = SplineEntity(
        uuid4().hex,
        tuple(
            reversed(
                (
                    (0, 0),
                    (2, -0.30887313143051287),
                    (4, -14.544001272786543),
                    (6, -11.928687954497818),
                    (8, -2.1618404888753933),
                    (10, -14.31667550479806),
                    (12, 0.8198072473745395),
                    (14, 0),
                )
            )
        ),
    )
    copies = offset_spline.offset_spline(source, -1)
    gaps = [
        math.dist(left.control_points_mm[-1], right.control_points_mm[0])
        for left, right in zip(copies, copies[1:], strict=False)
    ]
    assert sum(gap > 0.001 for gap in gaps) == 1
    assert copies[0].control_points_mm[0] == pytest.approx((14.379277, 0.925283), abs=0.001)
    assert copies[-1].control_points_mm[-1] == pytest.approx((0.152627, 0.988284), abs=0.001)


def test_open_spline_offset_retains_closed_and_open_branches() -> None:
    from uuid import uuid4

    from mycad.core.sketch import SplineEntity

    source = SplineEntity(
        uuid4().hex,
        (
            (0, 0),
            (-6.786802587550828, -4.4473769780254),
            (-6.977086685631252, -11.85600115039905),
            (-4.030346433512766, 3.774678688938385),
            (-11.919812531441856, 6.223357645296851),
            (-5.211271800158748, -7.731866967633548),
            (-8.694942377770245, -8.718534142072972),
            (6.691872686821082, 3.9656816441476934),
        ),
    )
    copies = offset_spline.offset_spline(source, 1)
    branches: list[list[SplineEntity]] = [[copies[0]]]
    for piece in copies[1:]:
        if math.dist(branches[-1][-1].control_points_mm[-1], piece.control_points_mm[0]) > 1e-6:
            branches.append([])
        branches[-1].append(piece)
    assert len(branches) == 3
    closed = [
        branch
        for branch in branches
        if math.dist(branch[0].control_points_mm[0], branch[-1].control_points_mm[-1]) < 1e-6
    ]
    assert len(closed) == 1
    assert all(len(branch) > 1 for branch in branches)
    source_loop = closed[0]
    sampled: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for piece in source_loop:
        for index in range(25):
            parameter = index / 24
            point = piece.point_at(parameter)
            before = piece.point_at(max(0.0, parameter - 0.001))
            after = piece.point_at(min(1.0, parameter + 0.001))
            sampled.append((point, (after[0] - before[0], after[1] - before[1])))
    again = offset_spline.offset_spline_path(tuple(source_loop), 0.1)
    assert again
    for piece in again:
        point = piece.point_at(0.5)
        before, after = piece.point_at(0.49), piece.point_at(0.51)
        _closest, tangent = min(sampled, key=lambda item: math.dist(point, item[0]))
        assert (after[0] - before[0]) * tangent[0] + (after[1] - before[1]) * tangent[1] > 0


def test_closed_branch_direction_reverses_with_source() -> None:
    from uuid import uuid4

    from mycad.core.sketch import SplineEntity

    points = (
        (0, 0),
        (-6.786802587550828, -4.4473769780254),
        (-6.977086685631252, -11.85600115039905),
        (-4.030346433512766, 3.774678688938385),
        (-11.919812531441856, 6.223357645296851),
        (-5.211271800158748, -7.731866967633548),
        (-8.694942377770245, -8.718534142072972),
        (6.691872686821082, 3.9656816441476934),
    )

    def closed_area(source: SplineEntity, distance: float) -> float:
        pieces = offset_spline.offset_spline(source, distance)
        branches: list[list[SplineEntity]] = [[pieces[0]]]
        for piece in pieces[1:]:
            if math.dist(branches[-1][-1].control_points_mm[-1], piece.control_points_mm[0]) > 1e-6:
                branches.append([])
            branches[-1].append(piece)
        closed = next(
            branch
            for branch in branches
            if math.dist(branch[0].control_points_mm[0], branch[-1].control_points_mm[-1]) < 1e-6
        )
        vertices = tuple(piece.control_points_mm[0] for piece in closed)
        return sum(
            left[0] * right[1] - right[0] * left[1]
            for left, right in zip(vertices, (*vertices[1:], vertices[0]), strict=True)
        )

    forward = closed_area(SplineEntity(uuid4().hex, points), 1)
    backward = closed_area(SplineEntity(uuid4().hex, tuple(reversed(points))), -1)
    assert abs(forward) > 1e-3
    assert backward == pytest.approx(-forward, rel=0.01)


def test_closed_branch_is_not_merged_with_a_touching_next_branch() -> None:
    from uuid import uuid4

    from mycad.core.sketch import EllipseEntity, SplineEntity
    from mycad.geom.offset_ellipse import offset_ellipse

    closed = offset_ellipse(EllipseEntity(uuid4().hex, (0, 0), 5, 3), -0.5)
    start = closed[-1].control_points_mm[-1]
    line = SplineEntity(
        uuid4().hex,
        (start, (start[0] + 1, start[1]), (start[0] + 2, start[1]), (start[0] + 3, start[1])),
    )
    output = offset_spline.offset_spline_path((*closed, line), -0.5)
    endpoints = [piece.control_points_mm[0] for piece in output]
    endpoints.extend(piece.control_points_mm[-1] for piece in output)
    assert any(math.dist(point, (start[0] + 3, start[1] - 0.5)) < 0.001 for point in endpoints)
    branches: list[list[SplineEntity]] = [[output[0]]]
    for piece in output[1:]:
        if math.dist(branches[-1][-1].control_points_mm[-1], piece.control_points_mm[0]) > 1e-6:
            branches.append([])
        branches[-1].append(piece)
    assert any(
        math.dist(branch[0].control_points_mm[0], branch[-1].control_points_mm[-1]) < 1e-6
        for branch in branches
    )
