# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Coplanar display projections retain the source's identities and segments."""

from uuid import uuid4

import pytest

from mycad.core.cross_sketch_tangency import project_coplanar_entity
from mycad.core.sketch import (
    ArcEntity,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    SplineEntity,
    WorkPlaneFrame,
)


@pytest.mark.parametrize("opposite", [False, True])
def test_project_rectangle_preserves_directed_sides(opposite: bool) -> None:
    source = WorkPlaneFrame(
        (5, 7, 0),
        (-1, 0, 0) if opposite else (0, 1, 0),
        (0, 1, 0) if opposite else (-1, 0, 0),
        (0, 0, -1) if opposite else (0, 0, 1),
    )
    target = WorkPlaneFrame.xy()
    rect = RectangleEntity(uuid4().hex, (1, 2), (4, 5), layer_name="A")
    projected = project_coplanar_entity(rect, source, target)
    assert isinstance(projected, PolylineEntity)
    assert projected.entity_id == rect.entity_id and projected.layer_name == "A"
    assert projected.closed
    for point, original in zip(projected.points_mm, ((1, 2), (4, 2), (4, 5), (1, 5)), strict=True):
        assert target.local_to_world(point) == pytest.approx(source.local_to_world(original))


def test_projection_preserves_reflected_curves_and_control_points() -> None:
    source = WorkPlaneFrame((0, 0, 0), (-1, 0, 0), (0, 1, 0), (0, 0, -1))
    target = WorkPlaneFrame.xy()
    arc = ArcEntity(uuid4().hex, (2, 3), 2, 30, 90)
    path = PolylineEntity(uuid4().hex, ((0, 0), (2, 0)), bulges=(0.5,))
    spline = SplineEntity(uuid4().hex, ((0, 0), (1, 2), (2, 3), (4, 0)))
    point = PointEntity(uuid4().hex, (1, 3))
    result_arc = project_coplanar_entity(arc, source, target)
    result_path = project_coplanar_entity(path, source, target)
    result_spline = project_coplanar_entity(spline, source, target)
    result_point = project_coplanar_entity(point, source, target)
    assert isinstance(result_arc, ArcEntity) and result_arc.sweep_angle_deg == -90
    assert result_arc.start_angle_deg == pytest.approx(150)
    assert isinstance(result_path, PolylineEntity) and result_path.bulges == (-0.5,)
    assert isinstance(result_spline, SplineEntity)
    assert result_spline.control_points_mm == ((0, 0), (-1, 2), (-2, 3), (-4, 0))
    assert isinstance(result_point, PointEntity) and result_point.position_mm == (-1, 3)


def test_projection_rejects_non_coplanar_sources() -> None:
    with pytest.raises(ValueError, match="共面"):
        project_coplanar_entity(
            PointEntity(uuid4().hex, (0, 0)), WorkPlaneFrame.xz(), WorkPlaneFrame.xy()
        )


def test_aligned_rectangle_projection_preserves_type_and_corners() -> None:
    source = WorkPlaneFrame((5, 7, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    rect = RectangleEntity(uuid4().hex, (1, 2), (4, 5))
    projected = project_coplanar_entity(rect, source, WorkPlaneFrame.xy())
    assert isinstance(projected, RectangleEntity)
    assert projected.first_corner_mm == (6, 9)
    assert projected.opposite_corner_mm == (9, 12)
    arc = ArcEntity(uuid4().hex, (1, 2), 2, 270, 90)
    projected_arc = project_coplanar_entity(arc, source, WorkPlaneFrame.xy())
    assert isinstance(projected_arc, ArcEntity)
    assert projected_arc.start_angle_deg == 270
