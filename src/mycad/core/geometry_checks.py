# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Backend-neutral outcomes for geometry validity checks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GeometryCheckIssue:
    """One failed validity or explicit postcondition check."""

    code: str
    message: str
    command_id: str
    parameter_path: str | None = None


@dataclass(frozen=True, slots=True)
class GeometryCheckResult:
    """Validity, solid count, and exact BREP volume for one command result."""

    is_valid: bool
    solid_count: int
    volume_mm3: float
    issues: tuple[GeometryCheckIssue, ...] = ()


__all__ = ["GeometryCheckIssue", "GeometryCheckResult"]
