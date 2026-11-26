# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Qt adapter for shared geometric tolerance vector paths."""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath

from mycad.core.geometric_tolerance_symbols import geometric_symbol_commands


def geometric_symbol(characteristic: str) -> QPainterPath:
    """Return a unit-square path; callers select pen and placement."""
    path = QPainterPath()
    for command, coordinates in geometric_symbol_commands(characteristic):
        if command == "move":
            path.moveTo(*coordinates)
        elif command == "line":
            path.lineTo(*coordinates)
        elif command == "cubic":
            path.cubicTo(*coordinates)
        else:
            path.addEllipse(QRectF(*coordinates))
    return path
