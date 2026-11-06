# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Native Boolean history must explain how source faces survive or change."""

from __future__ import annotations

from build123d import Box, CenterOf, GeomType, Part, Pos

from mycad.geom.kernel import BuildKernel
from mycad.geom.topology_evolution import boolean_with_evolution


def _face_index(shape: Part, axis: str) -> int:
    for index, face in enumerate(shape.faces()):
        if face.geom_type != GeomType.PLANE:
            continue
        center = face.center(CenterOf.MASS)
        coordinate = {"X": center.X, "Y": center.Y, "Z": center.Z}[axis[-1]]
        if (coordinate > 0.0) == axis.startswith("+"):
            return index
    raise AssertionError(f"missing face on {axis}")


def test_boolean_cut_reports_a_split_source_face() -> None:
    base = Box(20, 20, 4)
    slot_tool = Box(4, 24, 6)
    face_index = _face_index(base, "+Z")

    result, evolution = boolean_with_evolution("cut", [base], [slot_tool])

    assert result is not None
    transition = evolution.face_transition(0, face_index)
    assert transition.relation == "split"
    assert len(transition.targets) == 2
    for edge_index, _edge in enumerate(base.edges()):
        edge_transition = evolution.edge_transition(0, edge_index)
        assert all(target < len(result.edges()) for target in edge_transition.targets)


def test_boolean_fuse_reports_two_source_faces_merged_to_one() -> None:
    left = Box(10, 10, 2)
    right = Pos(10, 0, 0) * Box(10, 10, 2)
    left_top = _face_index(left, "+Z")
    right_top = _face_index(right, "+Z")

    result, evolution = boolean_with_evolution("fuse", [left], [right])

    assert result is not None
    left_transition = evolution.face_transition(0, left_top)
    right_transition = evolution.face_transition(1, right_top)
    assert left_transition.relation == "merged"
    assert right_transition.relation == "merged"
    assert left_transition.targets == right_transition.targets


def test_boolean_cut_marks_a_removed_source_face_deleted() -> None:
    base = Box(20, 20, 4)
    covering_tool = Box(30, 30, 6)
    top_index = _face_index(base, "+Z")

    result, evolution = boolean_with_evolution("cut", [base], [covering_tool])

    assert result is None
    assert evolution.face_transition(0, top_index).relation == "deleted"


def test_hole_captures_modified_preserved_and_generated_faces() -> None:
    kernel = BuildKernel()
    source = Box(20, 20, 20)
    top_index = _face_index(source, "+Z")
    bottom_index = _face_index(source, "-Z")
    side_index = _face_index(source, "+X")
    kernel.apply("feature.box", {"size_x": 20.0, "size_y": 20.0, "size_z": 20.0})
    kernel.apply(
        "feature.hole",
        {
            "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
            "position": {"kind": "center"},
            "diameter": 4.0,
            "depth": {"kind": "through_all"},
        },
    )

    evolution = kernel.last_topology_evolution
    assert evolution is not None
    assert evolution.face_transition(0, top_index).relation == "modified"
    assert evolution.face_transition(0, bottom_index).relation == "preserved"
    assert evolution.face_transition(0, side_index).relation == "preserved"
    assert any(
        transition.kind == "face" and transition.relation == "generated"
        for transition in evolution.transitions
    )


def test_build_kernel_exposes_only_the_last_successful_cut_evolution() -> None:
    kernel = BuildKernel()
    source = Box(20, 20, 4)
    face_index = _face_index(source, "+Z")
    kernel.apply(
        "feature.box",
        {"size_x": 20.0, "size_y": 20.0, "size_z": 4.0, "mode": "new"},
    )
    kernel.apply(
        "modify.boolean_cut",
        {
            "tool": {
                "type": "box",
                "size_x": 4.0,
                "size_y": 24.0,
                "size_z": 6.0,
                "center": [0.0, 0.0, 0.0],
            }
        },
    )

    assert kernel.last_topology_evolution is not None
    transition = kernel.last_topology_evolution.face_transition(0, face_index)
    assert transition.relation == "split"
    assert len(transition.targets) == 2
    kernel.apply(
        "feature.box",
        {"size_x": 3.0, "size_y": 3.0, "size_z": 3.0, "mode": "new"},
    )
    assert kernel.last_topology_evolution is None
