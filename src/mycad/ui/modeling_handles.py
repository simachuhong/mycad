# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Operation-specific dimension geometry, independent of the rendering backend."""

from __future__ import annotations

import math
from dataclasses import dataclass

from mycad.core.viewport_protocol import PlanarFaceFrame, Point3


@dataclass(frozen=True)
class DimensionHandle:
    key: str
    label: str
    frame: PlanarFaceFrame
    scale: float = 1.0
    minimum: float = 0.001
    maximum: float = 1_000_000.0
    angular: bool = False
    radial: Point3 = (1.0, 0.0, 0.0)
    ring_radius: float = 10.0


def cross(a: Point3, b: Point3) -> Point3:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def plane_direction(normal: Point3) -> Point3:
    """Stable unit direction in the plane, including vertical planes."""
    seed = (1.0, 0.0, 0.0) if abs(normal[0]) < 0.9 else (0.0, 1.0, 0.0)
    dot = sum(seed[i] * normal[i] for i in range(3))
    values = tuple(seed[i] - dot * normal[i] for i in range(3))
    length = math.sqrt(sum(v * v for v in values))
    return values[0] / length, values[1] / length, values[2] / length


def dimension_handle(
    command: str,
    key: str,
    label: str,
    origin: Point3,
    normal: Point3 = (0.0, 0.0, 1.0),
    *,
    axis: str = "X",
    ring_radius: float = 20.0,
) -> DimensionHandle:
    """Use actual primitive centering, face normals and revolution axes."""
    direction: Point3 = (1.0, 0.0, 0.0)
    scale = 1.0
    minimum = 0.001
    maximum = 1_000_000.0
    radial: Point3 = (1.0, 0.0, 0.0)
    angular = key in {"angle_deg", "start_angle_deg"}
    if key == "angle_deg":
        direction = (1.0, 0.0, 0.0) if axis == "X" else (0.0, 1.0, 0.0)
        radial = (
            (0.0, 1.0 if origin[1] >= 0 else -1.0, 0.0)
            if axis == "X"
            else (1.0 if origin[0] >= 0 else -1.0, 0.0, 0.0)
        )
        ring_radius = max(5.0, abs(origin[1] if axis == "X" else origin[0]))
        origin = (origin[0], 0.0, 0.0) if axis == "X" else (0.0, origin[1], 0.0)
        maximum = 360.0
    elif key == "start_angle_deg":
        direction = (0.0, 0.0, 1.0)
        minimum, maximum = -3600.0, 3600.0
    elif key == "distance":
        direction = normal
        minimum = -1_000_000.0
    elif key == "depth_value":
        direction = (-normal[0], -normal[1], -normal[2])
    elif key in {"diameter", "pattern_radius"}:
        direction = plane_direction(normal)
        scale = 0.5 if key == "diameter" else 1.0
    elif key.endswith("size_y") or key == "profile_height":
        direction, scale = (0.0, 1.0, 0.0), 0.5
    elif key.endswith("size_x") or key == "profile_width":
        scale = 0.5
    elif key.endswith("size_z") or key in {"height", "tool_height"}:
        direction, scale = (0.0, 0.0, 1.0), 0.5
    if command == "modify.fillet":
        direction = plane_direction(normal)
    return DimensionHandle(
        key,
        label,
        PlanarFaceFrame(origin, direction),
        scale,
        minimum,
        maximum,
        angular,
        radial,
        ring_radius,
    )
