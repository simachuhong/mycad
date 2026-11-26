# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Review supported DXF definitions and omissions before saving them to a library."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mycad.core.block_library import BlockAsset
from mycad.core.block_library_import import AssetIssue


class DxfBlockSelectionDialog(QDialog):
    def __init__(
        self,
        assets: tuple[BlockAsset, ...],
        issues: tuple[AssetIssue, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择要导入的 DXF 块")
        self.resize(650, 440)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for asset in assets:
            item = QListWidgetItem(asset.name)
            item.setData(Qt.ItemDataRole.UserRole, asset)
            self.list.addItem(item)
            item.setSelected(True)
        self.issues = QLabel(
            "\n".join(issue.message for issue in issues) if issues else "未报告不支持的块。"
        )
        self.issues.setWordWrap(True)
        self.issues.setTextFormat(Qt.TextFormat.PlainText)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("选择要保存到本地库的块："))
        layout.addWidget(self.list, 1)
        layout.addWidget(self.issues)
        layout.addWidget(buttons)

    def selected_assets(self) -> tuple[BlockAsset, ...]:
        values = (item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems())
        return tuple(value for value in values if isinstance(value, BlockAsset))


class DxfModelspaceDialog(QDialog):
    """Ask for an explicit name and insertion base in normalized millimetres."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("将 DXF 模型空间保存为块")
        self.name_field = QLineEdit()
        self.x_field, self.y_field = QDoubleSpinBox(), QDoubleSpinBox()
        for field in (self.x_field, self.y_field):
            field.setRange(-1e12, 1e12)
            field.setDecimals(8)
        self.message = QLabel("仅支持几何和文字；基点坐标使用换算后的毫米。")
        self.message.setWordWrap(True)
        form = QFormLayout()
        form.addRow("块名称", self.name_field)
        form.addRow("基点 X / mm", self.x_field)
        form.addRow("基点 Y / mm", self.y_field)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_valid)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addWidget(buttons)

    def _accept_valid(self) -> None:
        if not self.name_field.text().strip():
            self.message.setText("请输入块名称。")
            return
        self.accept()
