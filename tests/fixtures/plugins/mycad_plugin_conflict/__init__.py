# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""In-process fixture: contributions that collide with core registry.

The command spec reuses the built-in id ``feature.box``; the format
provider claims the .txt extension at the same priority the demo
plugin will use. The loader (T9b) must treat both as per-entry
conflicts; T9a only places the fixture.
"""

from __future__ import annotations

from pathlib import Path

from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.core.ports import ExportableKernel
from mycad.formats.base import FormatProvider
from mycad.plugins.types import CommandContribution

manifest: dict[str, object] = {
    "id": "conflict",
    "version": "1.0.0",
    "api_version": "1.0",
}


def commands() -> list[CommandContribution]:
    return [
        CommandContribution(
            spec=CommandSpec(
                id="feature.box",
                version=1,
                summary_en="Box (colliding)",
                label_zh="箱（撞名）",
                params_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                cli=CliSyntax(("box",)),
            ),
            handler_factory=None,
        ),
    ]


def _write_txt(geometry: ExportableKernel, path: Path) -> None:
    path.write_text("txt\n", encoding="utf-8")


def formats() -> list[FormatProvider]:
    return [
        FormatProvider(
            name="TXT-FIXTURE",
            vendor="fixture",
            priority=100,
            extensions=(".txt",),
            can_read=False,
            can_write=True,
            target="shape",
            _writer=_write_txt,
        ),
    ]
