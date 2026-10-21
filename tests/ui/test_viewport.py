# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Todo 9: offscreen tests for the pyqtgraph.opengl viewport.

The scene-construction surface (items, opts, camera) works without a GL
context — paint failures under offscreen are isolated inside
``GLViewWidget.paintGL`` and unreachable here because nothing is ever
``show()``-n. That is the point: every assertion below is about the scene
graph, not the framebuffer, so the same items run green on Linux (offscreen
or the todo-1 apt ladder) and Windows (native override in the module header
below; conftest uses ``setdefault`` so a per-module override survives).
"""

from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad import app as mycad_app
from mycad.app import AppServices, build_app
from mycad.core.persistence import LoadedDocument
from mycad.ui.main_window import MainWindow
from mycad.ui.viewport import GLViewport, unique_edges

if sys.platform == "win32":
    # Plan ladder, Windows leg: native GL for the GL tests. conftest only
    # ``setdefault``s the platform, so this module-level override survives.
    os.environ["QT_QPA_PLATFORM"] = "native"

#: The F3 flange: OD80 x 8, bore 20, 4 x d6 on PCD 50 — three bus commands.
FLANGE_COMMANDS: tuple[tuple[str, dict[str, object]], ...] = (
    ("feature.cylinder", {"radius": 40.0, "height": 8.0, "mode": "new"}),
    (
        "feature.hole",
        {
            "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
            "position": {"kind": "center"},
            "diameter": 20.0,
            "depth": {"kind": "through_all"},
        },
    ),
    (
        "feature.hole_pattern",
        {
            "base_hole": {
                "target_face": {"surface": "plane", "axis": "+Z", "rank": 0},
                "position": {"kind": "center"},
                "diameter": 6.0,
                "depth": {"kind": "through_all"},
            },
            "pattern": {"kind": "polar", "radius": 25.0, "count": 4, "start_angle_deg": 0},
        },
    ),
)


@pytest.fixture()
def services() -> AppServices:
    return build_app(discoverers=[])


@pytest.fixture()
def viewport(services: AppServices, qapp: object) -> GLViewport:
    return GLViewport(viewport_port=services.kernel)


@pytest.fixture()
def loaded(services: AppServices, qapp: object) -> LoadedDocument:
    return mycad_app.new_document(services)


@pytest.fixture()
def flange_viewport(viewport: GLViewport, loaded: LoadedDocument) -> GLViewport:
    viewport.bind_document(loaded)
    for spec_id, params in FLANGE_COMMANDS:
        loaded.bus.execute(spec_id, params, "test")
    return viewport


def _pump_events() -> None:
    """Flush one QTimer.singleShot(0) coalescing turn."""
    app = QApplication.instance()
    assert app is not None
    app.processEvents()


def test_unique_edges_dedup() -> None:
    triangles = ((0, 1, 2), (1, 3, 2))
    # Two triangles sharing edge (1, 2): 3+3 index pairs minus the duplicate.
    assert unique_edges(triangles) == ((0, 1), (0, 2), (1, 2), (1, 3), (2, 3))
    # Direction-independent: reversed triangles dedup to the same edges.
    assert unique_edges(triangles) == unique_edges(tuple(reversed(triangles)))


def test_empty_document_zero_items(viewport: GLViewport, loaded: LoadedDocument) -> None:
    viewport.bind_document(loaded)
    assert not viewport.items
    assert viewport.snapshot_count() == 0
    assert viewport.mesh_visible() is False


def test_flange_renders_final_snapshot(flange_viewport: GLViewport, loaded: LoadedDocument) -> None:
    _pump_events()
    assert flange_viewport.snapshot_count() == len(FLANGE_COMMANDS)
    # Exactly the final snapshot on screen: one shaded mesh + one edge plot.
    assert len(flange_viewport.items) == 2
    assert flange_viewport.mesh_visible() is True


def test_coalesced_rebuild_batch(flange_viewport: GLViewport, loaded: LoadedDocument) -> None:
    before = flange_viewport.rebuild_count()
    events = loaded.document.events
    # Two signals in one event-loop turn (post_command + geometry_rebuilt —
    # the bus union's two families) must collapse into exactly one rebuild.
    events.emit("post_command", {"command_id": "feature.box", "ordinal": 1})
    events.emit("geometry_rebuilt", {})
    _pump_events()
    assert flange_viewport.rebuild_count() == before + 1


def test_fit_view_moves_camera(flange_viewport: GLViewport) -> None:
    # The first scene already ran fit_view() in refresh(); a second call is
    # idempotent, and after a manual camera move it restores the framing.
    first_distance, first_center = flange_viewport.camera_state()
    flange_viewport.fit_view()
    dist2, center2 = flange_viewport.camera_state()
    assert dist2 == pytest.approx(first_distance)
    assert center2 == pytest.approx(first_center)
    flange_viewport.setCameraPosition(distance=first_distance * 2.0)
    flange_viewport.fit_view()
    dist3, center3 = flange_viewport.camera_state()
    assert dist3 == pytest.approx(first_distance)
    # Kernel tessellation centres the part at the origin (bbox z [-4, 4]).
    assert center3 == pytest.approx((0.0, 0.0, 0.0), abs=1e-3)


def test_wireframe_toggle(flange_viewport: GLViewport) -> None:
    assert flange_viewport.is_shaded() is True
    flange_viewport.set_shaded(False)
    assert flange_viewport.is_shaded() is False
    assert flange_viewport.mesh_visible() is False
    flange_viewport.set_shaded(True)
    assert flange_viewport.mesh_visible() is True


def test_undo_drops_snapshot(flange_viewport: GLViewport, loaded: LoadedDocument) -> None:
    assert flange_viewport.snapshot_count() == len(FLANGE_COMMANDS)
    loaded.bus.undo()
    _pump_events()
    assert flange_viewport.snapshot_count() == len(FLANGE_COMMANDS) - 1


def test_window_hosts_viewport(services: AppServices, qapp: object, qtbot: QtBot) -> None:
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    assert window.viewport is not None
    assert window.centralWidget() is window.viewport
    assert window.viewport.objectName() == "viewportHost"
    assert window.act_shaded_wireframe.isEnabled()
    assert window.act_fit_view.isEnabled()
    window.act_shaded_wireframe.setChecked(False)
    assert window.viewport.is_shaded() is False
    window.act_shaded_wireframe.setChecked(True)
    assert window.viewport.is_shaded() is True
    # request_rebuild routes through the viewport refresh hook.
    skips = window.viewport.rebuild_count()
    window.request_rebuild()
    assert window.viewport.rebuild_count() == skips + 1
