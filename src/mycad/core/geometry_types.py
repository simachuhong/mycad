# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral geometry DTOs (Phase 0).

These dataclasses are the cross-layer language used by providers (STEP, STL),
command results, and the history log. They are deliberately **neutral**:
they do not import ``build123d`` or ``OCP``. That is the rule enforced by
``tests/test_layering.py``: only modules under ``mycad.geom`` (a later wave)
are allowed to import the CAD backends; the rest of the codebase receives
plain ``(vertices, faces, indices)`` data.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned bounding box in millimetres."""

    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float

    @property
    def size(self) -> tuple[float, float, float]:
        """(dx, dy, dz) of the box."""
        return (self.xmax - self.xmin, self.ymax - self.ymin, self.zmax - self.zmin)

    @property
    def center(self) -> tuple[float, float, float]:
        """Geometric center as (cx, cy, cz)."""
        return (
            (self.xmin + self.xmax) / 2.0,
            (self.ymin + self.ymax) / 2.0,
            (self.zmin + self.zmax) / 2.0,
        )


@dataclass(frozen=True)
class MassProperties:
    """Static mass properties returned by geometry queries.

    ``bbox`` may be ``None`` for empty geometry (degenerate solids) and
    ``center_of_mass`` is stored as a 3-tuple to remain JSON-serializable.
    """

    volume: float
    solid_count: int
    cylindrical_face_count: int
    bbox: BoundingBox | None
    center_of_mass: tuple[float, float, float] = field(default=(0.0, 0.0, 0.0))


@dataclass(frozen=True)
class Tessellation:
    """Triangular mesh produced by tessellation.

    ``vertices`` is an ordered tuple of (x, y, z) tuples. ``triangle_indices``
    is a tuple of (i0, i1, i2) tuples where every index is a valid offset
    into ``vertices``. The invariant is checked in ``__post_init__`` so a
    bad mesh fails immediately at construction, not at render time.
    """

    vertices: tuple[tuple[float, float, float], ...]
    triangle_indices: tuple[tuple[int, int, int], ...]

    def __post_init__(self) -> None:
        n = len(self.vertices)
        for tri in self.triangle_indices:
            if not (0 <= tri[0] < n and 0 <= tri[1] < n and 0 <= tri[2] < n):
                msg = f"triangle index out of range: {tri} vs n_vertices={n}"
                raise ValueError(msg)


__all__ = ["BoundingBox", "MassProperties", "Tessellation"]
