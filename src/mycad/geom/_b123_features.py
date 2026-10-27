# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Internal build123d feature operations (Phase 0, T5).

Parses already-normalized feature command parameters (schema validation
happens upstream in the command layer; this module re-validates
defensively) and applies sketch features, body operations, fillet/chamfer,
and inline Booleans to the current solid set. All OCCT exceptions are wrapped into
the closed T1 exception taxonomy before leaving the geom package.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
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
    Solid,
    Until,
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
from mycad.core.selectors import BodySelector, EdgeSelector, FaceSelector
from mycad.core.sketch import CircleEntity, LineEntity
from mycad.core.sketch import Sketch as SketchValue
from mycad.geom._b123_ops import (
    checked_mapping,
    normalize_result,
    parse_center,
    parse_mode,
    parse_positive,
    reject_unknown_keys,
)
from mycad.geom.profiles import CircleProfile, Profile, RectProfile, profile_from_mapping
from mycad.geom.selectors import resolve_body, resolve_edges, resolve_face
from mycad.geom.sketch_profiles import make_sketch_faces


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
    if command_id == "modify.chamfer":
        return _chamfer(existing, command_id, checked)
    if command_id == "modify.boolean_cut":
        return _boolean_cut(existing, command_id, checked)
    if command_id == "modify.boolean_intersect":
        return _boolean_intersect(existing, command_id, checked)
    if command_id == "modify.boolean_bodies":
        return _boolean_bodies(existing, command_id, checked)
    if command_id == "modify.body_transform":
        return _body_transform(existing, command_id, checked)
    if command_id == "modify.body_pattern":
        return _body_pattern(existing, command_id, checked)
    if command_id == "feature.hole":
        return _hole(existing, command_id, checked)
    if command_id == "feature.hole_pattern":
        return _hole_pattern(existing, command_id, checked)
    msg = f"{command_id}: command is not implemented in the geometry kernel"
    raise ValidationError(message=msg, command_id=command_id)


def apply_sketch_extrusion(
    existing: Part | None,
    sketches: Mapping[str, SketchValue],
    params: Mapping[str, object],
) -> Part | None:
    """Execute a versioned sketch extrusion against a preceding replayed sketch."""
    command_id = "feature.extrude"
    reject_unknown_keys(params, _SKETCH_EXTRUDE_KEYS, command_id)
    profile = checked_mapping(params.get("profile"), command_id)
    reject_unknown_keys(profile, frozenset({"type", "sketch_id"}), command_id)
    sketch_id = profile.get("sketch_id")
    if profile.get("type") != "sketch" or not isinstance(sketch_id, str):
        raise ValidationError("拉伸草图引用无效。", command_id=command_id)
    sketch = sketches.get(sketch_id)
    if sketch is None:
        raise ValidationError("拉伸引用的草图不存在。", command_id=command_id)
    mode = parse_mode(params, command_id)
    faces = make_sketch_faces(sketch)
    raw_extent_mode = params.get("extent_mode", "one_sided")
    if raw_extent_mode == "to_face":
        selector = checked_mapping(params.get("target_face"), command_id)
        target_face = resolve_face(selector, existing, command_id)
        if target_face.geom_type != GeomType.PLANE:
            raise GeometryBuildError("到面拉伸的终止对象必须是平面。", command_id=command_id)
        target_center = target_face.center()
        sketch_normal = sketch.frame.normal
        signed_plane_offset = sum(
            (float(coordinate) - origin) * normal
            for coordinate, origin, normal in zip(
                (target_center.X, target_center.Y, target_center.Z),
                sketch.frame.origin_mm,
                sketch_normal,
                strict=True,
            )
        )
        if not math.isfinite(signed_plane_offset) or abs(signed_plane_offset) <= 1e-8:
            raise GeometryBuildError("目标平面必须与草图平面保持非零距离。", command_id=command_id)
        try:
            direction = (
                sketch_normal
                if signed_plane_offset > 0.0
                else tuple(-value for value in sketch_normal)
            )
            target_shape = Compound(children=[target_face])
            solid = _extrude_profile_regions(
                faces,
                lambda face: extrude(
                    face,
                    dir=direction,
                    until=Until.LAST,
                    target=target_shape,
                ),
                command_id,
            )
        except MycadError:
            raise
        except Exception as exc:
            raise GeometryBuildError(
                f"草图到面拉伸失败；目标面必须覆盖截面与终止位置：{exc}",
                command_id=command_id,
            ) from exc
        return _combine(existing, solid, mode, command_id)

    extent_mode = _extrude_extent_mode(params, command_id)
    distance = (
        _symmetric_depth(params, command_id)
        if extent_mode == "symmetric"
        else _signed_distance(params, command_id)
    )
    try:
        if extent_mode == "symmetric":
            solid = _extrude_profile_regions(
                faces,
                lambda face: extrude(
                    face,
                    amount=distance / 2.0,
                    both=True,
                    dir=sketch.frame.normal,
                ),
                command_id,
            )
        else:
            solid = _extrude_profile_regions(
                faces,
                lambda face: extrude(face, amount=distance, dir=sketch.frame.normal),
                command_id,
            )
    except MycadError:
        raise
    except Exception as exc:
        raise GeometryBuildError(
            f"草图拉伸失败，请检查方向和距离：{exc}", command_id=command_id
        ) from exc
    return _combine(existing, solid, mode, command_id)


def _extrude_profile_regions(
    faces: tuple[Face, ...], build_region: Callable[[Face], Part], command_id: str
) -> Part:
    """Extrude every disconnected sketch region and retain each resulting solid."""

    solids: list[Solid] = []
    for face in faces:
        region = build_region(face)
        solids.extend(region.solids())
    if not solids:
        raise GeometryBuildError("草图拉伸没有生成实体。", command_id=command_id)
    return Part(solids)


def apply_sketch_revolve(
    existing: Part | None,
    sketches: Mapping[str, SketchValue],
    params: Mapping[str, object],
) -> Part | None:
    """Execute a versioned sketch revolve against preceding replayed sketches."""
    command_id = "feature.revolve"
    reject_unknown_keys(params, _REVOLVE_KEYS, command_id)
    profile = checked_mapping(params.get("profile"), command_id)
    reject_unknown_keys(profile, frozenset({"type", "sketch_id"}), command_id)
    sketch_id = profile.get("sketch_id")
    if profile.get("type") != "sketch" or not isinstance(sketch_id, str):
        raise ValidationError("旋转草图引用无效。", command_id=command_id)
    sketch = sketches.get(sketch_id)
    if sketch is None:
        raise ValidationError("旋转引用的草图不存在。", command_id=command_id)
    axis_reference = params.get("axis_reference")
    if axis_reference is None:
        axis_value = params.get("axis")
        axis = Axis.Z if axis_value == "Z" else _revolve_axis(axis_value, command_id)
    else:
        axis = _sketch_line_axis(sketches, axis_reference, sketch_id, command_id)
    angle = _revolve_angle(params.get("angle_deg", 360.0), command_id)
    mode = parse_mode(params, command_id)
    faces = make_sketch_faces(sketch)
    try:
        solid = revolve(cast("Face | Iterable[Face]", faces), axis=axis, revolution_arc=angle)
    except MycadError:
        raise
    except Exception as exc:
        raise GeometryBuildError(
            f"草图旋转失败，请检查轮廓、轴线与角度：{exc}", command_id=command_id
        ) from exc
    return _combine(existing, solid, mode, command_id)


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


_EXTRUDE_KEYS = frozenset({"profile", "distance", "mode", "extent_mode"})
_SKETCH_EXTRUDE_KEYS = _EXTRUDE_KEYS | {"target_face"}


def _extrude_extent_mode(params: Mapping[str, object], command_id: str) -> str:
    value = params.get("extent_mode", "one_sided")
    if value not in ("one_sided", "symmetric"):
        raise ValidationError(
            f"{command_id}: parameter 'extent_mode' must be 'one_sided' or 'symmetric'",
            command_id=command_id,
        )
    return cast("str", value)


def _symmetric_depth(params: Mapping[str, object], command_id: str) -> float:
    value = params.get("distance")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError(
            f"{command_id}: symmetric total depth must be a positive finite number",
            command_id=command_id,
        )
    try:
        depth = float(value)
    except OverflowError:
        depth = math.inf
    if not math.isfinite(depth) or depth <= 0.0:
        raise ValidationError(
            f"{command_id}: symmetric total depth must be a positive finite number",
            command_id=command_id,
        )
    return depth


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
    """Sweep an XY profile along Z, or a selected planar face along its normal."""

    reject_unknown_keys(params, _EXTRUDE_KEYS, command_id)
    extent_mode = _extrude_extent_mode(params, command_id)
    raw_profile = checked_mapping(params.get("profile"), command_id)
    if raw_profile.get("type") == "face":
        if extent_mode == "symmetric":
            raise ValidationError("面拉伸暂不支持对称终止；请使用单侧范围。", command_id=command_id)
        return _extrude_face(existing, command_id, params, raw_profile)
    profile = profile_from_mapping(params.get("profile"), command_id)
    distance = (
        _symmetric_depth(params, command_id)
        if extent_mode == "symmetric"
        else _signed_distance(params, command_id)
    )
    mode = parse_mode(params, command_id)
    section = _profile_section(profile)
    try:
        if extent_mode == "symmetric":
            solid = extrude(section, distance / 2.0, both=True)
        else:
            solid = extrude(section, distance)
    except MycadError:
        raise
    except Exception as exc:
        msg = f"{command_id}: build123d failed to extrude the profile: {exc}"
        raise GeometryBuildError(message=msg, command_id=command_id) from exc
    return _combine(existing, solid, mode, command_id)


def _extrude_face(
    existing: Part | None,
    command_id: str,
    params: Mapping[str, object],
    profile: Mapping[str, object],
) -> Part:
    """Sweep the actual planar face, including its inner wires, along its normal.

    This is a bounded face extrusion, not a general synchronous face-move solver.
    Positive distance adds material; negative distance removes the swept material.
    """
    reject_unknown_keys(profile, frozenset({"type", "target_face"}), command_id)
    selector = checked_mapping(profile.get("target_face"), command_id)
    face = resolve_face(selector, existing, command_id)
    if face.geom_type != GeomType.PLANE:
        raise GeometryBuildError("请选择平面；曲面暂不支持面拉伸。", command_id=command_id)
    distance = _signed_distance(params, command_id)
    mode = parse_mode(params, command_id)
    expected_mode = "add" if distance > 0 else "cut"
    if mode != expected_mode:
        raise ValidationError(
            "面拉伸：向外使用 add，向内使用 cut；不允许替换原实体。", command_id=command_id
        )
    assert existing is not None  # resolve_face rejects an empty model
    try:
        solid = extrude(face, amount=distance, dir=face.normal_at())
        result = _combine(existing, solid, mode, command_id)
    except MycadError:
        raise
    except Exception as exc:
        raise GeometryBuildError(f"面拉伸失败，请调整距离：{exc}", command_id=command_id) from exc
    if result is None or len(result.solids()) != len(existing.solids()):
        raise GeometryBuildError("此距离会删除或分割实体，请减小拉伸距离。", command_id=command_id)
    if math.isclose(result.volume, existing.volume, rel_tol=1e-10, abs_tol=1e-8):
        raise GeometryBuildError("此距离未改变实体，请调整拉伸距离。", command_id=command_id)
    return result


_REVOLVE_KEYS = frozenset({"profile", "axis", "axis_reference", "angle_deg", "mode"})
_UNIT_AXIS_TOLERANCE = 1e-9


def _sketch_line_axis(
    sketches: Mapping[str, SketchValue],
    value: object,
    profile_sketch_id: str,
    command_id: str,
) -> Axis:
    """Resolve a persistent construction-line reference into a world-space axis."""

    reference = checked_mapping(value, command_id)
    reject_unknown_keys(reference, frozenset({"type", "sketch_id", "entity_id"}), command_id)
    sketch_id = reference.get("sketch_id")
    entity_id = reference.get("entity_id")
    if reference.get("type") != "sketch_line" or not isinstance(sketch_id, str):
        raise ValidationError("回转轴引用无效，必须指向构造线。", command_id=command_id)
    if sketch_id != profile_sketch_id:
        raise ValidationError(
            "axis reference must belong to the same sketch as the revolve profile.",
            command_id=command_id,
        )
    if not isinstance(entity_id, str):
        raise ValidationError("回转轴引用缺少构造线实体 ID。", command_id=command_id)
    sketch = sketches.get(sketch_id)
    if sketch is None:
        raise ValidationError("回转轴引用的草图不存在。", command_id=command_id)
    entity = next((item for item in sketch.entities if item.entity_id == entity_id), None)
    if not isinstance(entity, LineEntity) or not entity.construction:
        raise ValidationError(
            "回转轴引用必须指向 construction line（构造线）。", command_id=command_id
        )
    start = sketch.frame.local_to_world(entity.start_mm)
    end = sketch.frame.local_to_world(entity.end_mm)
    direction = tuple(end[index] - start[index] for index in range(3))
    return Axis(start, direction)


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
_CHAMFER_KEYS = frozenset({"edges", "distance"})


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


def _chamfer(existing: Part | None, command_id: str, params: Mapping[str, object]) -> Part | None:
    """Apply an equal-setback chamfer to selected stable edge predicates."""

    reject_unknown_keys(params, _CHAMFER_KEYS, command_id)
    edges_raw = params.get("edges")
    if not isinstance(edges_raw, (list, tuple)) or not edges_raw:
        raise ValidationError(
            f"{command_id}: parameter 'edges' must be a non-empty array of edge selectors",
            command_id=command_id,
        )
    edges = cast("Sequence[EdgeSelector | Mapping[str, object]]", edges_raw)
    distance = parse_positive(params, "distance", command_id)
    edge_list: list[Edge] = []
    for selector in edges:
        for edge in resolve_edges(selector, existing, command_id):
            if edge not in edge_list:
                edge_list.append(edge)
    if existing is None:
        raise GeometryBuildError(
            f"{command_id}: chamfer requires an existing solid; kernel is empty",
            command_id=command_id,
        )
    try:
        result = existing.chamfer(distance, None, edge_list)
    except MycadError:
        raise
    except Exception as exc:
        raise GeometryBuildError(
            f"{command_id}: build123d chamfer failed (distance={distance!r}): {exc}",
            command_id=command_id,
        ) from exc
    return normalize_result(cast("Part | Compound | Wire", result))


_BOOLEAN_TOOL_KEYS = frozenset({"tool"})
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

    reject_unknown_keys(params, _BOOLEAN_TOOL_KEYS, command_id)
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


def _boolean_intersect(
    existing: Part | None, command_id: str, params: Mapping[str, object]
) -> Part:
    """Intersect the current aggregate with one consumed inline tool solid."""

    reject_unknown_keys(params, _BOOLEAN_TOOL_KEYS, command_id)
    if "tool" not in params:
        msg = f"{command_id}: missing required parameter 'tool'"
        raise ValidationError(message=msg, command_id=command_id)
    if existing is None:
        msg = f"{command_id}: boolean_intersect requires an existing solid; kernel is empty"
        raise GeometryBuildError(message=msg, command_id=command_id)
    tool = _tool_solid(params["tool"], command_id)
    try:
        result = existing & tool
    except MycadError:
        raise
    except Exception as exc:
        msg = f"{command_id}: build123d failed to intersect the tool: {exc}"
        raise GeometryBuildError(message=msg, command_id=command_id) from exc
    normalized = normalize_result(result)
    if normalized is None or not normalized.solids():
        msg = f"{command_id}: intersection produced no solid; the tool has no common volume"
        raise GeometryBuildError(message=msg, command_id=command_id)
    return normalized


_BODY_BOOLEAN_KEYS = frozenset({"operation", "target_body", "tool_body", "keep_tool"})
_BODY_TRANSFORM_KEYS = frozenset({"body", "transform"})
_BODY_PATTERN_KEYS = frozenset({"seed_body", "pattern"})


def _boolean_bodies(existing: Part | None, command_id: str, params: Mapping[str, object]) -> Part:
    """Apply one Boolean operation to two selected bodies and retain all result solids."""

    reject_unknown_keys(params, _BODY_BOOLEAN_KEYS, command_id)
    operation = params.get("operation")
    if operation not in ("union", "difference", "intersection"):
        raise ValidationError(
            "body Boolean operation must be union, difference, or intersection",
            command_id=command_id,
        )
    keep_tool = params.get("keep_tool", False)
    if not isinstance(keep_tool, bool):
        raise ValidationError("keep_tool must be a boolean", command_id=command_id)
    try:
        target_index, target = resolve_body(
            cast("BodySelector | Mapping[str, object]", params.get("target_body")),
            existing,
            command_id,
        )
        tool_index, tool = resolve_body(
            cast("BodySelector | Mapping[str, object]", params.get("tool_body")),
            existing,
            command_id,
        )
    except MycadError:
        raise
    if target_index == tool_index:
        raise ValidationError("target and tool must be two different bodies", command_id=command_id)
    try:
        if operation == "union":
            combined = target + tool
        elif operation == "difference":
            combined = target - tool
        else:
            combined = target & tool
    except MycadError:
        raise
    except Exception as exc:
        raise GeometryBuildError(
            f"body Boolean {operation} failed: {exc}", command_id=command_id
        ) from exc
    if combined is None:
        raise GeometryBuildError(
            f"body Boolean {operation} produced an empty result; no history was written",
            command_id=command_id,
        )
    result = normalize_result(Part([combined]) if isinstance(combined, Solid) else combined)
    result_solids = [] if result is None else list(result.solids())
    if not result_solids:
        raise GeometryBuildError(
            f"body Boolean {operation} produced no solid result; no history was written",
            command_id=command_id,
        )
    assert existing is not None
    replacements: list[Solid] = []
    for index, solid in enumerate(existing.solids()):
        if index == target_index:
            replacements.extend(result_solids)
        elif index == tool_index and not keep_tool:
            continue
        else:
            replacements.append(solid)
    updated = normalize_result(Compound(children=replacements))
    if updated is None:
        raise GeometryBuildError("body Boolean removed every model body", command_id=command_id)
    return updated


def _body_transform(existing: Part | None, command_id: str, params: Mapping[str, object]) -> Part:
    """Move, rotate, mirror or copy one selected solid in replayable history."""

    reject_unknown_keys(params, _BODY_TRANSFORM_KEYS, command_id)
    transform_value = params.get("transform")
    if not isinstance(transform_value, Mapping):
        raise ValidationError("transform must be an operation object", command_id=command_id)
    transform = cast("Mapping[str, object]", transform_value)
    operation = transform.get("operation")
    body_index, body = resolve_body(
        cast("BodySelector | Mapping[str, object]", params.get("body")), existing, command_id
    )
    assert existing is not None
    if operation == "move" or operation == "copy":
        reject_unknown_keys(transform, frozenset({"operation", "translation_mm"}), command_id)
        delta = _body_vector(transform, "translation_mm", command_id)
        if not any(delta):
            raise ValidationError(
                "translation_mm must not be the zero vector", command_id=command_id
            )
        try:
            changed = body.translate(delta)
        except MycadError:
            raise
        except Exception as exc:
            raise GeometryBuildError(
                f"body translation failed: {exc}", command_id=command_id
            ) from exc
    elif operation == "rotate":
        reject_unknown_keys(
            transform,
            frozenset({"operation", "axis_unit", "center_mm", "angle_deg"}),
            command_id,
        )
        axis = _body_unit_vector(transform, "axis_unit", command_id)
        center = _body_vector(transform, "center_mm", command_id)
        angle = _body_angle(transform.get("angle_deg"), command_id)
        try:
            changed = body.rotate(Axis(center, axis), angle)
        except MycadError:
            raise
        except Exception as exc:
            raise GeometryBuildError(f"body rotation failed: {exc}", command_id=command_id) from exc
    elif operation == "mirror":
        reject_unknown_keys(
            transform,
            frozenset({"operation", "plane_normal_unit", "plane_origin_mm"}),
            command_id,
        )
        normal = _body_unit_vector(transform, "plane_normal_unit", command_id)
        plane_origin = _body_vector(transform, "plane_origin_mm", command_id)
        try:
            changed = body.mirror(Plane(origin=plane_origin, z_dir=normal))
        except MycadError:
            raise
        except Exception as exc:
            raise GeometryBuildError(f"body mirror failed: {exc}", command_id=command_id) from exc
    else:
        raise ValidationError(
            "transform operation must be move, rotate, mirror, or copy",
            command_id=command_id,
        )

    solids = existing.solids()
    replacements: list[Solid] = []
    for index, solid in enumerate(solids):
        if index == body_index:
            replacements.append(solid if operation == "copy" else changed)
            if operation == "copy":
                replacements.append(changed)
        else:
            replacements.append(solid)
    updated = normalize_result(Compound(children=replacements))
    if updated is None:
        raise GeometryBuildError("body transform removed every model body", command_id=command_id)
    return updated


def _body_pattern(existing: Part | None, command_id: str, params: Mapping[str, object]) -> Part:
    """Create deterministic separated instances of one selected seed solid."""

    reject_unknown_keys(params, _BODY_PATTERN_KEYS, command_id)
    pattern_value = params.get("pattern")
    if not isinstance(pattern_value, Mapping):
        raise ValidationError("pattern must be an object", command_id=command_id)
    pattern = cast("Mapping[str, object]", pattern_value)
    kind = pattern.get("kind")
    count = pattern.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or not 2 <= count <= 64:
        raise ValidationError(
            "pattern count must be an integer from 2 to 64", command_id=command_id
        )
    seed_index, seed = resolve_body(
        cast("BodySelector | Mapping[str, object]", params.get("seed_body")),
        existing,
        command_id,
    )
    assert existing is not None
    if kind == "linear":
        reject_unknown_keys(pattern, frozenset({"kind", "count", "spacing_mm"}), command_id)
        spacing = _body_vector(pattern, "spacing_mm", command_id)
        if not any(spacing):
            raise ValidationError(
                "linear spacing must not be the zero vector", command_id=command_id
            )
        copies: list[Solid] = []
        try:
            for instance in range(1, count):
                copies.append(seed.translate(tuple(value * instance for value in spacing)))
        except MycadError:
            raise
        except Exception as exc:
            raise GeometryBuildError(
                f"linear body pattern failed: {exc}", command_id=command_id
            ) from exc
    elif kind == "circular":
        reject_unknown_keys(
            pattern,
            frozenset({"kind", "count", "axis_unit", "center_mm", "angle_deg"}),
            command_id,
        )
        axis = _body_unit_vector(pattern, "axis_unit", command_id)
        center = _body_vector(pattern, "center_mm", command_id)
        angle = _body_angle(pattern.get("angle_deg"), command_id, maximum=360.0)
        divisor = count if math.isclose(angle, 360.0, abs_tol=1e-12) else count - 1
        copies = []
        try:
            for instance in range(1, count):
                copies.append(seed.rotate(Axis(center, axis), angle * instance / divisor))
        except MycadError:
            raise
        except Exception as exc:
            raise GeometryBuildError(
                f"circular body pattern failed: {exc}", command_id=command_id
            ) from exc
    else:
        raise ValidationError("pattern kind must be linear or circular", command_id=command_id)

    solids = existing.solids()
    replacements: list[Solid] = []
    for index, solid in enumerate(solids):
        replacements.append(solid)
        if index == seed_index:
            replacements.extend(copies)
    updated = normalize_result(Compound(children=replacements))
    if updated is None:
        raise GeometryBuildError("body pattern removed every model body", command_id=command_id)
    return updated


def _body_vector(
    values: Mapping[str, object], key: str, command_id: str
) -> tuple[float, float, float]:
    value = values.get(key)
    if not isinstance(value, (list, tuple)):
        raise ValidationError(f"{key} must contain three coordinates", command_id=command_id)
    coordinates = cast("Sequence[object]", value)
    if len(coordinates) != 3:
        raise ValidationError(f"{key} must contain three coordinates", command_id=command_id)
    result: list[float] = []
    for coordinate in coordinates:
        if (
            isinstance(coordinate, bool)
            or not isinstance(coordinate, (int, float))
            or not math.isfinite(coordinate)
        ):
            raise ValidationError(f"{key} must contain finite numbers", command_id=command_id)
        result.append(float(coordinate))
    return (result[0], result[1], result[2])


def _body_unit_vector(
    values: Mapping[str, object], key: str, command_id: str
) -> tuple[float, float, float]:
    vector = _body_vector(values, key, command_id)
    length = math.sqrt(sum(value * value for value in vector))
    if not math.isclose(length, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValidationError(f"{key} must be a unit vector", command_id=command_id)
    return vector


def _body_angle(value: object, command_id: str, *, maximum: float = 3600.0) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value == 0.0
        or abs(value) > maximum
    ):
        raise ValidationError(
            f"angle_deg must be finite, nonzero and at most {maximum:g} degrees in magnitude",
            command_id=command_id,
        )
    return float(value)


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
    _parse_hole_position(hole["position"], command_id)
    diameter = parse_positive(hole, "diameter", command_id)
    depth_kind, blind_value = _parse_hole_depth(hole["depth"], command_id)
    return selector_typed, diameter, depth_kind, blind_value


def _parse_hole_depth(value: object, command_id: str) -> tuple[str, float | None]:
    if not isinstance(value, Mapping):
        msg = f"{command_id}: 'depth' must be a mapping, got {type(value).__name__}"
        raise ValidationError(message=msg, command_id=command_id)
    depth_map = cast("Mapping[str, object]", value)
    kind = depth_map.get("kind")
    if kind == "through_all":
        if set(depth_map) != {"kind"}:
            msg = f"{command_id}: depth unknown parameter(s) {sorted(set(depth_map) - {'kind'})}"
            raise ValidationError(message=msg, command_id=command_id)
        return "through_all", None
    if kind == "blind":
        unknown = sorted(set(depth_map) - {"kind", "value"})
        if unknown:
            msg = f"{command_id}: depth unknown parameter(s) {unknown}"
            raise ValidationError(message=msg, command_id=command_id)
        value = parse_positive(depth_map, "value", command_id)
        return "blind", value
    msg = f"{command_id}: depth kind {kind!r} is not supported; use 'through_all' or 'blind'"
    raise ValidationError(message=msg, command_id=command_id)


def _parse_hole_position(value: object, command_id: str) -> tuple[float, float, float] | None:
    position = checked_mapping(value, command_id)
    if dict(position) == {"kind": "center"}:
        return None
    if set(position) == {"kind", "point"} and position["kind"] == "point":
        return parse_center({"center": position["point"]}, command_id)
    raise ValidationError(message="孔位置需要面心或平面上的坐标点。", command_id=command_id)


def _hole_position_offset(value: object, face: Face, command_id: str) -> tuple[float, float, float]:
    point = _parse_hole_position(value, command_id)
    if point is None:
        return (0.0, 0.0, 0.0)
    center = face.center()
    normal = face.normal_at(center)
    offset = (point[0] - center.X, point[1] - center.Y, point[2] - center.Z)
    distance = offset[0] * normal.X + offset[1] * normal.Y + offset[2] * normal.Z
    if abs(distance) > 1e-5 or not face.is_inside(point, tolerance=1e-5):
        raise GeometryBuildError(
            message="孔定位点不在当前目标面的有效区域，请重新选择。", command_id=command_id
        )
    return offset


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
    offset: tuple[float, float, float],
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
    pz = center.Z + offset[2]
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
    offset = _hole_position_offset(params["position"], face, command_id)
    cutter = _hole_cutter(existing, face, diameter, depth_kind, blind_value, command_id, offset)
    return _subtract_all(existing, [cutter], command_id)


_SKETCH_HOLE_KEYS = frozenset({"profile", "target_face", "depth"})


def apply_sketch_hole(
    existing: Part | None,
    sketches: Mapping[str, SketchValue],
    params: Mapping[str, object],
) -> Part | None:
    """Execute ``feature.hole@2`` from circle entities on a selected planar face."""
    command_id = "feature.hole"
    reject_unknown_keys(params, _SKETCH_HOLE_KEYS, command_id)
    profile = checked_mapping(params.get("profile"), command_id)
    reject_unknown_keys(profile, frozenset({"type", "sketch_id"}), command_id)
    sketch_id = profile.get("sketch_id")
    if profile.get("type") != "sketch" or not isinstance(sketch_id, str):
        raise ValidationError("孔的草图引用无效。", command_id=command_id)
    sketch = sketches.get(sketch_id)
    if sketch is None:
        raise ValidationError("孔引用的草图不存在。", command_id=command_id)
    selector = params.get("target_face")
    if not isinstance(selector, (FaceSelector, Mapping)):
        raise ValidationError("草图孔需要选择一个目标平面。", command_id=command_id)
    face = _resolve_hole_target_face(
        existing, cast("FaceSelector | Mapping[str, object]", selector), command_id
    )
    if existing is None:
        raise GeometryBuildError("草图孔需要已有实体。", command_id=command_id)
    depth_kind, blind_value = _parse_hole_depth(params.get("depth"), command_id)
    circles = tuple(
        entity
        for entity in sketch.entities
        if not entity.construction and isinstance(entity, CircleEntity)
    )
    unsupported = tuple(
        entity
        for entity in sketch.entities
        if not entity.construction and not isinstance(entity, CircleEntity)
    )
    if not circles or unsupported:
        raise GeometryBuildError(
            "草图孔只接受至少一个非构造圆；请把定位线标记为构造几何。",
            command_id=command_id,
        )
    face_center = face.center()
    normal = face.normal_at(face_center)
    dot = sum(
        axis * direction
        for axis, direction in zip(sketch.frame.normal, (normal.X, normal.Y, normal.Z), strict=True)
    )
    offset_from_face = sum(
        (coordinate - origin) * direction
        for coordinate, origin, direction in zip(
            sketch.frame.origin_mm,
            (face_center.X, face_center.Y, face_center.Z),
            (normal.X, normal.Y, normal.Z),
            strict=True,
        )
    )
    if abs(abs(dot) - 1.0) > 1e-6 or abs(offset_from_face) > 1e-5:
        raise GeometryBuildError(
            "孔草图必须位于所选平面上，且工作平面法向需与目标面平行。",
            command_id=command_id,
        )
    cutters: list[Part] = []
    for circle in circles:
        world_center = sketch.frame.local_to_world(circle.center_mm)
        offset = _hole_position_offset(
            {"kind": "point", "point": list(world_center)}, face, command_id
        )
        cutters.append(
            _hole_cutter(
                existing,
                face,
                circle.radius_mm * 2.0,
                depth_kind,
                blind_value,
                command_id,
                offset,
            )
        )
    return _subtract_all(existing, cutters, command_id)


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
    base_offset = _hole_position_offset(base_map["position"], face, command_id)
    theta0 = math.radians(start_deg)
    offsets = [
        (
            base_offset[0] + radius * math.cos(theta0 + 2 * math.pi * i / count),
            base_offset[1] + radius * math.sin(theta0 + 2 * math.pi * i / count),
            base_offset[2],
        )
        for i in range(count)
    ]
    cutters = [
        _hole_cutter(existing, face, diameter, depth_kind, blind_value, command_id, offset)
        for offset in offsets
    ]
    return _subtract_all(existing, cutters, command_id)
