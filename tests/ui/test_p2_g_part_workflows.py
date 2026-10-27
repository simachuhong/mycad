# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Create representative parts through GUI controls from an empty document."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFileDialog, QPushButton
from pytestqt.qtbot import QtBot

from mycad.app import build_app
from mycad.core.exceptions import ValidationError
from mycad.core.sketch import CircleEntity
from mycad.ui.main_window import MainWindow
from mycad.ui.sketch_editor import SketchEditorDialog
from tests.helpers.step_roundtrip import read_step

pytestmark = pytest.mark.usefixtures("choose_new_part")


def _point(dialog: SketchEditorDialog, point: tuple[float, float], *, mouse: bool = False) -> None:
    if mouse:
        QTest.mouseClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen(point)
        )
    else:
        dialog.u_field.setValue(point[0])
        dialog.v_field.setValue(point[1])
        dialog.coordinate_add_button.click()


def _curve(
    dialog: SketchEditorDialog, tool: str, *points: tuple[float, float], mouse: bool = False
) -> None:
    dialog.tool_combo.setCurrentText(tool)
    for point in points:
        _point(dialog, point, mouse=mouse)


def _flange(dialog: SketchEditorDialog) -> float:
    _curve(dialog, "圆", (0.0, 0.0), (40.0, 0.0), mouse=True)
    _curve(dialog, "圆", (0.0, 0.0), (10.0, 0.0))
    _curve(dialog, "圆", (25.0, 0.0), (28.0, 0.0))
    dialog.tool_combo.setCurrentText("选择元素")
    _point(dialog, (28.0, 0.0), mouse=True)
    assert len(dialog.canvas.selected_entity_ids) == 1
    dialog.center_u_field.setValue(0.0)
    dialog.center_v_field.setValue(0.0)
    dialog.pattern_angle_field.setValue(360.0)
    dialog.count_field.setValue(4)
    dialog.transform_buttons["circular_array"].click()
    assert len(dialog.canvas.entities) == 6, dialog.canvas.message
    return math.pi * (40**2 - 10**2 - 4 * 3**2) * 8


def _shaft(dialog: SketchEditorDialog) -> float:
    dialog.plane_combo.setCurrentText("XZ")
    dialog.closed_check.setChecked(True)
    _curve(
        dialog,
        "多段线",
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, -20.0),
        (6.0, -20.0),
        (6.0, -50.0),
        (0.0, -50.0),
    )
    dialog.finish_polyline_button.click()
    assert len(dialog.canvas.entities) == 1
    return math.pi * (10**2 * 20 + 6**2 * 30)


def _slot_plate(dialog: SketchEditorDialog) -> float:
    for half_span, radius in ((25.0, 25.0), (15.0, 5.0)):
        _curve(dialog, "直线", (-half_span, -radius), (half_span, -radius))
        _curve(dialog, "圆弧", (half_span, 0.0), (half_span, -radius), (half_span, radius))
        _curve(dialog, "直线", (half_span, radius), (-half_span, radius))
        _curve(dialog, "圆弧", (-half_span, 0.0), (-half_span, radius), (-half_span, -radius))
    for x in (-25.0, 25.0):
        for y in (-15.0, 15.0):
            _curve(dialog, "圆", (x, y), (x + 3.0, y))
    assert len(dialog.canvas.entities) == 12
    return (2500 + 625 * math.pi - 300 - 25 * math.pi - 36 * math.pi) * 6


def test_failed_sketch_submission_restores_editable_draft_for_retry(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new.trigger()
    loaded = window.loaded_document()
    assert loaded is not None
    window.act_sketch.trigger()
    dialog = window.findChild(SketchEditorDialog)
    assert dialog is not None
    _curve(dialog, "圆", (0.0, 0.0), (10.0, 0.0))
    original = tuple(dialog.canvas.entities)
    execute = loaded.bus.execute

    def reject_once(*_args: object, **_kwargs: object) -> object:
        raise ValidationError("simulated sketch validation failure")

    monkeypatch.setattr(loaded.bus, "execute", reject_once)
    dialog.finish_button.click()
    qtbot.waitUntil(lambda: "提交失败" in window.status_command.text(), timeout=10000)
    assert dialog.isVisible()
    assert dialog.result_sketch is None
    assert tuple(dialog.canvas.entities) == original
    assert not loaded.document.commands
    assert "simulated" in dialog.status_label.text()
    monkeypatch.setattr(loaded.bus, "execute", execute)
    dialog.finish_button.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 1, timeout=10000)
    assert services.kernel.sketches[0].entities == original
    assert not dialog.isVisible()


@pytest.mark.parametrize("part", ["flange", "shaft", "slot_plate"])
def test_part_from_gui_sketch_to_solid_undo_archive_and_step(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, part: str
) -> None:
    services = build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new.trigger()
    loaded = window.loaded_document()
    assert loaded is not None and not loaded.document.commands
    window.act_sketch.trigger()
    dialog = window.findChild(SketchEditorDialog)
    assert dialog is not None
    dialog.canvas.setFixedSize(800, 600)
    qtbot.waitExposed(dialog)
    expected_volume = {"flange": _flange, "shaft": _shaft, "slot_plate": _slot_plate}[part](dialog)
    entities = tuple(dialog.canvas.entities)
    dialog.finish_button.click()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and (bool(loaded.document.commands) or "失败" in window.status_command.text())
        ),
        timeout=10000,
    )
    assert len(loaded.document.commands) == 1, window.status_command.text()
    assert services.kernel.sketches[0].entities == entities

    palette = window.command_palette
    assert palette is not None
    command_id = "feature.revolve" if part == "shaft" else "feature.extrude"
    palette.command_activated.emit(command_id)
    bar = window.modeling_command_bar
    assert bar is not None
    source = bar.findChild(QComboBox, "revolveSource" if part == "shaft" else "extrudeSource")
    picker = bar.findChild(QComboBox, "sketchProfile")
    commit = bar.findChild(QPushButton, "modelingCommitButton")
    assert source is not None and picker is not None and commit is not None
    source.setCurrentIndex(source.findData("sketch"))
    picker.setCurrentIndex(picker.findData(services.kernel.sketches[0].sketch_id))
    if part == "shaft":
        axis = bar.findChild(QComboBox, "axis")
        assert axis is not None
        axis.setCurrentIndex(axis.findData("Z"))
    else:
        distance = bar.findChild(QDoubleSpinBox, "distance")
        assert distance is not None
        distance.setValue(8.0 if part == "flange" else 6.0)
    qtbot.waitUntil(commit.isEnabled, timeout=30000)
    assert len(loaded.document.commands) == 1
    assert services.kernel.mass_properties().solid_count == 0
    commit.click()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=30000)
    assert services.kernel.geometry_check().is_valid
    assert services.kernel.mass_properties().solid_count == 1
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, rel=1e-7)
    body_ids = services.kernel.body_ids
    body_selector = services.kernel.interactive_body_selector(body_ids[0])

    window.act_undo.trigger()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 1 and not unit.is_busy, timeout=10000)
    assert services.kernel.mass_properties().solid_count == 0
    window.act_redo.trigger()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=10000)
    assert services.kernel.body_ids != body_ids  # runtime IDs expire on replay
    assert services.kernel.interactive_body_selector(services.kernel.body_ids[0]) == body_selector
    assert services.kernel.sketches[0].entities == entities
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, rel=1e-7)

    if part == "flange":
        dimension_id: str | None = None
        for radius in (41.0, 42.0):
            previous_volume = services.kernel.mass_properties().volume
            previous_count = len(loaded.document.commands)

            def revise_dimension(
                radius: float = radius,
                dimension_id: str | None = dimension_id,
                previous_count: int = previous_count,
                previous_volume: float = previous_volume,
            ) -> None:
                constraints = window.active_sketch_constraint_dialog()
                assert constraints is not None
                try:
                    if dimension_id is not None:
                        constraints.dimension_combo.setCurrentIndex(
                            constraints.dimension_combo.findData(dimension_id)
                        )
                    constraints.kind_combo.setCurrentIndex(
                        constraints.kind_combo.findData("radius")
                    )
                    constraints.value_field.setValue(radius)
                    constraints.preview_button.click()
                    qtbot.waitUntil(constraints.apply_button.isEnabled, timeout=10000)
                    assert len(loaded.document.commands) == previous_count
                    assert services.kernel.mass_properties().volume == pytest.approx(
                        previous_volume
                    )
                    constraints.apply_button.click()
                except BaseException:
                    constraints.reject()
                    raise

            QTimer.singleShot(0, revise_dimension)
            window.act_sketch_constraints.trigger()
            qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
            assert len(loaded.document.commands) == previous_count + 1
            assert loaded.document.commands[-1].id == (
                "sketch.constraint.add" if dimension_id is None else "sketch.constraint.update"
            )
            sketch = services.kernel.sketches[0]
            dimension = next(c for c in sketch.constraints if c.kind == "radius")
            if dimension_id is not None:
                assert dimension.constraint_id == dimension_id
            dimension_id = dimension.constraint_id
            assert tuple(e.entity_id for e in sketch.entities) == tuple(
                e.entity_id for e in entities
            )
            outer = sketch.entities[0]
            assert isinstance(outer, CircleEntity)
            assert outer.radius_mm == pytest.approx(radius)
            expected_volume = math.pi * (radius**2 - 10**2 - 4 * 3**2) * 8
            assert services.kernel.mass_properties().volume == pytest.approx(
                expected_volume, rel=1e-7
            )
            assert services.kernel.geometry_check().is_valid
            window.act_undo.trigger()
            qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
            assert services.kernel.mass_properties().volume == pytest.approx(
                previous_volume, rel=1e-7
            )
            window.act_redo.trigger()
            qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
            assert services.kernel.mass_properties().volume == pytest.approx(
                expected_volume, rel=1e-7
            )
        entities = services.kernel.sketches[0].entities
        # Geometry predicates describe the revised body, not a persistent UUID.
        body_selector = services.kernel.interactive_body_selector(services.kernel.body_ids[0])

    archive = tmp_path / f"{part}.mc.json"
    step = tmp_path / f"{part}.step"

    def save_path(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(archive), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_path)
    window.act_save_as.trigger()
    assert archive.exists()

    def step_path(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(step), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", step_path)
    window.act_export.trigger()
    solid_count, volume = read_step(step)
    assert solid_count == 1
    assert volume == pytest.approx(expected_volume, rel=1e-7)

    def open_path(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(archive), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", open_path)
    window.act_open.trigger()
    qtbot.waitUntil(
        lambda: window.loaded_document() is not loaded and not unit.is_busy, timeout=10000
    )
    assert services.kernel.interactive_body_selector(services.kernel.body_ids[0]) == body_selector
    assert services.kernel.sketches[0].entities == entities
    assert services.kernel.mass_properties().volume == pytest.approx(expected_volume, rel=1e-7)
