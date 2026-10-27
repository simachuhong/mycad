# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral 2D sketch geometry values; no CAD, UI, or persistence imports."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

from mycad.core.selectors import AxisLiteral
from mycad.core.sketch_constraints import SketchConstraint
from mycad.core.sketch_layers import DEFAULT_DIM_LAYER, SketchLayer, SketchLayerTable

type Point2D = tuple[float, float]
type Point3D = tuple[float, float, float]
_EPSILON = 1e-12
_FRAME_TOLERANCE = 1e-9


def new_sketch_identity() -> str:
    """Return a stable-format identity to embed in a sketch command before submit."""
    return uuid4().hex


def _validate_identity(value: str, name: str) -> None:
    identity_value = cast("object", value)
    if not isinstance(identity_value, str):
        raise ValueError(f"{name} must be a canonical UUID")
    try:
        parsed = UUID(identity_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a canonical UUID") from exc
    if identity_value not in (parsed.hex, str(parsed)):
        raise ValueError(f"{name} must be a canonical UUID")


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _point2(value: object, name: str) -> Point2D:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must contain two finite coordinates")
    pair = cast("Sequence[object]", value)
    if len(pair) != 2:
        raise ValueError(f"{name} must contain two finite coordinates")
    return (_finite_number(pair[0], f"{name}[0]"), _finite_number(pair[1], f"{name}[1]"))


def _point3(value: object, name: str) -> Point3D:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must contain three finite coordinates")
    triple = cast("Sequence[object]", value)
    if len(triple) != 3:
        raise ValueError(f"{name} must contain three finite coordinates")
    return (
        _finite_number(triple[0], f"{name}[0]"),
        _finite_number(triple[1], f"{name}[1]"),
        _finite_number(triple[2], f"{name}[2]"),
    )


def _dot3(first: Point3D, second: Point3D) -> float:
    return sum(left * right for left, right in zip(first, second, strict=True))


def _cross3(first: Point3D, second: Point3D) -> Point3D:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _strict_mapping(value: object, name: str, keys: tuple[str, ...]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    mapping = cast("Mapping[str, object]", value)
    unknown = tuple(key for key in mapping if key not in keys)
    missing = tuple(key for key in keys if key not in mapping)
    if unknown or missing:
        raise ValueError(f"{name} has unknown fields {unknown} or missing fields {missing}")
    return mapping


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _entity_layer_name(value: object) -> str:
    """Validate a CAD layer reference through the same rule as its definition."""
    return SketchLayer(cast("str", value)).name


def _polyline_area(points: tuple[Point2D, ...]) -> float:
    following = (*points[1:], points[0])
    return 0.5 * sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(points, following, strict=True)
    )


def _orientation(first: Point2D, second: Point2D, third: Point2D) -> float:
    return (second[0] - first[0]) * (third[1] - first[1]) - (second[1] - first[1]) * (
        third[0] - first[0]
    )


def _on_segment(first: Point2D, point: Point2D, second: Point2D) -> bool:
    return (
        min(first[0], second[0]) - _EPSILON <= point[0] <= max(first[0], second[0]) + _EPSILON
        and min(first[1], second[1]) - _EPSILON <= point[1] <= max(first[1], second[1]) + _EPSILON
    )


def _segments_intersect(a: Point2D, b: Point2D, c: Point2D, d: Point2D) -> bool:
    ab_c = _orientation(a, b, c)
    ab_d = _orientation(a, b, d)
    cd_a = _orientation(c, d, a)
    cd_b = _orientation(c, d, b)
    if (ab_c > _EPSILON and ab_d < -_EPSILON or ab_c < -_EPSILON and ab_d > _EPSILON) and (
        cd_a > _EPSILON and cd_b < -_EPSILON or cd_a < -_EPSILON and cd_b > _EPSILON
    ):
        return True
    return (
        abs(ab_c) <= _EPSILON
        and _on_segment(a, c, b)
        or abs(ab_d) <= _EPSILON
        and _on_segment(a, d, b)
        or abs(cd_a) <= _EPSILON
        and _on_segment(c, a, d)
        or abs(cd_b) <= _EPSILON
        and _on_segment(c, b, d)
    )


def polyline_self_intersection(
    points: tuple[Point2D, ...], *, closed: bool
) -> tuple[int, int] | None:
    """Return the first touching/crossing nonadjacent segment pair, if any.

    Shared by closed-profile validation and offset-result checks; indices are
    zero based, and the implicit closing segment exists only for closed paths.
    """
    count = len(points)
    segment_count = count if closed else count - 1
    for first_index in range(segment_count):
        first_start = points[first_index]
        first_end = points[(first_index + 1) % count]
        for second_index in range(first_index + 1, segment_count):
            if second_index == first_index + 1 or (
                closed and first_index == 0 and second_index == count - 1
            ):
                continue
            second_start = points[second_index]
            second_end = points[(second_index + 1) % count]
            if _segments_intersect(first_start, first_end, second_start, second_end):
                return first_index, second_index
    return None


def _validate_simple_closed_polyline(points: tuple[Point2D, ...]) -> None:
    if abs(_polyline_area(points)) <= _EPSILON:
        raise ValueError("closed polyline must enclose nonzero area")
    if polyline_self_intersection(points, closed=True) is not None:
        raise ValueError("closed polyline must not self-intersect or touch itself")


@dataclass(frozen=True, slots=True)
class WorkPlaneFrame:
    """Right-handed orthonormal local plane frame, with millimetre origin."""

    origin_mm: Point3D
    u_axis: Point3D
    v_axis: Point3D
    normal: Point3D

    def __post_init__(self) -> None:
        for name in ("origin_mm", "u_axis", "v_axis", "normal"):
            object.__setattr__(self, name, _point3(getattr(self, name), f"work plane {name}"))
        axes = (self.u_axis, self.v_axis, self.normal)
        if any(abs(_dot3(axis, axis) - 1.0) > _FRAME_TOLERANCE for axis in axes) or any(
            abs(_dot3(axes[first], axes[second])) > _FRAME_TOLERANCE
            for first, second in ((0, 1), (0, 2), (1, 2))
        ):
            raise ValueError("work-plane axes must be orthonormal")
        if any(
            abs(actual - expected) > _FRAME_TOLERANCE
            for actual, expected in zip(_cross3(self.u_axis, self.v_axis), self.normal, strict=True)
        ):
            raise ValueError("work-plane frame must be right-handed")

    @classmethod
    def xy(cls) -> WorkPlaneFrame:
        """Return the global XY work plane."""
        return cls(
            origin_mm=(0.0, 0.0, 0.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 1.0, 0.0),
            normal=(0.0, 0.0, 1.0),
        )

    @classmethod
    def xz(cls) -> WorkPlaneFrame:
        """Return an XZ plane with a right-handed normal toward global -Y."""
        return cls(
            origin_mm=(0.0, 0.0, 0.0),
            u_axis=(1.0, 0.0, 0.0),
            v_axis=(0.0, 0.0, -1.0),
            normal=(0.0, 1.0, 0.0),
        )

    @classmethod
    def yz(cls) -> WorkPlaneFrame:
        """Return the YZ plane with the normal toward global +X."""
        return cls(
            origin_mm=(0.0, 0.0, 0.0),
            u_axis=(0.0, 1.0, 0.0),
            v_axis=(0.0, 0.0, 1.0),
            normal=(1.0, 0.0, 0.0),
        )

    @classmethod
    def from_planar_face(
        cls,
        origin_mm: Point3D,
        normal: Point3D,
        *,
        u_hint: Point3D = (1.0, 0.0, 0.0),
    ) -> WorkPlaneFrame:
        """Build a deterministic right-handed local frame on a selected plane."""
        origin = _point3(origin_mm, "face work-plane origin")
        raw_normal = _point3(normal, "face work-plane normal")
        normal_length = math.sqrt(_dot3(raw_normal, raw_normal))
        if normal_length <= _EPSILON:
            raise ValueError("face normal must be nonzero")
        unit_normal: Point3D = (
            raw_normal[0] / normal_length,
            raw_normal[1] / normal_length,
            raw_normal[2] / normal_length,
        )
        hint = _point3(u_hint, "face work-plane U hint")

        def projected_unit(candidate: Point3D) -> Point3D | None:
            normal_component = _dot3(candidate, unit_normal)
            projected: Point3D = (
                candidate[0] - normal_component * unit_normal[0],
                candidate[1] - normal_component * unit_normal[1],
                candidate[2] - normal_component * unit_normal[2],
            )
            length = math.sqrt(_dot3(projected, projected))
            if length <= _EPSILON:
                return None
            return (
                projected[0] / length,
                projected[1] / length,
                projected[2] / length,
            )

        u_axis = projected_unit(hint)
        if u_axis is None:
            fallback = min(
                ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
                key=lambda axis: abs(_dot3(axis, unit_normal)),
            )
            u_axis = projected_unit(fallback)
        if u_axis is None:
            raise ValueError("unable to establish an in-plane U direction")
        v_axis = _cross3(unit_normal, u_axis)
        return cls(origin, u_axis, v_axis, unit_normal)

    def local_to_world(self, point: Point2D) -> Point3D:
        """Map a local `(u, v)` point to model-space millimetres."""
        u, v = _point2(point, "local point")
        return (
            self.origin_mm[0] + self.u_axis[0] * u + self.v_axis[0] * v,
            self.origin_mm[1] + self.u_axis[1] * u + self.v_axis[1] * v,
            self.origin_mm[2] + self.u_axis[2] * u + self.v_axis[2] * v,
        )

    def world_to_local(self, point: Point3D) -> Point2D:
        """Project model-space millimetres into this work plane's local frame."""
        world = _point3(point, "world point")
        delta = (
            world[0] - self.origin_mm[0],
            world[1] - self.origin_mm[1],
            world[2] - self.origin_mm[2],
        )
        return (_dot3(delta, self.u_axis), _dot3(delta, self.v_axis))

    def to_mapping(self) -> dict[str, object]:
        """Return the strict JSON-compatible frame mapping."""
        return {
            "origin_mm": list(self.origin_mm),
            "u_axis": list(self.u_axis),
            "v_axis": list(self.v_axis),
            "normal": list(self.normal),
        }

    @classmethod
    def from_mapping(cls, value: object) -> WorkPlaneFrame:
        """Parse a strict frame mapping from command/archive data."""
        mapping = _strict_mapping(
            value,
            "work-plane frame",
            ("origin_mm", "u_axis", "v_axis", "normal"),
        )
        return cls(
            origin_mm=_point3(mapping["origin_mm"], "frame.origin_mm"),
            u_axis=_point3(mapping["u_axis"], "frame.u_axis"),
            v_axis=_point3(mapping["v_axis"], "frame.v_axis"),
            normal=_point3(mapping["normal"], "frame.normal"),
        )


@dataclass(frozen=True, slots=True)
class SketchSupportFace:
    """Replayable geometric anchor for a sketch attached to a planar model face."""

    center_mm: Point3D
    axis: AxisLiteral | None = None
    rank: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "center_mm", _point3(self.center_mm, "support face center"))
        if self.axis not in (None, "+X", "-X", "+Y", "-Y", "+Z", "-Z"):
            raise ValueError("support face axis must be a supported world axis")
        rank = cast("object", self.rank)
        if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int) or rank < 0):
            raise ValueError("support face rank must be a nonnegative integer")

    def to_mapping(self) -> dict[str, object]:
        """Return the existing face-selector anchor used by interactive modeling."""
        result: dict[str, object] = {"surface": "plane", "center_mm": list(self.center_mm)}
        if self.axis is not None:
            result["axis"] = self.axis
        if self.rank is not None:
            result["rank"] = self.rank
        return result

    @classmethod
    def from_mapping(cls, value: object) -> SketchSupportFace:
        """Parse a strict planar selector anchor from a picked face descriptor."""
        if not isinstance(value, Mapping):
            raise ValueError("support face must be a plane selector object")
        mapping = cast("Mapping[str, object]", value)
        required = {"surface", "center_mm"}
        allowed = required | {"axis", "rank"}
        if not required.issubset(mapping) or any(key not in allowed for key in mapping):
            raise ValueError("support face must contain surface, center_mm, and optional axis/rank")
        if mapping["surface"] != "plane":
            raise ValueError("sketch support must be a planar face")
        axis = mapping.get("axis")
        if axis is not None and (
            not isinstance(axis, str) or axis not in ("+X", "-X", "+Y", "-Y", "+Z", "-Z")
        ):
            raise ValueError("support face axis must be a supported world axis")
        rank = mapping.get("rank")
        if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int)):
            raise ValueError("support face rank must be a nonnegative integer")
        return cls(
            _point3(mapping["center_mm"], "support face center"),
            axis,
            rank,
        )


@dataclass(frozen=True, slots=True)
class LineEntity:
    """Finite line segment with a persistent sketch-local identity."""

    entity_id: str
    start_mm: Point2D
    end_mm: Point2D
    construction: bool = False
    layer_name: str = "0"

    def __post_init__(self) -> None:
        _validate_identity(self.entity_id, "entity_id")
        object.__setattr__(self, "start_mm", _point2(self.start_mm, "line start"))
        object.__setattr__(self, "end_mm", _point2(self.end_mm, "line end"))
        _boolean(self.construction, "construction")
        object.__setattr__(self, "layer_name", _entity_layer_name(self.layer_name))
        if self.start_mm == self.end_mm:
            raise ValueError("line endpoints must be distinct")


@dataclass(frozen=True, slots=True)
class PolylineEntity:
    """Connected line segments with an optional implicit closing segment."""

    entity_id: str
    points_mm: tuple[Point2D, ...]
    closed: bool = False
    construction: bool = False
    layer_name: str = "0"

    def __post_init__(self) -> None:
        _validate_identity(self.entity_id, "entity_id")
        points = tuple(_point2(point, "polyline point") for point in self.points_mm)
        object.__setattr__(self, "points_mm", points)
        _boolean(self.closed, "closed")
        _boolean(self.construction, "construction")
        object.__setattr__(self, "layer_name", _entity_layer_name(self.layer_name))
        minimum = 3 if self.closed else 2
        if len(points) < minimum:
            raise ValueError(f"polyline needs at least {minimum} distinct points")
        if self.closed and points[0] == points[-1]:
            raise ValueError(
                "closed polyline uses an implicit closing segment; omit repeated first point"
            )
        pairs = list(zip(points, points[1:], strict=False))
        if self.closed:
            pairs.append((points[-1], points[0]))
        if any(start == end for start, end in pairs):
            raise ValueError("polyline segments must have distinct endpoints")
        if self.closed:
            _validate_simple_closed_polyline(points)


@dataclass(frozen=True, slots=True)
class CircleEntity:
    """Circle in local sketch coordinates."""

    entity_id: str
    center_mm: Point2D
    radius_mm: float
    construction: bool = False
    layer_name: str = "0"

    def __post_init__(self) -> None:
        _validate_identity(self.entity_id, "entity_id")
        object.__setattr__(self, "center_mm", _point2(self.center_mm, "circle center"))
        object.__setattr__(self, "radius_mm", _finite_number(self.radius_mm, "circle radius"))
        _boolean(self.construction, "construction")
        object.__setattr__(self, "layer_name", _entity_layer_name(self.layer_name))
        if self.radius_mm <= _EPSILON:
            raise ValueError("circle radius must be positive")


@dataclass(frozen=True, slots=True)
class ArcEntity:
    """Circular arc; positive sweep is counterclockwise from the local +u axis."""

    entity_id: str
    center_mm: Point2D
    radius_mm: float
    start_angle_deg: float
    sweep_angle_deg: float
    construction: bool = False
    layer_name: str = "0"

    def __post_init__(self) -> None:
        _validate_identity(self.entity_id, "entity_id")
        object.__setattr__(self, "center_mm", _point2(self.center_mm, "arc center"))
        object.__setattr__(self, "radius_mm", _finite_number(self.radius_mm, "arc radius"))
        object.__setattr__(
            self, "start_angle_deg", _finite_number(self.start_angle_deg, "arc start angle")
        )
        object.__setattr__(
            self, "sweep_angle_deg", _finite_number(self.sweep_angle_deg, "arc sweep angle")
        )
        _boolean(self.construction, "construction")
        object.__setattr__(self, "layer_name", _entity_layer_name(self.layer_name))
        if self.radius_mm <= _EPSILON:
            raise ValueError("arc radius must be positive")
        if abs(self.sweep_angle_deg) <= _EPSILON or abs(self.sweep_angle_deg) >= 360.0:
            raise ValueError("arc sweep must be nonzero and less than 360 degrees")


@dataclass(frozen=True, slots=True)
class RectangleEntity:
    """Axis-aligned rectangle in local coordinates, defined by opposite corners."""

    entity_id: str
    first_corner_mm: Point2D
    opposite_corner_mm: Point2D
    construction: bool = False
    layer_name: str = "0"

    def __post_init__(self) -> None:
        _validate_identity(self.entity_id, "entity_id")
        object.__setattr__(
            self, "first_corner_mm", _point2(self.first_corner_mm, "rectangle first corner")
        )
        object.__setattr__(
            self,
            "opposite_corner_mm",
            _point2(self.opposite_corner_mm, "rectangle opposite corner"),
        )
        _boolean(self.construction, "construction")
        object.__setattr__(self, "layer_name", _entity_layer_name(self.layer_name))
        if (
            abs(self.first_corner_mm[0] - self.opposite_corner_mm[0]) <= _EPSILON
            or abs(self.first_corner_mm[1] - self.opposite_corner_mm[1]) <= _EPSILON
        ):
            raise ValueError("rectangle must have nonzero width and height")


@dataclass(frozen=True, slots=True)
class SplineEntity:
    """Open clamped uniform cubic B-spline, authored by control points.

    Neutral control data are authoritative; the UI samples de Boor evaluation,
    while the geometry adapter builds an exact OCCT B-spline from the same knots.
    """

    entity_id: str
    control_points_mm: tuple[Point2D, ...]
    construction: bool = False
    layer_name: str = "0"

    def __post_init__(self) -> None:
        _validate_identity(self.entity_id, "entity_id")
        points = tuple(_point2(point, "spline control point") for point in self.control_points_mm)
        if len(points) < 4:
            raise ValueError("三次样条曲线至少需要四个控制点。")
        if all(math.dist(points[0], point) <= _EPSILON for point in points[1:]):
            raise ValueError("样条控制点不能全部重合。")
        object.__setattr__(self, "control_points_mm", points)
        _boolean(self.construction, "construction")
        object.__setattr__(self, "layer_name", _entity_layer_name(self.layer_name))

    @property
    def knots(self) -> tuple[float, ...]:
        spans = len(self.control_points_mm) - 3
        return (0.0,) * 4 + tuple(index / spans for index in range(1, spans)) + (1.0,) * 4

    def point_at(self, parameter: float) -> Point2D:
        value = _finite_number(parameter, "spline parameter")
        if not 0.0 <= value <= 1.0:
            raise ValueError("spline parameter must be in [0, 1]")
        if value == 1.0:
            return self.control_points_mm[-1]
        knots = self.knots
        span = next(
            index
            for index in range(3, len(self.control_points_mm))
            if knots[index] <= value < knots[index + 1]
        )
        work = list(self.control_points_mm[span - 3 : span + 1])
        for level in range(1, 4):
            for index in range(3, level - 1, -1):
                knot_index = span - 3 + index
                alpha = (value - knots[knot_index]) / (
                    knots[knot_index + 4 - level] - knots[knot_index]
                )
                left, right = work[index - 1], work[index]
                work[index] = (
                    (1 - alpha) * left[0] + alpha * right[0],
                    (1 - alpha) * left[1] + alpha * right[1],
                )
        return work[3]

    def sampled_points(self) -> tuple[Point2D, ...]:
        segments = max(48, (len(self.control_points_mm) - 3) * 24)
        return tuple(self.point_at(index / segments) for index in range(segments + 1))


type SketchEntity = (
    LineEntity | PolylineEntity | CircleEntity | ArcEntity | RectangleEntity | SplineEntity
)


def _entity_to_mapping(entity: SketchEntity) -> dict[str, object]:
    common: dict[str, object] = {
        "entity_id": entity.entity_id,
        "construction": entity.construction,
        "layer_name": entity.layer_name,
    }
    if isinstance(entity, SplineEntity):
        return {
            **common,
            "kind": "spline",
            "control_points_mm": [list(point) for point in entity.control_points_mm],
        }
    if isinstance(entity, LineEntity):
        return {
            **common,
            "kind": "line",
            "start_mm": list(entity.start_mm),
            "end_mm": list(entity.end_mm),
        }
    if isinstance(entity, PolylineEntity):
        return {
            **common,
            "kind": "polyline",
            "points_mm": [list(point) for point in entity.points_mm],
            "closed": entity.closed,
        }
    if isinstance(entity, CircleEntity):
        return {
            **common,
            "kind": "circle",
            "center_mm": list(entity.center_mm),
            "radius_mm": entity.radius_mm,
        }
    if isinstance(entity, ArcEntity):
        return {
            **common,
            "kind": "arc",
            "center_mm": list(entity.center_mm),
            "radius_mm": entity.radius_mm,
            "start_angle_deg": entity.start_angle_deg,
            "sweep_angle_deg": entity.sweep_angle_deg,
        }
    return {
        **common,
        "kind": "rectangle",
        "first_corner_mm": list(entity.first_corner_mm),
        "opposite_corner_mm": list(entity.opposite_corner_mm),
    }


def _entity_from_mapping(value: object, *, require_layer: bool) -> SketchEntity:
    if not isinstance(value, Mapping):
        raise ValueError("sketch entity must be an object")
    mapping = cast("Mapping[str, object]", value)
    kind = mapping.get("kind")
    common = ("entity_id", "kind", "construction")
    layer_name = mapping.get("layer_name", "0")
    entity_common = (*common, "layer_name") if require_layer else common
    if kind == "spline":
        data = _strict_mapping(mapping, "spline entity", (*entity_common, "control_points_mm"))
        raw_points = data["control_points_mm"]
        if not isinstance(raw_points, (list, tuple)):
            raise ValueError("spline.control_points_mm must be an array")
        return SplineEntity(
            cast("str", data["entity_id"]),
            tuple(
                _point2(point, "spline control point")
                for point in cast("Sequence[object]", raw_points)
            ),
            _boolean(data["construction"], "construction"),
            _entity_layer_name(layer_name),
        )
    if kind == "line":
        data = _strict_mapping(mapping, "line entity", (*entity_common, "start_mm", "end_mm"))
        return LineEntity(
            cast("str", data["entity_id"]),
            _point2(data["start_mm"], "line.start_mm"),
            _point2(data["end_mm"], "line.end_mm"),
            _boolean(data["construction"], "construction"),
            _entity_layer_name(layer_name),
        )
    if kind == "polyline":
        data = _strict_mapping(mapping, "polyline entity", (*entity_common, "points_mm", "closed"))
        raw_points = data["points_mm"]
        if not isinstance(raw_points, (list, tuple)):
            raise ValueError("polyline.points_mm must be an array")
        points = tuple(
            _point2(point, f"polyline.points_mm[{index}]")
            for index, point in enumerate(cast("Sequence[object]", raw_points))
        )
        return PolylineEntity(
            cast("str", data["entity_id"]),
            points,
            _boolean(data["closed"], "closed"),
            _boolean(data["construction"], "construction"),
            _entity_layer_name(layer_name),
        )
    if kind == "circle":
        data = _strict_mapping(mapping, "circle entity", (*entity_common, "center_mm", "radius_mm"))
        return CircleEntity(
            cast("str", data["entity_id"]),
            _point2(data["center_mm"], "circle.center_mm"),
            _finite_number(data["radius_mm"], "circle.radius_mm"),
            _boolean(data["construction"], "construction"),
            _entity_layer_name(layer_name),
        )
    if kind == "arc":
        data = _strict_mapping(
            mapping,
            "arc entity",
            (*entity_common, "center_mm", "radius_mm", "start_angle_deg", "sweep_angle_deg"),
        )
        return ArcEntity(
            cast("str", data["entity_id"]),
            _point2(data["center_mm"], "arc.center_mm"),
            _finite_number(data["radius_mm"], "arc.radius_mm"),
            _finite_number(data["start_angle_deg"], "arc.start_angle_deg"),
            _finite_number(data["sweep_angle_deg"], "arc.sweep_angle_deg"),
            _boolean(data["construction"], "construction"),
            _entity_layer_name(layer_name),
        )
    if kind == "rectangle":
        data = _strict_mapping(
            mapping,
            "rectangle entity",
            (*entity_common, "first_corner_mm", "opposite_corner_mm"),
        )
        return RectangleEntity(
            cast("str", data["entity_id"]),
            _point2(data["first_corner_mm"], "rectangle.first_corner_mm"),
            _point2(data["opposite_corner_mm"], "rectangle.opposite_corner_mm"),
            _boolean(data["construction"], "construction"),
            _entity_layer_name(layer_name),
        )
    raise ValueError(f"unsupported geometry kind {kind!r}")


@dataclass(frozen=True, slots=True)
class Sketch:
    """Replayable neutral sketch state built from persistent 2D entities."""

    sketch_id: str
    frame: WorkPlaneFrame
    entities: tuple[SketchEntity, ...]
    constraints: tuple[SketchConstraint, ...] = ()
    layers: SketchLayerTable = SketchLayerTable()
    support_face: SketchSupportFace | None = None

    def __post_init__(self) -> None:
        _validate_identity(self.sketch_id, "sketch_id")
        if not isinstance(cast("object", self.frame), WorkPlaneFrame):
            raise ValueError("sketch frame must be a WorkPlaneFrame")
        if not isinstance(cast("object", self.layers), SketchLayerTable):
            raise ValueError("sketch layers must use the neutral layer-table DTO")
        if self.support_face is not None and not isinstance(
            cast("object", self.support_face), SketchSupportFace
        ):
            raise ValueError("sketch support face must use the neutral planar-face DTO")
        entities = tuple(self.entities)
        if any(
            not isinstance(
                cast("object", entity),
                (
                    LineEntity,
                    PolylineEntity,
                    CircleEntity,
                    ArcEntity,
                    RectangleEntity,
                    SplineEntity,
                ),
            )
            for entity in entities
        ):
            raise ValueError("sketch entities must use a supported geometry type")
        identities = tuple(entity.entity_id for entity in entities)
        if len(identities) != len(set(identities)):
            raise ValueError("entity identities must be unique within a sketch")
        layer_names = {layer.name.casefold() for layer in self.layers.layers}
        missing_layers = tuple(
            sorted(
                {
                    entity.layer_name
                    for entity in entities
                    if entity.layer_name.casefold() not in layer_names
                },
                key=str.casefold,
            )
        )
        if missing_layers:
            raise ValueError(f"sketch geometry references missing layer(s) {missing_layers}")
        object.__setattr__(self, "entities", entities)
        constraints = tuple(self.constraints)
        if any(
            not isinstance(cast("object", constraint), SketchConstraint)
            for constraint in constraints
        ):
            raise ValueError("sketch constraints must use the neutral constraint DTO")
        constraint_ids = tuple(constraint.constraint_id for constraint in constraints)
        if len(constraint_ids) != len(set(constraint_ids)):
            raise ValueError("constraint identities must be unique within a sketch")
        layers = self.layers
        for constraint in constraints:
            if constraint.layer_name is None:
                continue
            try:
                layers.get(constraint.layer_name)
            except KeyError as exc:
                if constraint.layer_name.casefold() != "dim":
                    raise ValueError("dimension references a missing annotation layer") from exc
                layers = layers.add(DEFAULT_DIM_LAYER)
        object.__setattr__(self, "layers", layers)
        object.__setattr__(self, "constraints", constraints)

    def to_mapping(self, *, version: int = 2) -> dict[str, object]:
        """Return JSON-compatible command values in the requested schema version."""
        if version not in (1, 2, 3):
            raise ValueError(f"unsupported sketch mapping version {version}")
        if version < 3 and any(isinstance(entity, SplineEntity) for entity in self.entities):
            raise ValueError("spline sketches require mapping version 3")
        entities = [_entity_to_mapping(entity) for entity in self.entities]
        if version == 1:
            if self.support_face is not None:
                raise ValueError("face-attached sketch cannot be represented by mapping version 1")
            if self.constraints:
                raise ValueError("dimensioned sketch cannot be represented by mapping version 1")
            if self.layers != SketchLayerTable() or any(
                entity.layer_name != "0" for entity in self.entities
            ):
                raise ValueError("layered sketch cannot be represented by mapping version 1")
            for entity in entities:
                entity.pop("layer_name")
            return {
                "sketch_id": self.sketch_id,
                "frame": self.frame.to_mapping(),
                "entities": entities,
            }
        result: dict[str, object] = {
            "sketch_id": self.sketch_id,
            "frame": self.frame.to_mapping(),
            "layers": self.layers.to_mapping(),
            "entities": entities,
        }
        if self.constraints and version == 2:
            raise ValueError("dimensioned sketch cannot be represented by mapping version 2")
        if self.support_face is not None:
            result["support_face"] = self.support_face.to_mapping()
        if version == 3:
            result["constraints"] = [constraint.to_mapping() for constraint in self.constraints]
        return result

    def to_state_mapping(self) -> dict[str, object]:
        """Return canonical sketch state, including durable constraint records."""
        return {
            **self.to_mapping(version=3),
        }

    def state_digest(self) -> str:
        """Hash the complete accepted state for stale-preview detection."""
        encoded = json.dumps(
            self.to_state_mapping(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def with_constraint(
        self,
        constraint: SketchConstraint,
        entities: tuple[SketchEntity, ...],
    ) -> Sketch:
        """Return a new immutable sketch state with one constraint and its solved geometry."""
        if any(item.constraint_id == constraint.constraint_id for item in self.constraints):
            raise ValueError(f"constraint identity {constraint.constraint_id!r} already exists")
        return Sketch(
            self.sketch_id,
            self.frame,
            entities,
            (*self.constraints, constraint),
            self.layers,
            self.support_face,
        )

    def with_updated_constraint(
        self, constraint: SketchConstraint, entities: tuple[SketchEntity, ...]
    ) -> Sketch:
        """Revise a dimension without retargeting it or rewriting other relations."""
        original = next(
            (item for item in self.constraints if item.constraint_id == constraint.constraint_id),
            None,
        )
        if original is None:
            raise ValueError("cannot update a missing sketch dimension")
        if original.kind not in ("length", "distance", "angle", "radius", "diameter", "arc_length"):
            raise ValueError("only an existing dimension can be revised")
        if (constraint.kind, constraint.references, constraint.source) != (
            original.kind,
            original.references,
            original.source,
        ):
            raise ValueError("dimension revision must preserve kind, references and source")
        return Sketch(
            self.sketch_id,
            self.frame,
            entities,
            tuple(
                constraint if item.constraint_id == constraint.constraint_id else item
                for item in self.constraints
            ),
            self.layers,
            self.support_face,
        )

    @classmethod
    def from_mapping(cls, value: object) -> Sketch:
        """Parse strict v1 or layered v2 sketch command values."""
        if not isinstance(value, Mapping):
            raise ValueError("sketch must be an object")
        raw_mapping = cast("Mapping[str, object]", value)
        has_layers = "layers" in raw_mapping
        required_keys: set[str] = (
            {"sketch_id", "frame", "entities", "layers"}
            if has_layers
            else {"sketch_id", "frame", "entities"}
        )
        allowed_keys = set(required_keys)
        if has_layers:
            allowed_keys.add("support_face")
        if has_layers:
            allowed_keys.add("constraints")
        unknown = tuple(key for key in raw_mapping if key not in allowed_keys)
        missing = tuple(key for key in required_keys if key not in raw_mapping)
        if unknown or missing:
            raise ValueError(f"sketch has unknown fields {unknown} or missing fields {missing}")
        mapping = raw_mapping
        raw_entities = mapping["entities"]
        if not isinstance(raw_entities, (list, tuple)):
            raise ValueError("entities must be an array")
        entities = tuple(
            _entity_from_mapping(entity, require_layer=has_layers)
            for entity in cast("Sequence[object]", raw_entities)
        )
        sketch_id = mapping["sketch_id"]
        if not isinstance(sketch_id, str):
            raise ValueError("sketch ID must be a canonical UUID")
        layers = (
            SketchLayerTable.from_mapping(mapping["layers"]) if has_layers else SketchLayerTable()
        )
        support_face = (
            SketchSupportFace.from_mapping(mapping["support_face"])
            if "support_face" in mapping
            else None
        )
        raw_constraints = raw_mapping.get("constraints", ())
        if not isinstance(raw_constraints, Sequence) or isinstance(raw_constraints, str | bytes):
            raise ValueError("constraints must be an array")
        constraints = tuple(
            SketchConstraint.from_mapping(item)
            for item in cast("Sequence[object]", raw_constraints)
        )
        entity_ids = {entity.entity_id for entity in entities}
        if any(
            reference.entity_id not in entity_ids
            for constraint in constraints
            for reference in constraint.references
        ):
            raise ValueError("constraints must reference geometry in the same sketch")
        return cls(
            sketch_id,
            WorkPlaneFrame.from_mapping(mapping["frame"]),
            entities,
            constraints=constraints,
            layers=layers,
            support_face=support_face,
        )
