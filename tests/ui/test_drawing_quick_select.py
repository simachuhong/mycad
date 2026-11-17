# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Filter visible drawing entities through the command line."""

from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad.core.sketch import CircleEntity, LineEntity
from mycad.ui.quick_select import QuickSelectDialog
from mycad.ui.sketch_editor import SketchEditorDialog


def test_qselect_filters_visible_entities_by_type(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    circle = CircleEntity(uuid4().hex, (0, 10), 3)
    assert canvas.replace_draft_entities((line, circle))

    def choose_line() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.kind.setCurrentText("直线")
        dialog.accept()

    QTimer.singleShot(100, choose_line)
    bar = editor.drawing_command_bar.input
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.selected_entity_ids == {line.entity_id}
    assert canvas.entities == [line, circle]


def test_qselect_multiple_then_delete_with_keyboard_focus(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.activateWindow()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert canvas.replace_draft_entities((first, second))

    def choose_lines() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.kind.setCurrentText("直线")
        dialog.accept()

    bar = editor.drawing_command_bar.input
    bar.setFocus()
    qtbot.waitUntil(bar.hasFocus, timeout=10000)
    QTimer.singleShot(100, choose_lines)
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.selected_entity_ids == {first.entity_id, second.entity_id}
    editor.activateWindow()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is not None, timeout=10000)
    focused = QApplication.focusWidget()
    assert focused is not None
    QTest.keyClick(focused, Qt.Key.Key_Delete)
    assert canvas.entities == []
    assert canvas.undo_last_operation()
    assert canvas.entities == [first, second]


def test_qselect_multiple_delete_in_main_window(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    window.activateWindow()
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert canvas.replace_draft_entities((first, second))

    def choose_lines() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.kind.setCurrentText("直线")
        dialog.accept()

    bar = editor.drawing_command_bar.input
    bar.setFocus()
    qtbot.waitUntil(bar.hasFocus, timeout=10000)
    QTimer.singleShot(100, choose_lines)
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    window.activateWindow()
    qtbot.waitUntil(canvas.hasFocus, timeout=10000)
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert canvas.entities == []
    assert canvas.undo_last_operation()
    assert canvas.entities == [first, second]


def test_qselect_multiple_images_delete_and_undo(qtbot: QtBot) -> None:
    from PySide6.QtGui import QImage

    from mycad import app
    from mycad.ui.main_window import MainWindow

    image = QImage(8, 4, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    QApplication.clipboard().setImage(image)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    for point in ((0, 0), (30, 0)):
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point(point, exact_point=True)
    originals = services.kernel.drawing_rasters
    assert len(originals) == 2

    def choose_images() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.kind.setCurrentText("图片")
        dialog.accept()

    window.activateWindow()
    bar = editor.drawing_command_bar.input
    bar.setFocus()
    qtbot.waitUntil(bar.hasFocus, timeout=10000)
    QTimer.singleShot(100, choose_images)
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    window.activateWindow()
    qtbot.waitUntil(canvas.hasFocus, timeout=10000)
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert not services.kernel.drawing_rasters
    window.request_undo()
    qtbot.waitUntil(lambda: services.kernel.drawing_rasters == originals, timeout=10000)


def test_qselect_multiple_dimensions_delete_and_undo(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.activateWindow()
    canvas = editor.canvas
    lines = (
        LineEntity(uuid4().hex, (0, 0), (10, 0)),
        LineEntity(uuid4().hex, (0, 5), (20, 5)),
    )
    assert canvas.replace_draft_entities(lines)
    dimensions = tuple(
        SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(line.entity_id, "geometry"),),
            value,
            "mm",
        )
        for line, value in zip(lines, (10, 20), strict=True)
    )
    canvas.constraints.extend(dimensions)

    def choose_dimensions() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.kind.setCurrentText("尺寸标注")
        dialog.accept()

    bar = editor.drawing_command_bar.input
    bar.setFocus()
    qtbot.waitUntil(bar.hasFocus, timeout=10000)
    QTimer.singleShot(100, choose_dimensions)
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    editor.activateWindow()
    qtbot.waitUntil(canvas.hasFocus, timeout=10000)
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert not canvas.constraints
    assert canvas.entities == list(lines)
    assert canvas.undo_last_operation()
    assert tuple(canvas.constraints) == dimensions


def test_qselect_scope_exclusion_layer_append_and_cancel(qtbot: QtBot) -> None:
    from mycad.core.sketch import SketchLayer

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    editor.set_document_layers(editor.layer_table.add(SketchLayer("profile")), "DIM")
    canvas = editor.canvas
    profile_line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="profile")
    default_line = LineEntity(uuid4().hex, (0, 5), (10, 5))
    circle = CircleEntity(uuid4().hex, (0, 10), 2, layer_name="profile")
    assert canvas.replace_draft_entities((profile_line, default_line, circle))
    canvas.selected_entity_ids = {profile_line.entity_id, circle.entity_id}
    bar = editor.drawing_command_bar.input

    def exclude_circle() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.scope.setCurrentIndex(1)
        dialog.kind.setCurrentText("圆")
        dialog.mode.setCurrentIndex(1)
        dialog.accept()

    QTimer.singleShot(100, exclude_circle)
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.selected_entity_ids == {profile_line.entity_id}

    def append_default_layer() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.layer.setCurrentIndex(dialog.layer.findData("0"))
        dialog.append.setChecked(True)
        dialog.accept()

    QTimer.singleShot(100, append_default_layer)
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.selected_entity_ids == {profile_line.entity_id, default_line.entity_id}

    def cancel_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.reject()

    QTimer.singleShot(100, cancel_dialog)
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.selected_entity_ids == {profile_line.entity_id, default_line.entity_id}


def test_qselect_rejects_active_dimension_without_discarding_it(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    for command in ("DIMLINEAR", "QSELECT"):
        bar.input.setText(command)
        QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.dimensions.mode == "linear"
    assert "请先完成或取消" in bar.status.text()


def test_qselect_filters_line_length(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QComboBox, QDoubleSpinBox

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    short = LineEntity(uuid4().hex, (0, 0), (3, 4))
    long = LineEntity(uuid4().hex, (0, 10), (10, 10))
    circle = CircleEntity(uuid4().hex, (0, 20), 8)
    assert canvas.replace_draft_entities((short, long, circle))

    def choose_length() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        attribute = dialog.findChild(QComboBox, "quickSelectAttribute")
        operator = dialog.findChild(QComboBox, "quickSelectOperator")
        threshold = dialog.findChild(QDoubleSpinBox, "quickSelectThreshold")
        if attribute is None or operator is None or threshold is None:
            dialog.reject()
            return
        attribute.setCurrentText("直线长度")
        operator.setCurrentText("大于")
        threshold.setValue(7)
        dialog.accept()

    QTimer.singleShot(100, choose_length)
    bar = editor.drawing_command_bar.input
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.selected_entity_ids == {long.entity_id}
    assert canvas.entities == [short, long, circle]


def test_qselect_radius_comparison_excludes_other_entity_types(qtbot: QtBot) -> None:
    from mycad.core.sketch import ArcEntity

    circle = CircleEntity(uuid4().hex, (0, 0), 5)
    arc = ArcEntity(uuid4().hex, (10, 0), 5, 0, 90)
    line = LineEntity(uuid4().hex, (0, 0), (3, 4))
    dialog = QuickSelectDialog((circle, arc, line))
    qtbot.addWidget(dialog)
    dialog.attribute.setCurrentText("圆/圆弧半径")
    dialog.threshold.setValue(5)
    assert dialog.matching_ids((circle, arc, line), frozenset()) == {
        circle.entity_id,
        arc.entity_id,
    }
    dialog.mode.setCurrentIndex(1)
    assert dialog.matching_ids((circle, arc, line), frozenset()) == {line.entity_id}


def test_qselect_does_not_interrupt_polygon_command(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar
    bar.input.setText("POLYGON")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    opened: list[bool] = []

    def close_unexpected_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        opened.append(isinstance(dialog, QuickSelectDialog))
        if isinstance(dialog, QuickSelectDialog):
            dialog.reject()

    QTimer.singleShot(100, close_unexpected_dialog)
    bar.input.setText("QSELECT")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    qtbot.wait(150)
    assert opened == [False]
    assert "请先完成或取消" in bar.status.text()
    bar.input.setText("4")
    QTest.keyClick(bar.input, Qt.Key.Key_Return)
    assert editor.canvas.tool == "多边形"
    assert "中心" in bar.status.text() or "边" in bar.status.text()


def test_qselect_numeric_comparison_does_not_expand_with_size(qtbot: QtBot) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (1_000_000.0005, 0))
    dialog = QuickSelectDialog((line,))
    qtbot.addWidget(dialog)
    dialog.attribute.setCurrentText("直线长度")
    dialog.threshold.setValue(1_000_000)
    dialog.operator.setCurrentText("大于")
    assert dialog.matching_ids((line,), frozenset()) == {line.entity_id}
    dialog.operator.setCurrentText("等于")
    assert dialog.matching_ids((line,), frozenset()) == set()


def test_qselect_polygon_filter_matches_polygon_command_output(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    bar = editor.drawing_command_bar.input
    for command in ("POLYGON", "5", "0,0", "I", "10"):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    polygon = editor.canvas.entities[0]
    assert isinstance(polygon, PolylineEntity) and polygon.closed
    open_line = PolylineEntity(uuid4().hex, ((20, 0), (25, 0), (25, 5)), False)
    curved = PolylineEntity(uuid4().hex, ((30, 0), (35, 0), (35, 5)), True, bulges=(0.5, 0, 0))
    entities = (polygon, open_line, curved)
    dialog = QuickSelectDialog(entities)
    qtbot.addWidget(dialog)
    assert dialog.kind.findText("多边形（闭合直线多段线）") >= 0
    dialog.kind.setCurrentText("多边形（闭合直线多段线）")
    assert dialog.matching_ids(entities, frozenset()) == {polygon.entity_id}


def test_qselect_dimensions_and_images_preserves_scope_and_append(qtbot: QtBot) -> None:
    from PySide6.QtGui import QImage

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(line.entity_id, "geometry"),), 10, "mm"
    )
    canvas.constraints.append(dimension)
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    raster = raster_from_clipboard_image(image, "0")
    canvas.set_drawing_rasters((raster,))
    bar = editor.drawing_command_bar.input

    def choose_dimension() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.kind.setCurrentText("尺寸标注")
        dialog.accept()

    QTimer.singleShot(100, choose_dimension)
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    assert not canvas.selected_entity_ids and not canvas.selected_raster_ids

    def append_image() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.kind.setCurrentText("图片")
        dialog.append.setChecked(True)
        dialog.accept()

    QTimer.singleShot(100, append_image)
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    assert canvas.selected_raster_ids == {raster.image_id}

    def selected_except_image() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.scope.setCurrentIndex(1)
        dialog.kind.setCurrentText("图片")
        dialog.mode.setCurrentIndex(1)
        dialog.accept()

    QTimer.singleShot(100, selected_except_image)
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.selected_constraint_ids == {dimension.constraint_id}
    assert not canvas.selected_raster_ids


def test_qselect_annotations_respect_layer_and_numeric_filter(qtbot: QtBot) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimensions = ((uuid4().hex, "DIM"), (uuid4().hex, "0"))
    images = ((uuid4().hex, "0"),)
    dialog = QuickSelectDialog((line,), dimensions=dimensions, images=images)
    qtbot.addWidget(dialog)
    dialog.layer.setCurrentIndex(dialog.layer.findData("DIM"))
    assert dialog.matching_annotations(dimensions, frozenset(), "尺寸标注") == {dimensions[0][0]}
    assert not dialog.matching_annotations(images, frozenset(), "图片")
    dialog.layer.setCurrentIndex(0)
    dialog.attribute.setCurrentText("直线长度")
    assert not dialog.matching_annotations(dimensions, frozenset(), "尺寸标注")
    assert not dialog.matching_annotations(images, frozenset(), "图片")
    dialog.mode.setCurrentIndex(1)
    assert dialog.matching_annotations(images, frozenset(), "图片") == {images[0][0]}


def test_qselect_matches_layer_names_without_case_sensitivity(qtbot: QtBot) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="PROFILE")
    dimensions = ((uuid4().hex, "Profile"),)
    dialog = QuickSelectDialog((line,), dimensions=dimensions)
    qtbot.addWidget(dialog)
    assert dialog.layer.count() == 2
    dialog.layer.setCurrentIndex(1)
    assert dialog.matching_ids((line,), frozenset()) == {line.entity_id}
    assert dialog.matching_annotations(dimensions, frozenset(), "尺寸标注") == {dimensions[0][0]}


def test_qselect_skips_hidden_and_locked_images(qtbot: QtBot) -> None:
    from PySide6.QtGui import QImage

    from mycad.core.sketch import SketchLayer
    from mycad.ui.drawing_clipboard import raster_from_clipboard_image

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    layers = editor.layer_table.add(SketchLayer("hidden", visible=False))
    layers = layers.add(SketchLayer("locked", locked=True))
    editor.set_document_layers(layers, "DIM")
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    visible = raster_from_clipboard_image(image, "0")
    hidden = raster_from_clipboard_image(image, "hidden")
    locked = raster_from_clipboard_image(image, "locked")
    editor.canvas.set_drawing_rasters((visible, hidden, locked))

    def choose_image() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.kind.setCurrentText("图片")
        dialog.accept()

    QTimer.singleShot(100, choose_image)
    bar = editor.drawing_command_bar.input
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.selected_raster_ids == {visible.image_id}


def test_qselect_skips_hidden_and_locked_dimensions(qtbot: QtBot) -> None:
    from mycad.core.sketch import SketchLayer
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    layers = editor.layer_table.add(SketchLayer("hidden", visible=False))
    layers = layers.add(SketchLayer("locked", locked=True))
    editor.set_document_layers(layers, "DIM")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    reference = (SketchGeometryReference(line.entity_id, "geometry"),)
    dimensions = [
        SketchConstraint(uuid4().hex, "length", reference, 10, "mm", layer_name=name)
        for name in ("DIM", "hidden", "locked")
    ]
    editor.canvas.constraints.extend(dimensions)

    def choose_dimension() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.kind.setCurrentText("尺寸标注")
        dialog.accept()

    QTimer.singleShot(100, choose_dimension)
    bar = editor.drawing_command_bar.input
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.selected_constraint_ids == {dimensions[0].constraint_id}


def test_qselect_rejects_image_removed_while_dialog_open(qtbot: QtBot) -> None:
    from PySide6.QtGui import QImage

    from mycad.ui.drawing_clipboard import raster_from_clipboard_image

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    image = QImage(4, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    raster = raster_from_clipboard_image(image, "0")
    canvas.set_drawing_rasters((raster,))
    canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {line.entity_id}

    def remove_image_then_accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.kind.setCurrentText("图片")
        canvas.set_drawing_rasters(())
        dialog.accept()

    QTimer.singleShot(100, remove_image_then_accept)
    bar = editor.drawing_command_bar.input
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.selected_entity_ids == {line.entity_id}
    assert not canvas.selected_raster_ids
    assert "已变化" in editor.status_label.text()


def test_qselect_filters_dimension_values_without_matching_other_types(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    short = LineEntity(uuid4().hex, (0, 0), (10, 0))
    long = LineEntity(uuid4().hex, (0, 10), (20, 10))
    assert canvas.replace_draft_entities((short, long))
    first = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(short.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
    )
    second = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(long.entity_id, "geometry"),),
        20,
        "mm",
        driving=True,
        scale=2,
        text_override="宽 <> mm",
    )
    canvas.constraints.extend((first, second))

    def choose() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.kind.setCurrentText("尺寸标注")
        dialog.attribute.setCurrentText("尺寸测量值（mm）")
        dialog.operator.setCurrentText("等于")
        dialog.threshold.setValue(20)
        dialog.accept()

    QTimer.singleShot(100, choose)
    bar = editor.drawing_command_bar.input
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.selected_constraint_ids == {second.constraint_id}
    assert not canvas.selected_entity_ids


def test_qselect_dimension_angle_and_exclusion_respect_units(qtbot: QtBot) -> None:
    linear, angle, image = uuid4().hex, uuid4().hex, uuid4().hex
    dimensions = ((linear, "DIM"), (angle, "DIM"))
    images = ((image, "0"),)
    dialog = QuickSelectDialog(
        (),
        dimensions=dimensions,
        images=images,
        dimension_values={linear: (90, "mm"), angle: (90, "deg")},
    )
    qtbot.addWidget(dialog)
    dialog.attribute.setCurrentText("尺寸测量值（°）")
    dialog.operator.setCurrentText("等于")
    dialog.threshold.setValue(90)
    assert dialog.threshold.suffix() == " °"
    assert dialog.matching_annotations(dimensions, frozenset(), "尺寸标注") == {angle}
    assert not dialog.matching_annotations(images, frozenset(), "图片")
    dialog.mode.setCurrentIndex(1)
    assert dialog.matching_annotations(dimensions, frozenset(), "尺寸标注") == {linear}
    assert dialog.matching_annotations(images, frozenset(), "图片") == {image}
    dialog.scope.setCurrentIndex(1)
    assert dialog.matching_annotations(dimensions, frozenset({angle}), "尺寸标注") == frozenset()


def test_qselect_rejects_dimension_removed_while_dialog_open(qtbot: QtBot) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
    )
    canvas.constraints.append(dimension)
    canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {line.entity_id}

    def remove_then_accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QuickSelectDialog)
        dialog.kind.setCurrentText("尺寸标注")
        canvas.constraints.clear()
        dialog.accept()

    QTimer.singleShot(100, remove_then_accept)
    bar = editor.drawing_command_bar.input
    bar.setText("QSELECT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert canvas.selected_entity_ids == {line.entity_id}
    assert not canvas.selected_constraint_ids
    assert "已变化" in editor.status_label.text()
