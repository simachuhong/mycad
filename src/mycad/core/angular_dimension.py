# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Geometry for selecting an angular dimension sector from its location."""

from __future__ import annotations

import math
from dataclasses import dataclass

from mycad.core.sketch import Point2D


@dataclass(frozen=True, slots=True)
class AngularSector:
    center: Point2D
    start: float
    sweep: float
    first_reversed: bool
    second_reversed: bool
    starts_with_first: bool

    def solver_degrees(self, displayed_degrees: float) -> float:
        """Translate a positive sector angle to the solver's directed line angle."""
        if not math.isfinite(displayed_degrees) or not 0 < displayed_degrees < 180:
            raise ValueError("角度尺寸须大于 0° 且小于 180°。")
        first_offset = 180.0 if self.first_reversed else 0.0
        second_offset = 180.0 if self.second_reversed else 0.0
        value = displayed_degrees if self.starts_with_first else -displayed_degrees
        value += first_offset - second_offset
        return (value + 180.0) % 360.0 - 180.0


def angular_sector(
    first: tuple[Point2D, Point2D], second: tuple[Point2D, Point2D], position: Point2D
) -> AngularSector:
    """Find the adjacent pair of line rays enclosing a dimension location."""
    u = (first[1][0] - first[0][0], first[1][1] - first[0][1])
    v = (second[1][0] - second[0][0], second[1][1] - second[0][1])
    cross = u[0] * v[1] - u[1] * v[0]
    if abs(cross) <= 1e-10:
        raise ValueError("平行直线不能放置角度尺寸。")
    delta = (second[0][0] - first[0][0], second[0][1] - first[0][1])
    t = (delta[0] * v[1] - delta[1] * v[0]) / cross
    center = (first[0][0] + t * u[0], first[0][1] + t * u[1])
    if math.dist(position, center) <= 1e-10:
        raise ValueError("角度标注位置不能与交点重合。")
    a, b = math.atan2(u[1], u[0]), math.atan2(v[1], v[0])
    rays = sorted(
        (
            (a % math.tau, 0, False),
            ((a + math.pi) % math.tau, 0, True),
            (b % math.tau, 1, False),
            ((b + math.pi) % math.tau, 1, True),
        )
    )
    angle = math.atan2(position[1] - center[1], position[0] - center[0]) % math.tau
    for index, (start, owner, reversed_ray) in enumerate(rays):
        end, end_owner, end_reversed = rays[(index + 1) % 4]
        sweep = (end - start) % math.tau
        if (angle - start) % math.tau <= sweep:
            first_reversed = reversed_ray if owner == 0 else end_reversed
            second_reversed = reversed_ray if owner == 1 else end_reversed
            if owner == end_owner:
                raise ValueError("无法确定角度标注的角区。")
            return AngularSector(center, start, sweep, first_reversed, second_reversed, owner == 0)
    raise ValueError("无法确定角度标注的角区。")
