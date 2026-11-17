# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact affine projection between sketch work planes."""

import pytest

from mycad.core.sketch import WorkPlaneFrame
from mycad.core.sketch_projection import plane_projection


def test_parallel_projection_maps_origin_and_axes() -> None:
    source = WorkPlaneFrame(
        origin_mm=(3, 4, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    projection = plane_projection(source, WorkPlaneFrame.xy(), (0, 0, -1))
    assert projection.map_point((2, 7)) == pytest.approx((5, 11))
    assert projection.u_axis == pytest.approx((1, 0))
    assert projection.v_axis == pytest.approx((0, 1))


def test_oblique_projection_preserves_exact_affine_mapping() -> None:
    source = WorkPlaneFrame.xz()
    projection = plane_projection(source, WorkPlaneFrame.xy(), (0, -1, -1))
    assert projection.map_point((2, 3)) == pytest.approx((2, 3))
    assert projection.map_point((-4, -5)) == pytest.approx((-4, -5))


def test_projection_parallel_to_target_plane_is_rejected() -> None:
    with pytest.raises(ValueError, match="平行"):
        plane_projection(WorkPlaneFrame.xz(), WorkPlaneFrame.xy(), (1, 0, 0))


def test_nonfinite_projection_direction_is_rejected() -> None:
    with pytest.raises(ValueError, match="有限"):
        plane_projection(WorkPlaneFrame.xy(), WorkPlaneFrame.xy(), (0, 0, float("nan")))


def test_projected_circle_intersects_finite_line_exactly() -> None:
    import math

    from mycad.core.sketch_projection import (
        PlaneProjection,
        intersect_projected_arc_with_line,
        project_circular_arc,
    )

    projection = PlaneProjection((0, 0), (2, 0), (0, 1))
    arc = project_circular_arc(projection, (0, 0), 1, 0, 360)
    hits = intersect_projected_arc_with_line(arc, (-3, 0.5), (3, 0.5))
    assert len(hits) == 2
    assert hits[0] == pytest.approx((-math.sqrt(3), 0.5))
    assert hits[1] == pytest.approx((math.sqrt(3), 0.5))
    assert len(intersect_projected_arc_with_line(arc, (-3, 1), (3, 1))) == 1
    assert not intersect_projected_arc_with_line(arc, (0, 0.5), (1, 0.5))


def test_projected_arc_respects_signed_finite_sweep() -> None:
    from mycad.core.sketch_projection import (
        PlaneProjection,
        intersect_projected_arc_with_line,
        project_circular_arc,
    )

    projection = PlaneProjection((0, 0), (2, 0), (0, 1))
    arc = project_circular_arc(projection, (0, 0), 1, 0, -180)
    assert not intersect_projected_arc_with_line(arc, (-3, 0.5), (3, 0.5))
    assert len(intersect_projected_arc_with_line(arc, (-3, -0.5), (3, -0.5))) == 2


def test_edge_on_circle_projection_handles_point_and_overlapping_hits() -> None:
    from mycad.core.sketch_projection import (
        PlaneProjection,
        intersect_projected_arc_with_line,
        project_circular_arc,
    )

    arc = project_circular_arc(PlaneProjection((0, 0), (1, 0), (0, 0)), (0, 0), 1, 0, 360)
    hits = intersect_projected_arc_with_line(arc, (0.5, -1), (0.5, 1))
    assert len(hits) == 1 and hits[0] == pytest.approx((0.5, 0))
    assert not intersect_projected_arc_with_line(arc, (2, -1), (2, 1))
    with pytest.raises(ValueError, match="重合"):
        intersect_projected_arc_with_line(arc, (-2, 0), (2, 0))


def test_projected_arc_can_intersect_target_support_line_for_extend() -> None:
    from mycad.core.sketch_projection import (
        PlaneProjection,
        intersect_projected_arc_with_line,
        project_circular_arc,
    )

    arc = project_circular_arc(PlaneProjection((0, 0), (2, 0), (0, 1)), (0, 0), 1, 0, 360)
    start, end = (3.0, 0.0), (4.0, 0.0)
    assert not intersect_projected_arc_with_line(arc, start, end)
    hits = intersect_projected_arc_with_line(arc, start, end, extend_line=True)
    assert len(hits) == 2
    assert hits[0] == pytest.approx((-2, 0), abs=1e-9)
    assert hits[1] == pytest.approx((2, 0), abs=1e-9)


def test_spatial_segments_intersect_only_when_they_really_meet() -> None:
    from mycad.core.sketch_projection import intersect_spatial_segments

    first = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    assert intersect_spatial_segments(*first, (5, -2, 0), (5, 2, 0)) == pytest.approx((5, 0, 0))
    assert intersect_spatial_segments(*first, (5, -2, 1), (5, 2, 1)) is None
    assert intersect_spatial_segments(*first, (15, -2, 0), (15, 2, 0)) is None
    assert intersect_spatial_segments(*first, (10, -2, 0), (10, 2, 0)) == pytest.approx((10, 0, 0))


def test_spatial_overlapping_segments_are_rejected_as_ambiguous() -> None:
    from mycad.core.sketch_projection import intersect_spatial_segments

    with pytest.raises(ValueError, match="重合"):
        intersect_spatial_segments((0, 0, 0), (10, 0, 0), (5, 0, 0), (15, 0, 0))


def test_spatial_collinear_disjoint_and_touching_segments() -> None:
    from mycad.core.sketch_projection import intersect_spatial_segments

    first = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    assert intersect_spatial_segments(*first, (11, 0, 0), (12, 0, 0)) is None
    assert intersect_spatial_segments(*first, (12, 0, 0), (10, 0, 0)) == pytest.approx((10, 0, 0))
    assert intersect_spatial_segments(*first, (0, 1, 0), (10, 1, 0)) is None


def test_spatial_line_and_arc_intersect_in_3d_without_projection() -> None:
    from mycad.core.sketch_projection import intersect_spatial_line_arc

    frame = WorkPlaneFrame.xz()
    hits = intersect_spatial_line_arc((-10, 0, 0), (10, 0, 0), frame, (0, 0), 5, 0, 360)
    assert len(hits) == 2
    assert hits[0] == pytest.approx((-5, 0, 0))
    assert hits[1] == pytest.approx((5, 0, 0))
    hit = intersect_spatial_line_arc((5, -2, 0), (5, 2, 0), frame, (0, 0), 5, 0, 360)
    assert len(hit) == 1 and hit[0] == pytest.approx((5, 0, 0))
    assert not intersect_spatial_line_arc((5, -2, 1), (5, 2, 1), frame, (0, 0), 5, 0, 360)
    assert not intersect_spatial_line_arc((5, -2, 0), (5, 2, 0), frame, (0, 0), 5, 90, 180)


def test_spatial_intersections_reject_nonfinite_coordinates() -> None:
    from mycad.core.sketch_projection import intersect_spatial_line_arc, intersect_spatial_segments

    with pytest.raises(ValueError, match="有限"):
        intersect_spatial_segments((float("nan"), 0, 0), (1, 0, 0), (0, 0, 0), (0, 1, 0))
    with pytest.raises(ValueError, match="有限"):
        intersect_spatial_line_arc(
            (0, 0, 0), (float("inf"), 1, 0), WorkPlaneFrame.xy(), (0, 0), 1, 0, 360
        )


def test_projected_arc_edge_mode_extends_boundary_to_support_ellipse() -> None:
    from mycad.core.sketch_projection import (
        PlaneProjection,
        intersect_projected_arc_with_line,
        project_circular_arc,
    )

    arc = project_circular_arc(PlaneProjection((0, 0), (2, 0), (0, 1)), (0, 0), 1, 0, 90)
    start, end = (-3.0, -0.5), (3.0, -0.5)
    assert not intersect_projected_arc_with_line(arc, start, end)
    hits = intersect_projected_arc_with_line(arc, start, end, extend_arc=True)
    assert len(hits) == 2


def test_line_boundary_intersections_respect_projection_mode() -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity, LineEntity
    from mycad.core.sketch_projection import line_boundary_intersections

    target_frame = WorkPlaneFrame.xy()
    source_frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    line = LineEntity(uuid4().hex, (5, -2), (5, 2))
    circle = CircleEntity(uuid4().hex, (5, 0), 2)
    for boundary in (line, circle):
        assert not line_boundary_intersections(target, target_frame, boundary, source_frame, None)
    line_hits = line_boundary_intersections(target, target_frame, line, source_frame, (0, 0, -1))
    assert len(line_hits) == 1 and line_hits[0] == pytest.approx((5, 0))
    circle_hits = line_boundary_intersections(
        target, target_frame, circle, source_frame, (0, 0, -1)
    )
    assert len(circle_hits) == 2
    assert circle_hits[0] == pytest.approx((3, 0))
    assert circle_hits[1] == pytest.approx((7, 0))


def test_line_boundary_intersections_allow_edge_and_target_extension() -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_projection import line_boundary_intersections

    frame = WorkPlaneFrame.xy()
    target = LineEntity(uuid4().hex, (0, 0), (2, 0))
    boundary = LineEntity(uuid4().hex, (5, 2), (5, 3))
    assert not line_boundary_intersections(target, frame, boundary, frame, (0, 0, -1))
    hits = line_boundary_intersections(
        target, frame, boundary, frame, (0, 0, -1), extend_target=True, extend_boundary=True
    )
    assert len(hits) == 1 and hits[0] == pytest.approx((5, 0))


def test_projected_collinear_boundaries_reject_only_actual_overlap() -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_projection import line_boundary_intersections

    frame = WorkPlaneFrame.xy()
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    disjoint = LineEntity(uuid4().hex, (11, 0), (12, 0))
    touching = LineEntity(uuid4().hex, (12, 0), (10, 0))
    overlapping = LineEntity(uuid4().hex, (5, 0), (15, 0))
    assert not line_boundary_intersections(target, frame, disjoint, frame, (0, 0, -1))
    hits = line_boundary_intersections(target, frame, touching, frame, (0, 0, -1))
    assert len(hits) == 1 and hits[0] == pytest.approx((10, 0))
    with pytest.raises(ValueError, match="重合"):
        line_boundary_intersections(target, frame, overlapping, frame, (0, 0, -1))


def test_external_intersections_trim_and_extend_line_without_temporary_entities() -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_edit import extend_curve_at, trim_curve_at

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    trimmed = trim_curve_at(
        (line,),
        (8, 0),
        hit_tolerance_mm=0.1,
        target_entity_id=line.entity_id,
        extra_intersections_mm=((5, 0),),
    )
    assert len(trimmed) == 1 and isinstance(trimmed[0], LineEntity)
    assert trimmed[0].entity_id == line.entity_id and trimmed[0].end_mm == pytest.approx((5, 0))
    extended = extend_curve_at(
        (line,),
        (10, 0),
        hit_tolerance_mm=0.1,
        target_entity_id=line.entity_id,
        extra_intersections_mm=((15, 0), (20, 0)),
    )
    assert len(extended) == 1 and isinstance(extended[0], LineEntity)
    assert extended[0].entity_id == line.entity_id and extended[0].end_mm == pytest.approx((15, 0))


@pytest.mark.parametrize("bad", [(5.0, 0.01), (float("nan"), 0.0)])
def test_external_line_intersections_reject_invalid_points(bad: tuple[float, float]) -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_edit import trim_curve_at

    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    with pytest.raises(ValueError, match="外部交点"):
        trim_curve_at((line,), (8, 0), hit_tolerance_mm=0.1, extra_intersections_mm=(bad,))


def test_tilted_circle_projects_as_ellipse_into_target_sketch() -> None:
    import math
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity, LineEntity
    from mycad.core.sketch_projection import line_boundary_intersections

    root = math.sqrt(0.5)
    tilted = WorkPlaneFrame(
        origin_mm=(0, 0, 2), u_axis=(1, 0, 0), v_axis=(0, root, root), normal=(0, -root, root)
    )
    target = LineEntity(uuid4().hex, (0, -4), (0, 4))
    circle = CircleEntity(uuid4().hex, (0, 0), 2)
    hits = line_boundary_intersections(target, WorkPlaneFrame.xy(), circle, tilted, (0, 0, -1))
    assert len(hits) == 2
    assert hits[0] == pytest.approx((0, -math.sqrt(2)))
    assert hits[1] == pytest.approx((0, math.sqrt(2)))


def test_spatial_boundary_bridge_trims_and_extends_without_mutating_source() -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity, LineEntity
    from mycad.core.sketch_projection import SpatialBoundary, edit_curve_with_spatial_boundaries

    target_frame = WorkPlaneFrame.xy()
    source_frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    source = CircleEntity(uuid4().hex, (5, 0), 2)
    boundary = SpatialBoundary(uuid4().hex, source_frame, source)
    result = edit_curve_with_spatial_boundaries(
        (target,),
        target.entity_id,
        (8, 0),
        target_frame,
        (boundary,),
        (0, 0, -1),
        operation="trim",
        hit_tolerance_mm=0.1,
    )
    assert len(result) == 1 and isinstance(result[0], LineEntity)
    assert result[0].end_mm == pytest.approx((7, 0))
    assert boundary.entity is source and source.center_mm == (5, 0)
    extension_source = LineEntity(uuid4().hex, (15, -5), (15, 5))
    extended = edit_curve_with_spatial_boundaries(
        (target,),
        target.entity_id,
        (10, 0),
        target_frame,
        (SpatialBoundary(uuid4().hex, source_frame, extension_source),),
        (0, 0, -1),
        operation="extend",
        hit_tolerance_mm=0.1,
    )
    assert len(extended) == 1 and isinstance(extended[0], LineEntity)
    assert extended[0].end_mm == pytest.approx((15, 0))


def test_spatial_boundary_bridge_rejects_duplicate_identity() -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_projection import SpatialBoundary, edit_curve_with_spatial_boundaries

    frame = WorkPlaneFrame.xy()
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    duplicate = LineEntity(target.entity_id, (5, -2), (5, 2))
    with pytest.raises(ValueError, match="身份不唯一"):
        edit_curve_with_spatial_boundaries(
            (target,),
            target.entity_id,
            (8, 0),
            frame,
            (SpatialBoundary(uuid4().hex, frame, duplicate),),
            (0, 0, -1),
            operation="trim",
            hit_tolerance_mm=0.1,
        )


def test_spatial_boundary_bridge_does_not_use_construction_geometry() -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_edit import NoTrimIntersection
    from mycad.core.sketch_projection import SpatialBoundary, edit_curve_with_spatial_boundaries

    frame = WorkPlaneFrame.xy()
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    source = LineEntity(uuid4().hex, (5, -2), (5, 2), construction=True)
    with pytest.raises(NoTrimIntersection):
        edit_curve_with_spatial_boundaries(
            (target,),
            target.entity_id,
            (8, 0),
            frame,
            (SpatialBoundary(uuid4().hex, frame, source),),
            (0, 0, -1),
            operation="trim",
            hit_tolerance_mm=0.1,
        )


def test_spatial_boundary_bridge_distinguishes_real_and_projected_intersections() -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_edit import NoTrimIntersection
    from mycad.core.sketch_projection import SpatialBoundary, edit_curve_with_spatial_boundaries

    target_frame = WorkPlaneFrame.xy()
    source_frame = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    source = LineEntity(uuid4().hex, (5, -1), (5, 1))
    boundaries = (SpatialBoundary(uuid4().hex, source_frame, source),)
    with pytest.raises(NoTrimIntersection):
        edit_curve_with_spatial_boundaries(
            (target,),
            target.entity_id,
            (8, 0),
            target_frame,
            boundaries,
            None,
            operation="trim",
            hit_tolerance_mm=0.1,
        )
    result = edit_curve_with_spatial_boundaries(
        (target,),
        target.entity_id,
        (8, 0),
        target_frame,
        boundaries,
        (0, 0, -1),
        operation="trim",
        hit_tolerance_mm=0.1,
    )
    assert len(result) == 1 and isinstance(result[0], LineEntity)
    assert result[0].end_mm == pytest.approx((5, 0))


def test_perpendicular_line_projects_to_valid_point_boundary() -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_projection import line_boundary_intersections

    target = LineEntity(uuid4().hex, (0, 0), (10, 0))
    boundary = LineEntity(uuid4().hex, (5, -2), (5, 2))
    target_frame, boundary_frame = WorkPlaneFrame.xy(), WorkPlaneFrame.xz()
    hits = line_boundary_intersections(target, target_frame, boundary, boundary_frame, (0, 0, -1))
    assert len(hits) == 1 and hits[0] == pytest.approx((5, 0))
    real_hits = line_boundary_intersections(target, target_frame, boundary, boundary_frame, None)
    assert len(real_hits) == 1 and real_hits[0] == pytest.approx((5, 0))


def test_edge_on_arc_collinear_disjoint_touch_and_overlap() -> None:
    from mycad.core.sketch_projection import (
        PlaneProjection,
        intersect_projected_arc_with_line,
        project_circular_arc,
    )

    arc = project_circular_arc(PlaneProjection((0, 0), (1, 0), (0, 0)), (0, 0), 1, 0, 90)
    assert not intersect_projected_arc_with_line(arc, (2, 0), (3, 0))
    hits = intersect_projected_arc_with_line(arc, (1, 0), (2, 0))
    assert len(hits) == 1 and hits[0] == pytest.approx((1, 0))
    with pytest.raises(ValueError, match="重合"):
        intersect_projected_arc_with_line(arc, (0.5, 0), (2, 0))


def test_line_boundaries_support_curved_polyline_and_rectangle() -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, PolylineEntity, RectangleEntity
    from mycad.core.sketch_projection import line_boundary_intersections

    frame = WorkPlaneFrame.xy()
    target = LineEntity(uuid4().hex, (-10, 3), (10, 3))
    arc_path = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), bulges=(-1,))
    hits = line_boundary_intersections(target, frame, arc_path, frame, (0, 0, -1))
    assert len(hits) == 2
    assert hits[0] == pytest.approx((-4, 3))
    assert hits[1] == pytest.approx((4, 3))
    rectangle = RectangleEntity(uuid4().hex, (-2, 0), (2, 6))
    hits = line_boundary_intersections(target, frame, rectangle, frame, (0, 0, -1))
    assert len(hits) == 2
    assert hits[0] == pytest.approx((-2, 3))
    assert hits[1] == pytest.approx((2, 3))


def test_projected_arc_intersection_rejects_nonfinite_line() -> None:
    from mycad.core.sketch_projection import (
        PlaneProjection,
        intersect_projected_arc_with_line,
        project_circular_arc,
    )

    arc = project_circular_arc(PlaneProjection((0, 0), (1, 0), (0, 1)), (0, 0), 1, 0, 360)
    with pytest.raises(ValueError, match="有限"):
        intersect_projected_arc_with_line(arc, (float("nan"), 0), (2, 0))


def test_projected_ellipse_circle_intersection_finds_four_points_and_tangencies() -> None:
    import math

    from mycad.core.sketch_projection import (
        PlaneProjection,
        intersect_projected_arc_with_circle,
        project_circular_arc,
    )

    ellipse = project_circular_arc(PlaneProjection((0, 0), (2, 0), (0, 1)), (0, 0), 1, 0, 360)
    hits = intersect_projected_arc_with_circle(ellipse, (0, 0), math.sqrt(2.5))
    assert len(hits) == 4
    for hit in hits:
        assert abs(hit[0]) == pytest.approx(math.sqrt(2))
        assert abs(hit[1]) == pytest.approx(math.sqrt(0.5))
    tangencies = intersect_projected_arc_with_circle(ellipse, (0, 0), 2)
    assert len(tangencies) == 2
    assert any(point == pytest.approx((2, 0)) for point in tangencies)
    assert any(point == pytest.approx((-2, 0)) for point in tangencies)
    assert not intersect_projected_arc_with_circle(ellipse, (0, 0), 3)


def test_projected_arc_circle_intersections_respect_both_sweeps() -> None:
    from mycad.core.sketch_projection import (
        PlaneProjection,
        intersect_projected_arc_with_circle,
        project_circular_arc,
    )

    arc = project_circular_arc(PlaneProjection((0, 0), (2, 0), (0, 1)), (0, 0), 1, 0, 180)
    hits = intersect_projected_arc_with_circle(
        arc, (0, 0), 2**0.5, start_angle_deg=0, sweep_angle_deg=180
    )
    assert len(hits) == 2 and all(point[1] > 0 for point in hits)
    assert not intersect_projected_arc_with_circle(
        arc, (0, 0), 2**0.5, start_angle_deg=180, sweep_angle_deg=180
    )


def test_coincident_projected_circle_intersection_is_ambiguous() -> None:
    from mycad.core.sketch_projection import (
        PlaneProjection,
        intersect_projected_arc_with_circle,
        project_circular_arc,
    )

    circle = project_circular_arc(PlaneProjection((0, 0), (1, 0), (0, 1)), (0, 0), 2, 0, 360)
    with pytest.raises(ValueError, match="重合"):
        intersect_projected_arc_with_circle(circle, (0, 0), 2)


def test_projected_ellipse_circle_tangency_at_oblique_angle() -> None:
    import math

    from mycad.core.sketch_projection import (
        PlaneProjection,
        intersect_projected_arc_with_circle,
        project_circular_arc,
    )

    theta = math.radians(37)
    point = (2 * math.cos(theta), math.sin(theta))
    normal = (math.cos(theta) / 2, math.sin(theta))
    length = math.hypot(*normal)
    center = (point[0] + 0.5 * normal[0] / length, point[1] + 0.5 * normal[1] / length)
    ellipse = project_circular_arc(PlaneProjection((0, 0), (2, 0), (0, 1)), (0, 0), 1, 0, 360)
    hits = intersect_projected_arc_with_circle(ellipse, center, 0.5)
    assert len(hits) == 1 and hits[0] == pytest.approx(point, abs=1e-7)


def test_projected_ellipse_circle_near_tangency_keeps_two_distinct_hits() -> None:
    import math

    from mycad.core.sketch_projection import (
        PlaneProjection,
        intersect_projected_arc_with_circle,
        project_circular_arc,
    )

    theta = math.radians(37)
    point = (2 * math.cos(theta), math.sin(theta))
    normal = (math.cos(theta) / 2, math.sin(theta))
    length = math.hypot(*normal)
    center = (point[0] + 0.5 * normal[0] / length, point[1] + 0.5 * normal[1] / length)
    ellipse = project_circular_arc(PlaneProjection((0, 0), (2, 0), (0, 1)), (0, 0), 1, 0, 360)
    hits = intersect_projected_arc_with_circle(ellipse, center, 0.500001)
    assert len(hits) == 2
    assert math.dist(*hits) > 1e-4


def test_rotated_coincident_projected_circle_is_ambiguous() -> None:
    import math

    from mycad.core.sketch_projection import (
        PlaneProjection,
        intersect_projected_arc_with_circle,
        project_circular_arc,
    )

    root = math.sqrt(0.5)
    projection = PlaneProjection((0, 0), (root, root), (-root, root))
    circle = project_circular_arc(projection, (0, 0), 2, 0, 360)
    with pytest.raises(ValueError, match="重合"):
        intersect_projected_arc_with_circle(circle, (0, 0), 2)


def test_circular_boundary_intersections_in_three_dimensions() -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_projection import circular_boundary_intersections

    target = CircleEntity(uuid4().hex, (0, 0), 5)
    boundary = CircleEntity(uuid4().hex, (0, 0), 5)
    hits = circular_boundary_intersections(
        target, WorkPlaneFrame.xy(), boundary, WorkPlaneFrame.xz(), None
    )
    assert len(hits) == 2
    assert any(point == pytest.approx((5, 0)) for point in hits)
    assert any(point == pytest.approx((-5, 0)) for point in hits)
    lifted = WorkPlaneFrame(
        origin_mm=(0, 0, 10), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    assert not circular_boundary_intersections(target, WorkPlaneFrame.xy(), boundary, lifted, None)


def test_projected_circular_boundary_finds_all_ellipse_circle_crossings() -> None:
    import math
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_projection import circular_boundary_intersections

    root = math.sqrt(0.5)
    tilted = WorkPlaneFrame(
        origin_mm=(0, 0, 2), u_axis=(1, 0, 0), v_axis=(0, root, root), normal=(0, -root, root)
    )
    target = CircleEntity(uuid4().hex, (0, 0), math.sqrt(3))
    boundary = CircleEntity(uuid4().hex, (0, 0), 2)
    hits = circular_boundary_intersections(
        target, WorkPlaneFrame.xy(), boundary, tilted, (0, 0, -1)
    )
    assert len(hits) == 4
    for point in hits:
        assert abs(point[0]) == pytest.approx(math.sqrt(2))
        assert abs(point[1]) == pytest.approx(1)


def test_spatial_circle_intersections_with_translated_planes() -> None:
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_projection import circular_boundary_intersections

    target_frame = WorkPlaneFrame(
        origin_mm=(0, 0, 3), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    source_frame = WorkPlaneFrame(
        origin_mm=(0, 2, 0), u_axis=(1, 0, 0), v_axis=(0, 0, -1), normal=(0, 1, 0)
    )
    target = CircleEntity(uuid4().hex, (0, 2), 5)
    boundary = CircleEntity(uuid4().hex, (0, -3), 5)
    hits = circular_boundary_intersections(target, target_frame, boundary, source_frame, None)
    assert len(hits) == 2
    assert any(point == pytest.approx((5, 2)) for point in hits)
    assert any(point == pytest.approx((-5, 2)) for point in hits)


def test_external_intersections_trim_circle_and_extend_arc() -> None:
    from uuid import uuid4

    from mycad.core.sketch import ArcEntity, CircleEntity
    from mycad.core.sketch_edit import extend_curve_at, trim_curve_at

    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    trimmed = trim_curve_at(
        (circle,),
        (5, 0),
        hit_tolerance_mm=0.1,
        target_entity_id=circle.entity_id,
        extra_intersections_mm=((0, -5), (0, 5)),
    )
    assert len(trimmed) == 1 and isinstance(trimmed[0], ArcEntity)
    assert trimmed[0].entity_id == circle.entity_id
    assert trimmed[0].start_angle_deg == pytest.approx(90)
    assert trimmed[0].sweep_angle_deg == pytest.approx(180)
    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, 90)
    extended = extend_curve_at(
        (arc,),
        (0, 5),
        hit_tolerance_mm=0.1,
        target_entity_id=arc.entity_id,
        extra_intersections_mm=((-5, 0),),
    )
    assert len(extended) == 1 and isinstance(extended[0], ArcEntity)
    assert extended[0].entity_id == arc.entity_id and extended[0].sweep_angle_deg == pytest.approx(
        180
    )


def test_spatial_boundary_bridge_trims_circle_and_extends_arc() -> None:
    from uuid import uuid4

    from mycad.core.sketch import ArcEntity, CircleEntity, LineEntity
    from mycad.core.sketch_projection import SpatialBoundary, edit_curve_with_spatial_boundaries

    frame = WorkPlaneFrame.xy()
    lifted = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    cutter = CircleEntity(uuid4().hex, (4, 0), 5)
    boundary = SpatialBoundary(uuid4().hex, lifted, cutter)
    result = edit_curve_with_spatial_boundaries(
        (circle,),
        circle.entity_id,
        (5, 0),
        frame,
        (boundary,),
        (0, 0, -1),
        operation="trim",
        hit_tolerance_mm=0.1,
    )
    assert len(result) == 1 and isinstance(result[0], ArcEntity)
    assert result[0].entity_id == circle.entity_id and result[0].sweep_angle_deg > 180
    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, 90)
    line = LineEntity(uuid4().hex, (-5, -3), (-5, 3))
    extended = edit_curve_with_spatial_boundaries(
        (arc,),
        arc.entity_id,
        (0, 5),
        frame,
        (SpatialBoundary(uuid4().hex, lifted, line),),
        (0, 0, -1),
        operation="extend",
        hit_tolerance_mm=0.1,
    )
    assert len(extended) == 1 and isinstance(extended[0], ArcEntity)
    assert extended[0].sweep_angle_deg == pytest.approx(180)


def test_spatial_boundary_bridge_trims_and_extends_open_polyline() -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.core.sketch_projection import SpatialBoundary, edit_curve_with_spatial_boundaries

    frame = WorkPlaneFrame.xy()
    lifted = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    target = PolylineEntity(uuid4().hex, ((0, 0), (10, 0)))
    cutter = LineEntity(uuid4().hex, (5, -2), (5, 2))
    boundary = SpatialBoundary(uuid4().hex, lifted, cutter)
    result = edit_curve_with_spatial_boundaries(
        (target,),
        target.entity_id,
        (8, 0),
        frame,
        (boundary,),
        (0, 0, -1),
        operation="trim",
        hit_tolerance_mm=0.1,
    )
    assert len(result) == 1 and isinstance(result[0], PolylineEntity)
    assert result[0].entity_id == target.entity_id
    assert result[0].points_mm[-1] == pytest.approx((5, 0))
    source = LineEntity(uuid4().hex, (15, -2), (15, 2))
    result = edit_curve_with_spatial_boundaries(
        (target,),
        target.entity_id,
        (10, 0),
        frame,
        (SpatialBoundary(uuid4().hex, lifted, source),),
        (0, 0, -1),
        operation="extend",
        hit_tolerance_mm=0.1,
    )
    assert len(result) == 1 and isinstance(result[0], PolylineEntity)
    assert result[0].points_mm[-1] == pytest.approx((15, 0))


def test_spatial_boundary_bridge_trims_and_extends_curved_open_polyline() -> None:
    import math
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.core.sketch_projection import SpatialBoundary, edit_curve_with_spatial_boundaries

    frame = WorkPlaneFrame.xy()
    lifted = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    target = PolylineEntity(uuid4().hex, ((-5, 0), (5, 0)), bulges=(-1,))
    cutter = LineEntity(uuid4().hex, (0, 3), (0, 7))
    result = edit_curve_with_spatial_boundaries(
        (target,),
        target.entity_id,
        (4, 3),
        frame,
        (SpatialBoundary(uuid4().hex, lifted, cutter),),
        (0, 0, -1),
        operation="trim",
        hit_tolerance_mm=0.1,
    )
    assert len(result) == 1 and isinstance(result[0], PolylineEntity)
    assert result[0].points_mm[-1] == pytest.approx((0, 5))
    assert result[0].bulges == pytest.approx((-math.tan(math.pi / 8),))
    arc_path = PolylineEntity(uuid4().hex, ((5, 0), (0, 5)), bulges=(math.tan(math.pi / 8),))
    boundary = LineEntity(uuid4().hex, (-5, -3), (-5, 3))
    extended = edit_curve_with_spatial_boundaries(
        (arc_path,),
        arc_path.entity_id,
        (0, 5),
        frame,
        (SpatialBoundary(uuid4().hex, lifted, boundary),),
        (0, 0, -1),
        operation="extend",
        hit_tolerance_mm=0.1,
    )
    assert len(extended) == 1 and isinstance(extended[0], PolylineEntity)
    assert extended[0].points_mm[-1] == pytest.approx((-5, 0), abs=1e-8)
    assert extended[0].bulges == pytest.approx((1,))


def test_spatial_boundary_bridge_trims_closed_rectangle() -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, PolylineEntity, RectangleEntity
    from mycad.core.sketch_projection import SpatialBoundary, edit_curve_with_spatial_boundaries

    frame = WorkPlaneFrame.xy()
    lifted = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    target = RectangleEntity(uuid4().hex, (0, 0), (10, 10))
    cutter = LineEntity(uuid4().hex, (5, -5), (5, 15))
    result = edit_curve_with_spatial_boundaries(
        (target,),
        target.entity_id,
        (10, 5),
        frame,
        (SpatialBoundary(uuid4().hex, lifted, cutter),),
        (0, 0, -1),
        operation="trim",
        hit_tolerance_mm=0.1,
    )
    assert len(result) == 1 and isinstance(result[0], PolylineEntity)
    assert result[0].entity_id == target.entity_id and not result[0].closed
    assert result[0].points_mm[0] == pytest.approx((5, 10))
    assert result[0].points_mm[-1] == pytest.approx((5, 0))


def test_spatial_boundary_bridge_trims_closed_curved_polyline() -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity, PolylineEntity
    from mycad.core.sketch_projection import SpatialBoundary, edit_curve_with_spatial_boundaries

    frame = WorkPlaneFrame.xy()
    lifted = WorkPlaneFrame(
        origin_mm=(0, 0, 5), u_axis=(1, 0, 0), v_axis=(0, 1, 0), normal=(0, 0, 1)
    )
    target = PolylineEntity(
        uuid4().hex, ((-5, 0), (5, 0), (5, 10), (-5, 10)), True, bulges=(0, 1, 0, 1)
    )
    cutter = LineEntity(uuid4().hex, (0, -2), (0, 12))
    result = edit_curve_with_spatial_boundaries(
        (target,),
        target.entity_id,
        (10, 5),
        frame,
        (SpatialBoundary(uuid4().hex, lifted, cutter),),
        (0, 0, -1),
        operation="trim",
        hit_tolerance_mm=0.1,
    )
    assert len(result) == 1 and isinstance(result[0], PolylineEntity)
    assert result[0].entity_id == target.entity_id and not result[0].closed
    assert result[0].points_mm[0] == pytest.approx((0, 10))
    assert result[0].points_mm[-1] == pytest.approx((0, 0))
    assert result[0].bulges == pytest.approx((0, 1, 0))


def test_projected_ellipse_window_selection_uses_exact_extrema() -> None:
    import math
    from uuid import uuid4

    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_projection import SpatialBoundary, projected_boundary_in_box

    angle = math.radians(7)
    c, s, root = math.cos(angle), math.sin(angle), math.sqrt(0.5)
    frame = WorkPlaneFrame(
        origin_mm=(0, 0, 2),
        u_axis=(c, s, 0),
        v_axis=(-s * root, c * root, root),
        normal=(s * root, -c * root, root),
    )
    source = SpatialBoundary(uuid4().hex, frame, CircleEntity(uuid4().hex, (0, 0), 5))
    x_max = 5 * math.hypot(c, s * root)
    assert not projected_boundary_in_box(
        source, WorkPlaneFrame.xy(), (-x_max + 1e-5, -10), (x_max - 1e-5, 10), crossing=False
    )
    assert projected_boundary_in_box(
        source, WorkPlaneFrame.xy(), (-x_max - 1e-5, -10), (x_max + 1e-5, 10), crossing=False
    )
    assert projected_boundary_in_box(
        source, WorkPlaneFrame.xy(), (x_max - 0.01, -1), (x_max + 0.01, 1), crossing=True
    )


def test_projected_boundary_crossing_selection_handles_overlap_and_disjoint() -> None:
    from uuid import uuid4

    from mycad.core.sketch import LineEntity
    from mycad.core.sketch_projection import SpatialBoundary, projected_boundary_in_box

    frame = WorkPlaneFrame.xy()
    source = SpatialBoundary(uuid4().hex, frame, LineEntity(uuid4().hex, (-5, 0), (5, 0)))
    assert projected_boundary_in_box(source, frame, (-1, 0), (1, 2), crossing=True)
    assert not projected_boundary_in_box(source, frame, (-1, 1), (1, 2), crossing=True)
    assert not projected_boundary_in_box(source, frame, (-1, -1), (1, 1), crossing=False)
    assert projected_boundary_in_box(source, frame, (-6, -1), (6, 1), crossing=False)


@pytest.mark.parametrize("bad", [(5.0, 0.1), (float("nan"), 0.0)])
def test_external_polyline_hits_reject_invalid_points(bad: tuple[float, float]) -> None:
    from uuid import uuid4

    from mycad.core.sketch import PolylineEntity
    from mycad.core.sketch_edit import trim_curve_at

    target = PolylineEntity(uuid4().hex, ((0, 0), (10, 0)))
    with pytest.raises(ValueError, match="外部交点"):
        trim_curve_at((target,), (8, 0), hit_tolerance_mm=0.1, extra_intersections_mm=(bad,))
