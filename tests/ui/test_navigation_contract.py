# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Mouse navigation uses the same contract inside and outside commands."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.app import build_app
from mycad.ui.main_window import MainWindow
from mycad.ui.viewport import GLViewport


@pytest.mark.parametrize("modeling", [False, True])
@pytest.mark.parametrize("pan", [False, True])
def test_middle_drag_has_one_navigation_contract(qtbot: QtBot, modeling: bool, pan: bool) -> None:
    view = GLViewport(viewport_port=build_app(discoverers=[]).kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.set_modeling_context_active(modeling)
    before_center = QVector3D(view.opts["center"])
    before_angles = (view.opts["elevation"], view.opts["azimuth"])
    commits: list[None] = []
    view.modeling_commit_requested.connect(lambda: commits.append(None))
    modifiers = Qt.KeyboardModifier.ShiftModifier if pan else Qt.KeyboardModifier.NoModifier
    QTest.mousePress(view, Qt.MouseButton.MiddleButton, modifiers, QPoint(400, 300))
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(430, 320),
        QPointF(430, 320),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.MiddleButton,
        modifiers,
    )
    view.mouseMoveEvent(event)
    QTest.mouseRelease(view, Qt.MouseButton.MiddleButton, modifiers, QPoint(430, 320))
    after_angles = (view.opts["elevation"], view.opts["azimuth"])
    if pan:
        assert QVector3D(view.opts["center"]) != before_center
        assert after_angles == before_angles
    else:
        assert QVector3D(view.opts["center"]) == before_center
        assert after_angles != before_angles
    assert commits == []


def test_left_drag_does_not_orbit_the_model(qtbot: QtBot) -> None:
    view = GLViewport(viewport_port=build_app(discoverers=[]).kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    before = (view.opts["elevation"], view.opts["azimuth"])
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    view.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(200, 200),
            QPointF(200, 200),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    assert (view.opts["elevation"], view.opts["azimuth"]) == before


def test_camera_status_does_not_claim_a_standard_view_after_orbit(qtbot: QtBot) -> None:
    window = MainWindow(services=build_app(discoverers=[]))
    qtbot.addWidget(window)
    view = window.viewport
    assert view is not None
    window.orientation_actions["top"].trigger()
    assert "俯视" in window.status_camera.text()
    view.orbit(10, 5)
    assert "自由" in window.status_camera.text()
    assert not any(action.isChecked() for action in window.orientation_actions.values())
    window.projection_actions["perspective"].trigger()
    assert "透视" in window.status_camera.text()


def test_escape_during_held_box_drag_does_not_fall_through_to_orbit(qtbot: QtBot) -> None:
    view = GLViewport(viewport_port=build_app(discoverers=[]).kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    before = (view.opts["elevation"], view.opts["azimuth"])
    QTest.mousePress(
        view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, QPoint(100, 100)
    )
    QTest.keyClick(view, Qt.Key.Key_Escape)
    view.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(200, 200),
            QPointF(200, 200),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    view.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(220, 220),
            QPointF(220, 220),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    assert (view.opts["elevation"], view.opts["azimuth"]) == before
    assert not view.selection_box_active()
