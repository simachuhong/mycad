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
from typing import Protocol, cast

import numpy as np
import pytest
from pyqtgraph.opengl import GLLinePlotItem, GLTextItem
from pyqtgraph.opengl.shaders import ShaderProgram
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad import app as mycad_app
from mycad.app import AppServices, build_app
from mycad.core.persistence import LoadedDocument
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.ui.main_window import MainWindow
from mycad.ui.viewport import (
    EDGE_COLOR,
    HIGHLIGHT_COLOR,
    SHADED_COLOR,
    GLViewport,
    ProjectionMode,
    ViewOrientation,
    build_workbench_shader,
    camera_basis,
    orientation_angles,
    unique_edges,
)


def test_workbench_shader_does_not_share_compiled_state_between_contexts() -> None:
    first = build_workbench_shader()
    second = build_workbench_shader()
    assert first is not second
    assert all(a is not b for a, b in zip(first.shaders, second.shaders, strict=True))


def test_preview_material_is_distinct_and_cancel_restores_it(
    viewport: GLViewport,
    loaded: LoadedDocument,
    qapp: object,
) -> None:
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 10}, "test")
    viewport.bind_document(loaded)
    original = cast(_MeshItemProbe, viewport.items[0])
    before = original.opts["color"]
    viewport.show_candidate_preview(viewport.snapshots()[-1], preserve_view=True)
    assert original.opts["color"] != before
    viewport.clear_candidate_preview()
    assert original.opts["color"] == before


def test_sketch_overlay_uses_layer_color(
    viewport: GLViewport,
    loaded: LoadedDocument,
) -> None:
    layer = SketchLayer("OUTLINE", color_rgb=(210, 40, 55))
    sketch = Sketch(
        "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a",
        WorkPlaneFrame.xy(),
        (
            LineEntity(
                "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b",
                (0.0, 0.0),
                (10.0, 0.0),
                layer_name="OUTLINE",
            ),
        ),
        layers=SketchLayerTable().add(layer),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(), "test")
    viewport.bind_document(loaded)

    line_items = [item for item in viewport.items if isinstance(item, GLLinePlotItem)]
    assert len(line_items) == 1
    item = cast(_LineItemProbe, line_items[0])
    assert item.color == pytest.approx((210 / 255, 40 / 255, 55 / 255, 1.0))


def test_sketch_dimension_label_appears_in_viewport_overlay(
    viewport: GLViewport,
    loaded: LoadedDocument,
) -> None:
    entity_id = "1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b"
    sketch = Sketch(
        "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a",
        WorkPlaneFrame.xy(),
        (LineEntity(entity_id, (0.0, 0.0), (10.0, 0.0)),),
        constraints=(
            SketchConstraint(
                "2c2c2c2c-2c2c-4c2c-8c2c-2c2c2c2c2c2c",
                "length",
                (SketchGeometryReference(entity_id, "geometry"),),
                value=10.0,
                unit="mm",
                driving=False,
                precision=1,
            ),
        ),
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "test")
    viewport.bind_document(loaded)

    labels = [item for item in viewport.items if isinstance(item, GLTextItem)]

    assert viewport.sketch_dimension_label_count() == 1
    assert len(labels) == 1
    assert labels[0].text == "10.0 mm"


if sys.platform == "win32":
    # Plan ladder, Windows leg: native GL for the GL tests. conftest only
    # ``setdefault``s the platform, so this module-level override survives.
    os.environ["QT_QPA_PLATFORM"] = "native"


class _MeshItemProbe(Protocol):
    opts: dict[str, object]


class _LineItemProbe(Protocol):
    color: tuple[float, float, float, float]
    pos: np.ndarray


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


@pytest.mark.parametrize(
    ("orientation", "expected"),
    (
        ("front", (0.0, 270.0)),
        ("back", (0.0, 90.0)),
        ("left", (0.0, 180.0)),
        ("right", (0.0, 0.0)),
        ("top", (90.0, 0.0)),
        ("bottom", (-90.0, 0.0)),
        ("isometric", (35.264389682754654, 45.0)),
    ),
)
def test_standard_orientation_angles(
    orientation: ViewOrientation,
    expected: tuple[float, float],
) -> None:
    assert orientation_angles(orientation) == pytest.approx(expected)


def test_orientation_and_projection_controls_preserve_view_scale(
    flange_viewport: GLViewport,
) -> None:
    view = flange_viewport
    before = view.camera_state()
    view.set_orientation("top")
    after_orientation = view.camera_state()
    assert after_orientation[0] == pytest.approx(before[0])
    assert after_orientation[1] == pytest.approx(before[1])
    assert view.opts["elevation"] == 90.0
    assert view.opts["azimuth"] == 0.0

    view.set_projection_mode("orthographic")
    orthographic = view.projectionMatrix()
    assert orthographic.row(3).w() == pytest.approx(1.0)
    assert view.projection_mode() == "orthographic"
    view.set_projection_mode("perspective")
    perspective = view.projectionMatrix()
    assert perspective.row(3).w() == pytest.approx(0.0)
    assert view.projection_mode() == "perspective"
    after_projection = view.camera_state()
    assert after_projection[0] == pytest.approx(before[0])
    assert after_projection[1] == pytest.approx(before[1])


@pytest.mark.parametrize("projection", ("orthographic", "perspective"))
@pytest.mark.parametrize(
    "orientation",
    ("front", "back", "left", "right", "top", "bottom", "isometric"),
)
def test_camera_rays_follow_gl_camera_in_both_projections(
    flange_viewport: GLViewport,
    projection: ProjectionMode,
    orientation: ViewOrientation,
) -> None:
    view = flange_viewport
    view.resize(900, 600)
    view.fit_view()
    view.set_orientation(orientation)
    view.set_projection_mode(projection)
    center_ray = view.camera_ray(450.0, 300.0)
    offset_ray = view.camera_ray(600.0, 300.0)
    assert center_ray is not None
    assert offset_ray is not None
    expected_forward = camera_basis(float(view.opts["elevation"]), float(view.opts["azimuth"]))[3]
    assert center_ray[1] == pytest.approx(expected_forward)
    assert sum(component**2 for component in center_ray[1]) == pytest.approx(1.0)
    if projection == "orthographic":
        assert offset_ray[1] == pytest.approx(center_ray[1])
        assert offset_ray[0] != pytest.approx(center_ray[0])
    else:
        assert offset_ray[1] != pytest.approx(center_ray[1])


def test_background_reaches_gl_as_opaque_light_color(viewport: GLViewport) -> None:
    # Assert the actual Qt -> GL conversion, not merely the source constant.
    assert viewport.opts["bgcolor"] == pytest.approx((239 / 255, 243 / 255, 247 / 255, 1.0))


def test_complete_cut_clears_scene_selection_and_roundtrips(
    viewport: GLViewport, loaded: LoadedDocument
) -> None:
    viewport.bind_document(loaded)
    picked: list[bool] = []
    viewport.current_entity_picked.connect(picked.append)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10}, "test")
    _pump_events()
    viewport.preview_history_feature(0)
    assert len(viewport.items) == 2
    loaded.bus.execute(
        "feature.box", {"size_x": 20, "size_y": 20, "size_z": 20, "mode": "cut"}, "test"
    )
    _pump_events()
    assert viewport.snapshot_count() == 2
    assert not viewport.items
    assert not viewport.mesh_visible()
    assert viewport.history_preview_ordinal() is None
    assert not picked
    assert not viewport.pick_current_entity_at_ray((0.0, 0.0, 50.0), (0.0, 0.0, -1.0))
    # An explicit tree action can inspect the old state, but it is labeled
    # as history preview and replaces the empty current scene. Returning to
    # the current model restores the empty result.
    assert viewport.preview_history_feature(0)
    assert viewport.history_preview_ordinal() == 0
    assert len(viewport.items) == 2
    viewport.show_current_model()
    assert not viewport.items
    assert viewport.history_preview_ordinal() is None
    loaded.bus.undo()
    _pump_events()
    assert viewport.mesh_visible()
    loaded.bus.redo()
    _pump_events()
    assert not viewport.items


def test_empty_document_rebind_removes_previous_history_preview(
    viewport: GLViewport, loaded: LoadedDocument, services: AppServices
) -> None:
    viewport.bind_document(loaded)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10}, "test")
    _pump_events()
    viewport.preview_history_feature(0)
    assert len(viewport.items) == 2
    assert viewport.history_preview_ordinal() == 0
    viewport.bind_document(mycad_app.new_document(services))
    assert not viewport.items
    assert viewport.history_preview_ordinal() is None


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


def test_workbench_lighting_and_gl_color_contract(
    viewport: GLViewport, loaded: LoadedDocument
) -> None:
    viewport.resize(320, 240)
    viewport.bind_document(loaded)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 10}, "test")
    _pump_events()
    mesh_item = cast(_MeshItemProbe, viewport.items[0])
    edge_item = cast(_LineItemProbe, viewport.items[1])
    assert mesh_item.opts["color"] == SHADED_COLOR
    assert edge_item.color == EDGE_COLOR
    assert SHADED_COLOR[3] == 1.0
    assert EDGE_COLOR[3] == 1.0
    assert HIGHLIGHT_COLOR == (1.0, 0.62, 0.10, 0.45)

    shader_value = mesh_item.opts["shader"]
    assert isinstance(shader_value, ShaderProgram)
    shader = shader_value
    assert shader.uniformData["key_light"] == pytest.approx((0.35, -0.25, 0.90))
    assert shader.uniformData["key_light"][2] > 0.0
    assert shader.uniformData["illumination"] == pytest.approx((0.45, 0.55))
    vertex_source = next(
        shader_part.code for shader_part in shader.shaders if "gl_Position" in shader_part.code
    )
    vertex = "".join(vertex_source.split())
    assert "normal=normalize(gl_Normal);" in vertex
    fragment_source = next(
        shader_part.code for shader_part in shader.shaders if "gl_FragColor" in shader_part.code
    )
    fragment = "".join(fragment_source.split())
    assert "normalize(vec3(key_light[0],key_light[1],key_light[2]))" in fragment
    assert "max(dot(normalize(normal),light_direction),0.0)" in fragment


def test_coalesced_rebuild_batch(flange_viewport: GLViewport, loaded: LoadedDocument) -> None:
    before = flange_viewport.rebuild_count()
    events = loaded.document.events
    # Two signals in one event-loop turn (post_command + geometry_rebuilt —
    # the bus union's two families) must collapse into exactly one rebuild.
    events.emit("post_command", {"command_id": "feature.box", "ordinal": 1})
    events.emit("geometry_rebuilt", {})
    _pump_events()
    assert flange_viewport.rebuild_count() == before + 1


def test_refresh_waits_until_serialized_execution_finishes(
    flange_viewport: GLViewport, loaded: LoadedDocument
) -> None:
    before = flange_viewport.rebuild_count()
    flange_viewport.set_execution_busy(True)
    loaded.document.events.emit("geometry_rebuilt", {})
    _pump_events()
    assert flange_viewport.rebuild_count() == before

    flange_viewport.set_execution_busy(False)
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
    scene_items = tuple(flange_viewport.items)
    assert len(scene_items) == 2
    rebuilds = flange_viewport.rebuild_count()

    assert flange_viewport.is_shaded() is True
    flange_viewport.set_shaded(False)
    assert flange_viewport.is_shaded() is False
    assert flange_viewport.mesh_visible() is False
    assert tuple(flange_viewport.items) == scene_items
    assert flange_viewport.rebuild_count() == rebuilds
    flange_viewport.set_shaded(True)
    assert flange_viewport.mesh_visible() is True
    assert tuple(flange_viewport.items) == scene_items
    assert flange_viewport.rebuild_count() == rebuilds


def test_render_modes_separate_brep_boundaries_from_mesh_diagnostics(
    flange_viewport: GLViewport,
) -> None:
    view = flange_viewport
    assert view.render_mode() == "shaded-edges"
    assert view.boundary_lines_visible()
    assert view.mesh_visible()
    assert not view.mesh_diagnostic_visible()
    boundary_item = cast(_LineItemProbe, tuple(view.items)[1])
    boundary_points = view.snapshots()[-1].boundary_edges
    assert boundary_item.pos.shape[0] == sum(2 * (len(edge.points) - 1) for edge in boundary_points)

    view.set_render_mode("shaded")
    assert view.mesh_visible()
    assert not view.boundary_lines_visible()
    assert not view.mesh_diagnostic_visible()

    view.set_render_mode("engineering-wireframe")
    assert not view.mesh_visible()
    assert view.boundary_lines_visible()
    assert not view.mesh_diagnostic_visible()

    view.set_render_mode("mesh-diagnostic")
    assert view.mesh_diagnostic_visible()
    assert view.mesh_visible()
    assert not view.boundary_lines_visible()
    diagnostic_item = cast(_LineItemProbe, tuple(view.items)[-1])
    assert diagnostic_item.pos.shape[0] == 2 * len(
        unique_edges(view.snapshots()[-1].mesh.triangle_indices)
    )

    view.set_render_mode("shaded-edges")
    assert view.mesh_visible()
    assert view.boundary_lines_visible()
    assert not view.mesh_diagnostic_visible()


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
    window.render_mode_actions["engineering-wireframe"].trigger()
    assert window.viewport.is_shaded() is False
    window.act_shaded_wireframe.trigger()
    assert window.viewport.is_shaded() is True
    # request_rebuild routes through the viewport refresh hook.
    loaded = mycad_app.new_document(services)
    window.bind_document(loaded)
    # Exercise the race where a core update queued a coalesced refresh just
    # before the explicit worker rebuild starts.
    loaded.document.events.emit("geometry_rebuilt", {})
    skips = window.viewport.rebuild_count()
    unit = window.execution_unit
    assert unit is not None
    window.request_rebuild()
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert window.viewport.rebuild_count() == skips + 1


def test_direct_refresh_defers_kernel_read_while_execution_is_busy(
    flange_viewport: GLViewport,
) -> None:
    before = flange_viewport.rebuild_count()
    flange_viewport.set_execution_busy(True)
    flange_viewport.refresh()
    assert flange_viewport.rebuild_count() == before
    flange_viewport.set_execution_busy(False)
    _pump_events()
    assert flange_viewport.rebuild_count() == before + 1


def test_xy_grid_uses_points_and_hides_without_scene_changes(viewport: GLViewport) -> None:
    original = tuple(viewport.items)
    viewport.set_xy_grid_visible(True)
    added = [item for item in viewport.items if item not in original]
    assert len(added) == 1
    assert type(added[0]).__name__ == "GLScatterPlotItem"
    viewport.set_xy_grid_visible(False)
    assert tuple(viewport.items) == original
