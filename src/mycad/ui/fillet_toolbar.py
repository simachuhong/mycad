# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Compact, viewport-external controls for the continuous fillet tool."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QToolBar, QWidget

from mycad.ui.cad_icons import set_button_icon
from mycad.ui.command_strip import install_command_strip


class FilletRadiusEdit(QLineEdit):
    """A small radius editor with an Escape-to-revert edit gesture."""

    escape_pressed = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """Reserve Escape for reverting the in-progress radius edit."""
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class FilletCommandBar(QToolBar):
    """One-line fillet controls placed above, never over, the 3D viewport."""

    radius_changed = Signal(str)
    radius_accepted = Signal()
    commit_requested = Signal()
    cancel_requested = Signal()
    clear_selection_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("圆角", parent)
        self.setObjectName("filletCommandBar")
        self.setMovable(False)
        self.setFloatable(False)
        self.setAllowedAreas(Qt.ToolBarArea.TopToolBarArea)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        content = QWidget(self)
        content.setObjectName("filletCommandBarContent")

        from PySide6.QtWidgets import QHBoxLayout

        layout = QHBoxLayout(content)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(8)
        title = QLabel("圆角", content)
        title.setStyleSheet("font-weight: 600;")
        self.radius_label = QLabel("R", content)
        self.radius_edit = FilletRadiusEdit(content)
        self.radius_edit.setObjectName("filletRadiusEdit")
        self.radius_edit.setAccessibleName("圆角半径，单位毫米")
        self.radius_edit.setToolTip("输入半径（mm）；输入时 Enter 仅接受数值。视口中按 R 可编辑。")
        self.radius_edit.setFixedWidth(112)
        self.radius_edit.setMaximumHeight(30)
        self.unit_label = QLabel("mm", content)
        self.selection_label = QLabel("选择边", content)
        self.clear_button = QPushButton("清空", content)
        self.clear_button.setToolTip("清空本组选边")
        self.commit_button = QPushButton("完成此组", content)
        set_button_icon(self.commit_button, "confirm")
        self.commit_button.setObjectName("filletCommitButton")
        self.commit_button.setToolTip("提交当前有效预览；视口中按 Enter 或短按右键")
        self.cancel_button = QPushButton("退出", content)
        set_button_icon(self.cancel_button, "cancel")
        self.cancel_button.setObjectName("filletCancelButton")
        layout.addWidget(title)
        layout.addWidget(self.radius_label)
        layout.addWidget(self.radius_edit)
        layout.addWidget(self.unit_label)
        layout.addSpacing(14)
        layout.addWidget(self.selection_label)
        layout.addWidget(self.clear_button)
        layout.addStretch(1)
        install_command_strip(self, content, (self.commit_button, self.cancel_button))

        self.radius_edit.textEdited.connect(self.radius_changed)
        self.radius_edit.editingFinished.connect(self._accept_radius)
        self.radius_edit.escape_pressed.connect(self._revert_radius)
        self.clear_button.clicked.connect(self.clear_selection_requested)
        self.commit_button.clicked.connect(self.commit_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self._accepted_text = "1"
        self.set_selection_count(0)
        self.set_busy(False)

    def radius_text(self) -> str:
        """Current literal shown in the radius editor."""
        return self.radius_edit.text()

    def set_radius(self, value: float) -> None:
        """Set the displayed radius without requesting another edit."""
        text = f"{value:.6f}".rstrip("0").rstrip(".")
        self._accepted_text = text
        self.radius_edit.setText(text)

    def begin_edit(self, initial_text: str | None = None) -> None:
        """Focus the field, replacing its value only for direct numeric input."""
        if initial_text is not None:
            self.radius_edit.setText(initial_text)
            self.radius_changed.emit(initial_text)
        self.radius_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        if initial_text is None:
            self.radius_edit.selectAll()
            self.radius_edit.setCursorPosition(len(self.radius_edit.text()))
        else:
            self.radius_edit.setCursorPosition(len(initial_text))

    def set_selection_count(self, count: int) -> None:
        """Update the visible count without a separate floating palette."""
        self.setProperty("selectionCount", count)
        self.selection_label.setText("选择边" if count == 0 else f"已选 {count} 条边")
        self.commit_button.setEnabled(count > 0 and not self.commit_button.property("busy"))

    def set_preview_valid(self, valid: bool) -> None:
        """Enable confirmation only when the latest preview is current."""
        count = self.selection_count()
        self.commit_button.setEnabled(
            valid and count > 0 and not self.commit_button.property("busy")
        )

    def selection_count(self) -> int:
        """Read the count from its user-facing label state."""
        count = self.property("selectionCount")
        return int(count) if isinstance(count, int) else 0

    def set_busy(self, busy: bool) -> None:
        """Prevent edits during serialized model mutation."""
        self.radius_edit.setEnabled(not busy)
        self.clear_button.setEnabled(not busy)
        self.cancel_button.setEnabled(not busy)
        self.commit_button.setProperty("busy", busy)
        if busy:
            self.commit_button.setEnabled(False)

    def _accept_radius(self) -> None:
        self._accepted_text = self.radius_edit.text()
        self.radius_accepted.emit()

    def _revert_radius(self) -> None:
        self.radius_edit.setText(self._accepted_text)
        self.radius_accepted.emit()
