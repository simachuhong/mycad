# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Test-only STEP readback helper (T8b).

This is the ONE file in the whole tests tree allowed to import a
build123d *read* API (layering whitelist in tests/test_layering.py).
Product code has no STEP import path in Phase 0 (F-DOC-03 is stage 1,
ADR-005); this exists solely for export->readback roundtrip asserts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import build123d
from build123d import Compound, GeomType

# import_step's stub signature is partially unknown under basedpyright
# strict; the cast narrows it to the exact call shape used here. This is
# a cast, not a suppression comment (same pattern as mycad/geom/io.py).
_read_step = cast(Callable[[Path], Compound], build123d.import_step)


@dataclass(frozen=True, slots=True)
class StepGeometry:
    """Geometric invariants read back from a STEP exchange file."""

    is_valid: bool
    solid_count: int
    volume_mm3: float
    bbox_size_mm: tuple[float, float, float]
    bbox_center_mm: tuple[float, float, float]
    cylindrical_face_diameters_mm: tuple[float, ...]


def read_step(path: Path) -> tuple[int, float]:
    """Read ``path`` back; return ``(solid count, volume in mm^3)``."""

    compound = _read_step(path)
    solids = compound.solids()
    return len(solids), sum(solid.volume for solid in solids)


def read_step_geometry(path: Path) -> StepGeometry:
    """Read validity, bounds, volume and exact cylindrical-face diameters."""

    compound = _read_step(path)
    solids = compound.solids()
    bounds = compound.bounding_box()
    diameters = {
        round(2.0 * float(face.radius), 7)
        for face in compound.faces().filter_by(GeomType.CYLINDER)
        if face.radius is not None
    }
    size = bounds.size
    center = bounds.center()
    return StepGeometry(
        is_valid=compound.is_valid,
        solid_count=len(solids),
        volume_mm3=sum(solid.volume for solid in solids),
        bbox_size_mm=(float(size.X), float(size.Y), float(size.Z)),
        bbox_center_mm=(float(center.X), float(center.Y), float(center.Z)),
        cylindrical_face_diameters_mm=tuple(sorted(diameters)),
    )


def planar_openings(path: Path) -> tuple[int, ...]:
    """Return inner boundary counts of exported planar faces."""
    return tuple(
        len(face.inner_wires())
        for face in _read_step(path).faces()
        if face.geom_type == GeomType.PLANE
    )
