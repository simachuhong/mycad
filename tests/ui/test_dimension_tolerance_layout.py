# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Dimension tolerance drawing and hit bounds use the same layout."""

from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from PySide6.QtCore import QPointF, QTimer
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.dimension_tolerance import DimensionTolerance
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import ConstraintKind, SketchConstraint, SketchGeometryReference
from mycad.ui.dimension_tolerance_editor import DimensionToleranceDialog, DimensionToleranceEditor
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchCanvas, SketchEditorDialog


def test_disabling_invalid_deviations_is_always_possible(qtbot: QtBot) -> None:
    editor = DimensionToleranceEditor()
    qtbot.addWidget(editor)
    editor.set_value(DimensionTolerance("deviation", 0.02, -0.01))
    editor.lower_spin.setValue(0.03)
    editor.mode.setCurrentIndex(editor.mode.findData("none"))
    assert editor.value().mode == "none"


def test_dimension_tolerance_inherits_style_and_explicit_none_disables(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    tol = DimensionTolerance("deviation", 0.02, -0.01, 2, 0.7, "top")
    canvas.drawing_dimension_styles = DimensionStyleTable(
        (DimensionStyle("标准", linear_tolerance=tol),), "标准"
    )
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(uuid4().hex, "geometry"),),
        20,
        "mm",
        style_name="标准",
    )
    base = canvas.dimension_label_rect(
        replace(dimension, tolerance=DimensionTolerance()), QPointF(200, 200)
    )
    layout = canvas.dimension_tolerance_layout(dimension)
    bounds = canvas.dimension_label_rect(dimension, QPointF(200, 200))
    assert layout.lines == ("+0.02", "-0.01")
    assert bounds.width() > base.width()
    assert (
        canvas.dimension_tolerance_layout(replace(dimension, tolerance=DimensionTolerance())).lines
        == ()
    )


def test_symmetric_negative_zero_is_normalized_on_canvas(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(uuid4().hex, "geometry"),),
        20,
        "mm",
        tolerance=DimensionTolerance("symmetric", -0.0, 0.0),
    )
    assert canvas.dimension_tolerance_layout(dimension).lines == ("±0.00",)


def test_equal_rounded_deviations_display_precision_warning(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(uuid4().hex, "geometry"),),
        20,
        "mm",
        tolerance=DimensionTolerance("deviation", 0.0124, 0.0116, 2),
    )
    assert canvas.dimension_tolerance_layout(dimension).lines == ("公差精度不足",)


def test_limit_values_follow_displayed_dimension_value(qtbot: QtBot) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    dimension = SketchConstraint(
        uuid4().hex,
        "diameter",
        (SketchGeometryReference(uuid4().hex, "geometry"),),
        20,
        "mm",
        tolerance=DimensionTolerance("limits", 0.02, -0.01),
    )
    layout = canvas.dimension_tolerance_layout(dimension)
    assert layout.lines == ("⌀20.02 mm", "⌀19.99 mm")


@pytest.mark.parametrize("mode", ["symmetric", "deviation", "limits"])
@pytest.mark.parametrize("inherited", [False, True])
def test_dimension_canvas_does_not_display_hidden_tolerance_as_zero(
    qtbot: QtBot, mode: str, inherited: bool
) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    tolerance = DimensionTolerance(mode, 1e-10, -1e-10, 8)
    if inherited:
        canvas.drawing_dimension_styles = DimensionStyleTable(
            (DimensionStyle("标准", linear_tolerance=tolerance),), "标准"
        )
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(uuid4().hex, "geometry"),),
        20,
        "mm",
        style_name="标准" if inherited else None,
        tolerance=None if inherited else tolerance,
    )
    assert canvas.dimension_tolerance_layout(dimension).lines == ("公差精度不足",)


@pytest.mark.parametrize("override", [None, "A<>B"])
def test_limit_values_do_not_display_negative_zero(qtbot: QtBot, override: str | None) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(uuid4().hex, "geometry"),),
        0.01,
        "mm",
        text_override=override,
        tolerance=DimensionTolerance("limits", 0.01, -0.011, 2),
    )
    lines = canvas.dimension_tolerance_layout(dimension).lines
    assert lines == (("0.02 mm", "0.00 mm") if override is None else ("A0.02B", "A0.00B"))


def test_limit_layout_formats_genuinely_negative_value_without_changing_geometry(
    qtbot: QtBot,
) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(uuid4().hex, "geometry"),),
        0.01,
        "mm",
        tolerance=DimensionTolerance("limits", 0.01, -0.03, 2),
    )
    assert canvas.dimension_tolerance_layout(dimension).lines == ("0.02 mm", "-0.02 mm")
    assert dimension.value == 0.01 and dimension.driving


@pytest.mark.parametrize("inherited", [False, True])
def test_limit_layout_reports_finite_values_whose_sum_overflows(
    qtbot: QtBot, inherited: bool
) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    tolerance = DimensionTolerance("limits", 1e308, 0)
    if inherited:
        canvas.drawing_dimension_styles = DimensionStyleTable(
            (DimensionStyle("overflow", linear_tolerance=tolerance),), "overflow"
        )
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(uuid4().hex, "geometry"),),
        1e308,
        "mm",
        style_name="overflow" if inherited else None,
        tolerance=None if inherited else tolerance,
    )
    layout = canvas.dimension_tolerance_layout(dimension)
    assert layout.lines == ("公差极限超出范围",)
    assert layout.width > 0 and layout.height > 0
    assert dimension.value == 1e308


@pytest.mark.parametrize(
    ("kind", "prefix", "suffix"),
    (
        ("length", "", " mm"),
        ("distance", "", " mm"),
        ("radius", "R", " mm"),
        ("diameter", "⌀", " mm"),
        ("arc_length", "⌒", " mm"),
        ("angle", "", "°"),
    ),
)
def test_limit_layout_retains_dimension_prefix_and_single_override(
    qtbot: QtBot, kind: str, prefix: str, suffix: str
) -> None:
    canvas = SketchCanvas(select_committed_entities=True)
    qtbot.addWidget(canvas)
    refs = (SketchGeometryReference(uuid4().hex, "geometry"),)
    if kind in ("distance", "angle"):
        refs += (SketchGeometryReference(uuid4().hex, "geometry"),)
    dimension = SketchConstraint(
        uuid4().hex,
        cast("ConstraintKind", kind),
        refs,
        20,
        "deg" if kind == "angle" else "mm",
        tolerance=DimensionTolerance("limits", 0.02, -0.01),
    )
    layout = canvas.dimension_tolerance_layout(dimension)
    assert layout.lines == (f"{prefix}20.02{suffix}", f"{prefix}19.99{suffix}")
    customized = canvas.dimension_tolerance_layout(replace(dimension, text_override="A<>B"))
    assert customized.lines == ("A20.02B", "A19.99B")
    assert customized.width > 0 and customized.height > 0


def test_single_dimension_override_is_staged_until_dimension_confirm(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
    )
    editor.canvas.entities = [line]
    editor.canvas.constraints = [dimension]
    editor.show()
    sketch = editor.dimension_sources()[0]
    editor.dimensions.edit(sketch, dimension)
    expected = DimensionTolerance("deviation", 0.02, -0.01)

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DimensionToleranceDialog)
        dialog.inherit.setChecked(False)
        dialog.editor.set_value(expected)
        dialog.accept()

    QTimer.singleShot(20, accept)
    editor.dimensions.tolerance_button.click()
    assert editor.dimensions.candidate is not None
    assert editor.dimensions.candidate.tolerance == expected
    assert editor.canvas.constraints[0].tolerance is None


def test_text_override_without_placeholder_cannot_hide_active_tolerance(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    line = LineEntity(uuid4().hex, (0, 0), (20, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        20,
        "mm",
        driving=False,
        tolerance=DimensionTolerance("deviation", 0.02, -0.01),
    )
    editor.canvas.entities = [line]
    editor.canvas.constraints = [dimension]
    editor.show()
    editor.dimensions.edit(editor.dimension_sources()[0], dimension)
    editor.dimensions.text_override.setText("覆盖数值")
    assert not editor.dimensions.apply_button.isEnabled()
    editor.dimensions.value_editor.setValue(21)
    assert not editor.dimensions.apply_button.isEnabled()
    assert editor.canvas.constraints[0] == dimension


def test_saved_dimension_tolerance_edit_is_undoable_and_reopens(
    qtbot: QtBot, tmp_path: Path
) -> None:
    line = LineEntity(uuid4().hex, (0, 0), (25, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        25,
        "mm",
        driving=False,
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=1)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    editor.dimensions.edit(sketch, dimension)
    tolerance = DimensionTolerance("deviation", 0.02, -0.01)

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DimensionToleranceDialog)
        dialog.inherit.setChecked(False)
        dialog.editor.set_value(tolerance)
        dialog.accept()

    QTimer.singleShot(20, accept)
    editor.dimensions.tolerance_button.click()
    editor.dimensions.apply_edit()
    qtbot.waitUntil(lambda: not unit.is_busy and len(loaded.document.commands) == 2, timeout=10000)
    assert services.kernel.sketches[0].constraints[0].tolerance == tolerance
    assert services.kernel.sketches[0].entities == (line,)
    target = tmp_path / "dimension-tolerance.my2d"
    save_document(loaded.document, target)
    reopened_services = app.build_app(discoverers=())
    reopened = app.open_app_document(reopened_services, target)
    assert reopened_services.kernel.sketches[0].constraints[0].tolerance == tolerance
    reopened.bus.undo()
    assert reopened_services.kernel.sketches[0].constraints[0].tolerance is None
    reopened.bus.redo()
    assert reopened_services.kernel.sketches[0].constraints[0].tolerance == tolerance


@pytest.mark.parametrize("mode", ["symmetric", "deviation", "limits"])
def test_tolerance_editor_reports_precision_loss_and_updates(qtbot: QtBot, mode: str) -> None:
    editor = DimensionToleranceEditor()
    qtbot.addWidget(editor)
    editor.set_nominal(20)
    editor.set_value(DimensionTolerance(mode, 0.001, -0.001, 2))
    assert "精度不足" in editor.value_notice.text()
    editor.precision.setValue(3)
    assert "精度不足" not in editor.value_notice.text()
    assert editor.value().upper_deviation == 0.001
    editor.precision.setValue(2)
    editor.mode.setCurrentIndex(editor.mode.findData("none"))
    assert "精度不足" not in editor.value_notice.text()
    editor.mode.setCurrentIndex(editor.mode.findData(mode))
    editor.upper_spin.setValue(0.02)
    if mode != "symmetric":
        editor.lower_spin.setValue(-0.02)
    assert "精度不足" not in editor.value_notice.text()


def test_editor_reports_deviations_rounded_to_same_value(qtbot: QtBot) -> None:
    editor = DimensionToleranceEditor()
    qtbot.addWidget(editor)
    editor.set_nominal(20)
    editor.set_value(DimensionTolerance("deviation", 0.0124, 0.0116, 2))
    assert "精度不足" in editor.value_notice.text()
    editor.precision.setValue(4)
    assert "精度不足" not in editor.value_notice.text()


def test_dimension_tolerance_editor_preserves_unrepresentable_values(qtbot: QtBot) -> None:
    editor = DimensionToleranceEditor()
    qtbot.addWidget(editor)
    tolerance = DimensionTolerance("deviation", 1e-10, -2e-10, 2, 1e-5)
    editor.set_value(tolerance)
    editor.precision.setValue(3)
    result = editor.value()
    assert (result.upper_deviation, result.lower_deviation, result.text_factor) == (
        1e-10,
        -2e-10,
        1e-5,
    )
    assert "原始值" in editor.value_notice.text()
    editor.upper_spin.setValue(0.5)
    editor.factor.setValue(1.0)
    result = editor.value()
    assert (result.upper_deviation, result.lower_deviation, result.text_factor) == (
        0.5,
        -2e-10,
        1.0,
    )


def test_disable_tolerance_preserves_valid_deviations(qtbot: QtBot) -> None:
    editor = DimensionToleranceEditor()
    qtbot.addWidget(editor)
    editor.set_value(DimensionTolerance("deviation", 0.02, -0.01, 2, 1))
    editor.mode.setCurrentIndex(editor.mode.findData("none"))
    disabled = editor.value()
    assert disabled.mode == "none"
    assert (disabled.upper_deviation, disabled.lower_deviation) == (0.02, -0.01)
    editor.set_value(disabled)
    editor.precision.setValue(3)
    assert (editor.value().upper_deviation, editor.value().lower_deviation) == (0.02, -0.01)


def test_exact_dimension_inputs_accept_signed_scientific_values(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QInputDialog

    editor = DimensionToleranceEditor()
    qtbot.addWidget(editor)
    editor.mode.setCurrentIndex(editor.mode.findData("deviation"))
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("1e-10", True))
    editor.exact_upper_button.click()
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("-2e-10", True))
    editor.exact_lower_button.click()
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("1e-5", True))
    editor.exact_factor_button.click()
    result = editor.value()
    assert (result.upper_deviation, result.lower_deviation, result.text_factor) == (
        1e-10,
        -2e-10,
        1e-5,
    )
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("0", True))
    editor.exact_factor_button.click()
    assert editor.factor.precise_value() == 1e-5
    with pytest.raises(ValueError, match="范围"):
        editor.value()
    assert "范围" in editor.value_notice.text()


def test_invalid_exact_dimension_input_blocks_acceptance(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialog, QInputDialog

    original = DimensionTolerance("deviation", 0.1, -0.2)
    dialog = DimensionToleranceDialog(original, DimensionTolerance())
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("inf", True))
    dialog.editor.exact_factor_button.click()
    dialog.accept()
    assert dialog.result() != int(QDialog.DialogCode.Accepted)
    assert "有限" in dialog.message.text()
    dialog.editor.factor.setValue(2.0)
    dialog.accept()
    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    assert dialog.selected_value() == DimensionTolerance("deviation", 0.1, -0.2, 2, 2.0)


@pytest.mark.parametrize("target", ("none", "deviation", "limits"))
def test_leaving_symmetric_mode_preserves_effective_lower_deviation(
    qtbot: QtBot, target: str
) -> None:
    editor = DimensionToleranceEditor()
    qtbot.addWidget(editor)
    editor.set_value(DimensionTolerance("symmetric", 0.1, -0.1))
    editor.upper_spin.setValue(0.2)
    assert editor.value().lower_deviation == -0.2
    editor.mode.setCurrentIndex(editor.mode.findData(target))
    result = editor.value()
    assert (result.upper_deviation, result.lower_deviation) == (0.2, -0.2)


def test_cancel_exact_input_clears_rejected_error_and_retains_value(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QInputDialog

    editor = DimensionToleranceEditor()
    qtbot.addWidget(editor)
    editor.set_value(DimensionTolerance("deviation", 0.1, -0.2))
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("bad", True))
    editor._enter_exact_value(editor.upper_spin, "上偏差")
    with pytest.raises(ValueError):
        editor.value()
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("bad", False))
    editor._enter_exact_value(editor.upper_spin, "上偏差")
    assert editor.value() == DimensionTolerance("deviation", 0.1, -0.2)
    assert "请输入" not in editor.value_notice.text()


def test_leaving_symmetric_mode_preserves_unrounded_deviation(qtbot: QtBot) -> None:
    editor = DimensionToleranceEditor()
    qtbot.addWidget(editor)
    editor.set_value(DimensionTolerance("symmetric", 1e-10, -1e-10))
    editor.mode.setCurrentIndex(editor.mode.findData("deviation"))
    result = editor.value()
    assert (result.upper_deviation, result.lower_deviation) == (1e-10, -1e-10)
    assert "下偏差" in editor.value_notice.text()


def test_loading_new_tolerance_does_not_convert_previous_symmetric_state(qtbot: QtBot) -> None:
    editor = DimensionToleranceEditor()
    qtbot.addWidget(editor)
    editor.set_value(DimensionTolerance("symmetric", 0.1, -0.1))
    editor.upper_spin.setValue(0.2)
    incoming = DimensionTolerance("deviation", 0.4, -0.3)
    editor.set_value(incoming)
    assert editor.value() == incoming
