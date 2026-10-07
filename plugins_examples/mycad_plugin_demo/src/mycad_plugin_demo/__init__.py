# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Minimal MyCAD demo plugin (T9c).

Security model: MyCAD loads plugins in-process via Python entry-points,
which means installing a plugin is an act of **complete trust in its
author** (ADR-003) — there is no sandbox, signature check or enforced
permission model in Phase 0. Review a plugin's source before installing.

This plugin contributes one command (``demo.ping``) and one write-only
pseudo format (``TXT-SUMMARY``). It assumes the host environment already
provides ``mycad``; it declares no dependencies of its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.core.handlers import HandlerContext
from mycad.core.ports import ExportableKernel
from mycad.formats.base import FormatProvider
from mycad.plugins.types import CommandContribution

__all__ = [
    "DEMO_PING_SPEC",
    "DemoPingHandler",
    "TXT_SUMMARY_PROVIDER",
    "commands",
    "formats",
    "manifest",
]

#: Module-level manifest (dict form). Discovery reads the ``manifest``
#: attribute of the module named by each entry point; ``api_version``
#: "1.0" passes the major-version gate (any 1.x loads).
manifest = {
    "id": "mycad-plugin-demo",
    "version": "0.1.0",
    "api_version": "1.0",
}

#: The one command this plugin contributes; values pinned by contract.
DEMO_PING_SPEC = CommandSpec(
    id="demo.ping",
    version=1,
    summary_en="Ping the demo plugin",
    label_zh="演示：心跳",
    params_schema={
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    cli=CliSyntax(("ping",)),
    undo_compensation="history_replay",
)


class DemoPingHandler:
    """Handler for ``demo.ping``: returns ``"pong"``, no geometry."""

    command_id = "demo.ping"

    def handle(self, params: Mapping[str, object], ctx: HandlerContext) -> str:
        return "pong"


def commands() -> list[CommandContribution]:
    """Entry point factory for the ``mycad.commands`` group."""

    return [CommandContribution(spec=DEMO_PING_SPEC, handler_factory=DemoPingHandler)]


def _write_txt_summary(geometry: ExportableKernel, path: Path) -> None:
    """Write a one-line mass-properties summary, UTF-8."""

    mass = geometry.mass_properties()
    path.write_text(f"solids={mass.solid_count} volume={mass.volume}\n", encoding="utf-8")


#: Write-only pseudo format: one summary line per model.
TXT_SUMMARY_PROVIDER = FormatProvider(
    name="TXT-SUMMARY",
    vendor="demo",
    priority=100,
    extensions=(".txt",),
    can_read=False,
    can_write=True,
    target="shape",
    _writer=_write_txt_summary,
)


def formats() -> list[FormatProvider]:
    """Entry point factory for the ``mycad.formats`` group."""

    return [TXT_SUMMARY_PROVIDER]
