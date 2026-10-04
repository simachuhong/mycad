# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Command framework package (T3): spec, validation, registry, grammar.

Phase 0 wiring: ``CommandSpec`` describes every MyCAD command (stable id,
version, JSON-Schema-subset params schema, CLI syntax facts);
``validate_params``/``normalize_params`` guard the single write path before
any geometry work begins.
"""

from mycad.commands.spec import CliSyntax, CommandSpec

__all__ = [
    "CliSyntax",
    "CommandSpec",
]
