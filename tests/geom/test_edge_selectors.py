# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""EdgeSelector resolution tests (rule 6 of the plan's selector semantics)."""

from __future__ import annotations

import pytest
from build123d import Edge, GeomType

from mycad.core.exceptions import TopologyReferenceError, ValidationError
from mycad.core.selectors import EdgeSelector, FaceSelector
from mycad.geom.kernel import BuildKernel
from tests.geom._geometry import build_flange, build_stacked_blocks


def _edge_center(edge: Edge) -> tuple[float, float, float]:
    center = edge.center()
    return (float(center.X), float(center.Y), float(center.Z))


def test_box_two_parents_union_dedups_shared_edge() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 20.0, "size_z": 30.0})
    selector = EdgeSelector(
        parent_faces=(
            FaceSelector(surface="plane", axis="+X"),
            FaceSelector(surface="plane", axis="+Z"),
        )
    )
    edges = kernel.resolve_edges(selector, "t")
    # 4 + 4 edges minus the 1 shared vertical edge = 7
    assert len(edges) == 7
    lengths = sorted((edge.length for edge in edges), reverse=True)
    assert lengths == pytest.approx([30.0, 30.0, 20.0, 20.0, 20.0, 10.0, 10.0], abs=1e-9)


def test_edge_total_order_is_length_desc_then_midpoint_lex() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 20.0, "size_z": 30.0})
    edges = kernel.resolve_edges(
        EdgeSelector(
            parent_faces=(
                FaceSelector(surface="plane", axis="+X"),
                FaceSelector(surface="plane", axis="+Z"),
            )
        ),
        "t",
    )
    keys = [(-edge.length, *_edge_center(edge)) for edge in edges]
    assert keys == sorted(keys)
    first = edges[0]
    assert first.length == pytest.approx(30.0, abs=1e-9)
    assert _edge_center(first) == pytest.approx((5.0, -10.0, 0.0), abs=1e-9)


def test_flange_end_face_circle_edges() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    edges = kernel.resolve_edges(
        EdgeSelector(
            parent_faces=(FaceSelector(surface="plane", axis="+Z", rank=0),),
            curve="circle",
        ),
        "t",
    )
    # the end annulus is bounded by 6 full circles: r40 outer, r10 bore, 4x r3
    assert len(edges) == 6
    radii = sorted(round(edge.radius, 6) for edge in edges)
    assert radii == [3.0, 3.0, 3.0, 3.0, 10.0, 40.0]


def test_curve_filter_line_on_flange_end_face_is_no_match() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    selector = EdgeSelector(
        parent_faces=(FaceSelector(surface="plane", axis="+Z", rank=0),),
        curve="line",
    )
    with pytest.raises(TopologyReferenceError, match="no-match") as excinfo:
        kernel.resolve_edges(selector, "modify.fillet")
    message = str(excinfo.value)
    assert "modify.fillet" in message
    assert '"parent_faces"' in message
    assert '"curve": "line"' in message


def test_parent_mismatch_propagates_as_topology_reference_error() -> None:
    kernel = BuildKernel()
    build_flange(kernel)
    selector = EdgeSelector(
        parent_faces=(FaceSelector(surface="cylinder", axis="+X"),),
        curve="circle",
    )
    with pytest.raises(TopologyReferenceError, match="no-match") as excinfo:
        kernel.resolve_edges(selector, "modify.fillet")
    message = str(excinfo.value)
    assert "modify.fillet" in message
    assert '"surface": "cylinder"' in message
    assert '"axis": "+X"' in message


def test_ambiguous_parent_without_rank_fails() -> None:
    kernel = BuildKernel()
    build_stacked_blocks(kernel)
    selector = EdgeSelector(parent_faces=(FaceSelector(surface="plane", axis="+Z"),))
    with pytest.raises(TopologyReferenceError, match="ambiguous"):
        kernel.resolve_edges(selector, "t")


def test_empty_kernel_parent_resolution_is_no_match() -> None:
    kernel = BuildKernel()
    selector = EdgeSelector(parent_faces=(FaceSelector(surface="plane", axis="+Z"),))
    with pytest.raises(TopologyReferenceError, match="no-match"):
        kernel.resolve_edges(selector, "t")


def test_multiple_parents_any_failure_raises() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    selector = EdgeSelector(
        parent_faces=(
            FaceSelector(surface="plane", axis="+Z"),
            FaceSelector(surface="plane", axis="+Z", rank=99),
        )
    )
    with pytest.raises(TopologyReferenceError, match="rank=99"):
        kernel.resolve_edges(selector, "t")


def test_mapping_descriptor_form_is_accepted() -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    descriptor = {
        "parent_faces": [{"surface": "plane", "axis": "+Z"}],
        "curve": "line",
    }
    edges = kernel.resolve_edges(descriptor, "t")
    assert len(edges) == 4
    assert all(edge.geom_type == GeomType.LINE for edge in edges)


@pytest.mark.parametrize(
    "descriptor",
    [
        {"parent_faces": []},
        {"parent_faces": [{"surface": "sphere"}]},
        {"parent_faces": "plane"},
        {"parent_faces": [{"surface": "plane", "axis": "+Z"}], "curve": "spiral"},
    ],
)
def test_malformed_edge_descriptors_raise_validation_error(
    descriptor: dict[str, object],
) -> None:
    kernel = BuildKernel()
    kernel.apply("feature.box", {"size_x": 10.0, "size_y": 10.0, "size_z": 10.0})
    with pytest.raises(ValidationError):
        kernel.resolve_edges(descriptor, "t")
