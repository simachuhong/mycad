# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Five-zone main window skeleton (UI初稿 §2/§10).

The window guarantees only the widget identity contract that the rest of
the phase-1 UI tests against: five named zones plus a resident status
bar. Panel contents land in later todos (menus/toolbar behaviour, left
palette, right tabs, viewport), so this placeholder imports nothing from
``mycad.core`` / ``mycad.geom`` yet.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QMainWindow,
    QStatusBar,
    QToolBar,
    QWidget,
)

CENTER_OBJECT_NAME = "viewportHost"
LEFT_DOCK_OBJECT_NAME = "leftPanelDock"
RIGHT_DOCK_OBJECT_NAME = "rightPanelDock"
BOTTOM_DOCK_OBJECT_NAME = "bottomPanelDock"
TOOLBAR_OBJECT_NAME = "mainToolBar"


class MainWindow(QMainWindow):
    """Skeleton shell: toolbar + viewportHost centre + three docks + status bar.

    Dock features keep their Qt defaults (closable/movable/floatable) —
    UI初稿 §2 requires docks to be floatable and closable, and the save/
    restore behaviour of that default set is asserted in tests/ui.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MyCAD")

        # Center: real viewport replaces this host in todo 9; five-region
        # layout stores an empty host widget (placeholder).
        center = QWidget()
        center.setObjectName(CENTER_OBJECT_NAME)
        self.setCentralWidget(center)

        self.main_toolbar = QToolBar("main")
        self.main_toolbar.setObjectName(TOOLBAR_OBJECT_NAME)
        # UI初稿 §10: movable, dockable to all four edges.
        self.main_toolbar.setMovable(True)
        self.main_toolbar.setFloatable(True)
        self.main_toolbar.setAllowedAreas(Qt.ToolBarArea.AllToolBarAreas)
        self.addToolBar(self.main_toolbar)

        self.left_dock = QDockWidget()
        self.left_dock.setObjectName(LEFT_DOCK_OBJECT_NAME)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock)

        self.right_dock = QDockWidget()
        self.right_dock.setObjectName(RIGHT_DOCK_OBJECT_NAME)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.right_dock)

        self.bottom_dock = QDockWidget()
        self.bottom_dock.setObjectName(BOTTOM_DOCK_OBJECT_NAME)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.bottom_dock)

        # Resident single-line status bar (UI初稿 §2/§8); the five status
        # fields are wired to bus signals in a later todo.
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
