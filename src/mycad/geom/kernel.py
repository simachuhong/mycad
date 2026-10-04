# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Sealed build123d kernel adapter (Phase 0, T2).

This module is the only product-code location allowed to import ``build123d``
(enforced by ``tests/test_layering.py``). No build123d/OCP/numpy object ever
leaves the ``mycad.geom`` package through the neutral DTOs it returns.

Conventions (project-wide): lengths are millimetres, angles are decimal
degrees. ``feature.cylinder`` primitives are centered on ``center`` with the
axis along +Z spanning z in [-height/2, +height/2]. Boolean modes are the
strings ``new`` / ``add`` / ``cut`` mapped to build123d ``Mode.NEW`` /
``Mode.ADD`` / ``Mode.SUBTRACT``.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Mapping
from pathlib import Path

from build123d import Edge, Face, Part

from mycad.core.exceptions import GeomVersionError
from mycad.core.geometry_types import MassProperties, Tessellation
from mycad.core.selectors import EdgeSelector, FaceSelector
from mycad.geom._b123_ops import apply_primitive
from mycad.geom.query import build_mass_properties, build_tessellation
from mycad.geom.selectors import ordered_face_candidates, resolve_edges, resolve_face

EXPECTED_B123D_VERSION: tuple[int, int, int] = (0, 11, 1)
EXPECTED_B123D_VERSION_STR = ".".join(str(part) for part in EXPECTED_B123D_VERSION)


def _parse_version_tuple(raw: str) -> tuple[int, int, int]:
    """Parse ``major.minor.micro`` into an int triple; anything else fails."""

    segments = raw.split(".")
    if len(segments) != 3:
        msg = (
            f"build123d version {raw!r} is not parseable as 'major.minor.micro' "
            f"integers; expected {EXPECTED_B123D_VERSION_STR}"
        )
        raise GeomVersionError(message=msg)
    try:
        parsed = tuple(int(segment) for segment in segments)
    except ValueError:
        msg = (
            f"build123d version {raw!r} is not parseable as 'major.minor.micro' "
            f"integers; expected {EXPECTED_B123D_VERSION_STR}"
        )
        raise GeomVersionError(message=msg) from None
    return (parsed[0], parsed[1], parsed[2])


def assert_b123d_version(raw: str | None = None) -> None:
    """Assert the installed build123d matches the pinned version.

    The version is read from ``importlib.metadata.version("build123d")`` —
    the unique version source (``build123d.__version__`` is deliberately
    never read so the gate cannot be bypassed by patching it).
    """

    actual_raw = raw if raw is not None else importlib.metadata.version("build123d")
    actual = _parse_version_tuple(actual_raw)
    if actual != EXPECTED_B123D_VERSION:
        msg = (
            f"build123d version mismatch: actual {actual_raw!r} "
            f"(parsed {actual}), expected {EXPECTED_B123D_VERSION_STR} "
            f"(parsed {EXPECTED_B123D_VERSION})"
        )
        raise GeomVersionError(message=msg)


assert_b123d_version()


class BuildKernel:
    """Geometry kernel facade: applies feature commands to an in-memory part."""

    def __init__(self) -> None:
        self._part: Part | None = None

    def reset(self) -> None:
        """Drop the current solid: the kernel returns to empty-geometry state."""

        self._part = None

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        """Apply one feature command (``feature.box`` / ``feature.cylinder``).

        ``mode`` selects the boolean behaviour: ``new`` replaces the current
        solid, ``add`` fuses into it, ``cut`` subtracts from it.
        """

        self._part = apply_primitive(self._part, command_id, params)

    def mass_properties(self) -> MassProperties:
        """Measure the current solid; empty geometry yields zeros, not errors."""

        return build_mass_properties(self._part)

    def tessellate(self, linear_tolerance_mm: float, angular_tolerance_deg: float) -> Tessellation:
        """Triangulate the current solid into in-memory vertex/index data.

        Writes no file format and touches no rendering stack. A finer
        (halved) linear tolerance must yield a strictly greater triangle
        count wherever the linear deflection is the binding constraint.
        """

        return build_tessellation(self._part, linear_tolerance_mm, angular_tolerance_deg)

    def export_step(self, path: str | Path) -> None:
        """Placeholder — STEP export is wired by T8."""

        raise NotImplementedError

    def export_stl(self, path: str | Path) -> None:
        """Placeholder — STL export is wired by T8."""

        raise NotImplementedError

    def face_candidates(
        self,
        selector: FaceSelector | Mapping[str, object],
        command_id: str,
    ) -> list[Face]:
        """All faces matching the selector, in the deterministic total order."""

        return ordered_face_candidates(selector, self._part, command_id)

    def resolve_face(
        self,
        selector: FaceSelector | Mapping[str, object],
        command_id: str,
    ) -> Face:
        """Resolve a FaceSelector to exactly one face (rank/unique semantics)."""

        return resolve_face(selector, self._part, command_id)

    def resolve_edges(
        self,
        selector: EdgeSelector | Mapping[str, object],
        command_id: str,
    ) -> list[Edge]:
        """Resolve an EdgeSelector to its ordered edge list."""

        return resolve_edges(selector, self._part, command_id)
