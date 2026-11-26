# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent reference dimensions imported without geometry association."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from mycad.core.dimension_tolerance import DimensionTolerance


def _finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("dimension values must be finite")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError("dimension values must be finite") from exc
    if not math.isfinite(result):
        raise ValueError("dimension values must be finite")
    return result


def _point(value: object) -> tuple[float, float]:
    if not isinstance(value, list | tuple):
        raise ValueError("dimension point must contain two coordinates")
    values = cast("Sequence[object]", value)
    if len(values) != 2:
        raise ValueError("dimension point must contain two coordinates")
    result: list[float] = []
    for item in values:
        result.append(_finite(item))
    return result[0], result[1]


@dataclass(frozen=True, slots=True)
class DetachedDimension:
    """A reference-only dimension, independent of sketch geometry."""

    dimension_id: str
    kind: str
    first_mm: tuple[float, float]
    second_mm: tuple[float, float]
    location_mm: tuple[float, float]
    angle_deg: float
    nominal: float
    tolerance: DimensionTolerance = DimensionTolerance()
    layer_name: str = "0"
    precision: int = 2
    linear_factor: float = 1.0
    text_override: str = ""
    vertex_mm: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        try:
            parsed = UUID(self.dimension_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("dimension ID must be a UUID") from exc
        if self.dimension_id not in (parsed.hex, str(parsed)):
            raise ValueError("dimension ID must be canonical")
        if self.kind not in (
            "rotated",
            "aligned",
            "radius",
            "diameter",
            "angular_3p",
            "angular_2l",
            "ordinate_x",
            "ordinate_y",
        ):
            raise ValueError("unsupported detached dimension")
        for name in ("first_mm", "second_mm", "location_mm"):
            object.__setattr__(self, name, _point(getattr(self, name)))
        for name in ("angle_deg", "nominal", "linear_factor"):
            object.__setattr__(self, name, _finite(getattr(self, name)))
        if (
            self.nominal < 0 and self.kind not in ("ordinate_x", "ordinate_y")
        ) or self.linear_factor <= 0:
            raise ValueError("invalid dimension measurement or scale")
        dx = self.second_mm[0] - self.first_mm[0]
        dy = self.second_mm[1] - self.first_mm[1]
        if self.kind in ("angular_3p", "angular_2l"):
            if self.vertex_mm is None or self.linear_factor != 1 or self.angle_deg != 0:
                raise ValueError(
                    "angular dimension requires a vertex, unit scale and no linear angle"
                )
            vertex = _point(self.vertex_mm)
            object.__setattr__(self, "vertex_mm", vertex)
            if math.dist(vertex, self.location_mm) <= 1e-12:
                raise ValueError("angular dimension location must differ from its vertex")
            first = (self.first_mm[0] - vertex[0], self.first_mm[1] - vertex[1])
            second = (self.second_mm[0] - vertex[0], self.second_mm[1] - vertex[1])
            if math.hypot(*first) <= 1e-12 or math.hypot(*second) <= 1e-12:
                raise ValueError("angular dimension rays must be nonzero")
            cross = first[0] * second[1] - first[1] * second[0]
            dot = first[0] * second[0] + first[1] * second[1]
            measured = math.degrees(math.atan2(cross, dot)) % 360
            straight = abs(measured - 180) <= 1e-9
            if not 1e-9 < measured < 360 - 1e-9 or (straight and self.kind == "angular_2l"):
                raise ValueError("angular dimension rays must be nonparallel")
            if straight:
                placement = (self.location_mm[0] - vertex[0], self.location_mm[1] - vertex[1])
                if first[0] * placement[1] - first[1] * placement[0] <= 1e-12:
                    raise ValueError("straight angle semicircle must match the location")
        elif self.vertex_mm is not None:
            raise ValueError("vertex applies only to angular dimensions")
        elif self.kind in ("ordinate_x", "ordinate_y"):
            angle = math.radians(self.angle_deg)
            cosine, sine = math.cos(angle), math.sin(angle)
            measured = (
                dx * cosine + dy * sine if self.kind == "ordinate_x" else -dx * sine + dy * cosine
            ) * self.linear_factor
        elif self.kind in ("radius", "diameter"):
            measured = math.hypot(dx, dy) * self.linear_factor
            if math.hypot(dx, dy) <= 1e-12:
                raise ValueError("radial dimension definition points must be distinct")
        else:
            radians = math.atan2(dy, dx) if self.kind == "aligned" else math.radians(self.angle_deg)
            measured = abs(dx * math.cos(radians) + dy * math.sin(radians)) * self.linear_factor
        if not math.isfinite(measured) or not math.isclose(
            measured, self.nominal, rel_tol=1e-9, abs_tol=1e-7
        ):
            raise ValueError("nominal value does not match the definition points and factor")
        if not isinstance(cast("object", self.tolerance), DimensionTolerance):
            raise ValueError("invalid tolerance")
        if (
            isinstance(cast("object", self.precision), bool)
            or not isinstance(cast("object", self.precision), int)
            or not 0 <= self.precision <= 8
        ):
            raise ValueError("invalid precision")
        if (
            not isinstance(cast("object", self.layer_name), str)
            or not self.layer_name
            or not self.layer_name.isprintable()
        ):
            raise ValueError("invalid layer")
        if not isinstance(cast("object", self.text_override), str) or len(self.text_override) > 512:
            raise ValueError("invalid dimension text")

    def to_mapping(self) -> dict[str, object]:
        result: dict[str, object] = {
            "dimension_id": self.dimension_id,
            "kind": self.kind,
            "first_mm": list(self.first_mm),
            "second_mm": list(self.second_mm),
            "location_mm": list(self.location_mm),
            "angle_deg": self.angle_deg,
            "nominal": self.nominal,
            "tolerance": self.tolerance.to_mapping(),
            "layer_name": self.layer_name,
            "precision": self.precision,
            "linear_factor": self.linear_factor,
            "text_override": self.text_override,
        }
        if self.vertex_mm is not None:
            result["vertex_mm"] = list(self.vertex_mm)
        return result

    @classmethod
    def from_mapping(cls, value: object) -> DetachedDimension:
        if not isinstance(value, Mapping):
            raise ValueError("dimension must be an object")
        data = cast("Mapping[str, object]", value)
        required = {
            "dimension_id",
            "kind",
            "first_mm",
            "second_mm",
            "location_mm",
            "angle_deg",
            "nominal",
            "tolerance",
            "layer_name",
            "precision",
            "linear_factor",
            "text_override",
        }
        if not required.issubset(data) or set(data) - required - {"vertex_mm"}:
            raise ValueError("dimension must contain its known fields")
        return cls(
            cast("str", data["dimension_id"]),
            cast("str", data["kind"]),
            _point(data["first_mm"]),
            _point(data["second_mm"]),
            _point(data["location_mm"]),
            cast("float", data["angle_deg"]),
            cast("float", data["nominal"]),
            DimensionTolerance.from_mapping(data["tolerance"]),
            cast("str", data["layer_name"]),
            cast("int", data["precision"]),
            cast("float", data["linear_factor"]),
            cast("str", data["text_override"]),
            _point(data["vertex_mm"]) if "vertex_mm" in data else None,
        )
