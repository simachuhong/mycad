# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Fixture submodule: format factory raising, commands side healthy.

Proves group isolation: the broken formats entry must not take the
distribution's command contributions down with it.
"""

from __future__ import annotations

from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.formats.base import FormatProvider
from mycad.plugins.types import CommandContribution

manifest: dict[str, object] = {
    "id": "formats-raise",
    "version": "1.0.0",
    "api_version": "1.0",
}


def commands() -> list[CommandContribution]:
    return [
        CommandContribution(
            spec=CommandSpec(
                id="formats.raise.spec.1",
                version=1,
                summary_en="R1",
                label_zh="卯",
                params_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                cli=CliSyntax(("r1",)),
            ),
            handler_factory=None,
        ),
    ]


def formats() -> list[FormatProvider]:
    raise RuntimeError("boom")
