# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Backend-independent dimensional tolerance values."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


@dataclass(frozen=True, slots=True)
class DimensionTolerance:
    """Signed deviations in the unit of the associated dimension."""

    mode: str = "none"
    upper_deviation: float = 0.0
    lower_deviation: float = 0.0
    precision: int = 2
    text_factor: float = 1.0
    alignment: str = "middle"

    def __post_init__(self) -> None:
        if self.mode not in ("none", "symmetric", "deviation", "limits"):
            raise ValueError("unsupported tolerance mode")
        upper = _number(self.upper_deviation, "upper deviation")
        lower = _number(self.lower_deviation, "lower deviation")
        factor = _number(self.text_factor, "text factor")
        if upper < lower:
            raise ValueError("upper deviation must not be below lower deviation")
        if self.mode == "symmetric" and (upper < 0 or lower != -upper):
            raise ValueError("symmetric deviations must be equal and opposite")
        precision = cast("object", self.precision)
        if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 8:
            raise ValueError("tolerance precision must be between 0 and 8")
        if factor <= 0 or factor > 100:
            raise ValueError("text factor must be positive and no more than 100")
        if self.alignment not in ("top", "middle", "bottom"):
            raise ValueError("unsupported tolerance alignment")
        object.__setattr__(self, "upper_deviation", upper)
        object.__setattr__(self, "lower_deviation", lower)
        object.__setattr__(self, "text_factor", factor)

    def limits(self, nominal: float) -> tuple[float, float]:
        value = _number(nominal, "nominal dimension")
        upper, lower = value + self.upper_deviation, value + self.lower_deviation
        if not math.isfinite(upper) or not math.isfinite(lower):
            raise ValueError("dimension limits must be finite")
        return upper, lower

    def to_mapping(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "upper_deviation": self.upper_deviation,
            "lower_deviation": self.lower_deviation,
            "precision": self.precision,
            "text_factor": self.text_factor,
            "alignment": self.alignment,
        }

    @classmethod
    def from_mapping(cls, value: object) -> DimensionTolerance:
        if not isinstance(value, Mapping):
            raise ValueError("dimension tolerance must be an object")
        data = cast("Mapping[str, object]", value)
        if set(data) != {
            "mode",
            "upper_deviation",
            "lower_deviation",
            "precision",
            "text_factor",
            "alignment",
        }:
            raise ValueError("dimension tolerance must contain its known fields")
        return cls(
            cast("str", data["mode"]),
            cast("float", data["upper_deviation"]),
            cast("float", data["lower_deviation"]),
            cast("int", data["precision"]),
            cast("float", data["text_factor"]),
            cast("str", data["alignment"]),
        )


def effective_tolerance(
    default: DimensionTolerance, override: DimensionTolerance | None
) -> DimensionTolerance:
    """Explicit none mode disables a non-none style default."""
    return default if override is None else override


def tolerance_parts(nominal: float, tolerance: DimensionTolerance) -> tuple[str, ...]:
    """Return tolerance components for layout without mutating stored precision."""
    precision = tolerance.precision
    if tolerance.mode == "none":
        return ()
    if tolerance.mode == "symmetric":
        return ("±" + _formatted_zero(tolerance.upper_deviation, precision, signed=False),)
    if tolerance.mode == "limits":
        values = tolerance.limits(nominal)
        return tuple(_formatted_zero(value, precision, signed=False) for value in values)
    return tuple(
        _formatted_zero(value, precision, signed=True)
        for value in (tolerance.upper_deviation, tolerance.lower_deviation)
    )


def tolerance_values_hidden_by_precision(nominal: float, tolerance: DimensionTolerance) -> bool:
    """Identify deviations or limits hidden by the selected display precision."""
    if tolerance.mode == "none":
        return False
    if tolerance.mode == "limits":
        try:
            values = tolerance_parts(nominal, tolerance)
        except ValueError:
            return False
        return tolerance.upper_deviation != tolerance.lower_deviation and values[0] == values[1]
    if tolerance.mode == "deviation" and tolerance.upper_deviation != tolerance.lower_deviation:
        values = tolerance_parts(nominal, tolerance)
        if values[0] == values[1]:
            return True
    return any(
        value != 0 and round(value, tolerance.precision) == 0
        for value in (tolerance.upper_deviation, tolerance.lower_deviation)
    )


def _formatted_zero(value: float, precision: int, *, signed: bool) -> str:
    text = f"{value:+.{precision}f}" if signed else f"{value:.{precision}f}"
    if text.startswith("-") and float(text) == 0:
        return text[1:]
    return text
