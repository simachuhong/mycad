# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""In-process fixture: callable-form manifest, one command + one format.

``CALL_COUNT`` is a one-element counter cell: ``CALL_COUNT[0]`` counts
manifest-builder invocations so tests can prove discovery resolves
(and calls) the manifest exactly once per module. A cell is used
instead of a plain int because the static checker treats all-caps
module names as constants and rejects in-function reassignment.
"""

from __future__ import annotations

from pathlib import Path

from mycad.commands.spec import CliSyntax, CommandSpec
from mycad.core.ports import ExportableKernel
from mycad.formats.base import FormatProvider
from mycad.plugins.types import CommandContribution

CALL_COUNT: list[int] = [0]


def _make_manifest() -> dict[str, object]:
    CALL_COUNT[0] += 1
    return {"id": "manifest-callable", "version": "1.0.0", "api_version": "1.0"}


manifest = _make_manifest


def commands() -> list[CommandContribution]:
    return [
        CommandContribution(
            spec=CommandSpec(
                id="demo.spec.1",
                version=1,
                summary_en="S1",
                label_zh="甲",
                params_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                cli=CliSyntax(("s1",)),
            ),
            handler_factory=None,
        ),
    ]


def _write_ft1(geometry: ExportableKernel, path: Path) -> None:
    path.write_text("ft1\n", encoding="utf-8")


def formats() -> list[FormatProvider]:
    return [
        FormatProvider(
            name="FT1",
            vendor="fixture",
            priority=50,
            extensions=(".ft1",),
            can_read=False,
            can_write=True,
            target="shape",
            _writer=_write_ft1,
        ),
    ]
