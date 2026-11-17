# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""AutoCAD indexed colors used by drawing dimension styles."""

from ezdxf.colors import aci2rgb
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QComboBox


def indexed_color(index: int, *, dark: bool = False) -> QColor:
    """Map an explicit ACI color to a visible drawing color."""
    if index == 7:
        return QColor("white" if dark else "black")
    rgb = aci2rgb(index)
    return QColor(rgb.r, rgb.g, rgb.b)


def dimension_color_combo() -> QComboBox:
    combo = QComboBox()
    combo.addItem("随图层", 256)
    for index in range(1, 256):
        swatch = QPixmap(18, 12)
        swatch.fill(indexed_color(index))
        combo.addItem(QIcon(swatch), f"索引颜色 {index}", index)
    return combo
