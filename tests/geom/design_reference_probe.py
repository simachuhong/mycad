# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Test-only N3 E1 prototype. No production command or persistence contract."""

from __future__ import annotations

import math
from typing import Protocol, cast

from build123d import Face, GeomType, Part, Plane, Vector

from mycad.core.exceptions import TopologyReferenceError
from mycad.geom.topology_evolution import BooleanKind, boolean_with_evolution


class _FaceIdentity(Protocol):
    def is_same(self, other: Face) -> bool: ...


def _failure(reason: str) -> TopologyReferenceError:
    return TopologyReferenceError(
        f"E1 probe cannot preserve selected face: {reason}",
        command_id="e1.probe",
        reason=reason,
        parameter_path="target_face",
    )


def bind_top_face(shape: Part) -> Face:
    candidates = [
        face
        for face in shape.faces()
        if face.geom_type == GeomType.PLANE and face.normal_at().Z > 1 - 1e-8
    ]
    if len(candidates) != 1:
        raise _failure("ambiguous" if candidates else "no-match")
    return candidates[0]


def advance_face(
    shape: Part, face: Face, tool: Part, operation: BooleanKind = "cut"
) -> tuple[Part, Face]:
    indices = [
        index
        for index, candidate in enumerate(shape.faces())
        if cast("_FaceIdentity", candidate).is_same(face)
    ]
    if len(indices) != 1:
        raise _failure("wrong-source")
    result, evolution = boolean_with_evolution(operation, [shape], [tool])
    try:
        transition = evolution.face_transition(0, indices[0])
    except KeyError as exc:
        raise _failure("unknown") from exc
    if transition.relation not in ("preserved", "modified"):
        raise _failure(transition.relation)
    if result is None or len(transition.targets) != 1:
        raise _failure("unknown")
    faces = result.faces()
    index = transition.targets[0]
    if not 0 <= index < len(faces):
        raise _failure("unknown")
    successor = faces[index]
    if successor.geom_type != face.geom_type or successor.normal_at().dot(face.normal_at()) < (
        1 - 1e-8
    ):
        raise _failure("drift")
    return result, successor


def local_point_on_face(
    face: Face, frame: Plane, uv: tuple[float, float]
) -> tuple[float, float, float]:
    if not all(math.isfinite(value) for value in uv):
        raise _failure("invalid-point")
    if face.geom_type != GeomType.PLANE or face.normal_at().dot(frame.z_dir) < 1 - 1e-8:
        raise _failure("unsupported-frame")
    point: Vector = frame.origin + frame.x_dir * uv[0] + frame.y_dir * uv[1]
    if abs((point - face.center()).dot(face.normal_at())) > 1e-7 or not face.is_inside(
        point, tolerance=1e-7
    ):
        raise _failure("outside-face")
    return point.X, point.Y, point.Z
