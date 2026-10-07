# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Fixture submodule: manifest id fails the plugin-id pattern."""

from __future__ import annotations

from mycad.plugins.types import CommandContribution

manifest: dict[str, object] = {"id": "Bad Id", "version": "1.0.0", "api_version": "1.0"}


def commands() -> list[CommandContribution]:
    return []
