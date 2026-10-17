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
from copy import deepcopy
from pathlib import Path

from build123d import Edge, Face, Part

from mycad.core.exceptions import GeomVersionError
from mycad.core.geometry_types import MassProperties, Tessellation
from mycad.core.selectors import EdgeSelector, FaceSelector
from mycad.core.viewport_protocol import ViewportData
from mycad.geom._b123_features import apply_feature
from mycad.geom._b123_ops import apply_primitive
from mycad.geom.io import write_step, write_stl
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


# Default mesh extraction tolerances for the viewport port (plan todo 3).
# Linear = chordal deviation (mm), angular = angular deviation (decimal
# degrees). Sized for the phase-1 GUI preview scale (OD80-class parts);
# explicit arguments to ``viewport_data`` always take precedence.
DEFAULT_MESH_LINEAR_TOLERANCE_MM: float = 0.1
DEFAULT_MESH_ANGULAR_TOLERANCE_DEG: float = 15.0


class BuildKernel:
    """Geometry kernel facade: applies feature commands to an in-memory part.

    Implements the core ``ViewportPort`` protocol structurally: every
    successful ``apply`` freezes a snapshot of the post-execution part.
    """

    def __init__(self) -> None:
        self._part: Part | None = None
        self._snapshots: list[tuple[str, Part]] = []

    def reset(self) -> None:
        """Drop the current solid and the snapshot list: empty-geometry state."""
        # Snapshot list joins the cleared state: undo/redo rebuild resets the
        # kernel first, so full replay re-populates snapshots in ordinal order.

        self._part = None
        self._snapshots = []

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        """Apply one feature command to the in-memory part.

        ``feature.box`` / ``feature.cylinder`` (T2) and the T5 feature
        layer (extrude / revolve / hole / hole_pattern / fillet /
        boolean_cut) share this entry point. ``mode`` selects the boolean
        behaviour where applicable: ``new`` replaces the current solid,
        ``add`` fuses into it, ``cut`` subtracts from it.

        On success a snapshot is frozen (plan todo 3): a deepcopy of the
        post-execution part appended as ``("<command id>:<snapshot
        index>", Part)``. The 0-based index equals the feature_history
        ordinal whenever the history holds only geometry-affecting
        commands — metadata and named-group annotations never enter the
        replay sequence (document.py), and undo/redo rebuild by full
        replay, so the list is naturally rebuilt in ordinal order.
        """

        if command_id in ("feature.box", "feature.cylinder"):
            self._part = apply_primitive(self._part, command_id, params)
        else:
            self._part = apply_feature(self._part, command_id, params)
        if self._part is not None:
            self._snapshots.append((f"{command_id}:{len(self._snapshots)}", deepcopy(self._part)))

    def viewport_data(
        self,
        linear_tolerance_mm: float = DEFAULT_MESH_LINEAR_TOLERANCE_MM,
        angular_tolerance_deg: float = DEFAULT_MESH_ANGULAR_TOLERANCE_DEG,
    ) -> tuple[ViewportData, ...]:
        """Per-snapshot meshes in feature order, implementing ``ViewportPort``.

        Zero-argument calls keep the protocol call shape valid; the
        defaulted tolerance parameters let callers request a finer mesh
        explicitly (the kernel tessellation contract below applies).
        No caching/invalidation (phase 1, plan todo 3 "Must NOT"):
        every call re-triangulates every snapshot through
        ``build_tessellation``, which deepcopies again — the
        stale-triangulation annotation in query.py applies unchanged.
        Empty document → empty tuple.
        """

        return tuple(
            ViewportData(
                feature_id=feature_id,
                mesh=build_tessellation(part, linear_tolerance_mm, angular_tolerance_deg),
            )
            for feature_id, part in self._snapshots
        )

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
        """Write the current model as a STEP file (wired by T8 via geom.io)."""

        write_step(self._part, Path(path))

    def export_stl(self, path: str | Path) -> None:
        """Write the current model as an STL mesh (wired by T8 via geom.io)."""

        write_stl(self._part, Path(path))

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
