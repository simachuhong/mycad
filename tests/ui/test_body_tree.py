# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Current bodies have real tree identities, separate from feature history."""

from __future__ import annotations

from typing import Protocol, cast

from pyqtgraph.opengl import GLMeshItem, MeshData
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.ui.main_window import MainWindow
from mycad.ui.viewport import SelectionKind


class _MeshProbe(Protocol):
    opts: dict[str, object]


def test_current_body_selection_is_synchronized_without_history_preview(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 10}, "test")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    view, panel = window.viewport, window.right_panel
    assert view is not None and panel is not None
    tree = panel.structure_tree
    matches = tree.findItems("实体 1", Qt.MatchFlag.MatchRecursive | Qt.MatchFlag.MatchExactly)
    assert len(matches) == 1
    body = matches[0]
    before = loaded.document.commands
    view.setCameraPosition(distance=95)
    view.pan(25, 15, 0, relative="view-upright")
    camera = view.camera_state()
    tree.itemClicked.emit(body, 0)
    selected = view.selection()
    assert selected is not None and selected.kind == "body"
    assert view.history_preview_ordinal() is None
    assert tree.currentItem() is body
    assert view.camera_state() == camera
    view.clear_selection()
    assert tree.currentItem() is None
    view.resize(800, 600)
    view.set_orientation("top")
    view.fit_view()
    view.set_selection_filter("face")
    assert view.pick_at(400, 300)
    assert tree.currentItem() is body
    assert "面" in panel.view_selection_label.text()
    assert loaded.document.commands == before
    loaded.bus.undo()
    qtbot.waitUntil(lambda: view.snapshots() == ())
    assert not tree.findItems("实体 1", Qt.MatchFlag.MatchRecursive | Qt.MatchFlag.MatchExactly)


def test_multiple_selected_bodies_are_all_selected_in_tree(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10}, "test")
    loaded.bus.execute(
        "feature.box",
        {"size_x": 10, "size_y": 10, "size_z": 10, "center": [20, 0, 0], "mode": "add"},
        "test",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    view, panel = window.viewport, window.right_panel
    assert view is not None and panel is not None
    view.resize(800, 600)
    view.set_orientation("top")
    view.fit_view()
    for x in (0, 20):
        point = view.project_world_point((x, 0, 5))
        assert point is not None and view.pick_at(*point, toggle=True)
    assert {item.text(0) for item in panel.structure_tree.selectedItems()} == {"实体 1", "实体 2"}


def test_body_visibility_filters_render_and_all_selection_without_changing_model(
    qtbot: QtBot,
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    for x, mode in ((0, "new"), (20, "add")):
        loaded.bus.execute(
            "feature.box",
            {"size_x": 10, "size_y": 10, "size_z": 10, "center": [x, 0, 0], "mode": mode},
            "test",
        )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    view, panel = window.viewport, window.right_panel
    assert view is not None and panel is not None
    view.resize(800, 600)
    view.set_orientation("top")
    view.fit_view()
    body = services.kernel.body_ids[0]
    history, volume = loaded.document.commands, services.kernel.mass_properties().volume
    camera = view.camera_state()
    assert view.select_body(body)
    assert view.set_body_visible(body, False)
    assert not view.body_visible(body)
    assert view.selection() is None
    assert view.camera_state() == camera
    assert view.visible_body_ids() == (services.kernel.body_ids[1],)
    item = next(item for item in view.items if isinstance(item, GLMeshItem) and item.visible())
    mesh = cast("_MeshProbe", item).opts["meshdata"]
    assert isinstance(mesh, MeshData)
    vertices = mesh.vertexes()
    assert vertices is not None
    assert float(vertices[:, 0].min()) == 15.0
    assert float(vertices[:, 0].max()) == 25.0
    probes: tuple[tuple[SelectionKind, tuple[float, float, float]], ...] = (
        ("body", (0.0, 0.0, 5.0)),
        ("face", (0.0, 0.0, 5.0)),
        ("edge", (5.0, 0.0, 5.0)),
        ("vertex", (5.0, 5.0, 5.0)),
    )
    for kind, point in probes:
        screen = view.project_world_point(point)
        assert screen is not None
        assert view.selection_target_at(*screen, kind) is None
    selected = view.targets_in_screen_rect((0.0, 0.0), (800.0, 600.0), crossing=True)
    assert {identity for item in selected for identity in item.body_ids} == {
        services.kernel.body_ids[1]
    }
    tree = panel.structure_tree
    leaf = tree.findItems("实体 1", Qt.MatchFlag.MatchRecursive | Qt.MatchFlag.MatchExactly)[0]
    assert leaf.checkState(0) == Qt.CheckState.Unchecked
    assert leaf.text(1) == "隐藏"
    tree.itemClicked.emit(leaf, 0)
    assert "已隐藏" in window.status_command.text()
    assert view.selection() is None
    leaf.setCheckState(0, Qt.CheckState.Checked)
    assert view.body_visible(body)
    assert leaf.text(1) == "显示"
    assert loaded.document.commands == history
    assert services.kernel.mass_properties().volume == volume


def test_body_visibility_preview_restoration_and_expired_identity(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10}, "test")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    view, panel = window.viewport, window.right_panel
    assert view is not None and panel is not None
    identity = services.kernel.body_ids[0]
    assert view.set_body_visible(identity, False)
    assert not view.mesh_visible()
    snapshot = view.snapshots()[-1]
    view.show_candidate_preview(snapshot, preserve_view=True)
    assert view.mesh_visible()
    assert not view.body_visibility_editable()
    assert not view.set_body_visible(identity, True)
    view.clear_candidate_preview()
    assert view.body_visibility_editable()
    assert not view.mesh_visible()
    show_all = window.findChild(QPushButton, "showAllBodies")
    assert show_all is not None and show_all.isEnabled()
    show_all.click()
    assert view.mesh_visible()
    assert view.set_body_visible(identity, False)
    loaded.bus.undo()
    loaded.bus.redo()
    view.refresh()
    assert not view.set_body_visible(identity, False)
    assert view.visible_body_ids() == services.kernel.body_ids
    assert view.mesh_visible()


def test_body_visibility_cannot_read_kernel_during_worker_execution(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10}, "test")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    view = window.viewport
    assert view is not None
    identity = services.kernel.body_ids[0]
    view.set_execution_busy(True)
    assert not view.body_visibility_editable()
    assert not view.set_body_visible(identity, False)
    assert view.body_visible(identity)
    view.set_execution_busy(False)
    assert view.set_body_visible(identity, False)


def test_body_origin_links_select_history_and_properties_show_operation_inputs(
    qtbot: QtBot,
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10}, "test")
    source = services.kernel.interactive_body_selector(services.kernel.body_ids[0])
    loaded.bus.execute(
        "modify.body_transform",
        {"body": source, "transform": {"operation": "copy", "translation_mm": [20, 0, 0]}},
        "test",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    view, panel = window.viewport, window.right_panel
    assert view is not None and panel is not None
    tree = panel.structure_tree
    copied = tree.findItems("实体 2", Qt.MatchFlag.MatchRecursive | Qt.MatchFlag.MatchExactly)[0]
    assert copied.childCount() == 2
    origin_link, input_link = copied.child(0), copied.child(1)
    assert origin_link is not None and input_link is not None
    assert "来源" in origin_link.text(0)
    assert "#1" in origin_link.text(0)
    assert "源实体" in input_link.text(0)
    assert "#0" in input_link.text(0)
    tree.itemClicked.emit(copied, 0)
    table = panel.property_table
    cells = [
        item.text()
        for row in range(table.rowCount())
        for column in range(table.columnCount())
        if (item := table.item(row, column)) is not None
    ]
    assert any("来源" in text for text in cells)
    assert any("源实体" in text for text in cells)
    assert view.history_preview_ordinal() is None
    tree.itemClicked.emit(origin_link, 0)
    qtbot.waitUntil(lambda: view.history_preview_ordinal() == 1, timeout=10000)
    tree.itemClicked.emit(input_link, 0)
    qtbot.waitUntil(lambda: view.history_preview_ordinal() == 0, timeout=10000)
    # State identifiers without a checked document mapping must never become ordinals.
    panel.set_current_snapshot(view.snapshots()[-1], state_ids=())
    copied = tree.findItems("实体 2", Qt.MatchFlag.MatchRecursive | Qt.MatchFlag.MatchExactly)[0]
    unavailable = copied.child(0)
    assert unavailable is not None and "不可用" in unavailable.text(0)
