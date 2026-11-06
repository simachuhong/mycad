# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Conservative primitive-face lineage; all indices are operation-local."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol, cast

from build123d import CenterOf, Face, GeomType, Part, Plane

from mycad.core.bound_refs import BoundFaceRef
from mycad.core.command_identity import ExecutionContext
from mycad.core.exceptions import TopologyReferenceError
from mycad.core.sketch import WorkPlaneFrame
from mycad.core.topology_evolution import TopologyEvolution
from mycad.geom._b123_ops import checked_mapping, parse_center

_NORMALS: dict[str, tuple[float, float, float]] = {
    "+X": (1, 0, 0),
    "-X": (-1, 0, 0),
    "+Y": (0, 1, 0),
    "-Y": (0, -1, 0),
    "+Z": (0, 0, 1),
    "-Z": (0, 0, -1),
}


class _ShapeIdentity(Protocol):
    def is_same(self, other: Face) -> bool: ...


def same_face(first: Face, second: Face) -> bool:
    return cast("_ShapeIdentity", first).is_same(second)


def reference_error(reason: str, *, path: str = "target_face") -> TopologyReferenceError:
    return TopologyReferenceError(
        f"design reference cannot resolve uniquely: {reason}",
        command_id="feature.hole",
        reason=reason,
        parameter_path=path,
    )


@dataclass(frozen=True)
class _TrackedFace:
    reference: BoundFaceRef
    face: Face | None
    frame: Plane
    failure: str | None = None


def _advance(
    state: _TrackedFace,
    source: Part,
    result: Part | None,
    evolution: TopologyEvolution | None,
    source_shape_index: int,
    *,
    generated: bool = False,
) -> _TrackedFace:
    if state.face is None:
        return state
    matches = [i for i, face in enumerate(source.faces()) if same_face(face, state.face)]
    if len(matches) != 1 or evolution is None:
        return replace(state, face=None, failure="unknown")
    try:
        transition = evolution.face_transition(source_shape_index, matches[0])
    except KeyError:
        return replace(state, face=None, failure="unknown")
    allowed = ("preserved", "modified", "generated") if generated else ("preserved", "modified")
    if transition.relation not in allowed:
        return replace(state, face=None, failure=transition.relation)
    if result is None or len(transition.targets) != 1:
        return replace(state, face=None, failure="unknown")
    faces = result.faces()
    index = transition.targets[0]
    if not 0 <= index < len(faces):
        return replace(state, face=None, failure="unknown")
    face = faces[index]
    if (
        face.geom_type != GeomType.PLANE
        or face.normal_at().dot(state.frame.z_dir) < 1 - 1e-7
        or abs((face.center() - state.frame.origin).dot(state.frame.z_dir)) > 1e-7
    ):
        return replace(state, face=None, failure="drift")
    return replace(state, face=face)


def _seed(
    source: Part, context: ExecutionContext, params: Mapping[str, object]
) -> tuple[_TrackedFace, ...]:
    if context.instance_id is None or context.command_id not in ("feature.box", "feature.cylinder"):
        return ()
    box = context.command_id == "feature.box"
    roles = (
        tuple(f"box.{axis}" for axis in _NORMALS) if box else ("cylinder.top", "cylinder.bottom")
    )
    center = parse_center(params, context.command_id)
    states: list[_TrackedFace] = []
    for role in roles:
        axis = role.split(".")[1] if box else ("+Z" if role == "cylinder.top" else "-Z")
        normal = _NORMALS[axis]
        dimension_key = f"size_{axis[-1].lower()}" if box else "height"
        half = float(cast("int | float", params[dimension_key])) / 2
        origin = tuple(c + n * half for c, n in zip(center, normal, strict=True))
        frame = Plane(
            origin=origin, x_dir=(1, 0, 0) if axis[-1] == "Z" else (0, 0, 1), z_dir=normal
        )
        faces = [
            face
            for face in source.faces()
            if face.geom_type == GeomType.PLANE and face.normal_at().dot(frame.z_dir) > 1 - 1e-7
        ]
        states.append(
            _TrackedFace(
                BoundFaceRef(context.instance_id, role),
                faces[0] if len(faces) == 1 else None,
                frame,
                None if len(faces) == 1 else "ambiguous",
            )
        )
    return tuple(states)


@dataclass(frozen=True)
class DesignFaces:
    """Immutable live map rebuilt from command history, never serialized."""

    states: tuple[_TrackedFace, ...] = ()

    def evolve(
        self,
        before: Part | None,
        result: Part | None,
        context: ExecutionContext,
        params: Mapping[str, object],
        evolution: TopologyEvolution | None,
        primitive: Part | None,
    ) -> DesignFaces:
        mode = params.get("mode", "new")
        if primitive is not None and (mode == "new" or before is None):
            retired = tuple(replace(s, face=None, failure="deleted") for s in self.states)
            return DesignFaces((*retired, *_seed(primitive, context, params)))
        supported = primitive is not None or context.command_id in (
            "feature.hole",
            "modify.boolean_cut",
        )
        states = tuple(
            _advance(s, before, result, evolution, 0)
            if before is not None and supported
            else replace(s, face=None, failure="unsupported-operation")
            for s in self.states
        )
        if primitive is not None and mode == "add":
            states += tuple(
                _advance(s, primitive, result, evolution, 1, generated=True)
                for s in _seed(primitive, context, params)
            )
        return DesignFaces(states)

    def reference_for(self, face: Face) -> BoundFaceRef:
        matches = [
            s.reference for s in self.states if s.face is not None and same_face(s.face, face)
        ]
        if len(matches) != 1:
            raise reference_error("ambiguous" if matches else "unknown-source")
        return matches[0]

    def frame_for(self, reference: BoundFaceRef) -> WorkPlaneFrame:
        """Return the same persistent local frame used to resolve hole UV coordinates."""
        states = [state for state in self.states if state.reference == reference]
        if len(states) != 1:
            raise reference_error("no-match")
        state = states[0]
        if state.face is None:
            raise reference_error(state.failure or "unknown")
        frame = state.frame
        return WorkPlaneFrame(
            (float(frame.origin.X), float(frame.origin.Y), float(frame.origin.Z)),
            (float(frame.x_dir.X), float(frame.x_dir.Y), float(frame.x_dir.Z)),
            (float(frame.y_dir.X), float(frame.y_dir.Y), float(frame.y_dir.Z)),
            (float(frame.z_dir.X), float(frame.z_dir.Y), float(frame.z_dir.Z)),
        )

    def resolve_position(
        self,
        reference: BoundFaceRef,
        value: object,
    ) -> tuple[Face, tuple[float, float, float]]:
        states = [s for s in self.states if s.reference == reference]
        if len(states) != 1:
            raise reference_error("no-match")
        state = states[0]
        if state.face is None:
            raise reference_error(state.failure or "unknown")
        face = state.face
        position = checked_mapping(value, "feature.hole")
        if position.get("kind") == "local":
            raw = position.get("uv_mm")
            if not isinstance(raw, (list, tuple)):
                raise reference_error("invalid-point", path="position.uv_mm")
            uv = cast("Sequence[object]", raw)
            if len(uv) != 2:
                raise reference_error("invalid-point", path="position.uv_mm")
            if any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in uv
            ):
                raise reference_error("invalid-point", path="position.uv_mm")
            numbers = cast("Sequence[int | float]", uv)
            point = (
                state.frame.origin + state.frame.x_dir * numbers[0] + state.frame.y_dir * numbers[1]
            )
        elif position.get("kind") == "center":
            point = face.center(CenterOf.MASS)
        else:
            from build123d import Vector

            point = Vector(*parse_center({"center": position.get("point")}, "feature.hole"))
        if abs((point - face.center()).dot(state.frame.z_dir)) > 1e-7 or not face.is_inside(
            point, tolerance=1e-7
        ):
            raise reference_error("outside-face", path="position")
        return face, (point.X, point.Y, point.Z)
