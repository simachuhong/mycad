# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Matrix fixture: api_version "1.5"."""

from __future__ import annotations

from mycad.plugins.types import CommandContribution

manifest: dict[str, object] = {
    "id": "matrix-1-5",
    "version": "1.0.0",
    "api_version": "1.5",
}


def commands() -> list[CommandContribution]:
    return []
