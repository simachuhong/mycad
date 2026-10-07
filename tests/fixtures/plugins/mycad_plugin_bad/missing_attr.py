# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Fixture submodule with no manifest attribute at all."""

from __future__ import annotations

from mycad.plugins.types import CommandContribution


def commands() -> list[CommandContribution]:
    return []
