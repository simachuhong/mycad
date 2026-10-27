# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Focused checks for the non-obstructing fillet command strip."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app as mycad_app
from mycad.app import AppServices, build_app
from mycad.ui.main_window import MainWindow

_BOX: tuple[str, dict[str, object]] = (
    "feature.box",
    {
        "size_x": 20.0,
        "size_y": 20.0,
        "size_z": 10.0,
        "center": [0.0, 0.0, 0.0],
        "mode": "new",
    },
)


def test_fillet_bar_sits_outside_viewport_and_accepting_radius_is_not_commit(
    qtbot: QtBot,
) -> None:
    services: AppServices = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    loaded = mycad_app.new_document(services)
    window.bind_document(loaded)
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("modify.fillet")
    window.show()
    qtbot.wait(50)

    bar = window.fillet_command_bar
    viewport = window.viewport
    assert bar is not None
    assert viewport is not None
    assert not bar.isHidden()
    bar_bottom = bar.mapToGlobal(QPoint(0, bar.height())).y()
    viewport_top = viewport.mapToGlobal(QPoint(0, 0)).y()
    assert bar_bottom <= viewport_top

    before = tuple(loaded.document.commands)
    bar.radius_edit.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.keyClick(bar.radius_edit, Qt.Key.Key_1)
    QTest.keyClick(bar.radius_edit, Qt.Key.Key_Return)
    assert tuple(loaded.document.commands) == before
    assert window.plan_draft is not None
    assert window.plan_draft.plan().steps[0].id == "modify.fillet"
    assert not bar.commit_button.isEnabled()


def test_fillet_selection_previews_and_commits_one_group(qtbot: QtBot) -> None:
    services: AppServices = build_app(discoverers=[])
    loaded = mycad_app.new_document(services)
    loaded.bus.execute(_BOX[0], _BOX[1], "test")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)

    viewport = window.viewport
    bar = window.fillet_command_bar
    assert viewport is not None and bar is not None
    viewport.resize(900, 600)
    viewport.set_orientation("top")
    viewport.fit_view()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("modify.fillet")
    snapshot = viewport.snapshots()[-1]
    selected_topology_id: object | None = None
    selected_point: tuple[float, float] | None = None
    for edge in snapshot.boundary_edges:
        start, end = edge.points[:2]
        midpoint = (
            (start[0] + end[0]) / 2.0,
            (start[1] + end[1]) / 2.0,
            (start[2] + end[2]) / 2.0,
        )
        projected = viewport.project_world_point(midpoint)
        if projected is None:
            continue
        target = viewport.selection_target_at(*projected, "edge")
        if target is not None and edge.topology_id in target.topology_ids:
            assert viewport.pick_at(*projected, toggle=True)
            selected_topology_id = edge.topology_id
            selected_point = projected
            break
    else:
        raise AssertionError("no selectable box edge was found")

    qtbot.waitUntil(lambda: "预览已更新" in window.status_command.text(), timeout=30000)
    assert bar.commit_button.isEnabled()
    assert selected_topology_id is not None and selected_point is not None
    for edge in snapshot.boundary_edges:
        if edge.topology_id == selected_topology_id:
            continue
        start, end = edge.points[:2]
        midpoint = (
            (start[0] + end[0]) / 2.0,
            (start[1] + end[1]) / 2.0,
            (start[2] + end[2]) / 2.0,
        )
        projected = viewport.project_world_point(midpoint)
        if projected is None:
            continue
        target = viewport.selection_target_at(*projected, "edge")
        if target is not None and edge.topology_id in target.topology_ids:
            assert viewport.pick_at(*projected, toggle=True)
            selection = viewport.selection()
            assert selection is not None and len(selection.topology_ids) == 2
            assert viewport.pick_at(*selected_point, toggle=True)
            selection = viewport.selection()
            assert selection is not None and len(selection.topology_ids) == 1
            break
    else:
        raise AssertionError("no second distinct source edge was selectable")

    qtbot.waitUntil(lambda: "预览已更新" in window.status_command.text(), timeout=30000)
    assert bar.commit_button.isEnabled()
    bar.commit_button.click()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)
    assert "已完成本组圆角" in window.status_command.text()
    assert len(loaded.document.commands) == 2


def test_fillet_confirmation_checks_revision_before_queued_refresh(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = mycad_app.new_document(services)
    loaded.bus.execute(_BOX[0], _BOX[1], "test")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    viewport, bar, unit = window.viewport, window.fillet_command_bar, window.execution_unit
    assert viewport is not None and bar is not None and unit is not None
    viewport.resize(900, 600)
    viewport.set_orientation("top")
    viewport.fit_view()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("modify.fillet")
    for edge in viewport.snapshots()[-1].boundary_edges:
        first, second = edge.points[:2]
        midpoint = (
            (first[0] + second[0]) / 2,
            (first[1] + second[1]) / 2,
            (first[2] + second[2]) / 2,
        )
        projected = viewport.project_world_point(midpoint)
        if projected is not None:
            target = viewport.selection_target_at(*projected, "edge")
            if target is not None and edge.topology_id in target.topology_ids:
                assert viewport.pick_at(*projected, toggle=True)
                break
    else:
        raise AssertionError("no selectable edge")
    qtbot.waitUntil(lambda: bar.commit_button.isEnabled() and not unit.is_busy, timeout=30000)
    before = loaded.document.commands
    loaded.bus.undo()
    loaded.bus.redo()
    assert loaded.document.commands == before
    bar.commit_button.click()
    assert not unit.is_busy
    assert not bar.commit_button.isEnabled()
    assert loaded.document.commands == before
