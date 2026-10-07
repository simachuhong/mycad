# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""In-process fixture: dict-form manifest, zero command contributions."""

from __future__ import annotations

from mycad.plugins.types import CommandContribution

manifest: dict[str, object] = {
    "id": "manifest-dict",
    "version": "1.0.0",
    "api_version": "1.0",
}


def commands() -> list[CommandContribution]:
    return []
