# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Modeless drawing layer table with independent on, freeze and lock controls."""

from __future__ import annotations

from dataclasses import replace
from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.ui.linetype_dialog import LinetypeSelectionDialog


class DrawingLayerPanel(QDialog):
    properties_changed = Signal(object, str)
    current_layer_changed = Signal(str)
    migrate_requested = Signal()

    def __init__(
        self,
        layers: SketchLayerTable,
        current_layer: str,
        dimension_layer: str,
        used_names: tuple[str, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("图层属性管理器 · 整张图纸")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(850, 380)
        self.layer_table = layers
        self.current_layer = current_layer
        self.dimension_layer = dimension_layer
        self.used_names = used_names
        self._updating = False
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ("名称", "显示", "冻结", "锁定", "颜色", "线型", "线宽 mm")
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        row.addWidget(QLabel("默认标注层"))
        self.dimension_combo = QComboBox()
        row.addWidget(self.dimension_combo)
        self.add_button = QPushButton("新建图层")
        self.remove_button = QPushButton("删除图层")
        self.current_button = QPushButton("置为当前层")
        self.migrate_button = QPushButton("旧标注移入 DIM")
        self.migrate_button.setToolTip("批量迁移仍继承几何图层的旧尺寸；已有独立标注层保持原归属")
        for button in (
            self.add_button,
            self.remove_button,
            self.current_button,
            self.migrate_button,
        ):
            row.addWidget(button)
        layout.addLayout(row)
        self.status_label = QLabel(
            "关闭和冻结独立；解冻不会打开已关闭的层。点击颜色或线型修改；双击线宽可修改。"
        )
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.table.itemChanged.connect(self._item_changed)
        self.dimension_combo.currentIndexChanged.connect(self._dimension_changed)
        self.add_button.clicked.connect(self._add)
        self.remove_button.clicked.connect(self._remove)
        self.current_button.clicked.connect(self._make_current)
        self.migrate_button.clicked.connect(self.migrate_requested)
        self.set_layers(layers, dimension_layer, current_layer)

    def set_layers(
        self, layers: SketchLayerTable, dimension_layer: str, current_layer: str
    ) -> None:
        self._updating = True
        self.layer_table = layers
        self.dimension_layer = dimension_layer
        self.current_layer = current_layer
        self.table.setRowCount(len(layers.layers))
        for row, layer in enumerate(layers.layers):
            name = QTableWidgetItem(layer.name + ("  ✓" if layer.name == current_layer else ""))
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, name)
            for column, state in ((1, layer.visible), (2, layer.frozen), (3, layer.locked)):
                item = QTableWidgetItem()
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsSelectable
                )
                item.setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
                self.table.setItem(row, column, item)
            color = QColor(*layer.color_rgb)
            swatch = QPixmap(24, 14)
            swatch.fill(color)
            painter = QPainter(swatch)
            painter.setPen(QPen(QColor("#808080")))
            painter.drawRect(0, 0, swatch.width() - 1, swatch.height() - 1)
            painter.end()
            color_button = QPushButton(color.name().upper())
            color_button.setIcon(QIcon(swatch))
            color_button.setToolTip(f"选择图层 {layer.name} 的颜色")
            color_button.setAccessibleName(f"选择图层 {layer.name} 的颜色")
            color_button.clicked.connect(partial(self._choose_color, layer.name))
            self.table.setCellWidget(row, 4, color_button)
            linetype_button = QPushButton(f"{layer.linetype} …")
            linetype_button.setToolTip(f"选择图层 {layer.name} 的线型")
            linetype_button.setAccessibleName(f"选择图层 {layer.name} 的线型")
            linetype_button.clicked.connect(partial(self._choose_linetype, layer.name))
            self.table.setCellWidget(row, 5, linetype_button)
            self.table.setItem(row, 6, QTableWidgetItem(f"{layer.lineweight_mm:g}"))
        self.table.resizeColumnsToContents()
        self.dimension_combo.clear()
        self.dimension_combo.addItem("使用当前绘图层", ".")
        for layer in layers.layers:
            self.dimension_combo.addItem(layer.name, layer.name)
        self.dimension_combo.setCurrentIndex(self.dimension_combo.findData(dimension_layer))
        self._updating = False

    def _choose_color(self, name: str) -> None:
        layer = self.layer_table.get(name)
        color = QColorDialog.getColor(QColor(*layer.color_rgb), self, "选择图层颜色")
        if not color.isValid():
            return
        try:
            layer = self.layer_table.get(name)
        except KeyError:
            return
        rgb = (color.red(), color.green(), color.blue())
        if rgb == layer.color_rgb:
            return
        self.layer_table = self.layer_table.replace(replace(layer, color_rgb=rgb))
        self.set_layers(self.layer_table, self.dimension_layer, self.current_layer)
        self.properties_changed.emit(self.layer_table, self.dimension_layer)

    def _choose_linetype(self, name: str) -> None:
        layer = self.layer_table.get(name)
        dialog = LinetypeSelectionDialog(layer.linetype, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        linetype = dialog.selected_linetype if accepted else None
        dialog.deleteLater()
        if linetype is None:
            return
        try:
            layer = self.layer_table.get(name)
        except KeyError:
            return
        if linetype == layer.linetype:
            return
        self.layer_table = self.layer_table.replace(replace(layer, linetype=linetype))
        self.set_layers(self.layer_table, self.dimension_layer, self.current_layer)
        self.properties_changed.emit(self.layer_table, self.dimension_layer)

    def set_layer_state(
        self,
        name: str,
        *,
        visible: bool | None = None,
        frozen: bool | None = None,
        locked: bool | None = None,
    ) -> bool:
        layer = self.layer_table.get(name)
        if frozen and layer.name.casefold() == self.current_layer.casefold():
            self.status_label.setText("当前绘图层不能冻结；请先切换到其他图层。")
            self.set_layers(self.layer_table, self.dimension_layer, self.current_layer)
            return False
        revised = replace(
            layer,
            visible=layer.visible if visible is None else visible,
            frozen=layer.frozen if frozen is None else frozen,
            locked=layer.locked if locked is None else locked,
        )
        self.layer_table = self.layer_table.replace(revised)
        self.set_layers(self.layer_table, self.dimension_layer, self.current_layer)
        self.properties_changed.emit(self.layer_table, self.dimension_layer)
        return True

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        layer = self.layer_table.layers[item.row()]
        column = item.column()
        if column in (1, 2, 3):
            state = item.checkState() == Qt.CheckState.Checked
            if column == 1:
                self.set_layer_state(layer.name, visible=state)
            elif column == 2:
                self.set_layer_state(layer.name, frozen=state)
            else:
                self.set_layer_state(layer.name, locked=state)
            return
        try:
            if column == 6:
                revised = replace(layer, lineweight_mm=float(item.text()))
            else:
                return
            self.layer_table = self.layer_table.replace(revised)
            self.properties_changed.emit(self.layer_table, self.dimension_layer)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            self.set_layers(self.layer_table, self.dimension_layer, self.current_layer)

    def _dimension_changed(self, _index: int) -> None:
        if not self._updating:
            self.dimension_layer = str(self.dimension_combo.currentData())
            self.properties_changed.emit(self.layer_table, self.dimension_layer)

    def _add(self) -> None:
        name, accepted = QInputDialog.getText(self, "新建图层", "图层名称")
        if accepted:
            try:
                self.layer_table = self.layer_table.add(SketchLayer(name))
                self.set_layers(self.layer_table, self.dimension_layer, self.current_layer)
                self.properties_changed.emit(self.layer_table, self.dimension_layer)
            except ValueError as exc:
                self.status_label.setText(str(exc))

    def _remove(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        name = self.layer_table.layers[row].name
        try:
            if name in (self.current_layer, self.dimension_layer):
                raise ValueError("请先更换当前绘图层或默认标注层，再删除此层")
            self.layer_table = self.layer_table.remove(name, used_names=self.used_names)
            self.set_layers(self.layer_table, self.dimension_layer, self.current_layer)
            self.properties_changed.emit(self.layer_table, self.dimension_layer)
        except ValueError as exc:
            self.status_label.setText(str(exc))

    def _make_current(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        layer = self.layer_table.layers[row]
        if layer.frozen:
            self.status_label.setText("冻结图层不能设为当前绘图层，请先解冻。")
            return
        self.current_layer_changed.emit(layer.name)
        self.set_layers(self.layer_table, self.dimension_layer, layer.name)
