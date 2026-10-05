# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Internal build123d feature operations (Phase 0, T5).

Parses already-normalized feature command parameters (schema validation
happens upstream in the command layer; this module re-validates
defensively) and applies extrude / revolve / hole / hole_pattern / fillet
/ boolean_cut to the current solid. All OCCT exceptions are wrapped into
the closed T1 exception taxonomy before leaving the geom package.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import cast

from build123d import (
    Axis,
    Box,
    Circle,
    Compound,
    Cylinder,
    Edge,
    Face,
    GeomType,
    Part,
    Plane,
    Pos,
    Rectangle,
    Sketch,
    Wire,
    extrude,
    revolve,
)

from mycad.core.exceptions import (
    GeometryBuildError,
    MycadError,
    TopologyReferenceError,
    ValidationError,
)
from mycad.core.selectors import EdgeSelector, FaceSelector
from mycad.geom._b123_ops import (
    checked_mapping,
    normalize_result,
    parse_center,
    parse_mode,
    parse_positive,
    reject_unknown_keys,
)
from mycad.geom.profiles import CircleProfile, Profile, RectProfile, profile_from_mapping
from mycad.geom.selectors import resolve_edges, resolve_face


def apply_feature(
    existing: Part | None, command_id: str, params: Mapping[str, object]
) -> Part | None:
    """Apply one feature command to ``existing``; return the new solid state."""

    checked = checked_mapping(params, command_id)
    if command_id == "feature.extrude":
        return _extrude(existing, command_id, checked)
    if command_id == "feature.revolve":
        return _revolve(existing, command_id, checked)
    if command_id == "modify.fillet":
        return _fillet(existing, command_id, checked)
    if command_id == "modify.boolean_cut":
        return _boolean_cut(existing, command_id, checked)
    if command_id == "feature.hole":
        return _hole(existing, command_id, checked)
    if command_id == "feature.hole_pattern":
        return _hole_pattern(existing, command_id, checked)
    msg = f"{command_id}: command is not implemented in the geometry kernel"
    raise ValidationError(message=msg, command_id=command_id)


def _profile_section(profile: Profile) -> Face | Sketch:
    """Place the profile on the XY work plane (z=0) as an extrudable section."""

    if isinstance(profile, CircleProfile):
        cx, cy = profile.center
        return Pos(cx, cy, 0.0) * Circle(profile.radius)
    if isinstance(profile, RectProfile):
        cx, cy = profile.center
        return Pos(cx, cy, 0.0) * Rectangle(profile.width, profile.height)
    msg = f"sealed profile set violated: {type(profile).__name__}"
    raise ValidationError(message=msg)


def _combine(existing: Part | None, solid: Part, mode: str, command_id: str) -> Part | None:
    """Apply mycad mode semantics (new / add / cut) to a freshly built solid."""

    if mode == "cut" and existing is None:
        msg = f"{command_id}: mode 'cut' requires an existing solid; kernel is empty"
        raise GeometryBuildError(message=msg, command_id=command_id)
    try:
        if mode == "cut":
            assert existing is not None  # narrowed by the guard above
            result = existing - solid
        elif mode == "add" and existing is not None:
            result = existing + solid
        else:
            result = solid
    except MycadError:
        raise
    except Exception as exc:
        msg = f"{command_id}: build123d failed to combine the feature: {exc}"
        raise GeometryBuildError(message=msg, command_id=command_id) from exc
    return normalize_result(result)


_EXTRUDE_KEYS = frozenset({"profile", "distance", "mode"})


def _signed_distance(params: Mapping[str, object], command_id: str) -> float:
    """distance is a signed finite number (negative = along -Z); zero is a
    zero-thickness extrude — a geometry failure, not a validation one."""

    value = params.get("distance")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"{command_id}: parameter 'distance' must be a number, got {value!r}"
        raise ValidationError(message=msg, command_id=command_id)
    if not math.isfinite(value):
        msg = f"{command_id}: parameter 'distance' must be finite, got {value!r}"
        raise ValidationError(message=msg, command_id=command_id)
    if value == 0:
        msg = f"{command_id}: zero-thickness extrude (distance=0) cannot build a solid"
        raise GeometryBuildError(message=msg, command_id=command_id)
    return float(value)


def _extrude(existing: Part | None, command_id: str, params: Mapping[str, object]) -> Part | None:
    """feature.extrude: sweep a profile on the XY plane along signed Z distance."""

    reject_unknown_keys(params, _EXTRUDE_KEYS, command_id)
    profile = profile_from_mapping(params.get("profile"), command_id)
    distance = _signed_distance(params, command_id)
    mode = parse_mode(params, command_id)
    section = _profile_section(profile)
    try:
        solid = extrude(section, distance)
    except MycadError:
        raise
    except Exception as exc:
        msg = f"{command_id}: build123d failed to extrude the profile: {exc}"
        raise GeometryBuildError(message=msg, command_id=command_id) from exc
    return _combine(existing, solid, mode, command_id)


_REVOLVE_KEYS = frozenset({"profile", "axis", "angle_deg", "mode"})
_UNIT_AXIS_TOLERANCE = 1e-9


def _revolve_axis(value: object, command_id: str) -> Axis:
    """axis is the enum 'X'/'Y' or a unit 3-vector through the origin.

    Non-unit vectors (including the zero vector) are a ValidationError —
    no auto-normalization, no warning: the user must mean the axis they
    spelled. Reversed directions are legal.
    """

    if value == "X":
        return Axis.X
    if value == "Y":
        return Axis.Y
    if isinstance(value, (list, tuple)):
        entries_in = cast("Sequence[object]", value)
        if len(entries_in) != 3:
            msg = (
                f"{command_id}: parameter 'axis' must be 'X', 'Y', or a unit 3-vector, "
                f"got {value!r}"
            )
            raise ValidationError(message=msg, command_id=command_id)
        entries: list[float] = []
        for item in entries_in:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                break
            entries.append(float(item))
        if len(entries) == 3:
            norm = math.sqrt(entries[0] ** 2 + entries[1] ** 2 + entries[2] ** 2)
            if abs(norm - 1.0) > _UNIT_AXIS_TOLERANCE:
                msg = (
                    f"{command_id}: revolve axis {value!r} must be a unit vector; "
                    f"measured norm={norm!r} (no auto-normalization)"
                )
                raise ValidationError(message=msg, command_id=command_id)
            return Axis((0.0, 0.0, 0.0), (entries[0], entries[1], entries[2]))
    msg = f"{command_id}: parameter 'axis' must be 'X', 'Y', or a unit 3-vector, got {value!r}"
    raise ValidationError(message=msg, command_id=command_id)


def _revolve_angle(value: object, command_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"{command_id}: parameter 'angle_deg' must be a number, got {value!r}"
        raise ValidationError(message=msg, command_id=command_id)
    if not math.isfinite(value) or not 0.0 < value <= 360.0:
        msg = f"{command_id}: parameter 'angle_deg' must be in (0, 360], got {value!r}"
        raise ValidationError(message=msg, command_id=command_id)
    return float(value)


def _revolve(existing: Part | None, command_id: str, params: Mapping[str, object]) -> Part | None:
    """feature.revolve: sweep a profile around an axis through the origin."""

    reject_unknown_keys(params, _REVOLVE_KEYS, command_id)
    profile = profile_from_mapping(params.get("profile"), command_id)
    axis = _revolve_axis(params.get("axis"), command_id)
    angle = _revolve_angle(params.get("angle_deg", 360.0), command_id)
    mode = parse_mode(params, command_id)
    section = _profile_section(profile)
    try:
        # Sketch iterates its faces at runtime; the stub's __iter__: Iterator[Shape] is coarser.
        solid = revolve(cast("Face | Iterable[Face]", section), axis=axis, revolution_arc=angle)
    except MycadError:
        raise
    except Exception as exc:
        msg = f"{command_id}: build123d failed to revolve the profile: {exc}"
        raise GeometryBuildError(message=msg, command_id=command_id) from exc
    return _combine(existing, solid, mode, command_id)


_FILLET_KEYS = frozenset({"edges", "radius"})


def _fillet(existing: Part | None, command_id: str, params: Mapping[str, object]) -> Part | None:
    """modify.fillet: round the edges resolved from EdgeSelector predicates.

    Locked signature (fillet_probe.py authority): the METHOD form with the
    radius FIRST — ``part.fillet(radius, edge_list)``; the reversed
    argument order raises TypeError and must never be used.
    """

    reject_unknown_keys(params, _FILLET_KEYS, command_id)
    edges_raw = params.get("edges")
    if not isinstance(edges_raw, (list, tuple)):
        msg = f"{command_id}: parameter 'edges' must be a non-empty array of edge selectors"
        raise ValidationError(message=msg, command_id=command_id)
    edges = cast("Sequence[EdgeSelector | Mapping[str, object]]", edges_raw)
    if len(edges) == 0:
        msg = f"{command_id}: parameter 'edges' must be a non-empty array of edge selectors"
        raise ValidationError(message=msg, command_id=command_id)
    radius = parse_positive(params, "radius", command_id)
    edge_list: list[Edge] = []
    for selector in edges:
        for edge in resolve_edges(selector, existing, command_id):
            if edge not in edge_list:
                edge_list.append(edge)
    if existing is None:
        # Unreachable in practice: edge resolution against an empty kernel
        # raises TopologyReferenceError above; the guard narrows the type.
        msg = f"{command_id}: fillet requires an existing solid; kernel is empty"
        raise GeometryBuildError(message=msg, command_id=command_id)
    try:
        result = existing.fillet(radius, edge_list)
    except MycadError:
        raise
    except Exception as exc:
        msg = f"{command_id}: build123d fillet failed (radius={radius!r}): {exc}"
        raise GeometryBuildError(message=msg, command_id=command_id) from exc
    # fillet's stub returns Solid | Part; normalize_result handles all Shape containers.
    return normalize_result(cast("Part | Compound | Wire", result))


_BOOLEAN_CUT_KEYS = frozenset({"tool"})
_TOOL_BOX_KEYS = frozenset({"type", "size_x", "size_y", "size_z", "center"})
_TOOL_CYLINDER_KEYS = frozenset({"type", "radius", "height", "center"})


def _tool_solid(tool: object, command_id: str) -> Part:
    """Build the inline tool primitive (box / cylinder, never carries a mode)."""

    if not isinstance(tool, Mapping):
        msg = f"{command_id}: parameter 'tool' must be a mapping, got {type(tool).__name__}"
        raise ValidationError(message=msg, command_id=command_id)
    params = cast("Mapping[str, object]", tool)
    tool_type = params.get("type")
    location = Pos(*parse_center(params, command_id))
    if tool_type == "box":
        reject_unknown_keys(params, _TOOL_BOX_KEYS, command_id)
        return location * Box(
            parse_positive(params, "size_x", command_id),
            parse_positive(params, "size_y", command_id),
            parse_positive(params, "size_z", command_id),
        )
    if tool_type == "cylinder":
        reject_unknown_keys(params, _TOOL_CYLINDER_KEYS, command_id)
        return location * Cylinder(
            radius=parse_positive(params, "radius", command_id),
            height=parse_positive(params, "height", command_id),
        )
    msg = f"{command_id}: tool 'type' must be 'box' or 'cylinder', got {tool_type!r}"
    raise ValidationError(message=msg, command_id=command_id)


def _boolean_cut(
    existing: Part | None, command_id: str, params: Mapping[str, object]
) -> Part | None:
    """modify.boolean_cut: subtract an inline tool solid — the only command
    on the ``cut`` verb (feature commands subtract via ``mode='cut'``)."""

    reject_unknown_keys(params, _BOOLEAN_CUT_KEYS, command_id)
    if "tool" not in params:
        msg = f"{command_id}: missing required parameter 'tool'"
        raise ValidationError(message=msg, command_id=command_id)
    if existing is None:
        msg = f"{command_id}: boolean_cut requires an existing solid; kernel is empty"
        raise GeometryBuildError(message=msg, command_id=command_id)
    tool = _tool_solid(params["tool"], command_id)
    try:
        result = existing - tool
    except MycadError:
        raise
    except Exception as exc:
        msg = f"{command_id}: build123d failed to subtract the tool: {exc}"
        raise GeometryBuildError(message=msg, command_id=command_id) from exc
    return normalize_result(result)


_HOLE_KEYS = frozenset({"target_face", "position", "diameter", "depth"})


def _descriptor_json(selector: object) -> str:
    """Echo a face selector descriptor (wire or dataclass form) in errors."""

    if isinstance(selector, FaceSelector):
        return json.dumps(
            {"surface": selector.surface, "axis": selector.axis, "rank": selector.rank},
            sort_keys=True,
        )
    if isinstance(selector, Mapping):
        return json.dumps(dict(cast("Mapping[str, object]", selector)), sort_keys=True)
    return repr(selector)


def _parse_hole_fields(
    hole: Mapping[str, object], command_id: str
) -> tuple[FaceSelector | Mapping[str, object], float, str, float | None]:
    """Parse the shared Hole fields (appendix A.0 ``#/$defs/Hole``).

    Returns ``(target_face selector, diameter, depth kind, blind value)``.
    """

    reject_unknown_keys(hole, _HOLE_KEYS, command_id)
    for key in ("target_face", "position", "diameter", "depth"):
        if key not in hole:
            msg = f"{command_id}: missing required parameter {key!r}"
            raise ValidationError(message=msg, command_id=command_id)
    selector: object = hole["target_face"]
    if not isinstance(selector, (FaceSelector, Mapping)):
        msg = f"{command_id}: 'target_face' must be a face selector, got {type(selector).__name__}"
        raise ValidationError(message=msg, command_id=command_id)
    selector_typed = cast("FaceSelector | Mapping[str, object]", selector)
    position: object = hole["position"]
    if not isinstance(position, Mapping):
        msg = (
            f"{command_id}: position {position!r} is not supported; "
            f"Phase 0 only implements {{'kind': 'center'}}"
        )
        raise ValidationError(message=msg, command_id=command_id)
    position_map = cast("Mapping[str, object]", position)
    if set(position_map) != {"kind"} or position_map.get("kind") != "center":
        msg = (
            f"{command_id}: position {position!r} is not supported; "
            f"Phase 0 only implements {{'kind': 'center'}}"
        )
        raise ValidationError(message=msg, command_id=command_id)
    diameter = parse_positive(hole, "diameter", command_id)
    depth: object = hole["depth"]
    if not isinstance(depth, Mapping):
        msg = f"{command_id}: 'depth' must be a mapping, got {type(depth).__name__}"
        raise ValidationError(message=msg, command_id=command_id)
    depth_map = cast("Mapping[str, object]", depth)
    kind = depth_map.get("kind")
    if kind == "through_all":
        if set(depth_map) != {"kind"}:
            msg = f"{command_id}: depth unknown parameter(s) {sorted(set(depth_map) - {'kind'})}"
            raise ValidationError(message=msg, command_id=command_id)
        return selector_typed, diameter, "through_all", None
    if kind == "blind":
        unknown = sorted(set(depth_map) - {"kind", "value"})
        if unknown:
            msg = f"{command_id}: depth unknown parameter(s) {unknown}"
            raise ValidationError(message=msg, command_id=command_id)
        value = parse_positive(depth_map, "value", command_id)
        return selector_typed, diameter, "blind", value
    msg = f"{command_id}: depth kind {kind!r} is not supported; use 'through_all' or 'blind'"
    raise ValidationError(message=msg, command_id=command_id)


def _resolve_hole_target_face(
    part: Part | None, selector: FaceSelector | Mapping[str, object], command_id: str
) -> Face:
    """Resolve the target face and pin it to a plane (holes need a flat datum)."""

    face = resolve_face(selector, part, command_id)
    if face.geom_type != GeomType.PLANE:
        msg = (
            f"reason=target-not-plane: hole target face must be planar, "
            f"got {face.geom_type.name}; descriptor={_descriptor_json(selector)}"
        )
        raise TopologyReferenceError(message=msg, command_id=command_id)
    return face


_BLIND_OVERSHOOT_MM = 0.01


def _hole_cutter(
    part: Part,
    face: Face,
    diameter: float,
    depth_kind: str,
    blind_value: float | None,
    command_id: str,
    offset: tuple[float, float],
) -> Part:
    """Build one hole cutter along the target face's outward normal.

    The hole axis is the outward normal at the face center (fixed rule).
    ``blind`` extends ``blind_value`` into the material — the opposite
    direction of the outward normal — with a tiny outward overshoot so the
    cutter mouth is never coincident with the datum face. ``through_all``
    spans the whole bounding box in BOTH directions along the axis.
    """

    radius = diameter / 2.0
    center = face.center()
    px = center.X + offset[0]
    py = center.Y + offset[1]
    pz = center.Z
    normal = face.normal_at(center)
    n = (normal.X, normal.Y, normal.Z)
    if depth_kind == "through_all":
        bb = part.bounding_box()
        diagonal = math.sqrt(
            (bb.max.X - bb.min.X) ** 2 + (bb.max.Y - bb.min.Y) ** 2 + (bb.max.Z - bb.min.Z) ** 2
        )
        height = 2.0 * diagonal + 2.0 * (radius + 1.0)
        origin = (px, py, pz)
    else:
        assert blind_value is not None  # narrowed by the depth kind
        eps = _BLIND_OVERSHOOT_MM
        height = blind_value + eps
        shift = blind_value / 2.0 - eps / 2.0
        origin = (px - n[0] * shift, py - n[1] * shift, pz - n[2] * shift)
    return Plane(origin=origin, z_dir=n).location * Cylinder(radius, height)


def _subtract_all(existing: Part, cutters: list[Part], command_id: str) -> Part | None:
    try:
        result: object = existing
        for cutter in cutters:
            result = result - cutter
    except MycadError:
        raise
    except Exception as exc:
        msg = f"{command_id}: build123d failed to subtract the hole(s): {exc}"
        raise GeometryBuildError(message=msg, command_id=command_id) from exc
    return normalize_result(result)


def _hole(existing: Part | None, command_id: str, params: Mapping[str, object]) -> Part | None:
    """feature.hole: drill a predicate-located hole at the target face center."""

    reject_unknown_keys(params, _HOLE_KEYS, command_id)
    selector, diameter, depth_kind, blind_value = _parse_hole_fields(params, command_id)
    face = _resolve_hole_target_face(existing, selector, command_id)
    if existing is None:
        # Unreachable in practice: face resolution on an empty kernel raises
        # TopologyReferenceError above; the guard narrows the type.
        msg = f"{command_id}: hole requires an existing solid; kernel is empty"
        raise GeometryBuildError(message=msg, command_id=command_id)
    cutter = _hole_cutter(existing, face, diameter, depth_kind, blind_value, command_id, (0.0, 0.0))
    return _subtract_all(existing, [cutter], command_id)


_HOLE_PATTERN_KEYS = frozenset({"base_hole", "pattern"})
_PATTERN_POLAR_KEYS = frozenset({"kind", "radius", "count", "start_angle_deg"})
_HORIZONTAL_TOLERANCE = 1e-9


def _parse_polar_pattern(pattern: object, command_id: str) -> tuple[float, int, float]:
    """Parse the polar pattern descriptor; anything else is an explicit reject."""

    if not isinstance(pattern, Mapping):
        msg = f"{command_id}: parameter 'pattern' must be a mapping, got {type(pattern).__name__}"
        raise ValidationError(message=msg, command_id=command_id)
    params = cast("Mapping[str, object]", pattern)
    reject_unknown_keys(params, _PATTERN_POLAR_KEYS, command_id)
    kind = params.get("kind")
    if kind != "polar":
        msg = (
            f"{command_id}: pattern kind {kind!r} is not implemented in Phase 0 "
            f"(only 'polar'); rejected explicitly, never silently accepted"
        )
        raise ValidationError(message=msg, command_id=command_id)
    radius = parse_positive(params, "radius", command_id)
    count = params.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or not 2 <= count <= 64:
        msg = f"{command_id}: pattern 'count' must be an integer in [2, 64], got {count!r}"
        raise ValidationError(message=msg, command_id=command_id)
    start = params.get("start_angle_deg", 0.0)
    if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start):
        msg = f"{command_id}: pattern 'start_angle_deg' must be a finite number, got {start!r}"
        raise ValidationError(message=msg, command_id=command_id)
    return radius, count, float(start)


def _hole_pattern(
    existing: Part | None, command_id: str, params: Mapping[str, object]
) -> Part | None:
    """feature.hole_pattern: replicate a predicate-located hole on a polar grid.

    Phase 0 limitation (#round7-3, fixed): the base target face must be a
    horizontal plane (outer normal parallel to global Z). Angles live in
    the GLOBAL XY frame — start_angle_deg=0 is +X, positive rotation goes
    from +X toward +Y (counter-clockwise seen from +Z) and -Z faces are
    NOT mirrored. Each instance drills along the base face's outward
    normal.
    """

    reject_unknown_keys(params, _HOLE_PATTERN_KEYS, command_id)
    for key in ("base_hole", "pattern"):
        if key not in params:
            msg = f"{command_id}: missing required parameter {key!r}"
            raise ValidationError(message=msg, command_id=command_id)
    base = params["base_hole"]
    if not isinstance(base, Mapping):
        msg = f"{command_id}: parameter 'base_hole' must be a mapping, got {type(base).__name__}"
        raise ValidationError(message=msg, command_id=command_id)
    base_map = cast("Mapping[str, object]", base)
    radius, count, start_deg = _parse_polar_pattern(params["pattern"], command_id)
    selector, diameter, depth_kind, blind_value = _parse_hole_fields(base_map, command_id)
    face = _resolve_hole_target_face(existing, selector, command_id)
    normal = face.normal_at(face.center())
    if abs(normal.Z) < 1.0 - _HORIZONTAL_TOLERANCE:
        msg = (
            f"reason=pattern-target-not-horizontal: hole_pattern base target face "
            f"must be horizontal (outer normal parallel to global Z); "
            f"descriptor={_descriptor_json(selector)}"
        )
        raise TopologyReferenceError(message=msg, command_id=command_id)
    if existing is None:
        # Unreachable in practice: face resolution on an empty kernel raises
        # TopologyReferenceError above; the guard narrows the type.
        msg = f"{command_id}: hole_pattern requires an existing solid; kernel is empty"
        raise GeometryBuildError(message=msg, command_id=command_id)
    theta0 = math.radians(start_deg)
    offsets = [
        (
            radius * math.cos(theta0 + 2 * math.pi * i / count),
            radius * math.sin(theta0 + 2 * math.pi * i / count),
        )
        for i in range(count)
    ]
    cutters = [
        _hole_cutter(existing, face, diameter, depth_kind, blind_value, command_id, offset)
        for offset in offsets
    ]
    return _subtract_all(existing, cutters, command_id)
