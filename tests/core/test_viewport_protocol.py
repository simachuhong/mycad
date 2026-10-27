# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Contract tests for the ViewportData protocol (phase 1, todo 2).

The port is the third core-side dependency inversion: an empty document
vacuously satisfies ``ViewportPort``, bad triangles must die at
construction time (Tessellation's own ``__post_init__``), and the DTO
must be frozen so preview data cannot be mutated mid-frame.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from mycad.core.geometry_types import Tessellation
from mycad.core.identity import BodyId, TopologyId
from mycad.core.viewport_protocol import (
    ViewportBoundaryEdge,
    ViewportData,
    ViewportFace,
    ViewportPort,
    ViewportSketchData,
    ViewportSketchDimension,
    ViewportVertex,
)


class _EmptyKernelPort:
    def viewport_data(self) -> tuple[ViewportData, ...]:
        return ()

    def viewport_state_ids(self) -> tuple[str, ...]:
        return ()

    def sketch_display_data(self) -> tuple[ViewportSketchData, ...]:
        return ()

    def historical_viewport_data(self, state_id: str) -> ViewportData | None:
        return None


def test_viewport_port_is_runtime_checkable_and_allows_empty() -> None:
    """One snapshot per ordinal; an empty document yields an empty tuple."""
    port = _EmptyKernelPort()
    assert isinstance(port, ViewportPort)
    assert port.viewport_data() == ()
    assert isinstance(port.viewport_data(), tuple)


def test_indices_validation_red_path() -> None:
    """A mesh with an out-of-range index must fail at construction, not
    at render time — ViewportData inherits Tessellation's validation."""
    with pytest.raises(ValueError, match="triangle index out of range"):
        ViewportData(
            state_id="demo.cylinder:1",
            mesh=Tessellation(vertices=((0.0, 0.0, 0.0),), triangle_indices=((0, 1, 2),)),
        )


def test_frozen_immutable() -> None:
    data = ViewportData(
        state_id="demo.cylinder:1",
        mesh=Tessellation(vertices=((0.0, 0.0, 0.0),), triangle_indices=()),
        normals=((0.0, 0.0, 1.0),),
    )
    # setattr via a variable name: a direct assignment is a static error on
    # a frozen dataclass, and the repo allows no suppression comments here
    # (same convention as tests/core/test_geometry_types.py).
    field_name = "state_id"
    with pytest.raises(FrozenInstanceError):
        setattr(data, field_name, "demo.hole_pattern:2")


def test_sketch_dimension_viewport_dto_validates_position_style_and_scale() -> None:
    dimension = ViewportSketchDimension(
        "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c",
        "10.00 mm",
        (5.0, 5.0, 0.0),
        (20, 40, 60),
        2.0,
    )

    assert dimension.scale == 2.0
    assert ViewportSketchData("0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a", (), (dimension,))
    with pytest.raises(ValueError, match="finite coordinates"):
        ViewportSketchDimension(
            dimension.constraint_id, dimension.text, (float("nan"), 0, 0), (0, 0, 0)
        )
    with pytest.raises(ValueError, match="scale must be positive"):
        ViewportSketchDimension(dimension.constraint_id, dimension.text, (0, 0, 0), (0, 0, 0), 0.0)


def test_brep_boundary_edge_is_frozen_and_validates_its_polyline() -> None:
    body_id = BodyId(uuid4(), 3)
    edge = ViewportBoundaryEdge(
        topology_id=TopologyId(uuid4(), 3),
        body_id=body_id,
        points=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
    )
    data = ViewportData(
        state_id="feature.box:0",
        mesh=Tessellation(vertices=(), triangle_indices=()),
        boundary_edges=(edge,),
    )

    assert data.boundary_edges == (edge,)
    field_name = "points"
    with pytest.raises(FrozenInstanceError):
        setattr(edge, field_name, ())
    with pytest.raises(ValueError, match="at least two points"):
        ViewportBoundaryEdge(edge.topology_id, body_id, ((0.0, 0.0, 0.0),))
    with pytest.raises(ValueError, match="finite"):
        ViewportBoundaryEdge(edge.topology_id, body_id, ((0.0, 0.0, 0.0), (float("nan"), 0.0, 0.0)))


def test_viewport_face_vertex_and_triangle_identity_mapping_is_frozen() -> None:
    body_id = BodyId(uuid4(), 3)
    face_id = TopologyId(uuid4(), 3)
    vertex_id = TopologyId(uuid4(), 3)
    face = ViewportFace(topology_id=face_id, body_id=body_id)
    vertex = ViewportVertex(
        topology_id=vertex_id,
        body_id=body_id,
        point=(1.0, 2.0, 3.0),
    )
    data = ViewportData(
        state_id="feature.box:0",
        mesh=Tessellation(
            vertices=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            triangle_indices=((0, 1, 2),),
        ),
        geometry_revision=7,
        faces=(face,),
        vertices=(vertex,),
        triangle_face_ids=(face_id,),
        triangle_body_ids=(body_id,),
    )

    assert data.geometry_revision == 7
    assert data.faces == (face,)
    assert data.vertices == (vertex,)
    assert data.triangle_face_ids == (face_id,)
    assert data.triangle_body_ids == (body_id,)
    field_name = "point"
    with pytest.raises(FrozenInstanceError):
        setattr(vertex, field_name, (0.0, 0.0, 0.0))


def test_viewport_triangle_identity_arrays_match_mesh() -> None:
    body_id = BodyId(uuid4(), 3)
    face_id = TopologyId(uuid4(), 3)

    def make_data(
        triangle_face_ids: tuple[TopologyId, ...],
        triangle_body_ids: tuple[BodyId, ...],
    ) -> ViewportData:
        return ViewportData(
            state_id="feature.box:0",
            mesh=Tessellation(
                vertices=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
                triangle_indices=((0, 1, 2),),
            ),
            triangle_face_ids=triangle_face_ids,
            triangle_body_ids=triangle_body_ids,
        )

    with pytest.raises(ValueError, match="triangle count"):
        make_data((), (body_id,))
    with pytest.raises(ValueError, match="triangle count"):
        make_data((face_id,), ())


def test_body_origin_contract_requires_unique_full_coverage_and_valid_result_index() -> None:
    from dataclasses import replace

    from mycad.core.viewport_protocol import BodyResultReference, ViewportBodyOrigin

    body = BodyId(uuid4(), 0)
    origin = ViewportBodyOrigin(body, BodyResultReference("feature.box:0", 0))
    snapshot = ViewportData(
        "feature.box:0",
        Tessellation((), ()),
        faces=(ViewportFace(TopologyId(uuid4(), 0), body),),
        body_origins=(origin,),
    )
    assert snapshot.body_origins == (origin,)
    with pytest.raises(ValueError, match="uniquely cover"):
        replace(snapshot, body_origins=(origin, origin))
    with pytest.raises(ValueError, match="uniquely cover"):
        replace(snapshot, body_origins=(replace(origin, body_id=BodyId(uuid4(), 0)),))
    with pytest.raises(ValueError, match="state identity"):
        BodyResultReference("", 0)
    with pytest.raises(ValueError, match="nonnegative integer"):
        BodyResultReference("feature.box:0", -1)
    with pytest.raises(ValueError, match="nonnegative integer"):
        BodyResultReference("feature.box:0", True)
    assert replace(snapshot, body_origins=()).body_origins == ()
    with pytest.raises(FrozenInstanceError):
        field_name = "solid_index"
        setattr(origin.result, field_name, 4)
