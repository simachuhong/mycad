# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Avoid redrawing the drawing canvas while a toolbar is being dragged."""

from __future__ import annotations

from functools import partial
from typing import cast, override

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QDrag, QGuiApplication, QKeyEvent, QMouseEvent, QWindow
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QStyle,
    QStyleOptionToolBar,
    QToolBar,
    QWidget,
)


def _start_wayland_system_move(toolbar: QToolBar) -> bool:
    """Ask the Wayland compositor to move an already floating toolbar."""
    if not QGuiApplication.platformName().lower().startswith("wayland"):
        return False
    window = cast("QWindow | None", toolbar.windowHandle())
    return window is not None and window.startSystemMove()


class ToolbarDragRepaintGuard(QObject):
    """Defer canvas paints during native toolbar drags without intercepting them."""

    def __init__(self, owner: QWidget, canvas: QWidget, toolbars: tuple[QToolBar, ...]) -> None:
        super().__init__(owner)
        self._owner = owner
        self._canvas = canvas
        self._toolbars: tuple[QToolBar, ...] = ()
        self._active = False
        self._was_enabled = False
        self._drag_toolbar: QToolBar | None = None
        self._platform_drag: QDrag | None = None
        self._press_global = QPoint()
        owner.destroyed.connect(self.finish)
        owner.installEventFilter(self)
        self.register(toolbars)

    def register(self, toolbars: tuple[QToolBar, ...]) -> None:
        for toolbar in toolbars:
            if toolbar in self._toolbars:
                continue
            self._toolbars = (*self._toolbars, toolbar)
            toolbar.installEventFilter(self)

    def finish(self) -> None:
        if not self._active:
            return
        self._active = False
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        if self._was_enabled:
            self._canvas.setUpdatesEnabled(True)
        self._was_enabled = False
        self._drag_toolbar = None
        self._platform_drag = None

    def _watch_platform_drag(self) -> None:
        if not self._active or self._drag_toolbar is None:
            return
        for drag in self._drag_toolbar.findChildren(
            QDrag, options=Qt.FindChildOption.FindDirectChildrenOnly
        ):
            if drag is not self._platform_drag:
                self._platform_drag = drag
                drag.destroyed.connect(partial(self._platform_drag_ended, drag))

    def _platform_drag_ended(self, drag: QDrag, _object: QObject | None = None) -> None:
        if drag is self._platform_drag:
            self.finish()

    def _snap_edge_hover(self, event: QMouseEvent) -> None:
        bar = self._drag_toolbar
        if bar is None or QGuiApplication.platformName().lower() != "xcb":
            return
        point = event.globalPosition().toPoint()
        if (point - self._press_global).manhattanLength() < QApplication.startDragDistance():
            return
        host = bar.parentWidget()
        if not isinstance(host, QMainWindow):
            return
        local = host.mapFromGlobal(point)
        rect = host.rect()
        margin = 16
        if rect.contains(local) or not rect.adjusted(-margin, -margin, margin, margin).contains(
            local
        ):
            return
        distances = (
            (abs(local.x() - rect.left()), Qt.ToolBarArea.LeftToolBarArea),
            (abs(local.x() - rect.right()), Qt.ToolBarArea.RightToolBarArea),
            (abs(local.y() - rect.top()), Qt.ToolBarArea.TopToolBarArea),
            (abs(local.y() - rect.bottom()), Qt.ToolBarArea.BottomToolBarArea),
        )
        distance, area = min(distances, key=lambda item: item[0])
        if distance > margin or not bar.allowedAreas() & area:
            return
        x = max(rect.left(), min(local.x(), rect.right()))
        y = max(rect.top(), min(local.y(), rect.bottom()))
        if area == Qt.ToolBarArea.LeftToolBarArea:
            x = min(rect.right(), rect.left() + 8)
        elif area == Qt.ToolBarArea.RightToolBarArea:
            x = max(rect.left(), rect.right() - 8)
        elif area == Qt.ToolBarArea.TopToolBarArea:
            y = min(rect.bottom(), rect.top() + 8)
        else:
            y = max(rect.top(), rect.bottom() - 8)
        target = host.mapToGlobal(QPoint(x, y))
        hover = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(bar.mapFromGlobal(target)),
            QPointF(target),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            event.modifiers(),
        )
        # Let Qt's normal drag handler choose the slot and finish the layout.
        QApplication.sendEvent(bar, hover)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if self._active:
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and isinstance(event, QMouseEvent)
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._snap_edge_hover(event)
            if watched is self._drag_toolbar and event.type() == QEvent.Type.ChildAdded:
                # Qt constructs QDrag as a toolbar child on Wayland. ChildAdded
                # arrives before construction finishes, so inspect it in the drag loop.
                QTimer.singleShot(0, self._watch_platform_drag)
            if (
                (
                    event.type() == QEvent.Type.MouseButtonRelease
                    and isinstance(event, QMouseEvent)
                    and event.button() == Qt.MouseButton.LeftButton
                )
                or (
                    event.type() == QEvent.Type.KeyPress
                    and isinstance(event, QKeyEvent)
                    and event.key() == Qt.Key.Key_Escape
                )
                or event.type() == QEvent.Type.ApplicationDeactivate
                or (watched is self._owner and event.type() == QEvent.Type.Hide)
                or (watched in self._toolbars and event.type() == QEvent.Type.UngrabMouse)
            ):
                self.finish()
        elif (
            event.type() == QEvent.Type.MouseButtonPress
            and watched in self._toolbars
            and isinstance(watched, QToolBar)
            and watched.isMovable()
            and self._owner.isVisible()
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
        ):
            option = QStyleOptionToolBar()
            watched.initStyleOption(option)
            handle = watched.style().subElementRect(
                QStyle.SubElement.SE_ToolBarHandle, option, watched
            )
            if handle.contains(event.position().toPoint()):
                if watched.isFloating() and _start_wayland_system_move(watched):
                    event.accept()
                    return True
                self._active = True
                self._drag_toolbar = watched
                self._press_global = event.globalPosition().toPoint()
                self._was_enabled = self._canvas.updatesEnabled()
                if self._was_enabled:
                    self._canvas.setUpdatesEnabled(False)
                app = QApplication.instance()
                if app is not None:
                    app.installEventFilter(self)
        return False
