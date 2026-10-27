# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Filter immutable display DTOs without suppressing any model geometry."""

from __future__ import annotations

from dataclasses import replace

from mycad.core.geometry_types import Tessellation
from mycad.core.identity import BodyId
from mycad.core.viewport_protocol import ViewportData


def visible_body_snapshot(snapshot: ViewportData, hidden: set[BodyId]) -> ViewportData:
    if not hidden:
        return snapshot
    indices = [i for i, body in enumerate(snapshot.triangle_body_ids) if body not in hidden]
    triangles = [snapshot.mesh.triangle_indices[i] for i in indices]
    vertex_indices = sorted({index for triangle in triangles for index in triangle})
    remap = {old: new for new, old in enumerate(vertex_indices)}
    mesh = Tessellation(
        tuple(snapshot.mesh.vertices[i] for i in vertex_indices),
        tuple((remap[a], remap[b], remap[c]) for a, b, c in triangles),
    )
    return replace(
        snapshot,
        mesh=mesh,
        normals=(),
        body_origins=tuple(
            origin for origin in snapshot.body_origins if origin.body_id not in hidden
        ),
        triangle_body_ids=tuple(snapshot.triangle_body_ids[i] for i in indices),
        triangle_face_ids=tuple(snapshot.triangle_face_ids[i] for i in indices),
        boundary_edges=tuple(
            edge for edge in snapshot.boundary_edges if edge.body_id not in hidden
        ),
        vertices=tuple(vertex for vertex in snapshot.vertices if vertex.body_id not in hidden),
        faces=tuple(face for face in snapshot.faces if face.body_id not in hidden),
    )
