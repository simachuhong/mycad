# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Built-in Phase-0 and released P2 commands with shared ``$defs``.

``COMMAND_SCHEMA_DEFS`` is the single formal A.0 transcription;
``BUILTIN_COMMAND_SPECS`` the A.1 specs plus individually released P2 commands. The
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

#: Unique command ids in the explicit catalog order; versions live in SPECS.
BUILTIN_COMMAND_IDS: tuple[str, ...] = tuple(
    dict.fromkeys(spec.id for spec in BUILTIN_COMMAND_SPECS)
)
