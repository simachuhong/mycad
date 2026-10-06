# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Built-in STL export provider (T8a): delegates to the kernel's export_stl."""

from __future__ import annotations

from pathlib import Path

from mycad.core.ports import ExportableKernel
from mycad.formats.base import FormatProvider


def _write_stl(geometry: ExportableKernel, path: Path) -> None:
    """Write ``geometry`` to ``path`` via the kernel's STL export."""

    geometry.export_stl(path)


STL_PROVIDER = FormatProvider(
    name="STL",
    vendor="OCC",
    priority=100,
    extensions=(".stl",),
    can_read=False,
    can_write=True,
    target="shape",
    _writer=_write_stl,
)
