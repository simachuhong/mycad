# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Shared workspace messages and compact console tabs."""

from typing import override

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class MessageLabel(QLabel):
    """Persistent prompts and transient cursor readings have separate channels."""

    text_changed = Signal(str)
    transient_changed = Signal(str)

    @override
    def setText(self, text: str) -> None:  # noqa: N802
        changed = self.text() != text
        super().setText(text)
        self.setToolTip(text)
        if changed:
            self.text_changed.emit(text)

    def set_transient_text(self, text: str) -> None:
        super().setText(text)
        self.setToolTip(text)
        self.transient_changed.emit(text)


def drawing_message(text: str) -> str:
    """Describe internal drawing relationships in user-facing object terms."""
    return (
        text.replace("跨草图相切", "对象相切")
        .replace("跨草图图元", "关联对象")
        .replace("跨草图尺寸", "关联尺寸")
        .replace("跨草图候选", "关联候选")
        .replace("跨草图", "对象关联")
    )


class DrawingMessageLabel(MessageLabel):
    """Show internal drawing-relationship errors using object terminology."""

    @override
    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(drawing_message(text))


class InformationPanel(QWidget):
    """Bounded plain-text history; cursor movement never enters this log."""

    def __init__(self) -> None:
        super().__init__()
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(500)
        self._last_message = ""
        clear = QPushButton("清空信息")
        clear.clicked.connect(self.clear)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(clear)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.output, 1)
        layout.addLayout(row)

    def append_message(self, message: str) -> None:
        if message and message != self._last_message:
            self.output.appendPlainText(message)
            self._last_message = message

    def clear(self) -> None:
        self.output.clear()
        self._last_message = ""


class AiChatPanel(QWidget):
    """Conversation draft surface until an AI service is configured."""

    def __init__(self) -> None:
        super().__init__()
        self.connection_label = QLabel("未连接 AI 服务 · 连接后可发送消息")
        self.connection_label.setWordWrap(True)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("AI 对话记录将显示在这里。当前尚未配置服务，不会发送消息。")
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("输入绘图需求（可先保留草稿）")
        self.input.setMaximumHeight(64)
        self.send_button = QPushButton("发送")
        self.send_button.setEnabled(False)
        self.send_button.setToolTip("尚未连接 AI 服务。")
        compose = QHBoxLayout()
        compose.addWidget(self.input, 1)
        compose.addWidget(self.send_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.connection_label)
        layout.addWidget(self.output, 1)
        layout.addLayout(compose)

    def clear(self) -> None:
        self.output.clear()
        self.input.clear()


class _ConsoleTabBar(QTabBar):
    """Capture clicking the active tab before Qt changes the current index."""

    active_tab_clicked = Signal()

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.tabAt(event.position().toPoint()) == self.currentIndex()
        ):
            self.active_tab_clicked.emit()
        super().mousePressEvent(event)


class WorkspaceConsole(QTabWidget):
    """Collapse to the tab strip without replacing or clearing any page."""

    expanded_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.expanded = False
        self.expanded_height = 240
        self.setObjectName("bottomTabs")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        bar = _ConsoleTabBar()
        bar.setExpanding(False)
        self.setTabBar(bar)
        self.collapse_button = QToolButton()
        self.collapse_button.setText("展开")
        self.collapse_button.clicked.connect(lambda: self.set_expanded(not self.expanded))
        self.setCornerWidget(self.collapse_button)
        bar.active_tab_clicked.connect(lambda: self.set_expanded(not self.expanded))
        self.currentChanged.connect(self._page_changed)

    def _page_changed(self, _index: int) -> None:
        self.set_expanded(True)

    def set_expanded(self, expanded: bool) -> None:
        if self.expanded and not expanded and self.isVisible():
            self.expanded_height = max(160, self.height())
        self.expanded = expanded
        if self.count():
            self.currentWidget().setVisible(expanded)
        if expanded:
            self.setMinimumHeight(160)
            self.setMaximumHeight(16_777_215)
        else:
            self.setFixedHeight(max(self.tabBar().sizeHint().height(), 26) + 4)
        self.collapse_button.setText("收起" if expanded else "展开")
        self.collapse_button.setToolTip("收起控制台" if expanded else "展开当前页")
        self.expanded_changed.emit(expanded)

    @override
    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 160 if self.expanded else max(self.tabBar().sizeHint().height(), 26) + 4)

    def show_page(self, page: QWidget) -> None:
        self.setCurrentWidget(page)
        self.set_expanded(True)

    def capture_state(self) -> tuple[bool, int, int]:
        height = self.expanded_height
        if self.expanded and self.isVisible():
            height = max(160, min(self.height(), 2000))
        return self.expanded, max(0, self.currentIndex()), max(160, min(height, 2000))

    def restore_state(self, state: tuple[bool, int, int]) -> None:
        expanded, page, height = state
        self.expanded_height = height
        if 0 <= page < self.count():
            self.setCurrentIndex(page)
        self.set_expanded(expanded)
