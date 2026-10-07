# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Fixture submodule: manifest dict carries an unknown extra key."""

from __future__ import annotations

from mycad.plugins.types import CommandContribution

manifest: dict[str, object] = {
    "id": "bad-extra",
    "version": "1.0.0",
    "api_version": "1.0",
    "surprise": True,
}


def commands() -> list[CommandContribution]:
    return []
