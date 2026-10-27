# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Second manual acceptance gates, exercised through real Qt controls."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document, open_app_document
from mycad.core.persistence import save_document
from mycad.core.sketch import CircleEntity, LineEntity
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog


def _click_dimension(draft: SketchEditorDialog, point: tuple[float, float]) -> None:
    QTest.mouseClick(
        draft.canvas, Qt.MouseButton.LeftButton, pos=draft.canvas.local_to_screen(point)
    )


def _drive_line(draft: SketchEditorDialog, value: float) -> None:
    draft.dimensions.buttons["aligned"].click()
    _click_dimension(draft, (15, 0))
    _click_dimension(draft, (15, -15))
    draft.dimensions.driving_check.setChecked(True)
    draft.dimensions.value_editor.setValue(value)
    draft.dimensions.apply_button.click()


def _edit_dimension(draft: SketchEditorDialog, identity: str) -> None:
    QTest.keyClick(draft.canvas, Qt.Key.Key_Escape)
    dimension = next(
        c
        for c in (*draft.canvas.constraints, *draft.canvas.background_constraints)
        if c.constraint_id == identity
    )
    entities = {e.entity_id: e for e in draft.canvas.visible_snap_entities()}
    layout = draft.canvas.dimension_layout(dimension, entities)
    assert layout is not None
    QTest.mouseDClick(draft.canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())


@pytest.mark.parametrize("tool", ["直线", "多段线"])
def test_right_click_matches_enter_without_submitting(qtbot: QtBot, tool: str) -> None:
    draft = SketchEditorDialog(continuous_lines=True)
    qtbot.addWidget(draft)
    draft.show()
    draft.canvas.set_tool(tool)
    for point in ((0.0, 0.0), (30.0, 0.0), (30.0, 20.0)):
        draft.canvas.add_coordinate_point(point)
    QTest.mouseClick(draft.canvas, Qt.MouseButton.RightButton)
    assert not draft.canvas.has_pending_geometry
    assert not draft.canvas.can_close_chain
    assert len(draft.canvas.entities) == (2 if tool == "直线" else 1)
    assert draft.result_sketch is None
    assert draft.isVisible()


def test_origin_grid_and_object_snap_priority(qtbot: QtBot) -> None:
    draft = SketchEditorDialog(continuous_lines=True)
    qtbot.addWidget(draft)
    draft.show()
    canvas = draft.canvas
    events: list[tuple[float, float, str]] = []

    def capture(u: float, v: float, kind: str) -> None:
        events.append((u, v, kind))

    canvas.cursor_changed.connect(capture)

    def hover(u: float, v: float) -> tuple[float, float, str]:
        QApplication.processEvents()
        # Seed a different position: Qt may coalesce a move to the previous cursor location.
        QTest.mouseMove(canvas, QPoint(1, 1))
        QTest.mouseMove(canvas, canvas.local_to_screen((u, v)))
        return events[-1]

    assert hover(0.4, -0.4) == (0.0, 0.0, "UCS 原点")
    draft.grid_snap_check.setChecked(True)
    step = canvas.grid_spacing_mm()
    assert hover(step + 0.2, step - 0.2) == (step, step, "栅格")
    canvas.replace_draft_entities(
        (LineEntity("11111111-1111-4111-8111-111111111111", (step + 0.5, step), (30.0, 40.0)),)
    )
    assert hover(step, step)[2] == "端点"
    canvas.set_snapping_enabled(False)
    assert hover(0.4, 0.4) == (0.0, 0.0, "栅格")
    draft.grid_snap_check.setChecked(False)
    assert hover(0.6, 0.6)[2] == ""


def test_persistent_controls_and_distinct_graphical_tools(qtbot: QtBot) -> None:
    draft = SketchEditorDialog(continuous_lines=True)
    qtbot.addWidget(draft)
    draft.resize(980, 570)
    draft.show()
    buttons = (*draft.tool_buttons.values(), *draft.transform_buttons.values())
    assert all(not button.icon().isNull() for button in buttons)
    assert len({button.property("cadIconName") for button in buttons}) == len(buttons)
    draft.tool_panel.verticalScrollBar().setValue(10000)
    for control in (
        draft.layer_combo,
        draft.layer_manager_button,
        draft.dimensions.buttons["smart"],
    ):
        assert control.isVisible()
        assert not draft.tool_panel.isAncestorOf(control)


def test_view_switch_preserves_pending_draft_and_history(qtbot: QtBot) -> None:
    window = MainWindow(services=build_app(discoverers=()))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.add_coordinate_point((0.0, 0.0))
    draft.canvas.add_coordinate_point((30.0, 0.0))
    before = (
        tuple(draft.canvas.entities),
        tuple(draft.canvas.constraints),
        draft.canvas.pending_point_count,
    )
    window.act_view_3d.trigger()
    assert (
        window.workspace_tabs.content("model") is window.viewport
        and window.active_workspace == "model"
    )
    assert window.active_sketch_dialog() is draft
    window.act_view_2d.trigger()
    assert window.workspace_tabs.content("sketch") is draft and window.active_workspace == "sketch"
    assert (
        tuple(draft.canvas.entities),
        tuple(draft.canvas.constraints),
        draft.canvas.pending_point_count,
    ) == before
    assert window.active_sketch_dialog() is draft
    draft.reject()
    window.close()


def test_dimension_drives_draft_and_undo_restores_geometry(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    draft = SketchEditorDialog(
        continuous_lines=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(draft)
    draft.show()
    draft.canvas.add_coordinate_point((0.0, 0.0))
    draft.canvas.add_coordinate_point((30.0, 0.0))
    draft.canvas.end_line_chain()
    original = tuple(draft.canvas.entities)
    _drive_line(draft, 50.0)
    line = draft.canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert math.dist(line.start_mm, line.end_mm) == pytest.approx(50.0)
    assert draft.canvas.constraints[-1].kind == "distance"
    assert draft.canvas.undo_last_operation()
    assert tuple(draft.canvas.entities) == original
    assert draft.canvas.redo_last_operation()
    draft.finish_sketch()
    assert draft.result_sketch is not None
    assert draft.result_sketch.constraints[-1].value == pytest.approx(50.0)


def test_dimension_lines_survive_submission_as_background(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    draft = SketchEditorDialog()
    qtbot.addWidget(draft)
    line = LineEntity("11111111-1111-4111-8111-111111111111", (0.0, 0.0), (30.0, 0.0))
    constraint = SketchConstraint(
        "22222222-2222-4222-8222-222222222222",
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        30.0,
        "mm",
    )
    sketch = Sketch(
        "33333333-3333-4333-8333-333333333333", WorkPlaneFrame.xy(), (line,), (constraint,)
    )
    draft.set_context_sketches((sketch,))
    assert draft.canvas.background_constraints == (constraint,)
    layout = draft.canvas.dimension_layout(constraint, {line.entity_id: line})
    assert layout is not None
    assert len(layout.lines) == 3  # two extension lines and the dimension line
    assert len(layout.arrows) == 2
    assert layout.label.y() != draft.canvas.local_to_screen((15.0, 0.0)).y()
    assert draft.dimensions.buttons["smart"].isEnabled()


def test_existing_draft_dimension_update_and_cancel(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    draft = SketchEditorDialog(
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(draft)
    draft.show()
    for point in ((0.0, 0.0), (30.0, 0.0)):
        draft.canvas.add_coordinate_point(point)
    _drive_line(draft, 40.0)
    before = (
        tuple(draft.canvas.entities),
        tuple(draft.canvas.constraints),
        draft.canvas.pending_point_count,
    )
    identity = before[1][-1].constraint_id
    _edit_dimension(draft, identity)
    draft.dimensions.value_editor.setValue(60.0)
    assert draft.dimensions.apply_button.isEnabled()
    assert draft.canvas.dimension_preview is not None
    QTest.keyClick(draft.dimensions.value_editor, Qt.Key.Key_Escape)
    assert draft.canvas.dimension_preview is None
    assert (
        tuple(draft.canvas.entities),
        tuple(draft.canvas.constraints),
        draft.canvas.pending_point_count,
    ) == before
    _edit_dimension(draft, identity)
    draft.dimensions.value_editor.setValue(60.0)
    draft.dimensions.apply_button.click()
    assert draft.canvas.constraints[-1].constraint_id == identity
    assert draft.canvas.constraints[-1].value == pytest.approx(60.0)


@pytest.mark.parametrize("driving", [True, False])
@pytest.mark.parametrize(
    "kind,target,measured",
    [
        ("length", 42.0, 30.0),
        ("distance", 25.0, 30.0),
        ("angle", 60.0, 90.0),
        ("radius", 12.0, 10.0),
        ("diameter", 24.0, 20.0),
    ],
)
def test_all_five_dimension_kinds_drive_or_measure(
    qtbot: QtBot, kind: str, target: float, measured: float, driving: bool
) -> None:
    services = build_app(discoverers=())
    draft = SketchEditorDialog(
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(draft)
    draft.show()
    entities = (
        LineEntity("11111111-1111-4111-8111-111111111111", (0.0, 0.0), (30.0, 0.0)),
        LineEntity("22222222-2222-4222-8222-222222222222", (0.0, 0.0), (0.0, 20.0)),
        CircleEntity("33333333-3333-4333-8333-333333333333", (50.0, 50.0), 10.0),
    )
    draft.canvas.replace_draft_entities(entities)
    tool = {"length": "aligned", "distance": "aligned"}.get(kind, kind)
    draft.dimensions.driving_check.setChecked(driving)
    draft.dimensions.buttons[tool].click()
    if kind in {"radius", "diameter"}:
        _click_dimension(draft, (60, 50))
    elif kind == "angle":
        _click_dimension(draft, (15, 0))
        _click_dimension(draft, (0, 10))
    else:
        _click_dimension(draft, (0, 0))
        _click_dimension(draft, (30, 0))
    _click_dimension(draft, (20, -15))
    if driving:
        draft.dimensions.driving_check.setChecked(True)
        draft.dimensions.value_editor.setValue(target)
        draft.dimensions.apply_button.click()
        if draft.dimensions.candidate is not None:
            draft.dimensions.apply_button.click()  # explicit branch-change acknowledgement
    constraint = draft.canvas.constraints[-1]
    assert constraint.kind == ("distance" if kind == "length" else kind)
    assert constraint.value == pytest.approx(target if driving else measured)
    assert constraint.driving == driving
    if not driving:
        assert tuple(draft.canvas.entities) == entities
    assert (
        draft.canvas.dimension_layout(
            constraint, {entity.entity_id: entity for entity in draft.canvas.entities}
        )
        is not None
    )


def test_driven_drawing_commits_saves_and_replays(qtbot: QtBot, tmp_path: Path) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.bind_document(loaded)
    window.act_view_2d.trigger()
    draft = window.active_sketch_dialog()
    assert draft is not None
    for point in ((0.0, 0.0), (30.0, 0.0)):
        draft.canvas.add_coordinate_point(point)
    draft.canvas.end_line_chain()
    _drive_line(draft, 45.0)
    assert not loaded.document.commands
    draft.finish_button.click()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 1 and not unit.is_busy, timeout=10000)
    next_draft = window.active_sketch_dialog()
    assert next_draft is not None and next_draft is not draft
    assert not next_draft.canvas.can_undo
    assert next_draft.canvas.background_constraints[-1].value == pytest.approx(45.0)

    _edit_dimension(next_draft, next_draft.canvas.background_constraints[-1].constraint_id)
    next_draft.dimensions.value_editor.setValue(55.0)
    qtbot.waitUntil(next_draft.dimensions.apply_button.isEnabled, timeout=10000)
    assert len(loaded.document.commands) == 1
    assert next_draft.canvas.dimension_preview is not None
    next_draft.dimensions.apply_button.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=10000)
    assert next_draft.canvas.background_constraints[-1].value == pytest.approx(55.0)
    window.act_undo.trigger()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 1 and not unit.is_busy, timeout=10000)
    assert next_draft.canvas.background_constraints[-1].value == pytest.approx(45.0)
    window.act_redo.trigger()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=10000)
    saved = services.kernel.sketches[0]
    path = tmp_path / "dimensions.mc.json"
    save_document(loaded.document, path)
    next_draft.reject()
    reopened = open_app_document(services, path)
    assert reopened.document.document_type == "drawing2d"
    assert services.kernel.sketches[0] == saved
    window.close()


def test_three_dimensional_undo_does_not_edit_hidden_draft(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute(
        "feature.box", {"size_x": 20.0, "size_y": 10.0, "size_z": 5.0}, confirmed_by="local"
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.act_view_2d.trigger()
    draft = window.active_sketch_dialog()
    assert draft is not None
    for point in ((0.0, 0.0), (30.0, 0.0)):
        draft.canvas.add_coordinate_point(point)
    before = tuple(draft.canvas.entities)
    window.act_view_3d.trigger()
    window.act_undo.trigger()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert tuple(draft.canvas.entities) == before
    assert len(loaded.document.commands) == 0
    window.act_redo.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert len(loaded.document.commands) == 1
    assert tuple(draft.canvas.entities) == before
    window.act_view_2d.trigger()
    draft.reject()
    window.close()


def test_explicit_coordinate_fields_bypass_origin_grid_and_inference(qtbot: QtBot) -> None:
    draft = SketchEditorDialog(continuous_lines=True)
    qtbot.addWidget(draft)
    draft.grid_snap_check.setChecked(True)
    for u, v in ((1.0, 1.0), (31.0, 1.2)):
        draft.u_field.setValue(u)
        draft.v_field.setValue(v)
        draft.coordinate_add_button.click()
    line = draft.canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.start_mm == (1.0, 1.0)
    assert line.end_mm == (31.0, 1.2)


def test_preview_uses_committed_sketch_layer_table(qtbot: QtBot) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraintSolveResult
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    draft = SketchEditorDialog()
    qtbot.addWidget(draft)
    draft.show()
    line = LineEntity(
        "11111111-1111-4111-8111-111111111111", (0.0, 0.0), (30.0, 0.0), layer_name="轮廓"
    )
    sketch = Sketch(
        "33333333-3333-4333-8333-333333333333",
        WorkPlaneFrame.xy(),
        (line,),
        layers=SketchLayerTable().add(SketchLayer("轮廓")),
    )
    draft.set_context_sketches((sketch,))
    draft.show_dimension_preview(SketchConstraintSolveResult("success", sketch, 3))
    assert not draft.canvas.grab().isNull()


def test_rectangle_length_defaults_to_edge_reference(qtbot: QtBot) -> None:
    from mycad.core.sketch import RectangleEntity

    services = build_app(discoverers=())
    draft = SketchEditorDialog(
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(draft)
    draft.canvas.replace_draft_entities(
        (RectangleEntity("11111111-1111-4111-8111-111111111111", (0.0, 0.0), (30.0, 20.0)),)
    )
    draft.show()
    _drive_line(draft, 40.0)
    rectangle = draft.canvas.entities[0]
    assert isinstance(rectangle, RectangleEntity)
    assert abs(rectangle.opposite_corner_mm[0] - rectangle.first_corner_mm[0]) == pytest.approx(
        40.0
    )
