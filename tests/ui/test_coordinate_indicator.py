# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Coordinate orientation remains legible independently of camera scale."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D
from pytestqt.qtbot import QtBot

from mycad.app import build_app
from mycad.ui.theme import ThemeName
from mycad.ui.viewport import GLViewport, ProjectionMode, ViewOrientation, camera_basis


@pytest.mark.parametrize(
    "orientation", ["front", "back", "left", "right", "top", "bottom", "isometric"]
)
def test_coordinate_indicator_tracks_camera_without_scaling(
    qtbot: QtBot, orientation: ViewOrientation
) -> None:
    view = GLViewport(viewport_port=build_app(discoverers=[]).kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.set_orientation(orientation)
    indicator = view.coordinate_indicator
    assert indicator.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert indicator.axis_labels == ("X", "Y", "Z")
    before = indicator.axis_vectors()
    assert len(before) == 3
    for vector in before:
        assert sum(v * v for v in vector) == pytest.approx(1)
    # The arrow directions agree with the actual view transformation.
    for vector, world in zip(
        before, (QVector3D(1, 0, 0), QVector3D(0, 1, 0), QVector3D(0, 0, 1)), strict=True
    ):
        transformed = view.viewMatrix().mapVector(world)
        assert vector == pytest.approx((transformed.x(), -transformed.y(), transformed.z()))
    view.setCameraPosition(distance=10000, pos=QVector3D(100, 200, 300))
    for actual, expected in zip(indicator.axis_vectors(), before, strict=True):
        assert actual == pytest.approx(expected)
    view.set_coordinate_axes_visible(True)
    assert indicator.origin_visible
    view.set_coordinate_axes_visible(False)
    assert not indicator.origin_visible
    assert not indicator.isHidden()
    view.orbit(17, 13)
    assert indicator.axis_vectors() != before


@pytest.mark.parametrize(
    ("orientation", "axis", "toward"),
    [("top", 2, True), ("bottom", 2, False), ("right", 0, True), ("front", 1, False)],
)
def test_end_on_axis_retains_dot_or_cross_direction(
    qtbot: QtBot, orientation: ViewOrientation, axis: int, toward: bool
) -> None:
    view = GLViewport(viewport_port=build_app(discoverers=[]).kernel)
    qtbot.addWidget(view)
    view.set_orientation(orientation)
    x, y, z = view.coordinate_indicator.axis_vectors()[axis]
    assert abs(x) + abs(y) < 1e-5
    assert (z > 0) is toward


@pytest.mark.parametrize(
    "orientation", ["front", "back", "left", "right", "top", "bottom", "isometric"]
)
@pytest.mark.parametrize("projection", ["orthographic", "perspective"])
def test_model_projection_and_picking_match_rendered_camera(
    qtbot: QtBot, orientation: ViewOrientation, projection: ProjectionMode
) -> None:
    view = GLViewport(viewport_port=build_app(discoverers=[]).kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.set_orientation(orientation)
    view.set_projection_mode(projection)
    view.setCameraPosition(distance=150, pos=QVector3D(8, -6, 2))
    for world in ((15.0, 3.0, 5.0), (-4.0, -12.0, 10.0)):
        projected = view.project_world_point(world)
        assert projected is not None
        clip = (view.projectionMatrix() * view.viewMatrix()).map(QVector3D(*world))
        expected = ((clip.x() + 1) * 400, (1 - clip.y()) * 300)
        assert projected == pytest.approx(expected, abs=1e-3)
        ray = view.camera_ray(*expected)
        assert ray is not None
        start, direction = ray
        delta = tuple(world[i] - start[i] for i in range(3))
        distance = sum(delta[i] * direction[i] for i in range(3))
        assert tuple(start[i] + distance * direction[i] for i in range(3)) == pytest.approx(
            world, abs=1e-3
        )


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_indicator_paints_three_readable_axis_colors(qtbot: QtBot, theme: ThemeName) -> None:
    view = GLViewport(viewport_port=build_app(discoverers=[]).kernel)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.set_orientation("isometric")
    view.set_theme(theme)
    indicator = view.coordinate_indicator
    indicator.sync_scene()
    image = indicator.grab().toImage()
    counts = [0, 0, 0]
    for y in range(image.height() - 120, image.height() - 10):
        for x in range(10, 150):
            color = image.pixelColor(x, y)
            channels = (color.red(), color.green(), color.blue())
            for i in range(3):
                if channels[i] > max(channels[(i + 1) % 3], channels[(i + 2) % 3]) + 30:
                    counts[i] += 1
    assert all(count > 30 for count in counts), counts


@pytest.mark.parametrize("elevation", [89.9, 90.1, -89.9, -90.1])
def test_camera_basis_has_no_pole_discontinuity(qtbot: QtBot, elevation: float) -> None:
    view = GLViewport(viewport_port=build_app(discoverers=[]).kernel)
    qtbot.addWidget(view)
    view.setCameraPosition(elevation=elevation, azimuth=37)
    _, right, up, _ = camera_basis(elevation, 37)
    matrix = view.viewMatrix()
    assert right == pytest.approx(
        (matrix.row(0).x(), matrix.row(0).y(), matrix.row(0).z()), abs=1e-6
    )
    assert up == pytest.approx((matrix.row(1).x(), matrix.row(1).y(), matrix.row(1).z()), abs=1e-6)
