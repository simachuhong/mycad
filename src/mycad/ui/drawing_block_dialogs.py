# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Small dialogs for naming, defining and placing independent drawing blocks."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mycad.core.drawing_blocks import BlockDefinition
from mycad.core.drawing_collection_state import DrawingCollectionSnapshot
from mycad.core.exceptions import ValidationError
from mycad.ui.preserving_spinbox import PreservingDoubleSpinBox

PICK_POINT = 2
OPEN_BLOCK_LIBRARY = 3


class BlockManagerDialog(QDialog):
    """List definitions and remove an unreferenced definition through the session."""

    def __init__(
        self,
        snapshot: Callable[[], DrawingCollectionSnapshot],
        remove: Callable[[str], None],
        rename: Callable[[str, str], None],
        parent: QWidget | None = None,
        *,
        save_to_library: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("管理块定义")
        self._snapshot = snapshot
        self._remove = remove
        self._rename = rename
        self._save_to_library = save_to_library
        self._displayed: dict[str, tuple[BlockDefinition, int]] = {}
        self.definition_field = QComboBox()
        self.name_field = QLineEdit()
        self.rename_button = QPushButton("重命名所选定义")
        self.remove_button = QPushButton("删除所选定义")
        self.library_button = QPushButton("保存到块库…")
        self.library_button.setVisible(save_to_library is not None)
        self.library_button.clicked.connect(self._save_selected)
        self.message = QLabel()
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        self.remove_button.clicked.connect(self._remove_selected)
        self.rename_button.clicked.connect(self._rename_selected)
        self.definition_field.currentIndexChanged.connect(self._select_definition)
        layout = QVBoxLayout(self)
        layout.addWidget(self.definition_field)
        layout.addWidget(self.name_field)
        layout.addWidget(self.rename_button)
        layout.addWidget(self.remove_button)
        layout.addWidget(self.library_button)
        layout.addWidget(self.message)
        layout.addWidget(close)
        self._refresh()

    def _refresh(self) -> None:
        view = self._snapshot()
        self._displayed = {
            definition.definition_id: (
                definition,
                sum(
                    item.definition_id == definition.definition_id for item in view.block_instances
                ),
            )
            for definition in view.block_definitions
        }
        self.definition_field.blockSignals(True)
        self.definition_field.clear()
        for definition in view.block_definitions:
            count = self._displayed[definition.definition_id][1]
            self.definition_field.addItem(
                f"{definition.name}（{count} 个实例）", definition.definition_id
            )
        self.definition_field.blockSignals(False)
        self.remove_button.setEnabled(bool(view.block_definitions))
        self.library_button.setEnabled(bool(view.block_definitions))
        self.rename_button.setEnabled(bool(view.block_definitions))
        self._select_definition()

    def _select_definition(self) -> None:
        identity = self.definition_field.currentData()
        displayed = self._displayed.get(identity) if isinstance(identity, str) else None
        self.name_field.setText(displayed[0].name if displayed is not None else "")

    def _ensure_current(self, identity: str) -> bool:
        view = self._snapshot()
        current = next(
            (item for item in view.block_definitions if item.definition_id == identity), None
        )
        count = sum(item.definition_id == identity for item in view.block_instances)
        if current is not None and self._displayed.get(identity) == (current, count):
            return True
        self._refresh()
        index = self.definition_field.findData(identity)
        if index >= 0:
            self.definition_field.setCurrentIndex(index)
        self.message.setText("块定义或实例数已变化，列表已刷新，请重新操作。")
        return False

    def _rename_selected(self) -> None:
        identity = self.definition_field.currentData()
        if not isinstance(identity, str):
            self.message.setText("请选择块定义。")
            return
        try:
            if not self._ensure_current(identity):
                return
            self._rename(identity, self.name_field.text().strip())
            self._refresh()
            self.definition_field.setCurrentIndex(self.definition_field.findData(identity))
            self.message.setText("已暂存重命名；可撤销或完成草稿提交。")
        except (KeyError, ValueError, ValidationError) as exc:
            self.message.setText(str(exc))

    def _save_selected(self) -> None:
        identity = self.definition_field.currentData()
        if not isinstance(identity, str) or self._save_to_library is None:
            self.message.setText("请选择块定义。")
            return
        try:
            if self._ensure_current(identity):
                self._save_to_library(identity)
        except (KeyError, OSError, ValueError, ValidationError) as exc:
            self.message.setText(str(exc))

    def _remove_selected(self) -> None:
        identity = self.definition_field.currentData()
        if not isinstance(identity, str):
            self.message.setText("请选择块定义。")
            return
        try:
            if not self._ensure_current(identity):
                return
            self._remove(identity)
            self._refresh()
            self.message.setText("已暂存删除；可撤销或完成草稿提交。")
        except (KeyError, ValueError, ValidationError) as exc:
            self.message.setText(str(exc))


def _number(*, minimum: float = -1e12, maximum: float = 1e12, value: float = 0) -> QDoubleSpinBox:
    field = QDoubleSpinBox()
    field.setDecimals(8)
    field.setRange(minimum, maximum)
    field.setValue(value)
    return field


class BlockCreateDialog(QDialog):
    """Capture a block name, base point and source handling."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("创建块")
        self.name_field = QLineEdit()
        self.base_x, self.base_y = _number(), _number()
        self.pick_point_button = QPushButton("在画布指定基点")
        self.pick_point_button.clicked.connect(lambda: self.done(PICK_POINT))
        self.source_mode = QComboBox()
        self.source_mode.addItem("转为块", True)
        self.source_mode.addItem("保留源对象", False)
        self.source_hint = QLabel(
            "块仅包含几何和文字。几何存在尺寸或约束时，可选择“保留源对象”；"
            "该选项只创建块定义，原对象及其关联保持不变。"
        )
        self.source_hint.setWordWrap(True)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.validate_creation: Callable[[], str | None] | None = None
        form = QFormLayout()
        form.addRow("名称", self.name_field)
        form.addRow("基点 X / mm", self.base_x)
        form.addRow("基点 Y / mm", self.base_y)
        form.addRow(self.pick_point_button)
        form.addRow("源对象", self.source_mode)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_valid)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.source_hint)
        layout.addWidget(self.message)
        layout.addWidget(buttons)

    def _accept_valid(self) -> None:
        if not self.name_field.text().strip():
            self.message.setText("请输入块名称。")
            return
        if self.validate_creation is not None:
            message = self.validate_creation()
            if message:
                self.message.setText(message)
                return
        self.accept()


class BlockInsertDialog(QDialog):
    """Capture an existing definition and positive uniform placement transform."""

    def __init__(
        self,
        definitions: tuple[BlockDefinition, ...],
        parent: QWidget | None = None,
        *,
        allow_library: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("插入块")
        self.definition_field = QComboBox()
        for item in definitions:
            self.definition_field.addItem(item.name, item.definition_id)
        self.x_field, self.y_field = _number(), _number()
        self.pick_point_button = QPushButton("在画布指定插入点")
        self.pick_point_button.clicked.connect(lambda: self.done(PICK_POINT))
        self.rotation_field = _number()
        self.scale_field = PreservingDoubleSpinBox()
        self.scale_field.setDecimals(8)
        self.scale_field.setRange(0.00000001, 1e9)
        self.scale_field.setValue(1)
        self.scale_exact_button = QPushButton("精确输入比例")
        self.scale_notice = QLabel()
        self.scale_exact_button.clicked.connect(self._enter_exact_scale)
        self.scale_field.retained_changed.connect(self._update_scale_notice)
        form = QFormLayout()
        form.addRow("块定义", self.definition_field)
        self.library_button = QPushButton("从块库选择…")
        self.library_button.setVisible(allow_library)
        self.library_button.clicked.connect(lambda: self.done(OPEN_BLOCK_LIBRARY))
        form.addRow(self.library_button)
        form.addRow("插入点 X / mm", self.x_field)
        form.addRow("插入点 Y / mm", self.y_field)
        form.addRow(self.pick_point_button)
        form.addRow("角度 / °", self.rotation_field)
        form.addRow("正等比比例", self.scale_field)
        form.addRow(self.scale_exact_button)
        form.addRow(self.scale_notice)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_valid)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _update_scale_notice(self) -> None:
        retained = self.scale_field.retained_value
        self.scale_notice.setText("" if retained is None else f"实际比例：{retained!r}")

    def _enter_exact_scale(self) -> None:
        error = self.scale_field.request_exact_value("正等比比例", positive=True)
        if error is not None:
            self.scale_notice.setText(error)

    def _accept_valid(self) -> None:
        if self.scale_field.input_error is not None:
            self.scale_notice.setText(self.scale_field.input_error)
            return
        self.accept()
