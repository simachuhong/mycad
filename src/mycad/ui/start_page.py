# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Document creation and opening entry points for the start page."""

from __future__ import annotations

from functools import partial
from typing import cast

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mycad.core.document_kinds import DocumentKind
from mycad.ui.cad_icons import current_icon_theme, set_button_icon
from mycad.ui.document_session import KIND_LABELS
from mycad.ui.recent_documents import RecentDocument
from mycad.ui.theme import ThemeName, theme_tokens


class StartPage(QWidget):
    """Present document types without creating or owning a document."""

    create_requested = Signal(str)
    open_requested = Signal()
    resume_requested = Signal()
    recent_open_requested = Signal(str)
    recent_locate_requested = Signal(str)
    recent_remove_requested = Signal(str)
    recent_clear_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget(scroll)
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)
        title = QLabel("MyCAD")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(title)
        layout.addWidget(QLabel("创建文档"))
        cards = QGridLayout()
        cards.setSpacing(12)
        self.drawing_button = self._card("二维图", "sketch", "独立平面绘图、图层与标注")
        self.engineering_button = self._card("工程图", "document", "从模型建立视图、尺寸与图纸")
        self.part_button = self._card("三维零件", "box", "草图、特征与实体建模")
        self.assembly_button = self._card(
            "三维装配\n规划中，暂不可创建", "group", "组织零部件与装配关系"
        )
        self.assembly_button.setEnabled(False)
        self.set_theme(current_icon_theme())
        for index, button in enumerate(
            (self.drawing_button, self.engineering_button, self.part_button, self.assembly_button)
        ):
            cards.addWidget(button, index // 2, index % 2)
        layout.addLayout(cards)
        self.drawing_button.clicked.connect(partial(self._request_create, "sketch"))
        self.engineering_button.clicked.connect(partial(self._request_create, "drawing"))
        self.part_button.clicked.connect(partial(self._request_create, "part"))
        self.open_button = QPushButton("打开文件…")
        self.open_button.clicked.connect(self.open_requested.emit)
        layout.addWidget(self.open_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.resume_button = QPushButton("返回当前文档")
        self.resume_button.clicked.connect(self.resume_requested.emit)
        self.resume_button.hide()
        layout.addWidget(self.resume_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(QLabel("最近文档"))
        self.recent_list = QListWidget()
        self.recent_list.setMinimumHeight(120)
        self.recent_list.itemDoubleClicked.connect(self._on_recent_double_clicked)
        layout.addWidget(self.recent_list)
        actions = QHBoxLayout()
        self.recent_open_button = QPushButton("打开")
        self.recent_locate_button = QPushButton("定位文件…")
        self.recent_remove_button = QPushButton("移除记录")
        self.recent_clear_button = QPushButton("清除最近记录")
        self.recent_open_button.clicked.connect(lambda: self._emit_recent("open"))
        self.recent_locate_button.clicked.connect(lambda: self._emit_recent("locate"))
        self.recent_remove_button.clicked.connect(lambda: self._emit_recent("remove"))
        self.recent_clear_button.clicked.connect(self.recent_clear_requested.emit)
        for button in (
            self.recent_open_button,
            self.recent_locate_button,
            self.recent_remove_button,
            self.recent_clear_button,
        ):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.recent_list.currentRowChanged.connect(self._sync_recent_actions)
        self._sync_recent_actions(-1)
        layout.addStretch()

    def _sync_recent_actions(self, row: int) -> None:
        for button in (
            self.recent_open_button,
            self.recent_locate_button,
            self.recent_remove_button,
        ):
            button.setEnabled(row >= 0)
        self.recent_clear_button.setEnabled(self.recent_list.count() > 0)

    def set_recent_documents(self, records: tuple[RecentDocument, ...]) -> None:
        self.recent_list.clear()
        for record in records:
            item = QListWidgetItem(
                f"{record.path.name} · {KIND_LABELS[record.kind]}\n"
                f"{record.path} · {record.opened_at}"
            )
            item.setData(Qt.ItemDataRole.UserRole, str(record.path))
            self.recent_list.addItem(item)
        self._sync_recent_actions(self.recent_list.currentRow())

    def _on_recent_double_clicked(self, _item: QListWidgetItem) -> None:
        self._emit_recent("open")

    def _emit_recent(self, action: str) -> None:
        item = cast("QListWidgetItem | None", self.recent_list.currentItem())
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(path, str):
            return
        if action == "open":
            self.recent_open_requested.emit(path)
        elif action == "locate":
            self.recent_locate_requested.emit(path)
        elif action == "remove":
            self.recent_remove_requested.emit(path)

    @staticmethod
    def _card(label: str, icon: str, description: str) -> QToolButton:
        button = QToolButton()
        button.setText(f"{label}\n{description}")
        button.setToolTip(description)
        button.setAccessibleName(f"{label}：{description}")
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setMinimumSize(190, 120)
        button.setIconSize(QSize(36, 36))
        set_button_icon(button, icon)
        return button

    def set_theme(self, theme: ThemeName) -> None:
        """Keep card text, background and states legible after a theme change."""
        tokens = theme_tokens(theme)
        style = (
            f"QToolButton {{ border: 1px solid {tokens.divider}; border-radius: 6px; "
            f"padding: 12px; background: {tokens.panel}; color: {tokens.text}; }}"
            f"QToolButton:hover:enabled {{ border: 2px solid {tokens.focus}; "
            f"background: {tokens.active}; color: {tokens.text}; }}"
            f"QToolButton:focus {{ border: 2px solid {tokens.focus}; }}"
            f"QToolButton:disabled {{ background: {tokens.secondary_panel}; "
            f"color: {tokens.secondary_text}; }}"
        )
        for button in (
            self.drawing_button,
            self.engineering_button,
            self.part_button,
            self.assembly_button,
        ):
            button.setStyleSheet(style)

    def _request_create(self, kind: DocumentKind) -> None:
        self.create_requested.emit(kind)
