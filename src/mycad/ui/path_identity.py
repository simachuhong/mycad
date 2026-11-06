# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Comparable file paths that remain usable when stored links are broken."""

import os
from pathlib import Path


def path_identity(path: Path) -> str:
    """Resolve aliases where possible, falling back to a normalized absolute path."""
    try:
        normalized = str(path.resolve())
    except (OSError, RuntimeError, ValueError):
        normalized = os.path.abspath(path)
    return os.path.normcase(normalized)
