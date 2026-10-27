# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Permanent workspace containers; switching never destroys their content."""

from typing import Literal

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

WorkspaceId = Literal["sketch", "drawing", "model"]
WORKSPACES: tuple[WorkspaceId, ...] = ("sketch", "drawing", "model")


class WorkspaceTabs(QTabWidget):
    workspace_changed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDocumentMode(True)
        self.setMovable(False)
        self.setTabsClosable(False)
        self._active: WorkspaceId = "model"
        self._contents: dict[WorkspaceId, QWidget] = {}
        for label in ("平面草图", "工程图", "3D图"):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            self.addTab(page, label)
        self.setCurrentIndex(2)
        self.currentChanged.connect(self._changed)

    @property
    def active_workspace(self) -> WorkspaceId:
        return self._active

    def activate(self, workspace: WorkspaceId) -> None:
        index = WORKSPACES.index(workspace)
        if self.isTabEnabled(index):
            self.setCurrentIndex(index)

    def set_content(self, workspace: WorkspaceId, widget: QWidget | None) -> None:
        old = self._contents.pop(workspace, None)
        if old is widget and widget is not None:
            self._contents[workspace] = widget
            return
        page = self.widget(WORKSPACES.index(workspace))
        assert page is not None
        layout = page.layout()
        assert layout is not None
        if old is not None:
            layout.removeWidget(old)
            old.hide()
            old.setParent(self)
        if widget is not None:
            self._contents[workspace] = widget
            layout.addWidget(widget)
            widget.setVisible(self.active_workspace == workspace)

    def content(self, workspace: WorkspaceId) -> QWidget | None:
        return self._contents.get(workspace)

    def _changed(self, index: int) -> None:
        previous = self._active
        grabber = QWidget.mouseGrabber()
        old = self.content(previous)
        if (
            grabber is not None
            and old is not None
            and (grabber is old or old.isAncestorOf(grabber))
        ):
            grabber.releaseMouse()
        self._active = WORKSPACES[index]
        content = self.content(self._active)
        if content is not None:
            content.show()
        self.workspace_changed.emit(previous, self._active)
