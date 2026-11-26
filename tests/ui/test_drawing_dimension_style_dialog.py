# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Drawing style edits remain staged until the dialog is accepted."""

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.dimension_tolerance import DimensionTolerance
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.dimension_presets import DimensionPresetDialog
from mycad.ui.drawing_dimension_styles import DrawingDimensionStylesDialog
from mycad.ui.main_window import MainWindow
from mycad.ui.viewport import GLViewport


def test_stage_style_add_select_and_cancel(qtbot: QtBot) -> None:
    initial = DimensionStyleTable((DimensionStyle("标准"),), "标准")
    dialog = DrawingDimensionStylesDialog(initial, frozenset())
    qtbot.addWidget(dialog)
    dialog.name.setCurrentText("加工图")
    dialog.precision.setValue(3)
    dialog.scale.setValue(2)
    dialog.save_button.click()
    dialog.set_current_button.click()
    assert dialog.table.current == DimensionStyle("加工图", 3, 2)
    dialog.reject()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert initial == DimensionStyleTable((DimensionStyle("标准"),), "标准")


def test_editing_other_style_fields_preserves_tolerances(qtbot: QtBot) -> None:
    tol = DimensionTolerance("deviation", 0.02, -0.01)
    style = DimensionStyle("标准", linear_tolerance=tol)
    dialog = DrawingDimensionStylesDialog(DimensionStyleTable((style,), "标准"), frozenset())
    qtbot.addWidget(dialog)
    dialog.precision.setValue(3)
    dialog.save_button.click()
    assert dialog.table.current.precision == 3
    assert dialog.table.current.linear_tolerance == tol


def test_dimension_style_dialog_selects_document_text_style(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    styles = TextStyleTable((TextStyle(), TextStyle("inspection", "检验", "DejaVu Sans")))
    dialog = DrawingDimensionStylesDialog(
        DimensionStyleTable((DimensionStyle("标准"),), "标准"), frozenset(), text_styles=styles
    )
    qtbot.addWidget(dialog)
    dialog.text_style.setCurrentIndex(dialog.text_style.findData("inspection"))
    dialog.save_button.click()
    assert dialog.table.current.text_style_id == "inspection"


def test_dimension_style_dialog_reports_font_substitution_and_width_limit(qtbot: QtBot) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable

    styles = TextStyleTable(
        (TextStyle(), TextStyle("missing", "缺失", "MyCAD missing font 9182", width_factor=100))
    )
    dialog = DrawingDimensionStylesDialog(
        DimensionStyleTable((DimensionStyle("标准"),), "标准"), frozenset(), text_styles=styles
    )
    qtbot.addWidget(dialog)
    dialog.text_style.setCurrentIndex(dialog.text_style.findData("missing"))
    assert "替代" in dialog.font_notice.text()
    assert "40" in dialog.font_notice.text()


def test_dimension_label_font_uses_selected_text_style(qtbot: QtBot) -> None:
    from dataclasses import replace
    from uuid import uuid4

    from PySide6.QtGui import QFontDatabase

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None and editor.canvas.text_tools is not None
    family = QFontDatabase.families()[0]
    text_style = TextStyle("inspect", "检验", family, width_factor=1.2)
    text_styles = TextStyleTable((TextStyle(), text_style))
    loaded.bus.execute("drawing.text_styles.set", text_styles.to_mapping(), "local")
    dimensions = DimensionStyleTable((DimensionStyle("标准", text_style_id="inspect"),), "标准")
    loaded.bus.execute("drawing.dimension_styles.set", dimensions.to_mapping(), "local")
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        style_name="标准",
    )
    font = editor.canvas.dimension_label_font(dimension)
    assert font.family() == editor.canvas.text_tools.manager.resolve(text_style).family()
    assert font.stretch() == 120
    huge = replace(text_style, width_factor=1e308)
    loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((TextStyle(), huge)).to_mapping(), "local"
    )
    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    assert editor.canvas.dimension_label_font(dimension).stretch() == 4000


def test_style_editor_sets_distinct_linear_and_angular_tolerances(qtbot: QtBot) -> None:
    initial = DimensionStyleTable((DimensionStyle("标准"),), "标准")
    dialog = DrawingDimensionStylesDialog(initial, frozenset())
    qtbot.addWidget(dialog)
    dialog.linear_tolerance.set_value(DimensionTolerance("deviation", 0.02, -0.01, 3, 0.7, "top"))
    dialog.angular_tolerance.set_value(DimensionTolerance("symmetric", 0.5, -0.5, 1))
    dialog.save_button.click()
    assert dialog.table.current.linear_tolerance == DimensionTolerance(
        "deviation", 0.02, -0.01, 3, 0.7, "top"
    )
    assert dialog.table.current.angular_tolerance == DimensionTolerance("symmetric", 0.5, -0.5, 1)


def test_style_tolerance_is_committed_and_inherited_on_canvas(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    tolerance = DimensionTolerance("deviation", 0.02, -0.01)

    def configure() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DrawingDimensionStylesDialog)
        dialog.linear_tolerance.set_value(tolerance)
        dialog.save_button.click()
        dialog.accept()

    QTimer.singleShot(100, configure)
    window._open_drawing_dimension_styles(editor)
    assert services.kernel.drawing_dimension_styles.current.linear_tolerance == tolerance
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.dimensions.driving_check.setChecked(False)
    bar = editor.drawing_command_bar.input
    for value in ("DIMLINEAR", "0,0", "25,0", "10,10"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.dimension_tolerance_layout(editor.canvas.constraints[0]).lines == (
        "+0.02",
        "-0.01",
    )


def test_style_manager_remains_usable_at_small_window_height(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QDialogButtonBox, QScrollArea

    style = DimensionStyle("标准")
    dialog = DrawingDimensionStylesDialog(DimensionStyleTable((style,), style.name), frozenset())
    qtbot.addWidget(dialog)
    dialog.resize(400, 400)
    dialog.show()
    qtbot.waitExposed(dialog)
    scroll = dialog.findChild(QScrollArea, "dimensionStyleScroll")
    assert scroll is not None and scroll.verticalScrollBar().maximum() > 0
    buttons = dialog.findChild(QDialogButtonBox)
    assert buttons is not None and buttons.isVisible()
    assert buttons.geometry().bottom() <= dialog.rect().bottom()


def test_imported_style_remains_visible_in_style_manager(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    original = services.kernel.drawing_dimension_styles
    styles = DimensionStyleTable((*original.styles, DimensionStyle("导入")), original.current_name)
    loaded.bus.execute(
        "drawing.clipboard.prepare",
        {
            "layers": services.kernel.drawing_layers.to_mapping(),
            "dimension_layer": services.kernel.dimension_layer,
            "assignments": [],
            "clipboard_styles": styles.to_mapping(),
        },
        "local",
        version=6,
    )
    seen: list[str] = []

    def inspect() -> None:
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, DrawingDimensionStylesDialog):
            seen.extend(style.name for style in dialog.table.styles)
            dialog.reject()

    QTimer.singleShot(50, inspect)
    window._open_drawing_dimension_styles(editor)
    assert "导入" in seen


def test_style_delete_rejects_current_and_in_use(qtbot: QtBot) -> None:
    initial = DimensionStyleTable((DimensionStyle("标准"), DimensionStyle("加工图")), "标准")
    dialog = DrawingDimensionStylesDialog(initial, frozenset({"加工图"}))
    qtbot.addWidget(dialog)
    dialog.name.setCurrentText("标准")
    dialog.delete_button.click()
    assert "当前" in dialog.message.text()
    dialog.name.setCurrentText("加工图")
    dialog.delete_button.click()
    assert "使用" in dialog.message.text()
    assert dialog.table == initial


def test_dimstyle_applies_drawing_style_to_new_dimension(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    opened: list[bool] = []

    def configure() -> None:
        dialog = QApplication.activeModalWidget()
        opened.append(isinstance(dialog, DrawingDimensionStylesDialog))
        if not isinstance(dialog, DrawingDimensionStylesDialog):
            if isinstance(dialog, QDialog):
                dialog.reject()
            return
        dialog.name.setCurrentText("加工图")
        dialog.precision.setValue(3)
        dialog.scale.setValue(2)
        dialog.save_button.click()
        dialog.set_current_button.click()
        dialog.accept()

    QTimer.singleShot(100, configure)
    bar = editor.drawing_command_bar.input
    bar.setText("DIMSTYLE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert opened == [True]
    assert services.kernel.drawing_dimension_styles.current_name == "加工图"
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.dimensions.driving_check.setChecked(False)
    for value in ("DIMLINEAR", "0,0", "25,0", "10,10"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    dimension = editor.canvas.constraints[0]
    assert (dimension.style_name, dimension.precision, dimension.scale) == ("加工图", 3, 2)


def test_tools_menu_opens_drawing_dimension_styles(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    action = next(
        (item for item in window.menu_tools.actions() if item.text() == "标注样式…"), None
    )
    assert action is not None and action.isEnabled()
    opened: list[bool] = []

    def dismiss() -> None:
        dialog = QApplication.activeModalWidget()
        opened.append(isinstance(dialog, DrawingDimensionStylesDialog))
        if isinstance(dialog, QDialog):
            dialog.reject()

    QTimer.singleShot(100, dismiss)
    action.trigger()
    assert opened == [True]
    editor.canvas.set_tool("直线")
    editor.canvas.add_coordinate_point((0, 0))
    action.trigger()
    assert "请先完成或取消" in editor.status_label.text()
    assert QApplication.activeModalWidget() is None


def test_drawing_style_arrow_and_line_options_render_and_reopen(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from uuid import uuid4

    from mycad.formats.providers.dxf_provider import write_sketches_dxf

    services = app.build_app(discoverers=())
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

    def configure() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DrawingDimensionStylesDialog)
        dialog.name.setCurrentText("机械")
        dialog.arrow_first.setCurrentIndex(dialog.arrow_first.findData("closed"))
        dialog.arrow_second.setCurrentIndex(dialog.arrow_second.findData("tick"))
        dialog.arrow_size.setValue(3)
        dialog.dimline_extension.setValue(2)
        dialog.extline_extension.setValue(1)
        dialog.extline_offset.setValue(0.5)
        dialog.text_height.setValue(4)
        dialog.save_button.click()
        dialog.set_current_button.click()
        dialog.accept()

    QTimer.singleShot(100, configure)
    window.act_drawing_dimension_styles.trigger()
    style = services.kernel.drawing_dimension_styles.current
    assert (style.arrow_first, style.arrow_second, style.arrow_size) == ("closed", "tick", 3)
    assert style.text_height == 4
    assert editor.canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (25, 0)),))
    editor.dimensions.driving_check.setChecked(False)
    bar = editor.drawing_command_bar.input
    for command in ("DIMLINEAR", "0,0", "25,0", "10,10"):
        bar.setText(command)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    dim = editor.canvas.constraints[0]
    layout = editor.canvas.dimension_layout(dim, editor.canvas.dimension_entities())
    assert layout is not None
    assert len(editor.canvas.dimension_arrow_segments(layout, dim.scale, dim)) == 4
    assert layout.lines[2][0] != layout.arrows[0][0]
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    next_editor = window.active_sketch_dialog()
    assert next_editor is not None

    def change_existing() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DrawingDimensionStylesDialog)
        dialog.arrow_first.setCurrentIndex(dialog.arrow_first.findData("filled"))
        dialog.arrow_second.setCurrentIndex(dialog.arrow_second.findData("tick"))
        dialog.dimline_extension.setValue(4)
        dialog.save_button.click()
        dialog.accept()

    QTimer.singleShot(100, change_existing)
    window.act_drawing_dimension_styles.trigger()
    style = services.kernel.drawing_dimension_styles.current
    assert style.arrow_first == "filled" and style.dimline_extension == 4
    updated_dimension = services.kernel.sketches[0].constraints[0]
    updated_layout = next_editor.canvas.dimension_layout(
        updated_dimension, next_editor.canvas.dimension_entities()
    )
    assert updated_layout is not None
    assert (
        len(
            next_editor.canvas.dimension_arrow_segments(
                updated_layout, updated_dimension.scale, updated_dimension
            )
        )
        == 4
    )
    assert not next_editor.canvas.grab().isNull()
    path = tmp_path / "style.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_dimension_styles.current == style
    dxf = tmp_path / "style.dxf"
    report = write_sketches_dxf(
        reopened.kernel.sketches, dxf, dimension_styles=reopened.kernel.drawing_dimension_styles
    )
    assert all("未导出为 DXF 标注" not in warning for warning in report.warnings)
    import ezdxf

    dimension = list(ezdxf.readfile(dxf).modelspace().query("DIMENSION"))[0]
    native = dimension.override()
    assert native.get("dimblk1") == ""
    assert native.get("dimblk2") == "OBLIQUE"
    assert native.get("dimdle") == pytest.approx(4 * dim.scale)
    assert native.get("dimexe") == pytest.approx(1 * dim.scale)
    assert native.get("dimexo") == pytest.approx(0.5 * dim.scale)
    assert native.get("dimtxt") == pytest.approx(4 * dim.scale)


def test_dimstyle_updates_saved_dimensions_and_replays(qtbot: QtBot, tmp_path: Path) -> None:
    from uuid import uuid4

    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None

    def configure() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DrawingDimensionStylesDialog)
        dialog.name.setCurrentText("加工图")
        dialog.precision.setValue(3)
        dialog.scale.setValue(2)
        dialog.save_button.click()
        dialog.set_current_button.click()
        dialog.accept()

    QTimer.singleShot(100, configure)
    bar = editor.drawing_command_bar.input
    bar.setText("DIMSTYLE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (25, 0)),))
    editor.dimensions.driving_check.setChecked(False)
    for value in ("DIMLINEAR", "0,0", "25,0", "10,10"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    before_dimension = services.kernel.sketches[0].constraints[0]
    assert before_dimension.style_name == "加工图"
    before_layout = editor.canvas.dimension_layout(
        before_dimension, editor.canvas.dimension_entities()
    )
    assert before_layout is not None
    before_height = editor.canvas.dimension_label_rect(
        before_dimension, before_layout.label
    ).height()

    def update_style() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DrawingDimensionStylesDialog)
        dialog.precision.setValue(1)
        dialog.scale.setValue(3)
        dialog.save_button.click()
        dialog.accept()

    QTimer.singleShot(100, update_style)
    bar = editor.drawing_command_bar.input
    bar.setText("DIMSTYLE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    changed = services.kernel.sketches[0]
    assert (changed.constraints[0].precision, changed.constraints[0].scale) == (1, 3)
    updated_layout = editor.canvas.dimension_layout(
        changed.constraints[0], editor.canvas.dimension_entities()
    )
    assert updated_layout is not None
    after_height = editor.canvas.dimension_label_rect(
        changed.constraints[0], updated_layout.label
    ).height()
    assert after_height == before_height * 1.5
    assert changed.constraints[0].value == before_dimension.value
    path = tmp_path / "drawing-styles.my2d"
    save_document(loaded.document, path)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, path)
    assert reopened_services.kernel.sketches == (changed,)
    assert (
        editor.canvas.dimension_label_rect(
            reopened_services.kernel.sketches[0].constraints[0], updated_layout.label
        ).height()
        == after_height
    )
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0].constraints[0].precision == 3
    reopened.bus.redo()
    assert reopened_services.kernel.sketches == (changed,)
    dxf = tmp_path / "updated-style.dxf"
    report = write_sketch_dxf(reopened_services.kernel.sketches[0], dxf)
    imported = read_sketch_dxf(dxf).sketch.constraints[0]
    assert (imported.precision, imported.scale, imported.value) == (1, 3, before_dimension.value)
    assert imported.style_name is None
    assert any("样式关联" in warning for warning in report.warnings)


def test_undo_redo_first_style_restores_new_dimension_default(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    loaded = window.loaded_document()
    assert editor is not None and unit is not None and loaded is not None

    def configure() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DrawingDimensionStylesDialog)
        dialog.name.setCurrentText("加工图")
        dialog.precision.setValue(3)
        dialog.save_button.click()
        dialog.set_current_button.click()
        dialog.accept()

    QTimer.singleShot(100, configure)
    bar = editor.drawing_command_bar.input
    bar.setText("DIMSTYLE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert len(loaded.document.commands) == 1
    window.act_undo.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy and not loaded.document.commands, timeout=10000)
    assert editor.dimensions.precision.value() == 2
    window.act_redo.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 1, timeout=10000)
    assert editor.canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (25, 0)),))
    editor.dimensions.driving_check.setChecked(False)
    for value in ("DIMLINEAR", "0,0", "25,0", "10,10"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.constraints[0].style_name == "加工图"
    assert editor.canvas.constraints[0].precision == 3


def test_style_change_refuses_used_draft_without_partial_commit(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None

    def activate() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DrawingDimensionStylesDialog)
        dialog.accept()

    bar = editor.drawing_command_bar.input
    QTimer.singleShot(100, activate)
    bar.setText("DIMSTYLE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (25, 0)),))
    editor.dimensions.driving_check.setChecked(False)
    for value in ("DIMLINEAR", "0,0", "25,0", "10,10"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    editor.dimensions.cancel()
    draft = tuple(editor.canvas.constraints)
    before = services.kernel.drawing_dimension_styles
    count = loaded.document.command_count

    def change() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DrawingDimensionStylesDialog)
        dialog.precision.setValue(4)
        dialog.save_button.click()
        dialog.accept()

    QTimer.singleShot(100, change)
    bar.setText("DIMSTYLE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert "请先完成草图" in editor.status_label.text()
    assert tuple(editor.canvas.constraints) == draft
    assert services.kernel.drawing_dimension_styles == before
    assert loaded.document.command_count == count


def test_undo_current_style_switch_with_unchanged_draft_style(qtbot: QtBot) -> None:
    from uuid import uuid4

    services = app.build_app(discoverers=())
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
    bar = editor.drawing_command_bar.input

    def add_style() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DrawingDimensionStylesDialog)
        dialog.name.setCurrentText("备用")
        dialog.save_button.click()
        dialog.accept()

    QTimer.singleShot(100, add_style)
    bar.setText("DIMSTYLE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (25, 0)),))
    editor.dimensions.driving_check.setChecked(False)
    for value in ("DIMLINEAR", "0,0", "25,0", "10,10"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    editor.dimensions.cancel()
    assert editor.canvas.constraints[0].style_name == "标准"

    def select_style() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DrawingDimensionStylesDialog)
        dialog.name.setCurrentText("备用")
        dialog.set_current_button.click()
        dialog.accept()

    QTimer.singleShot(100, select_style)
    bar.setText("DIMSTYLE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert services.kernel.drawing_dimension_styles.current_name == "备用"
    count = loaded.document.command_count
    window.act_undo.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and loaded.document.command_count == count - 1, timeout=10000
    )
    assert services.kernel.drawing_dimension_styles.current_name == "标准"
    assert editor.canvas.constraints[0].style_name == "标准"
    window.act_redo.trigger()
    qtbot.waitUntil(
        lambda: not unit.is_busy and loaded.document.command_count == count, timeout=10000
    )
    assert services.kernel.drawing_dimension_styles.current_name == "备用"


def test_dimstyle_keeps_access_to_local_presets(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    opened: list[bool] = []

    def local_preset() -> None:
        dialog = QApplication.activeModalWidget()
        opened.append(isinstance(dialog, DimensionPresetDialog))
        if isinstance(dialog, DimensionPresetDialog):
            dialog.precision.setValue(4)
            dialog.accept()
        elif isinstance(dialog, QDialog):
            dialog.reject()

    def style_manager() -> None:
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, DrawingDimensionStylesDialog):
            QTimer.singleShot(100, local_preset)
            dialog.local_presets_button.click()
        elif isinstance(dialog, QDialog):
            dialog.reject()

    QTimer.singleShot(100, style_manager)
    bar = editor.drawing_command_bar.input
    bar.setText("DIMSTYLE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert opened == [True]
    assert editor.dimensions.precision.value() == 4
    assert not editor.dimensions.drawing_style_active


def test_dimstyle_does_not_invalidate_pending_mixed_move(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    from uuid import uuid4

    def skip_viewport_paint(self: GLViewport) -> None:
        pass

    monkeypatch.setattr(GLViewport, "paintGL", skip_viewport_paint)
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,)), session_identity=1
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    draft = LineEntity(uuid4().hex, (20, 0), (30, 0))
    assert editor.canvas.replace_draft_entities((draft,))
    assert editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id, draft.entity_id}
    bar = editor.drawing_command_bar.input
    for value in ("MOVE", "0,0", "3,4"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: not unit.is_busy and editor.canvas.mixed_move is not None, timeout=10000
    )
    before = loaded.document.commands
    opened: list[bool] = []

    def reject_unexpected() -> None:
        dialog = QApplication.activeModalWidget()
        opened.append(isinstance(dialog, DrawingDimensionStylesDialog))
        if isinstance(dialog, QDialog):
            dialog.reject()

    QTimer.singleShot(100, reject_unexpected)
    bar.setText("DIMSTYLE")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    qtbot.wait(150)
    assert opened == [False]
    assert loaded.document.commands == before
    assert "完成" in editor.status_label.text()
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert len(loaded.document.commands) == len(before) + 2


def test_drawing_style_button_describes_its_actual_manager(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    button = editor.dimensions.preset_button
    assert button.text() == "标注样式"
    assert "图纸" in button.toolTip()
    assert "本机" in button.toolTip()
    opened: list[bool] = []

    def dismiss() -> None:
        dialog = QApplication.activeModalWidget()
        opened.append(isinstance(dialog, DrawingDimensionStylesDialog))
        if isinstance(dialog, QDialog):
            dialog.reject()

    QTimer.singleShot(100, dismiss)
    button.click()
    assert opened == [True]


def test_standalone_style_button_keeps_local_preset_label(qtbot: QtBot) -> None:
    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    assert editor.dimensions.preset_button.text() == "标注预设"
    assert "本机" in editor.dimensions.preset_button.toolTip()


@pytest.mark.parametrize("apply_change", [False, True])
def test_editing_dimension_format_preserves_new_dimension_drawing_style(
    qtbot: QtBot, apply_change: bool
) -> None:
    from uuid import uuid4

    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.ui.sketch_editor import SketchEditorDialog

    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        constraint_preview=services.kernel.preview_sketch_constraint,
        constraint_update_preview=services.kernel.preview_sketch_constraint_update,
    )
    qtbot.addWidget(editor)
    editor.show()
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        driving=False,
        scale=1,
    )
    editor.canvas.entities = [line]
    editor.canvas.constraints = [dimension]
    editor.canvas.changed.emit()
    editor.dimensions.set_drawing_style(DimensionStyle("加工图", precision=3, scale=2))
    original = next(sketch for sketch in editor.dimension_sources() if sketch.constraints)
    editor.dimensions.edit(original, dimension)
    editor.dimensions.scale.setValue(4)
    if apply_change:
        editor.dimensions.apply_edit()
        assert editor.canvas.constraints[0].scale == 4
    else:
        editor.dimensions.cancel()
        assert editor.canvas.constraints[0].scale == 1
    assert editor.dimensions.drawing_style_active
    editor.dimensions.start("linear")
    assert editor.dimensions.scale.value() == 2
    assert editor.dimensions.precision.value() == 3
    editor.dimensions.driving_check.setChecked(False)
    for value in ("0,0", "25,0", "10,15"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    new_dimension = editor.canvas.constraints[-1]
    assert (new_dimension.style_name, new_dimension.precision, new_dimension.scale) == (
        "加工图",
        3,
        2,
    )


def test_new_drawing_default_scale_and_first_style_are_consistent(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    assert editor.dimensions.scale.value() == 0.8
    seen: list[float] = []

    def accept_style() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DrawingDimensionStylesDialog)
        seen.append(dialog.scale.value())
        dialog.accept()

    QTimer.singleShot(100, accept_style)
    editor.dimensions.open_format_presets()
    assert seen == [0.8]
    assert services.kernel.drawing_dimension_styles.current.scale == 0.8
    assert editor.dimensions.scale.value() == 0.8
    from uuid import uuid4

    assert editor.canvas.replace_draft_entities((LineEntity(uuid4().hex, (0, 0), (25, 0)),))
    editor.dimensions.driving_check.setChecked(False)
    bar = editor.drawing_command_bar.input
    for value in ("DIMLINEAR", "0,0", "25,0", "10,10"):
        bar.setText(value)
        QTest.keyClick(bar, Qt.Key.Key_Return)
    assert editor.canvas.constraints[0].scale == 0.8


def test_symmetric_to_deviation_style_edit_saves_effective_values(
    qtbot: QtBot, tmp_path: Path
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None

    def configure() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DrawingDimensionStylesDialog)
        tolerance = dialog.linear_tolerance
        tolerance.set_value(DimensionTolerance("symmetric", 0.1, -0.1))
        tolerance.upper_spin.setValue(0.2)
        tolerance.mode.setCurrentIndex(tolerance.mode.findData("deviation"))
        dialog.save_button.click()
        dialog.accept()

    QTimer.singleShot(20, configure)
    window._open_drawing_dimension_styles(editor)
    expected = DimensionTolerance("deviation", 0.2, -0.2)
    assert services.kernel.drawing_dimension_styles.current.linear_tolerance == expected
    path = tmp_path / "converted-tolerance-style.my2d"
    save_document(loaded.document, path)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert reopened.kernel.drawing_dimension_styles.current.linear_tolerance == expected
