# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact ellipses produce bounded-error offset geometry."""

from typing import Protocol, cast
from uuid import uuid4

import pytest

from mycad.core.sketch import EllipseEntity


class DistanceToPoint(Protocol):
    def distance_to(self, other: tuple[float, float, float]) -> float: ...


@pytest.mark.parametrize("distance", [-0.5, 0.5])
def test_closed_ellipse_offset_is_closed_and_preserves_distance(distance: float) -> None:
    from mycad.geom.offset_ellipse import ellipse_edge, offset_ellipse

    source = EllipseEntity(uuid4().hex, (0, 0), 5, 3, layer_name="0")
    pieces = offset_ellipse(source, distance)
    assert pieces
    assert pieces[0].control_points_mm[0] == pytest.approx(
        pieces[-1].control_points_mm[-1], abs=0.001
    )
    edge = cast("DistanceToPoint", ellipse_edge(source))
    for piece in pieces:
        for point in piece.sampled_points()[::12]:
            assert edge.distance_to((point[0], point[1], 0)) == pytest.approx(
                abs(distance), abs=0.001
            )


def test_clockwise_ellipse_arc_uses_left_hand_side_and_keeps_endpoints() -> None:
    from mycad.geom.offset_ellipse import offset_ellipse

    source = EllipseEntity(uuid4().hex, (0, 0), 5, 3, 0, 0, -90)
    pieces = offset_ellipse(source, 0.5)
    assert pieces[0].control_points_mm[0] == pytest.approx((5.5, 0), abs=0.001)
    assert pieces[-1].control_points_mm[-1] == pytest.approx((0, -3.5), abs=0.001)


def test_ellipse_edge_follows_arbitrary_sketch_frame() -> None:
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.geom.offset_ellipse import ellipse_edge

    source = EllipseEntity(uuid4().hex, (2, 3), 5, 3, 25, 15, -110)
    frame = WorkPlaneFrame.xz()
    edge = ellipse_edge(source, frame=frame)
    for parameter in (0, 1):
        actual = edge.position_at(parameter)
        expected = frame.local_to_world(source.point_at(parameter))
        actual_point = (actual.X, actual.Y, actual.Z)
        assert actual_point == pytest.approx(expected, abs=1e-6)
    assert (
        cast("DistanceToPoint", edge).distance_to(frame.local_to_world(source.point_at(0.5))) < 1e-6
    )


def test_closed_ellipse_produces_exact_sketch_region() -> None:
    import math

    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.geom.sketch_profiles import make_sketch_regions

    source = EllipseEntity(uuid4().hex, (2, 3), 5, 3, 25)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xz(), (source,))
    regions = make_sketch_regions(sketch)
    assert len(regions) == 1
    assert regions[0].face.area == pytest.approx(math.pi * 15, rel=1e-8)


@pytest.mark.parametrize("sweep", [360, -360])
def test_closed_ellipse_offset_preserves_source_direction(sweep: int) -> None:
    from mycad.geom.offset_ellipse import offset_ellipse

    source = EllipseEntity(uuid4().hex, (3, 2), 5, 3, 35, 40, sweep)
    pieces = offset_ellipse(source, 0.5)
    points = tuple(point for piece in pieces for point in piece.sampled_points())
    area = sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points, (*points[1:], points[0]), strict=True)
    )
    assert area * sweep > 0


@pytest.mark.parametrize("distance", [1.8, 2.0])
def test_inward_ellipse_offset_rejects_cusp_or_self_intersection(distance: float) -> None:
    from mycad.geom.offset_ellipse import offset_ellipse

    source = EllipseEntity(uuid4().hex, (0, 0), 5, 3)
    with pytest.raises(ValueError, match="曲率"):
        offset_ellipse(source, distance)


def test_arc_can_offset_beyond_full_ellipse_minimum_when_local_curvature_allows() -> None:
    from mycad.geom.offset_ellipse import ellipse_edge, offset_ellipse

    source = EllipseEntity(uuid4().hex, (0, 0), 5, 3, 0, 70, 40)
    pieces = offset_ellipse(source, 2)
    assert pieces
    edge = cast("DistanceToPoint", ellipse_edge(source))
    for piece in pieces:
        for point in piece.sampled_points()[::12]:
            assert edge.distance_to((point[0], point[1], 0)) == pytest.approx(2, abs=0.001)


def test_closed_ellipse_result_can_be_offset_again_as_one_path() -> None:
    from mycad.geom.offset_ellipse import ellipse_edge, offset_ellipse
    from mycad.geom.offset_spline import offset_spline_path

    source = EllipseEntity(uuid4().hex, (0, 0), 5, 3)
    first = offset_ellipse(source, -0.5)
    second = offset_spline_path(first, -0.5)
    assert second
    assert second[0].control_points_mm[0] == pytest.approx(
        second[-1].control_points_mm[-1], abs=1e-6
    )
    edge = cast("DistanceToPoint", ellipse_edge(source))
    for piece in second:
        for point in piece.sampled_points()[::12]:
            assert edge.distance_to((point[0], point[1], 0)) == pytest.approx(1, abs=0.002)
