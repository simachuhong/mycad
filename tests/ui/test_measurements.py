# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Measure-tab interaction and revision-safe display."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.core.measurements import (
    MeasurementKind,
    MeasurementRequest,
    MeasurementResult,
    MeasurementTarget,
)
from mycad.ui.main_window import MainWindow
from mycad.ui.right_panel import RIGHT_TAB_TITLES, RightPanel


def test_measure_tab_runs_volume_query_and_displays_units(qapp: object) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.cylinder", {"radius": 5.0, "height": 8.0}, "test")
    panel = RightPanel()
    panel.bind_document(loaded, services.registry, kernel=services.kernel)

    index = RIGHT_TAB_TITLES.index("测量")
    assert panel.tabs.isTabEnabled(index)
    panel.tabs.setCurrentIndex(index)
    measure_button = panel.findChild(QPushButton, "measureButton")
    assert measure_button is not None
    measure_button.click()

    label = panel.findChild(QLabel, "measurementResult")
    assert label is not None
    assert "mm³" in label.text()
    assert "BREP" in label.text()


def test_measure_tab_selects_a_cylindrical_face_from_exact_targets(qapp: object) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.cylinder", {"radius": 5.0, "height": 8.0}, "test")
    panel = RightPanel()
    panel.bind_document(loaded, services.registry, kernel=services.kernel)
    kind_combo = panel.findChild(QComboBox, "measurementKind")
    target_combo = panel.findChild(QComboBox, "measurementTarget0")
    measure_button = panel.findChild(QPushButton, "measureButton")
    assert kind_combo is not None and target_combo is not None and measure_button is not None

    kind_combo.setCurrentIndex(1)
    target_combo.setCurrentIndex(1)
    measure_button.click()

    label = panel.findChild(QLabel, "measurementResult")
    assert label is not None
    assert "10 mm" in label.text()


def test_measure_tab_clears_previous_result_when_model_changes(qapp: object) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.cylinder", {"radius": 5.0, "height": 8.0}, "test")
    window = MainWindow(services=services)
    window.bind_document(loaded)
    panel = window.right_panel
    assert panel is not None
    measure_button = panel.findChild(QPushButton, "measureButton")
    assert measure_button is not None
    measure_button.click()

    loaded.bus.execute("feature.cylinder", {"radius": 6.0, "height": 8.0}, "test")

    label = panel.findChild(QLabel, "measurementResult")
    assert label is not None
    assert label.text() == "模型已变化，请重新测量。"
    window.close()


def test_measure_tab_invalidates_on_undo_and_clears_on_rebind(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.cylinder", {"radius": 5.0, "height": 8.0}, "test")
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    panel = window.right_panel
    assert panel is not None
    measure_button = panel.findChild(QPushButton, "measureButton")
    label = panel.findChild(QLabel, "measurementResult")
    assert measure_button is not None and label is not None
    measure_button.click()
    loaded.bus.execute(
        "feature.cylinder",
        {"radius": 2.0, "height": 8.0, "mode": "add"},
        "test",
    )
    loaded.bus.undo()
    assert label.text() == "模型已变化，请重新测量。"

    replacement = new_document(services)
    window.bind_document(replacement)

    assert label.text() == "选择测量类型并执行；结果来自当前精确 BREP。"
    window.close()


def test_measure_tab_defers_kernel_queries_while_execution_is_busy(
    qapp: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.cylinder", {"radius": 5.0, "height": 8.0}, "test")
    panel = RightPanel()
    panel.bind_document(loaded, services.registry, kernel=services.kernel)
    kind_combo = panel.findChild(QComboBox, "measurementKind")
    measure_button = panel.findChild(QPushButton, "measureButton")
    assert kind_combo is not None and measure_button is not None
    kind_combo.setCurrentIndex(2)

    target_queries: list[MeasurementKind] = []
    measurements: list[MeasurementRequest] = []

    def record_targets(kind: MeasurementKind) -> tuple[MeasurementTarget, ...]:
        target_queries.append(kind)
        return ()

    def record_measurement(request: MeasurementRequest) -> MeasurementResult:
        measurements.append(request)
        return MeasurementResult(None, "mm", request.revision, "test", error="unused")

    monkeypatch.setattr(services.kernel, "measurement_targets", record_targets)
    monkeypatch.setattr(services.kernel, "measure", record_measurement)
    panel.set_measurement_busy(True)
    kind_combo.currentIndexChanged.emit(2)
    measure_button.clicked.emit()

    assert not kind_combo.isEnabled()
    assert not measure_button.isEnabled()
    assert target_queries == []
    assert measurements == []

    panel.set_measurement_busy(False)
    assert target_queries == ["circular_edge_center_distance"]
