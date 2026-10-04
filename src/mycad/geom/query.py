# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral-DTO geometry queries: mass properties and tessellation.

All build123d/OCP measurements are converted with explicit ``float()`` /
``tuple()`` calls so no backend type crosses the geom boundary.
"""

from __future__ import annotations

import math
from copy import deepcopy

from build123d import GeomType, Part

from mycad.core.exceptions import ValidationError
from mycad.core.geometry_types import BoundingBox, MassProperties, Tessellation

_EMPTY_MASS_PROPERTIES = MassProperties(
    volume=0.0,
    solid_count=0,
    cylindrical_face_count=0,
    bbox=None,
    center_of_mass=(0.0, 0.0, 0.0),
)


def _is_nonempty_part(part: Part | None) -> bool:
    return part is not None and len(part.solids()) > 0


def build_mass_properties(part: Part | None) -> MassProperties:
    """Fill the neutral MassProperties DTO from the build123d part.

    Empty geometry (``part is None`` or zero solids) is a defined state:
    ``solid_count=0``, ``volume=0.0``, ``bbox=None``,
    ``center_of_mass=(0.0, 0.0, 0.0)`` — not an exception.
    """

    if not _is_nonempty_part(part):
        return _EMPTY_MASS_PROPERTIES
    assert part is not None
    bb = part.bounding_box()
    center = part.center()
    return MassProperties(
        volume=float(part.volume),
        solid_count=len(part.solids()),
        cylindrical_face_count=len(part.faces().filter_by(GeomType.CYLINDER)),
        bbox=BoundingBox(
            xmin=float(bb.min.X),
            ymin=float(bb.min.Y),
            zmin=float(bb.min.Z),
            xmax=float(bb.max.X),
            ymax=float(bb.max.Y),
            zmax=float(bb.max.Z),
        ),
        center_of_mass=(float(center.X), float(center.Y), float(center.Z)),
    )


def _positive_finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"tessellate: {name} must be a number, got {value!r}"
        raise ValidationError(message=msg)
    if not math.isfinite(value) or value <= 0:
        msg = f"tessellate: {name} must be a positive finite number, got {value!r}"
        raise ValidationError(message=msg)
    return float(value)


def build_tessellation(
    part: Part | None,
    linear_tolerance_mm: object,
    angular_tolerance_deg: object,
) -> Tessellation:
    """Triangulate into memory-only vertex/index tuples.

    ``linear_tolerance_mm`` is the chordal deviation in millimetres;
    ``angular_tolerance_deg`` is the angular deviation in decimal degrees
    (build123d expects radians internally). The mesh is produced from a
    deepcopy of the part so a finer tolerance always re-meshes — build123d
    keeps any cached triangulation and OCCT's incremental mesher never
    refines an already-triangulated face, so reusing the stored shape would
    silently return stale triangle counts.
    """

    linear = _positive_finite(linear_tolerance_mm, "linear_tolerance_mm")
    angular = _positive_finite(angular_tolerance_deg, "angular_tolerance_deg")
    if not _is_nonempty_part(part):
        return Tessellation(vertices=(), triangle_indices=())
    assert part is not None
    vertices, triangles = deepcopy(part).tessellate(linear, math.radians(angular))
    return Tessellation(
        vertices=tuple((float(v.X), float(v.Y), float(v.Z)) for v in vertices),
        triangle_indices=tuple((int(a), int(b), int(c)) for (a, b, c) in triangles),
    )
