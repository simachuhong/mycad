# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Shell smoke tests (plan todo 4): five zones + GL capability + clean exit.

The GL probe intentionally locks ``QOpenGLContext.create()`` success in
wave 1 so the three T1 CI platforms expose their offscreen-GL reality now
instead of at todo 9 (plan text, acceptance criteria).
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
from PySide6.QtWidgets import QApplication, QDockWidget, QStatusBar

from mycad.ui.main_window import MainWindow


def _zone_object_names(window: MainWindow) -> set[str]:
    central = window.centralWidget()
    assert central is not None, "central viewportHost widget is required"
    return {
        central.objectName(),
        window.left_dock.objectName(),
        window.right_dock.objectName(),
        window.bottom_dock.objectName(),
        window.main_toolbar.objectName(),
    }


def test_shell_builds_the_five_zones(qapp: QApplication) -> None:  # noqa: ARG001
    window = MainWindow()
    window.show()
    # Object names are the identity contract the rest of phase-1 binds to;
    # locked as literals (not module constants) so a rename inside
    # main_window.py cannot drift past this guard.
    assert _zone_object_names(window) == {
        "viewportHost",
        "leftPanelDock",
        "rightPanelDock",
        "bottomPanelDock",
        "mainToolBar",
    }
    status = window.statusBar()
    assert isinstance(status, QStatusBar)
    # UI初稿 §2: every dock starts floatable and closable; defaults satisfy
    # both, and this probe fails if a later todo quietly strips them.
    for dock in (window.left_dock, window.right_dock, window.bottom_dock):
        features_mask = (
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        assert dock.features() & features_mask


def test_offscreen_gl_context_creation(qapp: QApplication) -> None:  # noqa: ARG001
    surface = QOffscreenSurface()
    surface.setScreen(qapp.primaryScreen())
    surface.create()
    assert surface.isValid(), "QOffscreenSurface itself failed to create"
    context = QOpenGLContext()
    assert context.create(), "offscreen GL is unavailable on this platform"
    assert context.makeCurrent(surface), "context could not bind the offscreen surface"


def test_qtimer_single_shot_exits_the_loop_cleanly(qapp: QApplication) -> None:  # noqa: ARG001
    window = MainWindow()
    window.show()
    QTimer.singleShot(50, qapp.quit)
    assert qapp.exec() == 0
