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
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from build123d import CenterOf, Compound, Edge, Face, GeomType, Part, Solid

from mycad.core.exceptions import TopologyReferenceError, ValidationError
from mycad.core.identity import FeatureId, RuntimeIdentityScope
from mycad.core.selectors import BodySelector, EdgeSelector, FaceSelector
from mycad.core.semantic_refs import (
    EdgePredicate,
    FacePredicate,
    SemanticEdgeRef,
    SemanticFaceRef,
    TopologyResolutionEvidence,
)

__all__ = [
    "EdgeSelector",
    "BodySelector",
    "FaceSelector",
    "ordered_face_candidates",
    "body_selector_for_index",
    "resolve_body",
    "resolve_edges",
    "resolve_face",
    "bind_semantic_edge",
    "bind_semantic_face",
    "resolve_semantic_edge",
    "resolve_semantic_face",
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
_ANCHOR_TOLERANCE_MM = 1e-7
_BODY_VOLUME_RELATIVE_TOLERANCE = 1e-8


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _body_signature(solid: Solid) -> tuple[float, tuple[float, float, float], tuple[float, ...]]:
    center = solid.center(CenterOf.MASS)
    bounds = solid.bounding_box()
    return (
        float(solid.volume),
        (float(center.X), float(center.Y), float(center.Z)),
        (
            float(bounds.min.X),
            float(bounds.min.Y),
            float(bounds.min.Z),
            float(bounds.max.X),
            float(bounds.max.Y),
            float(bounds.max.Z),
        ),
    )


def _same_body_signature(solid: Solid, selector: BodySelector) -> bool:
    volume, center, bounds = _body_signature(solid)
    return math.isclose(
        volume,
        selector.volume_mm3,
        rel_tol=_BODY_VOLUME_RELATIVE_TOLERANCE,
        abs_tol=1e-7,
    ) and all(
        abs(actual - expected) <= _ANCHOR_TOLERANCE_MM
        for actual, expected in zip(
            (*center, *bounds), (*selector.center_mm, *selector.bounds_mm), strict=True
        )
    )


def body_selector_for_index(part: Part | Compound | None, body_index: int) -> dict[str, object]:
    """Turn a selected current solid into a stable geometric history locator."""

    if part is None or isinstance(body_index, bool):
        raise TopologyReferenceError("reason=drift: selected body is no longer current")
    solids = part.solids()
    if body_index < 0 or body_index >= len(solids):
        raise TopologyReferenceError("reason=drift: selected body index is out of range")
    volume, center, bounds = _body_signature(solids[body_index])
    matching_indices: list[int] = []
    for index, solid in enumerate(solids):
        candidate_volume, candidate_center, candidate_bounds = _body_signature(solid)
        if math.isclose(
            candidate_volume,
            volume,
            rel_tol=_BODY_VOLUME_RELATIVE_TOLERANCE,
            abs_tol=1e-7,
        ) and all(
            abs(actual - expected) <= _ANCHOR_TOLERANCE_MM
            for actual, expected in zip(
                (*candidate_center, *candidate_bounds), (*center, *bounds), strict=True
            )
        ):
            matching_indices.append(index)
    bounds_tuple = cast("tuple[float, float, float, float, float, float]", bounds)
    selector = BodySelector(volume, center, bounds_tuple)
    if len(matching_indices) > 1:
        selector = BodySelector(
            volume,
            center,
            bounds_tuple,
            matching_indices.index(body_index),
        )
    return selector.to_mapping()


def resolve_body(
    selector: BodySelector | Mapping[str, object],
    part: Part | Compound | None,
    command_id: str,
) -> tuple[int, Solid]:
    """Resolve one whole body by measured signature, rejecting stale/ambiguous refs."""

    try:
        query = (
            selector if isinstance(selector, BodySelector) else BodySelector.from_mapping(selector)
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"{command_id}: invalid body selector: {exc}", command_id=command_id
        ) from exc
    if part is None:
        raise TopologyReferenceError(
            message="reason=no-match: body selector cannot resolve in an empty model",
            command_id=command_id,
            reason="no-match",
        )
    candidates = [
        (index, solid)
        for index, solid in enumerate(part.solids())
        if _same_body_signature(solid, query)
    ]
    if query.rank is not None:
        if query.rank >= len(candidates):
            raise TopologyReferenceError(
                message=f"reason=rank-out-of-range: body selector rank={query.rank}",
                command_id=command_id,
                reason="rank-out-of-range",
            )
        return candidates[query.rank]
    if len(candidates) == 1:
        return candidates[0]
    reason = "no-match" if not candidates else "ambiguous"
    raise TopologyReferenceError(
        message=f"reason={reason}: body selector matched {len(candidates)} body(s)",
        command_id=command_id,
        reason=reason,
    )


def _parse_anchor(value: object, command_id: str, name: str) -> tuple[float, float, float] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        msg = f"{command_id}: {name} must contain exactly 3 finite numbers"
        raise ValidationError(message=msg, command_id=command_id)
    entries = cast("Sequence[object]", value)
    if len(entries) != 3:
        msg = f"{command_id}: {name} must contain exactly 3 finite numbers"
        raise ValidationError(message=msg, command_id=command_id)
    coordinates: list[float] = []
    for component in entries:
        if isinstance(component, bool) or not isinstance(component, int | float):
            msg = f"{command_id}: {name} must contain exactly 3 finite numbers"
            raise ValidationError(message=msg, command_id=command_id)
        coordinate = float(component)
        if not math.isfinite(coordinate):
            msg = f"{command_id}: {name} must contain exactly 3 finite numbers"
            raise ValidationError(message=msg, command_id=command_id)
        coordinates.append(coordinate)
    return (coordinates[0], coordinates[1], coordinates[2])


def _parse_radius(value: object, command_id: str, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{command_id}: {name} must be a positive finite number"
        raise ValidationError(message=msg, command_id=command_id)
    radius = float(value)
    if not math.isfinite(radius) or radius <= 0.0:
        msg = f"{command_id}: {name} must be a positive finite number"
        raise ValidationError(message=msg, command_id=command_id)
    return radius


@dataclass(frozen=True)
class _FaceQuery:
    surface: str
    axis: str | None
    rank: int | None
    center_mm: tuple[float, float, float] | None
    radius_mm: float | None
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
        center_raw: object = None
        radius_raw: object = None
    else:
        surface = selector.get("surface")
        axis = selector.get("axis")
        rank = selector.get("rank")
        center_raw = selector.get("center_mm")
        radius_raw = selector.get("radius_mm")
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
    center_mm = _parse_anchor(center_raw, command_id, "face center_mm")
    radius_mm = _parse_radius(radius_raw, command_id, "face radius_mm")
    if surface == "plane" and axis is None and center_mm is None:
        msg = f"{command_id}: plane face selector requires an explicit axis or center_mm anchor"
        raise ValidationError(message=msg, command_id=command_id)
    if surface != "cylinder" and radius_mm is not None:
        msg = f"{command_id}: face radius_mm is only valid for cylinder selectors"
        raise ValidationError(message=msg, command_id=command_id)
    descriptor = _face_descriptor_dict(selector)
    if descriptor.get("axis") == "":
        descriptor["axis"] = None
    if center_mm is not None:
        descriptor["center_mm"] = list(center_mm)
    if radius_mm is not None:
        descriptor["radius_mm"] = radius_mm
    return _FaceQuery(
        surface=surface,
        axis=axis,
        rank=rank,
        center_mm=center_mm,
        radius_mm=radius_mm,
        descriptor_json=json.dumps(descriptor, sort_keys=True),
    )


def _matching_faces(part: Part | Compound, query: _FaceQuery) -> list[Face]:
    faces: list[Face] = []
    if query.surface == "plane":
        for face in part.faces().filter_by(GeomType.PLANE):
            if query.axis is None:
                faces.append(face)
                continue
            axis_vector = _AXIS_VECTORS[query.axis]
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
    part: Part | Compound | None,
    command_id: str,
) -> list[Face]:
    """All faces matching the selector, in the deterministic total order."""

    query = _build_face_query(selector, command_id)
    if part is None:
        return []
    candidates = sorted(_matching_faces(part, query), key=_face_order_key)
    if query.center_mm is not None:
        candidates = [
            face for face in candidates if _within_anchor(_face_anchor(face), query.center_mm)
        ]
    if query.radius_mm is not None:
        candidates = [
            face
            for face in candidates
            if face.radius is not None
            and abs(float(face.radius) - query.radius_mm) <= _ANCHOR_TOLERANCE_MM
        ]
    return candidates


def resolve_face(
    selector: FaceSelector | Mapping[str, object],
    part: Part | Compound | None,
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
    center_mm: tuple[float, float, float] | None
    radius_mm: float | None
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
        center_raw: object = None
        radius_raw: object = None
    else:
        parents_raw = selector.get("parent_faces")
        curve = selector.get("curve")
        center_raw = selector.get("center_mm")
        radius_raw = selector.get("radius_mm")
    if curve == "":
        curve = None
    if curve is not None and (not isinstance(curve, str) or curve not in ("line", "circle")):
        msg = (
            f"{command_id}: edge selector 'curve' must be 'line' or 'circle' "
            f"(or omitted), got {curve!r}"
        )
        raise ValidationError(message=msg, command_id=command_id)
    center_mm = _parse_anchor(center_raw, command_id, "edge center_mm")
    radius_mm = _parse_radius(radius_raw, command_id, "edge radius_mm")
    if radius_mm is not None and curve == "line":
        msg = f"{command_id}: edge radius_mm cannot be combined with curve='line'"
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
    if center_mm is not None:
        descriptor["center_mm"] = list(center_mm)
    if radius_mm is not None:
        descriptor["radius_mm"] = radius_mm
    return _EdgeQuery(
        parent_selectors=parents,
        curve=curve,
        center_mm=center_mm,
        radius_mm=radius_mm,
        descriptor_json=json.dumps(descriptor, sort_keys=True),
    )


def _edge_order_key(edge: Edge) -> tuple[float, float, float, float]:
    center = edge.center()
    return (-edge.length, center.X, center.Y, center.Z)


def resolve_edges(
    selector: EdgeSelector | Mapping[str, object],
    part: Part | Compound | None,
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
    if query.center_mm is not None:
        edges = [edge for edge in edges if _within_anchor(_edge_anchor(edge), query.center_mm)]
    if query.radius_mm is not None:
        edges = [
            edge
            for edge in edges
            if edge.geom_type == GeomType.CIRCLE
            and abs(float(edge.radius) - query.radius_mm) <= _ANCHOR_TOLERANCE_MM
        ]
    if not edges:
        reason = f"curve filter {query.curve!r}" if query.curve is not None else "parent resolution"
        msg = (
            f"reason=no-match: edge selector matched 0 edges after {reason}; "
            f"descriptor={query.descriptor_json}"
        )
        raise TopologyReferenceError(message=msg, command_id=command_id)
    return sorted(edges, key=_edge_order_key)


def _semantic_error(
    reason: str,
    topology_kind: str,
    role: str,
    command_id: str,
    parameter_path: str | None,
    candidate_count: int | None = None,
) -> TopologyReferenceError:
    count = "" if candidate_count is None else f"; candidates={candidate_count}"
    path = "" if parameter_path is None else f"; parameter_path={parameter_path}"
    message = (
        f"reason={reason}: semantic {topology_kind} role {role!r} could not resolve{count}{path}"
    )
    return TopologyReferenceError(
        message=message,
        command_id=command_id,
        reason=reason,
        parameter_path=parameter_path,
    )


def _face_candidates_for_predicate(
    predicate: FacePredicate,
    part: Part | Compound | None,
    command_id: str,
) -> list[Face]:
    candidates = ordered_face_candidates(
        FaceSelector(surface=predicate.surface, axis=predicate.axis), part, command_id
    )
    if predicate.center_mm is not None:
        candidates = [
            face for face in candidates if _within_anchor(_face_anchor(face), predicate.center_mm)
        ]
    if predicate.radius_mm is not None:
        candidates = [
            face
            for face in candidates
            if face.radius is not None
            and abs(float(face.radius) - predicate.radius_mm) <= _ANCHOR_TOLERANCE_MM
        ]
    return candidates


def _within_anchor(
    candidate: tuple[float, float, float], anchor: tuple[float, float, float]
) -> bool:
    return all(
        abs(actual - expected) <= _ANCHOR_TOLERANCE_MM
        for actual, expected in zip(candidate, anchor, strict=True)
    )


def _face_anchor(face: Face) -> tuple[float, float, float]:
    center = face.center(CenterOf.MASS)
    return float(center.X), float(center.Y), float(center.Z)


def _edge_anchor(edge: Edge) -> tuple[float, float, float]:
    center = edge.arc_center if edge.geom_type == GeomType.CIRCLE else edge.center()
    return float(center.X), float(center.Y), float(center.Z)


def _choose_semantic_face(
    candidates: list[Face],
    role: str,
    command_id: str,
    parameter_path: str | None,
) -> tuple[Face, TopologyResolutionEvidence]:
    if not candidates:
        raise _semantic_error("no-match", "face", role, command_id, parameter_path, 0)
    if role == "max_face":
        max_area = max(face.area for face in candidates)
        winners = [face for face in candidates if face.area == max_area]
        if len(winners) != 1:
            raise _semantic_error(
                "ambiguous", "face", role, command_id, parameter_path, len(winners)
            )
        return winners[0], TopologyResolutionEvidence(
            candidate_count=len(candidates),
            selection_rule="max-area",
            selected_measure=max_area,
        )
    if len(candidates) != 1:
        raise _semantic_error(
            "ambiguous", "face", role, command_id, parameter_path, len(candidates)
        )
    face = candidates[0]
    return face, TopologyResolutionEvidence(
        candidate_count=1,
        selection_rule="unique-predicate",
        selected_measure=face.area,
    )


def bind_semantic_face(
    scope: RuntimeIdentityScope,
    owner_feature: FeatureId,
    role: str,
    predicate: FacePredicate,
    part: Part | Compound | None,
    command_id: str,
    parameter_path: str | None = None,
) -> tuple[SemanticFaceRef, Face]:
    """Bind a face role only after its predicate resolves uniquely."""

    face, _evidence = _choose_semantic_face(
        _face_candidates_for_predicate(predicate, part, command_id),
        role,
        command_id,
        parameter_path,
    )
    reference = SemanticFaceRef(
        owner_feature=owner_feature,
        role=role,
        predicate=predicate,
        topology_id=scope.new_topology_id(),
    )
    return reference, face


def resolve_semantic_face(
    scope: RuntimeIdentityScope,
    reference: SemanticFaceRef,
    owner_feature: FeatureId,
    part: Part | Compound | None,
    command_id: str,
    parameter_path: str | None = None,
) -> tuple[Face, TopologyResolutionEvidence]:
    """Re-query a face role in the current shape or explain why it expired."""

    if not scope.is_current_topology(reference.topology_id):
        scope.require_current_topology(reference.topology_id, command_id, parameter_path)
    if reference.owner_feature != owner_feature:
        raise _semantic_error("deleted", "face", reference.role, command_id, parameter_path)
    return _choose_semantic_face(
        _face_candidates_for_predicate(reference.predicate, part, command_id),
        reference.role,
        command_id,
        parameter_path,
    )


def _edge_candidates_for_predicate(
    predicate: EdgePredicate,
    part: Part | Compound | None,
    command_id: str,
    parameter_path: str | None,
) -> list[Edge]:
    parent_faces: list[Face] = []
    for index, parent_predicate in enumerate(predicate.parent_faces):
        candidates = _face_candidates_for_predicate(parent_predicate, part, command_id)
        if not candidates:
            raise _semantic_error(
                "no-match",
                "face",
                "parent-face",
                command_id,
                f"{parameter_path}.parent_faces[{index}]" if parameter_path else None,
                0,
            )
        for candidate in candidates:
            if candidate not in parent_faces:
                parent_faces.append(candidate)
    edges: list[Edge] = []
    for face in parent_faces:
        for edge in face.edges():
            if edge not in edges:
                edges.append(edge)
    if predicate.curve is not None:
        wanted = GeomType.LINE if predicate.curve == "line" else GeomType.CIRCLE
        edges = [edge for edge in edges if edge.geom_type == wanted]
    if predicate.center_mm is not None:
        edges = [edge for edge in edges if _within_anchor(_edge_anchor(edge), predicate.center_mm)]
    if predicate.radius_mm is not None:
        edges = [
            edge
            for edge in edges
            if edge.geom_type == GeomType.CIRCLE
            and abs(float(edge.radius) - predicate.radius_mm) <= _ANCHOR_TOLERANCE_MM
        ]
    return sorted(edges, key=_edge_order_key)


def _choose_semantic_edge(
    candidates: list[Edge],
    role: str,
    command_id: str,
    parameter_path: str | None,
) -> tuple[Edge, TopologyResolutionEvidence]:
    if not candidates:
        raise _semantic_error("no-match", "edge", role, command_id, parameter_path, 0)
    if role == "longest_edge":
        max_length = max(edge.length for edge in candidates)
        winners = [edge for edge in candidates if edge.length == max_length]
        if len(winners) != 1:
            raise _semantic_error(
                "ambiguous", "edge", role, command_id, parameter_path, len(winners)
            )
        return winners[0], TopologyResolutionEvidence(
            candidate_count=len(candidates),
            selection_rule="max-length",
            selected_measure=max_length,
        )
    if len(candidates) != 1:
        raise _semantic_error(
            "ambiguous", "edge", role, command_id, parameter_path, len(candidates)
        )
    edge = candidates[0]
    return edge, TopologyResolutionEvidence(
        candidate_count=1,
        selection_rule="unique-predicate",
        selected_measure=edge.length,
    )


def bind_semantic_edge(
    scope: RuntimeIdentityScope,
    owner_feature: FeatureId,
    role: str,
    predicate: EdgePredicate,
    part: Part | Compound | None,
    command_id: str,
    parameter_path: str | None = None,
) -> tuple[SemanticEdgeRef, Edge]:
    """Bind one edge role after parent and curve predicates resolve uniquely."""

    edge, _evidence = _choose_semantic_edge(
        _edge_candidates_for_predicate(predicate, part, command_id, parameter_path),
        role,
        command_id,
        parameter_path,
    )
    reference = SemanticEdgeRef(
        owner_feature=owner_feature,
        role=role,
        predicate=predicate,
        topology_id=scope.new_topology_id(),
    )
    return reference, edge


def resolve_semantic_edge(
    scope: RuntimeIdentityScope,
    reference: SemanticEdgeRef,
    owner_feature: FeatureId,
    part: Part | Compound | None,
    command_id: str,
    parameter_path: str | None = None,
) -> tuple[Edge, TopologyResolutionEvidence]:
    """Re-query an edge role in the current shape or explain its expiry."""

    if not scope.is_current_topology(reference.topology_id):
        scope.require_current_topology(reference.topology_id, command_id, parameter_path)
    if reference.owner_feature != owner_feature:
        raise _semantic_error("deleted", "edge", reference.role, command_id, parameter_path)
    return _choose_semantic_edge(
        _edge_candidates_for_predicate(reference.predicate, part, command_id, parameter_path),
        reference.role,
        command_id,
        parameter_path,
    )
