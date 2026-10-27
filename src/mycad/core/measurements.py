# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral requests and results for exact model measurements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from mycad.core.semantic_refs import SemanticEdgeRef, SemanticFaceRef

MeasurementKind = Literal[
    "body_volume",
    "cylindrical_face_diameter",
    "circular_edge_center_distance",
    "parallel_plane_separation",
]
MeasurementReference = SemanticFaceRef | SemanticEdgeRef


@dataclass(frozen=True, slots=True)
class MeasurementRequest:
    """A measurement operation bound to one geometry revision."""

    kind: MeasurementKind
    revision: int
    references: tuple[MeasurementReference, ...] = ()

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("measurement revision must be nonnegative")


@dataclass(frozen=True, slots=True)
class MeasurementResult:
    """Exact value or an actionable reason the requested measurement failed."""

    value: float | None
    unit: str
    revision: int
    description: str
    source: str = "BREP"
    error: str | None = None


@dataclass(frozen=True, slots=True)
class MeasurementTarget:
    """One selectable exact BREP entity, exposed without backend objects."""

    reference: MeasurementReference
    label: str


class MeasurementKernel(Protocol):
    """Narrow UI-facing port for exact measurements and revision checks."""

    @property
    def geometry_revision(self) -> int:
        """Revision of the currently active BREP state."""
        ...

    def measure(self, request: MeasurementRequest) -> MeasurementResult:
        """Query the active BREP state."""
        ...

    def measurement_targets(self, kind: MeasurementKind) -> tuple[MeasurementTarget, ...]:
        """List exact selectable entities for a measurement kind."""
        ...


__all__ = [
    "MeasurementKernel",
    "MeasurementKind",
    "MeasurementReference",
    "MeasurementRequest",
    "MeasurementResult",
    "MeasurementTarget",
]
