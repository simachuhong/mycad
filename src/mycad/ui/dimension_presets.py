# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Named local defaults for new dimensions."""

from __future__ import annotations

import json
import math
from typing import cast, override

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

_PRESETS_KEY = "drawing2d/dimensionPresets"


def load_dimension_presets(settings: QSettings) -> dict[str, tuple[int, float]]:
    raw = settings.value(_PRESETS_KEY, "{}")
    if not isinstance(raw, str):
        return {}
    try:
        data: object = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, tuple[int, float]] = {}
    for name, item in cast("dict[object, object]", data).items():
        if not isinstance(item, list):
            continue
        values = cast("list[object]", item)
        if (
            isinstance(name, str)
            and 0 < len(name.strip()) <= 80
            and len(values) == 2
            and isinstance(values[0], int)
            and not isinstance(values[0], bool)
            and 0 <= values[0] <= 8
            and isinstance(values[1], int | float)
            and not isinstance(values[1], bool)
            and math.isfinite(values[1])
            and 0.1 <= values[1] <= 100
        ):
            result[name] = (values[0], float(values[1]))
    return result


class DimensionPresetDialog(QDialog):
    """Edit local presets and apply one to future dimensions on acceptance."""

    def __init__(
        self, settings: QSettings, precision: int, scale: float, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("标注格式预设")
        self._settings = settings
        self._presets = load_dimension_presets(settings)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("预设保存在本机；确定后应用于当前图纸的新建标注，已有尺寸不变。"))
        form = QFormLayout()
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.addItems(sorted(self._presets))
        self.name.setCurrentIndex(-1)
        self.name.setMaxCount(500)
        self.name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        form.addRow("预设名称", self.name)
        self.precision = QSpinBox()
        self.precision.setRange(0, 8)
        self.precision.setValue(precision)
        form.addRow("小数位数", self.precision)
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.1, 100.0)
        self.scale.setValue(scale)
        form.addRow("标注比例", self.scale)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.save_button = QPushButton("保存预设")
        self.delete_button = QPushButton("删除预设")
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)
        self.message = QLabel()
        layout.addWidget(self.message)
        close = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = close.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = close.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_button is not None:
            ok_button.setText("确定")
        if cancel_button is not None:
            cancel_button.setText("取消")
        close.accepted.connect(self.accept)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.name.currentIndexChanged.connect(self._selected)
        self.save_button.clicked.connect(self._save)
        self.delete_button.clicked.connect(self._delete)

    def _selected(self, _index: int) -> None:
        value = self._presets.get(self.name.currentText())
        if value is not None:
            self.precision.setValue(value[0])
            self.scale.setValue(value[1])

    def _save(self) -> None:
        name = self.name.currentText().strip()
        if not name or len(name) > 80:
            self.message.setText("请输入 1 至 80 个字符的预设名称。")
            return
        self._presets[name] = (self.precision.value(), self.scale.value())
        if self.name.findText(name) < 0:
            self.name.addItem(name)
        self.name.setCurrentText(name)
        self.message.setText("已暂存预设；点击确定保存。")

    def _delete(self) -> None:
        name = self.name.currentText()
        if name in self._presets:
            del self._presets[name]
            self.name.removeItem(self.name.findText(name))
            self.message.setText("已暂存删除；点击确定保存。")

    @override
    def accept(self) -> None:
        self._settings.setValue(_PRESETS_KEY, json.dumps(self._presets, ensure_ascii=False))
        super().accept()
