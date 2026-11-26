# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Font-independent vector paths for geometric characteristic symbols."""

from __future__ import annotations

from mycad.core.geometric_tolerance import CHARACTERISTICS


class _Path:
    def __init__(self) -> None:
        self.commands: list[tuple[str, tuple[float, ...]]] = []

    def move_to(self, *coordinates: float) -> None:
        self.commands.append(("move", coordinates))

    def line_to(self, *coordinates: float) -> None:
        self.commands.append(("line", coordinates))

    def cubic_to(self, *coordinates: float) -> None:
        self.commands.append(("cubic", coordinates))

    def add_ellipse(self, *coordinates: float) -> None:
        self.commands.append(("ellipse", coordinates))


def geometric_symbol_commands(characteristic: str) -> tuple[tuple[str, tuple[float, ...]], ...]:
    """Return backend-independent unit-square drawing commands."""
    if characteristic not in CHARACTERISTICS:
        raise ValueError("unsupported geometric characteristic")
    path = _Path()

    def stroke(*points: tuple[float, float]) -> None:
        path.move_to(*points[0])
        for point in points[1:]:
            path.line_to(*point)

    def circle(x: float, y: float, size: float) -> None:
        path.add_ellipse(x, y, size, size)

    if characteristic == "straightness":
        stroke((0.12, 0.5), (0.88, 0.5))
    elif characteristic == "flatness":
        stroke((0.12, 0.72), (0.33, 0.28), (0.88, 0.28), (0.67, 0.72), (0.12, 0.72))
    elif characteristic in ("circularity", "cylindricity", "concentricity", "position"):
        circle(0.27, 0.27, 0.46)
        if characteristic == "cylindricity":
            stroke((0.08, 0.78), (0.26, 0.22))
            stroke((0.74, 0.78), (0.92, 0.22))
        elif characteristic == "concentricity":
            circle(0.38, 0.38, 0.24)
        elif characteristic == "position":
            stroke((0.5, 0.08), (0.5, 0.92))
            stroke((0.08, 0.5), (0.92, 0.5))
    elif characteristic in ("line_profile", "surface_profile"):
        path.move_to(0.15, 0.7)
        path.cubic_to(0.15, 0.12, 0.85, 0.12, 0.85, 0.7)
        if characteristic == "surface_profile":
            stroke((0.08, 0.7), (0.92, 0.7))
    elif characteristic == "parallelism":
        stroke((0.18, 0.78), (0.4, 0.22))
        stroke((0.6, 0.78), (0.82, 0.22))
    elif characteristic == "perpendicularity":
        stroke((0.15, 0.75), (0.85, 0.75))
        stroke((0.5, 0.75), (0.5, 0.2))
    elif characteristic == "angularity":
        stroke((0.18, 0.75), (0.82, 0.75))
        stroke((0.18, 0.75), (0.7, 0.25))
    elif characteristic == "symmetry":
        for y in (0.3, 0.5, 0.7):
            stroke((0.15, y), (0.85, y))
    else:
        stroke((0.2, 0.78), (0.78, 0.2), (0.75, 0.45))
        stroke((0.78, 0.2), (0.53, 0.23))
        if characteristic == "total_runout":
            stroke((0.08, 0.65), (0.65, 0.08), (0.62, 0.3))
            stroke((0.65, 0.08), (0.42, 0.11))
    return tuple(path.commands)
