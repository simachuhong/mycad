# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Kernel protocol: the core-side dependency inversion (T6a).

Core holds only this Protocol and never imports ``mycad.geom``; the
concrete BuildKernel is wired in top-level composition (T7/T10).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from mycad.core.command_identity import ExecutionContext
from mycad.core.identity import TopologyId
from mycad.core.measurements import MeasurementRequest, MeasurementResult

if TYPE_CHECKING:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch import Sketch
    from mycad.core.sketch_layers import SketchLayerTable


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
class DrawingBaselineKernel(Protocol):
    """Optional capability for initializing replayable drawing defaults."""

    def set_drawing_fillet_baseline(self, radius: float) -> None: ...


@runtime_checkable
class DrawingGroupArrayConflictKernel(Protocol):
    """Read legacy-compatible group/array dependency conflicts for admission."""

    @property
    def drawing_group_array_conflicts(self) -> frozenset[tuple[str, str, str, str]]: ...


@runtime_checkable
class DrawingGroupMappingKernel(Protocol):
    """Read-only state for reporting group members lost by a sketch revision."""

    @property
    def sketches(self) -> tuple[Sketch, ...]: ...

    @property
    def drawing_groups(self) -> tuple[DrawingGroup, ...]: ...


@runtime_checkable
class ChamferBaselineKernel(Protocol):
    """Optional capability for initializing the chamfer angle baseline."""

    def set_drawing_chamfer_angle_baseline(self, angle: float) -> None: ...


@runtime_checkable
class DatumRevisionGuard(Protocol):
    """Optional admission check for newly submitted sketch changes."""

    def validate_datum_revision(self, command_id: str, params: Mapping[str, object]) -> None: ...


@runtime_checkable
class VersionedDatumRevisionGuard(Protocol):
    """Optional admission check that receives the actual command version."""

    def validate_datum_revision_versioned(
        self, command_id: str, params: Mapping[str, object], version: int
    ) -> None: ...


@runtime_checkable
class DrawingBlockExplosionKernel(Protocol):
    """Read-only state required to derive validated explosion operations."""

    @property
    def drawing_block_definitions(self) -> tuple[BlockDefinition, ...]: ...

    @property
    def drawing_block_instances(self) -> tuple[BlockInstance, ...]: ...

    @property
    def drawing_groups(self) -> tuple[DrawingGroup, ...]: ...

    @property
    def drawing_layers(self) -> SketchLayerTable: ...

    @property
    def drawing_text_styles(self) -> TextStyleTable: ...

    @property
    def drawing_identity_reservations(self) -> tuple[str, ...]: ...


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
