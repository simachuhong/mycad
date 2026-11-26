# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Exact, sketch-local surface extension geometry for finite lines and arcs."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from mycad.core.sketch import ArcEntity, LineEntity, Point2D


@dataclass(frozen=True, slots=True)
class SurfaceExtensionSpec:
    side: Literal["start", "end"]
    distance_mm: float
    offset_mm: float
    overshoot_mm: float

    def __post_init__(self) -> None:
        values: list[float] = []
        for raw in (self.distance_mm, self.offset_mm, self.overshoot_mm):
            if isinstance(raw, bool) or not isinstance(cast("object", raw), int | float):
                raise ValueError("invalid surface extension distances")
            try:
                values.append(float(raw))
            except OverflowError as exc:
                raise ValueError("invalid surface extension distances") from exc
        if (
            self.side not in ("start", "end")
            or any(not math.isfinite(v) for v in values)
            or values[0] <= 0
            or values[1] < 0
            or values[2] < 0
            or values[1] >= values[0] + values[2]
            or not math.isfinite(values[0] + values[2])
        ):
            raise ValueError("invalid surface extension distances")
        object.__setattr__(self, "distance_mm", values[0])
        object.__setattr__(self, "offset_mm", values[1])
        object.__setattr__(self, "overshoot_mm", values[2])

    def to_mapping(self) -> dict[str, object]:
        return {
            "side": self.side,
            "distance_mm": self.distance_mm,
            "offset_mm": self.offset_mm,
            "overshoot_mm": self.overshoot_mm,
        }

    @classmethod
    def from_mapping(cls, value: object) -> SurfaceExtensionSpec:
        if not isinstance(value, Mapping):
            raise ValueError("invalid surface extension")
        data = cast("Mapping[str, object]", value)
        if set(data) != {
            "side",
            "distance_mm",
            "offset_mm",
            "overshoot_mm",
        }:
            raise ValueError("invalid surface extension")
        return cls(
            cast("Literal['start', 'end']", data["side"]),
            cast("float", data["distance_mm"]),
            cast("float", data["offset_mm"]),
            cast("float", data["overshoot_mm"]),
        )


@dataclass(frozen=True, slots=True)
class SurfaceExtensionGeometry:
    target_mm: Point2D
    start_mm: Point2D
    end_mm: Point2D
    center_mm: Point2D | None = None
    sweep_angle_deg: float = 0.0


def surface_extension_geometry(
    entity: LineEntity | ArcEntity,
    side: Literal["start", "end"],
    distance_mm: float,
    offset_mm: float,
    overshoot_mm: float,
) -> SurfaceExtensionGeometry:
    """Compute target and extension, with all distances measured along the curve."""
    spec = SurfaceExtensionSpec(side, distance_mm, offset_mm, overshoot_mm)
    distance_mm, offset_mm, overshoot_mm = spec.distance_mm, spec.offset_mm, spec.overshoot_mm
    direction = 1.0 if side == "end" else -1.0
    if isinstance(entity, LineEntity):
        dx = entity.end_mm[0] - entity.start_mm[0]
        dy = entity.end_mm[1] - entity.start_mm[1]
        length = math.hypot(dx, dy)
        endpoint = entity.end_mm if side == "end" else entity.start_mm

        def point(distance: float) -> Point2D:
            return (
                endpoint[0] + direction * dx / length * distance,
                endpoint[1] + direction * dy / length * distance,
            )

        return SurfaceExtensionGeometry(
            point(distance_mm), point(offset_mm), point(distance_mm + overshoot_mm)
        )
    if not isinstance(cast("object", entity), ArcEntity):
        raise ValueError("surface extension requires a line or circular arc")
    travel = math.degrees((distance_mm + overshoot_mm) / entity.radius_mm)
    if travel >= 360 - abs(entity.sweep_angle_deg):
        raise ValueError("surface extension overlaps the original arc")
    sign = math.copysign(1.0, entity.sweep_angle_deg) * direction
    endpoint_angle = entity.start_angle_deg + (entity.sweep_angle_deg if side == "end" else 0)

    def arc_point(distance: float) -> Point2D:
        angle = math.radians(endpoint_angle) + sign * distance / entity.radius_mm
        return (
            entity.center_mm[0] + entity.radius_mm * math.cos(angle),
            entity.center_mm[1] + entity.radius_mm * math.sin(angle),
        )

    return SurfaceExtensionGeometry(
        arc_point(distance_mm),
        arc_point(offset_mm),
        arc_point(distance_mm + overshoot_mm),
        entity.center_mm,
        sign * math.degrees((distance_mm + overshoot_mm - offset_mm) / entity.radius_mm),
    )
