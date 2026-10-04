# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Predicate selector resolution against build123d topology.

The FaceSelector/EdgeSelector descriptors themselves are defined once in
``mycad.core.selectors`` and re-exported here for import-path convenience.

Resolution rules (fixed by the Phase 0 plan, zero discretion):
1. ``surface`` filters by geometry kind: ``plane`` -> planar faces (axis is
   the outward normal direction), ``cylinder`` -> cylindrical faces (axis is
   the center axis, UNDIRECTED: +Z matches -Z, but +X never matches a
   Z-axis cylinder).
2. ``plane`` REQUIRES ``axis`` (a signed axis value); ``cylinder`` axis is
   optional (None = all cylindrical faces).
3. Candidates are totally ordered by face area descending, then by face
   center (x, y, z) lexicographic ascending, plain float compare, no
   tolerance merging.
4. ``rank`` given: 0-based index into the ordered candidates (rank beyond
   the candidate count fails); ``rank`` omitted: exactly one candidate is
   required (0 -> no-match, >=2 -> ambiguous), never silently candidate 0.
5. Surface/axis mismatch -> TopologyReferenceError reason "no-match" with
   the descriptor JSON echoed.
6. EdgeSelector: resolve ALL parent faces first (any failure raises), take
   the order-preserving deduplicated union of their edges, optionally
   filter by curve kind (line/circle); same total-order semantics on edges
   (length descending, midpoint lexicographic ascending).

Units: millimetres, decimal degrees. The empty string axis ("" -> None
normalization happens upstream in T3) is treated defensively as None here,
so "" and None inputs behave identically.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from build123d import Edge, Face, GeomType, Part

from mycad.core.exceptions import TopologyReferenceError, ValidationError
from mycad.core.selectors import EdgeSelector, FaceSelector

__all__ = [
    "EdgeSelector",
    "FaceSelector",
    "ordered_face_candidates",
    "resolve_edges",
    "resolve_face",
]

_AXIS_VECTORS: dict[str, tuple[float, float, float]] = {
    "+X": (1.0, 0.0, 0.0),
    "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0),
    "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0),
    "-Z": (0.0, 0.0, -1.0),
}

_PARALLEL_TOLERANCE = 1e-9


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


@dataclass(frozen=True)
class _FaceQuery:
    surface: str
    axis: str | None
    rank: int | None
    descriptor_json: str


def _face_descriptor_dict(
    selector: FaceSelector | Mapping[str, object],
) -> dict[str, object]:
    if isinstance(selector, FaceSelector):
        return {
            "surface": selector.surface,
            "axis": selector.axis,
            "rank": selector.rank,
        }
    return dict(selector)


def _build_face_query(selector: FaceSelector | Mapping[str, object], command_id: str) -> _FaceQuery:
    if isinstance(selector, FaceSelector):
        surface: object = selector.surface
        axis: object = selector.axis
        rank: object = selector.rank
    else:
        surface = selector.get("surface")
        axis = selector.get("axis")
        rank = selector.get("rank")
    if axis == "":
        axis = None
    if not isinstance(surface, str) or surface not in ("plane", "cylinder"):
        msg = (
            f"{command_id}: face selector 'surface' must be 'plane' or 'cylinder', got {surface!r}"
        )
        raise ValidationError(message=msg, command_id=command_id)
    if axis is not None and (not isinstance(axis, str) or axis not in _AXIS_VECTORS):
        msg = (
            f"{command_id}: face selector 'axis' must be one of "
            f"{sorted(_AXIS_VECTORS)} (or omitted), got {axis!r}"
        )
        raise ValidationError(message=msg, command_id=command_id)
    if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int)):
        msg = f"{command_id}: face selector 'rank' must be an integer, got {rank!r}"
        raise ValidationError(message=msg, command_id=command_id)
    if rank is not None and rank < 0:
        msg = f"{command_id}: face selector 'rank' must be >= 0, got {rank}"
        raise ValidationError(message=msg, command_id=command_id)
    if surface == "plane" and axis is None:
        msg = (
            f"{command_id}: plane face selector requires an explicit axis "
            f"(the plane normal direction must be explicit); got axis=None"
        )
        raise ValidationError(message=msg, command_id=command_id)
    descriptor = _face_descriptor_dict(selector)
    if descriptor.get("axis") == "":
        descriptor["axis"] = None
    return _FaceQuery(
        surface=surface,
        axis=axis,
        rank=rank,
        descriptor_json=json.dumps(descriptor, sort_keys=True),
    )


def _matching_faces(part: Part, query: _FaceQuery) -> list[Face]:
    faces: list[Face] = []
    if query.surface == "plane":
        if query.axis is None:
            return faces
        axis_vector = _AXIS_VECTORS[query.axis]
        for face in part.faces().filter_by(GeomType.PLANE):
            normal = face.normal_at(face.center())
            if _dot((normal.X, normal.Y, normal.Z), axis_vector) > 1.0 - _PARALLEL_TOLERANCE:
                faces.append(face)
        return faces
    for face in part.faces().filter_by(GeomType.CYLINDER):
        if query.axis is None:
            faces.append(face)
            continue
        axis_vector = _AXIS_VECTORS[query.axis]
        rotation_axis = face.axis_of_rotation
        if rotation_axis is None:
            continue
        direction = rotation_axis.direction
        cylinder_axis = (direction.X, direction.Y, direction.Z)
        if abs(_dot(cylinder_axis, axis_vector)) > 1.0 - _PARALLEL_TOLERANCE:
            faces.append(face)
    return faces


def _face_order_key(face: Face) -> tuple[float, float, float, float]:
    center = face.center()
    return (-face.area, center.X, center.Y, center.Z)


def ordered_face_candidates(
    selector: FaceSelector | Mapping[str, object],
    part: Part | None,
    command_id: str,
) -> list[Face]:
    """All faces matching the selector, in the deterministic total order."""

    query = _build_face_query(selector, command_id)
    if part is None:
        return []
    return sorted(_matching_faces(part, query), key=_face_order_key)


def resolve_face(
    selector: FaceSelector | Mapping[str, object],
    part: Part | None,
    command_id: str,
) -> Face:
    """Resolve a FaceSelector to exactly one face (rank / unique semantics)."""

    query = _build_face_query(selector, command_id)
    candidates = ordered_face_candidates(selector, part, command_id)
    if query.rank is not None:
        if query.rank >= len(candidates):
            msg = (
                f"reason=rank-out-of-range: face selector rank={query.rank} but only "
                f"{len(candidates)} candidate face(s) matched; "
                f"descriptor={query.descriptor_json}"
            )
            raise TopologyReferenceError(message=msg, command_id=command_id)
        return candidates[query.rank]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        msg = (
            f"reason=no-match: face selector matched 0 candidate faces; "
            f"descriptor={query.descriptor_json}"
        )
        raise TopologyReferenceError(message=msg, command_id=command_id)
    msg = (
        f"reason=ambiguous: face selector matched {len(candidates)} candidate "
        f"faces, exactly 1 required (add a rank to disambiguate); "
        f"descriptor={query.descriptor_json}"
    )
    raise TopologyReferenceError(message=msg, command_id=command_id)


@dataclass(frozen=True)
class _EdgeQuery:
    parent_selectors: tuple[FaceSelector | Mapping[str, object], ...]
    curve: str | None
    descriptor_json: str


def _edge_descriptor_dict(
    selector: EdgeSelector | Mapping[str, object],
) -> dict[str, object]:
    if isinstance(selector, EdgeSelector):
        return {
            "parent_faces": [_face_descriptor_dict(parent) for parent in selector.parent_faces],
            "curve": selector.curve,
        }
    return dict(selector)


def _build_edge_query(selector: EdgeSelector | Mapping[str, object], command_id: str) -> _EdgeQuery:
    if isinstance(selector, EdgeSelector):
        parents_raw: object = selector.parent_faces
        curve: object = selector.curve
    else:
        parents_raw = selector.get("parent_faces")
        curve = selector.get("curve")
    if curve == "":
        curve = None
    if curve is not None and (not isinstance(curve, str) or curve not in ("line", "circle")):
        msg = (
            f"{command_id}: edge selector 'curve' must be 'line' or 'circle' "
            f"(or omitted), got {curve!r}"
        )
        raise ValidationError(message=msg, command_id=command_id)
    if isinstance(parents_raw, FaceSelector):
        parents: tuple[FaceSelector | Mapping[str, object], ...] = (parents_raw,)
    elif isinstance(parents_raw, (list, tuple)):
        entries = cast("Sequence[object]", parents_raw)
        if len(entries) == 0:
            msg = f"{command_id}: edge selector needs at least one parent face"
            raise ValidationError(message=msg, command_id=command_id)
        checked: list[FaceSelector | Mapping[str, object]] = []
        for item in entries:
            if isinstance(item, FaceSelector):
                checked.append(item)
            elif isinstance(item, Mapping):
                checked.append(cast("Mapping[str, object]", item))
            else:
                msg = (
                    f"{command_id}: edge selector parent_faces entries must be "
                    f"face selectors, got {type(item).__name__}"
                )
                raise ValidationError(message=msg, command_id=command_id)
        parents = tuple(checked)
    else:
        msg = (
            f"{command_id}: edge selector 'parent_faces' must be a non-empty "
            f"sequence of face selectors"
        )
        raise ValidationError(message=msg, command_id=command_id)
    descriptor = _edge_descriptor_dict(selector)
    if descriptor.get("curve") == "":
        descriptor["curve"] = None
    return _EdgeQuery(
        parent_selectors=parents,
        curve=curve,
        descriptor_json=json.dumps(descriptor, sort_keys=True),
    )


def _edge_order_key(edge: Edge) -> tuple[float, float, float, float]:
    center = edge.center()
    return (-edge.length, center.X, center.Y, center.Z)


def resolve_edges(
    selector: EdgeSelector | Mapping[str, object],
    part: Part | None,
    command_id: str,
) -> list[Edge]:
    """Resolve an EdgeSelector to its ordered, deduplicated edge list."""

    query = _build_edge_query(selector, command_id)
    parent_faces = [resolve_face(parent, part, command_id) for parent in query.parent_selectors]
    edges: list[Edge] = []
    for face in parent_faces:
        for edge in face.edges():
            if edge not in edges:
                edges.append(edge)
    if query.curve is not None:
        wanted = GeomType.LINE if query.curve == "line" else GeomType.CIRCLE
        edges = [edge for edge in edges if edge.geom_type == wanted]
    if not edges:
        reason = f"curve filter {query.curve!r}" if query.curve is not None else "parent resolution"
        msg = (
            f"reason=no-match: edge selector matched 0 edges after {reason}; "
            f"descriptor={query.descriptor_json}"
        )
        raise TopologyReferenceError(message=msg, command_id=command_id)
    return sorted(edges, key=_edge_order_key)
