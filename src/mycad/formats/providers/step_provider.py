# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Built-in STEP export provider (T8a): delegates to the kernel's export_step."""

from __future__ import annotations

from pathlib import Path

from mycad.core.ports import ExportableKernel
from mycad.formats.base import FormatProvider


def _write_step(geometry: ExportableKernel, path: Path) -> None:
    """Write ``geometry`` to ``path`` via the kernel's STEP export."""

    geometry.export_step(path)


STEP_PROVIDER = FormatProvider(
    name="STEP",
    vendor="OCC",
    priority=100,
    extensions=(".step",),
    can_read=False,
    can_write=True,
    target="shape",
    _writer=_write_step,
)
