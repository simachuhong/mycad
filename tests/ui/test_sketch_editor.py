# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The sketch editor keeps drawing in a disposable draft until Finish."""

from __future__ import annotations

import math
from uuid import uuid4

import pytest
from PySide6.QtCore import QPoint, Qt
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
    dialog = window.active_sketch_dialog()
    assert dialog is not None
    assert dialog.plane_combo.currentText() == "所选面"
    dialog.canvas.set_snapping_enabled(False)
    dialog.canvas.add_coordinate_point((0.0, 0.0))
    dialog.canvas.add_coordinate_point((10.0, 0.0))
    dialog.finish_button.click()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and (
                loaded.document.commands[-1].id == "sketch.create"
                or "失败" in window.status_command.text()
            )
        ),
        timeout=5000,
    )
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
    loaded = new_document(services)
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
    loaded = new_document(services)
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
