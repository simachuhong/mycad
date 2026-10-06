# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Kernel protocol: the core-side dependency inversion (T6a).

Core holds only this Protocol and never imports ``mycad.geom``; the
concrete BuildKernel is wired in top-level composition (T7/T10).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class Kernel(Protocol):
    """Minimal geometry-kernel surface the command layer depends on."""

    def reset(self) -> None:
        """Clear all geometry state back to an empty model."""
        ...

    def apply(self, command_id: str, params: Mapping[str, object]) -> None:
        """Apply one command by id with its validated parameters."""
        ...
