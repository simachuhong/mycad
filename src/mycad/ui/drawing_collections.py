# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Small user interface for editing one independent drawing group."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef

_MEMBER_LABELS = {
    "geometry": "几何对象",
    "dimension": "尺寸标注",
    "text": "文字",
    "tolerance": "公差框",
    "datum": "基准标识",
    "reference_dimension": "参考尺寸",
    "raster": "图片",
    "block_instance": "块实例",
}


class DrawingGroupEditor(QDialog):
    """Edit group properties and add or remove the canvas's direct selection."""

    def __init__(
        self,
        group: DrawingGroup,
        selection: tuple[DrawingObjectRef, ...],
        parent: QWidget | None = None,
        *,
        member_labels: Mapping[DrawingObjectRef, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("组管理")
        self.setMinimumWidth(540)
        self.resize(600, 500)
        self._group = group
        self._selection = selection
        self._member_labels = dict(member_labels or {})
        self._members = list(group.members)
        self.name_field = QLineEdit(group.name or "")
        self.name_field.setPlaceholderText("留空则为匿名组")
        self.description_field = QLineEdit(group.description)
        self.description_field.setPlaceholderText("可选：填写用途或备注")
        self.selectable_field = QCheckBox("启用组选择")
        self.selectable_field.setChecked(group.selectable)
        self.member_list = QListWidget()
        self.member_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.member_list.setMinimumHeight(180)
        self.member_count = QLabel()
        self.message = QLabel()
        self.message.setWordWrap(True)
        form = QFormLayout()
        form.addRow("组名称", self.name_field)
        form.addRow("说明", self.description_field)
        form.addRow(self.selectable_field)
        self.add_selection_button = QPushButton("加入画布所选对象")
        self.add_selection_button.clicked.connect(self.add_selection)
        self.add_selection_button.setEnabled(bool(selection))
        self.remove_members_button = QPushButton("移除列表选中项")
        self.remove_members_button.setEnabled(False)
        self.remove_members_button.clicked.connect(self.remove_selected_members)
        self.member_list.itemSelectionChanged.connect(self._sync_selection_buttons)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_selection_button)
        buttons.addWidget(self.remove_members_button)
        buttons.addStretch()
        self.confirm = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.confirm.accepted.connect(self._accept_valid)
        self.confirm.rejected.connect(self.reject)
        ok = self.confirm.button(QDialogButtonBox.StandardButton.Ok)
        cancel = self.confirm.button(QDialogButtonBox.StandardButton.Cancel)
        ok.setText("保存")
        cancel.setText("取消")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addLayout(form)
        layout.addWidget(self.member_count)
        layout.addWidget(self.member_list, 1)
        selection_hint = QLabel(
            f"打开窗口前在画布中选中了 {len(selection)} 个对象。"
            "需要添加其他对象时，请先关闭窗口并在画布中选择。"
        )
        selection_hint.setWordWrap(True)
        layout.addWidget(selection_hint)
        layout.addLayout(buttons)
        layout.addWidget(self.message)
        layout.addWidget(self.confirm)
        self._refresh()

    def _refresh(self) -> None:
        self.member_list.clear()
        counts: dict[str, int] = {}
        for item in self._members:
            label = self._member_labels.get(item, _MEMBER_LABELS.get(item.kind, "对象"))
            counts[label] = counts.get(label, 0) + 1
            row = QListWidgetItem(f"{label} {counts[label]}")
            owner = f"\n草图 ID：{item.sketch_id}" if item.sketch_id is not None else ""
            row.setToolTip(f"{label}\n对象 ID：{item.object_id}{owner}")
            self.member_list.addItem(row)
        self.member_count.setText(f"组成员 · {len(self._members)} 个")
        self._sync_selection_buttons()
        self.message.setText(
            "组没有成员；确认后解散组，成员对象保留。" if not self._members else ""
        )

    def _sync_selection_buttons(self) -> None:
        self.remove_members_button.setEnabled(bool(self.member_list.selectedItems()))

    def remove_selected_members(self) -> None:
        rows = {self.member_list.row(item) for item in self.member_list.selectedItems()}
        self._members = [member for index, member in enumerate(self._members) if index not in rows]
        self._refresh()

    def add_selection(self) -> None:
        for item in self._selection:
            if item not in self._members:
                self._members.append(item)
        self._refresh()

    def remove_selection(self) -> None:
        self._members = [item for item in self._members if item not in self._selection]
        self._refresh()

    @property
    def has_members(self) -> bool:
        return bool(self._members)

    def updated_group(self) -> DrawingGroup:
        name = self.name_field.text().strip() or None
        return replace(
            self._group,
            members=tuple(self._members),
            name=name,
            description=self.description_field.text(),
            selectable=self.selectable_field.isChecked(),
        )

    def _accept_valid(self) -> None:
        if not self.has_members:
            self.accept()
            return
        try:
            self.updated_group()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        self.accept()
