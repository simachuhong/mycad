# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Rigid, right-handed coordinate frames independent of the geometry backend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mycad.core.sketch import Point3D, WorkPlaneFrame


@dataclass(frozen=True, slots=True)
class RigidFrame:
    """An origin and orthonormal axes expressed in the parent coordinate system."""

    origin_mm: Point3D
    x_axis: Point3D
    y_axis: Point3D
    z_axis: Point3D

    def __post_init__(self) -> None:
        validated = WorkPlaneFrame(self.origin_mm, self.x_axis, self.y_axis, self.z_axis)
        object.__setattr__(self, "origin_mm", validated.origin_mm)
        object.__setattr__(self, "x_axis", validated.u_axis)
        object.__setattr__(self, "y_axis", validated.v_axis)
        object.__setattr__(self, "z_axis", validated.normal)

    @classmethod
    def identity(cls) -> RigidFrame:
        """Return the fixed world frame."""
        return cls((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))

    def _direction_to_world(self, value: Point3D) -> Point3D:
        x, y, z = value
        return (
            x * self.x_axis[0] + y * self.y_axis[0] + z * self.z_axis[0],
            x * self.x_axis[1] + y * self.y_axis[1] + z * self.z_axis[1],
            x * self.x_axis[2] + y * self.y_axis[2] + z * self.z_axis[2],
        )

    def local_to_world(self, point: Point3D) -> Point3D:
        """Map a point from this frame into its parent coordinates."""
        direction = self._direction_to_world(point)
        return (
            self.origin_mm[0] + direction[0],
            self.origin_mm[1] + direction[1],
            self.origin_mm[2] + direction[2],
        )

    def world_to_local(self, point: Point3D) -> Point3D:
        """Map a parent-space point into this frame."""
        delta = tuple(point[index] - self.origin_mm[index] for index in range(3))
        return (
            sum(delta[index] * self.x_axis[index] for index in range(3)),
            sum(delta[index] * self.y_axis[index] for index in range(3)),
            sum(delta[index] * self.z_axis[index] for index in range(3)),
        )

    def compose(self, child: RigidFrame) -> RigidFrame:
        """Compose parent-from-this and this-from-child transforms."""
        return RigidFrame(
            self.local_to_world(child.origin_mm),
            self._direction_to_world(child.x_axis),
            self._direction_to_world(child.y_axis),
            self._direction_to_world(child.z_axis),
        )

    def principal_plane(self, plane: Literal["xy", "xz", "yz"]) -> WorkPlaneFrame:
        """Return the named plane using the established sketch axis conventions."""
        if plane == "xy":
            return WorkPlaneFrame(self.origin_mm, self.x_axis, self.y_axis, self.z_axis)
        if plane == "xz":
            negative_z: Point3D = (-self.z_axis[0], -self.z_axis[1], -self.z_axis[2])
            return WorkPlaneFrame(self.origin_mm, self.x_axis, negative_z, self.y_axis)
        if plane == "yz":
            return WorkPlaneFrame(self.origin_mm, self.y_axis, self.z_axis, self.x_axis)
        raise ValueError("unknown principal plane")
