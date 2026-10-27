# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Scrollable command fields with permanently reachable confirmation controls."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QToolBar,
    QWidget,
)


class _FieldsArea(QScrollArea):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setSingleShot(True)
        self._reveal_timer.timeout.connect(self._reveal_focus)

    def _reveal_focus(self) -> None:
        field = QApplication.focusWidget()
        if field is None or not self.isAncestorOf(field):
            return
        parent = field.parentWidget()
        if isinstance(parent, QAbstractSpinBox):
            field = parent
        content = self.widget()
        if content is None:
            return
        left = field.mapTo(content, QPoint()).x()
        right = left + field.width()
        scrollbar = self.horizontalScrollBar()
        visible_width = self.viewport().width()
        if left < scrollbar.value() + 12:
            scrollbar.setValue(left - 12)
        elif right > scrollbar.value() + visible_width - 12:
            scrollbar.setValue(right - visible_width + 12)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.FocusIn and isinstance(watched, QWidget):
            self.ensureWidgetVisible(watched, 12, 0)
            # Qt also scrolls the spin box's line edit during focus dispatch.
            # Reveal the whole field after that, including its unit and arrows.
            self._reveal_timer.start(0)
        return super().eventFilter(watched, event)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(480, 54)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(120, 54)


def install_command_strip(
    toolbar: QToolBar, fields: QWidget, actions: Sequence[QWidget]
) -> QWidget:
    """Keep actions outside the scrolling fields, including at 200% scaling.

    QScrollArea automatically reveals a child receiving keyboard focus. The
    visible horizontal scrollbar also exposes every field with the mouse;
    no duplicate controls or popup can steal the command's input state.
    """
    content = QWidget(toolbar)
    content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    layout = QHBoxLayout(content)
    layout.setContentsMargins(0, 0, 6, 0)
    layout.setSpacing(6)
    scroll = _FieldsArea(content)
    scroll.setObjectName("commandFieldsScroll")
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    fields.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
    scroll.setWidget(fields)
    for field in fields.findChildren(QWidget):
        field.installEventFilter(scroll)
    layout.addWidget(scroll, 1)
    for action in actions:
        layout.addWidget(action)
    toolbar.addWidget(content)
    toolbar.setFixedHeight(62)
    return content
