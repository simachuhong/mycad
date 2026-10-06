# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Export ports: the second dependency inversion (T6a, enabling T8).

Core defines these Protocols only — it never imports ``mycad.geom`` or
``mycad.formats``. Concrete implementations are wired in top-level
composition. The document model is single-threaded by design; these
ports carry no locking semantics.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

from mycad.core.geometry_types import MassProperties


@runtime_checkable
class ExportableKernel(Protocol):
    """Kernel surface an exporter needs (method names mirror T2 BuildKernel)."""

    def reset(self) -> None:
        """Clear all geometry state back to an empty model."""
        ...

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        """Apply one command by id with its validated parameters."""
        ...

    def mass_properties(self) -> MassProperties:
        """Return the neutral mass-properties DTO of the current model."""
        ...

    def export_step(self, path: Path) -> None:
        """Write the current model as a STEP file."""
        ...

    def export_stl(self, path: Path) -> None:
        """Write the current model as an STL mesh."""
        ...


@runtime_checkable
class FormatPort(Protocol):
    """One export format behind the resolver (implemented in T8)."""

    name: str
    vendor: str
    priority: int
    extensions: tuple[str, ...]
    can_write: bool

    def write(self, geometry: ExportableKernel, path: Path) -> None:
        """Write the kernel's model to ``path`` in this format."""
        ...


@runtime_checkable
class FormatResolver(Protocol):
    """Pick the FormatPort that handles a given path."""

    def resolve(self, path: Path) -> FormatPort:
        """Return the format port responsible for ``path``."""
        ...
