# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""End-to-end checks for nonmodal modeling command interaction."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QLabel,
    QPushButton,
    QSpinBox,
)
from pytestqt.qtbot import QtBot

from mycad import app as mycad_app
from mycad.app import AppServices, build_app
from mycad.core.sketch import CircleEntity, LineEntity, RectangleEntity, Sketch, WorkPlaneFrame
from mycad.ui.main_window import MainWindow
from mycad.ui.right_panel import HistoryEditDialog
from mycad.ui.viewport import ViewOrientation
from mycad.ui.workplane_position import WorkplanePositionDialog


def _body_centers(services: AppServices) -> tuple[tuple[float, float, float], ...]:
    centers: list[tuple[float, float, float]] = []
    for identity in services.kernel.body_ids:
        selector = services.kernel.interactive_body_selector(identity)
        center: object = selector["center_mm"]
        assert isinstance(center, (tuple, list))
        coordinates = cast("Sequence[object]", center)
        assert len(coordinates) == 3
        x, y, z = coordinates
        assert all(
            not isinstance(value, bool) and isinstance(value, int | float) for value in coordinates
        )
        centers.append(
            (
                float(cast("int | float", x)),
                float(cast("int | float", y)),
                float(cast("int | float", z)),
            )
        )
    return tuple(sorted(centers))


@pytest.mark.parametrize(
    "command_id",
    [
        "feature.box",
        "feature.cylinder",
        "feature.extrude",
        "feature.revolve",
        "feature.hole",
        "feature.hole_pattern",
        "modify.boolean_cut",
        "modify.boolean_intersect",
        "modify.boolean_bodies",
        "modify.body_transform",
        "modify.body_pattern",
        "modify.chamfer",
    ],
)
def test_each_builtin_modeling_command_starts_in_the_shared_bar(
    qtbot: QtBot,
    command_id: str,
) -> None:
    services: AppServices = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(mycad_app.new_document(services))
    window.show()
    assert window.command_palette is not None

    window.command_palette.command_activated.emit(command_id)

    bar = window.modeling_command_bar
    assert bar is not None
    assert bar.isVisible()
    assert bar.command_id == command_id
    assert window.plan_cards is not None
    assert not window.findChildren(QDialog)


@pytest.mark.parametrize("command_id", ["feature.box", "feature.cylinder"])
def test_box_uses_external_bar_auto_previews_and_commits_explicitly(
    qtbot: QtBot, command_id: str
) -> None:
    services: AppServices = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()

    assert window.command_palette is not None
    window.command_palette.command_activated.emit(command_id)
    qtbot.wait(50)

    bar = window.modeling_command_bar
    viewport = window.viewport
    assert bar is not None and viewport is not None
    assert bar.isVisible()
    assert bar.mapToGlobal(QPoint(0, bar.height())).y() <= viewport.mapToGlobal(QPoint()).y()
    assert window.plan_cards is not None
    assert not window.findChildren(QDialog)

    viewport.workplane_point_picked.emit((0.0, 0.0, 0.0), QPoint())
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert commit is not None
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    assert loaded.document.commands == ()

    commit.click()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 1 and not unit.is_busy, timeout=30000)
    assert "已完成建模操作" in window.status_command.text()
    assert len(loaded.document.commands) == 1
    assert loaded.document.commands[0].id == command_id
    assert services.kernel.body_ids
    loaded.bus.undo()
    assert not loaded.document.commands
    assert not services.kernel.body_ids
    loaded.bus.redo()
    assert len(loaded.document.commands) == 1
    assert services.kernel.body_ids


def test_boolean_intersect_previews_then_commits_explicitly(qtbot: QtBot) -> None:
    services: AppServices = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute(
        "feature.box",
        {"size_x": 20.0, "size_y": 20.0, "size_z": 10.0},
        "test",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("modify.boolean_intersect")

    bar = window.modeling_command_bar
    viewport = window.viewport
    assert bar is not None and viewport is not None
    viewport.workplane_point_picked.emit((5.0, 0.0, 0.0), QPoint())
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert commit is not None
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    assert len(loaded.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(4000.0, abs=1e-6)

    commit.click()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)
    assert loaded.document.commands[-1].id == "modify.boolean_intersect"
    assert services.kernel.mass_properties().volume == pytest.approx(1000.0, abs=1e-6)


@pytest.mark.parametrize("keep_tool", [False, True])
def test_selected_body_boolean_picks_target_then_tool_and_commits_latest_preview(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    keep_tool: bool,
    tmp_path: Path,
) -> None:
    services: AppServices = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute(
        "feature.box",
        {
            "size_x": 10.0,
            "size_y": 10.0,
            "size_z": 10.0,
            "center": [0.0, 0.0, 0.0],
            "mode": "new",
        },
        "test",
    )
    first_body = services.kernel.interactive_body_selector(services.kernel.body_ids[0])
    loaded.bus.execute(
        "modify.body_transform",
        {
            "body": first_body,
            "transform": {"operation": "copy", "translation_mm": [5.0, 0.0, 0.0]},
        },
        "test",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    viewport = window.viewport
    assert viewport is not None and window.command_palette is not None
    viewport.resize(800, 600)
    viewport.set_orientation("top")
    viewport.fit_view()
    window.command_palette.command_activated.emit("modify.boolean_bodies")

    bar = window.modeling_command_bar
    assert bar is not None
    operation = bar.findChild(QComboBox, "bodyOperation")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert operation is not None and commit is not None
    operation.setCurrentIndex(operation.findData("difference"))
    target = viewport.project_world_point((-2.5, 0.0, 0.0))
    tool = viewport.project_world_point((7.5, 0.0, 0.0))
    assert target is not None and tool is not None
    assert viewport.pick_at(*target)
    assert not commit.isEnabled()
    assert viewport.pick_at(*tool, toggle=True)
    selection = viewport.selection()
    assert selection is not None
    assert len(selection.body_ids) == 2
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    keep = bar.findChild(QComboBox, "keepTool")
    roles = bar.findChild(QLabel, "modelingSelectionStatus")
    assert keep is not None and roles is not None
    assert "目标：实体 1" in roles.text() and "刀具：实体 2" in roles.text()
    assert "消耗" in roles.text()
    if keep_tool:
        keep.setCurrentIndex(keep.findData("true"))
        qtbot.waitUntil(commit.isEnabled, timeout=30000)
        assert "保留" in roles.text()
    assert f"当前模型共 {2 if keep_tool else 1} 个实体" in window.status_command.text()

    assert len(loaded.document.commands) == 2
    assert services.kernel.mass_properties().volume == pytest.approx(2000.0, abs=1e-6)
    unit = window.execution_unit
    assert unit is not None
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 3 and not unit.is_busy, timeout=30000)

    assert loaded.document.commands[-1].id == "modify.boolean_bodies"
    assert loaded.document.commands[-1].params["operation"] == "difference"
    assert services.kernel.mass_properties().volume == pytest.approx(
        1500.0 if keep_tool else 500.0, abs=1e-6
    )
    assert services.kernel.mass_properties().solid_count == (2 if keep_tool else 1)
    assert "目标：实体 1" in window.status_command.text()
    assert "刀具：实体 2" in window.status_command.text()
    assert ("保留" if keep_tool else "消耗") in window.status_command.text()
    expected_volume = 1500.0 if keep_tool else 500.0
    if keep_tool:
        qtbot.waitUntil(lambda: viewport.visible_body_ids() == services.kernel.body_ids)
        retained = next(
            identity
            for identity in services.kernel.body_ids
            if services.kernel.interactive_body_selector(identity)["volume_mm3"]
            == pytest.approx(1000.0)
        )
        assert viewport.set_body_visible(retained, False)
        assert len(viewport.visible_body_ids()) == 1
        assert services.kernel.mass_properties().volume == pytest.approx(expected_volume)
    window.act_undo.trigger()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=10000)
    assert services.kernel.mass_properties().volume == pytest.approx(2000.0)
    window.act_redo.trigger()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 3 and not unit.is_busy, timeout=10000)
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume)
    archive = tmp_path / "selected-body-boolean.mc.json"

    def save_path(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(archive), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_path)
    window.act_save_as.trigger()
    assert archive.exists()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", save_path)
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.loaded_document() is not loaded and not unit.is_busy, timeout=10000
    )
    assert services.kernel.geometry_check().is_valid
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume)
    assert services.kernel.mass_properties().solid_count == (2 if keep_tool else 1)
    monkeypatch.setattr(window, "_ask_save_dialog", lambda: "discard")


@pytest.mark.parametrize(
    ("command_id", "expected_centers"),
    (
        ("modify.body_transform", ((10.0, 0.0, 0.0),)),
        ("modify.body_pattern", ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))),
    ),
)
def test_selected_body_transform_and_pattern_preview_before_commit(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    command_id: str,
    expected_centers: tuple[tuple[float, float, float], ...],
) -> None:
    services: AppServices = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute(
        "feature.box",
        {
            "size_x": 10.0,
            "size_y": 10.0,
            "size_z": 10.0,
            "center": [0.0, 0.0, 0.0],
            "mode": "new",
        },
        "test",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    viewport = window.viewport
    assert viewport is not None and window.command_palette is not None
    viewport.resize(800, 600)
    viewport.set_orientation("top")
    viewport.fit_view()
    window.command_palette.command_activated.emit(command_id)

    bar = window.modeling_command_bar
    assert bar is not None
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert commit is not None
    point = viewport.project_world_point((0.0, 0.0, 0.0))
    assert point is not None and viewport.pick_at(*point)
    qtbot.waitUntil(commit.isEnabled, timeout=30000)

    assert len(loaded.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(1000.0, abs=1e-6)
    unit = window.execution_unit
    assert unit is not None
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)

    centers = _body_centers(services)
    assert len(centers) == len(expected_centers)
    for actual, expected in zip(centers, expected_centers, strict=True):
        assert actual == pytest.approx(expected, abs=1e-6)
    assert services.kernel.mass_properties().volume == pytest.approx(
        1000.0 * len(expected_centers), abs=1e-6
    )
    monkeypatch.setattr(window, "_ask_save_dialog", lambda: "discard")


@pytest.mark.parametrize(
    ("operation", "seed_center", "expected_centers"),
    (
        ("rotate", (10.0, 0.0, 0.0), ((0.0, 10.0, 0.0),)),
        ("mirror", (10.0, 0.0, 0.0), ((-10.0, 0.0, 0.0),)),
        ("copy", (0.0, 0.0, 0.0), ((0.0, 0.0, 0.0), (15.0, 0.0, 0.0))),
    ),
)
def test_selected_body_transform_modes_preview_and_commit(
    qtbot: QtBot,
    operation: str,
    seed_center: tuple[float, float, float],
    expected_centers: tuple[tuple[float, float, float], ...],
) -> None:
    services: AppServices = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute(
        "feature.box",
        {
            "size_x": 10.0,
            "size_y": 10.0,
            "size_z": 10.0,
            "center": list(seed_center),
            "mode": "new",
        },
        "test",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    viewport = window.viewport
    assert viewport is not None and window.command_palette is not None
    viewport.resize(800, 600)
    viewport.set_orientation("top")
    viewport.fit_view()
    window.command_palette.command_activated.emit("modify.body_transform")

    bar = window.modeling_command_bar
    assert bar is not None
    transform = bar.findChild(QComboBox, "transformOperation")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert transform is not None and commit is not None
    transform.setCurrentIndex(transform.findData(operation))
    if operation == "rotate":
        angle = bar.findChild(QDoubleSpinBox, "rotate_angle")
        assert angle is not None
        angle.setValue(90.0)
    elif operation == "copy":
        translation = bar.findChild(QDoubleSpinBox, "move_x")
        assert translation is not None
        translation.setValue(15.0)
    point = viewport.project_world_point((seed_center[0], seed_center[1], seed_center[2] + 5.0))
    assert point is not None and viewport.pick_at(*point)
    qtbot.waitUntil(commit.isEnabled, timeout=30000)

    assert len(loaded.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(1000.0)
    unit = window.execution_unit
    assert unit is not None
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)

    transform = loaded.document.commands[-1].params["transform"]
    assert isinstance(transform, dict)
    assert transform["operation"] == operation
    centers = _body_centers(services)
    assert len(centers) == len(expected_centers)
    for actual, expected in zip(centers, expected_centers, strict=True):
        assert actual == pytest.approx(expected, abs=1e-6)
    assert services.kernel.mass_properties().volume == pytest.approx(
        1000.0 * len(expected_centers), abs=1e-6
    )


def test_selected_body_circular_pattern_previews_and_commits_full_set(qtbot: QtBot) -> None:
    services: AppServices = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute(
        "feature.box",
        {
            "size_x": 10.0,
            "size_y": 10.0,
            "size_z": 10.0,
            "center": [10.0, 0.0, 0.0],
            "mode": "new",
        },
        "test",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    viewport = window.viewport
    assert viewport is not None and window.command_palette is not None
    viewport.resize(800, 600)
    viewport.set_orientation("top")
    viewport.fit_view()
    window.command_palette.command_activated.emit("modify.body_pattern")

    bar = window.modeling_command_bar
    assert bar is not None
    kind = bar.findChild(QComboBox, "patternKind")
    count = bar.findChild(QSpinBox, "body_pattern_count")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert kind is not None and count is not None and commit is not None
    kind.setCurrentIndex(kind.findData("circular"))
    count.setValue(4)
    point = viewport.project_world_point((10.0, 0.0, 5.0))
    assert point is not None and viewport.pick_at(*point)
    qtbot.waitUntil(commit.isEnabled, timeout=30000)

    assert len(loaded.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(1000.0)
    unit = window.execution_unit
    assert unit is not None
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)

    pattern = loaded.document.commands[-1].params["pattern"]
    assert isinstance(pattern, dict)
    assert pattern["kind"] == "circular"
    assert pattern["count"] == 4
    centers = _body_centers(services)
    assert len(centers) == 4
    expected_centers = tuple(
        sorted(
            (
                (10.0, 0.0, 0.0),
                (0.0, 10.0, 0.0),
                (-10.0, 0.0, 0.0),
                (0.0, -10.0, 0.0),
            )
        )
    )
    for actual, expected in zip(centers, expected_centers, strict=True):
        assert actual == pytest.approx(expected, abs=1e-6)
    assert services.kernel.mass_properties().volume == pytest.approx(4000.0, abs=1e-6)


def test_face_selection_returns_to_source_before_picking(
    qtbot: QtBot,
) -> None:
    services: AppServices = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute(
        "feature.box",
        {
            "size_x": 20.0,
            "size_y": 20.0,
            "size_z": 10.0,
            "center": [0.0, 0.0, 0.0],
            "mode": "new",
        },
        "test",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    viewport = window.viewport
    assert viewport is not None and window.command_palette is not None
    viewport.resize(800, 600)
    viewport.set_orientation("top")
    viewport.fit_view()
    window.command_palette.command_activated.emit("feature.hole")

    snapshot = viewport.snapshots()[-1]
    viewport.show_candidate_preview(snapshot, preserve_view=True)
    target = viewport.selection_target_at(viewport.width() / 2.0, viewport.height() / 2.0, "face")

    assert target is None
    bar = window.modeling_command_bar
    assert bar is not None
    source_button = bar.findChild(QPushButton, "modelingSelectSource")
    assert source_button is not None
    source_button.click()
    target = viewport.selection_target_at(viewport.width() / 2.0, viewport.height() / 2.0, "face")
    assert target is not None and target.kind == "face"
    assert viewport.pick_at(viewport.width() / 2.0, viewport.height() / 2.0)
    assert viewport.selection() is not None
    assert window.plan_draft is not None
    assert "target_face" in window.plan_draft.plan().steps[0].params


@pytest.mark.parametrize("bypass", [False, True])
@pytest.mark.parametrize(("orientation", "expected"), [("top", (0, 0, 5)), ("right", (10, 0, 0))])
def test_hole_click_near_world_origin_snaps_axis_through_origin(
    qtbot: QtBot, bypass: bool, orientation: ViewOrientation, expected: tuple[int, int, int]
) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 10})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    viewport = window.viewport
    assert viewport is not None and window.command_palette is not None
    viewport.set_orientation(orientation)
    viewport.fit_view()
    window.command_palette.command_activated.emit("feature.hole")
    origin = viewport.project_world_point((0, 0, 0))
    assert origin is not None
    QTest.mouseClick(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier if bypass else Qt.KeyboardModifier.NoModifier,
        QPoint(round(origin[0] + 5), round(origin[1])),
    )
    assert window.plan_draft is not None
    position = window.plan_draft.plan().steps[0].params["position"]
    assert isinstance(position, dict)
    position = cast("dict[str, object]", position)
    assert position["kind"] == "point"
    point = position["point"]
    assert isinstance(point, list)
    if bypass:
        assert point != pytest.approx(expected)
    else:
        assert point == pytest.approx(expected)
        bar = window.modeling_command_bar
        assert bar is not None
        status = bar.findChild(QLabel, "modelingSelectionStatus")
        assert status is not None and "世界原点" in status.text()
    assert len(loaded.document.commands) == 1
    if not bypass:
        bar = window.modeling_command_bar
        unit = window.execution_unit
        assert bar is not None and unit is not None
        commit = bar.findChild(QPushButton, "modelingCommitButton")
        assert commit is not None
        qtbot.waitUntil(commit.isEnabled, timeout=30000)
        commit.click()
        qtbot.waitUntil(
            lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000
        )
        assert loaded.document.commands[-1].params["position"] == position


def test_cancel_discards_placed_preview_without_writing_history(qtbot: QtBot) -> None:
    services: AppServices = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.cylinder")

    bar = window.modeling_command_bar
    viewport = window.viewport
    assert bar is not None and viewport is not None
    viewport.workplane_point_picked.emit((10.0, 12.0, 0.0), QPoint())
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    cancel = bar.findChild(QPushButton, "modelingCancelButton")
    assert commit is not None and cancel is not None
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    cancel.click()

    assert loaded.document.commands == ()
    assert bar.isHidden()
    assert viewport.displayed_snapshot_id() is None


def test_cancel_restores_filter_and_preserves_view(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 10})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.viewport is not None and window.command_palette is not None
    viewport = window.viewport
    viewport.set_selection_filter("body")
    viewport.set_orientation("top")
    before = viewport.capture_view()
    window.command_palette.command_activated.emit("feature.extrude")
    assert viewport.selection_filter() == "face"
    assert window.modeling_command_bar is not None
    cancel = window.modeling_command_bar.findChild(QPushButton, "modelingCancelButton")
    assert cancel is not None
    cancel.click()
    assert viewport.selection_filter() == "body"
    assert viewport.capture_view() == before
    assert len(loaded.document.commands) == 1


def test_extrude_requires_face_and_previews_the_whole_face(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 10}, "test")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    viewport = window.viewport
    bar = window.modeling_command_bar
    assert viewport is not None and bar is not None
    assert window.command_palette is not None
    viewport.resize(800, 600)
    viewport.set_orientation("top")
    viewport.fit_view()
    window.command_palette.command_activated.emit("feature.extrude")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    distance = bar.findChild(QDoubleSpinBox, "distance")
    assert commit is not None and distance is not None
    assert viewport.selection_filter() == "face"
    assert not commit.isEnabled()
    # A workplane placement event must never substitute a circle for a selected face.
    viewport.workplane_point_picked.emit((5.0, 6.0, 0.0), QPoint())
    assert not commit.isEnabled()
    assert viewport.pick_at(400, 300)
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    assert len(loaded.document.commands) == 1
    # Re-picking the source face while the preview is displayed remains possible.
    assert viewport.pick_at(400, 300)
    distance.setValue(-2.0)
    assert not commit.isEnabled()
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    unit = window.execution_unit
    assert unit is not None
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)
    assert loaded.document.commands[-1].params["mode"] == "cut"
    props = services.kernel.mass_properties()
    assert props.volume == pytest.approx(20 * 20 * 8)
    assert props.solid_count == 1


def test_extrude_xy_creation_requires_explicit_source_switch(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.extrude")
    bar = window.modeling_command_bar
    viewport = window.viewport
    assert bar is not None and viewport is not None
    source = bar.findChild(QComboBox, "extrudeSource")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert source is not None and commit is not None
    source.setCurrentIndex(source.findData("profile"))
    viewport.workplane_point_picked.emit((0.0, 0.0, 0.0), QPoint())
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    source.setCurrentIndex(source.findData("face"))
    assert not commit.isEnabled()
    assert viewport.selection_filter() == "face"
    assert loaded.document.commands == ()


def test_sketch_extrude_previews_then_commits_current_version(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    sketch_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    loaded.bus.execute(
        "sketch.create",
        Sketch(
            sketch_id,
            WorkPlaneFrame.xy(),
            (CircleEntity("1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b", (0.0, 0.0), 5.0),),
        ).to_mapping(),
        confirmed_by="local",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.extrude")
    bar, viewport = window.modeling_command_bar, window.viewport
    assert bar is not None and viewport is not None
    source = bar.findChild(QComboBox, "extrudeSource")
    sketch_picker = bar.findChild(QComboBox, "sketchProfile")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert source is not None and sketch_picker is not None and commit is not None
    source.setCurrentIndex(source.findData("sketch"))
    sketch_picker.setCurrentIndex(sketch_picker.findData(sketch_id))
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    assert len(loaded.document.commands) == 1
    unit = window.execution_unit
    assert unit is not None
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)

    assert loaded.document.commands[-1].version == 5
    assert loaded.document.commands[-1].params["profile"] == {
        "type": "sketch",
        "sketch_id": sketch_id,
    }
    assert loaded.document.commands[-1].params["extent_mode"] == "one_sided"
    assert services.kernel.mass_properties().volume == pytest.approx(math.pi * 5.0**2 * 10.0)


def test_symmetric_sketch_extrude_previews_without_writing_then_commits_centered_body(
    qtbot: QtBot,
) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    sketch_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    loaded.bus.execute(
        "sketch.create",
        Sketch(
            sketch_id,
            WorkPlaneFrame.xy(),
            (CircleEntity("1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b", (0.0, 0.0), 5.0),),
        ).to_mapping(),
        confirmed_by="local",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.extrude")
    bar, viewport = window.modeling_command_bar, window.viewport
    assert bar is not None and viewport is not None
    source = bar.findChild(QComboBox, "extrudeSource")
    sketch_picker = bar.findChild(QComboBox, "sketchProfile")
    extent = bar.findChild(QComboBox, "extentMode")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert (
        source is not None
        and sketch_picker is not None
        and extent is not None
        and commit is not None
    )
    source.setCurrentIndex(source.findData("sketch"))
    sketch_picker.setCurrentIndex(sketch_picker.findData(sketch_id))
    extent.setCurrentIndex(extent.findData("symmetric"))
    qtbot.waitUntil(commit.isEnabled, timeout=30000)

    assert len(loaded.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(0.0)
    assert viewport.displayed_snapshot_id() is not None

    unit = window.execution_unit
    assert unit is not None
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)

    props = services.kernel.mass_properties()
    assert loaded.document.commands[-1].version == 5
    assert loaded.document.commands[-1].params["extent_mode"] == "symmetric"
    assert props.volume == pytest.approx(math.pi * 5.0**2 * 10.0)
    assert props.center_of_mass[2] == pytest.approx(0.0, abs=1e-6)


def test_sketch_revolve_previews_then_commits_about_a_construction_axis(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    sketch_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    loaded.bus.execute(
        "sketch.create",
        Sketch(
            sketch_id,
            WorkPlaneFrame.xz(),
            (
                RectangleEntity("7b7b7b7b-7b7b-4b7b-8b7b-7b7b7b7b7b7b", (4.0, -10.0), (6.0, 0.0)),
                LineEntity(
                    "9c9c9c9c-9c9c-4c9c-8c9c-9c9c9c9c9c9c",
                    (2.0, -10.0),
                    (2.0, 0.0),
                    construction=True,
                ),
            ),
        ).to_mapping(),
        confirmed_by="local",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.revolve")
    bar = window.modeling_command_bar
    assert bar is not None
    source = bar.findChild(QComboBox, "revolveSource")
    sketch_picker = bar.findChild(QComboBox, "sketchProfile")
    axis_source = bar.findChild(QComboBox, "axisSource")
    axis_line = bar.findChild(QComboBox, "axisLine")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert (
        source is not None
        and sketch_picker is not None
        and axis_source is not None
        and axis_line is not None
        and commit is not None
    )
    source.setCurrentIndex(source.findData("sketch"))
    sketch_picker.setCurrentIndex(sketch_picker.findData(sketch_id))
    axis_source.setCurrentIndex(axis_source.findData("sketch_line"))
    axis_line.setCurrentIndex(axis_line.findData("9c9c9c9c-9c9c-4c9c-8c9c-9c9c9c9c9c9c"))
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    unit = window.execution_unit
    assert unit is not None
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)

    assert loaded.document.commands[-1].version == 4
    assert loaded.document.commands[-1].params["profile"] == {
        "type": "sketch",
        "sketch_id": sketch_id,
    }
    axis_reference = loaded.document.commands[-1].params["axis_reference"]
    assert isinstance(axis_reference, dict)
    assert axis_reference["entity_id"] == "9c9c9c9c-9c9c-4c9c-8c9c-9c9c9c9c9c9c"
    assert services.kernel.mass_properties().volume == pytest.approx(120.0 * math.pi, rel=2e-5)
    assert services.kernel.mass_properties().center_of_mass == pytest.approx(
        (2.0, 0.0, 5.0), abs=1e-6
    )


def test_sketch_hole_previews_and_commits_against_selected_planar_face(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute(
        "feature.box",
        {"size_x": 20.0, "size_y": 20.0, "size_z": 10.0},
        "local",
    )
    sketch_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    loaded.bus.execute(
        "sketch.create",
        Sketch(
            sketch_id,
            WorkPlaneFrame(
                origin_mm=(0.0, 0.0, 5.0),
                u_axis=(1.0, 0.0, 0.0),
                v_axis=(0.0, 1.0, 0.0),
                normal=(0.0, 0.0, 1.0),
            ),
            (CircleEntity("1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b", (0.0, 0.0), 2.0),),
        ).to_mapping(),
        confirmed_by="local",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.hole")
    bar, viewport = window.modeling_command_bar, window.viewport
    assert bar is not None and viewport is not None
    source = bar.findChild(QComboBox, "holeSource")
    sketch_picker = bar.findChild(QComboBox, "sketchProfile")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert source is not None and sketch_picker is not None and commit is not None
    source.setCurrentIndex(source.findData("sketch"))
    sketch_picker.setCurrentIndex(sketch_picker.findData(sketch_id))
    viewport.set_orientation("top")
    viewport.fit_view()
    assert viewport.pick_at(400, 300)
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    assert len(loaded.document.commands) == 2
    assert services.kernel.mass_properties().volume == pytest.approx(4000.0)
    unit = window.execution_unit
    assert unit is not None
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 3 and not unit.is_busy, timeout=30000)

    assert loaded.document.commands[-1].version == 3
    assert loaded.document.commands[-1].params["profile"] == {
        "type": "sketch",
        "sketch_id": sketch_id,
    }
    assert services.kernel.mass_properties().volume == pytest.approx(
        4000.0 - math.pi * 4.0 * 10.0, rel=2e-5
    )


def test_hole_pattern_previews_selected_face_and_commits_all_instances(qtbot: QtBot) -> None:
    services: AppServices = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute(
        "feature.box",
        {"size_x": 20.0, "size_y": 20.0, "size_z": 10.0},
        "test",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    viewport = window.viewport
    assert viewport is not None and window.command_palette is not None
    viewport.resize(800, 600)
    viewport.set_orientation("top")
    viewport.fit_view()
    window.command_palette.command_activated.emit("feature.hole_pattern")

    bar = window.modeling_command_bar
    assert bar is not None
    diameter = bar.findChild(QDoubleSpinBox, "diameter")
    depth_kind = bar.findChild(QComboBox, "depthKind")
    pattern_radius = bar.findChild(QDoubleSpinBox, "pattern_radius")
    pattern_count = bar.findChild(QSpinBox, "pattern_count")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert (
        diameter is not None
        and depth_kind is not None
        and pattern_radius is not None
        and pattern_count is not None
        and commit is not None
    )
    diameter.setValue(2.0)
    depth_kind.setCurrentIndex(depth_kind.findData("through_all"))
    pattern_radius.setValue(5.0)
    pattern_count.setValue(4)
    point = viewport.project_world_point((0.0, 0.0, 5.0))
    assert point is not None and viewport.pick_at(*point)
    qtbot.waitUntil(commit.isEnabled, timeout=30000)

    assert len(loaded.document.commands) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(4000.0)
    unit = window.execution_unit
    assert unit is not None
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)

    command = loaded.document.commands[-1]
    assert command.id == "feature.hole_pattern"
    assert command.params["pattern"] == {
        "kind": "polar",
        "radius": 5.0,
        "count": 4,
        "start_angle_deg": 0.0,
    }
    assert services.kernel.mass_properties().solid_count == 1
    assert services.kernel.mass_properties().volume == pytest.approx(
        4000.0 - 4.0 * math.pi * 10.0, rel=2e-5
    )


def test_extrude_zero_input_cannot_confirm_old_preview_and_escape_restores(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 10}, "test")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    view, bar = window.viewport, window.modeling_command_bar
    assert view is not None and bar is not None and window.command_palette is not None
    window.command_palette.command_activated.emit("feature.extrude")
    view.set_orientation("top")
    view.fit_view()
    assert view.pick_at(view.width() / 2, view.height() / 2)
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    field = bar.findChild(QDoubleSpinBox, "distance")
    assert commit is not None and field is not None
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    before = loaded.document.commands
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow, timeout=5000)
    field.setFocus()
    qtbot.waitUntil(field.hasFocus, timeout=5000)
    field.selectAll()
    QTest.keyClicks(field, "0")
    assert not commit.isEnabled()
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert not commit.isEnabled()
    assert loaded.document.commands == before
    QTest.keyClick(field, Qt.Key.Key_Escape)
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    assert field.value() == 10
    assert loaded.document.commands == before
    cancel = bar.findChild(QPushButton, "modelingCancelButton")
    assert cancel is not None
    cancel.click()
    assert not view.extrude_manipulator.active
    assert loaded.document.commands == before


def test_first_right_click_accepts_handle_second_commits_once(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 10}, "test")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    view, bar = window.viewport, window.modeling_command_bar
    assert view is not None and bar is not None and window.command_palette is not None
    window.command_palette.command_activated.emit("feature.extrude")
    view.set_orientation("isometric")
    view.fit_view()
    point = view.project_world_point((0, 0, 5))
    assert point is not None and view.pick_at(*point)
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert commit is not None
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    view.extrude_manipulator.refresh()
    dimension = view.extrude_manipulator.dimension
    distance = bar.findChild(QDoubleSpinBox, "distance")
    assert dimension is not None and distance is not None
    assert not distance.isHidden()
    frame = dimension.frame
    world_anchor = (
        frame.origin[0] + frame.normal[0] * distance.value() * dimension.scale,
        frame.origin[1] + frame.normal[1] * distance.value() * dimension.scale,
        frame.origin[2] + frame.normal[2] * distance.value() * dimension.scale,
    )
    anchor = view.project_world_point(world_anchor)
    assert anchor is not None
    assert view.extrude_manipulator.hit(anchor)
    position = QPoint(round(anchor[0]), round(anchor[1]))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=position)
    assert view.extrude_manipulator.adjusting
    QTest.mouseClick(view, Qt.MouseButton.RightButton, pos=position)
    assert not view.extrude_manipulator.adjusting
    assert len(loaded.document.commands) == 1
    QTest.mouseClick(view, Qt.MouseButton.RightButton, pos=position)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)
    assert loaded.document.commands[-1].id == "feature.extrude"


def test_annular_face_hole_pattern_can_use_face_centroid(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute("feature.cylinder", {"radius": 40.0, "height": 8.0}, "test")
    loaded.bus.execute(
        "feature.hole",
        {
            "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
            "position": {"kind": "center"},
            "diameter": 20.0,
            "depth": {"kind": "through_all"},
        },
        "test",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    view = window.viewport
    assert view is not None and window.command_palette is not None
    view.set_orientation("top")
    view.fit_view()
    window.command_palette.command_activated.emit("feature.hole_pattern")
    bar = window.modeling_command_bar
    assert bar is not None
    center = bar.findChild(QComboBox, "patternCenter")
    diameter = bar.findChild(QDoubleSpinBox, "diameter")
    radius = bar.findChild(QDoubleSpinBox, "pattern_radius")
    depth = bar.findChild(QComboBox, "depthKind")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert center is not None and diameter is not None and radius is not None
    assert depth is not None and commit is not None
    assert center.currentData() == "picked"
    center.setCurrentIndex(center.findData("face_center"))
    diameter.setValue(6.0)
    radius.setValue(25.0)
    depth.setCurrentIndex(depth.findData("through_all"))
    point = view.project_world_point((20.0, 10.0, 8.0))
    assert point is not None and view.pick_at(*point)
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    assert len(loaded.document.commands) == 2
    original_volume = services.kernel.mass_properties().volume
    diameter.setValue(200.0)
    qtbot.waitUntil(lambda: "预览失败" in window.status_command.text(), timeout=30000)
    assert not commit.isEnabled()
    assert len(loaded.document.commands) == 2
    assert services.kernel.mass_properties().volume == pytest.approx(original_volume)
    diameter.setValue(6.0)
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    commit.click()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 3 and not unit.is_busy, timeout=30000)
    params = loaded.document.commands[-1].params
    base_hole = cast("dict[str, object]", params["base_hole"])
    assert base_hole["position"] == {"kind": "center"}
    assert services.kernel.mass_properties().volume == pytest.approx(
        math.pi * (40**2 - 10**2 - 4 * 3**2) * 8
    )
    assert services.kernel.geometry_check().is_valid

    panel = window.right_panel
    assert panel is not None
    panel.select_feature_ordinal(2)
    edit = panel.findChild(QPushButton, "editHistoryFeature")
    assert edit is not None and edit.isEnabled()
    original_timestamp = loaded.document.commands[-1].timestamp_utc

    def change_holes() -> None:
        dialog = window.findChild(HistoryEditDialog)
        assert dialog is not None
        try:
            hole_diameter = dialog.parameter_form.field_widget("base_hole.diameter")
            hole_count = dialog.parameter_form.field_widget("pattern.count")
            assert isinstance(hole_diameter, QDoubleSpinBox)
            assert isinstance(hole_count, QSpinBox)
            hole_diameter.setValue(8.0)
            hole_count.setValue(6)
            dialog.reason_field.setText("法兰改为六个直径 8 mm 安装孔")
            dialog.preview_changes()
            qtbot.waitUntil(dialog.confirm_button.isEnabled, timeout=30000)
            dialog.confirm_changes()
        except BaseException:
            dialog.reject()
            raise

    QTimer.singleShot(0, change_holes)
    edit.click()
    qtbot.waitUntil(
        lambda: bool(loaded.document.commands[-1].amendments) and not unit.is_busy, timeout=30000
    )
    assert len(loaded.document.commands) == 3
    assert loaded.document.commands[-1].timestamp_utc == original_timestamp
    assert len(loaded.document.commands[-1].amendments) == 1
    assert services.kernel.mass_properties().volume == pytest.approx(
        math.pi * (40**2 - 10**2 - 6 * 4**2) * 8
    )
    assert services.kernel.geometry_check().is_valid


def test_open_sketch_preview_locates_failure_and_allows_correct_profile(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    first_id = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
    second_id = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
    entity_id = "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c"
    for sketch in (
        Sketch(first_id, WorkPlaneFrame.xz(), (LineEntity(entity_id, (12.0, 8.0), (20.0, 8.0)),)),
        Sketch(second_id, WorkPlaneFrame.xz(), (CircleEntity(entity_id, (0.0, 0.0), 5.0),)),
    ):
        loaded.bus.execute("sketch.create", sketch.to_mapping(), "test")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.extrude")
    bar = window.modeling_command_bar
    assert bar is not None
    source = bar.findChild(QComboBox, "extrudeSource")
    picker = bar.findChild(QComboBox, "sketchProfile")
    distance = bar.findChild(QDoubleSpinBox, "distance")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert source is not None and picker is not None and commit is not None and distance is not None
    source.setCurrentIndex(source.findData("sketch"))
    picker.setCurrentIndex(picker.findData(first_id))
    qtbot.waitUntil(lambda: "预览失败" in window.status_command.text(), timeout=30000)
    assert not commit.isEnabled()
    assert "U/V (mm)" in window.status_command.toolTip()
    assert entity_id in window.status_command.toolTip()
    assert "(12, 8)" in window.status_command.toolTip()
    assert len(loaded.document.commands) == 2
    picker.setCurrentIndex(picker.findData(second_id))
    distance.setValue(8.0)
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    assert len(loaded.document.commands) == 2
    commit.click()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 3 and not unit.is_busy, timeout=30000)
    assert services.kernel.mass_properties().volume == pytest.approx(math.pi * 5**2 * 8)


@pytest.mark.parametrize("change", ["undo", "redo", "write", "amend", "undo_redo"])
def test_document_changes_expire_accepted_modeling_preview(qtbot: QtBot, change: str) -> None:
    services = build_app(discoverers=())
    loaded = mycad_app.new_document(services)
    params: dict[str, object] = {"size_x": 20.0, "size_y": 20.0, "size_z": 20.0}
    loaded.bus.execute("feature.box", params, "test")
    if change == "redo":
        loaded.bus.undo()
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.box")
    bar, viewport, unit = window.modeling_command_bar, window.viewport, window.execution_unit
    assert bar is not None and viewport is not None and unit is not None
    mode = bar.findChild(QComboBox, "mode")
    assert mode is not None
    mode.setCurrentIndex(mode.findData("add"))
    viewport.workplane_point_picked.emit((50.0, 0.0, 0.0), QPoint())
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert commit is not None
    qtbot.waitUntil(lambda: commit.isEnabled() and not unit.is_busy, timeout=30000)
    old_revision = loaded.document.revision
    if change == "undo":
        window.request_undo()
    elif change == "redo":
        window.request_redo()
    elif change == "write":
        loaded.bus.execute("feature.box", {**params, "size_x": 30.0}, "test")
    elif change == "amend":
        loaded.bus.edit_and_replay(
            0, {**params, "size_x": 30.0}, actor="test", reason="preview regression"
        )
    else:
        loaded.bus.undo()
        loaded.bus.redo()
    qtbot.waitUntil(
        lambda: loaded.document.revision > old_revision and not unit.is_busy, timeout=30000
    )
    qtbot.waitUntil(lambda: not commit.isEnabled(), timeout=3000)
    before = loaded.document.commands
    commit.click()
    assert loaded.document.commands == before
    # Explicit input change regenerates a preview against the new document.
    viewport.workplane_point_picked.emit((60.0, 0.0, 0.0), QPoint())
    qtbot.waitUntil(lambda: commit.isEnabled() and not unit.is_busy, timeout=30000)
    commit.click()
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == len(before) + 1 and not unit.is_busy, timeout=30000
    )


def test_commit_checks_document_revision_before_queued_events_are_delivered(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = mycad_app.new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20.0, "size_y": 20.0, "size_z": 20.0}, "test")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    assert window.command_palette is not None and window.viewport is not None
    window.command_palette.command_activated.emit("feature.box")
    window.viewport.workplane_point_picked.emit((50.0, 0.0, 0.0), QPoint())
    bar, unit = window.modeling_command_bar, window.execution_unit
    assert bar is not None and unit is not None
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert commit is not None
    qtbot.waitUntil(lambda: commit.isEnabled() and not unit.is_busy, timeout=30000)
    loaded.bus.undo()
    # No Qt event processing between the external write and the confirm click.
    commit.click()
    assert not unit.is_busy
    assert not commit.isEnabled()
    assert loaded.document.commands == ()


def test_sphere_numeric_preview_and_commit(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.sphere")
    bar = window.modeling_command_bar
    assert bar is not None and bar.isVisible()
    center_z = bar.findChild(QDoubleSpinBox, "center_z")
    assert center_z is not None
    center_z.setValue(12)
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert commit is not None
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    assert not loaded.document.commands
    commit.click()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(
        lambda: len(loaded.document.commands) == 1 and not unit.is_busy,
        timeout=30000,
    )
    assert services.kernel.mass_properties().center_of_mass == pytest.approx((0, 0, 12))
    loaded.bus.undo()
    assert not loaded.document.commands and not services.kernel.body_ids
    loaded.bus.redo()
    assert services.kernel.mass_properties().center_of_mass == pytest.approx((0, 0, 12))


def test_sphere_positioning_adopts_world_xz_and_cancel_preserves_document(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.sphere")
    bar = window.modeling_command_bar
    assert bar is not None
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert commit is not None
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    bar.position_requested.emit()
    dialog = window.findChild(WorkplanePositionDialog)
    assert dialog is not None
    dialog.plane_combo.setCurrentIndex(1)
    dialog.lock_plane()
    dialog.u_field.setValue(4)
    dialog.v_field.setValue(7)
    dialog.adopt()
    assert bar.values()["center"] == pytest.approx([4, 0, -7])
    bar.cancel_requested.emit()
    assert loaded.document.commands == ()
    assert services.kernel.mass_properties().solid_count == 0


def test_sphere_positioning_blocks_commit_and_closes_on_cancel(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.sphere")
    bar = window.modeling_command_bar
    assert bar is not None
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert commit is not None
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    bar.position_requested.emit()
    dialog = window.findChild(WorkplanePositionDialog)
    assert dialog is not None and dialog.isVisible()
    assert not commit.isEnabled()
    bar.cancel_requested.emit()
    assert not dialog.isVisible()
    assert not loaded.document.commands


def test_sphere_positioning_uses_visible_source_anchors(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None and window.viewport is not None
    window.command_palette.command_activated.emit("feature.sphere")
    bar = window.modeling_command_bar
    assert bar is not None
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert commit is not None
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    bar.position_requested.emit()
    assert window.findChild(WorkplanePositionDialog) is not None
    snapshots = window.viewport.snapshots()
    snapshot = snapshots[-1] if snapshots else None
    assert snapshot is not None
    assert window.viewport.displayed_snapshot_id() == snapshot.state_id
    assert max(vertex.point[0] for vertex in snapshot.vertices) == pytest.approx(5)
    assert any(
        anchor.point == pytest.approx((5, 5, 5))
        for anchor in window.viewport.interaction_snap_anchors()
    )


def test_sphere_positioning_cannot_commit_after_parameter_change(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.sphere")
    bar = window.modeling_command_bar
    assert bar is not None
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    radius = bar.findChild(QDoubleSpinBox, "radius")
    assert commit is not None and radius is not None
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    bar.position_requested.emit()
    dialog = window.findChild(WorkplanePositionDialog)
    assert dialog is not None
    radius.setValue(7)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=30000)
    qtbot.wait(500)
    assert not commit.isEnabled()
    assert not loaded.document.commands


@pytest.mark.parametrize("command_id", ["feature.box", "feature.cylinder", "feature.sphere"])
def test_new_primitive_defaults_to_preserving_existing_solid(qtbot: QtBot, command_id: str) -> None:
    services = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute("feature.sphere", {"radius": 5}, "test")
    original_volume = services.kernel.mass_properties().volume
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit(command_id)
    bar, viewport = window.modeling_command_bar, window.viewport
    assert bar is not None and viewport is not None
    mode = bar.findChild(QComboBox, "mode")
    assert mode is not None and mode.currentData() == "add"
    assert services.kernel.mass_properties().volume == pytest.approx(original_volume)
    if command_id == "feature.sphere":
        x = bar.findChild(QDoubleSpinBox, "center_x")
        assert x is not None
        x.setValue(50)
    else:
        viewport.workplane_point_picked.emit((50.0, 0.0, 0.0), QPoint())
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert commit is not None
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    assert services.kernel.mass_properties().volume == pytest.approx(original_volume)
    commit.click()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)
    assert loaded.document.commands[-1].params["mode"] == "add"
    assert services.kernel.mass_properties().solid_count == 2
    assert services.kernel.mass_properties().volume > original_volume
