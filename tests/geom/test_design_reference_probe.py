# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""E1 experiments: real native lineage, not persisted command identity."""

from __future__ import annotations

import math

import pytest
from build123d import Box, CenterOf, Cylinder, GeomType, Part, Plane, Pos

from mycad.core.exceptions import TopologyReferenceError
from tests.geom.design_reference_probe import advance_face, bind_top_face, local_point_on_face


@pytest.mark.parametrize("radius", [None, 10.0])
def test_two_cuts_follow_the_actual_previous_result(radius: float | None) -> None:
    base = Box(20, 20, 4) if radius is None else Cylinder(radius, 4)
    face = bind_top_face(base)
    first, first_face = advance_face(base, face, Pos(4, 0, 0) * Cylinder(1, 8))
    second, second_face = advance_face(first, first_face, Pos(-4, 0, 0) * Cylinder(1, 8))
    expected_area = 400.0 if radius is None else 100.0 * math.pi
    assert first_face.area == pytest.approx(expected_area - math.pi)
    assert second_face.area == pytest.approx(expected_area - 2 * math.pi)
    assert pytest.approx(2) == second_face.center().Z
    assert pytest.approx(1) == second_face.normal_at().Z
    assert second.volume == pytest.approx(4 * (expected_area - 2 * math.pi))
    assert base.volume == pytest.approx(4 * expected_area)


def test_identical_looking_face_from_another_shape_is_not_a_binding() -> None:
    base = Box(20, 20, 4)
    foreign_face = bind_top_face(Box(20, 20, 4))
    with pytest.raises(TopologyReferenceError) as error:
        advance_face(base, foreign_face, Cylinder(1, 8))
    assert error.value.reason == "wrong-source"
    assert error.value.parameter_path == "target_face"


@pytest.mark.parametrize(
    ("operation", "tool", "reason"),
    [
        ("cut", Box(4, 24, 6), "split"),
        ("cut", Box(30, 30, 6), "deleted"),
        ("fuse", Pos(20, 0, 0) * Box(20, 20, 4), "merged"),
    ],
)
def test_uncertain_evolution_rejects_without_changing_input(
    operation: str, tool: Part, reason: str
) -> None:
    from mycad.geom.topology_evolution import BooleanKind

    assert operation in ("cut", "fuse")
    kind: BooleanKind = "cut" if operation == "cut" else "fuse"
    base = Box(20, 20, 4)
    face = bind_top_face(base)
    with pytest.raises(TopologyReferenceError) as error:
        advance_face(base, face, tool, kind)
    assert error.value.reason == reason
    assert base.volume == pytest.approx(1600)
    assert face.area == pytest.approx(400)


def test_asymmetric_trim_moves_centroid_but_not_local_hole_point() -> None:
    base = Box(20, 20, 4)
    trimmed, top = advance_face(base, bind_top_face(base), Pos(9, 0, 0) * Box(4, 24, 8))
    assert pytest.approx(-1.5) == top.center(CenterOf.MASS).X
    frame = Plane(origin=(0, 0, 2), x_dir=(1, 0, 0), z_dir=(0, 0, 1))
    point = local_point_on_face(top, frame, (-4, 3))
    assert point == pytest.approx((-4, 3, 2))
    drilled, _ = advance_face(trimmed, top, Pos(point[0], point[1], 0) * Cylinder(1, 8))
    holes = [face for face in drilled.faces() if face.geom_type == GeomType.CYLINDER]
    assert len(holes) == 1
    assert holes[0].radius == pytest.approx(1)
    assert pytest.approx(-4, abs=1e-6) == holes[0].center(CenterOf.MASS).X
    assert pytest.approx(3, abs=1e-6) == holes[0].center(CenterOf.MASS).Y
    assert drilled.volume == pytest.approx(1360 - 4 * math.pi)


@pytest.mark.parametrize("height", [4.0, 8.0])
def test_rebuild_uses_new_source_frame_instead_of_old_world_point(height: float) -> None:
    base = Box(20, 20, height)
    frame = Plane(origin=(0, 0, height / 2), x_dir=(1, 0, 0), z_dir=(0, 0, 1))
    top = bind_top_face(base)
    point = local_point_on_face(top, frame, (-4, 3))
    assert point == pytest.approx((-4, 3, height / 2))
    drilled, _top = advance_face(base, top, Pos(point[0], point[1], 0) * Cylinder(1, height + 2))
    walls = [face for face in drilled.faces() if face.geom_type == GeomType.CYLINDER]
    assert len(walls) == 1
    center = walls[0].center(CenterOf.MASS)
    bounds = walls[0].bounding_box()
    assert pytest.approx((-4, 3, 0)) == (center.X, center.Y, center.Z)
    assert walls[0].radius == pytest.approx(1)
    assert pytest.approx((-height / 2, height / 2)) == (bounds.min.Z, bounds.max.Z)
    assert drilled.volume == pytest.approx(height * (400 - math.pi))


@pytest.mark.parametrize("uv", [(20.0, 0.0), (math.nan, 0.0), (0.0, math.inf)])
def test_invalid_or_outside_local_point_is_rejected(uv: tuple[float, float]) -> None:
    face = bind_top_face(Box(20, 20, 4))
    with pytest.raises(TopologyReferenceError):
        local_point_on_face(face, Plane(origin=(0, 0, 2)), uv)


def test_old_height_frame_is_not_silently_projected_to_new_face() -> None:
    with pytest.raises(TopologyReferenceError):
        local_point_on_face(bind_top_face(Box(20, 20, 8)), Plane(origin=(0, 0, 2)), (0, 0))


@pytest.mark.parametrize("left_radius", [10.0, 5.0, 8.0])
def test_size_reversal_does_not_switch_the_selected_source_body(left_radius: float) -> None:
    left = Pos(-20, 0, 0) * Cylinder(left_radius, 4)
    right = Pos(20, 0, 0) * Cylinder(8, 4)
    combined = Part([*left.solids(), *right.solids()])
    selected = bind_top_face(left)
    result, successor = advance_face(combined, selected, Pos(-20, 0, 0) * Cylinder(1, 8))
    assert successor.area == pytest.approx(math.pi * (left_radius**2 - 1))
    assert pytest.approx(-20) == successor.center(CenterOf.MASS).X
    assert len(result.solids()) == 2
    assert result.volume == pytest.approx(4 * math.pi * (left_radius**2 + 64 - 1))
    walls = [
        face
        for face in result.faces()
        if face.geom_type == GeomType.CYLINDER
        and face.radius is not None
        and abs(face.radius - 1) < 1e-7
    ]
    assert len(walls) == 1
    center = walls[0].center(CenterOf.MASS)
    bounds = walls[0].bounding_box()
    assert pytest.approx((-20, 0, 0)) == (center.X, center.Y, center.Z)
    assert pytest.approx((-2, 2)) == (bounds.min.Z, bounds.max.Z)


def test_removed_local_region_is_not_accepted_as_a_hole_location() -> None:
    base = Box(20, 20, 4)
    _result, top = advance_face(base, bind_top_face(base), Cylinder(2, 8))
    with pytest.raises(TopologyReferenceError) as error:
        local_point_on_face(top, Plane(origin=(0, 0, 2)), (0, 0))
    assert error.value.reason == "outside-face"


def test_local_blind_hole_preserves_center_direction_and_depth() -> None:
    base = Box(20, 20, 6)
    top = bind_top_face(base)
    point = local_point_on_face(top, Plane(origin=(0, 0, 3)), (4, -3))
    result, successor = advance_face(base, top, Pos(point[0], point[1], 2) * Cylinder(1, 2))
    walls = [face for face in result.faces() if face.geom_type == GeomType.CYLINDER]
    assert len(walls) == 1
    wall = walls[0]
    center = wall.center(CenterOf.MASS)
    assert pytest.approx((4, -3, 2)) == (center.X, center.Y, center.Z)
    bounds = wall.bounding_box()
    assert pytest.approx((1, 3)) == (bounds.min.Z, bounds.max.Z)
    assert wall.area == pytest.approx(4 * math.pi)
    assert result.volume == pytest.approx(2400 - 2 * math.pi)
    assert pytest.approx(1) == successor.normal_at().Z


def test_reversed_normal_frame_is_rejected() -> None:
    with pytest.raises(TopologyReferenceError) as error:
        local_point_on_face(
            bind_top_face(Box(20, 20, 4)), Plane(origin=(0, 0, 2), z_dir=(0, 0, -1)), (0, 0)
        )
    assert error.value.reason == "unsupported-frame"


def test_missing_native_history_is_not_replaced_by_a_similar_face(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import Sequence

    from mycad.core.topology_evolution import TopologyEvolution
    from mycad.geom.topology_evolution import BooleanKind, boolean_with_evolution
    from tests.geom import design_reference_probe

    def omit_history(
        kind: BooleanKind, arguments: Sequence[Part], tools: Sequence[Part]
    ) -> tuple[Part | None, TopologyEvolution]:
        result, _evolution = boolean_with_evolution(kind, arguments, tools)
        return result, TopologyEvolution(())

    monkeypatch.setattr(design_reference_probe, "boolean_with_evolution", omit_history)
    base = Box(20, 20, 4)
    with pytest.raises(TopologyReferenceError) as error:
        advance_face(base, bind_top_face(base), Cylinder(1, 8))
    assert error.value.reason == "unknown"
