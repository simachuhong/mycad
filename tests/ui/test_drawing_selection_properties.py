# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Selection-linked properties in the independent 2D workspace."""

import gc
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import LineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


@pytest.mark.parametrize("image_count", [1, 2])
def test_image_property_layer_change_rejects_stale_document(qtbot: QtBot, image_count: int) -> None:
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from mycad import app
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    layers = editor.layer_table.add(SketchLayer("目标"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    QApplication.clipboard().setImage(image)
    try:
        for index in range(image_count):
            assert editor.canvas.begin_clipboard_paste()
            editor.canvas.add_coordinate_point((20 + index * 10, 20), exact_point=True)
        rasters = services.kernel.drawing_rasters
        editor.canvas.selected_raster_ids = {item.image_id for item in rasters}
        editor.canvas.changed.emit()
        combo = editor.property_layer_combo
        assert combo is not None
        target = combo.findData("目标")
        assert target >= 0
        updated = replace(rasters[0], origin_mm=(40, 50))
        loaded.bus.execute(
            "drawing.raster.update", updated.to_mapping(version=2), "local", version=2
        )
        assert editor.canvas.source_context_revision != loaded.document.revision
        before = tuple(loaded.document.commands)
        combo.activated.emit(target)
        assert tuple(loaded.document.commands) == before
        assert services.kernel.drawing_rasters[0].origin_mm == (40, 50)
        assert services.kernel.drawing_rasters[0].layer_name == "0"
        assert "变化" in editor.status_label.text()
        combo = editor.property_layer_combo
        assert combo is not None
        combo.activated.emit(combo.findData("目标"))
        assert services.kernel.drawing_rasters[0].origin_mm == (40, 50)
        assert all(item.layer_name == "目标" for item in services.kernel.drawing_rasters)
    finally:
        QApplication.clipboard().clear()


@pytest.mark.parametrize("image_count", [1, 2])
def test_image_delete_rejects_stale_document_and_can_retry(qtbot: QtBot, image_count: int) -> None:
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from mycad import app
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    QApplication.clipboard().setImage(image)
    try:
        for index in range(image_count):
            assert editor.canvas.begin_clipboard_paste()
            editor.canvas.add_coordinate_point((20 + index * 10, 20), exact_point=True)
        rasters = services.kernel.drawing_rasters
        editor.canvas.selected_raster_ids = {item.image_id for item in rasters}
        updated = replace(rasters[0], origin_mm=(40, 50))
        loaded.bus.execute(
            "drawing.raster.update", updated.to_mapping(version=2), "local", version=2
        )
        before = tuple(loaded.document.commands)
        assert not editor.canvas.delete_selected()
        assert tuple(loaded.document.commands) == before
        assert len(services.kernel.drawing_rasters) == image_count
        assert services.kernel.drawing_rasters[0].origin_mm == (40, 50)
        assert "变化" in editor.canvas.message
        assert editor.canvas.delete_selected()
        assert not services.kernel.drawing_rasters
    finally:
        QApplication.clipboard().clear()


def test_non_drawing_editor_keeps_hidden_property_controls_alive(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=False)
    qtbot.addWidget(editor)
    editor.show()
    qtbot.waitExposed(editor)
    gc.collect()
    editor.canvas.changed.emit()
    assert not editor.property_edit_dimension_button.isVisible()


def test_empty_selection_shows_own_document_metadata_across_switches(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    first = window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None

    def rows(target: SketchEditorDialog) -> dict[str, str]:
        values: dict[str, str] = {}
        for row in range(target.properties_table.rowCount()):
            name, value = target.properties_table.item(row, 0), target.properties_table.item(row, 1)
            assert name is not None and value is not None
            values[name.text()] = value.text()
        return values

    assert set(rows(editor)) == {"编号", "修订", "材料", "来源", "名称", "备注"}
    assert rows(editor)["编号"] == "" and rows(editor)["名称"] == "—"
    first.loaded.document.set_metadata("part_name", "第一张图")
    qtbot.waitUntil(lambda: rows(editor).get("名称") == "第一张图", timeout=10000)
    assert rows(editor)["备注"] == "—"
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    assert rows(editor)["对象类型"] == "直线" and "名称" not in rows(editor)
    editor.canvas.selected_entity_ids.clear()
    editor.canvas.changed.emit()
    assert rows(editor)["名称"] == "第一张图"

    second = window.new_session_document("sketch")
    second_editor = window.active_sketch_dialog()
    assert second_editor is not None and second_editor is not editor
    second.loaded.document.set_metadata("part_name", "第二张图")
    qtbot.waitUntil(lambda: rows(second_editor).get("名称") == "第二张图", timeout=10000)
    first.loaded.document.set_metadata("part_name", "第一张图已更新")
    window.activate_session_document(first.loaded.document.document_id)
    assert window.active_sketch_dialog() is editor
    assert rows(editor)["名称"] == "第一张图已更新"


def test_selected_line_properties_follow_selection(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    rows: dict[str, str] = {}
    for row in range(editor.properties_table.rowCount()):
        name = editor.properties_table.item(row, 0)
        value = editor.properties_table.item(row, 1)
        assert name is not None and value is not None
        rows[name.text()] = value.text()
    assert rows["对象类型"] == "直线"
    assert rows["图层"] == "0"
    assert rows["长度"] == "5 mm"
    editor.canvas.selected_entity_ids.clear()
    editor.canvas.changed.emit()
    assert editor.properties_table.rowCount() == 0


def test_window_crossing_and_subtraction_update_properties(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer, SketchLayerTable

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    qtbot.waitExposed(editor)
    canvas = editor.canvas
    layers = SketchLayerTable().add(SketchLayer("另层"))
    canvas.set_layer_table(layers, "0")
    inside = LineEntity(uuid4().hex, (-5, 0), (5, 0))
    crossing = LineEntity(uuid4().hex, (-30, 5), (0, 5), layer_name="另层")
    canvas.set_background_sketches(
        (Sketch(uuid4().hex, WorkPlaneFrame.xy(), (inside, crossing), layers=layers),),
        WorkPlaneFrame.xy(),
    )
    canvas.set_tool("选择元素")

    def rows() -> dict[str, str]:
        values: dict[str, str] = {}
        for row in range(editor.properties_table.rowCount()):
            name, value = editor.properties_table.item(row, 0), editor.properties_table.item(row, 1)
            assert name is not None and value is not None
            values[name.text()] = value.text()
        return values

    def box(first: tuple[float, float], second: tuple[float, float]) -> None:
        start, end = canvas.local_to_screen(first), canvas.local_to_screen(second)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)

    box((-20, 15), (20, -15))
    assert canvas.selected_entity_ids == {inside.entity_id}
    assert rows()["选中数量"] == "1" and rows()["图层"] == "0"
    box((20, 15), (-20, -15))
    assert canvas.selected_entity_ids == {inside.entity_id, crossing.entity_id}
    assert rows()["选中数量"] == "2" and rows()["图层"] == "多种"
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        canvas.local_to_screen((-10, 5)),
    )
    assert canvas.selected_entity_ids == {inside.entity_id}
    assert rows()["选中数量"] == "1" and rows()["图层"] == "0"


def test_selected_image_and_dimension_properties(qtbot: QtBot) -> None:
    from PySide6.QtGui import QImage

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    raster = raster_from_clipboard_image(image, "0")
    editor.canvas.drawing_rasters = (raster,)
    editor.canvas.selected_raster_ids = {raster.image_id}
    editor.canvas.changed.emit()

    def rows() -> dict[str, str]:
        result: dict[str, str] = {}
        for row in range(editor.properties_table.rowCount()):
            name, value = editor.properties_table.item(row, 0), editor.properties_table.item(row, 1)
            assert name is not None and value is not None
            result[name.text()] = value.text()
        return result

    assert rows()["对象类型"] == "图片"
    assert rows()["图层"] == "0"
    assert rows()["宽度"] == f"{raster.width_mm:g} mm"
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    assert editor.canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        5,
        "mm",
        layer_name="DIM",
    )
    editor.canvas.constraints = [dimension]
    editor.canvas.selected_raster_ids.clear()
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    editor.canvas.changed.emit()
    assert rows()["对象类型"] == "尺寸标注"
    assert rows()["图层"] == "DIM"
    assert rows()["驱动"] == "是"
    assert rows()["约束值"] == "5 mm"


def test_property_layer_edit_keeps_drawing_layer_and_undoes(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    layers = editor.layer_table.add(SketchLayer("轮廓"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    combo = editor.property_layer_combo
    assert combo is not None
    target = combo.findText("轮廓")
    assert target >= 0
    combo.activated.emit(target)
    assert editor.canvas.entities[0].layer_name == "轮廓"
    assert editor.layer_combo.currentText() == "0"
    window.request_undo()
    assert editor.canvas.entities[0].layer_name == "0"
    assert editor.layer_combo.currentText() == "0"


def test_property_mixed_layers_support_layer_named_multiple(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    layers = editor.layer_table.add(SketchLayer("多种"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    first = LineEntity(uuid4().hex, (0, 0), (3, 0))
    second = LineEntity(uuid4().hex, (0, 1), (3, 1), layer_name="多种")
    assert editor.canvas.replace_draft_entities((first, second))
    editor.canvas.selected_entity_ids = {first.entity_id, second.entity_id}
    editor.canvas.changed.emit()
    combo = editor.property_layer_combo
    assert combo is not None
    target = combo.findData("多种")
    assert target >= 0
    combo.activated.emit(target)
    assert [entity.layer_name for entity in editor.canvas.entities] == ["多种", "多种"]
    window.request_undo()
    assert [entity.layer_name for entity in editor.canvas.entities] == ["0", "多种"]


def test_saved_line_property_layer_edit_replays_and_reopens(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    layers = editor.layer_table.add(SketchLayer("轮廓"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    combo = editor.property_layer_combo
    assert combo is not None
    target = combo.findData("轮廓")
    assert target >= 0
    combo.activated.emit(target)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].layer_name == "轮廓", editor.status_label.text()
    assert editor.layer_combo.currentText() == "0"
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].layer_name == "0"
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].layer_name == "轮廓"
    path = tmp_path / "property-layer.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches[0].entities[0].layer_name == "轮廓"


def test_image_property_layer_edit_preserves_image_and_replays(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    layers = editor.layer_table.add(SketchLayer("图片层"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    QApplication.clipboard().setImage(image)
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((4, 7), exact_point=True)
    original = services.kernel.drawing_rasters[0]
    editor.canvas.selected_raster_ids = {original.image_id}
    editor.canvas.changed.emit()
    combo = editor.property_layer_combo
    assert combo is not None
    target = combo.findData("图片层")
    assert target >= 0
    combo.activated.emit(target)
    assert services.kernel.drawing_rasters[0].layer_name == "图片层"
    assert services.kernel.drawing_rasters[0].origin_mm == original.origin_mm
    assert editor.layer_combo.currentText() == "0"
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_rasters[0].layer_name == "0"
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.drawing_rasters[0].layer_name == "图片层"
    path = tmp_path / "image-property-layer.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_rasters[0].layer_name == "图片层"
    QApplication.clipboard().clear()


def test_draft_driving_dimension_property_layer_edit_is_undoable(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    layers = editor.layer_table.add(SketchLayer("标注层"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    assert editor.canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        5,
        "mm",
        layer_name="0",
    )
    editor.canvas.constraints = [dimension]
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    editor.canvas.changed.emit()
    combo = editor.property_layer_combo
    assert combo is not None
    target = combo.findData("标注层")
    assert target >= 0
    combo.activated.emit(target)
    assert editor.canvas.constraints[0].layer_name == "标注层"
    assert editor.canvas.constraints[0].value == 5
    assert editor.canvas.constraints[0].driving
    assert editor.canvas.entities == [line]
    assert editor.layer_combo.currentText() == "0"
    window.request_undo()
    assert editor.canvas.constraints[0] == dimension
    assert editor.canvas.entities == [line]


def test_saved_driving_dimension_property_layer_replays(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        5,
        "mm",
        layer_name="0",
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    layers = editor.layer_table.add(SketchLayer("标注层"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    editor.canvas.changed.emit()
    combo = editor.property_layer_combo
    assert combo is not None
    target = combo.findData("标注层")
    assert target >= 0
    combo.activated.emit(target)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].constraints[0].layer_name == "标注层", (
        editor.status_label.text()
    )
    assert services.kernel.sketches[0].entities[0] == line
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].constraints[0].layer_name == "0"
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].constraints[0].layer_name == "标注层"
    path = tmp_path / "dimension-property-layer.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches[0].constraints[0].layer_name == "标注层"


def test_real_canvas_clicks_update_image_and_dimension_properties(qtbot: QtBot) -> None:
    from dataclasses import replace

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    editor.tool_buttons["选择元素"].click()
    canvas = editor.canvas
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    raster = replace(
        raster_from_clipboard_image(image, "0"), origin_mm=(20, 20), width_mm=10, height_mm=5
    )
    canvas.set_drawing_rasters((raster,))
    line = LineEntity(uuid4().hex, (-10, 0), (0, 0))
    assert canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(-5, 8),
    )
    canvas.constraints = [dimension]
    canvas.changed.emit()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((25, 22)))
    assert canvas.selected_raster_ids == {raster.image_id}
    image_type = editor.properties_table.item(1, 1)
    assert image_type is not None and image_type.text() == "图片"
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=layout.label.toPoint())
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    dimension_type = editor.properties_table.item(1, 1)
    assert dimension_type is not None and dimension_type.text() == "尺寸标注"


def test_ctrl_click_dimension_keeps_selected_picture(qtbot: QtBot) -> None:
    from dataclasses import replace

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1400, 900)
    editor.show()
    editor.tool_buttons["选择元素"].click()
    canvas = editor.canvas
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    raster = replace(
        raster_from_clipboard_image(image, "0"), origin_mm=(20, 20), width_mm=10, height_mm=5
    )
    canvas.set_drawing_rasters((raster,))
    line = LineEntity(uuid4().hex, (-10, 0), (0, 0))
    assert canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        position_mm=(-5, 8),
    )
    canvas.constraints = [dimension]
    canvas.changed.emit()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((25, 22)))
    layout = canvas.dimension_layout(dimension, canvas.dimension_entities())
    assert layout is not None
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        layout.label.toPoint(),
    )
    assert canvas.selected_raster_ids == {raster.image_id}
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    value = editor.properties_table.item(1, 1)
    assert value is not None and value.text() == "混合选择"


def test_property_page_opens_selected_dimension_editor(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    assert editor.canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        5,
        "mm",
        layer_name="0",
    )
    editor.canvas.constraints = [dimension]
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    editor.canvas.changed.emit()
    assert editor.property_edit_dimension_button.isEnabled()
    editor.property_edit_dimension_button.click()
    assert editor.dimensions.candidate == dimension
    assert editor.dimensions.value_editor.value() == 5
    assert not editor.dimensions.value_editor.isReadOnly()


def test_property_page_edits_saved_driving_dimension_and_undoes(qtbot: QtBot) -> None:
    import math

    from mycad import app
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        5,
        "mm",
        layer_name="0",
        position_mm=(2.5, 4),
    )
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    editor.canvas.changed.emit()
    editor.property_edit_dimension_button.click()
    editor.dimensions.value_editor.setValue(10)
    original, candidate = editor.dimensions.original, editor.dimensions.candidate
    assert original is not None and candidate is not None
    qtbot.waitUntil(
        lambda: editor.dimensions.accepted_preview(original, candidate) is not None, timeout=15000
    )
    preview = editor.dimensions.accepted_preview(original, candidate)
    assert preview is not None and preview.status == "success"
    editor.dimensions.apply_button.click()
    if preview.branch_changes:
        editor.dimensions.apply_button.click()
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.sketches[0].constraints[0].value == 10,
        timeout=15000,
    )
    updated = services.kernel.sketches[0].entities[0]
    assert isinstance(updated, LineEntity)
    assert math.isclose(math.dist(updated.start_mm, updated.end_mm), 10, abs_tol=1e-6)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].constraints[0].value == 5


def test_other_entity_geometry_properties(qtbot: QtBot) -> None:
    from mycad.core.sketch import (
        ArcEntity,
        PointEntity,
        PolylineEntity,
        RectangleEntity,
        SplineEntity,
    )

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    arc = ArcEntity(uuid4().hex, (1, 2), 3, 30, -90)
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (4, 0), (4, 3)), closed=True)
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (4, 3))
    point = PointEntity(uuid4().hex, (6, 7))
    spline = SplineEntity(uuid4().hex, ((0, 0), (1, 1), (2, 1), (3, 0)))
    assert editor.canvas.replace_draft_entities((arc, polyline, rectangle, point, spline))

    def selected_rows(identity: str) -> dict[str, str]:
        editor.canvas.selected_entity_ids = {identity}
        editor.canvas.changed.emit()
        result: dict[str, str] = {}
        for row in range(editor.properties_table.rowCount()):
            name, value = editor.properties_table.item(row, 0), editor.properties_table.item(row, 1)
            assert name is not None and value is not None
            result[name.text()] = value.text()
        return result

    assert selected_rows(arc.entity_id)["扫掠角"] == "-90°"
    assert selected_rows(polyline.entity_id)["顶点数"] == "3"
    assert selected_rows(polyline.entity_id)["闭合"] == "是"
    assert selected_rows(rectangle.entity_id)["宽度"] == "4 mm"
    assert selected_rows(point.entity_id)["位置"] == "6, 7"
    assert selected_rows(spline.entity_id)["控制点数"] == "4"


def test_property_layer_edit_mixed_image_saved_and_draft_is_atomic(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    saved = LineEntity(uuid4().hex, (0, 0), (4, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    layers = editor.layer_table.add(SketchLayer("目标"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    QApplication.clipboard().setImage(image)
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((20, 20), exact_point=True)
    raster = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (0, 3), (4, 3))
    assert editor.canvas.replace_draft_entities((draft,))
    editor.canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    editor.canvas.selected_raster_ids = {raster.image_id}
    editor.canvas.changed.emit()
    combo = editor.property_layer_combo
    assert combo is not None
    target = combo.findData("目标")
    assert target >= 0
    combo.activated.emit(target)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].layer_name == "目标", editor.status_label.text()
    assert editor.canvas.entities[0].layer_name == "目标"
    assert services.kernel.drawing_rasters[0].layer_name == "目标"
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].layer_name == "0"
    assert editor.canvas.entities[0].layer_name == "0"
    assert services.kernel.drawing_rasters[0].layer_name == "0"
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].layer_name == "目标"
    assert editor.canvas.entities[0].layer_name == "目标"
    assert services.kernel.drawing_rasters[0].layer_name == "目标"
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    path = tmp_path / "mixed-property-layer.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert all(
        entity.layer_name == "目标"
        for sketch in reopened.kernel.sketches
        for entity in sketch.entities
    )
    assert reopened.kernel.drawing_rasters[0].layer_name == "目标"
    QApplication.clipboard().clear()


def test_property_layer_edit_mixed_image_and_draft_without_saved_sketch(qtbot: QtBot) -> None:
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from mycad import app
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    layers = editor.layer_table.add(SketchLayer("目标"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    QApplication.clipboard().setImage(image)
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((20, 20), exact_point=True)
    raster = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (0, 3), (4, 3))
    assert editor.canvas.replace_draft_entities((draft,))
    editor.canvas.selected_entity_ids = {draft.entity_id}
    editor.canvas.selected_raster_ids = {raster.image_id}
    editor.canvas.changed.emit()
    combo = editor.property_layer_combo
    assert combo is not None
    target = combo.findData("目标")
    assert target >= 0
    combo.activated.emit(target)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert editor.canvas.entities[0].layer_name == "目标", editor.status_label.text()
    assert services.kernel.drawing_rasters[0].layer_name == "目标"
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert editor.canvas.entities[0].layer_name == "0"
    assert services.kernel.drawing_rasters[0].layer_name == "0"
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert editor.canvas.entities[0].layer_name == "目标"
    assert services.kernel.drawing_rasters[0].layer_name == "目标"
    QApplication.clipboard().clear()


def test_property_layer_edit_rolls_back_image_if_draft_update_fails(
    qtbot: QtBot, monkeypatch: object
) -> None:
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from pytest import MonkeyPatch

    from mycad import app
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    assert isinstance(monkeypatch, MonkeyPatch)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    layers = editor.layer_table.add(SketchLayer("目标"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    QApplication.clipboard().setImage(image)
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((20, 20), exact_point=True)
    raster = services.kernel.drawing_rasters[0]
    draft = LineEntity(uuid4().hex, (0, 3), (4, 3))
    assert editor.canvas.replace_draft_entities((draft,))
    editor.canvas.selected_entity_ids = {draft.entity_id}
    editor.canvas.selected_raster_ids = {raster.image_id}
    editor.canvas.changed.emit()
    before = loaded.document.command_count

    def reject_update(*args: object, **kwargs: object) -> bool:
        return False

    monkeypatch.setattr(editor.canvas, "replace_draft_entities_atomically", reject_update)
    combo = editor.property_layer_combo
    assert combo is not None
    combo.activated.emit(combo.findData("目标"))
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert loaded.document.command_count == before
    assert editor.canvas.entities == [draft]
    assert services.kernel.drawing_rasters[0] == raster
    assert "回滚" in editor.status_label.text()
    QApplication.clipboard().clear()


def test_property_mixed_layer_preserves_real_saved_tangency(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    assert editor.canvas.replace_draft_entities((line, circle))
    window.act_cross_sketch_tangency.trigger()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((1, 0))
    )
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 4))
    )
    first_canvas = editor.canvas
    qtbot.waitUntil(lambda: bool(first_canvas.constraints) and not unit.is_busy, timeout=10000)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    constraint = services.kernel.sketches[0].constraints[0]
    layers = editor.layer_table.add(SketchLayer("目标"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    QApplication.clipboard().setImage(image)
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((30, 20), exact_point=True)
    editor.canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    editor.canvas.selected_raster_ids = {services.kernel.drawing_rasters[0].image_id}
    editor.canvas.changed.emit()
    combo = editor.property_layer_combo
    assert combo is not None
    combo.activated.emit(combo.findData("目标"))
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert all(entity.layer_name == "目标" for entity in services.kernel.sketches[0].entities), (
        editor.status_label.text()
    )
    assert services.kernel.sketches[0].constraints == (constraint,)
    assert services.kernel.drawing_rasters[0].layer_name == "目标"
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert all(entity.layer_name == "0" for entity in services.kernel.sketches[0].entities)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    path = tmp_path / "tangent-property-layer.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert reopened.kernel.sketches[0].constraints == (constraint,)
    assert reopened.kernel.drawing_rasters[0].layer_name == "目标"
    QApplication.clipboard().clear()


def test_property_mixed_layer_preserves_tangency_between_saved_records(qtbot: QtBot) -> None:
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from mycad import app
    from mycad.core.cross_sketch_tangency import CrossSketchRef, CrossSketchTangency
    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, first, session_identity=0)
    app.commit_new_sketch(services, loaded, second, session_identity=0)
    relation = CrossSketchTangency(
        uuid4().hex,
        CrossSketchRef(first.sketch_id, line.entity_id),
        CrossSketchRef(second.sketch_id, circle.entity_id),
        "line_left",
    )
    app.commit_cross_sketch_tangency(services, loaded, relation, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    layers = editor.layer_table.add(SketchLayer("目标"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    QApplication.clipboard().setImage(image)
    assert editor.canvas.begin_clipboard_paste()
    editor.canvas.add_coordinate_point((30, 20), exact_point=True)
    editor.canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    editor.canvas.selected_raster_ids = {services.kernel.drawing_rasters[0].image_id}
    editor.canvas.changed.emit()
    combo = editor.property_layer_combo
    assert combo is not None
    combo.activated.emit(combo.findData("目标"))
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert all(sketch.entities[0].layer_name == "目标" for sketch in services.kernel.sketches), (
        editor.status_label.text()
    )
    assert services.kernel.cross_sketch_tangencies == (relation,)
    assert services.kernel.drawing_rasters[0].layer_name == "目标"
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert all(sketch.entities[0].layer_name == "0" for sketch in services.kernel.sketches)
    assert services.kernel.cross_sketch_tangencies == (relation,)
    QApplication.clipboard().clear()


def test_property_layer_edit_two_images_is_one_undo(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from mycad import app
    from mycad.core.persistence import save_document
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit, loaded = (
        window.active_sketch_dialog(),
        window.execution_unit,
        window.loaded_document(),
    )
    assert editor is not None and unit is not None and loaded is not None
    layers = editor.layer_table.add(SketchLayer("图片层"))
    editor.request_layer_update(layers, ".")
    qtbot.waitUntil(lambda: not unit.is_busy and editor.layer_table == layers, timeout=10000)
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    QApplication.clipboard().setImage(image)
    for position in ((10, 10), (30, 20)):
        assert editor.canvas.begin_clipboard_paste()
        editor.canvas.add_coordinate_point(position, exact_point=True)
    editor.canvas.selected_raster_ids = {
        image.image_id for image in services.kernel.drawing_rasters
    }
    editor.canvas.changed.emit()
    combo = editor.property_layer_combo
    assert combo is not None
    target = combo.findData("图片层")
    assert target >= 0
    count = loaded.document.command_count
    combo.activated.emit(target)
    assert loaded.document.command_count == count + 1
    assert all(image.layer_name == "图片层" for image in services.kernel.drawing_rasters)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert all(image.layer_name == "0" for image in services.kernel.drawing_rasters)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    path = tmp_path / "images-property-layer.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=[])
    app.open_app_document(reopened, path)
    assert all(image.layer_name == "图片层" for image in reopened.kernel.drawing_rasters)
    QApplication.clipboard().clear()


def test_properties_clear_when_selected_image_and_dimension_layer_frozen(qtbot: QtBot) -> None:
    from dataclasses import replace

    from PySide6.QtGui import QImage

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        layer_name="DIM",
    )
    editor.canvas.constraints = [dimension]
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    raster = raster_from_clipboard_image(image, "DIM")
    editor.canvas.set_drawing_rasters((raster,))
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    editor.canvas.selected_raster_ids = {raster.image_id}
    editor.canvas.changed.emit()
    assert editor.properties_table.rowCount() > 0
    layers = editor.layer_table.replace(replace(editor.layer_table.get("DIM"), frozen=True))
    editor.set_document_layers(layers, "DIM")
    assert not editor.canvas.selected_raster_ids
    assert not editor.canvas.selected_constraint_ids
    assert editor.properties_table.rowCount() == 0
