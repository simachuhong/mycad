# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Collect close choices without destroying any editable document."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mycad.ui.document_session import SessionDocument


class UnsavedDocumentsDialog(QDialog):
    def __init__(self, entries: tuple[SessionDocument, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("未保存的文档")
        self.resize(580, 320)
        self.choices: dict[str, str] | None = None
        self.entries = entries
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("勾选要保存的文档；未勾选的修改将在成功退出后放弃。"))
        self.list = QListWidget()
        for entry in entries:
            pending_view = entry.workbench is not None and entry.workbench.has_pending_view_edit
            item = QListWidgetItem(entry.label + (" · 视图操作未确认" if pending_view else ""))
            location = str(entry.path) if entry.path else "尚未命名"
            item.setToolTip(
                f"{location}\n请先回到该文档完成或取消视图操作。" if pending_view else location
            )
            item.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(item)
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        for text, handler in (
            ("保存选中并退出", self._save),
            ("放弃全部并退出", self._discard),
            ("取消退出", self.reject),
        ):
            button = QPushButton(text)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def _save(self) -> None:
        self.choices = {
            entry.loaded.document.document_id: "save"
            if self.list.item(i).checkState() == Qt.CheckState.Checked
            else "discard"
            for i, entry in enumerate(self.entries)
        }
        self.accept()

    def _discard(self) -> None:
        self.choices = {entry.loaded.document.document_id: "discard" for entry in self.entries}
        self.accept()
