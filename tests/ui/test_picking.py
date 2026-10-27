# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Current-model ray picking and explicit historical-state preview tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from build123d import Part
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QTreeWidgetItem
from pytestqt.qtbot import QtBot

from mycad.app import AppServices, build_app, new_document
from mycad.core.geometry_types import Tessellation
from mycad.core.groups import NamedGroup
from mycad.core.persistence import LoadedDocument
from mycad.geom import kernel as kernel_module
from mycad.ui.main_window import MainWindow
from mycad.ui.right_panel import ORDINAL_ROLE
from mycad.ui.viewport import GLViewport, SelectionState


# Teardown 兜底（同 test_document_lifecycle）：pytest-qt 关脏态窗走真实三选
# 弹窗，offscreen 下 exec 阻塞可挂死整个进程；落到 "discard" 保进程可退。
def _discard(self: MainWindow) -> str:
    return "discard"


@pytest.fixture(autouse=True)
def _autodiscard_close(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MainWindow, "_ask_save_dialog", _discard)


_BOX: tuple[str, dict[str, object]] = (
    "feature.box",
    {
        "size_x": 80.0,
        "size_y": 80.0,
        "size_z": 8.0,
        "center": [0.0, 0.0, 0.0],
        "mode": "new",
    },
)
_CYL: tuple[str, dict[str, object]] = (
    "feature.cylinder",
    {
        "radius": 10.0,
        "height": 30.0,
        "center": [0.0, 0.0, 14.0],
        "mode": "new",
    },
)
_CUT: tuple[str, dict[str, object]] = (
    "modify.boolean_cut",
    {
        "tool": {
            "type": "cylinder",
            "radius": 10.0,
            "height": 30.0,
            "center": [0.0, 0.0, 0.0],
        }
    },
)


def _ray_down(x: float, y: float) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Camera-independent vertical ray from high above (-Z direction)."""
    return ((x, y, 200.0), (0.0, 0.0, -1.0))


def _center_ray(
    _x: float, _y: float
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    return _ray_down(0.0, 0.0)


def _two_feature_ray(
    x: float, _y: float
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    return _ray_down(0.0, 0.0) if x == 0.0 else _ray_down(35.0, 0.0)


def _point3(point: tuple[float, ...]) -> tuple[float, float, float]:
    return point[0], point[1], point[2]


def _loaded(services: AppServices, *commands: tuple[str, dict[str, object]]) -> LoadedDocument:
    loaded = new_document(services)
    for command_id, params in commands:
        loaded.bus.execute(command_id, params, "test")
    return loaded


def _find_leaf(item: QTreeWidgetItem | None, ordinal: int) -> QTreeWidgetItem | None:
    """特征叶挂在 根→分组→叶 两层，递归找 ORDINAL_ROLE 命中的节点。"""
    if item is None:
        return None
    for index in range(item.childCount()):
        child = item.child(index)
        if child is None:
            continue
        data = child.data(0, ORDINAL_ROLE)
        if isinstance(data, int) and not isinstance(data, bool) and data == ordinal:
            return child
        found = _find_leaf(child, ordinal)
        if found is not None:
            return found
    return None


def _pump_events() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    assert app is not None
    app.processEvents()


@pytest.fixture()
def services(qapp: object) -> AppServices:
    return build_app(discoverers=[])


@pytest.fixture()
def two_feature_view(services: AppServices, qapp: object) -> GLViewport:
    view = GLViewport(viewport_port=services.kernel)
    view.bind_document(_loaded(services, _BOX, _CYL))
    _pump_events()
    return view


def test_snapshot_ids_follow_command_order(two_feature_view: GLViewport) -> None:
    ids = two_feature_view.history_state_ids()
    assert ids == ("feature.box:0", "feature.cylinder:1")
    assert two_feature_view.state_ordinal("feature.box:0") == 0
    assert two_feature_view.state_ordinal("feature.cylinder:1") == 1
    assert two_feature_view.state_ordinal("feature.nope:9") == -1


def test_default_pick_uses_only_current_model(two_feature_view: GLViewport) -> None:
    # The second `new` feature replaced the box. The current cylinder is hit
    # on-axis; the old box at x=35 is not a selectable historical ghost.
    assert two_feature_view.pick_current_entity_at_ray(*_ray_down(0.0, 0.0)) is True
    assert two_feature_view.pick_current_entity_at_ray(*_ray_down(35.0, 0.0)) is False
    assert two_feature_view.pick_current_entity_at_ray(*_ray_down(500.0, 500.0)) is False


def test_current_model_selection_is_independent_of_history_source(
    two_feature_view: GLViewport, monkeypatch: pytest.MonkeyPatch
) -> None:
    def center_camera_ray(
        _x: float, _y: float
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        return _ray_down(0.0, 0.0)

    def edge_camera_ray(
        _x: float, _y: float
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        return _ray_down(35.0, 0.0)

    monkeypatch.setattr(two_feature_view, "camera_ray", center_camera_ray)
    assert two_feature_view.pick_at(0.0, 0.0) is True
    assert two_feature_view.current_entity_selected() is True
    # Current model selection uses an overlay on the current scene only.
    assert len(two_feature_view.items) == 3

    monkeypatch.setattr(two_feature_view, "camera_ray", edge_camera_ray)
    assert two_feature_view.pick_at(0.0, 0.0) is False
    assert two_feature_view.current_entity_selected() is False
    assert len(two_feature_view.items) == 3
    assert two_feature_view.selection() is None


def test_repeated_selection_reuses_scene_and_highlight_items(
    two_feature_view: GLViewport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def ray_for_pixel(
        x: float, _y: float
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        return _ray_down(0.0, 0.0) if int(x) % 2 == 0 else _ray_down(35.0, 0.0)

    monkeypatch.setattr(two_feature_view, "camera_ray", ray_for_pixel)
    assert two_feature_view.pick_at(0.0, 0.0)
    original_items = tuple(two_feature_view.items)
    for index in range(40):
        assert two_feature_view.pick_at(float(index % 2), 0.0) is (index % 2 == 0)

    assert tuple(two_feature_view.items) == original_items
    assert len(two_feature_view.items) == 3


def test_history_preview_replaces_scene_and_returns_to_current(
    two_feature_view: GLViewport,
) -> None:
    assert two_feature_view.history_preview_ordinal() is None
    assert two_feature_view.displayed_snapshot_id() == "feature.cylinder:1"
    assert two_feature_view.pick_current_entity_at_ray(*_ray_down(0.0, 0.0)) is True
    assert two_feature_view.pick_current_entity_at_ray(*_ray_down(35.0, 0.0)) is False
    assert two_feature_view.preview_history_feature(0) is True
    assert two_feature_view.history_preview_ordinal() == 0
    assert two_feature_view.displayed_snapshot_id() == "feature.box:0"
    assert two_feature_view.pick_current_entity_at_ray(*_ray_down(0.0, 0.0)) is False
    # Preview changes the displayed state; it is not an old-mesh overlay.
    assert len(two_feature_view.items) == 2
    two_feature_view.show_current_model()
    assert two_feature_view.history_preview_ordinal() is None
    assert two_feature_view.displayed_snapshot_id() == "feature.cylinder:1"
    assert len(two_feature_view.items) == 2


def test_history_mesh_is_only_extracted_when_previewed(
    services: AppServices, qapp: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = kernel_module.build_tessellation
    calls = 0

    def count_calls(
        part: Part | None,
        linear: object,
        angular: object,
    ) -> Tessellation:
        nonlocal calls
        calls += 1
        return original(part, linear, angular)

    monkeypatch.setattr(kernel_module, "build_tessellation", count_calls)
    view = GLViewport(viewport_port=services.kernel)
    try:
        view.bind_document(_loaded(services, _BOX, _CYL))
        assert calls == 1
        assert view.history_state_ids() == ("feature.box:0", "feature.cylinder:1")
        monkeypatch.setattr(
            view,
            "camera_ray",
            _two_feature_ray,
        )
        assert view.pick_at(0.0, 0.0)
        assert not view.pick_at(35.0, 0.0)
        assert calls == 1
        assert view.preview_history_feature(0)
        assert calls == 2
        assert view.preview_history_feature(0)
        assert calls == 2
        view.show_current_model()
        view.refresh()
        assert calls == 2
    finally:
        view.dispose()


def test_model_refresh_reuses_overlay_but_invalidates_old_selection(
    services: AppServices, qapp: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded = _loaded(services, _BOX)
    view = GLViewport(viewport_port=services.kernel)
    try:
        view.bind_document(loaded)
        monkeypatch.setattr(view, "camera_ray", _center_ray)
        assert view.pick_at(0.0, 0.0)
        original_items = tuple(view.items)

        rebuilds = view.rebuild_count()
        loaded.bus.edit_and_replay(
            0,
            {
                "size_x": 10.0,
                "size_y": 10.0,
                "size_z": 10.0,
                "center": [100.0, 0.0, 0.0],
                "mode": "new",
            },
            "test",
            "move geometry",
        )
        _pump_events()

        assert view.rebuild_count() == rebuilds + 1
        assert not view.current_entity_selected()
        assert tuple(view.items) == original_items
        assert not view.pick_current_entity_at_ray(*_ray_down(0.0, 0.0))
        assert view.pick_current_entity_at_ray(*_ray_down(100.0, 0.0))
    finally:
        view.dispose()


def test_rebind_and_dispose_clear_old_selection_resources(
    services: AppServices, qapp: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = GLViewport(viewport_port=services.kernel)
    try:
        view.bind_document(_loaded(services, _BOX))
        monkeypatch.setattr(view, "camera_ray", _center_ray)
        assert view.pick_at(0.0, 0.0)
        original_items = tuple(view.items)

        replacement_box: tuple[str, dict[str, object]] = (
            "feature.box",
            {
                "size_x": 10.0,
                "size_y": 10.0,
                "size_z": 10.0,
                "center": [200.0, 0.0, 0.0],
                "mode": "new",
            },
        )
        view.bind_document(_loaded(services, replacement_box))

        assert not view.current_entity_selected()
        assert tuple(view.items) == original_items
        assert not view.pick_current_entity_at_ray(*_ray_down(0.0, 0.0))
        assert view.pick_current_entity_at_ray(*_ray_down(200.0, 0.0))

        view.dispose()
        assert not view.items
        assert view.selection() is None
        assert not view.current_entity_selected()
    finally:
        view.dispose()


def test_annotation_changes_keep_viewport_selection_and_history_preview(
    services: AppServices, qapp: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded = _loaded(services, _BOX, _CYL)
    view = GLViewport(viewport_port=services.kernel)
    try:
        view.bind_document(loaded)
        monkeypatch.setattr(view, "camera_ray", _center_ray)
        assert view.pick_at(0.0, 0.0)
        selected = view.selection()
        assert selected is not None

        rebuilds = view.rebuild_count()
        loaded.document.set_metadata("part_no", "P2-08")
        _pump_events()

        assert view.rebuild_count() == rebuilds
        assert view.current_entity_selected()
        assert view.selection() == selected

        assert view.preview_history_feature(0)
        rebuilds = view.rebuild_count()
        loaded.document.add_named_group(NamedGroup(name="top-faces"))
        _pump_events()

        assert view.rebuild_count() == rebuilds
        assert view.history_preview_ordinal() == 0
    finally:
        view.dispose()


def test_boolean_cut_picking_uses_post_execution_state(services: AppServices) -> None:
    view = GLViewport(viewport_port=services.kernel)
    try:
        view.bind_document(_loaded(services, _BOX, _CUT))
        _pump_events()
        ids = view.history_state_ids()
        # Destructive commands keep the post-execution semantics: the cut
        # result is one snapshot; no removed-volume feature id exists.
        assert ids == ("feature.box:0", "modify.boolean_cut:1")
        # The final model has a through-hole and a solid rim. Historical
        # snapshots never contribute candidates to default hit testing.
        assert view.pick_current_entity_at_ray(*_ray_down(0.0, 0.0)) is False
        assert view.pick_current_entity_at_ray(*_ray_down(35.0, 0.0)) is True
    finally:
        view.dispose()


def test_pick_at_without_camera_is_empty(services: AppServices) -> None:
    view = GLViewport(viewport_port=services.kernel)
    try:
        # Never resized: no usable camera geometry -> nothing picked.
        assert view.pick_at(0, 0) is False
    finally:
        view.dispose()


def test_current_entity_pick_does_not_claim_feature_source(
    qtbot: QtBot, services: AppServices
) -> None:
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(_loaded(services, _BOX, _CYL))
    assert window.viewport is not None
    assert window.right_panel is not None
    tree = window.right_panel.structure_tree
    window.right_panel.select_feature_ordinal(0)
    assert tree.currentItem() is not None
    window.viewport.current_entity_picked.emit(True)
    assert tree.currentItem() is None
    assert window.status_selection.text() == "当前模型已选中"
    # Empty-space pick clears current-entity selection without claiming a
    # feature ordinal either.
    window.viewport.current_entity_picked.emit(False)
    assert window.status_selection.text() == "选择 0"


def test_tree_click_previews_history_and_return_action_restores_current(
    qtbot: QtBot, services: AppServices
) -> None:
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(_loaded(services, _BOX, _CYL))
    assert window.viewport is not None
    assert window.right_panel is not None
    viewport = window.viewport
    tree = window.right_panel.structure_tree
    assert not window.act_return_current_model.isEnabled()
    target = _find_leaf(tree.invisibleRootItem(), 0)
    assert target is not None
    # 用户点击路径：itemClicked 才发 structure_selection_changed；
    # setCurrentItem 是编程式选中（视口→树方向专用），不发该信号。
    tree.itemClicked.emit(target, 0)
    qtbot.waitUntil(lambda: viewport.history_preview_ordinal() == 0)
    assert viewport.history_preview_ordinal() == 0
    assert viewport.displayed_snapshot_id() == "feature.box:0"
    assert window.status_selection.text() == "历史预览 #0"
    assert window.act_return_current_model.isEnabled()
    window.act_return_current_model.trigger()
    assert viewport.history_preview_ordinal() is None
    assert viewport.displayed_snapshot_id() == "feature.cylinder:1"
    assert tree.currentItem() is None


def test_body_face_edge_and_vertex_filters_select_runtime_topology(
    services: AppServices,
) -> None:
    loaded = _loaded(services, _BOX)
    view = GLViewport(viewport_port=services.kernel)
    try:
        view.resize(900, 600)
        view.bind_document(loaded)
        view.set_orientation("top")
        view.fit_view()
        center = (450.0, 300.0)
        snapshot = view.snapshots()[-1]

        view.set_selection_filter("body")
        assert view.pick_at(*center)
        body_selection = view.selection()
        assert body_selection is not None and body_selection.kind == "body"
        assert isinstance(body_selection, SelectionState)
        assert body_selection.body_ids == services.kernel.body_ids

        view.set_selection_filter("face")
        assert view.pick_at(*center)
        face_selection = view.selection()
        assert face_selection is not None and face_selection.kind == "face"
        assert face_selection.topology_ids[0] in {face.topology_id for face in snapshot.faces}

        edge = snapshot.boundary_edges[0]
        edge_point = _point3(
            tuple(
                (start + end) / 2.0
                for start, end in zip(edge.points[0], edge.points[1], strict=True)
            )
        )
        projected_edge = view.project_world_point(edge_point)
        assert projected_edge is not None
        view.set_selection_filter("edge")
        assert view.pick_at(*projected_edge)
        edge_selection = view.selection()
        assert edge_selection is not None and edge_selection.kind == "edge"
        assert edge_selection.topology_ids == (edge.topology_id,)

        vertex = snapshot.vertices[0]
        projected_vertex = view.project_world_point(_point3(vertex.point))
        assert projected_vertex is not None
        view.set_selection_filter("vertex")
        assert view.pick_at(*projected_vertex)
        vertex_selection = view.selection()
        assert vertex_selection is not None and vertex_selection.kind == "vertex"
        assert vertex_selection.topology_ids == (vertex.topology_id,)
    finally:
        view.dispose()


def test_fillet_candidate_keeps_source_edges_pickable_and_camera_stable(
    services: AppServices,
) -> None:
    loaded = _loaded(services, _BOX)
    view = GLViewport(viewport_port=services.kernel)
    try:
        view.resize(900, 600)
        view.bind_document(loaded)
        view.set_orientation("top")
        view.fit_view()
        view.set_selection_filter("edge")
        view.set_fillet_interaction_active(True)
        source = view.snapshots()[-1]
        edge = source.boundary_edges[0]
        first, second = edge.points[:2]
        projected = view.project_world_point(
            _point3(tuple((start + end) / 2.0 for start, end in zip(first, second, strict=True)))
        )
        assert projected is not None
        assert view.pick_at(*projected, toggle=True)
        selection_before = view.selection()
        camera_before = view.camera_state()

        candidate = replace(source, state_id="candidate:fillet", boundary_edges=())
        view.show_candidate_preview(candidate, preserve_view=True)

        assert view.displayed_snapshot_id() == "candidate:fillet"
        assert view.selection() == selection_before
        assert view.camera_state() == camera_before
        target = view.selection_target_at(*projected, "edge")
        assert target is not None
        assert target.topology_ids == (edge.topology_id,)
        view.clear_candidate_preview()
        assert view.selection() == selection_before
        assert view.camera_state() == camera_before
    finally:
        view.dispose()


def test_ctrl_toggles_multiple_bodies_and_selection_does_not_change_history(
    services: AppServices,
) -> None:
    loaded = new_document(services)
    loaded.bus.execute(
        "feature.cylinder",
        {"radius": 5, "height": 5, "center": [-15, 0, 0], "mode": "new"},
        "test",
    )
    loaded.bus.execute(
        "feature.cylinder",
        {"radius": 5, "height": 5, "center": [15, 0, 0], "mode": "add"},
        "test",
    )
    view = GLViewport(viewport_port=services.kernel)
    try:
        view.resize(900, 600)
        view.bind_document(loaded)
        view.set_orientation("top")
        view.fit_view()
        before_revision = loaded.document.revision
        before_commands = loaded.document.commands
        before_history = loaded.document.commands
        first = view.project_world_point((-15.0, 0.0, 2.5))
        second = view.project_world_point((15.0, 0.0, 2.5))
        assert first is not None and second is not None

        assert view.pick_at(*first)
        assert view.pick_at(*second, toggle=True)
        selection = view.selection()
        assert selection is not None and selection.kind == "body"
        assert len(selection.body_ids) == 2
        assert view.pick_at(*first, toggle=True)
        selection = view.selection()
        assert selection is not None and len(selection.body_ids) == 1

        assert loaded.document.revision == before_revision
        assert loaded.document.commands == before_commands
        assert loaded.document.commands == before_history
    finally:
        view.dispose()


def test_crossing_and_containment_boxes_use_projected_geometry(
    services: AppServices,
) -> None:
    loaded = _loaded(services, _BOX)
    view = GLViewport(viewport_port=services.kernel)
    try:
        view.resize(900, 600)
        view.bind_document(loaded)
        view.set_orientation("top")
        view.fit_view()
        snapshot = view.snapshots()[-1]
        projected = tuple(view.project_world_point(point) for point in snapshot.mesh.vertices)
        screen_points = tuple(point for point in projected if point is not None)
        assert screen_points
        containment = view.targets_in_screen_rect(
            (
                min(point[0] for point in screen_points) - 1,
                min(point[1] for point in screen_points) - 1,
            ),
            (
                max(point[0] for point in screen_points) + 1,
                max(point[1] for point in screen_points) + 1,
            ),
            crossing=False,
        )
        assert len(containment) == 1

        center = (450.0, 300.0)
        crossing = view.targets_in_screen_rect(
            (center[0] - 5, center[1] - 5),
            (center[0] + 5, center[1] + 5),
            crossing=True,
        )
        assert len(crossing) == 1
        assert crossing[0].kind == "body"
    finally:
        view.dispose()


def test_hover_pick_radius_is_six_logical_pixels_and_escape_cancels_box(
    qtbot: QtBot,
    services: AppServices,
) -> None:
    loaded = _loaded(services, _BOX)
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(900, 600)
    view.bind_document(loaded)
    view.set_orientation("top")
    view.fit_view()
    view.set_selection_filter("edge")
    # Top-view +X points down on screen. Use the middle of the outer +X
    # edge, then move outward perpendicular to it. The former first BREP
    # edge collapsed to a corner, where +screen-Y can run along another edge.
    midpoint = (40.0, 0.0, 4.0)
    original_dpr = view.devicePixelRatioF()
    camera_distance = view.camera_distance()
    for zoom in (0.5, 1.0, 2.0):
        view.setCameraPosition(distance=camera_distance * zoom)
        projected = view.project_world_point(midpoint)
        assert projected is not None
        assert view.selection_target_at(projected[0], projected[1] + 5.9, "edge") is not None
        assert view.selection_target_at(projected[0], projected[1] + 6.1, "edge") is None
    assert original_dpr > 0.0

    before_revision = loaded.document.revision
    before_history = loaded.document.commands
    view.show()
    QTest.mousePress(
        view,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        QPoint(100, 100),
    )
    QTest.mouseMove(view, QPoint(300, 300))
    assert view.selection_box_active()
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert not view.selection_box_active()
    assert view.selection() is None
    assert loaded.document.revision == before_revision
    assert loaded.document.commands == before_history
    view.dispose()


def test_pointer_hover_preselects_and_click_commits_only_view_selection(
    qtbot: QtBot,
    services: AppServices,
) -> None:
    loaded = _loaded(services, _BOX)
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.resize(900, 600)
    view.bind_document(loaded)
    view.set_orientation("top")
    view.fit_view()
    view.set_selection_filter("face")
    before_revision = loaded.document.revision
    before_commands = loaded.document.commands

    center = QPoint(view.width() // 2, view.height() // 2)
    hover = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(center),
        QPointF(center),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert QCoreApplication.sendEvent(view, hover)
    preselection = view.preselection()
    assert preselection is not None and preselection.kind == "face"
    assert view.selection() is None

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(center),
        QPointF(center),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(center),
        QPointF(center),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert QCoreApplication.sendEvent(view, press)
    assert QCoreApplication.sendEvent(view, release)
    selection = view.selection()
    assert selection is not None and selection == preselection
    assert view.preselection() is None
    assert loaded.document.revision == before_revision
    assert loaded.document.commands == before_commands
    view.dispose()


def test_history_preview_and_geometry_revision_invalidate_selection(
    services: AppServices,
) -> None:
    loaded = _loaded(services, _BOX, _CYL)
    view = GLViewport(viewport_port=services.kernel)
    try:
        view.resize(900, 600)
        view.bind_document(loaded)
        view.fit_view()
        view.set_selection_filter("face")
        assert view.pick_at(450.0, 300.0)
        selected = view.selection()
        assert selected is not None
        before_revision = loaded.document.revision
        before_history = loaded.document.commands
        assert view.preview_history_feature(0)
        assert view.selection() is None
        assert not view.pick_at(450.0, 300.0)
        assert view.history_preview_ordinal() == 0
        assert view.show_current_model() is None
        assert loaded.document.revision == before_revision
        assert loaded.document.commands == before_history

        assert view.pick_at(450.0, 300.0)
        stale = view.selection()
        assert stale is not None
        loaded.bus.execute("feature.box", {"size_x": 5, "size_y": 5, "size_z": 5}, "test")
        _pump_events()
        assert view.selection() is None
        assert all(
            not services.kernel.is_current_topology(identity) for identity in stale.topology_ids
        )
    finally:
        view.dispose()


def test_viewport_selection_identity_is_shared_with_the_right_panel(
    qtbot: QtBot,
    services: AppServices,
) -> None:
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    loaded = _loaded(services, _BOX)
    window.bind_document(loaded)
    assert window.viewport is not None and window.right_panel is not None
    window.viewport.resize(900, 600)
    window.viewport.fit_view()
    assert window.viewport.pick_at(450.0, 300.0)
    selection = window.viewport.selection()
    assert selection is not None
    assert window.status_selection.text() == "选择 实体 1"
    assert "视口选择：实体" in window.right_panel.view_selection_label.text()
    assert str(selection.body_ids[0].value)[:8] in window.right_panel.view_selection_label.toolTip()
