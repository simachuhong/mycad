# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral-DTO geometry queries: mass properties and tessellation.

All build123d/OCP measurements are converted with explicit ``float()`` /
``tuple()`` calls so no backend type crosses the geom boundary.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from copy import deepcopy

from build123d import Compound, Edge, Face, GeomType, Part

from mycad.core.exceptions import GeometryBuildError, ValidationError
from mycad.core.geometry_checks import GeometryCheckIssue, GeometryCheckResult
from mycad.core.geometry_types import BoundingBox, MassProperties, Tessellation
from mycad.core.identity import BodyId, TopologyId
from mycad.core.viewport_protocol import (
    ViewportBoundaryEdge,
    ViewportFace,
    ViewportVertex,
)

_EMPTY_MASS_PROPERTIES = MassProperties(
    volume=0.0,
    solid_count=0,
    cylindrical_face_count=0,
    bbox=None,
    center_of_mass=(0.0, 0.0, 0.0),
)

_PARALLEL_TOLERANCE = 1e-9


def _is_nonempty_part(part: Part | Compound | None) -> bool:
    return part is not None and len(part.solids()) > 0


def validate_result(
    part: Part | Compound | None,
    command_id: str,
    *,
    require_single_solid: bool = False,
) -> GeometryCheckResult:
    """Check one command result without healing or changing its BREP.

    ``None`` and a null shape are valid empty results (for example, a cut
    that removes the complete body). Non-null non-solid shapes are invalid.
    Every nonempty result is checked by build123d's BRepCheck_Analyzer-backed
    ``is_valid`` property, and volume must be finite and nonnegative.
    """

    if part is None or part.is_null:
        return GeometryCheckResult(is_valid=True, solid_count=0, volume_mm3=0.0)

    solids = part.solids()
    solid_count = len(solids)
    if solid_count == 0 and not (part.faces() or part.edges() or part.vertices()):
        return GeometryCheckResult(is_valid=True, solid_count=0, volume_mm3=0.0)
    volume_mm3 = float(part.volume)
    issues: list[GeometryCheckIssue] = []

    if solid_count == 0:
        issues.append(
            GeometryCheckIssue(
                code="no-solid-result",
                message="non-null geometry result contains no solids",
                command_id=command_id,
            )
        )
    if not part.is_valid:
        issues.append(
            GeometryCheckIssue(
                code="invalid-brep",
                message="BREP validity check failed",
                command_id=command_id,
            )
        )
    for index, solid in enumerate(solids):
        if not solid.is_valid:
            issues.append(
                GeometryCheckIssue(
                    code="invalid-solid",
                    message=f"solid {index} failed BREP validity check",
                    command_id=command_id,
                )
            )
    if not math.isfinite(volume_mm3):
        issues.append(
            GeometryCheckIssue(
                code="non-finite-volume",
                message=f"volume must be finite, got {volume_mm3!r}",
                command_id=command_id,
            )
        )
    elif volume_mm3 < 0.0:
        issues.append(
            GeometryCheckIssue(
                code="negative-volume",
                message=f"volume must be nonnegative, got {volume_mm3!r}",
                command_id=command_id,
            )
        )
    if require_single_solid and solid_count != 1:
        issues.append(
            GeometryCheckIssue(
                code="solid-count",
                message=f"expected one solid, got {solid_count}",
                command_id=command_id,
                parameter_path="mode",
            )
        )

    return GeometryCheckResult(
        is_valid=not issues,
        solid_count=solid_count,
        volume_mm3=volume_mm3,
        issues=tuple(issues),
    )


def require_valid_result(result: GeometryCheckResult) -> None:
    """Raise the existing geometry exception for an invalid result."""

    if result.is_valid:
        return
    issue = result.issues[0]
    msg = f"{issue.command_id}: geometry check {issue.code} failed: {issue.message}"
    raise GeometryBuildError(message=msg, command_id=issue.command_id)


def measure_cylindrical_face_diameter(face: Face) -> float:
    """Return the analytic diameter of a cylindrical BREP face."""

    if face.geom_type != GeomType.CYLINDER or face.radius is None:
        raise ValueError("select one cylindrical face")
    return 2.0 * float(face.radius)


def measure_circular_edge_center_distance(first: Edge, second: Edge) -> float:
    """Return the Euclidean distance between two exact circle centers."""

    if first.geom_type != GeomType.CIRCLE or second.geom_type != GeomType.CIRCLE:
        raise ValueError("select two circular edges")
    first_center = first.arc_center
    second_center = second.arc_center
    dx = float(first_center.X - second_center.X)
    dy = float(first_center.Y - second_center.Y)
    dz = float(first_center.Z - second_center.Z)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def measure_parallel_plane_separation(first: Face, second: Face) -> float:
    """Return the exact normal separation for two parallel planar faces."""

    if first.geom_type != GeomType.PLANE or second.geom_type != GeomType.PLANE:
        raise ValueError("select two planar faces")
    first_center = first.center()
    second_center = second.center()
    first_normal = first.normal_at(first_center)
    second_normal = second.normal_at(second_center)
    dot = float(
        first_normal.X * second_normal.X
        + first_normal.Y * second_normal.Y
        + first_normal.Z * second_normal.Z
    )
    if abs(dot) < 1.0 - _PARALLEL_TOLERANCE:
        raise ValueError("selected planar faces are not parallel")
    dx = float(second_center.X - first_center.X)
    dy = float(second_center.Y - first_center.Y)
    dz = float(second_center.Z - first_center.Z)
    projected = dx * first_normal.X + dy * first_normal.Y + dz * first_normal.Z
    return abs(float(projected))


def build_mass_properties(part: Part | Compound | None) -> MassProperties:
    """Fill the neutral MassProperties DTO from the build123d part.

    Empty geometry (``part is None`` or zero solids) is a defined state:
    ``solid_count=0``, ``volume=0.0``, ``bbox=None``,
    ``center_of_mass=(0.0, 0.0, 0.0)`` — not an exception.
    """

    if not _is_nonempty_part(part):
        return _EMPTY_MASS_PROPERTIES
    assert part is not None
    bb = part.bounding_box()
    center = part.center()
    return MassProperties(
        volume=float(part.volume),
        solid_count=len(part.solids()),
        cylindrical_face_count=len(part.faces().filter_by(GeomType.CYLINDER)),
        bbox=BoundingBox(
            xmin=float(bb.min.X),
            ymin=float(bb.min.Y),
            zmin=float(bb.min.Z),
            xmax=float(bb.max.X),
            ymax=float(bb.max.Y),
            zmax=float(bb.max.Z),
        ),
        center_of_mass=(float(center.X), float(center.Y), float(center.Z)),
    )


def _positive_finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"tessellate: {name} must be a number, got {value!r}"
        raise ValidationError(message=msg)
    if not math.isfinite(value) or value <= 0:
        msg = f"tessellate: {name} must be a positive finite number, got {value!r}"
        raise ValidationError(message=msg)
    return float(value)


def normalize_tessellation_tolerances(
    linear_tolerance_mm: object,
    angular_tolerance_deg: object,
) -> tuple[float, float]:
    """Validate and normalize the values used to identify a mesh request."""

    return (
        _positive_finite(linear_tolerance_mm, "linear_tolerance_mm"),
        _positive_finite(angular_tolerance_deg, "angular_tolerance_deg"),
    )


def build_tessellation(
    part: Part | Compound | None,
    linear_tolerance_mm: object,
    angular_tolerance_deg: object,
) -> Tessellation:
    """Triangulate into memory-only vertex/index tuples.

    ``linear_tolerance_mm`` is the chordal deviation in millimetres;
    ``angular_tolerance_deg`` is the angular deviation in decimal degrees
    (build123d expects radians internally). The mesh is produced from a
    deepcopy of the part so a finer tolerance always re-meshes — build123d
    keeps any cached triangulation and OCCT's incremental mesher never
    refines an already-triangulated face, so reusing the stored shape would
    silently return stale triangle counts.
    """

    linear, angular = normalize_tessellation_tolerances(linear_tolerance_mm, angular_tolerance_deg)
    if not _is_nonempty_part(part):
        return Tessellation(vertices=(), triangle_indices=())
    assert part is not None
    vertices, triangles = deepcopy(part).tessellate(linear, math.radians(angular))
    return Tessellation(
        vertices=tuple((float(v.X), float(v.Y), float(v.Z)) for v in vertices),
        triangle_indices=tuple((int(a), int(b), int(c)) for (a, b, c) in triangles),
    )


def build_boundary_edges(
    part: Part | Compound | None,
    body_ids: Sequence[BodyId],
    topology_id_for_edge: Callable[[int, int], TopologyId],
    linear_tolerance_mm: object = 0.1,
) -> tuple[ViewportBoundaryEdge, ...]:
    """Sample exact BREP edges into neutral, runtime-identified polylines."""
    tolerance = _positive_finite(linear_tolerance_mm, "linear_tolerance_mm")
    if not _is_nonempty_part(part):
        return ()
    assert part is not None
    solids = part.solids()
    if len(solids) != len(body_ids):
        raise ValueError("body identities must align with current solids")
    face_owners_by_edge: dict[int, set[int]] = {}
    for face_index, face in enumerate(part.faces()):
        for face_edge in face.edges():
            face_owners_by_edge.setdefault(hash(face_edge), set()).add(face_index)
    boundaries: list[ViewportBoundaryEdge] = []
    for body_index, (body_id, solid) in enumerate(zip(body_ids, solids, strict=True)):
        for edge_index, edge in enumerate(solid.edges()):
            if len(face_owners_by_edge.get(hash(edge), ())) < 2:
                continue
            length = float(edge.length)
            if not math.isfinite(length) or length <= 0.0:
                continue
            segment_count = (
                1
                if edge.geom_type == GeomType.LINE
                else min(
                    128,
                    max(16, math.ceil(length / (4.0 * tolerance))),
                )
            )
            points = tuple(
                (
                    float((point := edge.position_at(index / segment_count)).X),
                    float(point.Y),
                    float(point.Z),
                )
                for index in range(segment_count + 1)
            )
            boundaries.append(
                ViewportBoundaryEdge(
                    topology_id=topology_id_for_edge(body_index, edge_index),
                    body_id=body_id,
                    points=points,
                )
            )
    return tuple(boundaries)


def build_viewport_topology(
    part: Part | Compound | None,
    body_ids: Sequence[BodyId],
    topology_id_for_face: Callable[[int, int], TopologyId],
    topology_id_for_vertex: Callable[[int, int], TopologyId],
    linear_tolerance_mm: object = 0.1,
    angular_tolerance_deg: object = 15.0,
) -> tuple[
    tuple[ViewportFace, ...],
    tuple[ViewportVertex, ...],
    tuple[TopologyId, ...],
    tuple[BodyId, ...],
]:
    """Map the shape's exact BREP faces/vertices onto tessellated triangles.

    ``Shape.tessellate`` emits triangles in ``part.faces()`` order. We obtain
    each face's triangle count with the same mesh tolerances, then repeat its
    opaque topology/body identities for those triangles. Face/vertex order is
    local to each solid and never persisted.
    """
    linear, angular = normalize_tessellation_tolerances(linear_tolerance_mm, angular_tolerance_deg)
    if not _is_nonempty_part(part):
        return (), (), (), ()
    assert part is not None
    shape = deepcopy(part)
    angular_radians = math.radians(angular)
    shape.mesh(linear, angular_radians)
    solids = shape.solids()
    if len(solids) != len(body_ids):
        raise ValueError("body identities must align with current solids")

    body_for_face: dict[int, BodyId] = {}
    topology_for_face: dict[int, TopologyId] = {}
    viewport_faces: list[ViewportFace] = []
    for body_index, (body_id, solid) in enumerate(zip(body_ids, solids, strict=True)):
        for face_index, face in enumerate(solid.faces()):
            face_hash = hash(face)
            topology_id = topology_id_for_face(body_index, face_index)
            body_for_face[face_hash] = body_id
            topology_for_face[face_hash] = topology_id
            viewport_faces.append(ViewportFace(topology_id=topology_id, body_id=body_id))

    vertices: list[ViewportVertex] = []
    for body_index, (body_id, solid) in enumerate(zip(body_ids, solids, strict=True)):
        for vertex_index, vertex in enumerate(solid.vertices()):
            center = vertex.center()
            vertices.append(
                ViewportVertex(
                    topology_id=topology_id_for_vertex(body_index, vertex_index),
                    body_id=body_id,
                    point=(float(center.X), float(center.Y), float(center.Z)),
                )
            )

    triangle_face_ids: list[TopologyId] = []
    triangle_body_ids: list[BodyId] = []
    for face in shape.faces():
        face_hash = hash(face)
        topology_id = topology_for_face[face_hash]
        body_id = body_for_face[face_hash]
        triangles = face.tessellate(linear, angular_radians)[1]
        triangle_face_ids.extend((topology_id,) * len(triangles))
        triangle_body_ids.extend((body_id,) * len(triangles))

    return (
        tuple(viewport_faces),
        tuple(vertices),
        tuple(triangle_face_ids),
        tuple(triangle_body_ids),
    )
