# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Todo 10: math ray pick + tree<->viewport bidirectional highlight tests.

The pick uses ray x triangle intersection against per-ordinal snapshots
(the plan's pre-authorized fallback decision; deterministic offscreen).
Front-most snapshot along the ray wins, mirroring depth-buffer semantics.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QTreeWidgetItem
from pytestqt.qtbot import QtBot

from mycad.app import AppServices, build_app, new_document
from mycad.core.persistence import LoadedDocument
from mycad.ui.main_window import MainWindow
from mycad.ui.right_panel import ORDINAL_ROLE
from mycad.ui.viewport import GLViewport


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
    ids = [snapshot.feature_id for snapshot in two_feature_view.snapshots()]
    assert ids == ["feature.box:0", "feature.cylinder:1"]
    assert two_feature_view.feature_ordinal("feature.box:0") == 0
    assert two_feature_view.feature_ordinal("feature.cylinder:1") == 1
    assert two_feature_view.feature_ordinal("feature.nope:9") == -1


def test_frontmost_snapshot_wins(two_feature_view: GLViewport) -> None:
    # Straight down the shared axis: the cylinder lives above the box.
    assert two_feature_view.pick_feature_at_ray(*_ray_down(0.0, 0.0)) == "feature.cylinder:1"
    # x=35 lies inside the box (±40) but outside the cylinder (r=10).
    assert two_feature_view.pick_feature_at_ray(*_ray_down(35.0, 0.0)) == "feature.box:0"
    # Far outside both bodies: no intersection at all.
    assert two_feature_view.pick_feature_at_ray(*_ray_down(500.0, 500.0)) is None


def test_highlight_roundtrip(two_feature_view: GLViewport) -> None:
    assert two_feature_view.highlight_ordinal() is None
    two_feature_view.highlight_feature(1)
    assert two_feature_view.highlight_ordinal() == 1
    # Public observable: shaded mesh + edge plot (2) plus one overlay item.
    assert len(two_feature_view.items) == 3
    two_feature_view.highlight_feature(None)
    assert two_feature_view.highlight_ordinal() is None
    assert len(two_feature_view.items) == 2


def test_boolean_cut_snaps_to_post_execution_state(services: AppServices) -> None:
    view = GLViewport(viewport_port=services.kernel)
    try:
        view.bind_document(_loaded(services, _BOX, _CUT))
        _pump_events()
        ids = [snapshot.feature_id for snapshot in view.snapshots()]
        # Destructive commands keep the post-execution semantics: the cut
        # result is one snapshot; no removed-volume feature id exists.
        assert ids == ["feature.box:0", "modify.boolean_cut:1"]
        # Per-snapshot picking walks the whole history: straight down the
        # bore axis only the pre-cut snapshot (solid at the center) is hit.
        assert view.pick_feature_at_ray(*_ray_down(0.0, 0.0)) == "feature.box:0"
        # x=35: both snapshots share the same plane; the strict-front-most
        # rule (first snapshot wins ties) reports the pre-cut view of it.
        assert view.pick_feature_at_ray(*_ray_down(35.0, 0.0)) == "feature.box:0"
    finally:
        view.dispose()


def test_pick_at_without_camera_is_empty(services: AppServices) -> None:
    view = GLViewport(viewport_port=services.kernel)
    try:
        # Never resized: no usable camera geometry -> nothing picked.
        assert view.pick_at(0, 0) == -1
    finally:
        view.dispose()


def test_viewport_pick_signal_selects_tree_leaf(qtbot: QtBot, services: AppServices) -> None:
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(_loaded(services, _BOX, _CYL))
    assert window.viewport is not None
    assert window.right_panel is not None
    tree = window.right_panel.structure_tree
    window.viewport.feature_picked.emit(1)
    item = tree.currentItem()
    assert item is not None
    assert item.data(0, ORDINAL_ROLE) == 1
    # Empty-space pick clears the selection.
    window.viewport.feature_picked.emit(-1)
    assert tree.currentItem() is None


def test_tree_click_highlights_viewport(qtbot: QtBot, services: AppServices) -> None:
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(_loaded(services, _BOX, _CYL))
    assert window.viewport is not None
    assert window.right_panel is not None
    tree = window.right_panel.structure_tree
    target = _find_leaf(tree.invisibleRootItem(), 1)
    assert target is not None
    # 用户点击路径：itemClicked 才发 structure_selection_changed；
    # setCurrentItem 是编程式选中（视口→树方向专用），不发该信号。
    tree.itemClicked.emit(target, 0)
    assert window.viewport.highlight_ordinal() == 1
