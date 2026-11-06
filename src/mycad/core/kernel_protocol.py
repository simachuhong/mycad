# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Kernel protocol: the core-side dependency inversion (T6a).

Core holds only this Protocol and never imports ``mycad.geom``; the
concrete BuildKernel is wired in top-level composition (T7/T10).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from mycad.core.command_identity import ExecutionContext
from mycad.core.identity import TopologyId
from mycad.core.measurements import MeasurementRequest, MeasurementResult


@runtime_checkable
class ContextualKernel(Protocol):
    """Optional identity-aware capability; legacy Kernel remains compatible."""

    def apply_with_context(
        self, command_id: str, params: Mapping[str, object], context: ExecutionContext
    ) -> None: ...


@runtime_checkable
class BoundFaceKernel(ContextualKernel, Protocol):
    """Optional design binding capability, beyond carrying command context."""

    def interactive_face_binding(self, identity: TopologyId) -> dict[str, object]: ...


@runtime_checkable
class Kernel(Protocol):
    """Minimal geometry-kernel surface the command layer depends on."""

    def reset(self) -> None:
        """Clear all geometry state back to an empty model."""
        ...

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        """Apply one command by id with its validated parameters."""
        ...

    def measure(self, request: MeasurementRequest) -> MeasurementResult:
        """Measure the current result using exact geometry queries."""
        ...
