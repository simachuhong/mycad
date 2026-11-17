# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The sketch editor keeps drawing in a disposable draft until Finish."""

from __future__ import annotations

import math
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    Sketch,
    SketchSupportFace,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import SketchLayer, SketchLayerTable
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog, SketchLayerManagerDialog


def test_sketch_editor_draws_line_on_selected_non_xy_plane(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    dialog.plane_combo.setCurrentText("XZ")
    dialog.tool_combo.setCurrentText("直线")
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    first = canvas.local_to_screen((0.0, 0.0))
    second = canvas.local_to_screen((20.0, 10.0))

    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=first)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=second)

    assert len(canvas.entities) == 1
    entity = canvas.entities[0]
    assert isinstance(entity, LineEntity)
    assert entity.start_mm == pytest.approx((0.0, 0.0), abs=0.15)
    assert entity.end_mm == pytest.approx((20.0, 10.0), abs=0.15)
    assert dialog.current_frame() == WorkPlaneFrame.xz()


def test_sketch_editor_keeps_selected_face_attachment_in_completed_draft(qtbot: QtBot) -> None:
    frame = WorkPlaneFrame.from_planar_face((4.0, 5.0, 6.0), (0.0, 1.0, 1.0))
    support = SketchSupportFace((4.0, 5.0, 6.0))
    dialog = SketchEditorDialog(attached_frame=frame, support_face=support)
    qtbot.addWidget(dialog)

    assert dialog.plane_combo.currentText() == "所选面"
    assert dialog.current_frame() == frame
    assert all(field.isReadOnly() for field in dialog.origin_fields.values())
    dialog.canvas.set_tool("直线")
    dialog.canvas.set_snapping_enabled(False)
    dialog.canvas.add_coordinate_point((0.0, 0.0))
    dialog.canvas.add_coordinate_point((10.0, 0.0))
    dialog.finish_sketch()

    assert dialog.result_sketch is not None
    assert dialog.result_sketch.support_face == support
    assert dialog.result_sketch.frame == frame


def test_selected_model_face_starts_and_replays_an_attached_sketch(
    qtbot: QtBot,
) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services)
    loaded.bus.execute(
        "feature.box",
        {"size_x": 40.0, "size_y": 30.0, "size_z": 8.0},
        confirmed_by="local",
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1100, 760)
    window.show()
    qtbot.waitExposed(window)
    window.bind_document(loaded)
    assert window.viewport is not None
    window.viewport.set_orientation("top")
    window.viewport.fit_view()
    window.viewport.set_selection_filter("face")
    assert window.viewport.pick_at(window.viewport.width() / 2, window.viewport.height() / 2)

    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    assert task.plane_combo.currentText() == "所选模型平面（查询）"
    task.lock_plane()
    task.select_tool("line")
    for point in ((0.0, 0.0, 4.0), (10.0, 0.0, 4.0)):
        screen = window.viewport.project_world_point(point)
        assert screen is not None
        QTest.mouseClick(
            window.viewport,
            Qt.MouseButton.LeftButton,
            pos=QPoint(round(screen[0]), round(screen[1])),
        )
    task.preview()
    assert task.confirm_button.isEnabled(), task.status_label.text()
    task.confirm()
    assert len(services.kernel.sketches) == 1, window.status_command.text()

    sketch = services.kernel.sketches[0]
    assert sketch.support_face is not None
    assert sketch.frame.origin_mm == pytest.approx((0.0, 0.0, 4.0), abs=1e-6)
    assert sketch.frame.normal == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)
    assert len(sketch.constraints) == 1
    assert sketch.constraints[0].kind == "horizontal"
    assert sketch.constraints[0].source == "inferred"
    assert loaded.document.commands[-1].id == "sketch.create"


@pytest.mark.parametrize("target_point", [(0.0, 20.0), (-20.0, 0.0)])
def test_draft_handle_drag_re_solves_constraints_and_is_one_undo_step(
    qtbot: QtBot, target_point: tuple[float, float]
) -> None:
    services = build_app(discoverers=())
    line = LineEntity("1b1b1b1b-1b1b-4b1b-8b1b-1b1b1b1b1b1b", (0.0, 0.0), (20.0, 0.0))
    fixed_id = "8d8d8d8d-8d8d-4d8d-8d8d-8d8d8d8d8d8d"
    length_id = "9e9e9e9e-9e9e-4e9e-8e9e-9e9e9e9e9e9e"
    constraints = (
        SketchConstraint(
            fixed_id,
            "fixed",
            (SketchGeometryReference(line.entity_id, "start"),),
        ),
        SketchConstraint(
            length_id,
            "length",
            (SketchGeometryReference(line.entity_id, "geometry"),),
            20.0,
            "mm",
        ),
    )
    preview = services.kernel.preview_sketch_drag(
        Sketch("0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a", WorkPlaneFrame.xy(), (line,), constraints),
        SketchGeometryReference(line.entity_id, "end"),
        (0.0, 20.0),
    )
    if preview.status == "unavailable":
        pytest.skip(preview.message or "PlaneGCS is unavailable")

    dialog = SketchEditorDialog(drag_preview=services.kernel.preview_sketch_drag)
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    dialog.tool_combo.setCurrentText("选择元素")
    dialog.canvas.entities = [line]
    dialog.canvas.constraints = list(constraints)
    qtbot.waitExposed(dialog)

    start = dialog.canvas.local_to_screen((20.0, 0.0))
    target = dialog.canvas.local_to_screen(target_point)
    QTest.mousePress(dialog.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(dialog.canvas, target, delay=100)
    if target_point[0] < 0:
        assert "方向变化" in dialog.status_label.text()
    QTest.mouseRelease(dialog.canvas, Qt.MouseButton.LeftButton, pos=target)
    if target_point[0] < 0:
        assert "方向变化" in dialog.status_label.text()

    solved = dialog.canvas.entities[0]
    assert isinstance(solved, LineEntity)
    assert solved.start_mm == pytest.approx((0.0, 0.0), abs=1e-6)
    assert math.hypot(solved.end_mm[0], solved.end_mm[1]) == pytest.approx(20.0, abs=1e-6)
    assert math.dist(solved.end_mm, target_point) <= 0.15
    assert tuple(dialog.canvas.constraints) == constraints
    assert dialog.undo_entity_button.isEnabled()
    dialog.undo_entity_button.click()
    assert dialog.canvas.entities == [line]
    assert dialog.canvas.constraints == list(constraints)
    dialog.redo_entity_button.click()
    assert dialog.canvas.entities == [solved]
    assert dialog.canvas.constraints == list(constraints)


def test_draft_curved_vertex_coincidence_drag_and_undo(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(1, 0))
    line = LineEntity(uuid4().hex, (10, 0), (20, 0))
    joined = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(polyline.entity_id, "vertex", 1),
            SketchGeometryReference(line.entity_id, "start"),
        ),
    )
    dialog = SketchEditorDialog(drag_preview=services.kernel.preview_sketch_drag)
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    dialog.tool_combo.setCurrentText("选择元素")
    dialog.canvas.set_snapping_enabled(False)
    dialog.canvas.entities = [polyline, line]
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    assert canvas.control_point_at((10, 0)) is None
    canvas.constraints = [joined]
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    QTest.mouseMove(canvas, canvas.local_to_screen((12, 3)), delay=100)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((12, 3)))
    moved, moved_line = canvas.entities
    assert isinstance(moved, PolylineEntity) and isinstance(moved_line, LineEntity)
    assert moved_line.start_mm == pytest.approx((12, 3), abs=0.15)
    assert moved.points_mm[1] == pytest.approx(moved_line.start_mm)
    assert moved.bulges == polyline.bulges
    dialog.undo_entity_button.click()
    assert canvas.entities == [polyline, line] and canvas.constraints == [joined]


def test_draft_curved_polyline_vertex_drag_preserves_bulges_and_undo(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)), bulges=(1.0, 0.0))
    dialog = SketchEditorDialog(drag_preview=services.kernel.preview_sketch_drag)
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    dialog.tool_combo.setCurrentText("选择元素")
    dialog.canvas.set_snapping_enabled(False)
    dialog.canvas.entities = [polyline]
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    start = canvas.local_to_screen((10, 0))
    target = canvas.local_to_screen((12, -3))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, target, delay=100)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
    moved = canvas.entities[0]
    assert isinstance(moved, PolylineEntity)
    assert moved.points_mm[1] == pytest.approx((12, -3), abs=0.15)
    assert moved.bulges == polyline.bulges
    dialog.undo_entity_button.click()
    assert canvas.entities == [polyline]
    dialog.redo_entity_button.click()
    assert canvas.entities == [moved]


def test_finish_returns_one_sketch_and_cancel_discards_draft(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    dialog.tool_combo.setCurrentText("矩形")
    qtbot.waitExposed(dialog)
    first = dialog.canvas.local_to_screen((-10.0, -5.0))
    second = dialog.canvas.local_to_screen((10.0, 5.0))
    QTest.mouseClick(dialog.canvas, Qt.MouseButton.LeftButton, pos=first)
    QTest.mouseClick(dialog.canvas, Qt.MouseButton.LeftButton, pos=second)

    dialog.finish_button.click()

    assert dialog.result_sketch is not None
    assert len(dialog.result_sketch.entities) == 1
    assert dialog.result_sketch.frame == WorkPlaneFrame.xy()

    cancelled = SketchEditorDialog()
    qtbot.addWidget(cancelled)
    cancelled.show()
    cancelled.reject()
    assert cancelled.result_sketch is None


def test_auto_inference_keeps_near_horizontal_line_exact_and_persists_relation(
    qtbot: QtBot,
) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.canvas.set_snapping_enabled(False)
    dialog.canvas.add_coordinate_point((0.0, 0.0))
    dialog.canvas.add_coordinate_point((10.0, 0.4))

    assert len(dialog.canvas.entities) == 1
    line = dialog.canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.end_mm == pytest.approx((10.0, 0.0))
    assert len(dialog.canvas.constraints) == 1
    relation = dialog.canvas.constraints[0]
    assert relation.kind == "horizontal"
    assert relation.source == "inferred"
    assert relation.references == (SketchGeometryReference(line.entity_id, "geometry"),)

    dialog.finish_sketch()

    assert dialog.result_sketch is not None
    assert dialog.result_sketch.constraints == (relation,)


def test_draft_undo_restores_inferred_relation_and_geometry_together(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.canvas.set_snapping_enabled(False)
    dialog.canvas.add_coordinate_point((0.0, 0.0))
    dialog.canvas.add_coordinate_point((10.0, 0.2))

    assert dialog.canvas.constraints
    assert dialog.canvas.undo_last_operation()
    assert dialog.canvas.entities == []
    assert dialog.canvas.constraints == []


def test_auto_inference_can_be_disabled_for_exact_coordinate_input(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.auto_relation_check.setChecked(False)
    dialog.canvas.set_snapping_enabled(False)
    dialog.canvas.add_coordinate_point((0.0, 0.0))
    dialog.canvas.add_coordinate_point((10.0, 0.4))

    line = dialog.canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.end_mm == pytest.approx((10.0, 0.4))
    assert dialog.canvas.constraints == []


def test_rotating_an_inferred_line_drops_and_reports_invalid_relation(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.canvas.set_snapping_enabled(False)
    dialog.canvas.add_coordinate_point((0.0, 0.0))
    dialog.canvas.add_coordinate_point((10.0, 0.2))
    source = dialog.canvas.entities[0]
    assert isinstance(source, LineEntity)
    assert dialog.canvas.constraints

    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.canvas.set_tool("选择元素")
    QTest.mouseClick(
        dialog.canvas,
        Qt.MouseButton.LeftButton,
        pos=dialog.canvas.local_to_screen((5.0, 0.0)),
    )
    assert dialog.canvas.selected_entity_ids == {source.entity_id}
    dialog.angle_field.setValue(45.0)
    dialog.numeric_rotate_button.click()

    assert dialog.canvas.constraints == []
    assert "自动关系" in dialog.canvas.message


def test_layer_manager_styles_layer_and_editor_records_new_geometry_on_it(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    manager = SketchLayerManagerDialog(dialog.layer_table)
    qtbot.addWidget(dialog)
    qtbot.addWidget(manager)

    assert manager.add_layer("OUTLINE")
    manager.layer_combo.setCurrentText("OUTLINE")
    manager.set_color_rgb((210, 40, 55))
    manager.linetype_combo.setCurrentText("DASHED")
    manager.lineweight_combo.setCurrentIndex(manager.lineweight_combo.findData(0.35))
    manager.accept()
    dialog.layer_table = manager.layer_table
    dialog.canvas.set_layer_table(manager.layer_table, "0")
    dialog.layer_combo.addItem("OUTLINE")
    dialog.layer_combo.setCurrentText("OUTLINE")
    dialog.canvas.set_tool("直线")
    dialog.canvas.set_snapping_enabled(False)
    dialog.canvas.add_coordinate_point((0.0, 0.0))
    dialog.canvas.add_coordinate_point((10.0, 0.0))
    dialog.finish_sketch()

    assert dialog.result_sketch is not None
    assert dialog.result_sketch.layers.get("OUTLINE") == SketchLayer(
        "OUTLINE",
        color_rgb=(210, 40, 55),
        linetype="DASHED",
        lineweight_mm=0.35,
    )
    assert dialog.result_sketch.entities[0].layer_name == "OUTLINE"


def test_layer_and_geometry_history_restores_style_references_and_active_layer(
    qtbot: QtBot,
) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    initial = dialog.layer_table
    dialog.request_layer_update(initial.add(SketchLayer("OUTLINE", color_rgb=(210, 40, 55))), "DIM")
    dialog.layer_combo.setCurrentText("OUTLINE")
    layers = dialog.layer_table
    for point in ((0.0, 0.0), (10.0, 0.0)):
        dialog.canvas.add_coordinate_point(point)
    entities = tuple(dialog.canvas.entities)
    assert entities[0].layer_name == "OUTLINE"
    dialog.undo_entity_button.click()
    assert dialog.canvas.entities == []
    assert dialog.layer_table == layers
    dialog.undo_entity_button.click()
    assert dialog.layer_table == initial
    assert dialog.layer_combo.currentText() == "0"
    assert dialog.layer_combo.findText("OUTLINE") == -1
    dialog.redo_entity_button.click()
    assert dialog.layer_table == layers
    assert dialog.layer_combo.currentText() == "OUTLINE"
    dialog.redo_entity_button.click()
    assert tuple(dialog.canvas.entities) == entities
    dialog.finish_sketch()
    assert dialog.result_sketch is not None
    assert dialog.result_sketch.layers == layers


def test_hidden_layer_is_not_selectable_or_a_snap_source(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    hidden = SketchLayer("HIDDEN", visible=False)
    dialog.layer_table = dialog.layer_table.add(hidden)
    dialog.canvas.set_layer_table(dialog.layer_table, "0")
    hidden_line = LineEntity(uuid4().hex, (2.0, 3.0), (12.0, 3.0), layer_name="HIDDEN")
    dialog.canvas.entities.append(hidden_line)

    dialog.canvas.set_tool("选择元素")
    QTest.mouseClick(
        dialog.canvas,
        Qt.MouseButton.LeftButton,
        pos=dialog.canvas.local_to_screen((7.0, 3.0)),
    )
    assert dialog.canvas.selected_entity_ids == set()
    dialog.canvas.set_tool("直线")
    dialog.canvas.add_coordinate_point((2.1, 3.1))
    dialog.canvas.add_coordinate_point((20.0, 3.1))
    created = dialog.canvas.entities[-1]
    assert isinstance(created, LineEntity)
    assert created.start_mm == pytest.approx((2.1, 3.1))


def test_locked_layer_rejects_draft_transform_without_mutation(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    locked = SketchLayer("LOCKED", locked=True)
    dialog.layer_table = dialog.layer_table.add(locked)
    dialog.canvas.set_layer_table(dialog.layer_table, "0")
    line = LineEntity(uuid4().hex, (2.0, 3.0), (12.0, 3.0), layer_name="LOCKED")
    dialog.canvas.entities.append(line)
    dialog.canvas.set_tool("选择元素")
    QTest.mouseClick(
        dialog.canvas,
        Qt.MouseButton.LeftButton,
        pos=dialog.canvas.local_to_screen((7.0, 3.0)),
    )

    dialog.transform_buttons["move"].click()

    assert dialog.canvas.entities == [line]
    assert "已锁定图层" in dialog.status_label.text()


def test_layer_manager_cannot_delete_layer_used_by_draft_entity(qtbot: QtBot) -> None:
    layers = SketchLayerTable().add(SketchLayer("USED"))
    manager = SketchLayerManagerDialog(layers, used_names=("USED",))
    qtbot.addWidget(manager)
    manager.layer_combo.setCurrentText("USED")

    manager.remove_button.click()

    assert manager.layer_table.get("USED").name == "USED"
    assert "used" in manager.status_label.text().lower()


def test_sketch_editor_exposes_required_draw_tools_and_coordinate_entry(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)

    assert tuple(dialog.tool_combo.itemText(i) for i in range(dialog.tool_combo.count())) == (
        "直线",
        "选择元素",
        "多段线",
        "圆",
        "圆弧",
        "矩形",
        "多边形",
        "样条曲线",
        "修剪",
        "延伸",
        "分割",
    )
    assert dialog.coordinate_add_button.text() == "按坐标点"
    assert dialog.construction_check.text() == "构造几何"


def test_drawing_circular_array_keeps_original_and_undoes(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(1100, 760)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.canvas.set_snapping_enabled(False)
    dialog.canvas.set_tool("圆")
    dialog.canvas.add_coordinate_point((25.0, 0.0))
    dialog.canvas.add_coordinate_point((28.0, 0.0))
    original = dialog.canvas.entities[0]
    dialog.tool_combo.setCurrentText("选择元素")
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((28.0, 0.0))
    )
    assert dialog.canvas.selected_entity_ids == {original.entity_id}
    dialog.center_u_field.setValue(0.0)
    dialog.center_v_field.setValue(0.0)
    dialog.pattern_angle_field.setValue(360.0)
    dialog.count_field.setValue(4)
    dialog.transform_buttons["circular_array"].click()
    circles = dialog.canvas.entities
    assert len(circles) == 4
    typed_circles = [circle for circle in circles if isinstance(circle, CircleEntity)]
    assert len(typed_circles) == 4
    assert {
        (round(circle.center_mm[0]), round(circle.center_mm[1])) for circle in typed_circles
    } == {
        (25, 0),
        (0, 25),
        (-25, 0),
        (0, -25),
    }
    assert len({circle.entity_id for circle in circles}) == 4
    dialog.undo_entity_button.click()
    assert tuple(dialog.canvas.entities) == (original,)


def test_sketch_selection_supports_move_copy_and_linear_array_in_the_draft(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(1100, 760)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.canvas.set_snapping_enabled(False)
    dialog.canvas.set_tool("直线")
    dialog.canvas.add_coordinate_point((0.0, 0.0))
    dialog.canvas.add_coordinate_point((10.0, 0.0))
    original_id = dialog.canvas.entities[0].entity_id

    dialog.tool_combo.setCurrentText("选择元素")
    middle = dialog.canvas.local_to_screen((5.0, 0.0))
    QTest.mouseClick(dialog.canvas, Qt.MouseButton.LeftButton, pos=middle)
    assert dialog.canvas.selected_entity_ids == {original_id}

    dialog.delta_u_field.setValue(2.0)
    dialog.delta_v_field.setValue(1.0)
    dialog.numeric_move_button.click()
    moved = dialog.canvas.entities[0]
    assert isinstance(moved, LineEntity)
    assert moved.entity_id == original_id
    assert moved.start_mm == (2.0, 1.0)
    assert moved.end_mm == (12.0, 1.0)

    dialog.numeric_copy_button.click()
    assert len(dialog.canvas.entities) == 2
    copied = dialog.canvas.entities[1]
    assert isinstance(copied, LineEntity)
    assert copied.entity_id != original_id
    assert copied.start_mm == (4.0, 2.0)
    assert len(dialog.canvas.selected_entity_ids) == 2

    dialog.delta_u_field.setValue(0.0)
    dialog.delta_v_field.setValue(5.0)
    dialog.count_field.setValue(3)
    dialog.transform_buttons["linear_array"].click()
    assert len(dialog.canvas.entities) == 6
    assert len({entity.entity_id for entity in dialog.canvas.entities}) == 6
    assert "数量包含原始元素" in dialog.status_label.text()
    array_entities = tuple(dialog.canvas.entities)
    array_constraints = tuple(dialog.canvas.constraints)
    array_selection = set(dialog.canvas.selected_entity_ids)

    dialog.undo_entity_button.click()
    assert len(dialog.canvas.entities) == 2
    dialog.undo_entity_button.click()
    assert len(dialog.canvas.entities) == 1
    restored = dialog.canvas.entities[0]
    assert isinstance(restored, LineEntity)
    assert restored.entity_id == original_id
    assert restored.start_mm == (2.0, 1.0)
    dialog.undo_entity_button.click()
    moved_back = dialog.canvas.entities[0]
    assert isinstance(moved_back, LineEntity)
    assert moved_back.start_mm == (0.0, 0.0)
    for _ in range(3):
        assert dialog.redo_entity_button.isEnabled()
        dialog.redo_entity_button.click()
    assert tuple(dialog.canvas.entities) == array_entities
    assert tuple(dialog.canvas.constraints) == array_constraints
    assert dialog.canvas.selected_entity_ids == array_selection
    assert not dialog.redo_entity_button.isEnabled()


def test_draft_redo_survives_cancelled_input_but_new_edit_discards_branch(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    for point in ((0.0, 0.0), (10.0, 0.0)):
        canvas.add_coordinate_point(point)
    original = tuple(canvas.entities)
    relations = tuple(canvas.constraints)
    dialog.undo_entity_button.click()
    assert canvas.can_redo
    canvas.add_coordinate_point((20.0, 0.0))
    assert not canvas.can_redo
    assert not canvas.redo_last_operation()
    assert not dialog.redo_entity_button.isEnabled()
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.can_redo
    QTest.keyClick(
        canvas,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert tuple(canvas.entities) == original
    assert tuple(canvas.constraints) == relations
    QTest.keyClick(canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert canvas.entities == []
    for point in ((20.0, 0.0), (30.0, 0.0)):
        canvas.add_coordinate_point(point)
    assert not canvas.can_redo
    assert not canvas.redo_last_operation()
    assert canvas.entities[0].entity_id != original[0].entity_id


def test_sketch_offset_creates_a_parallel_copy_and_can_be_undone(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.canvas.set_snapping_enabled(False)
    dialog.canvas.set_tool("直线")
    dialog.canvas.add_coordinate_point((0.0, 0.0))
    dialog.canvas.add_coordinate_point((10.0, 0.0))
    original_id = dialog.canvas.entities[0].entity_id
    dialog.tool_combo.setCurrentText("选择元素")
    QTest.mouseClick(
        dialog.canvas,
        Qt.MouseButton.LeftButton,
        pos=dialog.canvas.local_to_screen((5.0, 0.0)),
    )

    dialog.offset_distance_field.setValue(2.0)
    dialog.transform_buttons["offset"].click()

    assert len(dialog.canvas.entities) == 2
    original, offset = dialog.canvas.entities
    assert isinstance(original, LineEntity)
    assert isinstance(offset, LineEntity)
    assert original.entity_id == original_id
    assert offset.entity_id != original_id
    assert offset.start_mm == (0.0, 2.0)
    assert offset.end_mm == (10.0, 2.0)
    dialog.undo_entity_button.click()
    assert dialog.canvas.entities == [original]


def test_trim_tool_removes_clicked_line_interval_and_keeps_first_fragment_identity(
    qtbot: QtBot,
) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("直线")
    for point in ((0.0, 0.0), (20.0, 0.0), (10.0, -5.0), (10.0, 5.0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    original_id = canvas.entities[0].entity_id

    dialog.tool_combo.setCurrentText("修剪")
    trim_position = canvas.local_to_screen((15.0, 0.0))
    QTest.mouseMove(canvas, QPoint(5, 5))
    QTest.mouseMove(canvas, trim_position)
    qtbot.waitUntil(lambda: canvas.hovered_trim_target_id == original_id, timeout=1000)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=trim_position)

    assert len(canvas.entities) == 2
    assert canvas.hovered_trim_target_id is None
    trimmed = canvas.entities[0]
    assert isinstance(trimmed, LineEntity)
    assert trimmed.entity_id == original_id
    assert trimmed.start_mm == pytest.approx((0.0, 0.0), abs=0.15)
    assert trimmed.end_mm == pytest.approx((10.0, 0.0), abs=0.15)
    retained_cutter = canvas.entities[1]
    assert isinstance(retained_cutter, LineEntity)
    assert retained_cutter.start_mm == pytest.approx((10.0, -5.0), abs=0.15)
    assert dialog.status_label.text().startswith("修剪完成")


def test_trim_hover_preview_is_nonmutating_and_shift_previews_extension(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("直线")
    for point in (
        (0.0, 0.0),
        (20.0, 0.0),
        (5.0, -5.0),
        (5.0, 5.0),
        (10.0, -5.0),
        (10.0, 5.0),
        (25.0, -5.0),
        (25.0, 5.0),
    ):
        canvas.add_coordinate_point(point)
    original = tuple(canvas.entities)
    original_id = canvas.entities[0].entity_id
    dialog.tool_combo.setCurrentText("修剪")

    trim_position = canvas.local_to_screen((7.5, 0.0))
    QTest.mouseMove(canvas, trim_position)
    assert canvas.previewed_line_edit_original == original[0]
    preview_segments = tuple(
        entity for entity in canvas.previewed_line_edit_entities if isinstance(entity, LineEntity)
    )
    assert len(preview_segments) == 2
    assert tuple(canvas.entities) == original

    endpoint_position = canvas.local_to_screen((20.0, 0.0))
    QTest.mouseMove(canvas, endpoint_position)
    canvas.setFocus()
    QTest.keyPress(canvas, Qt.Key.Key_Shift)
    assert canvas.previewed_line_edit_original == original[0]
    extension_preview = canvas.previewed_line_edit_entities[0]
    assert isinstance(extension_preview, LineEntity)
    assert extension_preview.end_mm == pytest.approx((25.0, 0.0), abs=0.15)
    assert tuple(canvas.entities) == original

    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        pos=endpoint_position,
    )
    QTest.keyRelease(canvas, Qt.Key.Key_Shift)
    extended = canvas.entities[0]
    assert isinstance(extended, LineEntity)
    assert extended.entity_id == original_id
    assert extended.end_mm == pytest.approx((25.0, 0.0), abs=0.15)
    dialog.undo_entity_button.click()
    assert tuple(canvas.entities) == original


def test_drag_trim_across_multiple_sections_is_one_undo_step(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("直线")
    for point in (
        (0.0, 0.0),
        (20.0, 0.0),
        (5.0, -5.0),
        (5.0, 5.0),
        (10.0, -5.0),
        (10.0, 5.0),
        (15.0, -5.0),
        (15.0, 5.0),
    ):
        canvas.add_coordinate_point(point)
    original = tuple(canvas.entities)
    dialog.tool_combo.setCurrentText("修剪")
    start = canvas.local_to_screen((2.5, 0.0))
    end = canvas.local_to_screen((17.5, 0.0))

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, end)
    assert tuple(canvas.entities) != original
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)

    remaining_horizontal = tuple(
        entity
        for entity in canvas.entities
        if isinstance(entity, LineEntity)
        and entity.start_mm[1] == pytest.approx(0.0)
        and entity.end_mm[1] == pytest.approx(0.0)
    )
    assert not any(remaining_horizontal), (canvas.entities, canvas.message)
    trimmed = tuple(canvas.entities)
    dialog.undo_entity_button.click()
    assert tuple(canvas.entities) == original
    dialog.redo_entity_button.click()
    assert tuple(canvas.entities) == trimmed
    dialog.undo_entity_button.click()
    dialog.undo_entity_button.click()
    assert tuple(canvas.entities) == original[:-1]


def test_escape_cancels_in_progress_drag_trim_without_adding_undo_step(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("直线")
    for point in (
        (0.0, 0.0),
        (20.0, 0.0),
        (10.0, -5.0),
        (10.0, 5.0),
    ):
        canvas.add_coordinate_point(point)
    original = tuple(canvas.entities)
    original_constraints = tuple(canvas.constraints)
    for point in ((30.0, 0.0), (30.0, 10.0)):
        canvas.add_coordinate_point(point)
    future = tuple(canvas.entities)
    dialog.undo_entity_button.click()
    assert tuple(canvas.entities) == original
    assert dialog.redo_entity_button.isEnabled()
    dialog.tool_combo.setCurrentText("修剪")
    start = canvas.local_to_screen((5.0, 0.0))
    end = canvas.local_to_screen((15.0, 0.0))

    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    assert not dialog.undo_entity_button.isEnabled()
    assert not dialog.redo_entity_button.isEnabled()
    assert not canvas.redo_last_operation()
    QTest.mouseMove(canvas, end)
    assert tuple(canvas.entities) != original
    QTest.keyClick(canvas, Qt.Key.Key_Escape)

    assert tuple(canvas.entities) == original
    assert tuple(canvas.constraints) == original_constraints
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert tuple(canvas.entities) == original
    dialog.redo_entity_button.click()
    assert tuple(canvas.entities) == future
    dialog.undo_entity_button.click()
    dialog.undo_entity_button.click()
    assert tuple(canvas.entities) == original[:-1]


def test_trim_tool_trims_circle_against_line_intersections_and_undo_restores_circle(
    qtbot: QtBot,
) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(1000, 740)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("圆")
    canvas.add_coordinate_point((0.0, 0.0))
    canvas.add_coordinate_point((10.0, 0.0))
    circle_id = canvas.entities[0].entity_id
    canvas.set_tool("直线")
    for point in ((5.0, -10.0), (5.0, 10.0), (-5.0, -10.0), (-5.0, 10.0)):
        canvas.add_coordinate_point(point)

    dialog.tool_combo.setCurrentText("修剪")
    top = canvas.local_to_screen((0.0, 10.0))
    QTest.mouseMove(canvas, top)
    assert canvas.hovered_trim_target_id == circle_id
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=top)

    trimmed = canvas.entities[0]
    assert isinstance(trimmed, ArcEntity)
    assert trimmed.entity_id == circle_id
    assert trimmed.start_angle_deg == pytest.approx(120.0)
    assert trimmed.sweep_angle_deg == pytest.approx(300.0)
    dialog.undo_entity_button.click()
    restored = canvas.entities[0]
    assert isinstance(restored, CircleEntity)
    assert restored.entity_id == circle_id


def test_trim_tool_trims_open_polyline_segment_and_undo_restores_path(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("多段线")
    canvas.add_coordinate_point((0.0, 0.0))
    canvas.add_coordinate_point((20.0, 0.0))
    canvas.finish_polyline()
    canvas.set_tool("直线")
    for point in ((5.0, -5.0), (5.0, 5.0), (15.0, -5.0), (15.0, 5.0)):
        canvas.add_coordinate_point(point)
    original = canvas.entities[0]
    assert isinstance(original, PolylineEntity)

    dialog.tool_combo.setCurrentText("修剪")
    trim_position = canvas.local_to_screen((10.0, 0.0))
    QTest.mouseMove(canvas, canvas.local_to_screen((10.0, 3.0)))
    QTest.mouseMove(canvas, trim_position)
    assert canvas.hovered_trim_target_id == original.entity_id
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=trim_position)

    first, second = canvas.entities[:2]
    assert isinstance(first, PolylineEntity)
    assert isinstance(second, PolylineEntity)
    assert first.entity_id == original.entity_id
    assert first.points_mm[-1] == pytest.approx((5.0, 0.0), abs=0.15)
    assert second.points_mm[0] == pytest.approx((15.0, 0.0), abs=0.15)
    assert second.entity_id != original.entity_id
    assert dialog.status_label.text().startswith("修剪完成")

    dialog.undo_entity_button.click()
    assert canvas.entities[0] == original
    assert len(canvas.entities) == 3


def test_trim_tool_trims_open_polyline_endpoint_to_single_hit_and_undoes(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("多段线")
    canvas.add_coordinate_point((0.0, 0.0))
    canvas.add_coordinate_point((20.0, 0.0))
    canvas.finish_polyline()
    canvas.set_tool("直线")
    for point in ((5.0, -5.0), (5.0, 5.0)):
        canvas.add_coordinate_point(point)
    original = canvas.entities[0]
    assert isinstance(original, PolylineEntity)

    dialog.tool_combo.setCurrentText("修剪")
    trim_position = canvas.local_to_screen((2.0, 0.0))
    QTest.mouseMove(canvas, canvas.local_to_screen((2.0, 3.0)))
    QTest.mouseMove(canvas, trim_position)
    assert canvas.hovered_trim_target_id == original.entity_id
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=trim_position)

    trimmed = canvas.entities[0]
    assert isinstance(trimmed, PolylineEntity)
    assert trimmed.entity_id == original.entity_id
    assert trimmed.points_mm[0] == pytest.approx((5.0, 0.0), abs=0.15)
    assert trimmed.points_mm[-1] == pytest.approx((20.0, 0.0), abs=0.15)
    assert dialog.status_label.text().startswith("修剪完成")

    dialog.undo_entity_button.click()
    assert canvas.entities[0] == original
    assert len(canvas.entities) == 2


def test_split_tool_does_not_preselect_non_line_curves(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(1000, 740)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("圆")
    canvas.add_coordinate_point((0.0, 0.0))
    canvas.add_coordinate_point((10.0, 0.0))

    dialog.tool_combo.setCurrentText("分割")
    on_circle = canvas.local_to_screen((0.0, 10.0))
    QTest.mouseMove(canvas, on_circle)

    assert canvas.hovered_line_edit_target_id is None


def test_trim_tool_reports_missing_intersection_without_changing_draft(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("直线")
    canvas.add_coordinate_point((0.0, 0.0))
    canvas.add_coordinate_point((20.0, 0.0))
    before = tuple(canvas.entities)

    dialog.tool_combo.setCurrentText("修剪")
    canvas.add_coordinate_point((10.0, 0.0))

    assert tuple(canvas.entities) == before
    assert "无法修剪" in dialog.status_label.text()


def test_extend_tool_preselects_endpoint_and_extends_to_nearest_intersection(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("直线")
    for point in ((0.0, 0.0), (20.0, 0.0), (30.0, -5.0), (30.0, 5.0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    original_id = canvas.entities[0].entity_id

    dialog.tool_combo.setCurrentText("延伸")
    endpoint_position = canvas.local_to_screen((20.0, 0.0))
    QTest.mouseMove(canvas, endpoint_position)
    assert canvas.hovered_line_edit_target_id == original_id
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=endpoint_position)

    extended = canvas.entities[0]
    assert isinstance(extended, LineEntity)
    assert extended.entity_id == original_id
    assert extended.start_mm == pytest.approx((0.0, 0.0), abs=0.15)
    assert extended.end_mm == pytest.approx((30.0, 0.0), abs=0.15)
    assert dialog.status_label.text().startswith("已延伸")


def test_extend_tool_preselects_and_extends_arc_endpoint(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(1000, 740)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("圆弧")
    for point in ((0.0, 0.0), (10.0, 0.0), (0.0, 10.0)):
        canvas.add_coordinate_point(point)
    arc = canvas.entities[0]
    assert isinstance(arc, ArcEntity)
    arc_id = arc.entity_id
    canvas.set_tool("直线")
    for point in ((5.0, -10.0), (5.0, 10.0)):
        canvas.add_coordinate_point(point)

    dialog.tool_combo.setCurrentText("延伸")
    arc_start = canvas.local_to_screen((10.0, 0.0))
    QTest.mouseMove(canvas, arc_start)
    assert canvas.hovered_line_edit_target_id == arc_id
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=arc_start)

    extended = canvas.entities[0]
    assert isinstance(extended, ArcEntity)
    assert extended.entity_id == arc_id
    assert extended.start_angle_deg == pytest.approx(300.0)
    assert extended.sweep_angle_deg == pytest.approx(150.0)
    assert dialog.status_label.text().startswith("已延伸目标曲线")


def test_extend_tool_preselects_open_polyline_endpoint_and_undoes(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("多段线")
    for point in ((0.0, 0.0), (2.0, 0.0), (20.0, 0.0)):
        canvas.add_coordinate_point(point)
    canvas.finish_polyline()
    canvas.set_tool("直线")
    for point in ((25.0, -5.0), (25.0, 5.0), (30.0, -5.0), (30.0, 5.0)):
        canvas.add_coordinate_point(point)
    original = canvas.entities[0]
    assert isinstance(original, PolylineEntity)

    dialog.tool_combo.setCurrentText("延伸")
    endpoint_position = canvas.local_to_screen((20.0, 0.0))
    QTest.mouseMove(canvas, canvas.local_to_screen((20.0, 3.0)))
    QTest.mouseMove(canvas, endpoint_position)
    assert canvas.hovered_line_edit_target_id == original.entity_id
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=endpoint_position)

    extended = canvas.entities[0]
    assert isinstance(extended, PolylineEntity)
    assert extended.entity_id == original.entity_id
    assert extended.points_mm[0] == (0.0, 0.0)
    assert extended.points_mm[1] == (2.0, 0.0)
    assert extended.points_mm[2] == pytest.approx((25.0, 0.0), abs=0.15)
    assert dialog.status_label.text().startswith("已延伸")

    dialog.undo_entity_button.click()
    assert canvas.entities[0] == original
    assert len(canvas.entities) == 3


def test_split_tool_splits_clicked_line_at_nearest_intersection(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("直线")
    for point in (
        (0.0, 0.0),
        (20.0, 0.0),
        (5.0, -5.0),
        (5.0, 5.0),
        (15.0, -5.0),
        (15.0, 5.0),
    ):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    original_id = canvas.entities[0].entity_id

    dialog.tool_combo.setCurrentText("分割")
    cursor_position = canvas.local_to_screen((13.0, 0.0))
    QTest.mouseMove(canvas, cursor_position)
    assert canvas.hovered_line_edit_target_id == original_id
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=cursor_position)

    first = canvas.entities[0]
    second = canvas.entities[1]
    assert isinstance(first, LineEntity)
    assert isinstance(second, LineEntity)
    assert first.entity_id == original_id
    assert first.end_mm == pytest.approx((15.0, 0.0), abs=0.15)
    assert second.start_mm == pytest.approx((15.0, 0.0), abs=0.15)
    assert second.entity_id != original_id
    assert dialog.status_label.text().startswith("已分割目标图元")


def test_splitting_visible_geometry_keeps_hidden_layer_order_stable(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("直线")
    for point in (
        (0.0, 0.0),
        (20.0, 0.0),
        (5.0, -5.0),
        (5.0, 5.0),
        (15.0, -5.0),
        (15.0, 5.0),
    ):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    hidden = SketchLayer("HIDDEN", visible=False)
    dialog.layer_table = dialog.layer_table.add(hidden)
    canvas.set_layer_table(dialog.layer_table, "0")
    hidden_line = LineEntity(uuid4().hex, (30.0, 0.0), (40.0, 0.0), layer_name="HIDDEN")
    canvas.entities.insert(1, hidden_line)
    original_id = canvas.entities[0].entity_id

    dialog.tool_combo.setCurrentText("分割")
    cursor_position = canvas.local_to_screen((13.0, 0.0))
    QTest.mouseMove(canvas, cursor_position)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=cursor_position)

    assert canvas.entities[0].entity_id == original_id
    assert canvas.entities[2] == hidden_line
    assert len(canvas.entities) == 5


def test_split_tool_splits_open_polyline_segment_and_undo_restores_original(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("多段线")
    canvas.add_coordinate_point((0.0, 0.0))
    canvas.add_coordinate_point((20.0, 0.0))
    canvas.finish_polyline()
    canvas.set_tool("直线")
    for point in ((5.0, -5.0), (5.0, 5.0), (15.0, -5.0), (15.0, 5.0)):
        canvas.add_coordinate_point(point)
    original = canvas.entities[0]
    assert isinstance(original, PolylineEntity)

    dialog.tool_combo.setCurrentText("分割")
    cursor_position = canvas.local_to_screen((13.0, 0.0))
    QTest.mouseMove(canvas, canvas.local_to_screen((13.0, 3.0)))
    QTest.mouseMove(canvas, cursor_position)
    assert canvas.hovered_line_edit_target_id == original.entity_id
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=cursor_position)

    first, second = canvas.entities[:2]
    assert isinstance(first, PolylineEntity)
    assert isinstance(second, PolylineEntity)
    assert first.entity_id == original.entity_id
    assert first.points_mm[-1] == pytest.approx((15.0, 0.0), abs=0.15)
    assert second.points_mm[0] == pytest.approx((15.0, 0.0), abs=0.15)
    assert second.entity_id != original.entity_id
    assert dialog.status_label.text().startswith("已分割目标图元")

    dialog.undo_entity_button.click()
    assert canvas.entities[0] == original
    assert len(canvas.entities) == 3


def test_orthogonal_input_locks_line_and_polyline_and_preserves_snaps(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    orthogonal = next(
        (check for check in dialog.findChildren(QCheckBox) if check.text() == "正交"),
        None,
    )
    assert orthogonal is not None
    orthogonal.setChecked(True)
    canvas = dialog.canvas
    canvas.set_tool("直线")
    canvas.add_coordinate_point((0.0, 0.0))
    canvas.add_coordinate_point((12.0, 5.0))
    line = canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.end_mm == pytest.approx((12.0, 0.0))

    canvas.set_tool("多段线")
    canvas.add_coordinate_point((20.0, 20.0))
    canvas.add_coordinate_point((25.0, 22.0))
    canvas.add_coordinate_point((27.0, 30.0))
    canvas.finish_polyline()
    polyline = canvas.entities[1]
    assert isinstance(polyline, PolylineEntity)
    assert polyline.points_mm == ((20.0, 20.0), (25.0, 20.0), (25.0, 30.0))

    canvas.set_snapping_enabled(False)
    canvas.set_tool("直线")
    canvas.add_coordinate_point((31.0, 7.0))
    canvas.set_snapping_enabled(True)
    canvas.add_coordinate_point((25.1, 20.1))
    snapped_line = canvas.entities[2]
    assert isinstance(snapped_line, LineEntity)
    assert snapped_line.end_mm == pytest.approx((25.0, 20.0))
    assert canvas.current_snap_kind == "端点"


def test_orthogonal_mouse_input_matches_the_coordinate_tool(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    dialog.tool_combo.setCurrentText("直线")
    dialog.orthogonal_check.setChecked(True)
    qtbot.waitExposed(dialog)
    first = dialog.canvas.local_to_screen((0.0, 0.0))
    second = dialog.canvas.local_to_screen((20.0, 10.0))

    QTest.mouseClick(dialog.canvas, Qt.MouseButton.LeftButton, pos=first)
    QTest.mouseClick(dialog.canvas, Qt.MouseButton.LeftButton, pos=second)

    line = dialog.canvas.entities[0]
    assert isinstance(line, LineEntity)
    assert line.end_mm == pytest.approx((20.0, 0.0), abs=0.15)


def test_perpendicular_capture_uses_active_line_anchor(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("直线")
    canvas.add_coordinate_point((0.0, 0.0))
    canvas.add_coordinate_point((20.0, 0.0))
    canvas.add_coordinate_point((8.0, 4.0))
    canvas.set_snapping_enabled(True)
    canvas.add_coordinate_point((8.2, 0.2))

    line = canvas.entities[1]
    assert isinstance(line, LineEntity)
    assert line.end_mm == pytest.approx((8.0, 0.0))
    assert canvas.current_snap_kind == "垂足"


def test_tangent_capture_uses_active_line_anchor(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    canvas.set_tool("圆")
    canvas.add_coordinate_point((0.0, 0.0))
    canvas.add_coordinate_point((5.0, 0.0))
    canvas.set_tool("直线")
    canvas.add_coordinate_point((10.0, 0.0))
    canvas.set_snapping_enabled(True)
    canvas.add_coordinate_point((2.5, 4.33))

    line = canvas.entities[1]
    assert isinstance(line, LineEntity)
    assert line.end_mm == pytest.approx((2.5, 4.3301270189), abs=1e-5)
    assert canvas.current_snap_kind == "切点"


def test_circle_radius_mouse_snaps_to_tangent_of_existing_line(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    canvas = dialog.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    assert canvas.set_tool("圆")
    center_pos = canvas.local_to_screen((6, 8))
    center = canvas.screen_to_local(QPointF(center_pos))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=center_pos)
    QTest.mouseMove(canvas, canvas.local_to_screen((6.4, 0.4)))
    assert canvas.current_snap_kind == "切点"
    assert canvas._cursor == pytest.approx((center[0], 0))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((6.4, 0.4)))
    circle = canvas.entities[-1]
    assert isinstance(circle, CircleEntity)
    assert circle.center_mm == pytest.approx(center)
    assert circle.radius_mm == pytest.approx(abs(center[1]))


def test_circle_radius_tangent_does_not_use_line_extension(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (5, 0)),))
    assert canvas.set_tool("圆")
    canvas.add_coordinate_point((10, 8), exact_point=True)
    assert canvas._snapped((10, 0))[1] != "切点"


def test_circle_radius_snaps_to_diagonal_line_tangent(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (12, 12)),))
    assert canvas.set_tool("圆")
    canvas.add_coordinate_point((8, 2), exact_point=True)
    canvas.add_coordinate_point((5.1, 5.2))
    circle = canvas.entities[-1]
    assert isinstance(circle, CircleEntity)
    assert circle.radius_mm == pytest.approx(math.sqrt(18))
    assert canvas.current_snap_kind == "切点"


def test_circle_tangent_snap_respects_disabled_snapping(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (20, 0)),))
    assert canvas.set_tool("圆")
    canvas.add_coordinate_point((6, 8), exact_point=True)
    canvas.set_snapping_enabled(False)
    point, kind = canvas._snapped((6.4, 0.4))
    assert point == pytest.approx((6.4, 0.4))
    assert kind != "切点"


def test_circle_arc_closed_polyline_and_construction_entities(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    canvas.set_tool("圆")
    canvas.set_construction(True)
    canvas.add_coordinate_point((100.0, 100.0))
    canvas.add_coordinate_point((110.0, 100.0))
    canvas.set_tool("圆弧")
    canvas.add_coordinate_point((130.0, 100.0))
    canvas.add_coordinate_point((140.0, 100.0))
    canvas.add_coordinate_point((130.0, 110.0))
    canvas.set_tool("多段线")
    canvas.set_construction(False)
    canvas.set_closed_polyline(True)
    for point in ((0.0, 0.0), (10.0, 0.0), (0.0, 10.0), (0.0, 0.0)):
        canvas.add_coordinate_point(point)
    canvas.finish_polyline()

    assert isinstance(canvas.entities[0], CircleEntity)
    assert canvas.entities[0].construction
    assert isinstance(canvas.entities[1], ArcEntity)
    assert canvas.entities[1].sweep_angle_deg == pytest.approx(90.0)
    assert isinstance(canvas.entities[2], PolylineEntity)
    assert canvas.entities[2].closed
    assert len(canvas.entities[2].points_mm) == 3


def test_sketch_snaps_to_circle_center_and_line_intersections(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    canvas.set_tool("圆")
    canvas.add_coordinate_point((100.0, 100.0))
    canvas.add_coordinate_point((110.0, 100.0))
    canvas.set_tool("直线")
    canvas.add_coordinate_point((100.2, 100.1))
    assert canvas.current_snap_kind == "圆心"
    canvas.add_coordinate_point((120.0, 120.0))
    assert isinstance(canvas.entities[-1], LineEntity)
    assert canvas.entities[-1].start_mm == (100.0, 100.0)
    canvas.set_tool("直线")
    canvas.add_coordinate_point((0.0, 0.0))
    canvas.add_coordinate_point((50.0, 10.0))
    canvas.set_tool("直线")
    canvas.add_coordinate_point((20.0, -10.0))
    canvas.add_coordinate_point((20.0, 30.0))
    canvas.set_tool("直线")
    canvas.add_coordinate_point((20.1, 4.2))

    assert canvas.current_snap_kind == "交点"


def test_endpoint_snap_has_stable_priority_over_midpoint_at_same_location(
    qtbot: QtBot,
) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.canvas.entities.extend(
        (
            LineEntity("11111111111141118111111111111111", (0.0, 0.0), (10.0, 0.0)),
            LineEntity("22222222222242228222222222222222", (5.0, 0.0), (5.0, 5.0)),
        )
    )
    dialog.canvas.set_tool("直线")

    dialog.canvas.add_coordinate_point((5.0, 0.0))

    assert dialog.canvas.current_snap_kind == "端点"


def test_sketch_editor_can_temporarily_disable_point_snapping(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    snap_checkbox = next(
        (checkbox for checkbox in dialog.findChildren(QCheckBox) if checkbox.text() == "捕捉"),
        None,
    )
    assert snap_checkbox is not None
    snap_checkbox.setChecked(False)
    dialog.canvas.entities.append(
        LineEntity("33333333333343338333333333333333", (0.0, 0.0), (10.0, 0.0))
    )
    dialog.canvas.set_tool("直线")

    dialog.canvas.add_coordinate_point((0.1, 0.1))
    dialog.canvas.add_coordinate_point((10.1, 10.0))

    entity = dialog.canvas.entities[-1]
    assert isinstance(entity, LineEntity)
    assert entity.start_mm == pytest.approx((0.1, 0.1), abs=1e-9)
    assert dialog.canvas.current_snap_kind == ""


def test_sketch_arc_can_be_drawn_clockwise(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.arc_direction_combo.setCurrentText("顺时针")
    dialog.canvas.set_tool("圆弧")
    for point in ((0.0, 0.0), (10.0, 0.0), (0.0, -10.0)):
        dialog.canvas.add_coordinate_point(point)

    assert isinstance(dialog.canvas.entities[0], ArcEntity)
    assert dialog.canvas.entities[0].sweep_angle_deg == pytest.approx(-90.0)


def test_sketch_snaps_to_line_circle_intersection(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    canvas.set_tool("圆")
    canvas.add_coordinate_point((0.0, 0.0))
    canvas.add_coordinate_point((10.0, 0.0))
    canvas.set_tool("直线")
    canvas.add_coordinate_point((-15.0, 0.0))
    canvas.add_coordinate_point((15.0, 0.0))
    canvas.set_tool("直线")
    canvas.add_coordinate_point((9.9, 0.0))

    assert canvas.current_snap_kind == "交点"


def test_sketch_snaps_to_circle_circle_intersection(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    canvas.set_tool("圆")
    canvas.add_coordinate_point((0.0, 0.0))
    canvas.add_coordinate_point((10.0, 0.0))
    canvas.set_tool("圆")
    canvas.add_coordinate_point((10.0, 0.0))
    canvas.add_coordinate_point((20.0, 0.0))
    canvas.set_tool("直线")
    canvas.add_coordinate_point((5.0, 8.65))

    assert canvas.current_snap_kind == "交点"


def test_sketch_snaps_to_arc_circle_intersection_inside_arc_sweep(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    canvas.set_tool("圆弧")
    for point in ((0.0, 0.0), (10.0, 0.0), (0.0, 10.0)):
        canvas.add_coordinate_point(point)
    canvas.set_tool("圆")
    canvas.add_coordinate_point((10.0, 0.0))
    canvas.add_coordinate_point((20.0, 0.0))
    canvas.set_tool("直线")
    canvas.add_coordinate_point((5.1, 8.66))
    snap_kind = canvas.current_snap_kind
    canvas.add_coordinate_point((20.0, 15.0))

    snapped_line = canvas.entities[-1]
    assert snap_kind == "交点"
    assert isinstance(snapped_line, LineEntity)
    assert snapped_line.start_mm == pytest.approx((5.0, 8.660254037844386), abs=0.02)


def test_sketch_snaps_to_arc_arc_intersection_inside_both_sweeps(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    canvas.set_tool("圆弧")
    for point in ((0.0, 0.0), (10.0, 0.0), (0.0, 10.0)):
        canvas.add_coordinate_point(point)
    canvas.set_tool("圆弧")
    canvas.add_coordinate_point((10.0, 0.0))
    for angle in (100.0, 140.0):
        radians = math.radians(angle)
        canvas.add_coordinate_point((10.0 + 10.0 * math.cos(radians), 10.0 * math.sin(radians)))
    canvas.set_tool("直线")
    canvas.add_coordinate_point((5.1, 8.66))
    snap_kind = canvas.current_snap_kind
    canvas.add_coordinate_point((20.0, 15.0))

    snapped_line = canvas.entities[-1]
    assert snap_kind == "交点"
    assert isinstance(snapped_line, LineEntity)
    assert snapped_line.start_mm == pytest.approx((5.0, 8.660254037844386), abs=0.02)


def test_arc_snap_excludes_circle_intersection_outside_sweep(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    canvas.set_tool("圆弧")
    for point in ((0.0, 0.0), (10.0, 0.0), (0.0, 10.0)):
        canvas.add_coordinate_point(point)
    canvas.set_tool("直线")
    canvas.add_coordinate_point((-5.0, -10.0))
    canvas.add_coordinate_point((15.0, -10.0))
    canvas.set_tool("直线")
    canvas.add_coordinate_point((0.1, -10.0))

    assert canvas.current_snap_kind == ""


def test_unfinished_element_must_be_cleared_before_finishing_sketch(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.canvas.set_tool("直线")
    dialog.canvas.add_coordinate_point((0.0, 0.0))
    dialog.canvas.add_coordinate_point((10.0, 0.0))
    assert dialog.finish_button.isEnabled()
    dialog.canvas.add_coordinate_point((20.0, 0.0))

    assert dialog.canvas.pending_point_count == 1
    assert not dialog.finish_button.isEnabled()
    dialog.finish_sketch()
    assert dialog.result_sketch is None
    assert "未完成" in dialog.status_label.text()

    QTest.keyClick(dialog.canvas, Qt.Key.Key_Escape)
    assert dialog.canvas.pending_point_count == 0
    assert dialog.isVisible()
    QTest.keyClick(dialog.canvas, Qt.Key.Key_Escape)
    assert not dialog.isVisible()
    assert dialog.result_sketch is None


def test_switching_tool_does_not_discard_an_unfinished_element(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.tool_combo.setCurrentText("直线")
    dialog.canvas.add_coordinate_point((0.0, 0.0))

    dialog.tool_combo.setCurrentText("圆")

    assert dialog.canvas.tool == "直线"
    assert dialog.tool_combo.currentText() == "直线"
    assert "未完成" in dialog.status_label.text()


def test_work_plane_cannot_change_after_drawing_starts(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.canvas.set_tool("直线")
    dialog.canvas.add_coordinate_point((0.0, 0.0))
    dialog.canvas.add_coordinate_point((10.0, 0.0))

    dialog.plane_combo.setCurrentText("XZ")

    assert dialog.plane_combo.currentText() == "XY"
    assert dialog.current_frame() == WorkPlaneFrame.xy()
    assert len(dialog.canvas.entities) == 1
    assert "工作平面已锁定" in dialog.status_label.text()


def test_sketch_editor_can_undo_last_draft_entity(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.canvas.set_tool("直线")
    for point in ((0.0, 0.0), (10.0, 0.0), (0.0, 10.0), (10.0, 10.0)):
        dialog.canvas.add_coordinate_point(point)

    assert len(dialog.canvas.entities) == 2
    first_id = dialog.canvas.entities[0].entity_id
    dialog.undo_entity_button.click()

    assert len(dialog.canvas.entities) == 1
    assert dialog.canvas.entities[0].entity_id == first_id
    assert dialog.finish_button.isEnabled()


def test_main_window_sketch_finish_submits_one_replayable_command(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()

    window.act_sketch.trigger()
    dialog = window.active_sketch_dialog()
    assert dialog is not None
    qtbot.waitExposed(dialog)
    dialog.tool_combo.setCurrentText("直线")
    first = dialog.canvas.local_to_screen((0.0, 0.0))
    second = dialog.canvas.local_to_screen((12.0, 6.0))
    QTest.mouseClick(dialog.canvas, Qt.MouseButton.LeftButton, pos=first)
    QTest.mouseClick(dialog.canvas, Qt.MouseButton.LeftButton, pos=second)
    dialog.tool_combo.setCurrentText("选择元素")
    middle = dialog.canvas.local_to_screen((6.0, 3.0))
    QTest.mouseClick(dialog.canvas, Qt.MouseButton.LeftButton, pos=middle)
    dialog.delta_u_field.setValue(3.0)
    dialog.delta_v_field.setValue(-2.0)
    dialog.numeric_move_button.click()

    assert loaded.document.commands == ()
    assert len(dialog.canvas.entities) == 1
    draft_line = dialog.canvas.entities[0]
    assert isinstance(draft_line, LineEntity)
    assert draft_line.start_mm == pytest.approx((3.0, -2.0), abs=0.15)
    assert draft_line.end_mm == pytest.approx((15.0, 4.0), abs=0.15)

    dialog.finish_button.click()

    execution_unit = window.execution_unit
    assert execution_unit is not None
    qtbot.waitUntil(lambda: not execution_unit.is_busy, timeout=5000)
    assert len(loaded.document.commands) == 1
    assert loaded.document.commands[0].id == "sketch.create"
    assert len(services.kernel.sketches) == 1
    committed_line = services.kernel.sketches[0].entities[0]
    assert isinstance(committed_line, LineEntity)
    assert committed_line.start_mm == pytest.approx((3.0, -2.0), abs=0.15)
    assert committed_line.end_mm == pytest.approx((15.0, 4.0), abs=0.15)
    assert window.viewport is not None
    assert window.viewport.sketch_item_count() == 1


def test_main_window_sketch_cancel_writes_nothing(qtbot: QtBot) -> None:
    services = build_app(discoverers=())
    loaded = new_document(services, document_type="drawing2d")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.act_sketch.trigger()

    dialog = window.active_sketch_dialog()
    assert dialog is not None
    dialog.reject()

    assert loaded.document.commands == ()
    assert services.kernel.sketches == ()


def test_offset_failure_keeps_draft_then_valid_distance_undo_redo_restores_ids(
    qtbot: QtBot,
) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.canvas.set_snapping_enabled(False)
    dialog.tool_combo.setCurrentText("多段线")
    for point in ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)):
        dialog.canvas.add_coordinate_point(point)
    dialog.finish_polyline_button.click()
    original = tuple(dialog.canvas.entities)
    constraints = tuple(dialog.canvas.constraints)
    assert len(original) == 1
    dialog.tool_combo.setCurrentText("选择元素")
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5.0, 0.0))
    )
    selection = set(dialog.canvas.selected_entity_ids)
    assert selection == {original[0].entity_id}
    dialog.offset_distance_field.setValue(6)
    dialog.transform_buttons["offset"].click()
    assert "反转" in dialog.status_label.text()
    assert tuple(dialog.canvas.entities) == original
    assert tuple(dialog.canvas.constraints) == constraints
    assert dialog.canvas.selected_entity_ids == selection
    dialog.offset_distance_field.setValue(1)
    dialog.transform_buttons["offset"].click()
    result = tuple(dialog.canvas.entities)
    assert len(result) == 2 and result[0] == original[0]
    assert result[1].entity_id != result[0].entity_id
    assert dialog.canvas.undo_last_operation()
    assert tuple(dialog.canvas.entities) == original
    assert tuple(dialog.canvas.constraints) == constraints
    assert dialog.canvas.selected_entity_ids == selection
    assert dialog.canvas.redo_last_operation()
    assert tuple(dialog.canvas.entities) == result


def test_split_and_move_cannot_reassign_user_dimension_to_changed_draft_geometry(
    qtbot: QtBot,
) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    line = LineEntity("11111111-1111-4111-8111-111111111111", (0.0, 0.0), (20.0, 0.0))
    cutter = LineEntity("22222222-2222-4222-8222-222222222222", (10.0, -5.0), (10.0, 5.0))
    constraint = SketchConstraint(
        "33333333-3333-4333-8333-333333333333",
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20.0,
        "mm",
    )
    dialog.canvas.entities = [line, cutter]
    dialog.canvas.constraints = [constraint]
    dialog.canvas.set_snapping_enabled(False)
    dialog.tool_combo.setCurrentText("分割")
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5.0, 0.0))
    )
    assert "用户约束" in dialog.canvas.message
    assert dialog.canvas.entities == [line, cutter]
    assert dialog.canvas.constraints == [constraint]
    assert not dialog.canvas.can_undo
    dialog.tool_combo.setCurrentText("选择元素")
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5.0, 0.0))
    )
    dialog.delta_u_field.setValue(2)
    dialog.transform_buttons["move"].click()
    assert "用户约束" in dialog.canvas.message
    assert dialog.canvas.entities == [line, cutter]
    assert dialog.canvas.constraints == [constraint]
    assert not dialog.canvas.can_undo


@pytest.mark.parametrize(("sweep", "expected_radius"), [(90.0, 7.0), (-90.0, 3.0)])
def test_numeric_negative_arc_offset_respects_sweep(
    qtbot: QtBot, sweep: float, expected_radius: float
) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    arc = ArcEntity(uuid4().hex, (0, 0), 5, 0, sweep)
    assert dialog.canvas.replace_draft_entities((arc,))
    dialog.tool_combo.setCurrentText("选择元素")
    angle = math.radians(sweep / 2)
    QTest.mouseClick(
        dialog.canvas,
        Qt.MouseButton.LeftButton,
        pos=dialog.canvas.local_to_screen((5 * math.cos(angle), 5 * math.sin(angle))),
    )
    dialog.offset_distance_field.setValue(-2)
    dialog.transform_buttons["offset"].click()
    assert len(dialog.canvas.entities) == 2
    result = dialog.canvas.entities[1]
    assert isinstance(result, ArcEntity)
    assert result.radius_mm == pytest.approx(expected_radius)
    dialog.undo_entity_button.click()
    assert dialog.canvas.entities == [arc]


def test_interactive_offset_preview_and_continuous_undo(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.begin_interactive_offset()
    canvas.set_interactive_offset_distance(2)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    QTest.mouseMove(canvas, canvas.local_to_screen((10, 4)))
    assert len(canvas.transform_preview_entities) == 1
    preview = canvas.transform_preview_entities[0]
    assert isinstance(preview, LineEntity)
    assert preview.start_mm == pytest.approx((0, 2))
    assert canvas.entities == [line]
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 4)))
    assert len(canvas.entities) == 2
    first_copy = canvas.entities[1]
    assert isinstance(first_copy, LineEntity) and first_copy.start_mm == pytest.approx((0, 2))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, -4)))
    assert len(canvas.entities) == 3
    second_copy = canvas.entities[2]
    assert isinstance(second_copy, LineEntity) and second_copy.start_mm == pytest.approx((0, -2))
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    canvas.undo_last_operation()
    assert canvas.entities == [line, first_copy]
    canvas.undo_last_operation()
    assert canvas.entities == [line]


@pytest.mark.parametrize("locked", [True, False])
def test_interactive_offset_does_not_edit_restricted_layer(qtbot: QtBot, locked: bool) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    dialog.layer_table = dialog.layer_table.add(
        SketchLayer("restricted", locked=locked, visible=locked)
    )
    canvas.set_layer_table(dialog.layer_table, "0")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0), layer_name="restricted")
    assert canvas.replace_draft_entities((line,))
    canvas.begin_interactive_offset()
    canvas.set_interactive_offset_distance(2)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 5)))
    assert canvas.entities == [line]
    assert not canvas.transform_preview_entities
    QTest.keyClick(canvas, Qt.Key.Key_Escape)


def test_interactive_offset_rejects_collapsed_circle_and_allows_retry(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    assert canvas.replace_draft_entities((circle,))
    canvas.begin_interactive_offset()
    canvas.set_interactive_offset_distance(5)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1, 0)))
    assert canvas.entities == [circle]
    assert not canvas.transform_preview_entities
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((9, 0)))
    assert len(canvas.entities) == 2
    copy = canvas.entities[1]
    assert isinstance(copy, CircleEntity) and copy.radius_mm == pytest.approx(10)
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
    assert canvas.active_transform is None


def test_interactive_offset_delete_does_not_delete_source(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    canvas.replace_draft_entities((line,))
    canvas.begin_interactive_offset()
    canvas.set_interactive_offset_distance(2)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert canvas.entities == [line]
    assert canvas.active_transform == "offset"
    QTest.keyClick(canvas, Qt.Key.Key_Escape)


@pytest.mark.parametrize("kind", ["arc", "polyline", "rectangle"])
def test_interactive_offset_curves_and_paths(qtbot: QtBot, kind: str) -> None:
    from mycad.core.sketch import RectangleEntity

    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    if kind == "arc":
        entity = ArcEntity(uuid4().hex, (0, 0), 10, 0, 90)
        target = (10 * math.cos(math.pi / 4), 10 * math.sin(math.pi / 4))
        side = (12 * math.cos(math.pi / 4), 12 * math.sin(math.pi / 4))
    elif kind == "polyline":
        entity = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)))
        target, side = (10, 0), (10, 5)
    else:
        entity = RectangleEntity(uuid4().hex, (0, 0), (20, 20))
        target, side = (10, 0), (10, -5)
    assert canvas.replace_draft_entities((entity,))
    canvas.begin_interactive_offset()
    canvas.set_interactive_offset_distance(2)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(target))
    QTest.mouseMove(canvas, canvas.local_to_screen(side))
    assert len(canvas.transform_preview_entities) == 1
    preview = canvas.transform_preview_entities[0]
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(side))
    assert len(canvas.entities) == 2 and canvas.entities[1] == preview
    if kind == "arc":
        assert isinstance(preview, ArcEntity) and preview.radius_mm == pytest.approx(12)
    else:
        assert isinstance(preview, PolylineEntity)
        assert preview.points_mm[0][1] == pytest.approx(2 if kind == "polyline" else -2)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)


def test_interactive_offset_rejects_changed_draft_target(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    original = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((original,))
    canvas.begin_interactive_offset()
    canvas.set_interactive_offset_distance(2)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    changed = LineEntity(original.entity_id, (0, 1), (20, 1))
    assert canvas.replace_draft_entities((changed,))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 5)))
    assert canvas.entities == [changed]
    assert not canvas.transform_preview_entities
    assert "变化" in canvas.message


def test_interactive_offset_rejects_layer_locked_after_pick(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    layer = SketchLayer("editable")
    dialog.layer_table = dialog.layer_table.add(layer)
    canvas.set_layer_table(dialog.layer_table, "0")
    line = LineEntity(uuid4().hex, (0, 0), (20, 0), layer_name="editable")
    assert canvas.replace_draft_entities((line,))
    canvas.begin_interactive_offset()
    canvas.set_interactive_offset_distance(2)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    dialog.layer_table = dialog.layer_table.replace(SketchLayer("editable", locked=True))
    canvas.set_layer_table(dialog.layer_table, "0")
    assert canvas.active_transform is None
    assert canvas.entities == [line]
    assert not canvas.transform_preview_entities


def test_interactive_offset_unsupported_object_can_reselect(qtbot: QtBot) -> None:
    from mycad.core.sketch import PointEntity

    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    point = PointEntity(uuid4().hex, (0, 10))
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    assert canvas.replace_draft_entities((point, line))
    canvas.begin_interactive_offset()
    canvas.set_interactive_offset_distance(2)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 10)))
    assert "不支持" in canvas.message
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 5)))
    assert len(canvas.entities) == 3
    assert isinstance(canvas.entities[-1], LineEntity)


def test_point_entity_handle_resolves_to_its_position(qtbot: QtBot) -> None:
    from mycad.core.sketch import PointEntity

    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    point = PointEntity(uuid4().hex, (3, 7))
    handles = dialog.canvas.entity_point_references(point)
    assert len(handles) == 1
    reference, position = handles[0]
    assert dialog.canvas.point_for_reference(reference, {point.entity_id: point}) == position
    assert (
        dialog.canvas.point_for_reference(
            SketchGeometryReference(point.entity_id, "vertex", 1), {point.entity_id: point}
        )
        is None
    )


def test_all_entity_handles_resolve_to_their_displayed_positions(qtbot: QtBot) -> None:
    from mycad.core.sketch import PointEntity, RectangleEntity, SplineEntity

    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    entities = (
        PointEntity(uuid4().hex, (3, 7)),
        LineEntity(uuid4().hex, (0, 0), (2, 3)),
        PolylineEntity(uuid4().hex, ((0, 0), (1, 2), (4, 3))),
        RectangleEntity(uuid4().hex, (0, 1), (2, 3)),
        CircleEntity(uuid4().hex, (3, 5), 2),
        ArcEntity(uuid4().hex, (3, 5), 2, 45, -90),
        SplineEntity(uuid4().hex, ((0, 0), (1, 2), (2, 2), (3, 0))),
    )
    for entity in entities:
        for reference, position in dialog.canvas.entity_point_references(entity):
            assert dialog.canvas.point_for_reference(reference, {entity.entity_id: entity}) == (
                pytest.approx(position)
            )
            assert dialog.canvas.point_for_reference(reference, {}) is None


def test_trim_uses_only_explicit_boundaries_and_preserves_other_entities(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.set_snapping_enabled(False)
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    selected = LineEntity(uuid4().hex, (5, -5), (5, 5))
    excluded = LineEntity(uuid4().hex, (15, -5), (15, 5))
    assert canvas.replace_draft_entities((target, selected, excluded))
    assert canvas.set_tool("修剪")
    canvas.set_line_edit_boundaries(frozenset({selected.entity_id}))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    assert len(canvas.entities) == 3
    result = canvas.entities[0]
    assert isinstance(result, LineEntity)
    assert result.entity_id == target.entity_id
    assert result.start_mm == pytest.approx((0, 0))
    assert result.end_mm == pytest.approx((5, 0))
    assert canvas.entities[1:] == [selected, excluded]


def test_trim_rejects_changed_explicit_boundary(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (5, -5), (5, 5))
    assert canvas.replace_draft_entities((target, boundary))
    assert canvas.set_tool("修剪")
    canvas.set_line_edit_boundaries(frozenset({boundary.entity_id}))
    changed = LineEntity(boundary.entity_id, (6, -5), (6, 5))
    assert canvas.replace_draft_entities((target, changed))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    assert canvas.entities == [target, changed]
    assert "边界对象已变化" in canvas.message


def test_explicit_boundaries_reset_on_tool_switch(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    first = LineEntity(uuid4().hex, (5, -5), (5, 5))
    second = LineEntity(uuid4().hex, (15, -5), (15, 5))
    assert canvas.replace_draft_entities((target, first, second))
    assert canvas.set_tool("修剪")
    canvas.set_line_edit_boundaries(frozenset({first.entity_id}))
    assert canvas.set_tool("选择元素")
    assert canvas.set_tool("修剪")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    assert len(canvas.entities) == 4


def test_trim_uses_locked_line_as_explicit_boundary(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    dialog.layer_table = dialog.layer_table.add(SketchLayer("boundary", locked=True))
    canvas.set_layer_table(dialog.layer_table, "0")
    target = LineEntity(uuid4().hex, (0, 0), (20, 0))
    boundary = LineEntity(uuid4().hex, (5, -5), (5, 5), layer_name="boundary")
    assert canvas.replace_draft_entities((target, boundary))
    assert canvas.set_tool("修剪")
    canvas.set_line_edit_boundaries(frozenset({boundary.entity_id}))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    assert len(canvas.entities) == 2
    result = canvas.entities[0]
    assert isinstance(result, LineEntity) and result.end_mm == pytest.approx((5, 0))
    assert canvas.entities[1] == boundary


@pytest.mark.parametrize("snap_at_start", [True, False])
def test_arc_endpoint_snaps_to_genuine_tangent_on_circle(qtbot: QtBot, snap_at_start: bool) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    circle = CircleEntity(uuid4().hex, (0.0, 0.0), 5.0)
    assert canvas.replace_draft_entities((circle,))
    canvas.set_tool("圆弧")
    canvas.add_coordinate_point((10.0, 0.0), exact_point=True)
    if snap_at_start:
        canvas.add_coordinate_point((5.1, 0.1))
        assert canvas.current_snap_kind == "切点"
        canvas.add_coordinate_point((10.0, 5.0), exact_point=True)
    else:
        canvas.add_coordinate_point((10.0, 5.0), exact_point=True)
        canvas.add_coordinate_point((5.1, 0.1))
        assert canvas.current_snap_kind == "切点"
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity)
    assert arc.radius_mm == pytest.approx(5.0)
    angle = arc.start_angle_deg if snap_at_start else arc.start_angle_deg + arc.sweep_angle_deg
    point = (
        arc.center_mm[0] + arc.radius_mm * math.cos(math.radians(angle)),
        arc.center_mm[1] + arc.radius_mm * math.sin(math.radians(angle)),
    )
    assert point == pytest.approx((5.0, 0.0))


def test_three_point_arc_endpoint_snaps_tangent_to_existing_line(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    line = LineEntity(uuid4().hex, (-20, 0), (40, 0))
    assert canvas.replace_draft_entities((line,))
    assert canvas.set_tool("圆弧")
    assert canvas.arc_creation_mode == "three_point"
    canvas.add_coordinate_point((0, 5), exact_point=True)
    canvas.add_coordinate_point((10, 5), exact_point=True)
    point, kind = canvas._snapped((5.1, 0.1))
    assert kind == "切点"
    assert point == pytest.approx((5, 0))
    canvas.add_coordinate_point((5.1, 0.1))
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity)
    assert arc.center_mm == pytest.approx((5, 5))
    assert arc.radius_mm == pytest.approx(5)
    assert arc.center_mm[1] == pytest.approx(arc.radius_mm)


def test_three_point_arc_does_not_snap_tangent_to_line_extension(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (-20, 0), (0, 0)),))
    assert canvas.set_tool("圆弧")
    canvas.add_coordinate_point((0, 5), exact_point=True)
    canvas.add_coordinate_point((10, 5), exact_point=True)
    assert canvas._snapped((5, 0))[1] != "切点"


def test_three_point_arc_tangent_mouse_preview_and_commit(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    dialog.resize(900, 620)
    dialog.show()
    canvas = dialog.canvas
    line = LineEntity(uuid4().hex, (-20, 0), (40, 0))
    assert canvas.replace_draft_entities((line,))
    assert canvas.set_tool("圆弧")
    for point in ((0, 5), (10, 5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    QTest.mouseMove(canvas, canvas.local_to_screen((5, 0)))
    assert canvas.current_snap_kind == "切点"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity)
    assert abs(arc.center_mm[1]) == pytest.approx(arc.radius_mm)
    end_angle = math.radians(arc.start_angle_deg + arc.sweep_angle_deg)
    assert arc.center_mm[1] + arc.radius_mm * math.sin(end_angle) == pytest.approx(0, abs=1e-8)


@pytest.mark.parametrize("snap_at_start", [True, False])
def test_center_arc_snaps_tangent_to_existing_line(qtbot: QtBot, snap_at_start: bool) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    assert canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (20, 0)),))
    assert canvas.set_tool("圆弧")
    assert canvas.begin_arc_center()
    canvas.add_coordinate_point((6, 8), exact_point=True)
    if not snap_at_start:
        canvas.add_coordinate_point((14, 8), exact_point=True)
    canvas.add_coordinate_point((6.1, 0.1))
    assert canvas.current_snap_kind == "切点"
    if snap_at_start:
        canvas.add_coordinate_point((14, 8), exact_point=True)
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity)
    assert arc.center_mm == pytest.approx((6, 8))
    assert arc.radius_mm == pytest.approx(8)


@pytest.mark.parametrize("target_kind", ["circle", "arc"])
def test_line_circle_and_center_arc_snap_tangent_to_circular_target(
    qtbot: QtBot, target_kind: str
) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    target: CircleEntity | ArcEntity = (
        CircleEntity(uuid4().hex, (0, 0), 5)
        if target_kind == "circle"
        else ArcEntity(uuid4().hex, (0, 0), 5, -30, 120)
    )
    assert canvas.replace_draft_entities((target,))
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((2.5, 4.33))
    assert canvas.current_snap_kind == "切点"
    line = canvas.entities[-1]
    assert isinstance(line, LineEntity)
    assert line.end_mm == pytest.approx((2.5, 5 * math.sqrt(3) / 2))
    assert canvas.replace_draft_entities((target,))
    assert canvas.set_tool("圆")
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((5.1, 0.1))
    circle = canvas.entities[-1]
    assert isinstance(circle, CircleEntity)
    assert canvas.current_snap_kind == "切点"
    assert circle.radius_mm == pytest.approx(5)
    assert canvas.replace_draft_entities((target,))
    assert canvas.set_tool("圆弧")
    assert canvas.begin_arc_center()
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((5.1, 0.1))
    assert canvas.current_snap_kind == "切点"
    canvas.add_coordinate_point((10, 5), exact_point=True)
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity)
    assert arc.radius_mm == pytest.approx(5)


@pytest.mark.parametrize("target_kind", ["circle", "arc"])
def test_three_point_arc_snaps_tangent_to_circular_target(qtbot: QtBot, target_kind: str) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    target: CircleEntity | ArcEntity = (
        CircleEntity(uuid4().hex, (0, 0), 5)
        if target_kind == "circle"
        else ArcEntity(uuid4().hex, (0, 0), 5, -30, 60)
    )
    assert canvas.replace_draft_entities((target,))
    assert canvas.set_tool("圆弧")
    canvas.add_coordinate_point((10, 5), exact_point=True)
    canvas.add_coordinate_point((15, 0), exact_point=True)
    canvas.add_coordinate_point((5.1, 0.1))
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity)
    assert canvas.current_snap_kind == "切点"
    assert arc.center_mm == pytest.approx((10, 0), abs=1e-7)
    assert arc.radius_mm == pytest.approx(5)


def test_line_snaps_tangent_to_polyline_arc_segment(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    target = PolylineEntity(uuid4().hex, ((5, 0), (-5, 0)), bulges=(1.0,))
    assert canvas.replace_draft_entities((target,))
    assert canvas.set_tool("直线")
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((2.5, 4.33))
    assert canvas.current_snap_kind == "切点"
    line = canvas.entities[-1]
    assert isinstance(line, LineEntity)
    assert line.end_mm == pytest.approx((2.5, 5 * math.sqrt(3) / 2))


def test_three_point_arc_cannot_snap_to_arc_extension(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    target = ArcEntity(uuid4().hex, (0, 0), 5, 90, 90)
    assert canvas.replace_draft_entities((target,))
    assert canvas.set_tool("圆弧")
    canvas.add_coordinate_point((10, 5), exact_point=True)
    canvas.add_coordinate_point((15, 0), exact_point=True)
    assert canvas._snapped((5.1, 0.1))[1] != "切点"


def test_arc_endpoint_does_not_claim_tangent_when_radius_does_not_fit(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    assert canvas.replace_draft_entities((CircleEntity(uuid4().hex, (0.0, 0.0), 5.0),))
    canvas.set_tool("圆弧")
    canvas.add_coordinate_point((10.0, 0.0), exact_point=True)
    canvas.add_coordinate_point((10.0, 4.0), exact_point=True)
    canvas.add_coordinate_point((5.1, 0.1))
    assert canvas.current_snap_kind != "切点"


def test_arc_tangent_two_objects_then_radius_command(qtbot: QtBot) -> None:
    from mycad.core.fillet_curves import tangent_on_curves

    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    dialog.resize(1200, 900)
    dialog.show()
    canvas = dialog.canvas
    left = CircleEntity(uuid4().hex, (-15.0, 0.0), 5.0)
    right = CircleEntity(uuid4().hex, (15.0, 0.0), 5.0)
    assert canvas.replace_draft_entities((left, right))
    bar = dialog.drawing_command_bar.input
    for text in ("ARC", "T"):
        bar.setText(text)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    for point in ((-15.0, 5.0), (15.0, 5.0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    canvas.setFocus()
    QTest.keyClicks(canvas, "12")
    assert bar.text() == "12"
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(canvas.entities) == 3
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity)
    assert arc.radius_mm == 12
    assert tangent_on_curves(left, arc) and tangent_on_curves(right, arc)
    assert tuple(canvas.entities[:2]) == (left, right)
    assert canvas.undo_last_operation()
    assert tuple(canvas.entities) == (left, right)


@pytest.mark.parametrize("polyline", [False, True])
def test_tangent_arc_two_lines_or_polyline_segments(qtbot: QtBot, polyline: bool) -> None:
    from mycad.core.cross_sketch_tangency import tangent_entity_curve
    from mycad.core.fillet_curves import tangent_on_curves

    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    if polyline:
        path = PolylineEntity(uuid4().hex, ((0, 0), (30, 0), (30, 30)))
        originals = (path,)
        sources = (tangent_entity_curve(path, 0), tangent_entity_curve(path, 1))
    else:
        first = LineEntity(uuid4().hex, (0, 0), (30, 0))
        second = LineEntity(uuid4().hex, (30, 0), (30, 30))
        originals = (first, second)
        sources = originals
    assert canvas.replace_draft_entities(originals)
    canvas.set_tool("圆弧")
    assert canvas.begin_arc_ttr()
    canvas.add_coordinate_point((20, 0), exact_point=True)
    canvas.add_coordinate_point((30, 10), exact_point=True)
    assert canvas.arc_ttr_radius_pending
    assert not canvas.finish_arc_ttr(0)
    assert tuple(canvas.entities) == originals and canvas.arc_ttr_radius_pending
    assert canvas.finish_arc_ttr(5)
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity) and arc.radius_mm == pytest.approx(5)
    assert all(tangent_on_curves(source, arc) for source in sources)
    assert tuple(canvas.entities[:-1]) == originals
    assert canvas.undo_last_operation() and tuple(canvas.entities) == originals


def test_tangent_arc_cancel_keeps_sources(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    source = LineEntity(uuid4().hex, (0, 0), (30, 0))
    assert canvas.replace_draft_entities((source,))
    canvas.set_tool("圆弧")
    assert canvas.begin_arc_ttr()
    canvas.add_coordinate_point((20, 0), exact_point=True)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.arc_ttr_active and tuple(canvas.entities) == (source,)


@pytest.mark.parametrize("source_kind", ["line", "arc", "polyline_arc"])
def test_arc_start_tangent_snap_uses_finite_source_curves(qtbot: QtBot, source_kind: str) -> None:
    dialog = SketchEditorDialog()
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    if source_kind == "line":
        source = LineEntity(uuid4().hex, (-10, 0), (20, 0))
        center, contact = (7.0, 5.0), (7.0, 0.0)
    else:
        source = (
            ArcEntity(uuid4().hex, (0, 0), 5, 10, 100)
            if source_kind == "arc"
            else PolylineEntity(uuid4().hex, ((5, 0), (-5, 0)), bulges=(1.0,))
        )
        center = (10 / math.sqrt(2), 10 / math.sqrt(2))
        contact = (5 / math.sqrt(2), 5 / math.sqrt(2))
    assert canvas.replace_draft_entities((source,))
    canvas.set_tool("圆弧")
    canvas.add_coordinate_point(center, exact_point=True)
    canvas.add_coordinate_point((contact[0] + 0.1, contact[1] + 0.1))
    assert canvas.current_snap_kind == "切点"
    canvas.add_coordinate_point((center[0] + 5, center[1]), exact_point=True)
    result = canvas.entities[-1]
    assert isinstance(result, ArcEntity)
    point = (
        result.center_mm[0] + result.radius_mm * math.cos(math.radians(result.start_angle_deg)),
        result.center_mm[1] + result.radius_mm * math.sin(math.radians(result.start_angle_deg)),
    )
    assert point == pytest.approx(contact)


def test_tangent_arc_button_retries_unsolvable_radius(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    sources = (CircleEntity(uuid4().hex, (-15, 0), 5), CircleEntity(uuid4().hex, (15, 0), 5))
    assert canvas.replace_draft_entities(sources)
    dialog.arc_ttr_button.click()
    assert canvas.tool == "圆弧" and canvas.arc_ttr_active
    canvas.add_coordinate_point((-15, 5), exact_point=True)
    canvas.add_coordinate_point((15, 5), exact_point=True)
    assert not canvas.finish_arc_ttr(1)
    assert canvas.arc_ttr_radius_pending and tuple(canvas.entities) == sources
    assert canvas.finish_arc_ttr(12)
    assert len(canvas.entities) == 3 and not canvas.arc_ttr_active
    assert canvas.undo_last_operation()
    dialog.arc_ttr_button.click()
    canvas.add_coordinate_point((-15, 5), exact_point=True)
    canvas.add_coordinate_point((15, 5), exact_point=True)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert len(canvas.entities) == 3 and isinstance(canvas.entities[-1], ArcEntity)
    assert canvas.entities[-1].radius_mm == 12
    assert canvas.undo_last_operation()
    dialog.arc_ttr_button.click()
    canvas.add_coordinate_point((-15, 5), exact_point=True)
    canvas.add_coordinate_point((15, 5), exact_point=True)
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
    assert len(canvas.entities) == 3 and isinstance(canvas.entities[-1], ArcEntity)


def test_arc_command_center_option_keeps_arc_tool(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    bar = dialog.drawing_command_bar.input
    for value in ("ARC", "C"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.tool == "圆弧"
    for point in ((0, 0), (10, 0), (0, 10)):
        canvas.add_coordinate_point(point, exact_point=True)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], ArcEntity)


def test_tangent_arc_rejects_document_change_during_selection(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    sources = (CircleEntity(uuid4().hex, (-15, 0), 5), CircleEntity(uuid4().hex, (15, 0), 5))
    assert canvas.replace_draft_entities(sources)
    revision = [1]
    canvas.source_revision_provider = lambda: revision[0]
    assert canvas.set_tool("圆弧") and canvas.begin_arc_ttr()
    canvas.add_coordinate_point((-15, 5), exact_point=True)
    canvas.add_coordinate_point((15, 5), exact_point=True)
    assert canvas.arc_ttr_radius_pending
    history_position = canvas.history_position
    revision[0] = 2
    assert not canvas.finish_arc_ttr(12)
    assert tuple(canvas.entities) == sources
    assert canvas.history_position == history_position
    assert "来源已变化" in canvas.message
    assert "来源已变化" in dialog.status_label.text()
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.arc_ttr_active


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("curve_kind", ["circle", "arc"])
def test_tangent_arc_line_and_curved_source_in_both_orders(
    qtbot: QtBot, reverse: bool, curve_kind: str
) -> None:
    from mycad.core.fillet_curves import tangent_on_curves

    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    line = LineEntity(uuid4().hex, (-20, 0), (20, 0))
    curve = (
        CircleEntity(uuid4().hex, (0, 5), 2)
        if curve_kind == "circle"
        else ArcEntity(uuid4().hex, (0, 5), 2, 180, 180)
    )
    assert canvas.replace_draft_entities((line, curve))
    assert canvas.set_tool("圆弧") and canvas.begin_arc_ttr()
    picks = ((-3.0, 0.0), (-1.3, 3.5))
    for point in reversed(picks) if reverse else picks:
        canvas.add_coordinate_point(point, exact_point=True)
    assert canvas.arc_ttr_radius_pending
    assert canvas.finish_arc_ttr(2)
    result = canvas.entities[-1]
    assert isinstance(result, ArcEntity) and result.radius_mm == 2
    assert tangent_on_curves(line, result) and tangent_on_curves(curve, result)
    assert canvas.entities[:2] == [line, curve]
    assert (
        len([constraint for constraint in canvas.constraints if constraint.kind == "tangent"]) == 2
    )


def test_tangent_arc_does_not_snap_beyond_finite_line(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    line = LineEntity(uuid4().hex, (-20, 0), (-5, 0))
    circle = CircleEntity(uuid4().hex, (0, 5), 2)
    sources = (line, circle)
    assert canvas.replace_draft_entities(sources)
    assert canvas.set_tool("圆弧") and canvas.begin_arc_ttr()
    canvas.add_coordinate_point((-10, 0), exact_point=True)
    canvas.add_coordinate_point((-1.3, 3.5), exact_point=True)
    assert canvas.arc_ttr_radius_pending
    assert not canvas.finish_arc_ttr(2)
    assert tuple(canvas.entities) == sources and canvas.arc_ttr_radius_pending


@pytest.mark.parametrize("reverse", [False, True])
def test_tangent_arc_line_circle_internal_solution(qtbot: QtBot, reverse: bool) -> None:
    from mycad.core.fillet_curves import tangent_on_curves

    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    line = LineEntity(uuid4().hex, (-20, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (0, 4), 5)
    assert canvas.replace_draft_entities((line, circle))
    assert canvas.set_tool("圆弧") and canvas.begin_arc_ttr()
    picks = ((-1.0, 0.0), (-5.0, 4.0))
    for point in reversed(picks) if reverse else picks:
        canvas.add_coordinate_point(point, exact_point=True)
    assert canvas.arc_ttr_radius_pending
    assert canvas.finish_arc_ttr(2)
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity)
    assert math.dist(arc.center_mm, circle.center_mm) == pytest.approx(3)
    assert tangent_on_curves(arc, line) and tangent_on_curves(arc, circle)
    assert (
        len([constraint for constraint in canvas.constraints if constraint.kind == "tangent"]) == 2
    )


def test_circle_alias_after_completed_arc_starts_circle(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    bar = dialog.drawing_command_bar.input
    bar.setText("ARC")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    for point in ((0, 0), (10, 0), (0, 10)):
        canvas.add_coordinate_point(point, exact_point=True)
    assert isinstance(canvas.entities[-1], ArcEntity)
    bar.setText("C")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.tool == "圆"


def test_arc_mode_option_typed_on_canvas_starts_tangent_mode(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    assert canvas.set_tool("圆弧")
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_T)
    QTest.keyClick(dialog.drawing_command_bar.input, Qt.Key.Key_Return)
    assert canvas.arc_ttr_active and not canvas.arc_ttr_radius_pending


@pytest.mark.parametrize(
    ("middle", "end", "sweep"),
    [((0, 1), (-1, 0), 180), ((0, -1), (-1, 0), -180), ((-1, 0), (0, 1), -270)],
)
def test_arc_three_point_mode_uses_requested_path(
    qtbot: QtBot, middle: tuple[int, int], end: tuple[int, int], sweep: float
) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    bar = dialog.drawing_command_bar.input
    for value in ("ARC", "3P"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    for point in ((1, 0), middle, end):
        canvas.add_coordinate_point(point, exact_point=True)
    assert len(canvas.entities) == 1
    arc = canvas.entities[0]
    assert isinstance(arc, ArcEntity)
    assert arc.center_mm == pytest.approx((0, 0))
    assert arc.radius_mm == pytest.approx(1)
    assert arc.sweep_angle_deg == pytest.approx(sweep)
    assert canvas.undo_last_operation() and not canvas.entities


@pytest.mark.parametrize("tracking", ["orthogonal", "polar"])
def test_three_point_arc_tracks_from_previous_point(qtbot: QtBot, tracking: str) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    dialog.snap_check.setChecked(False)
    dialog.tool_combo.setCurrentText("圆弧")
    if tracking == "orthogonal":
        dialog.orthogonal_check.setChecked(True)
    else:
        dialog.polar_check.setChecked(True)
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((10.5, 9))
    arc = canvas.entities[0]
    assert isinstance(arc, ArcEntity)
    assert arc.center_mm == pytest.approx((5, 4.5))
    end_angle = math.radians(arc.start_angle_deg + arc.sweep_angle_deg)
    assert (
        arc.center_mm[0] + arc.radius_mm * math.cos(end_angle),
        arc.center_mm[1] + arc.radius_mm * math.sin(end_angle),
    ) == pytest.approx((10, 9))


@pytest.mark.parametrize("exact", [False, True])
def test_three_point_arc_snap_and_exact_input_override_ortho(qtbot: QtBot, exact: bool) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    source = LineEntity(uuid4().hex, (12, 9), (20, 9))
    assert canvas.replace_draft_entities((source,))
    dialog.tool_combo.setCurrentText("圆弧")
    dialog.orthogonal_check.setChecked(True)
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((12, 9) if exact else (12.05, 9.05), exact_point=exact)
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity)
    end_angle = math.radians(arc.start_angle_deg + arc.sweep_angle_deg)
    assert (
        arc.center_mm[0] + arc.radius_mm * math.cos(end_angle),
        arc.center_mm[1] + arc.radius_mm * math.sin(end_angle),
    ) == pytest.approx((12, 9))


@pytest.mark.parametrize("tracking", ["orthogonal", "polar"])
def test_center_arc_tracks_from_last_point(qtbot: QtBot, tracking: str) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    dialog.snap_check.setChecked(False)
    dialog.arc_center_button.click()
    if tracking == "orthogonal":
        dialog.orthogonal_check.setChecked(True)
    else:
        dialog.polar_check.setChecked(True)
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((10.5, 9))
    arc = canvas.entities[0]
    assert isinstance(arc, ArcEntity)
    assert arc.center_mm == pytest.approx((0, 0))
    assert arc.radius_mm == pytest.approx(10)
    assert arc.start_angle_deg == pytest.approx(0)
    assert arc.sweep_angle_deg == pytest.approx(math.degrees(math.atan2(9, 10)))


def test_center_arc_tangent_snap_overrides_orthogonal_tracking(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    source = CircleEntity(uuid4().hex, (0, 0), 5)
    assert canvas.replace_draft_entities((source,))
    dialog.arc_center_button.click()
    dialog.orthogonal_check.setChecked(True)
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((10, 5), exact_point=True)
    canvas.add_coordinate_point((5.1, 0.1))
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity)
    assert canvas.current_snap_kind == "切点"
    assert arc.sweep_angle_deg == pytest.approx(90)


def test_arc_three_point_collinear_can_retry(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    bar = dialog.drawing_command_bar.input
    for value in ("ARC", "3P"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    for point in ((0, 0), (1, 0), (2, 0)):
        canvas.add_coordinate_point(point, exact_point=True)
    assert not canvas.entities and canvas.has_pending_geometry
    canvas.add_coordinate_point((1, 1), exact_point=True)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], ArcEntity)


@pytest.mark.parametrize("independent_2d", [False, True])
def test_center_arc_rejects_start_at_center_and_retries(qtbot: QtBot, independent_2d: bool) -> None:
    dialog = SketchEditorDialog(select_committed_entities=independent_2d)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    dialog.arc_center_button.click()
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((0, 0), exact_point=True)
    assert canvas.pending_point_count == 1
    assert "起点" in canvas.message and not canvas.entities
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((0, 10), exact_point=True)
    assert len(canvas.entities) == 1
    arc = canvas.entities[0]
    assert isinstance(arc, ArcEntity)
    assert arc.center_mm == pytest.approx((0, 0))
    assert arc.radius_mm == pytest.approx(10)


def test_arc_three_point_rejects_duplicate_second_point_and_retries(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    dialog.arc_three_point_button.click()
    canvas.add_coordinate_point((1, 0), exact_point=True)
    canvas.add_coordinate_point((1, 0), exact_point=True)
    assert canvas.pending_point_count == 1 and "不能" in canvas.message
    canvas.add_coordinate_point((0, 1), exact_point=True)
    canvas.add_coordinate_point((-1, 0), exact_point=True)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], ArcEntity)


def test_three_point_arc_saved_and_reopened(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.formats.providers.dxf_provider import read_sketch_dxf
    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.arc_three_point_button.click()
    for point in ((10, 0), (-10, 0), (0, 10)):
        editor.canvas.add_coordinate_point(point, exact_point=True)
    arc = editor.canvas.entities[-1]
    assert isinstance(arc, ArcEntity) and arc.sweep_angle_deg == pytest.approx(-270)
    editor.finish_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor and not unit.is_busy)
    dxf = tmp_path / "three-point.dxf"

    def choose_dxf(*_args: object) -> tuple[str, str]:
        return str(dxf), ""

    def accept_preview(dialog: DxfOutputPreviewDialog) -> int:
        return int(dialog.DialogCode.Accepted)

    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName", choose_dxf)
    monkeypatch.setattr(DxfOutputPreviewDialog, "exec", accept_preview)
    window.act_export.trigger()
    qtbot.waitUntil(lambda: dxf.exists() and not unit.is_busy, timeout=20000)
    imported = read_sketch_dxf(dxf)
    exported_arc = next(
        entity for entity in imported.sketch.entities if isinstance(entity, ArcEntity)
    )
    assert exported_arc.center_mm == pytest.approx((0, 0))
    assert exported_arc.radius_mm == pytest.approx(10)
    assert exported_arc.sweep_angle_deg == pytest.approx(-270)
    loaded = window.loaded_document()
    assert loaded is not None
    path = tmp_path / "three-point.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert any(arc in sketch.entities for sketch in services.kernel.sketches)
    reopened.bus.undo()
    assert not services.kernel.sketches
    reopened.bus.redo()
    assert any(arc in sketch.entities for sketch in services.kernel.sketches)


def test_three_point_arc_mouse_preview_and_escape(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    dialog.resize(1000, 700)
    dialog.show()
    canvas = dialog.canvas
    dialog.arc_three_point_button.click()
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.add_coordinate_point((-10, 0), exact_point=True)
    QTest.mouseMove(canvas, canvas.local_to_screen((0, 10)))
    assert not canvas.grab().isNull()
    assert canvas.has_pending_geometry and not canvas.entities
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.has_pending_geometry and not canvas.entities


def test_arc_defaults_to_three_points_and_center_button_selects_center_mode(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    assert canvas.set_tool("圆弧")
    for point in ((1, 0), (0, 1), (-1, 0)):
        canvas.add_coordinate_point(point, exact_point=True)
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity) and arc.center_mm == pytest.approx((0, 0))
    dialog.arc_center_button.click()
    for point in ((10, 10), (20, 10), (10, 20)):
        canvas.add_coordinate_point(point, exact_point=True)
    centered = canvas.entities[-1]
    assert isinstance(centered, ArcEntity)
    assert centered.center_mm == (10, 10) and centered.radius_mm == 10


def test_arc_canvas_keyboard_coordinates_work_after_first_point(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    assert canvas.set_tool("圆弧")
    canvas.add_coordinate_point((10, 0), exact_point=True)
    canvas.setFocus()
    QTest.keyClicks(canvas, "0,10")
    bar = dialog.drawing_command_bar.input
    assert bar.text() == "0,10"
    QTest.keyClick(bar, Qt.Key.Key_Return)
    canvas.add_coordinate_point((-10, 0), exact_point=True)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], ArcEntity)
    assert canvas.entities[0].center_mm == pytest.approx((0, 0))


def test_three_point_arc_tangent_snap_supports_small_valid_geometry(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    factor = 1e-7
    target = CircleEntity(uuid4().hex, (0, 0), 5 * factor)
    assert canvas.replace_draft_entities((target,))
    assert canvas.set_tool("圆弧")
    canvas._scale = 1e8
    canvas.add_coordinate_point((10 * factor, 5 * factor), exact_point=True)
    canvas.add_coordinate_point((15 * factor, 0), exact_point=True)
    canvas.add_coordinate_point((5.001 * factor, 0.001 * factor))
    assert canvas.current_snap_kind == "切点"
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity)
    assert arc.center_mm == pytest.approx((10 * factor, 0), abs=1e-12)
    assert arc.radius_mm == pytest.approx(5 * factor, abs=1e-12)


def test_three_point_arc_snaps_to_much_smaller_circle(qtbot: QtBot) -> None:
    dialog = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(dialog)
    canvas = dialog.canvas
    radius = 100_000_000.0
    center_x = radius + 5
    target = CircleEntity(uuid4().hex, (0, 0), 5)
    assert canvas.replace_draft_entities((target,))
    assert canvas.set_tool("圆弧")
    canvas._scale = 100
    canvas.add_coordinate_point((center_x, radius), exact_point=True)
    canvas.add_coordinate_point((center_x + radius, 0), exact_point=True)
    canvas.add_coordinate_point((5.001, 0.001))
    assert canvas.current_snap_kind == "切点"
    arc = canvas.entities[-1]
    assert isinstance(arc, ArcEntity)
    assert arc.center_mm == pytest.approx((center_x, 0), abs=1e-4)
    assert arc.radius_mm == pytest.approx(radius, abs=1e-4)


def test_tangent_line_captures_two_circles_with_one_mode_activation(qtbot: QtBot) -> None:
    from mycad.core.fillet_curves import tangent_on_curves

    editor = SketchEditorDialog(select_committed_entities=True, continuous_lines=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    first = CircleEntity(uuid4().hex, (0, 0), 5)
    second = CircleEntity(uuid4().hex, (30, 0), 5)
    assert canvas.replace_draft_entities((first, second))
    assert canvas.set_tool("直线")
    assert canvas.begin_line_tangent_pick()
    QTest.mouseMove(canvas, canvas.local_to_screen((0, 5)))
    assert canvas.current_snap_kind == "待定切点"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 5)))
    QTest.mouseMove(canvas, canvas.local_to_screen((30, 5)))
    assert canvas.current_snap_kind == "切点"
    assert canvas.previewed_tangent_line is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((30, 5)))
    line = canvas.entities[-1]
    assert isinstance(line, LineEntity)
    assert tangent_on_curves(line, first) and tangent_on_curves(line, second)
    assert canvas.undo_last_operation()
    assert canvas.entities == [first, second]


@pytest.mark.parametrize("tool", ["直线", "圆", "圆弧"])
def test_tangent_capture_button_creates_geometry_between_circles(qtbot: QtBot, tool: str) -> None:
    from mycad.core.fillet_curves import tangent_on_curves

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    assert canvas.replace_draft_entities((first, second))
    editor.tool_buttons[tool].click()
    assert editor.tangent_capture_button.isEnabled()
    editor.tangent_capture_button.click()
    points = ((0, 2), (10, 2)) if tool == "直线" else ((1.7, 1.1), (8.3, 1.1))
    for point in points:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if tool != "直线":
        bar = editor.drawing_command_bar.input
        bar.setText("4")
        QTest.keyClick(bar, Qt.Key.Key_Return)
    result = canvas.entities[-1]
    assert isinstance(result, {"直线": LineEntity, "圆": CircleEntity, "圆弧": ArcEntity}[tool])
    assert tangent_on_curves(result, first) and tangent_on_curves(result, second)
    assert canvas.undo_last_operation()
    assert canvas.entities == [first, second]


@pytest.mark.parametrize("tool", ["圆", "圆弧"])
def test_two_object_tangency_shows_deferred_snap_on_mouse(qtbot: QtBot, tool: str) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = ArcEntity(uuid4().hex, (10, 0), 2, 0, 180)
    assert canvas.replace_draft_entities((first, second))
    editor.tool_buttons[tool].click()
    editor.tangent_capture_button.click()
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseMove(canvas, canvas.local_to_screen(point))
        assert canvas.current_snap_kind == "待定切点"
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert canvas.circle_ttr_radius_pending or canvas.arc_ttr_radius_pending
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.circle_ttr_active and not canvas.arc_ttr_active
    assert canvas.current_snap_kind == ""
    assert canvas.entities == [first, second]


@pytest.mark.parametrize("tool", ["直线", "圆", "圆弧"])
@pytest.mark.parametrize("both_arcs", [False, True])
def test_tangent_capture_supports_finite_arc_sources(
    qtbot: QtBot, tool: str, both_arcs: bool
) -> None:
    from mycad.core.fillet_curves import tangent_on_curves

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    first: CircleEntity | ArcEntity = (
        ArcEntity(uuid4().hex, (0, 0), 2, 0, 180)
        if both_arcs
        else CircleEntity(uuid4().hex, (0, 0), 2)
    )
    second = ArcEntity(uuid4().hex, (10, 0), 2, 0, 180)
    assert canvas.replace_draft_entities((first, second))
    editor.tool_buttons[tool].click()
    editor.tangent_capture_button.click()
    points = ((0, 2), (10, 2)) if tool == "直线" else ((1.7, 1.1), (8.3, 1.1))
    for point in points:
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    if tool != "直线":
        editor.drawing_command_bar.input.setText("4")
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    result = canvas.entities[-1]
    assert isinstance(result, {"直线": LineEntity, "圆": CircleEntity, "圆弧": ArcEntity}[tool])
    assert tangent_on_curves(result, first) and tangent_on_curves(result, second)
    assert canvas.undo_last_operation()
    assert canvas.entities == [first, second]


def test_tangent_capture_line_no_solution_keeps_draft_and_can_cancel(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    outer = CircleEntity(uuid4().hex, (0, 0), 10)
    inner = CircleEntity(uuid4().hex, (2, 0), 2)
    assert canvas.replace_draft_entities((outer, inner))
    editor.tool_buttons["直线"].click()
    editor.tangent_capture_button.click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 10)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((2, 2)))
    assert canvas.entities == [outer, inner]
    assert canvas.line_tangent_active
    assert "公共切线" in canvas.message
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert not canvas.line_tangent_active
    assert canvas.entities == [outer, inner]


@pytest.mark.parametrize("tool", ["圆", "圆弧"])
@pytest.mark.parametrize("dynamic", [False, True])
def test_two_tangent_radius_can_be_typed_from_canvas(
    qtbot: QtBot, tool: str, dynamic: bool
) -> None:
    from PySide6.QtWidgets import QApplication

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    assert canvas.replace_draft_entities((first, second))
    editor.dynamic_input_check.setChecked(dynamic)
    editor.tool_buttons[tool].click()
    editor.tangent_capture_button.click()
    for point in ((1.7, 1.1), (8.3, 1.1)):
        QTest.mouseMove(canvas, canvas.local_to_screen(point))
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    canvas.setFocus()
    QTest.keyClicks(canvas, "4")
    focused = QApplication.focusWidget()
    assert focused is not None
    QTest.keyClick(focused, Qt.Key.Key_Return)
    assert len(canvas.entities) == 3
    assert isinstance(canvas.entities[-1], CircleEntity if tool == "圆" else ArcEntity)
    assert canvas.entities[-1].radius_mm == pytest.approx(4)


def test_two_object_tangent_button_rejects_incomplete_line(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.tool_buttons["直线"].click()
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.tangent_capture_button.click()
    assert not editor.canvas.line_tangent_active
    assert editor.canvas.pending_point_count == 1
    assert "完成或取消当前直线" in editor.canvas.message


def test_two_object_tangent_button_rejects_blank_second_pick(qtbot: QtBot) -> None:
    from mycad.core.fillet_curves import tangent_on_curves

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    first = CircleEntity(uuid4().hex, (0, 0), 2)
    second = CircleEntity(uuid4().hex, (10, 0), 2)
    assert canvas.replace_draft_entities((first, second))
    editor.tool_buttons["直线"].click()
    editor.tangent_capture_button.click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((0, 2)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 5)))
    assert canvas.entities == [first, second]
    assert canvas.line_tangent_active
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 2)))
    line = canvas.entities[-1]
    assert isinstance(line, LineEntity)
    assert tangent_on_curves(line, first) and tangent_on_curves(line, second)
