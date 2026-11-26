# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Staged document text styles and application font resource controls."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mycad.core.drawing_text import TextStyle, TextStyleTable
from mycad.ui.font_manager import FontManager


class TextStyleDialog(QDialog):
    """Keep style edits local until accepted; font imports are application resources."""

    def __init__(
        self,
        table: TextStyleTable,
        used: frozenset[str],
        manager: FontManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("文字样式 STYLE")
        self.resize(460, 510)
        self.table, self.used, self.manager = table, used, manager
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        self.styles = QComboBox()
        self.name = QLineEdit()
        self.family = QComboBox()
        self.family.setEditable(True)
        self.family.addItems(list(manager.families()))
        self.font_style = QComboBox()
        self.font_style.setEditable(True)
        self.height_field = QDoubleSpinBox()
        self.height_field.setRange(0.01, 10000)
        self.height_field.setDecimals(3)
        self.height_field.setSuffix(" mm")
        self.width_field = QDoubleSpinBox()
        self.width_field.setRange(0.01, 100)
        self.width_field.setDecimals(3)
        form.addRow("已有样式", self.styles)
        form.addRow("样式名称", self.name)
        form.addRow("字体", self.family)
        form.addRow("字形", self.font_style)
        form.addRow("默认字高", self.height_field)
        form.addRow("默认宽度因子", self.width_field)
        self.preview = QLabel("文字预览：技术要求 ABC 123 ⌀ ± °")
        self.preview.setWordWrap(True)
        form.addRow(self.preview)
        self.message = QLabel()
        self.message.setWordWrap(True)
        form.addRow(self.message)
        buttons = QHBoxLayout()
        for label, slot in (
            ("新建", self.add_style),
            ("保存修改", self.save_style),
            ("删除", self.remove_style),
            ("设为当前", self.set_current),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        form.addRow(buttons)
        resource = QPushButton("导入字体文件…")
        resource.setToolTip(
            "将 TTF/OTF/TTC 加入 MyCAD 用户字体库；字体导入独立于本图纸的确定/取消。"
        )
        resource.clicked.connect(self.import_font)
        form.addRow(resource)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.styles.currentIndexChanged.connect(self._load)
        self.family.currentTextChanged.connect(self._family_changed)
        self.font_style.currentTextChanged.connect(self._preview)
        self._refill(table.current_id)

    def _refill(self, identity: str) -> None:
        self.styles.blockSignals(True)
        self.styles.clear()
        for style in self.table.styles:
            self.styles.addItem(style.name, style.style_id)
        self.styles.setCurrentIndex(max(0, self.styles.findData(identity)))
        self.styles.blockSignals(False)
        self._load()

    def _load(self, _index: int = 0) -> None:
        style = self.table.get(str(self.styles.currentData()))
        self.name.setText(style.name)
        self.family.setCurrentText(style.font_family)
        self.font_style.setCurrentText(style.font_style)
        self.height_field.setValue(style.height_mm)
        self.width_field.setValue(style.width_factor)
        self.message.setText("当前样式" if style.style_id == self.table.current_id else "")
        self._preview()

    def _value(self) -> TextStyle:
        original = self.table.get(str(self.styles.currentData()))
        style = replace(
            original,
            name=self.name.text().strip(),
            font_family=self.family.currentText(),
            font_style=self.font_style.currentText(),
            height_mm=self.height_field.value(),
            width_factor=self.width_field.value(),
        )
        if (style.font_family, style.font_style) != (original.font_family, original.font_style):
            style = replace(style, font_file="")
        elif original.font_file:
            return style
        return replace(style, font_file=self.manager.font_file(style))

    def _family_changed(self, family: str) -> None:
        preferred = self.font_style.currentText()
        available = QFontDatabase.styles(family)
        self.font_style.blockSignals(True)
        self.font_style.clear()
        self.font_style.addItems(available)
        self.font_style.setCurrentText(
            preferred
            if preferred in available
            else available[0]
            if available
            else preferred or "Regular"
        )
        self.font_style.blockSignals(False)
        self._preview()

    def _preview(self, _value: str = "") -> None:
        original = self.table.get(str(self.styles.currentData()))
        style = replace(
            original,
            font_family=self.family.currentText(),
            font_style=self.font_style.currentText(),
        )
        if (style.font_family, style.font_style) != (original.font_family, original.font_style):
            style = replace(style, font_file="")
        font = self.manager.resolve(style)
        font.setPointSize(16)
        self.preview.setFont(font)
        substitution = self.manager.substitution(style)
        self.preview.setToolTip(substitution)

    def save_style(self) -> bool:
        try:
            style = self._value()
            self.table = TextStyleTable(
                tuple(
                    style if value.style_id == style.style_id else value
                    for value in self.table.styles
                ),
                self.table.current_id,
            )
        except ValueError as exc:
            self.message.setText(str(exc))
            return False
        self._refill(style.style_id)
        return True

    def add_style(self) -> None:
        names = {value.name for value in self.table.styles}
        name, index = "新样式", 1
        while name in names:
            index += 1
            name = f"新样式 {index}"
        style = replace(self.table.current, style_id=uuid4().hex, name=name)
        self.table = TextStyleTable((*self.table.styles, style), self.table.current_id)
        self._refill(style.style_id)

    def remove_style(self) -> None:
        identity = str(self.styles.currentData())
        if identity == self.table.current_id or identity in self.used:
            self.message.setText("当前样式或被文字使用的样式不能删除。")
            return
        self.table = TextStyleTable(
            tuple(style for style in self.table.styles if style.style_id != identity),
            self.table.current_id,
        )
        self._refill(self.table.current_id)

    def set_current(self) -> None:
        if self.save_style():
            self.table = TextStyleTable(self.table.styles, str(self.styles.currentData()))
            self._load()

    def import_font(self) -> None:
        from pathlib import Path

        name, _filter = QFileDialog.getOpenFileName(
            self, "导入字体", "", "字体文件 (*.ttf *.otf *.ttc)"
        )
        if not name:
            return
        try:
            families = self.manager.import_font(Path(name))
            current = self.family.currentText()
            self.family.clear()
            self.family.addItems(list(self.manager.families()))
            self.family.setCurrentText(families[0] if families else current)
            self.message.setText("字体已加入 MyCAD 用户字体库。")
        except (OSError, ValueError) as exc:
            self.message.setText(f"字体导入失败：{exc}")

    def _accept(self) -> None:
        if self.save_style():
            self.accept()
