# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""In-process fixture: plugin built against a future api major."""

from __future__ import annotations

from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.plugins.types import CommandContribution

manifest: dict[str, object] = {
    "id": "future",
    "version": "1.0.0",
    "api_version": "9.9",
}


def commands() -> list[CommandContribution]:
    return [
        CommandContribution(
            spec=CommandSpec(
                id="future.spec.1",
                version=1,
                summary_en="F1",
                label_zh="未",
                params_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                cli=CliSyntax(("f1",)),
            ),
            handler_factory=None,
        ),
    ]
