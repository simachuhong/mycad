# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral selector descriptors (Phase 0).

Selectors describe which bodies, faces, or edges a future command will
target. Body locators carry geometric measurements because they identify a
whole solid; face and edge selectors remain topology predicates resolved by
the geometry adapter.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

# ---------------------------------------------------------------------------
# Face selectors
# ---------------------------------------------------------------------------

AxisLiteral = Literal["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
SurfaceLiteral = Literal["plane", "cylinder"]


def _is_finite_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True)
class BodySelector:
    """Replayable geometric locator for one current solid body.

    The rank disambiguates coincident bodies with identical measured
    signatures. It is a selector tie-break, never a serialized runtime ID.
    """

    volume_mm3: float
    center_mm: tuple[float, float, float]
    bounds_mm: tuple[float, float, float, float, float, float]
    rank: int | None = None

    def __post_init__(self) -> None:
        volume = self.volume_mm3
        if not _is_finite_number(volume) or volume <= 0.0:
            raise ValueError("body selector volume must be positive and finite")
        if len(self.center_mm) != 3 or any(
            not _is_finite_number(value) for value in self.center_mm
        ):
            raise ValueError("body selector center must contain three finite coordinates")
        if len(self.bounds_mm) != 6 or any(
            not _is_finite_number(value) for value in self.bounds_mm
        ):
            raise ValueError("body selector bounds must contain six finite coordinates")
        if any(self.bounds_mm[index] > self.bounds_mm[index + 3] for index in range(3)):
            raise ValueError("body selector bounds must be ordered minimum/maximum pairs")
        if self.rank is not None and not _is_nonnegative_integer(self.rank):
            raise ValueError("body selector rank must be a nonnegative integer")

    def to_mapping(self) -> dict[str, object]:
        """Return the stable wire mapping used in command history."""

        result: dict[str, object] = {
            "volume_mm3": self.volume_mm3,
            "center_mm": list(self.center_mm),
            "bounds_mm": list(self.bounds_mm),
        }
        if self.rank is not None:
            result["rank"] = self.rank
        return result

    @classmethod
    def from_mapping(cls, value: object) -> BodySelector:
        """Parse a strict schema-shaped body selector mapping."""

        if not isinstance(value, Mapping):
            raise ValueError("body selector must be an object")
        record = cast("Mapping[str, object]", value)
        allowed = {"volume_mm3", "center_mm", "bounds_mm", "rank"}
        if set(record) - allowed or not {"volume_mm3", "center_mm", "bounds_mm"} <= set(record):
            raise ValueError("body selector must contain volume, center, bounds, and optional rank")
        center = record["center_mm"]
        bounds = record["bounds_mm"]
        if not isinstance(center, (list, tuple)):
            raise ValueError("body selector center must contain three coordinates")
        if not isinstance(bounds, (list, tuple)):
            raise ValueError("body selector bounds must contain six coordinates")
        center_values = cast("Sequence[object]", center)
        bounds_values = cast("Sequence[object]", bounds)
        if len(center_values) != 3:
            raise ValueError("body selector center must contain three coordinates")
        if len(bounds_values) != 6:
            raise ValueError("body selector bounds must contain six coordinates")
        if not all(_is_finite_number(item) for item in (*center_values, *bounds_values)):
            raise ValueError("body selector center and bounds must contain finite numbers")
        center_numbers = cast("Sequence[int | float]", center_values)
        bounds_numbers = cast("Sequence[int | float]", bounds_values)
        raw_volume = record["volume_mm3"]
        if not _is_finite_number(raw_volume):
            raise ValueError("body selector volume must be positive and finite")
        rank = record.get("rank")
        parsed_rank: int | None = None
        if "rank" in record:
            if not _is_nonnegative_integer(rank):
                raise ValueError("body selector rank must be a nonnegative integer")
            parsed_rank = cast("int", rank)
        return cls(
            float(cast("int | float", raw_volume)),
            cast("tuple[float, float, float]", tuple(float(item) for item in center_numbers)),
            cast(
                "tuple[float, float, float, float, float, float]",
                tuple(float(item) for item in bounds_numbers),
            ),
            parsed_rank,
        )


@dataclass(frozen=True)
class FaceSelector:
    """Pick a face by surface kind and optional axis alignment.

    ``axis`` only applies to planar faces (``surface="plane"``). Cylindrical
    faces are picked solely by ``surface`` at this stage; finer-grained
    cylindrical selection (radius band, axis direction) lands in a later
    wave via the geometry adapter.
    """

    surface: SurfaceLiteral
    axis: AxisLiteral | None = None
    rank: int | None = None


CurveLiteral = Literal["line", "circle"]


@dataclass(frozen=True)
class EdgeSelector:
    """Pick an edge by the surfaces it lies between.

    ``parent_faces`` is required: an edge must belong to at least one face.
    A line vs circle hint is available via ``curve`` for downstream
    disambiguation; this descriptor carries no positional data of its own.
    """

    parent_faces: tuple[FaceSelector, ...]
    curve: CurveLiteral | None = None


__all__ = [
    "BodySelector",
    "FaceSelector",
    "EdgeSelector",
    "AxisLiteral",
    "SurfaceLiteral",
    "CurveLiteral",
]
