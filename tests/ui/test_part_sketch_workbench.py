# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Independent part sketching uses a disposable candidate before confirmation."""

from collections.abc import Mapping
from dataclasses import replace
from math import dist, pi
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.persistence import document_payload, save_document
from mycad.core.replay_proposal import ReplayAppend, ReplayChangeSet
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PointEntity,
    RectangleEntity,
    Sketch,
    SketchSupportFace,
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import (
    SketchBranchChange,
    SketchConstraint,
    SketchConstraintSolveResult,
    SketchGeometryReference,
)
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.ui.main_window import MainWindow
from mycad.ui.part_sketch_workbench import PartSketchWorkbench
from mycad.ui.sketch_editor import SketchEditorDialog
from mycad.ui.viewport import GLViewport


def test_select_part_sketch_region_then_preview_and_confirm(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("circle")
    task.place_uv((0, 0))
    task.place_uv((10, 0))
    outer = task.session.sketch.entities[0]
    task.select_tool("circle")
    task.place_uv((0, 0))
    task.place_uv((3, 0))
    task.select_tool("circle")
    task.place_uv((30, 0))
    task.place_uv((34, 0))
    view.fit_world_points(((-12, -12, 0), (35, 12, 0)))
    task.region_button.click()
    center = view.project_world_point((0, 0, 0))
    ring = view.project_world_point((5, 0, 0))
    assert center is not None and ring is not None
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(center[0]), round(center[1]))
    )
    assert task.selected_region_ids is None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(ring[0]), round(ring[1])))
    assert task.selected_region_ids == (outer.entity_id,)
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert task.selected_region_ids == (outer.entity_id,)


def test_part_sketch_point_tool_saves_exact_coordinates_and_undoes(
    qtbot: QtBot, tmp_path: Path
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.point_button.click()
    task.place_uv((2.5, -3.75))
    point = task.session.sketch.entities[0]
    assert isinstance(point, PointEntity) and point.position_mm == (2.5, -3.75)
    task.undo()
    assert not task.session.sketch.entities
    task.redo()
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    path = tmp_path / "point.my3d"
    save_document(loaded.document, path)
    reopened_services = app.fork_app_services(services)
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == (point,)


def test_part_sketch_line_snaps_to_created_point(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.point_button.click()
    task.place_uv((3, 4))
    point = task.session.sketch.entities[0]
    assert isinstance(point, PointEntity)
    view.fit_world_points(((-5, -5, 0), (15, 15, 0)))
    task.line_button.click()
    start = view.project_world_point((3, 4, 0))
    end = view.project_world_point((12, 4, 0))
    assert start is not None and end is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(start[0]), round(start[1])))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(end[0]), round(end[1])))
    line = task.session.sketch.entities[1]
    assert isinstance(line, LineEntity)
    assert line.start_mm == point.position_mm
    assert any(
        constraint.kind == "coincident"
        and any(reference.entity_id == point.entity_id for reference in constraint.references)
        for constraint in task.session.sketch.constraints
    )
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()


def test_existing_part_sketch_point_move_replays_and_can_be_undone(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    point = PointEntity("a1" * 16, (2, 3))
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (point,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    view.fit_world_points(((-10, -10, 0), (15, 15, 0)))
    start = view.project_world_point((2, 3, 0))
    end = view.project_world_point((8, 9, 0))
    assert start is not None and end is not None
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(round(start[0]), round(start[1])))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(round(end[0]), round(end[1])))
    assert cast("PointEntity", task.session.sketch.entities[0]).position_mm == pytest.approx(
        (8, 9), abs=0.2
    )
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert loaded.document.commands[-1].id == "sketch.revise"
    assert loaded.document.commands[-1].version == 2
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == (point,)


def test_point_distance_constraint_is_replayed_with_the_sketch(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.point_button.click()
    task.place_uv((0, 0))
    task.place_uv((3, 4))
    sketch = task.session.sketch
    first, second = sketch.entities
    constraint = SketchConstraint(
        "a1" * 16,
        "distance",
        (
            SketchGeometryReference(first.entity_id, "vertex", 0),
            SketchGeometryReference(second.entity_id, "vertex", 0),
        ),
        10,
        "mm",
    )
    solved = services.kernel.preview_sketch_constraint(sketch, constraint)
    assert solved.status == "success", solved.message
    task.accept_constraint(sketch, constraint, solved)
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert services.kernel.sketches[0].constraints[0].value == pytest.approx(10)


def test_part_sketch_spline_requires_four_controls_and_round_trips(
    qtbot: QtBot, tmp_path: Path
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.spline_button.click()
    controls = ((0, 0), (3, 4), (7, 4), (10, 0))
    for point in controls[:3]:
        task.place_uv(point)
    QTest.keyClick(view, Qt.Key.Key_Return)
    assert not task.session.sketch.entities
    assert "四个" in task.status_label.text()
    task.place_uv(controls[3])
    expected_preview = SplineEntity(task.session.sketch.sketch_id, controls).sampled_points()
    assert task.preview_curve == tuple((x, y, 0) for x, y in expected_preview)
    QTest.keyClick(view, Qt.Key.Key_Return)
    spline = task.session.sketch.entities[0]
    assert isinstance(spline, SplineEntity) and spline.control_points_mm == controls
    task.undo()
    assert not task.session.sketch.entities
    task.redo()
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    path = tmp_path / "spline.my3d"
    save_document(loaded.document, path)
    reopened_services = app.fork_app_services(services)
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == (spline,)


def test_spline_and_line_form_an_extrudable_part_sketch(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.spline_button.click()
    for point in ((0, 0), (0, 10), (10, 10), (10, 0)):
        task.place_uv(point)
    task.finish_spline()
    task.line_button.click()
    task.place_uv((10, 0))
    task.place_uv((0, 0))
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    sketch_id = services.kernel.sketches[0].sketch_id
    loaded.bus.execute(
        "feature.extrude", {"profile": {"type": "sketch", "sketch_id": sketch_id}, "distance": 4}
    )
    assert services.kernel.mass_properties().volume > 0


def test_spline_cancel_preserves_draft_and_right_click_finishes(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.spline_button.click()
    for point in ((0, 0), (2, 2), (4, 2)):
        task.place_uv(point)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert not task.session.sketch.entities and not task.pending_point_count
    assert not task.preview_curve
    task.spline_button.click()
    for point in ((0, 0), (2, 2), (4, 2), (6, 0)):
        task.place_uv(point)
    QTest.mouseClick(view, Qt.MouseButton.RightButton)
    assert isinstance(task.session.sketch.entities[0], SplineEntity)


def test_selected_spline_shows_and_drags_control_points(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.spline_button.click()
    for point in ((0, 0), (2, 6), (8, 6), (10, 0)):
        task.place_uv(point)
    task.finish_spline()
    spline = cast("SplineEntity", task.session.sketch.entities[0])
    task.select_tool("select")
    view.fit_world_points(((-3, -3, 0), (13, 12, 0)))
    curve = view.project_world_point((*spline.point_at(0.5), 0))
    assert curve is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(curve[0]), round(curve[1])))
    assert task.selected_entity_id == spline.entity_id
    assert len(view.draft_sketch_control_points()) == 4
    start = view.project_world_point((2, 6, 0))
    end = view.project_world_point((2, 9, 0))
    assert start is not None and end is not None
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(round(start[0]), round(start[1])))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(round(end[0]), round(end[1])))
    updated = cast("SplineEntity", task.session.sketch.entities[0])
    assert updated.control_points_mm[1] == pytest.approx((2, 9), abs=0.2)
    task.undo()
    assert task.session.sketch.entities[0] == spline


def test_part_sketch_trim_click_is_local_undoable_and_persistent(
    qtbot: QtBot, tmp_path: Path
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    for first, second in (((0, 0), (10, 0)), ((5, -5), (5, 5))):
        task.line_button.click()
        task.place_uv(first)
        task.place_uv(second)
    original = task.session.sketch.entities
    view.fit_world_points(((-2, -7, 0), (12, 7, 0)))
    task.trim_button.click()
    point = view.project_world_point((8, 0, 0))
    assert point is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(point[0]), round(point[1])))
    changed = task.session.sketch.entities[0]
    assert isinstance(changed, LineEntity)
    assert changed.end_mm == pytest.approx((5, 0))
    task.undo()
    assert task.session.sketch.entities == original
    task.redo()
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    path = tmp_path / "trim.my3d"
    save_document(loaded.document, path)
    reopened_services = app.fork_app_services(services)
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities == task.session.sketch.entities


def test_trim_preview_and_commit_share_fragment_identity(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    for first, second in (((-10, 0), (10, 0)), ((-5, -5), (-5, 5)), ((5, -5), (5, 5))):
        task.line_button.click()
        task.place_uv(first)
        task.place_uv(second)
    view.fit_world_points(((-12, -7, 0), (12, 7, 0)))
    task.trim_button.click()
    screen = view.project_world_point((0, 0, 0))
    assert screen is not None
    position = QPoint(round(screen[0]), round(screen[1]))
    QTest.mouseMove(view, QPoint(position.x() + 25, position.y() + 25))
    QTest.mouseMove(view, position)
    preview = task.displayed_sketch
    assert len(preview.entities) == 4
    assert len(task.session.sketch.entities) == 3
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=position)
    assert task.session.sketch == preview


def test_trim_rejects_constrained_target_without_losing_draft(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    for first, second in (((0, 0), (10, 0)), ((5, -5), (5, 5))):
        task.line_button.click()
        task.place_uv(first)
        task.place_uv(second)
    sketch = task.session.sketch
    relation = SketchConstraint(
        "a1" * 16,
        "length",
        (SketchGeometryReference(sketch.entities[0].entity_id, "geometry"),),
        10,
        "mm",
    )
    task.session.replace_sketch(replace(sketch, constraints=(relation,)))
    before = task.session.sketch
    view.fit_world_points(((-2, -7, 0), (12, 7, 0)))
    task.trim_button.click()
    point = view.project_world_point((8, 0, 0))
    assert point is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(point[0]), round(point[1])))
    assert task.session.sketch == before
    assert "关联" in task.status_label.text()


def test_trimmed_lines_form_a_consumable_closed_profile(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    for first, second in (
        ((-5, 0), (15, 0)),
        ((0, 0), (0, 5)),
        ((0, 5), (10, 5)),
        ((10, 5), (10, 0)),
    ):
        task.line_button.click()
        task.place_uv(first)
        task.place_uv(second)
    view.fit_world_points(((-7, -3, 0), (17, 8, 0)))
    task.trim_button.click()
    for point in ((-3, 0, 0), (13, 0, 0)):
        screen = view.project_world_point(point)
        assert screen is not None
        QTest.mouseClick(
            view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
        )
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    sketch_id = services.kernel.sketches[0].sketch_id
    loaded.bus.execute(
        "feature.extrude", {"profile": {"type": "sketch", "sketch_id": sketch_id}, "distance": 4}
    )
    assert services.kernel.mass_properties().volume == pytest.approx(200)


def test_part_sketch_extend_to_visible_boundary_is_undoable(qtbot: QtBot, tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    for first, second in (((0, 0), (4, 0)), ((8, -5), (8, 5))):
        task.line_button.click()
        task.place_uv(first)
        task.place_uv(second)
    original = task.session.sketch.entities
    view.fit_world_points(((-2, -7, 0), (10, 7, 0)))
    task.extend_button.click()
    point = view.project_world_point((3.8, 0, 0))
    assert point is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(point[0]), round(point[1])))
    changed = cast("LineEntity", task.session.sketch.entities[0])
    assert changed.end_mm == pytest.approx((8, 0))
    task.undo()
    assert task.session.sketch.entities == original
    task.redo()
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert services.kernel.sketches[0].entities[0] == changed
    path = tmp_path / "extend.my3d"
    save_document(loaded.document, path)
    reopened_services = app.fork_app_services(services)
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].entities[0] == changed


def test_extended_line_completes_a_consumable_profile(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    for first, second in (
        ((0, 0), (5, 0)),
        ((0, 0), (0, 5)),
        ((0, 5), (10, 5)),
        ((10, 5), (10, 0)),
    ):
        task.line_button.click()
        task.place_uv(first)
        task.place_uv(second)
    view.fit_world_points(((-3, -3, 0), (13, 8, 0)))
    task.extend_button.click()
    screen = view.project_world_point((5, 0, 0))
    assert screen is not None
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
    )
    assert cast("LineEntity", task.session.sketch.entities[0]).end_mm == pytest.approx((10, 0)), (
        task.status_label.text()
    )
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    sketch_id = services.kernel.sketches[0].sketch_id
    loaded.bus.execute(
        "feature.extrude", {"profile": {"type": "sketch", "sketch_id": sketch_id}, "distance": 4}
    )
    assert services.kernel.mass_properties().volume == pytest.approx(200)


@pytest.mark.parametrize("tool", ["trim", "extend", "offset"])
def test_curve_edit_reports_unsupported_spline_without_modifying_it(
    qtbot: QtBot, tool: str
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.spline_button.click()
    for point in ((0, 0), (2, 6), (8, 6), (10, 0)):
        task.place_uv(point)
    task.finish_spline()
    spline = cast("SplineEntity", task.session.sketch.entities[0])
    view.fit_world_points(((-3, -3, 0), (13, 10, 0)))
    task.select_tool(tool)
    screen = view.project_world_point((*spline.point_at(0.5), 0))
    assert screen is not None
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
    )
    assert task.session.sketch.entities == (spline,)
    assert "样条" in task.status_label.text() and "暂不支持" in task.status_label.text()


def test_part_sketch_offset_preview_commit_and_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.line_button.click()
    task.place_uv((0, 0))
    task.place_uv((10, 0))
    view.fit_world_points(((-2, -5, 0), (12, 7, 0)))
    task.offset_button.click()
    task.offset_distance.setValue(2)
    screen = view.project_world_point((5, 0, 0))
    assert screen is not None
    position = QPoint(round(screen[0]), round(screen[1]))
    QTest.mouseMove(view, QPoint(position.x() + 25, position.y() + 25))
    QTest.mouseMove(view, position)
    preview = task.displayed_sketch
    assert len(preview.entities) == 2
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=position)
    assert task.session.sketch == preview
    offset = cast("LineEntity", task.session.sketch.entities[1])
    assert offset.start_mm == pytest.approx((0, 2))
    assert offset.end_mm == pytest.approx((10, 2))
    task.undo()
    assert len(task.session.sketch.entities) == 1
    task.redo()
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    path = tmp_path / "offset.my3d"
    save_document(loaded.document, path)
    reopened = app.fork_app_services(services)
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches[0].entities[1] == offset


def test_offset_distance_change_invalidates_preview_and_zero_is_rejected(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.line_button.click()
    task.place_uv((0, 0))
    task.place_uv((10, 0))
    before = task.session.sketch
    view.fit_world_points(((-2, -5, 0), (12, 7, 0)))
    task.offset_button.click()
    screen = view.project_world_point((5, 0, 0))
    assert screen is not None
    position = QPoint(round(screen[0]), round(screen[1]))
    QTest.mouseMove(view, QPoint(position.x() + 25, position.y() + 25))
    QTest.mouseMove(view, position)
    assert len(task.displayed_sketch.entities) == 2
    task.offset_distance.setValue(0)
    assert task.displayed_sketch == before
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=position)
    assert task.session.sketch == before
    assert "非零" in task.status_label.text()


def test_offset_circle_produces_a_consumable_annular_profile(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.circle_button.click()
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    view.fit_world_points(((-10, -10, 0), (10, 10, 0)))
    task.offset_button.click()
    task.offset_distance.setValue(2)
    screen = view.project_world_point((5, 0, 0))
    assert screen is not None
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
    )
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    sketch_id = services.kernel.sketches[0].sketch_id
    loaded.bus.execute(
        "feature.extrude", {"profile": {"type": "sketch", "sketch_id": sketch_id}, "distance": 4}
    )
    assert services.kernel.mass_properties().volume == pytest.approx(96 * pi)


def test_part_sketch_mirror_copy_preview_undo_and_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.line_button.click()
    task.place_uv((0, 2))
    task.place_uv((10, 2))
    source = task.session.sketch.entities[0]
    view.fit_world_points(((-3, -5, 0), (13, 7, 0)))
    task.mirror_button.click()
    for point in ((5, 2, 0), (0, 0, 0)):
        screen = view.project_world_point(point)
        assert screen is not None
        QTest.mouseClick(
            view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
        )
    end = view.project_world_point((10, 0, 0))
    assert end is not None
    position = QPoint(round(end[0]), round(end[1]))
    QTest.mouseMove(view, position)
    preview = task.displayed_sketch
    assert len(preview.entities) == 2
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=position)
    assert task.session.sketch == preview
    mirrored = cast("LineEntity", task.session.sketch.entities[1])
    assert mirrored.entity_id != source.entity_id
    assert mirrored.start_mm == pytest.approx((0, -2), abs=0.15)
    assert mirrored.end_mm == pytest.approx((10, -2), abs=0.15)
    task.undo()
    assert task.session.sketch.entities == (source,)
    task.redo()
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    path = tmp_path / "mirror.my3d"
    save_document(loaded.document, path)
    reopened = app.fork_app_services(services)
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches[0].entities[1] == mirrored


def test_mirrored_circles_form_consumable_disconnected_regions(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.circle_button.click()
    task.place_uv((5, 0))
    task.place_uv((7, 0))
    view.fit_world_points(((-10, -8, 0), (10, 8, 0)))
    task.mirror_button.click()
    for point in ((7, 0, 0), (0, -5, 0), (0, 5, 0)):
        screen = view.project_world_point(point)
        assert screen is not None
        QTest.mouseClick(
            view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
        )
    assert len(task.session.sketch.entities) == 2
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    sketch_id = services.kernel.sketches[0].sketch_id
    loaded.bus.execute(
        "feature.extrude", {"profile": {"type": "sketch", "sketch_id": sketch_id}, "distance": 4}
    )
    assert services.kernel.mass_properties().volume == pytest.approx(32 * pi)


def test_mirror_without_copy_rejects_related_geometry_and_cancel_clears_state(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.line_button.click()
    task.place_uv((0, 2))
    task.place_uv((10, 2))
    sketch = task.session.sketch
    relation = SketchConstraint(
        "a1" * 16,
        "length",
        (SketchGeometryReference(sketch.entities[0].entity_id, "geometry"),),
        10,
        "mm",
    )
    task.session.replace_sketch(replace(sketch, constraints=(relation,)))
    before = task.session.sketch
    view.fit_world_points(((-3, -5, 0), (13, 7, 0)))
    task.mirror_button.click()
    task.mirror_keep_source.setChecked(False)
    for point in ((5, 2, 0), (0, 0, 0), (10, 0, 0)):
        screen = view.project_world_point(point)
        assert screen is not None
        QTest.mouseClick(
            view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
        )
    assert task.session.sketch == before
    assert "关联" in task.status_label.text()
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert task.session.sketch == before
    assert task.mirror_target_id is None


def test_mirror_axis_accepts_exact_numeric_coordinates(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.line_button.click()
    task.place_uv((0, 2))
    task.place_uv((10, 2))
    view.fit_world_points(((-3, -5, 0), (13, 7, 0)))
    task.mirror_button.click()
    screen = view.project_world_point((5, 2, 0))
    assert screen is not None
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
    )
    task.place_uv((0, 0))
    task.place_uv((10, 0))
    mirrored = cast("LineEntity", task.session.sketch.entities[1])
    assert mirrored.start_mm == (0, -2)
    assert mirrored.end_mm == (10, -2)


def test_mirror_target_expires_when_selected_entity_is_deleted(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.line_button.click()
    task.place_uv((0, 2))
    task.place_uv((10, 2))
    view.fit_world_points(((-3, -5, 0), (13, 7, 0)))
    task.mirror_button.click()
    screen = view.project_world_point((5, 2, 0))
    assert screen is not None
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
    )
    assert task.mirror_target_id is not None
    task.delete_selection()
    assert not task.session.sketch.entities
    assert task.mirror_target_id is None and task.mirror_axis_start is None


def test_hidden_region_boundaries_are_not_displayed_or_selectable(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    visible = CircleEntity("a1" * 16, (0, 0), 10)
    hidden = CircleEntity("b2" * 16, (30, 0), 4, layer_name="隐藏")
    layers = SketchLayerTable((SketchLayer("0"), SketchLayer("隐藏", visible=False)))
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (visible, hidden), layers=layers)
    loaded.bus.execute(
        "sketch.create", sketch.to_mapping(version=2), confirmed_by="local", version=2
    )
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    view.fit_world_points(((-12, -12, 0), (35, 12, 0)))
    task.region_button.click()
    assert view.draft_sketch_curve_count() == 1
    point = view.project_world_point((30, 0, 0))
    assert point is not None and view.draft_sketch_region_at(*point) is None


def test_region_selection_expires_when_local_sketch_changes(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("circle")
    task.place_uv((0, 0))
    task.place_uv((10, 0))
    view.fit_world_points(((-12, -12, 0), (12, 12, 0)))
    task.region_button.click()
    point = view.project_world_point((5, 0, 0))
    assert point is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(point[0]), round(point[1])))
    assert task.selected_region_ids is not None
    task.undo()
    assert task.selected_region_ids is None
    assert view.draft_sketch_region_at(*point) is None


def test_open_sketch_region_reports_location_and_preserves_draft(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((10, 0))
    draft = task.session.sketch
    task.region_button.click()
    assert task.session.sketch == draft
    assert task.selected_region_ids is None
    assert "开口" in task.status_label.text()
    assert "0" in task.status_label.text()
    assert draft.entities[0].entity_id in task.status_label.text()


def test_self_intersecting_region_reports_relevant_geometry(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    points = ((0, 0), (10, 10), (0, 10), (10, 0), (0, 0))
    lines = tuple(
        LineEntity(f"{index + 1:032x}", first, second)
        for index, (first, second) in enumerate(zip(points, points[1:], strict=False))
    )
    task.session.replace_sketch(replace(task.session.sketch, entities=lines))
    task.region_button.click()
    assert "自相交" in task.status_label.text()
    assert lines[0].entity_id in task.status_label.text()
    assert task.session.sketch.entities == lines


def test_draw_in_part_viewport_preview_and_cancel(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    before = document_payload(loaded.document)
    camera = view.capture_view()
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.show()
    task.lock_plane()
    task.select_tool("line")
    for point in ((-5.0, 0.0, 0.0), (5.0, 0.0, 0.0)):
        screen = view.project_world_point(point)
        assert screen is not None
        QTest.mouseClick(
            view,
            Qt.MouseButton.LeftButton,
            pos=QPoint(round(screen[0]), round(screen[1])),
        )
    assert len(task.session.sketch.entities) == 1
    assert isinstance(task.session.sketch.entities[0], LineEntity)
    assert view.draft_sketch_curve_count() == 1
    task.preview()
    assert task.confirm_button.isEnabled()
    assert document_payload(loaded.document) == before
    task.reject()
    assert document_payload(loaded.document) == before
    assert view.draft_sketch_curve_count() == 0
    assert view.capture_view() == camera


def test_previewed_part_sketch_is_confirmed_once(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((10, 0))
    task.preview()
    task.confirm()
    assert len(loaded.document.commands) == 1
    assert loaded.document.commands[0].id == "sketch.create"
    assert services.kernel.sketches[0].entities == task.session.sketch.entities
    task.confirm()
    assert len(loaded.document.commands) == 1


def test_shape_tools_and_local_undo(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("rectangle")
    task.place_uv((0, 0))
    task.place_uv((10, 5))
    task.select_tool("circle")
    task.place_uv((5, 2))
    task.place_uv((7, 2))
    task.select_tool("arc")
    task.place_uv((0, 0))
    task.place_uv((2, 0))
    task.place_uv((0, 2))
    assert tuple(type(item) for item in task.session.sketch.entities) == (
        RectangleEntity,
        CircleEntity,
        ArcEntity,
    )
    task.undo()
    assert len(task.session.sketch.entities) == 2
    task.redo()
    assert len(task.session.sketch.entities) == 3
    task.preview()
    assert task.confirm_button.isEnabled()
    task.reject()


def test_select_and_delete_draft_curve_in_viewport(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((-5, 0))
    task.place_uv((5, 0))
    line = task.session.sketch.entities[0]
    task.select_tool("select")
    position = view.project_world_point((0, 0, 0))
    assert position is not None
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(position[0]), round(position[1]))
    )
    assert task.selected_entity_id == line.entity_id
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert task.session.sketch.entities == ()
    assert loaded.document.commands == ()
    task.undo()
    assert task.session.sketch.entities == (line,)
    task.reject()


def test_pointer_snaps_origin_but_numeric_point_remains_exact(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    origin = view.project_world_point((0, 0, 0))
    assert origin is not None
    QTest.mouseClick(
        view,
        Qt.MouseButton.LeftButton,
        pos=QPoint(round(origin[0] + 5), round(origin[1])),
    )
    task.u_field.setValue(3.25)
    task.v_field.setValue(0)
    task.numeric_point_button.click()
    line = task.session.sketch.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == (0, 0)
    assert line.end_mm == (3.25, 0)
    task.reject()


def test_source_change_expires_preview_without_dropping_draft(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    task.preview()
    assert task.confirm_button.isEnabled()
    loaded.bus.execute("feature.box", {"size_x": 3, "size_y": 3, "size_z": 3})
    qtbot.waitUntil(lambda: not task.confirm_button.isEnabled())
    assert len(task.session.sketch.entities) == 1
    task.confirm()
    assert [command.id for command in loaded.document.commands] == ["feature.box"]
    task.reject()


def test_grid_snap_is_separate_from_grid_display(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.object_snap.setChecked(False)
    task.grid_snap.setChecked(True)
    assert not task.grid_visible.isChecked()
    task.select_tool("line")
    point = view.project_world_point((2.6, 3.2, 0))
    assert point is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(point[0]), round(point[1])))
    task.u_field.setValue(7.25)
    task.v_field.setValue(3)
    task.numeric_point_button.click()
    line = task.session.sketch.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == (3, 3)
    assert line.end_mm == (7.25, 3)
    task.reject()


def test_drag_line_endpoint_and_undo(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.object_snap.setChecked(False)
    task.select_tool("line")
    task.place_uv((-5, 0))
    task.place_uv((5, 0))
    task.select_tool("select")
    start = view.project_world_point((-5, 0, 0))
    target = view.project_world_point((-5, 2, 0))
    assert start is not None and target is not None
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(round(start[0]), round(start[1])))
    QTest.mouseMove(view, QPoint(round(target[0]), round(target[1])))
    QTest.mouseRelease(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(target[0]), round(target[1]))
    )
    line = task.session.sketch.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm[1] == pytest.approx(2, abs=0.1)
    task.undo()
    original = task.session.sketch.entities[0]
    assert isinstance(original, LineEntity)
    assert original.start_mm == (-5, 0)
    task.reject()


def test_sketch_can_be_bound_to_confirmed_datum_plane(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    datum = {
        "name": "平面 A",
        "construction": {
            "kind": "principal",
            "coordinate_system": {"kind": "world"},
            "plane": "xz",
        },
    }
    candidate = app.create_replay_candidate(services, loaded, session_identity=4)
    candidate.stage(
        ReplayChangeSet((), (ReplayAppend("datum.plane.create", 1, datum, "local"),), False, 6),
        current_session_identity=4,
    )
    assert candidate.preview(current_session_identity=4).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=4), current_session_identity=4
    )
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    index = task.plane_combo.findText("平面 A")
    assert index >= 0
    task.plane_combo.setCurrentIndex(index)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((1, 2))
    task.place_uv((4, 2))
    task.preview()
    assert task.confirm_button.isEnabled()
    task.confirm()
    command = loaded.document.commands[-1]
    assert command.id == "sketch.create" and command.version == 4
    support = command.params["support"]
    assert isinstance(support, Mapping)
    plane = cast("Mapping[str, object]", support)["plane"]
    assert isinstance(plane, Mapping)
    assert plane["source_instance_id"] == loaded.document.commands[0].instance_id


def test_confirmed_draft_constraint_commits_as_separate_audited_command(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("circle")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    sketch = task.session.sketch
    circle = sketch.entities[0]
    constraint = SketchConstraint(
        "a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a",
        "radius",
        (SketchGeometryReference(circle.entity_id, "geometry"),),
        7,
        "mm",
    )
    solved = services.kernel.preview_sketch_constraint(sketch, constraint)
    assert solved.status == "success"
    task.accept_constraint(sketch, constraint, solved)
    assert loaded.document.commands == ()
    assert task.session.sketch.constraints == (constraint,)
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert [command.id for command in loaded.document.commands] == [
        "sketch.create",
        "sketch.constraint.add",
    ]
    assert all(command.confirmed_by == "local" for command in loaded.document.commands)
    circle_result = services.kernel.sketches[0].entities[0]
    assert isinstance(circle_result, CircleEntity)
    assert circle_result.radius_mm == pytest.approx(7)


def test_part_entry_uses_independent_workbench_and_guards_draft(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    assert window.findChild(SketchEditorDialog) is None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((3, 0))
    assert task.has_draft
    window.act_save.trigger()
    assert "请先完成或取消" in window.status_command.text()
    assert loaded.document.commands == ()
    task.reject()
    assert window.part_sketch_task is None
    assert loaded.document.commands == ()


def test_existing_sketch_edit_previews_downstream_before_commit(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), 5)
    sketch = Sketch("d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (circle,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": sketch.sketch_id}, "distance": 4},
        confirmed_by="local",
    )
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    changed = replace(circle, radius_mm=7)
    task.session.replace_sketch(replace(sketch, entities=(changed,)))
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    assert services.kernel.mass_properties().volume == pytest.approx(100 * pi)
    task.confirm()
    assert loaded.document.commands[-1].id == "sketch.revise"
    assert services.kernel.mass_properties().volume == pytest.approx(196 * pi)


def test_sketch_tree_edit_opens_independent_part_workbench(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), 5)
    sketch = Sketch("d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (circle,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    assert window.right_panel is not None
    window.right_panel.select_feature_ordinal(0)
    button = window.right_panel.findChild(QPushButton, "editPartSketch")
    assert button is not None
    button.click()
    task = window.part_sketch_task
    assert task is not None
    assert task.session.sketch.sketch_id == sketch.sketch_id
    assert not task.has_draft
    task.reject()


def test_legacy_selected_planar_face_can_support_new_sketch(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 8})
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    frame = WorkPlaneFrame.from_planar_face((0, 0, 4), (0, 0, 1))
    support = SketchSupportFace((0, 0, 4))
    task = PartSketchWorkbench(
        services, loaded, view, session_identity=4, attached_frame=frame, support_face=support
    )
    qtbot.addWidget(task)
    assert task.plane_combo.currentText() == "所选模型平面（查询）"
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((10, 0))
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert services.kernel.sketches[0].support_face == support
    assert services.kernel.sketches[0].frame.origin_mm == pytest.approx((0, 0, 4))


def test_pointer_infers_horizontal_relationship_and_replays_it(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    for point in ((0.0, 0.0, 0.0), (10.0, 0.05, 0.0)):
        screen = view.project_world_point(point)
        assert screen is not None
        QTest.mouseClick(
            view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
        )
    line = task.session.sketch.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm[1] == line.end_mm[1]
    assert len(task.session.sketch.constraints) == 1
    assert task.session.sketch.constraints[0].kind == "horizontal"
    assert task.session.sketch.constraints[0].source == "inferred"
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert services.kernel.sketches[0].constraints[0].kind == "horizontal"


def test_snapped_draft_endpoint_creates_persistent_coincidence(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    start = view.project_world_point((5, 0, 0))
    end = view.project_world_point((5, 4, 0))
    assert start is not None and end is not None
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(start[0] + 4), round(start[1]))
    )
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(end[0]), round(end[1])))
    relations = task.session.sketch.constraints
    assert any(item.kind == "coincident" and item.source == "inferred" for item in relations)
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert any(item.kind == "coincident" for item in services.kernel.sketches[0].constraints)


def test_global_undo_redo_routes_to_active_part_sketch(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 5})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((5, 1))
    window.request_undo()
    assert task.session.sketch.entities == ()
    assert len(loaded.document.commands) == 1
    window.request_redo()
    assert len(task.session.sketch.entities) == 1
    assert len(loaded.document.commands) == 1
    task.reject()


def test_new_sketch_preserves_constraint_order_when_inference_follows_dimension(
    qtbot: QtBot,
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("circle")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    initial = task.session.sketch
    radius = SketchConstraint(
        "a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a",
        "radius",
        (SketchGeometryReference(initial.entities[0].entity_id, "geometry"),),
        7,
        "mm",
    )
    result = services.kernel.preview_sketch_constraint(initial, radius)
    task.accept_constraint(initial, radius, result)
    task.select_tool("line")
    for point in ((-10.0, 10.0, 0.0), (10.0, 10.0, 0.0)):
        screen = view.project_world_point(point)
        assert screen is not None
        QTest.mouseClick(
            view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
        )
    expected = task.session.sketch.constraints
    assert tuple(item.kind for item in expected) == ("radius", "horizontal")
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert services.kernel.sketches[0].constraints == expected


def test_unfinished_part_sketch_blocks_document_switch_and_window_close(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    qtbot.addWidget(window)
    window.bind_document(app.new_workspace_document(services, kind="part"))
    assert window.document_session is not None
    original = window.document_session.active
    assert original is not None
    other = window.new_session_document("part")
    window.activate_session_document(original.loaded.document.document_id)
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((5, 1))
    window.activate_session_document(other.loaded.document.document_id)
    assert window.document_session.active is original
    assert not window.close()
    assert task.has_draft
    task.reject()
    window.activate_session_document(other.loaded.document.document_id)
    assert window.document_session.active is other


def test_construction_circle_is_excluded_from_extrusion(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("rectangle")
    task.place_uv((0, 0))
    task.place_uv((10, 5))
    task.construction.setChecked(True)
    task.select_tool("circle")
    task.place_uv((5, 2))
    task.place_uv((6, 2))
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    sketch = services.kernel.sketches[0]
    assert sketch.entities[1].construction
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": sketch.sketch_id}, "distance": 5},
    )
    assert services.kernel.mass_properties().volume == pytest.approx(250)


def test_selected_entity_can_toggle_construction_and_undo(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("circle")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    task.select_tool("select")
    screen = view.project_world_point((5, 0, 0))
    assert screen is not None
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
    )
    task.toggle_construction_button.click()
    assert task.session.sketch.entities[0].construction
    task.undo()
    assert not task.session.sketch.entities[0].construction
    task.reject()


def test_constraint_preview_displays_solution_without_mutating_draft(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("circle")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    task.constraint_button.click()
    dialog = task.constraint_dialog
    assert dialog is not None
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("radius"))
    dialog.value_field.setValue(7)
    dialog.preview_button.click()
    assert dialog.apply_button.isEnabled()
    draft = task.session.sketch.entities[0]
    displayed = task.displayed_sketch.entities[0]
    assert isinstance(draft, CircleEntity) and isinstance(displayed, CircleEntity)
    assert draft.radius_mm == pytest.approx(5)
    assert displayed.radius_mm == pytest.approx(7)
    assert loaded.document.commands == ()
    dialog.reject()
    assert task.displayed_sketch == task.session.sketch
    task.reject()


def test_active_sketch_displays_driving_and_reference_dimensions(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), 5)
    reference = SketchGeometryReference(circle.entity_id, "geometry")
    radius = SketchConstraint("a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a", "radius", (reference,), 5, "mm")
    diameter = SketchConstraint(
        "b2b2b2b2b2b24b2b8b2b2b2b2b2b2b2b", "diameter", (reference,), 10, "mm", driving=False
    )
    sketch = Sketch(
        "d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (circle,), (radius, diameter)
    )
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    dimensions = view.draft_sketch_dimensions()
    assert {item.constraint_id for item in dimensions} == {
        radius.constraint_id,
        diameter.constraint_id,
    }
    assert any("R5.00" in item.text and "驱动" in item.text for item in dimensions)
    assert any("⌀10.00" in item.text and "参考" in item.text for item in dimensions)
    assert dimensions[0].position != dimensions[1].position
    task.reject()
    assert not view.draft_sketch_dimensions()


def test_editing_dimensioned_sketch_fits_labels_on_screen_and_restores_view(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), 15)
    reference = SketchGeometryReference(circle.entity_id, "geometry")
    radius = SketchConstraint("a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a", "radius", (reference,), 15, "mm")
    sketch = Sketch("d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (circle,), (radius,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.show()
    qtbot.waitExposed(view)
    before = view.capture_view()
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    position = view.project_world_point(view.draft_sketch_dimensions()[0].position)
    assert position is not None
    assert 0 <= position[0] < view.width() and 0 <= position[1] < view.height()
    task.reject()
    assert view.capture_view() == before


def test_editing_sketch_hides_committed_dimension_labels_until_task_ends(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), 5)
    reference = SketchGeometryReference(circle.entity_id, "geometry")
    radius = SketchConstraint("a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a", "radius", (reference,), 5, "mm")
    sketch = Sketch("d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (circle,), (radius,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    assert view.sketch_dimension_label_count() == 1
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    assert len(view.draft_sketch_dimensions()) == 1
    assert view.sketch_dimension_label_count() == 0
    task.reject()
    assert not view.draft_sketch_dimensions()
    assert view.sketch_dimension_label_count() == 1


def test_double_click_draft_dimension_edits_existing_constraint_on_canvas(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), 5)
    reference = SketchGeometryReference(circle.entity_id, "geometry")
    radius = SketchConstraint("a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a", "radius", (reference,), 5, "mm")
    sketch = Sketch("d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (circle,), (radius,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.show()
    qtbot.waitExposed(view)
    busy = [False]
    task = PartSketchWorkbench(
        services,
        loaded,
        view,
        session_identity=4,
        existing_sketch=sketch,
        can_execute=lambda: not busy[0],
    )
    qtbot.addWidget(task)
    dimension = view.draft_sketch_dimensions()[0]
    position = view.project_world_point(dimension.position)
    assert position is not None
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(position[0]), round(position[1]))
    )
    assert task.selected_dimension_id == radius.constraint_id
    assert view.draft_sketch_dimensions()[0].color_rgb != dimension.color_rgb
    QTest.mouseDClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(position[0]), round(position[1]))
    )
    editor = task.dimension_editor
    assert editor is not None and view.isAncestorOf(editor)
    assert task.has_draft
    assert editor.value() == pytest.approx(5)
    assert len(loaded.document.commands) == 1
    editor.setValue(8)
    task.preview()
    assert not task.confirm_button.isEnabled()
    assert "尺寸" in task.status_label.text()
    QTest.keyClick(editor.lineEdit(), Qt.Key.Key_Escape)
    assert task.dimension_editor is None
    assert task.session.sketch == sketch
    QTest.mouseDClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(position[0]), round(position[1]))
    )
    editor = task.dimension_editor
    assert editor is not None
    editor.setValue(0)
    QTest.keyClick(editor.lineEdit(), Qt.Key.Key_Return)
    assert task.dimension_editor is editor
    assert "失败" in task.status_label.text()
    assert task.session.sketch == sketch
    editor.setValue(7)
    busy[0] = True
    QTest.keyClick(editor.lineEdit(), Qt.Key.Key_Return)
    assert task.dimension_editor is editor
    assert task.session.sketch == sketch
    assert "忙" in task.status_label.text()
    busy[0] = False
    original_preview = services.kernel.preview_sketch_constraint_update

    def conflict_preview(_base: Sketch, _changed: SketchConstraint) -> SketchConstraintSolveResult:
        return SketchConstraintSolveResult(
            "failed", None, None, conflicting_constraint_ids=(radius.constraint_id,), message="冲突"
        )

    monkeypatch.setattr(services.kernel, "preview_sketch_constraint_update", conflict_preview)
    QTest.keyClick(editor.lineEdit(), Qt.Key.Key_Return)
    assert task.dimension_editor is editor
    assert task.session.sketch == sketch
    assert radius.constraint_id[:8] in task.status_label.text()
    assert circle.entity_id[:8] in task.status_label.text()
    assert task.selected_entity_id == circle.entity_id

    def branch_preview(base: Sketch, changed: SketchConstraint) -> SketchConstraintSolveResult:
        result = original_preview(base, changed)
        return replace(
            result,
            branch_changes=(SketchBranchChange("direction", (circle.entity_id,), "方向反转"),),
        )

    monkeypatch.setattr(services.kernel, "preview_sketch_constraint_update", branch_preview)
    QTest.keyClick(editor.lineEdit(), Qt.Key.Key_Return)
    assert task.dimension_editor is None
    assert task.session.sketch == sketch
    dialog = task.constraint_dialog
    assert dialog is not None
    assert dialog.dimension_combo.currentData() == radius.constraint_id
    assert dialog.value_field.value() == pytest.approx(7)
    assert not dialog.apply_button.isEnabled()
    assert not dialog.branch_acknowledgement.isChecked()
    dialog.reject()
    monkeypatch.setattr(services.kernel, "preview_sketch_constraint_update", original_preview)
    QTest.mouseDClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(position[0]), round(position[1]))
    )
    editor = task.dimension_editor
    assert editor is not None
    editor.setValue(7)
    QTest.keyClick(editor.lineEdit(), Qt.Key.Key_Return)
    assert task.dimension_editor is None
    assert any("R7.00" in item.text for item in view.draft_sketch_dimensions())
    assert "自由度" in task.status_label.text()
    assert services.kernel.sketches[0].entities[0] == circle
    assert task.session.sketch.constraints[0].constraint_id == radius.constraint_id
    task.preview()
    assert task.confirm_button.isEnabled()
    task.confirm()
    updated = services.kernel.sketches[0].entities[0]
    assert isinstance(updated, CircleEntity)
    assert updated.radius_mm == pytest.approx(7)


def test_reference_dimension_is_read_only_on_canvas(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), 5)
    reference = SketchGeometryReference(circle.entity_id, "geometry")
    diameter = SketchConstraint(
        "b2b2b2b2b2b24b2b8b2b2b2b2b2b2b2b", "diameter", (reference,), 10, "mm", driving=False
    )
    sketch = Sketch("d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (circle,), (diameter,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    position = view.project_world_point(view.draft_sketch_dimensions()[0].position)
    assert position is not None
    QTest.mouseDClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(position[0]), round(position[1]))
    )
    assert task.dimension_editor is None
    assert "参考尺寸" in task.status_label.text()
    assert task.session.sketch == sketch
    task.reject()


def test_canvas_dimension_editor_expires_when_document_changes(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), 5)
    reference = SketchGeometryReference(circle.entity_id, "geometry")
    radius = SketchConstraint("a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a", "radius", (reference,), 5, "mm")
    sketch = Sketch("d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (circle,), (radius,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    position = view.project_world_point(view.draft_sketch_dimensions()[0].position)
    assert position is not None
    QTest.mouseDClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(position[0]), round(position[1]))
    )
    editor = task.dimension_editor
    assert editor is not None
    editor.setValue(7)
    loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 10, "size_z": 4})
    qtbot.waitUntil(lambda: task.dimension_editor is None)
    assert task.session.sketch == sketch
    assert len(loaded.document.commands) == 2
    assert "模型已改变" in task.status_label.text()
    task.reject()


def test_canvas_relation_can_be_selected_deleted_and_undone(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    line = LineEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), (10, 0))
    reference = SketchGeometryReference(line.entity_id, "geometry")
    relation = SketchConstraint(
        "a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a", "horizontal", (reference,), source="inferred"
    )
    sketch = Sketch("d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (line,), (relation,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    annotation = view.draft_relation_annotations()[0]
    assert annotation.constraint_id == relation.constraint_id
    position = view.project_world_point(annotation.position)
    assert position is not None
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(position[0]), round(position[1]))
    )
    assert task.selected_relation_id == relation.constraint_id
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert not task.session.sketch.constraints
    assert services.kernel.sketches[0].constraints == (relation,)
    task.undo()
    assert task.session.sketch.constraints == (relation,)
    task.redo()
    assert not task.session.sketch.constraints
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert not services.kernel.sketches[0].constraints


def test_overlapping_canvas_relations_cycle_by_stable_identity(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    first = LineEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), (10, 0))
    second = LineEntity("e4e4e4e4e4e44e4e8e4e4e4e4e4e4e4e", (0, 5), (10, 5))
    refs = (
        SketchGeometryReference(first.entity_id, "geometry"),
        SketchGeometryReference(second.entity_id, "geometry"),
    )
    parallel = SketchConstraint("a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a", "parallel", refs)
    equal = SketchConstraint("b2b2b2b2b2b24b2b8b2b2b2b2b2b2b2b", "equal", refs)
    sketch = Sketch(
        "d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (first, second), (parallel, equal)
    )
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    annotation = view.draft_relation_annotations()[0]
    position = view.project_world_point(annotation.position)
    assert position is not None
    click = QPoint(round(position[0]), round(position[1]))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=click)
    first_selected = task.selected_relation_id
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=click)
    assert {first_selected, task.selected_relation_id} == {
        parallel.constraint_id,
        equal.constraint_id,
    }
    task.reject()


def test_overlapping_canvas_dimensions_cycle_by_stable_identity(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), 5)
    reference = SketchGeometryReference(circle.entity_id, "geometry")
    radius = SketchConstraint(
        "a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a", "radius", (reference,), 5, "mm", text_position_mm=(7, 7)
    )
    diameter = SketchConstraint(
        "b2b2b2b2b2b24b2b8b2b2b2b2b2b2b2b",
        "diameter",
        (reference,),
        10,
        "mm",
        driving=False,
        text_position_mm=(7, 7),
    )
    sketch = Sketch(
        "d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (circle,), (radius, diameter)
    )
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    position = view.project_world_point(view.draft_sketch_dimensions()[0].position)
    assert position is not None
    click = QPoint(round(position[0]), round(position[1]))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=click)
    first_selected = task.selected_dimension_id
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=click)
    assert {first_selected, task.selected_dimension_id} == {
        radius.constraint_id,
        diameter.constraint_id,
    }
    task.reject()


def test_overlapping_dimension_and_relation_are_both_selectable(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    line = LineEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), (10, 0))
    reference = SketchGeometryReference(line.entity_id, "geometry")
    relation = SketchConstraint(
        "a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a", "horizontal", (reference,), source="inferred"
    )
    dimension = SketchConstraint(
        "b2b2b2b2b2b24b2b8b2b2b2b2b2b2b2b",
        "length",
        (reference,),
        10,
        "mm",
        text_position_mm=(5, 0),
    )
    sketch = Sketch(
        "d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (line,), (relation, dimension)
    )
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    position = view.project_world_point(view.draft_sketch_dimensions()[0].position)
    assert position is not None
    click = QPoint(round(position[0]), round(position[1]))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=click)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=click)
    assert task.selected_relation_id == relation.constraint_id
    task.reject()


@pytest.mark.parametrize("kind", ["length", "radius", "diameter"])
def test_canvas_dimension_selects_geometry_and_places_annotation(
    qtbot: QtBot, tmp_path: Path, kind: str
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line" if kind == "length" else "circle")
    task.place_uv((-5, 0) if kind == "length" else (0, 0))
    task.place_uv((5, 0))
    entity = task.session.sketch.entities[0]
    view.fit_world_points(((-10, -10, 0), (15, 15, 0)))
    label = {"length": "长度", "radius": "半径", "diameter": "直径"}[kind]
    next(action for action in task.dimension_menu.actions() if action.text() == label).trigger()
    source = view.project_world_point((0, 0, 0) if kind == "length" else (5, 0, 0))
    location = view.project_world_point((12, 12, 0))
    assert source is not None and location is not None
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(source[0]), round(source[1]))
    )
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(location[0]), round(location[1]))
    )
    dialog = task.constraint_dialog
    assert dialog is not None
    assert dialog.first_entity.currentData() == entity.entity_id
    assert dialog.kind_combo.currentData() == kind
    dialog.driving_check.setChecked(False)
    dialog.preview_button.click()
    assert dialog.apply_button.isEnabled(), dialog.status_label.text()
    dialog.apply_button.click()
    dimension = task.session.sketch.constraints[0]
    assert dimension.kind == kind and not dimension.driving
    assert dimension.position_mm == pytest.approx((12, 12), abs=0.2)
    assert any(
        item.constraint_id == dimension.constraint_id for item in view.draft_sketch_dimensions()
    )
    task.undo()
    assert not task.session.sketch.constraints
    task.redo()
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert services.kernel.sketches[0].constraints[0].position_mm == pytest.approx(
        (12, 12), abs=0.2
    )
    path = tmp_path / f"{kind}.my3d"
    save_document(loaded.document, path)
    reopened_services = app.fork_app_services(services)
    app.open_app_document(reopened_services, path)
    reopened = reopened_services.kernel.sketches[0].constraints[0]
    assert reopened.constraint_id == dimension.constraint_id
    assert reopened.position_mm == pytest.approx((12, 12), abs=0.2)


@pytest.mark.parametrize("kind", ["distance", "angle"])
def test_canvas_two_reference_dimension_selects_and_places(qtbot: QtBot, kind: str) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((-5, 0))
    task.place_uv((5, 0))
    task.place_uv((0, -5))
    task.place_uv((0, 5))
    first, second = task.session.sketch.entities
    view.fit_world_points(((-10, -10, 0), (15, 15, 0)))
    label = "点距" if kind == "distance" else "角度"
    next(action for action in task.dimension_menu.actions() if action.text() == label).trigger()
    picks = ((-5, 0, 0), (5, 0, 0)) if kind == "distance" else ((4, 0, 0), (0, 4, 0))
    for point in (*picks, (12, 12, 0)):
        screen = view.project_world_point(point)
        assert screen is not None
        QTest.mouseClick(
            view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
        )
    dialog = task.constraint_dialog
    assert dialog is not None and dialog.kind_combo.currentData() == kind
    assert dialog.first_entity.currentData() == first.entity_id
    assert dialog.second_entity.currentData() == (
        first.entity_id if kind == "distance" else second.entity_id
    )
    dialog.driving_check.setChecked(False)
    dialog.preview_button.click()
    assert dialog.apply_button.isEnabled(), dialog.status_label.text()
    dialog.apply_button.click()
    dimension = task.session.sketch.constraints[0]
    assert dimension.kind == kind and not dimension.driving
    assert dimension.value == pytest.approx(10 if kind == "distance" else 90)
    assert dimension.position_mm == pytest.approx((12, 12), abs=0.2)
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert services.kernel.sketches[0].constraints[0].constraint_id == dimension.constraint_id


def test_canvas_dimension_mode_does_not_discard_unfinished_geometry(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.begin_dimension_placement("length")
    assert "完成当前图元" in task.status_label.text()
    task.place_uv((5, 0))
    assert len(task.session.sketch.entities) == 1
    task.begin_dimension_placement("length")
    assert task.has_draft
    task.preview()
    assert not task.confirm_button.isEnabled()
    assert "标注" in task.status_label.text()
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert len(task.session.sketch.entities) == 1
    task.preview()
    assert task.confirm_button.isEnabled()
    task.reject()


def test_canvas_length_dimension_accepts_rectangle_edge(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("rectangle")
    task.place_uv((-5, -5))
    task.place_uv((5, 5))
    rectangle = task.session.sketch.entities[0]
    view.fit_world_points(((-10, -10, 0), (15, 15, 0)))
    task.begin_dimension_placement("length")
    for point in ((0, 5, 0), (12, 12, 0)):
        screen = view.project_world_point(point)
        assert screen is not None
        QTest.mouseClick(
            view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
        )
    dialog = task.constraint_dialog
    assert dialog is not None
    assert dialog.first_entity.currentData() == rectangle.entity_id
    assert dialog.first_reference.currentData() == "segment"
    assert dialog.first_index.value() == 2
    dialog.driving_check.setChecked(False)
    dialog.preview_button.click()
    assert dialog.apply_button.isEnabled(), dialog.status_label.text()
    dialog.apply_button.click()
    dimension = task.session.sketch.constraints[0]
    assert dimension.value == pytest.approx(10)
    assert dimension.references[0].kind == "segment"
    task.reject()


def test_edit_driving_dimension_refreshes_reference_and_downstream(
    qtbot: QtBot, tmp_path: Path
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), 5)
    ref = SketchGeometryReference(circle.entity_id, "geometry")
    radius = SketchConstraint("a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a", "radius", (ref,), 5, "mm")
    diameter = SketchConstraint(
        "b2b2b2b2b2b24b2b8b2b2b2b2b2b2b2b", "diameter", (ref,), 10, "mm", driving=False
    )
    sketch = Sketch(
        "d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (circle,), (radius, diameter)
    )
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": sketch.sketch_id}, "distance": 4},
    )
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    label = next(
        d for d in view.draft_sketch_dimensions() if d.constraint_id == radius.constraint_id
    )
    position = view.project_world_point(label.position)
    assert position is not None
    QTest.mouseDClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(position[0]), round(position[1]))
    )
    editor = task.dimension_editor
    assert editor is not None
    editor.setValue(7)
    QTest.keyClick(editor.lineEdit(), Qt.Key.Key_Return)
    assert task.dimension_editor is None
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    assert services.kernel.mass_properties().volume == pytest.approx(100 * pi)
    task.confirm()
    assert loaded.document.commands[-1].id == "sketch.constraint.update"
    assert services.kernel.sketches[0].constraints[1].value == pytest.approx(14)
    assert services.kernel.mass_properties().volume == pytest.approx(196 * pi)
    path = tmp_path / "driven.my3d"
    save_document(loaded.document, path)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(100 * pi)
    assert services.kernel.sketches[0].constraints[0].value == pytest.approx(5)
    reopened_services = app.fork_app_services(services)
    app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches[0].constraints[0].constraint_id == radius.constraint_id
    assert reopened_services.kernel.sketches[0].constraints[1].value == pytest.approx(14)
    assert reopened_services.kernel.mass_properties().volume == pytest.approx(196 * pi)


def test_drag_rectangle_corner_changes_draft_geometry(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.object_snap.setChecked(False)
    task.select_tool("rectangle")
    task.place_uv((-5, -3))
    task.place_uv((5, 3))
    task.select_tool("select")
    start = view.project_world_point((-5, -3, 0))
    target = view.project_world_point((-4, -2, 0))
    assert start is not None and target is not None
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(round(start[0]), round(start[1])))
    QTest.mouseRelease(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(target[0]), round(target[1]))
    )
    rectangle = task.session.sketch.entities[0]
    assert isinstance(rectangle, RectangleEntity)
    assert rectangle.first_corner_mm == pytest.approx((-4, -2), abs=0.1)
    task.undo()
    original = task.session.sketch.entities[0]
    assert isinstance(original, RectangleEntity)
    assert original.first_corner_mm == (-5, -3)
    task.reject()


def test_deleting_related_geometry_requires_confirmation(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((10, 0))
    sketch = task.session.sketch
    line = sketch.entities[0]
    relation = SketchConstraint(
        "12345678123456781234567812345678",
        "horizontal",
        (SketchGeometryReference(line.entity_id, "geometry"),),
    )
    task.session.replace_sketch(replace(sketch, constraints=(relation,)))
    task.selected_entity_id = line.entity_id
    questions: list[str] = []

    def ask(*args: object, **kwargs: object) -> QMessageBox.StandardButton:
        questions.append(str(args[2]))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", ask)
    task.delete_selection()
    assert task.session.sketch.entities == (line,)
    assert task.session.sketch.constraints == (relation,)
    assert relation.constraint_id in questions[0]

    def approve(*args: object, **kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", approve)
    task.delete_selection()
    assert task.session.sketch.entities == ()
    assert task.session.sketch.constraints == ()
    task.reject()


def test_confirmed_sketch_is_preselected_for_independent_extrude(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QComboBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    task.lock_plane()
    task.select_tool("circle")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    sketch_id = task.session.sketch.sketch_id
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert len(loaded.document.commands) == 1
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.extrude")
    bar = window.modeling_command_bar
    assert bar is not None
    source = bar.findChild(QComboBox, "extrudeSource")
    picker = bar.findChild(QComboBox, "sketchProfile")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert source is not None and picker is not None and commit is not None
    assert source.currentData() == "sketch"
    assert picker.currentData() == sketch_id
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    assert len(loaded.document.commands) == 1
    unit = window.execution_unit
    assert unit is not None
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)
    assert loaded.document.commands[-1].id == "feature.extrude"
    assert services.kernel.mass_properties().volume == pytest.approx(pi * 5**2 * 10)


def test_selected_region_from_sketch_drives_extrude(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QComboBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.act_sketch.trigger()
    task = window.part_sketch_task
    view = window.viewport
    assert task is not None and view is not None
    task.lock_plane()
    for center, edge in (((0, 0), (10, 0)), ((0, 0), (3, 0)), ((30, 0), (34, 0))):
        task.select_tool("circle")
        task.place_uv(center)
        task.place_uv(edge)
    outer = task.session.sketch.entities[0]
    view.fit_world_points(((-12, -12, 0), (35, 12, 0)))
    task.region_button.click()
    point = view.project_world_point((5, 0, 0))
    assert point is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(point[0]), round(point[1])))
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.extrude")
    bar = window.modeling_command_bar
    assert bar is not None
    region = bar.findChild(QComboBox, "sketchRegion")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert region is not None and commit is not None
    assert region.currentData() == "selected"
    profile = cast("Mapping[str, object]", bar.values()["profile"])
    assert profile["boundary_entity_ids"] == [outer.entity_id]
    region.setCurrentIndex(region.findData("all"))
    assert "boundary_entity_ids" not in cast("Mapping[str, object]", bar.values()["profile"])
    region.setCurrentIndex(region.findData("selected"))
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    unit = window.execution_unit
    assert unit is not None
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)
    assert services.kernel.mass_properties().volume == pytest.approx(910 * pi)


def test_existing_unchanged_sketch_can_select_region_without_new_history(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("a1" * 16, (0, 0), 10)
    sketch = Sketch("e5" * 16, WorkPlaneFrame.xy(), (circle,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(), confirmed_by="local")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    view.fit_world_points(((-12, -12, 0), (12, 12, 0)))
    task.region_button.click()
    point = view.project_world_point((5, 0, 0))
    assert point is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(point[0]), round(point[1])))
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert task.selected_region_ids == (circle.entity_id,)
    assert len(loaded.document.commands) == 1


def test_selected_region_from_sketch_drives_revolve(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QComboBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.act_sketch.trigger()
    task = window.part_sketch_task
    view = window.viewport
    assert task is not None and view is not None
    task.lock_plane()
    for first, second in (((2, 0), (4, 5)), ((8, 0), (10, 5))):
        task.select_tool("rectangle")
        task.place_uv(first)
        task.place_uv(second)
    selected = task.session.sketch.entities[0]
    view.fit_world_points(((0, -2, 0), (12, 7, 0)))
    task.region_button.click()
    point = view.project_world_point((3, 2, 0))
    assert point is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(point[0]), round(point[1])))
    assert task.selected_region_ids == (selected.entity_id,)
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.revolve")
    bar = window.modeling_command_bar
    assert bar is not None
    axis = bar.findChild(QComboBox, "axis")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert axis is not None and commit is not None
    axis.setCurrentIndex(axis.findData("Y"))
    assert cast("Mapping[str, object]", bar.values()["profile"])["boundary_entity_ids"] == [
        selected.entity_id
    ]
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    unit = window.execution_unit
    assert unit is not None
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)
    assert services.kernel.mass_properties().volume == pytest.approx(60 * pi)


def test_drag_preview_is_transient_and_escape_restores_draft(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.object_snap.setChecked(False)
    task.select_tool("line")
    task.place_uv((-5, 0))
    task.place_uv((5, 0))
    original = task.session.sketch
    task.select_tool("select")
    start = view.project_world_point((-5, 0, 0))
    target = view.project_world_point((-5, 2, 0))
    assert start is not None and target is not None
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(round(start[0]), round(start[1])))
    QTest.mouseMove(view, QPoint(round(target[0]), round(target[1])))
    assert task.session.sketch == original
    assert task.displayed_sketch != original
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert task.session.sketch == original
    assert task.displayed_sketch == original
    task.reject()


def test_repeated_click_cycles_overlapping_geometry(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    for _ in range(2):
        task.place_uv((-5, 0))
        task.place_uv((5, 0))
    entities = task.session.sketch.entities
    task.select_tool("select")
    point = view.project_world_point((0, 0, 0))
    assert point is not None
    position = QPoint(round(point[0]), round(point[1]))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=position)
    first = task.selected_entity_id
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=position)
    second = task.selected_entity_id
    assert {first, second} == {item.entity_id for item in entities}
    assert "候选" in task.status_label.text()
    endpoint = view.project_world_point((-5, 0, 0))
    assert endpoint is not None
    endpoint_position = QPoint(round(endpoint[0]), round(endpoint[1]))
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=endpoint_position)
    first_endpoint = task.selected_entity_id
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=endpoint_position)
    assert {first_endpoint, task.selected_entity_id} == {item.entity_id for item in entities}
    task.reject()


def test_existing_sketch_commits_geometry_and_multiple_constraints_atomically(
    qtbot: QtBot, tmp_path: Path
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), 5)
    sketch = Sketch("d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (circle,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": sketch.sketch_id}, "distance": 4},
        confirmed_by="local",
    )
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    extra = CircleEntity("e4e4e4e4e4e44e4e8e4e4e4e4e4e4e4e", (20, 0), 3, construction=True)
    task.session.add_entity(extra)
    for identity, target, value in (
        ("a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a", circle.entity_id, 7),
        ("b2b2b2b2b2b24b2b8b2b2b2b2b2b2b2b", extra.entity_id, 4),
    ):
        before = task.session.sketch
        relation = SketchConstraint(
            identity, "radius", (SketchGeometryReference(target, "geometry"),), value, "mm"
        )
        result = services.kernel.preview_sketch_constraint(before, relation)
        assert result.status == "success"
        task.accept_constraint(before, relation, result)
    before_payload = document_payload(loaded.document)
    final_draft = task.session.sketch
    task.undo()
    assert len(task.session.sketch.constraints) == 1
    task.redo()
    assert task.session.sketch == final_draft
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    assert document_payload(loaded.document) == before_payload
    task.confirm()
    assert [command.id for command in loaded.document.commands[-3:]] == [
        "sketch.revise",
        "sketch.constraint.add",
        "sketch.constraint.add",
    ]
    assert services.kernel.sketches[0] == task.session.sketch
    assert services.kernel.mass_properties().volume == pytest.approx(196 * pi)
    path = tmp_path / "mixed-sketch.my3d"
    save_document(loaded.document, path)
    reopened_services = app.fork_app_services(services)
    reopened = app.open_app_document(reopened_services, path)
    assert reopened.document.commands == loaded.document.commands
    assert reopened_services.kernel.sketches[0] == final_draft
    assert reopened_services.kernel.mass_properties().volume == pytest.approx(196 * pi)


def test_existing_sketch_can_persist_inferred_relation_on_new_geometry(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 5), 2)
    sketch = Sketch("d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (circle,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    task.select_tool("line")
    for point in ((0.0, 0.0, 0.0), (10.0, 0.05, 0.0)):
        screen = view.project_world_point(point)
        assert screen is not None
        QTest.mouseClick(
            view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
        )
    assert len(task.session.sketch.constraints) == 1
    assert task.session.sketch.constraints[0].source == "inferred"
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert services.kernel.sketches[0].constraints == task.session.sketch.constraints


def test_inferred_relation_is_marked_and_cleared_with_draft(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    for point in ((0.0, 0.0, 0.0), (10.0, 0.05, 0.0)):
        screen = view.project_world_point(point)
        assert screen is not None
        QTest.mouseClick(
            view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
        )
    assert view.draft_relation_labels() == ("H",)
    task.undo()
    assert view.draft_relation_labels() == ()
    task.redo()
    assert view.draft_relation_labels() == ("H",)
    task.reject()
    assert view.draft_relation_labels() == ()


def test_new_sketch_preserves_consecutive_dimension_edits(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("circle")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    entity = task.session.sketch.entities[0]
    relation = SketchConstraint(
        "a1a1a1a1a1a14a1a8a1a1a1a1a1a1a1a",
        "radius",
        (SketchGeometryReference(entity.entity_id, "geometry"),),
        6,
        "mm",
    )
    initial = task.session.sketch
    first = services.kernel.preview_sketch_constraint(initial, relation)
    task.accept_constraint(initial, relation, first)
    before = task.session.sketch
    revised = replace(relation, value=7)
    second = services.kernel.preview_sketch_constraint_update(before, revised)
    task.accept_constraint(before, revised, second)
    final = task.session.sketch
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert [item.id for item in loaded.document.commands] == [
        "sketch.create",
        "sketch.constraint.add",
        "sketch.constraint.update",
    ]
    assert services.kernel.sketches[0] == final


def test_failed_downstream_rebuild_preserves_source_and_draft(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    circle = CircleEntity("c2c2c2c2c2c24c2c8c2c2c2c2c2c2c2c", (0, 0), 5)
    helper = CircleEntity("e4e4e4e4e4e44e4e8e4e4e4e4e4e4e4e", (20, 0), 3, construction=True)
    sketch = Sketch("d3d3d3d3d3d34d3d8d3d3d3d3d3d3d3d", WorkPlaneFrame.xy(), (circle, helper))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), confirmed_by="local")
    loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": sketch.sketch_id}, "distance": 4},
        confirmed_by="local",
    )
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4, existing_sketch=sketch)
    qtbot.addWidget(task)
    task.session.delete_entities((circle.entity_id,))
    draft = task.session.sketch
    before = document_payload(loaded.document)
    task.preview()
    assert not task.confirm_button.isEnabled()
    assert "预览失败" in task.status_label.text()
    assert "sketch.revise" in task.status_label.text()
    assert "ReplayFailure(" not in task.status_label.text()
    assert "第" in task.status_label.text()
    assert document_payload(loaded.document) == before
    assert task.session.sketch == draft
    assert services.kernel.mass_properties().volume == pytest.approx(100 * pi)
    task.reject()


def test_drawing_snaps_to_draft_line_midpoint(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((2, 0))
    task.place_uv((12, 0))
    for point in ((7.0, 0.0, 0.0), (7.0, 4.0, 0.0)):
        screen = view.project_world_point(point)
        assert screen is not None
        QTest.mouseClick(
            view, Qt.MouseButton.LeftButton, pos=QPoint(round(screen[0]), round(screen[1]))
        )
    line = task.session.sketch.entities[-1]
    assert isinstance(line, LineEntity)
    assert line.start_mm == pytest.approx((7, 0))
    task.reject()


def test_part_sketch_uses_embedded_command_bar_and_exclusive_tool(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QToolBar

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1300, 900)
    window.bind_document(loaded)
    window.show()
    assert window.command_palette is not None
    window.command_palette.command_activated.emit("feature.hole")
    bar = window.modeling_command_bar
    assert bar is not None and bar.isVisible()
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    sketch_bar = window.findChild(QToolBar, "partRibbonToolbar")
    assert sketch_bar is not None and sketch_bar.isVisible()
    assert not task.isWindow()
    assert sketch_bar.isAncestorOf(task)
    assert not bar.isVisible()
    assert task.line_button.isEnabled()
    window.resize(1000, 700)
    qtbot.wait(50)
    for button in (task.line_button, task.constraint_button, task.preview_button):
        assert button.width() >= button.sizeHint().width()
    options = task.findChild(QPushButton, "partSketchOptions")
    assert options is not None
    assert not task.grid_spacing.isVisible()
    options.click()
    assert task.grid_spacing.isVisible()
    options.click()
    assert not task.grid_spacing.isVisible()
    assert window.viewport is not None
    assert (
        sketch_bar.mapToGlobal(QPoint(0, sketch_bar.height())).y()
        <= window.viewport.mapToGlobal(QPoint()).y()
    )
    task.lock_plane()
    assert task.line_button.isEnabled()
    task.select_tool("line")
    assert task.line_button.isChecked() and not task.rectangle_button.isChecked()
    task.place_uv((0, 0))
    task.place_uv((10, 0))
    window.command_palette.command_activated.emit("feature.box")
    assert not bar.isVisible()
    assert task.has_draft
    window.workspace_tabs.activate("drawing")
    assert not sketch_bar.isVisible()
    assert task.has_draft
    window.workspace_tabs.activate("model")
    assert sketch_bar.isVisible()
    task.reject()
    assert sketch_bar.isVisible()
    window.command_palette.command_activated.emit("feature.box")
    assert bar.isVisible()


def test_active_sketch_is_visible_on_top_of_model(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 10}, "local")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    if not view.isValid():
        pytest.skip("requires a working OpenGL framebuffer")
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("rectangle")
    task.place_uv((-8, -5))
    task.place_uv((8, 5))
    view.update()
    qtbot.wait(150)
    framebuffer = view.grabFramebuffer()
    position = view.project_world_point((0, 5, 0))
    assert position is not None
    ratio = view.devicePixelRatioF()
    x, y = round(position[0] * ratio), round(position[1] * ratio)
    colors = [framebuffer.pixelColor(x + dx, y + dy) for dx in range(-3, 4) for dy in range(-3, 4)]
    assert any(
        color.blue() > color.red() + 45 and color.blue() > color.green() + 35 for color in colors
    )
    task.reject()


def test_drawing_displays_live_temporary_geometry_and_escape_clears_it(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.object_snap.setChecked(False)
    task.select_tool("rectangle")
    start = view.project_world_point((-5, -5, 0))
    end = view.project_world_point((5, 5, 0))
    assert start is not None and end is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(start[0]), round(start[1])))
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(*end),
        QPointF(view.mapToGlobal(QPoint(round(end[0]), round(end[1])))),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view, move)
    assert task.session.sketch.entities == ()
    assert view.draft_sketch_curve_count() == 1
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.draft_sketch_curve_count() == 0
    assert task.session.sketch.entities == ()
    task.reject()


def test_pick_visible_datum_to_choose_sketch_plane(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    candidate = app.create_replay_candidate(services, loaded, session_identity=4)
    datum = {
        "name": "平面 A",
        "construction": {
            "kind": "principal",
            "coordinate_system": {"kind": "world"},
            "plane": "xz",
        },
    }
    candidate.stage(
        ReplayChangeSet((), (ReplayAppend("datum.plane.create", 1, datum, "local"),), False, 6),
        current_session_identity=4,
    )
    assert candidate.preview(current_session_identity=4).state == "succeeded"
    candidate.commit(
        candidate.authorize_commit(current_session_identity=4), current_session_identity=4
    )
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    plane = next(item for item in view.interaction_datums() if item.name == "平面 A")
    view.datum_selection_changed.emit(plane.reference)
    assert task.plane_combo.currentText() == "平面 A"
    task.lock_plane()
    assert task.session.sketch.frame == plane.frame
    task.reject()


def test_snap_marker_clears_when_cursor_leaves_anchor(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    for point in ((0.0, 0.0, 0.0), (12.0, 8.0, 0.0)):
        pos = view.project_world_point(point)
        assert pos is not None
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(*pos),
            QPointF(view.mapToGlobal(QPoint(round(pos[0]), round(pos[1])))),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(view, event)
        if point[0] == 0:
            assert view.position_marker_points()
    assert view.position_marker_points() == ()
    task.reject()


def test_unfinished_entity_blocks_preview_and_confirm(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("rectangle")
    task.place_uv((0, 0))
    task.place_uv((10, 5))
    task.preview()
    assert task.confirm_button.isEnabled()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.preview()
    task.confirm()
    assert not task.confirm_button.isEnabled()
    assert not loaded.document.commands
    assert task.has_draft
    task.reject()


def test_line_preview_matches_inferred_endpoint(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    getattr(task, "_preview" + "_drawing")((10, 0.05))
    endpoint = getattr(task, "_rubber" + "_band_curve")[-1]
    task.place_uv((10, 0.05), numeric=False)
    line = task.session.sketch.entities[0]
    assert isinstance(line, LineEntity)
    assert endpoint == task.session.sketch.frame.local_to_world(line.end_mm)
    task.reject()


def test_locked_line_dimensions_match_preview_and_committed_geometry(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.dynamic_input.first_value.setValue(10)
    task.dynamic_input.first_lock.setChecked(True)
    task.dynamic_input.second_value.setValue(30)
    task.dynamic_input.second_lock.setChecked(True)
    getattr(task, "_preview" + "_drawing")((8, 0.01))
    endpoint = getattr(task, "_rubber" + "_band_curve")[-1]
    task.place_uv((8, 0.01), numeric=False)
    line = task.session.sketch.entities[0]
    assert isinstance(line, LineEntity)
    assert line.end_mm == pytest.approx((8.660254037844, 5))
    assert endpoint == pytest.approx(task.session.sketch.frame.local_to_world(line.end_mm))
    assert not task.session.sketch.constraints
    task.undo()
    assert not task.session.sketch.entities
    task.reject()


def test_locked_rectangle_and_circle_dimensions_commit_exact_values(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("rectangle")
    task.place_uv((2, 3))
    task.dynamic_input.first_value.setValue(12)
    task.dynamic_input.first_lock.setChecked(True)
    task.dynamic_input.second_value.setValue(7)
    task.dynamic_input.second_lock.setChecked(True)
    task.place_uv((-10, 15), numeric=False)
    rectangle = task.session.sketch.entities[0]
    assert isinstance(rectangle, RectangleEntity)
    assert rectangle.opposite_corner_mm == pytest.approx((-10, 10))
    task.select_tool("circle")
    task.place_uv((0, 0))
    task.dynamic_input.first_value.setValue(5)
    task.dynamic_input.first_lock.setChecked(True)
    task.dynamic_input.circle_mode.setCurrentIndex(1)
    assert task.dynamic_input.first_value.value() == pytest.approx(10)
    task.place_uv((30, 0), numeric=False)
    circle = task.session.sketch.entities[1]
    assert isinstance(circle, CircleEntity)
    assert circle.radius_mm == pytest.approx(5)
    task.reject()


def test_dynamic_continuous_line_resets_locks_between_segments(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("continuous")
    task.place_uv((0, 0))
    task.dynamic_input.first_value.setValue(5)
    task.dynamic_input.first_lock.setChecked(True)
    task.place_uv((10, 0), numeric=False)
    assert not task.dynamic_input.first_lock.isChecked()
    task.place_uv((5, 8), numeric=True)
    first, second = task.session.sketch.entities
    assert isinstance(first, LineEntity) and isinstance(second, LineEntity)
    assert first.end_mm == pytest.approx((5, 0))
    assert second.start_mm == pytest.approx(first.end_mm)
    assert second.end_mm == pytest.approx((5, 8))
    task.reject()


def test_dynamic_geometry_survives_save_and_reopen(qtbot: QtBot, tmp_path: Path) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("circle")
    task.place_uv((2, 3))
    task.dynamic_input.first_value.setValue(8)
    task.dynamic_input.first_lock.setChecked(True)
    task.place_uv((20, 3), numeric=False)
    task.preview()
    task.confirm()
    assert len(loaded.document.commands) == 1
    path = tmp_path / "dynamic-sketch.my3d"
    save_document(loaded.document, path)
    reopened_services = app.fork_app_services(services)
    app.open_app_document(reopened_services, path)
    circle = reopened_services.kernel.sketches[0].entities[0]
    assert isinstance(circle, CircleEntity)
    assert circle.center_mm == pytest.approx((2, 3))
    assert circle.radius_mm == pytest.approx(8)


def test_invalid_dynamic_size_keeps_unfinished_entity_for_correction(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("circle")
    task.place_uv((0, 0))
    task.dynamic_input.first_value.setValue(0)
    task.dynamic_input.first_lock.setChecked(True)
    task.place_uv((5, 0), numeric=False)
    assert not task.session.sketch.entities
    assert "大于零" in task.status_label.text()
    task.dynamic_input.first_value.lineEdit().setText("-")
    task.place_uv((5, 0), numeric=False)
    assert not task.session.sketch.entities
    assert "有效" in task.status_label.text()
    task.dynamic_input.first_value.setValue(3)
    getattr(task, "_preview" + "_drawing")((5, 0))
    assert "有效" not in task.status_label.text()
    task.place_uv((5, 0), numeric=False)
    circle = task.session.sketch.entities[0]
    assert isinstance(circle, CircleEntity)
    assert circle.radius_mm == pytest.approx(3)
    task.reject()


@pytest.mark.parametrize("tool", ["rectangle", "circle"])
def test_dynamic_preview_matches_finished_shape(qtbot: QtBot, tool: str) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool(tool)
    task.place_uv((0, 0))
    task.dynamic_input.first_value.setValue(6)
    task.dynamic_input.first_lock.setChecked(True)
    if tool == "rectangle":
        task.dynamic_input.second_value.setValue(4)
        task.dynamic_input.second_lock.setChecked(True)
    getattr(task, "_preview" + "_drawing")((9, 3))
    preview = getattr(task, "_rubber" + "_band_curve")
    task.place_uv((9, 3), numeric=False)
    shape = task.session.sketch.entities[0]
    if isinstance(shape, RectangleEntity):
        assert preview[2] == pytest.approx(
            task.session.sketch.frame.local_to_world(shape.opposite_corner_mm)
        )
    else:
        assert isinstance(shape, CircleEntity)
        assert dist(
            preview[0], task.session.sketch.frame.local_to_world(shape.center_mm)
        ) == pytest.approx(shape.radius_mm)
    task.reject()


def test_dynamic_field_focus_and_escape_do_not_close_sketch(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    session = DocumentSession()
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=session)
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    field = task.dynamic_input.first_value
    field.setFocus()
    qtbot.waitUntil(field.hasFocus)
    QTest.keyClick(field.lineEdit(), Qt.Key.Key_Tab)
    assert task.dynamic_input.second_value.hasFocus()
    QTest.keyClick(task.dynamic_input.second_value.lineEdit(), Qt.Key.Key_Tab)
    assert task.dynamic_input.first_lock.hasFocus()
    QTest.keyClick(task.dynamic_input.first_lock, Qt.Key.Key_Space)
    assert task.dynamic_input.first_lock.isChecked()
    QTest.keyClick(task.dynamic_input.first_lock, Qt.Key.Key_Space)
    assert not task.dynamic_input.first_lock.isChecked()
    field.setFocus()
    QTest.keyClick(field.lineEdit(), Qt.Key.Key_Return)
    assert window.part_sketch_task is task
    assert not task.session.sketch.entities
    QTest.keyClick(field.lineEdit(), Qt.Key.Key_Escape)
    assert window.part_sketch_task is task
    assert not task.session.sketch.entities
    assert not task.dynamic_input.first_lock.isChecked()
    task.place_uv((5, 5))
    task.place_uv((8, 5))
    line = task.session.sketch.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == pytest.approx((5, 5))
    task.reject()


def test_dynamic_keyboard_input_and_mouse_commit_use_same_geometry(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.resize(1024, 768)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    window.act_sketch.trigger()
    task, view = window.part_sketch_task, window.viewport
    assert task is not None and view is not None
    task.lock_plane()
    task.object_snap.setChecked(False)
    task.select_tool("line")
    start = view.project_world_point((0, 0, 0))
    cursor = view.project_world_point((8, 0.1, 0))
    assert start is not None and cursor is not None
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(round(start[0]), round(start[1])))
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(*cursor),
        QPointF(view.mapToGlobal(QPoint(round(cursor[0]), round(cursor[1])))),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view, move)
    field = task.dynamic_input.first_value.lineEdit()
    field.setFocus()
    QTest.keyClick(field, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(field, "10")
    assert task.dynamic_input.first_lock.isChecked()
    angle = task.dynamic_input.second_value.lineEdit()
    angle.setFocus()
    QTest.keyClick(angle, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(angle, "30")
    assert task.dynamic_input.second_lock.isChecked()
    endpoint = getattr(task, "_rubber" + "_band_curve")[-1]
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(cursor[0]), round(cursor[1]))
    )
    line = task.session.sketch.entities[0]
    assert isinstance(line, LineEntity)
    assert line.end_mm == pytest.approx((8.660254037844, 5), abs=0.01)
    assert endpoint == pytest.approx(task.session.sketch.frame.local_to_world(line.end_mm))
    assert not task.dynamic_input.first_lock.isChecked()
    assert not task.dynamic_input.second_lock.isChecked()
    task.reject()


def test_dynamic_field_undo_does_not_undo_sketch_geometry(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    task.place_uv((1, 1))
    field = task.dynamic_input.first_value.lineEdit()
    field.setFocus()
    QTest.keyClick(field, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(field, "8")
    QTest.keyClick(field, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert len(task.session.sketch.entities) == 1
    task.reject()


def test_locked_length_does_not_show_or_persist_incompatible_snap(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    view.resize(800, 600)
    view.bind_document(loaded)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((10, 10))
    task.place_uv((20, 10))
    task.place_uv((0, 0))
    task.dynamic_input.first_value.setValue(5)
    task.dynamic_input.first_lock.setChecked(True)
    target = view.project_world_point((10, 10, 0))
    assert target is not None
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(*target),
        QPointF(view.mapToGlobal(QPoint(round(target[0]), round(target[1])))),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view, move)
    assert not view.position_marker_points()
    task.dynamic_input.first_lock.setChecked(False)
    assert view.position_marker_points()
    task.dynamic_input.first_lock.setChecked(True)
    task.dynamic_input.first_value.setValue(5)
    assert not view.position_marker_points()
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, pos=QPoint(round(target[0]), round(target[1]))
    )
    line = task.session.sketch.entities[-1]
    assert isinstance(line, LineEntity)
    assert dist(line.start_mm, line.end_mm) == pytest.approx(5)
    assert not task.session.sketch.constraints
    task.reject()


def test_undo_clears_unfinished_outline(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((5, 0))
    task.select_tool("rectangle")
    task.place_uv((0, 0))
    getattr(task, "_preview" + "_drawing")((2, 3))
    task.undo()
    assert not getattr(task, "_rubber" + "_band_curve")
    assert view.draft_sketch_curve_count() == 0
    task.reject()


def test_resident_rectangle_entry_selects_tool_before_plane(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QToolButton

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.part_ribbon.setCurrentIndex(1)
    button = next(
        button
        for button in window.part_ribbon.findChildren(QToolButton)
        if button.defaultAction() is window.act_part_rectangle
    )
    button.click()
    task = window.part_sketch_task
    assert task is not None
    assert task.rectangle_button.isChecked()
    assert not getattr(task, "_lock" + "ed")
    task.lock_plane()
    task.place_uv((0, 0))
    task.place_uv((10, 5))
    assert isinstance(task.session.sketch.entities[0], RectangleEntity)
    task.reject()


def test_tool_then_pick_model_face_and_lock(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 8})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    view = window.viewport
    assert view is not None
    view.resize(800, 600)
    view.set_orientation("top")
    view.fit_view()
    window.selection_filter_actions["edge"].trigger()
    initial_view = view.capture_view()
    window.act_part_rectangle.trigger()
    task = window.part_sketch_task
    assert task is not None
    assert view.selection_filter() == "face"
    assert window.selection_filter_actions["face"].isChecked()
    assert view.pick_at(view.width() / 2, view.height() / 2)
    assert task.plane_combo.currentText() == "所选模型平面（查询）"
    task.lock_plane()
    task.place_uv((0, 0))
    task.place_uv((4, 3))
    assert task.session.sketch.support_face is not None
    assert isinstance(task.session.sketch.entities[0], RectangleEntity)
    task.reject()
    assert view.selection_filter() == "edge"
    assert window.selection_filter_actions["edge"].isChecked()
    restored_view = view.capture_view()
    assert restored_view.distance == initial_view.distance
    assert restored_view.center == initial_view.center
    assert restored_view.orientation == initial_view.orientation
    assert restored_view.rotation == initial_view.rotation


def test_2d_entry_does_not_turn_part_into_a_drawing(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.act_view_2d.trigger()
    assert window.active_workspace == "model"
    assert window.loaded_document() is loaded
    assert window.part_sketch_task is None


def test_undo_cancels_outline_even_without_accepted_edits(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("rectangle")
    task.place_uv((0, 0))
    getattr(task, "_preview" + "_drawing")((2, 3))
    task.undo()
    assert not task.has_draft
    assert view.draft_sketch_curve_count() == 0
    task.reject()


def test_escape_before_plane_lock_cancels_selected_tool(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    task.select_tool("rectangle")
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert task.select_button.isChecked()
    assert not task.rectangle_button.isChecked()
    task.reject()


def test_stale_part_sketch_cleanup_preserves_current_session_filter(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    view.set_selection_filter("edge")
    session = [4]
    task = PartSketchWorkbench(
        services, loaded, view, session_identity=4, current_session=lambda: session[0]
    )
    qtbot.addWidget(task)
    assert view.selection_filter() == "face"
    session[0] = 5
    view.set_selection_filter("vertex")
    task.reject()
    assert view.selection_filter() == "vertex"


def test_stale_part_sketch_does_not_intercept_current_session_input(qtbot: QtBot) -> None:
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QKeyEvent, QMouseEvent

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    session = [4]
    task = PartSketchWorkbench(
        services,
        loaded,
        view,
        session_identity=4,
        current_session=lambda: session[0],
        can_execute=lambda: False,
    )
    qtbot.addWidget(task)
    session[0] = 5
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
    assert not task.eventFilter(view, event)
    mouse = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(20, 20),
        QPointF(20, 20),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert not task.eventFilter(view, mouse)
    task.reject()


def test_closed_part_sketch_cannot_modify_active_viewport(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    busy = [False]
    task = PartSketchWorkbench(
        services, loaded, view, session_identity=4, can_execute=lambda: not busy[0]
    )
    qtbot.addWidget(task)
    finished: list[int] = []
    task.finished.connect(finished.append)
    task.reject()
    calls: list[bool] = []

    def record_curves(*_args: object, **_kwargs: object) -> None:
        calls.append(True)

    monkeypatch.setattr(view, "set_draft_sketch_curves", record_curves)
    monkeypatch.setattr(view, "clear_candidate_preview", record_curves)
    busy[0] = True
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
    assert not task.eventFilter(view, event)
    busy[0] = False
    task.select_tool("line")
    task.lock_plane()
    loaded.bus.execute("feature.box", {"size_x": 2, "size_y": 2, "size_z": 2})
    task.reject()
    task.accept()
    assert not calls
    assert len(finished) == 1
    assert len(loaded.document.commands) == 1


def test_part_sketch_normal_view_works_before_and_after_lock(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    task = PartSketchWorkbench(services, loaded, view, session_identity=4)
    qtbot.addWidget(task)
    calls: list[object] = []

    def record_view(frame: object) -> None:
        calls.append(frame)

    monkeypatch.setattr(view, "look_at_workplane", record_view)
    task.normal_view_button.click()
    assert len(calls) == 1
    task.lock_plane()
    calls.clear()
    task.normal_view_button.click()
    assert len(calls) == 1
    task.reject()


@pytest.mark.parametrize("expiry", ["session", "closed", "revision"])
def test_old_dynamic_input_cannot_clear_current_viewport(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, expiry: str
) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    view = GLViewport(viewport_port=services.kernel)
    qtbot.addWidget(view)
    view.bind_document(loaded)
    session = [4]
    task = PartSketchWorkbench(
        services, loaded, view, session_identity=4, current_session=lambda: session[0]
    )
    qtbot.addWidget(task)
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0.0, 0.0))
    monkeypatch.setattr(task, "_last_dynamic_point", (1.0, 1.0))
    if expiry == "closed":
        task.reject()
    elif expiry == "session":
        session[0] = 5
    else:
        loaded.bus.execute("feature.box", {"size_x": 2, "size_y": 2, "size_z": 2})
    calls: list[str] = []

    def record_view(*_args: object, **_kwargs: object) -> None:
        calls.append("view")

    monkeypatch.setattr(view, "set_draft_sketch_regions", record_view)
    monkeypatch.setattr(view, "set_position_markers", record_view)
    monkeypatch.setattr(view, "look_at_workplane", record_view)
    monkeypatch.setattr(task, "_preview_drawing", record_view)
    task.dynamic_input.changed.emit()
    task.dynamic_input.escape_requested.emit()
    task.normal_view_button.click()
    assert calls == []
    if expiry != "closed":
        task.reject()


def test_sketch_ribbon_is_resident_grouped_and_reuses_active_page(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QFrame

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1024, 768)
    window.show()
    assert [window.part_ribbon.tabText(i) for i in range(window.part_ribbon.count())] == [
        "主页",
        "草图",
        "检查",
        "工具",
        "视图",
    ]
    window.part_ribbon.setCurrentIndex(1)
    assert window.part_ribbon.isVisible()
    assert (
        window.part_sketch_entry_toolbar.y()
        >= window.main_toolbar.y() + window.main_toolbar.height()
    )
    window.act_part_rectangle.trigger()
    task = window.part_sketch_task
    assert task is not None
    assert window.part_ribbon.isAncestorOf(task)
    assert window.part_ribbon.currentIndex() == 1
    assert all(
        task.findChild(QFrame, name) is not None
        for name in (
            "sketchPlaneGroup",
            "sketchDrawGroup",
            "sketchRelationsGroup",
            "sketchFinishGroup",
        )
    )
    assert window.part_ribbon.width() <= window.width()
    task.reject()
    assert window.part_ribbon.isVisible()
    assert window.part_ribbon.currentIndex() == 1


def test_ribbon_starts_on_own_row_after_restoring_old_layout(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    first = MainWindow(services=services)
    qtbot.addWidget(first)
    first.removeToolBarBreak(first.part_sketch_entry_toolbar)
    first.store_window_state()
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1024, 768)
    window.show()
    assert (
        window.part_sketch_entry_toolbar.y()
        >= window.main_toolbar.y() + window.main_toolbar.height()
    )


def test_sketch_options_use_two_rows_for_narrow_windows(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="part")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1024, 768)
    window.show()
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    task.options_button.click()
    qtbot.wait(50)
    assert (
        task.u_field.mapTo(task.options_panel, QPoint()).y()
        > task.object_snap.mapTo(task.options_panel, QPoint()).y()
    )
    assert (
        task.numeric_point_button.mapTo(window, QPoint(task.numeric_point_button.width(), 0)).x()
        <= window.width()
    )
    task.reject()


def test_narrow_part_sketch_keeps_plane_and_finish_controls_accessible(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.new_session_document("part")
    window.resize(683, 600)
    window.show()
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    task.select_tool("line")
    qtbot.wait(100)
    assert window.width() <= 683
    cancel = next(
        button for button in task.findChildren(QPushButton) if button.text() == "取消草图"
    )
    for button in (task.lock_button, task.confirm_button, cancel):
        assert button.isVisible()
        assert window.rect().contains(button.mapTo(window, button.rect().bottomRight()))
        assert button.visibleRegion().boundingRect() == button.rect()
    for field in (task.dynamic_input.first_value, task.dynamic_input.second_value):
        assert field.isVisible()
        assert field.visibleRegion().boundingRect() == field.rect()
    task.reject()


def test_large_part_sketch_shows_dynamic_fields_without_scrolling(qtbot: QtBot) -> None:
    from mycad.ui.document_session import DocumentSession

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1920, 1080)
    window.show()
    window.show_start_page()
    entry = window.new_session_document("part")
    entry.loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 30, "size_z": 8})
    assert window.viewport is not None
    window.viewport.refresh()
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    task.select_tool("line")
    qtbot.wait(500)
    for field in (task.dynamic_input.first_value, task.dynamic_input.second_value):
        assert field.isVisible()
        assert field.visibleRegion().boundingRect() == field.rect()
        assert field.height() >= field.minimumSizeHint().height()
    task.reject()
