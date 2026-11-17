# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Visual selection of the linetypes supported by drawing layers."""

from typing import override

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mycad.core.sketch_layers import SKETCH_LINETYPES, SketchLinetype

_LINE_STYLES: dict[SketchLinetype, Qt.PenStyle] = {
    "CONTINUOUS": Qt.PenStyle.SolidLine,
    "DASHED": Qt.PenStyle.DashLine,
    "DOTTED": Qt.PenStyle.DotLine,
    "DASHDOT": Qt.PenStyle.DashDotLine,
}
_DESCRIPTIONS: dict[SketchLinetype, str] = {
    "CONTINUOUS": "连续线",
    "DASHED": "虚线",
    "DOTTED": "点线",
    "DASHDOT": "点画线",
}


class _LinetypePreview(QWidget):
    def __init__(self, linetype: SketchLinetype, parent: QWidget) -> None:
        super().__init__(parent)
        self._linetype: SketchLinetype = linetype
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName(_DESCRIPTIONS[linetype])

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        pen = QPen(self.palette().color(QPalette.ColorRole.Text), 2.0)
        pen.setStyle(_LINE_STYLES[self._linetype])
        painter.setPen(pen)
        painter.drawLine(8, self.height() // 2, max(8, self.width() - 8), self.height() // 2)


class LinetypeSelectionDialog(QDialog):
    """Choose one available linetype by name, appearance and description."""

    def __init__(self, current: SketchLinetype, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择线型")
        self.resize(540, 290)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("可用线型"))
        self.table = QTableWidget(len(SKETCH_LINETYPES), 3, self)
        self.table.setObjectName("linetypeChoices")
        self.table.setHorizontalHeaderLabels(("线型", "外观", "说明"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(2, 100)
        for row, linetype in enumerate(SKETCH_LINETYPES):
            self.table.setItem(row, 0, QTableWidgetItem(linetype))
            self.table.setItem(row, 1, QTableWidgetItem())
            self.table.setCellWidget(row, 1, _LinetypePreview(linetype, self.table))
            self.table.setItem(row, 2, QTableWidgetItem(_DESCRIPTIONS[linetype]))
        self.table.selectRow(SKETCH_LINETYPES.index(current))
        self.table.doubleClicked.connect(self.accept)
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selected_linetype(self) -> SketchLinetype:
        return SKETCH_LINETYPES[self.table.currentRow()]

    @override
    def accept(self) -> None:
        if self.table.currentRow() >= 0:
            super().accept()
