# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Built-in Phase-0 commands (T7a): shared ``$defs`` table + 8 CommandSpecs.

``COMMAND_SCHEMA_DEFS`` is the single formal A.0 transcription;
``BUILTIN_COMMAND_SPECS`` the eight A.1 specs in catalog order. The
composition root (``build_app``) registers them into a
``CommandRegistry(schema_defs=COMMAND_SCHEMA_DEFS)`` — built-ins never go
through entry_points.
"""

from __future__ import annotations

from mycad.builtin_commands.defs import COMMAND_SCHEMA_DEFS
from mycad.builtin_commands.specs import BUILTIN_COMMAND_SPECS

__all__ = [
    "BUILTIN_COMMAND_IDS",
    "BUILTIN_COMMAND_SPECS",
    "COMMAND_SCHEMA_DEFS",
]

#: The eight command ids, in BUILTIN_COMMAND_SPECS (A.1 catalog) order.
BUILTIN_COMMAND_IDS: tuple[str, ...] = tuple(spec.id for spec in BUILTIN_COMMAND_SPECS)
