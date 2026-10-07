# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Fixture submodule: format factory returning an empty list (legal)."""

from __future__ import annotations

from mycad.formats.base import FormatProvider

manifest: dict[str, object] = {
    "id": "formats-empty",
    "version": "1.0.0",
    "api_version": "1.0",
}


def formats() -> list[FormatProvider]:
    return []
