# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""MyCAD core: the neutral domain package (zero CAD-backend imports).

Importing ``mycad.core`` loads every core submodule — the teeth of
``tests/test_core_isolation.py``: any build123d / OCP leak anywhere in the
package surfaces in a fresh subprocess.
"""

# ruff: noqa: I001 — the §4.1 import order below is FIXED by design
# (dependencies before dependents) and deliberately non-alphabetical:
# exceptions → selectors → geometry_types → signals → groups →
# kernel_protocol → handlers → ports → plan → document → bus →
# schema_v1 → migrations → persistence (schema_v1 precedes migrations
# because the migration default targets its ARCHIVE_VERSION constant).

from __future__ import annotations

from .exceptions import MycadError
from .selectors import EdgeSelector, FaceSelector
from .geometry_types import BoundingBox, MassProperties, Tessellation
from .signals import SignalBus
from .groups import NamedGroup
from .kernel_protocol import Kernel
from .handlers import BuiltinModelingHandler, CommandHandler, HandlerContext
from .ports import ExportableKernel, FormatPort, FormatResolver
from .plan import Plan
from .document import AFFECTED_OBJECTS, Document, ExecutedCommand, PlannedCommand
from .bus import CommandBus
from .schema_v1 import ARCHIVE_FORMAT, ARCHIVE_VERSION
from .migrations import Migration, migrate, register
from .persistence import LoadedDocument, open_document, save_document

__all__ = [
    "AFFECTED_OBJECTS",
    "ARCHIVE_FORMAT",
    "ARCHIVE_VERSION",
    "BoundingBox",
    "BuiltinModelingHandler",
    "CommandBus",
    "CommandHandler",
    "Document",
    "EdgeSelector",
    "ExecutedCommand",
    "ExportableKernel",
    "FaceSelector",
    "FormatPort",
    "FormatResolver",
    "HandlerContext",
    "Kernel",
    "LoadedDocument",
    "MassProperties",
    "Migration",
    "MycadError",
    "NamedGroup",
    "Plan",
    "PlannedCommand",
    "SignalBus",
    "Tessellation",
    "migrate",
    "open_document",
    "register",
    "save_document",
]
