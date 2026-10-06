# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Format-provider vocabulary (T8a): frozen descriptors + import grading.

This module never imports ``mycad.geom`` or ``build123d``: writers are
injected as closures over ``ExportableKernel`` method calls, keeping the
build123d boundary inside ``mycad.geom`` (ADR-002 / ADR-005).
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mycad.core.ports import ExportableKernel


class ImportKind(enum.StrEnum):
    """Grading vocabulary for import paths — Phase 0 defines it, nothing returns it."""

    DUMB_SOLID = "dumb_solid"
    ASSEMBLY_WITH_ATTRS = "assembly_with_attrs"
    EDITABLE_FEATURES = "editable_features"


@dataclass(frozen=True)
class FormatProvider:
    """One export format: pinned metadata plus an injected writer closure.

    Structurally implements the T6 ``FormatPort`` protocol. ``_writer`` is
    the only behaviour: a closure that calls back into kernel methods, so
    no build123d call ever lives in this package.
    """

    name: str
    vendor: str
    priority: int
    extensions: tuple[str, ...]
    can_read: bool
    can_write: bool
    target: Literal["shape", "xcaf"]
    _writer: Callable[[ExportableKernel, Path], None]

    def write(self, geometry: ExportableKernel, path: Path) -> None:
        """Write the kernel's model to ``path`` in this format."""

        self._writer(geometry, path)
