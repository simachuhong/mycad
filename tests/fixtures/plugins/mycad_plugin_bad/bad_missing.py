# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Fixture submodule: manifest dict lacks the version key."""

from __future__ import annotations

from mycad.plugins.types import CommandContribution

manifest: dict[str, object] = {"id": "bad-missing", "api_version": "1.0"}


def commands() -> list[CommandContribution]:
    return []
