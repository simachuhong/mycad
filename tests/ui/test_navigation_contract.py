# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Mouse navigation uses the same contract inside and outside commands."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.app import build_app
from mycad.ui.main_window import MainWindow
from mycad.ui.viewport import GLViewport, ProjectionMode, ViewOrientation


@pytest.mark.parametrize("modeling", [False, True])
@pytest.mark.parametrize("pan", [False, True])
def test_middle_drag_has_one_navigation_contract(qtbot: QtBot, modeling: bool, pan: bool) -> None:
    view = GLViewport(viewport_port=build_app(discoverers=[]).kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.set_modeling_context_active(modeling)
    before_center = QVector3D(view.opts["center"])
    before_rotation = view.viewMatrix().normalMatrix()
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
    after_rotation = view.viewMatrix().normalMatrix()
    if pan:
        assert QVector3D(view.opts["center"]) != before_center
        assert after_rotation == before_rotation
    else:
        assert QVector3D(view.opts["center"]) == before_center
        assert after_rotation != before_rotation
    assert commits == []


@pytest.mark.parametrize("modeling", [False, True])
@pytest.mark.parametrize(("orientation", "dy"), [("top", 30), ("bottom", -30)])
def test_middle_drag_crosses_both_camera_poles(
    qtbot: QtBot, modeling: bool, orientation: ViewOrientation, dy: int
) -> None:
    view = GLViewport(viewport_port=build_app(discoverers=[]).kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.set_orientation(orientation)
    view.set_modeling_context_active(modeling)
    before = view.camera_state()
    QTest.mousePress(view, Qt.MouseButton.MiddleButton, pos=QPoint(400, 300))
    view.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(400, 300 + dy),
            QPointF(400, 300 + dy),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.MiddleButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    QTest.mouseRelease(view, Qt.MouseButton.MiddleButton, pos=QPoint(400, 300 + dy))
    # Both outward drags move past the pole toward negative world X.
    assert view.viewMatrix().row(2).x() == pytest.approx(-0.5, abs=1e-6)
    assert view.camera_state() == before
    assert view.orientation() is None


def test_horizontal_orbit_can_tilt_world_z_and_complete_a_full_turn(qtbot: QtBot) -> None:
    view = GLViewport(viewport_port=build_app(discoverers=[]).kernel)
    qtbot.addWidget(view)
    view.set_orientation("isometric")
    before = view.viewMatrix()
    view.orbit(45, 0)
    assert abs(view.viewMatrix().row(0).z()) > 0.1
    for _ in range(7):
        view.orbit(45, 0)
    for row in range(3):
        assert view.viewMatrix().row(row).toTuple() == pytest.approx(
            before.row(row).toTuple(), abs=1e-5
        )


def test_free_camera_supports_world_size_point_rendering(qtbot: QtBot) -> None:
    view = GLViewport(viewport_port=build_app(discoverers=[]).kernel)
    qtbot.addWidget(view)
    view.orbit(40, 120)
    points = np.array([[0.0, 0.0, 0.0], [10.0, 20.0, 30.0]])
    # GLScatterPlotItem(pxMode=False) asks for pixel sizes as one array.
    sizes = view.pixelSize(points)
    expected = [view.pixelSize(QVector3D(*point)) for point in points]
    assert sizes == pytest.approx(expected)


@pytest.mark.parametrize("projection", ["orthographic", "perspective"])
def test_free_camera_keeps_rendering_picking_pan_and_saved_view_aligned(
    qtbot: QtBot, projection: ProjectionMode
) -> None:
    view = GLViewport(viewport_port=build_app(discoverers=[]).kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.set_projection_mode(projection)
    view.set_orientation("top")
    view.orbit(35, 130)
    view.orbit(-40, 15)
    view.setCameraPosition(distance=150, pos=QVector3D(8, -6, 2))
    matrix = view.viewMatrix()
    eye_in_view = matrix.map(view.cameraPosition())
    assert eye_in_view.toTuple() == pytest.approx((0, 0, 0), abs=1e-4)
    world = (15.0, 3.0, 5.0)
    clip = (view.projectionMatrix() * matrix).map(QVector3D(*world))
    screen = ((clip.x() + 1) * 400, (1 - clip.y()) * 300)
    assert view.project_world_point(world) == pytest.approx(screen, abs=1e-3)
    ray = view.camera_ray(*screen)
    assert ray is not None
    start, direction = ray
    distance = sum((world[i] - start[i]) * direction[i] for i in range(3))
    assert tuple(start[i] + distance * direction[i] for i in range(3)) == pytest.approx(
        world, abs=1e-3
    )
    saved = view.capture_view()
    view.set_orientation("front")
    view.restore_view(saved)
    for row in range(4):
        assert view.viewMatrix().row(row).toTuple() == pytest.approx(
            matrix.row(row).toTuple(), abs=1e-5
        )
    center_before = QVector3D(view.opts["center"])
    QTest.mousePress(
        view, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.ShiftModifier, QPoint(400, 300)
    )
    view.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(430, 320),
            QPointF(430, 320),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.MiddleButton,
            Qt.KeyboardModifier.ShiftModifier,
        )
    )
    QTest.mouseRelease(
        view, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.ShiftModifier, QPoint(430, 320)
    )
    # Panning stays in the tilted screen plane, not the world XY plane.
    delta = matrix.mapVector(view.opts["center"] - center_before)
    assert delta.z() == pytest.approx(0, abs=1e-5)
    assert delta.x() < 0 < delta.y()


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
