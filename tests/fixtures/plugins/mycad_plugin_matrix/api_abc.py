# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Matrix fixture: api_version "abc"."""

from __future__ import annotations

from mycad.plugins.types import CommandContribution

manifest: dict[str, object] = {
    "id": "matrix-abc",
    "version": "1.0.0",
    "api_version": "abc",
}


def commands() -> list[CommandContribution]:
    return []
