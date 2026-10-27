# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Parametric cross-section profiles (Phase 0, T5).

Frozen dataclasses built from standard-library types only: the parsed,
neutral form of the ``Profile`` wire descriptor (plan appendix A.0)
consumed by ``feature.extrude`` / ``feature.revolve``. Sections live on
the XY work plane at z=0; rotated datum-plane descriptions are a Phase 1
evolution (reserved in the plan, deliberately not implemented here).
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from mycad.core.exceptions import ValidationError
from mycad.core.sketch import WorkPlaneFrame


@dataclass(frozen=True)
class Profile(ABC):
    """Abstract base of the sealed Phase 0 profile set (XY plane, z=0)."""

    @abstractmethod
    def area(self) -> float:
        """Cross-section area (mm²) — the shared contract of the sealed set."""


@dataclass(frozen=True)
class CircleProfile(Profile):
    """Circular section: ``radius`` around ``center`` (default origin)."""

    radius: float
    center: tuple[float, float] = (0.0, 0.0)

    def area(self) -> float:
        """``π r²``."""

        return math.pi * self.radius * self.radius


@dataclass(frozen=True)
class RectProfile(Profile):
    """Rectangular section: ``width`` along X, ``height`` along Y."""

    width: float
    height: float
    center: tuple[float, float] = (0.0, 0.0)

    def area(self) -> float:
        """``width × height``."""

        return self.width * self.height


def _finite_coordinates(value: tuple[float, ...], size: int, name: str) -> None:
    if len(value) != size or any(
        isinstance(cast("object", component), bool) or not math.isfinite(component)
        for component in value
    ):
        raise ValueError(f"{name} must contain {size} finite coordinates")


@dataclass(frozen=True, slots=True)
class WireContour:
    """Closed, simple polygonal 2D profile contour; holes are labeled explicitly."""

    vertices_mm: tuple[tuple[float, float], ...]
    is_hole: bool = False
    closed: bool = True

    def __post_init__(self) -> None:
        if not self.closed:
            raise ValueError("profile contour must be closed")
        if len(self.vertices_mm) < 3:
            raise ValueError("profile contour needs at least three vertices")
        for vertex in self.vertices_mm:
            _finite_coordinates(vertex, 2, "profile vertex")
        if abs(self.signed_area_mm2) <= 1e-12:
            raise ValueError("profile contour must enclose a nonzero area")
        if self.is_hole and self.signed_area_mm2 >= 0.0:
            raise ValueError("hole contour must use clockwise winding")
        if not self.is_hole and self.signed_area_mm2 <= 0.0:
            raise ValueError("outer contour must use counterclockwise winding")

    @property
    def signed_area_mm2(self) -> float:
        return 0.5 * sum(
            first[0] * second[1] - second[0] * first[1]
            for first, second in zip(
                self.vertices_mm,
                (*self.vertices_mm[1:], self.vertices_mm[0]),
                strict=True,
            )
        )


@dataclass(frozen=True, slots=True)
class ConstructionSegment2D:
    """Open construction geometry in local sketch coordinates."""

    start_mm: tuple[float, float]
    end_mm: tuple[float, float]

    def __post_init__(self) -> None:
        _finite_coordinates(self.start_mm, 2, "construction segment start")
        _finite_coordinates(self.end_mm, 2, "construction segment end")
        if self.start_mm == self.end_mm:
            raise ValueError("construction segment endpoints must differ")


DimensionKind = Literal["driving", "reference"]


@dataclass(frozen=True, slots=True)
class DimensionLabel:
    """Prototype dimension label; kind distinguishes solver input from display-only data."""

    name: str
    value: float
    unit: Literal["mm", "deg"]
    kind: DimensionKind

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("dimension name must not be empty")
        if not math.isfinite(self.value):
            raise ValueError("dimension value must be finite")
        if self.unit not in ("mm", "deg"):
            raise ValueError("dimension unit must be 'mm' or 'deg'")
        if self.kind not in ("driving", "reference"):
            raise ValueError("dimension kind must be 'driving' or 'reference'")


@dataclass(frozen=True, slots=True)
class ProfileSketch:
    """Neutral 2D sketch values, distinct from the 3D model's profile DTOs."""

    frame: WorkPlaneFrame
    contours: tuple[WireContour, ...]
    construction_geometry: tuple[ConstructionSegment2D, ...] = ()
    dimensions: tuple[DimensionLabel, ...] = ()

    def __post_init__(self) -> None:
        if not self.contours or not any(not contour.is_hole for contour in self.contours):
            raise ValueError("profile sketch requires at least one outer contour")
        outer_contours = tuple(contour for contour in self.contours if not contour.is_hole)
        for hole in (contour for contour in self.contours if contour.is_hole):
            if not any(_contour_is_strictly_inside(hole, outer) for outer in outer_contours):
                raise ValueError("hole contour must lie inside an outer contour")

    def to_mapping(self) -> dict[str, object]:
        """Return JSON-compatible prototype values; this is not the v1 archive schema."""

        return {
            "frame": {
                "origin_mm": list(self.frame.origin_mm),
                "u_axis": list(self.frame.u_axis),
                "v_axis": list(self.frame.v_axis),
                "normal": list(self.frame.normal),
            },
            "contours": [
                {
                    "vertices_mm": [list(vertex) for vertex in contour.vertices_mm],
                    "is_hole": contour.is_hole,
                    "closed": contour.closed,
                }
                for contour in self.contours
            ],
            "construction_geometry": [
                {"start_mm": list(segment.start_mm), "end_mm": list(segment.end_mm)}
                for segment in self.construction_geometry
            ],
            "dimensions": [
                {"name": item.name, "value": item.value, "unit": item.unit, "kind": item.kind}
                for item in self.dimensions
            ],
        }

    @classmethod
    def from_mapping(cls, value: object) -> ProfileSketch:
        """Parse a JSON-compatible prototype record with strict value checks."""

        record = _require_mapping(value, "profile sketch")
        frame_data = _require_mapping(record.get("frame"), "profile sketch frame")
        frame = WorkPlaneFrame(
            origin_mm=_read_vector3(frame_data.get("origin_mm"), "frame.origin_mm"),
            u_axis=_read_vector3(frame_data.get("u_axis"), "frame.u_axis"),
            v_axis=_read_vector3(frame_data.get("v_axis"), "frame.v_axis"),
            normal=_read_vector3(frame_data.get("normal"), "frame.normal"),
        )
        contours_raw = _require_sequence(record.get("contours"), "profile sketch contours")
        contours: list[WireContour] = []
        for index, entry in enumerate(contours_raw):
            item = _require_mapping(entry, f"contours[{index}]")
            vertices_raw = _require_sequence(
                item.get("vertices_mm"), f"contours[{index}].vertices_mm"
            )
            vertices = tuple(
                _read_vector2(vertex, f"contours[{index}].vertices_mm[{vertex_index}]")
                for vertex_index, vertex in enumerate(vertices_raw)
            )
            is_hole = item.get("is_hole", False)
            closed = item.get("closed", True)
            if not isinstance(is_hole, bool) or not isinstance(closed, bool):
                raise ValueError(f"contours[{index}] flags must be booleans")
            contours.append(WireContour(vertices, is_hole, closed))
        construction_raw = _require_sequence(
            record.get("construction_geometry", []), "profile sketch construction_geometry"
        )
        construction: list[ConstructionSegment2D] = []
        for index, entry in enumerate(construction_raw):
            item = _require_mapping(entry, f"construction_geometry[{index}]")
            construction.append(
                ConstructionSegment2D(
                    _read_vector2(item.get("start_mm"), f"construction_geometry[{index}].start_mm"),
                    _read_vector2(item.get("end_mm"), f"construction_geometry[{index}].end_mm"),
                )
            )
        dimensions_raw = _require_sequence(
            record.get("dimensions", []), "profile sketch dimensions"
        )
        dimensions: list[DimensionLabel] = []
        for index, entry in enumerate(dimensions_raw):
            item = _require_mapping(entry, f"dimensions[{index}]")
            name = item.get("name")
            dimension_value = item.get("value")
            unit = item.get("unit")
            kind = item.get("kind")
            if (
                not isinstance(name, str)
                or isinstance(dimension_value, bool)
                or not isinstance(dimension_value, int | float)
                or unit not in ("mm", "deg")
                or kind not in ("driving", "reference")
            ):
                raise ValueError(f"dimensions[{index}] is malformed")
            dimensions.append(
                DimensionLabel(
                    name,
                    float(dimension_value),
                    unit,
                    kind,
                )
            )
        return cls(frame, tuple(contours), tuple(construction), tuple(dimensions))


def _contains_point(polygon: tuple[tuple[float, float], ...], point: tuple[float, float]) -> bool:
    x, y = point
    if any(
        _point_on_segment(point, first, second)
        for first, second in zip(polygon, (*polygon[1:], polygon[0]), strict=True)
    ):
        return False
    inside = False
    for first, second in zip(polygon, (*polygon[1:], polygon[0]), strict=True):
        x1, y1 = first
        x2, y2 = second
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _point_on_segment(
    point: tuple[float, float], first: tuple[float, float], second: tuple[float, float]
) -> bool:
    dx = second[0] - first[0]
    dy = second[1] - first[1]
    length = math.hypot(dx, dy)
    tolerance = 1e-9 * max(1.0, length)
    cross = dx * (point[1] - first[1]) - dy * (point[0] - first[0])
    if abs(cross) > tolerance:
        return False
    return (
        min(first[0], second[0]) - 1e-9 <= point[0] <= max(first[0], second[0]) + 1e-9
        and min(first[1], second[1]) - 1e-9 <= point[1] <= max(first[1], second[1]) + 1e-9
    )


def _segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    def orientation(
        start: tuple[float, float], end: tuple[float, float], point: tuple[float, float]
    ) -> float:
        return (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (
            point[0] - start[0]
        )

    first_side = orientation(first_start, first_end, second_start)
    second_side = orientation(first_start, first_end, second_end)
    third_side = orientation(second_start, second_end, first_start)
    fourth_side = orientation(second_start, second_end, first_end)
    if (first_side > 0 > second_side or first_side < 0 < second_side) and (
        third_side > 0 > fourth_side or third_side < 0 < fourth_side
    ):
        return True
    return (
        (first_side == 0 and _point_on_segment(second_start, first_start, first_end))
        or (second_side == 0 and _point_on_segment(second_end, first_start, first_end))
        or (third_side == 0 and _point_on_segment(first_start, second_start, second_end))
        or (fourth_side == 0 and _point_on_segment(first_end, second_start, second_end))
    )


def _contour_is_strictly_inside(hole: WireContour, outer: WireContour) -> bool:
    if not all(_contains_point(outer.vertices_mm, vertex) for vertex in hole.vertices_mm):
        return False
    outer_edges = tuple(
        zip(outer.vertices_mm, (*outer.vertices_mm[1:], outer.vertices_mm[0]), strict=True)
    )
    hole_edges = tuple(
        zip(hole.vertices_mm, (*hole.vertices_mm[1:], hole.vertices_mm[0]), strict=True)
    )
    return not any(
        _segments_intersect(hole_start, hole_end, outer_start, outer_end)
        for hole_start, hole_end in hole_edges
        for outer_start, outer_end in outer_edges
    )


def _require_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return cast("Mapping[str, object]", value)


def _require_sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"{name} must be a sequence")
    return cast("Sequence[object]", value)


def _read_vector(value: object, size: int, name: str) -> tuple[float, ...]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"{name} must contain {size} finite coordinates")
    entries = cast("Sequence[object]", value)
    if len(entries) != size:
        raise ValueError(f"{name} must contain {size} finite coordinates")
    result_values: list[float] = []
    for component in entries:
        if isinstance(component, bool) or not isinstance(component, int | float):
            raise ValueError(f"{name} must contain {size} finite coordinates")
        result_values.append(float(component))
    result = tuple(result_values)
    _finite_coordinates(result, size, name)
    return result


def _read_vector2(value: object, name: str) -> tuple[float, float]:
    components = _read_vector(value, 2, name)
    return components[0], components[1]


def _read_vector3(value: object, name: str) -> tuple[float, float, float]:
    components = _read_vector(value, 3, name)
    return components[0], components[1], components[2]


__all__ = [
    "CircleProfile",
    "ConstructionSegment2D",
    "DimensionLabel",
    "Profile",
    "ProfileSketch",
    "RectProfile",
    "WireContour",
    "WorkPlaneFrame",
]


def _positive_number(value: object, key: str, command_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"{command_id}: profile {key!r} must be a number, got {value!r}"
        raise ValidationError(message=msg, command_id=command_id)
    if not math.isfinite(value) or value <= 0:
        msg = f"{command_id}: profile {key!r} must be a positive finite number, got {value!r}"
        raise ValidationError(message=msg, command_id=command_id)
    return float(value)


def _center2(value: object, command_id: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)):
        msg = f"{command_id}: profile 'center' must be a 2-number sequence"
        raise ValidationError(message=msg, command_id=command_id)
    entries = cast("Sequence[object]", value)
    if len(entries) != 2:
        msg = f"{command_id}: profile 'center' must be a 2-number sequence"
        raise ValidationError(message=msg, command_id=command_id)
    coords: list[float] = []
    for item in entries:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            msg = f"{command_id}: profile 'center' must contain only numbers"
            raise ValidationError(message=msg, command_id=command_id)
        coords.append(float(item))
    return (coords[0], coords[1])


def profile_from_mapping(value: object, command_id: str) -> Profile:
    """Parse the wire ``Profile`` descriptor (appendix A.0) into a dataclass."""

    if not isinstance(value, Mapping):
        msg = f"{command_id}: 'profile' must be a mapping, got {type(value).__name__}"
        raise ValidationError(message=msg, command_id=command_id)
    params = cast("Mapping[str, object]", value)
    ptype = params.get("type")
    if ptype == "circle":
        unknown = sorted(set(params) - {"type", "radius", "center"})
        if unknown:
            msg = f"{command_id}: profile unknown parameter(s) {unknown}"
            raise ValidationError(message=msg, command_id=command_id)
        if "radius" not in params:
            msg = f"{command_id}: profile missing required parameter 'radius'"
            raise ValidationError(message=msg, command_id=command_id)
        center = _center2(params["center"], command_id) if "center" in params else (0.0, 0.0)
        return CircleProfile(
            radius=_positive_number(params["radius"], "radius", command_id), center=center
        )
    if ptype == "rect":
        unknown = sorted(set(params) - {"type", "width", "height", "center"})
        if unknown:
            msg = f"{command_id}: profile unknown parameter(s) {unknown}"
            raise ValidationError(message=msg, command_id=command_id)
        for key in ("width", "height"):
            if key not in params:
                msg = f"{command_id}: profile missing required parameter {key!r}"
                raise ValidationError(message=msg, command_id=command_id)
        center = _center2(params["center"], command_id) if "center" in params else (0.0, 0.0)
        return RectProfile(
            width=_positive_number(params["width"], "width", command_id),
            height=_positive_number(params["height"], "height", command_id),
            center=center,
        )
    msg = f"{command_id}: profile 'type' must be 'circle' or 'rect', got {ptype!r}"
    raise ValidationError(message=msg, command_id=command_id)
