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
from typing import cast

from mycad.core.exceptions import ValidationError


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


__all__ = [
    "CircleProfile",
    "Profile",
    "RectProfile",
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
