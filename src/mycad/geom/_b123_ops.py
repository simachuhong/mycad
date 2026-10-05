# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Internal build123d operations for the kernel adapter.

Parses already-normalized command parameters (schema validation happens
upstream in the command layer; this module re-validates defensively) and
applies ``feature.box`` / ``feature.cylinder`` primitives in all three
boolean modes.

mycad mode semantics map to build123d boolean algebra: ``new`` starts a
fresh solid (replace), ``add`` is the fuse operation (build123d ``Mode.ADD``
semantics, spelled ``part + primitive`` here), ``cut`` is the subtract
operation (``Mode.SUBTRACT`` semantics, ``part - primitive``). build123d
0.11.1 has no ``Mode.NEW`` enum member and its builder ``add()`` symbol
carries partially-unknown type annotations, so the strictly-typed algebra
operators — the same fuse/subtract the builder mode uses internally — are
the direct equivalent. Volumes for all three modes are pinned analytically
in tests/geom/test_kernel_primitives.py.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from build123d import Box, Compound, Cylinder, Part, Pos, Wire

from mycad.core.exceptions import GeometryBuildError, MycadError, ValidationError

_MODES = frozenset({"new", "add", "cut"})


def checked_mapping(value: object, command_id: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        msg = f"{command_id}: params must be a mapping, got {type(value).__name__}"
        raise ValidationError(message=msg, command_id=command_id)
    return cast("Mapping[str, object]", value)


_BOX_KEYS = frozenset({"size_x", "size_y", "size_z", "center", "mode"})
_CYLINDER_KEYS = frozenset({"radius", "height", "center", "mode"})


@dataclass(frozen=True)
class _BoxParams:
    size_x: float
    size_y: float
    size_z: float
    center: tuple[float, float, float]
    mode: str


@dataclass(frozen=True)
class _CylinderParams:
    radius: float
    height: float
    center: tuple[float, float, float]
    mode: str


_PrimitiveParams = _BoxParams | _CylinderParams


def reject_unknown_keys(
    params: Mapping[str, object], allowed: frozenset[str], command_id: str
) -> None:
    unknown = sorted(set(params) - allowed)
    if unknown:
        msg = f"{command_id}: unknown parameter(s) {unknown}; allowed keys: {sorted(allowed)}"
        raise ValidationError(message=msg, command_id=command_id)


def parse_positive(params: Mapping[str, object], key: str, command_id: str) -> float:
    if key not in params:
        msg = f"{command_id}: missing required parameter {key!r}"
        raise ValidationError(message=msg, command_id=command_id)
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"{command_id}: parameter {key!r} must be a number, got {value!r}"
        raise ValidationError(message=msg, command_id=command_id)
    if not math.isfinite(value) or value <= 0:
        msg = f"{command_id}: parameter {key!r} must be a positive finite number, got {value!r}"
        raise ValidationError(message=msg, command_id=command_id)
    return float(value)


def parse_center(params: Mapping[str, object], command_id: str) -> tuple[float, float, float]:
    if "center" not in params:
        return (0.0, 0.0, 0.0)
    value = params["center"]
    if not isinstance(value, (list, tuple)):
        msg = f"{command_id}: parameter 'center' must be a 3-number sequence"
        raise ValidationError(message=msg, command_id=command_id)
    entries = cast("Sequence[object]", value)
    if len(entries) != 3:
        msg = f"{command_id}: parameter 'center' must have exactly 3 entries"
        raise ValidationError(message=msg, command_id=command_id)
    coords: list[float] = []
    for item in entries:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            msg = f"{command_id}: parameter 'center' must contain only numbers"
            raise ValidationError(message=msg, command_id=command_id)
        if not math.isfinite(item):
            msg = f"{command_id}: parameter 'center' entries must be finite"
            raise ValidationError(message=msg, command_id=command_id)
        coords.append(float(item))
    return (coords[0], coords[1], coords[2])


def parse_mode(params: Mapping[str, object], command_id: str) -> str:
    value = params.get("mode", "new")
    if not isinstance(value, str) or value not in _MODES:
        msg = f"{command_id}: parameter 'mode' must be one of {sorted(_MODES)}, got {value!r}"
        raise ValidationError(message=msg, command_id=command_id)
    return value


def _parse_box(command_id: str, params: Mapping[str, object]) -> _PrimitiveParams:
    reject_unknown_keys(params, _BOX_KEYS, command_id)
    return _BoxParams(
        size_x=parse_positive(params, "size_x", command_id),
        size_y=parse_positive(params, "size_y", command_id),
        size_z=parse_positive(params, "size_z", command_id),
        center=parse_center(params, command_id),
        mode=parse_mode(params, command_id),
    )


def _parse_cylinder(command_id: str, params: Mapping[str, object]) -> _PrimitiveParams:
    reject_unknown_keys(params, _CYLINDER_KEYS, command_id)
    return _CylinderParams(
        radius=parse_positive(params, "radius", command_id),
        height=parse_positive(params, "height", command_id),
        center=parse_center(params, command_id),
        mode=parse_mode(params, command_id),
    )


def _placed_primitive(spec: _PrimitiveParams) -> Part:
    location = Pos(spec.center[0], spec.center[1], spec.center[2])
    if isinstance(spec, _BoxParams):
        return location * Box(spec.size_x, spec.size_y, spec.size_z)
    return location * Cylinder(radius=spec.radius, height=spec.height)


def normalize_result(result: Part | Compound | Wire) -> Part | None:
    solids = result.solids()
    if not solids:
        return None
    if isinstance(result, Part):
        return result
    return Part(solids)


def apply_primitive(
    existing: Part | None, command_id: str, params: Mapping[str, object]
) -> Part | None:
    """Apply one feature command to ``existing``; return the new solid state.

    Returns ``None`` when the operation leaves no solid (empty geometry is a
    defined state, not an error).
    """

    checked = checked_mapping(params, command_id)
    if command_id == "feature.box":
        spec = _parse_box(command_id, checked)
    elif command_id == "feature.cylinder":
        spec = _parse_cylinder(command_id, checked)
    else:
        msg = f"{command_id}: command is not implemented in the geometry kernel"
        raise ValidationError(message=msg, command_id=command_id)
    if spec.mode == "cut" and existing is None:
        msg = f"{command_id}: mode 'cut' requires an existing solid; kernel is empty"
        raise GeometryBuildError(message=msg, command_id=command_id)
    primitive = _placed_primitive(spec)
    try:
        if spec.mode == "cut":
            assert existing is not None  # narrowed by the guard above
            result = existing - primitive
        elif spec.mode == "add" and existing is not None:
            result = existing + primitive
        else:
            result = primitive
    except MycadError:
        raise
    except Exception as exc:
        msg = f"{command_id}: build123d failed to apply the primitive: {exc}"
        raise GeometryBuildError(message=msg, command_id=command_id) from exc
    return normalize_result(result)
