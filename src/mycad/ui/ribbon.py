# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Reusable action groups for the three-dimensional ribbon."""

from collections.abc import Sequence
from typing import cast

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class RibbonGroup(QWidget):
    """Present shared actions as primary and compact secondary controls."""

    def __init__(
        self,
        title: str,
        primary: Sequence[QAction],
        secondary: Sequence[QAction],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(2)
        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        for column, action in enumerate(primary):
            button = self._button(action, primary=True)
            grid.addWidget(button, 0, column, 2, 1)
        for index, action in enumerate(secondary):
            button = self._button(action, primary=False)
            grid.addWidget(button, index % 2, len(primary) + index // 2)
        layout.addLayout(grid, 1)
        label = QLabel(title, self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

    def _button(self, action: QAction, *, primary: bool) -> QToolButton:
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon
            if primary
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        button.setIconSize(QSize(32, 32) if primary else QSize(16, 16))
        menu = cast("object", action.menu())
        if isinstance(menu, QMenu):
            button.setMenu(menu)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        return button


class RibbonPage(QScrollArea):
    """A ribbon page that remains reachable at narrow window widths."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumHeight(140)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.content = QWidget(self)
        self.content_layout = QHBoxLayout(self.content)
        self.content_layout.setContentsMargins(8, 4, 8, 4)
        self.setWidget(self.content)
