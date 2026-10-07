# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Fixture submodule: format factory returning a single-element list."""

from __future__ import annotations

from pathlib import Path

from mycad.core.ports import ExportableKernel
from mycad.formats.base import FormatProvider

manifest: dict[str, object] = {
    "id": "formats-single",
    "version": "1.0.0",
    "api_version": "1.0",
}


def _write_single(geometry: ExportableKernel, path: Path) -> None:
    path.write_text("single\n", encoding="utf-8")


def formats() -> list[FormatProvider]:
    return [
        FormatProvider(
            name="SINGLE-FIXTURE",
            vendor="fixture",
            priority=60,
            extensions=(".single",),
            can_read=False,
            can_write=True,
            target="shape",
            _writer=_write_single,
        ),
    ]
