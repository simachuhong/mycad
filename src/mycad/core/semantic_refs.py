# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Neutral semantic topology references; no CAD kernel types cross core."""

from __future__ import annotations

import math
from dataclasses import dataclass

from mycad.core.identity import FeatureId, TopologyId
from mycad.core.selectors import AxisLiteral, CurveLiteral, SurfaceLiteral


@dataclass(frozen=True, slots=True)
class FacePredicate:
    """Coarse face query that intentionally carries no selector rank."""

    surface: SurfaceLiteral
    axis: AxisLiteral | None = None
    center_mm: tuple[float, float, float] | None = None
    radius_mm: float | None = None

    def __post_init__(self) -> None:
        if self.surface not in ("plane", "cylinder"):
            raise ValueError(f"unsupported face surface {self.surface!r}")
        if self.surface == "plane" and self.axis is None:
            raise ValueError("plane face predicate requires an axis")
        if self.center_mm is not None and (
            len(self.center_mm) != 3 or any(not math.isfinite(value) for value in self.center_mm)
        ):
            raise ValueError("face center_mm must contain three finite coordinates")
        if self.radius_mm is not None and (
            not math.isfinite(self.radius_mm) or self.radius_mm <= 0.0
        ):
            raise ValueError("face radius_mm must be positive and finite")


@dataclass(frozen=True, slots=True)
class EdgePredicate:
    """Edge query constrained by one or more semantic parent faces."""

    parent_faces: tuple[FacePredicate, ...]
    curve: CurveLiteral | None = None
    center_mm: tuple[float, float, float] | None = None
    radius_mm: float | None = None

    def __post_init__(self) -> None:
        if not self.parent_faces:
            raise ValueError("edge predicate requires at least one parent face")
        if self.center_mm is not None and (
            len(self.center_mm) != 3 or any(not math.isfinite(value) for value in self.center_mm)
        ):
            raise ValueError("edge center_mm must contain three finite coordinates")
        if self.radius_mm is not None and (
            not math.isfinite(self.radius_mm) or self.radius_mm <= 0.0
        ):
            raise ValueError("edge radius_mm must be positive and finite")


@dataclass(frozen=True, slots=True)
class SemanticFaceRef:
    """Face role owned by one runtime feature and topology generation."""

    owner_feature: FeatureId
    role: str
    predicate: FacePredicate
    topology_id: TopologyId

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("semantic face role must not be empty")


@dataclass(frozen=True, slots=True)
class SemanticEdgeRef:
    """Edge role owned by one runtime feature and topology generation."""

    owner_feature: FeatureId
    role: str
    predicate: EdgePredicate
    topology_id: TopologyId

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("semantic edge role must not be empty")


@dataclass(frozen=True, slots=True)
class TopologyResolutionEvidence:
    """Backend-neutral evidence returned with a uniquely resolved role."""

    candidate_count: int
    selection_rule: str
    selected_measure: float


__all__ = [
    "EdgePredicate",
    "FacePredicate",
    "SemanticEdgeRef",
    "SemanticFaceRef",
    "TopologyResolutionEvidence",
]
