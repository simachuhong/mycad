# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Straight section definitions in a parent view's model-space coordinates."""

from dataclasses import dataclass
from math import hypot, isfinite
from typing import Literal

from mycad.core.drawing_projection import Point2, Point3, ViewBasis, finite


@dataclass(frozen=True, slots=True)
class SectionPlane:
    """A point on the cutting plane and the observer-facing section basis."""

    origin: Point3
    basis: ViewBasis


@dataclass(frozen=True, slots=True)
class SectionLine:
    """A cutting line in the parent's unscaled projected model coordinates.

    The plane extends through the line along the parent's viewing normal.
    The side names identify the observer relative to start → end in that view.
    """

    start: Point2
    end: Point2
    observer_side: Literal["left", "right"] = "right"

    def __post_init__(self) -> None:
        finite((*self.start, *self.end), "section line")
        length = hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])
        if not isfinite(length) or length < 1e-9:
            raise ValueError("section line must have nonzero length")
        if self.observer_side not in ("left", "right"):
            raise ValueError("invalid section observer side")

    def plane(self, parent: ViewBasis) -> SectionPlane:
        dx, dy = self.end[0] - self.start[0], self.end[1] - self.start[1]
        length = hypot(dx, dy)
        dx, dy = dx / length, dy / length
        side = 1 if self.observer_side == "right" else -1
        tangent = tuple(
            dx * right + dy * up for right, up in zip(parent.right, parent.up, strict=True)
        )
        normal = tuple(
            side * (dy * right - dx * up) for right, up in zip(parent.right, parent.up, strict=True)
        )
        distance = side * (dy * self.start[0] - dx * self.start[1])
        finite((distance,), "section plane offset")
        origin = tuple(distance * component for component in normal)
        return SectionPlane(
            (origin[0], origin[1], origin[2]),
            ViewBasis.from_normal_up(
                (normal[0], normal[1], normal[2]), (tangent[0], tangent[1], tangent[2])
            ),
        )
