# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""DXF import keeps visible annotations when another layer is frozen."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.dimension_styles import DimensionStyle, DimensionStyleTable
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
from mycad.core.sketch_layers import DEFAULT_SKETCH_LAYER, SketchLayer, SketchLayerTable
from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketches_dxf
from mycad.ui.main_window import MainWindow


def test_frozen_dimension_dxf_import_keeps_other_dimensions_visible(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layers = SketchLayerTable((DEFAULT_SKETCH_LAYER, SketchLayer("冻结层", frozen=True)))
    visible = LineEntity(uuid4().hex, (0, 0), (20, 0))
    hidden = LineEntity(uuid4().hex, (0, 20), (20, 20))
    style = DimensionStyle("源样式")
    dimensions = tuple(
        SketchConstraint(
            uuid4().hex,
            "length",
            (SketchGeometryReference(line.entity_id, "geometry"),),
            20,
            "mm",
            driving=False,
            position_mm=(10, y),
            style_name=style.name,
            layer_name=layer,
        )
        for line, y, layer in ((visible, 5, "0"), (hidden, 25, "冻结层"))
    )
    source = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (visible, hidden), dimensions, layers)
    path = tmp_path / "frozen.dxf"
    write_sketches_dxf((source,), path, dimension_styles=DimensionStyleTable((style,), style.name))
    imported = read_sketch_dxf(path)
    assert len(imported.sketch.constraints) == 2
    assert imported.sketch.layers.get("冻结层").frozen
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_kw: QMessageBox.StandardButton.Yes)
    window._queue_dxf_sketch_import(path, unit_override=None)
    qtbot.waitUntil(
        lambda: (
            bool(loaded.document.commands) and not unit.is_busy and not unit.is_delivering_result
        ),
        timeout=10000,
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    assert len(services.kernel.sketches[0].constraints) == 2
    assert {c.layer_name for c in editor.canvas.visible_dimensions()} == {"0"}
    canvas = editor.canvas
    canvas.grid_visible = False
    point = QPointF(80, 60)
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            point,
            point,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    cursor_pixel = canvas.grab().toImage().pixelColor(80, 60)
    QApplication.sendEvent(canvas, QEvent(QEvent.Type.Leave))
    assert canvas.grab().toImage().pixelColor(80, 60) != cursor_pixel

    window.act_undo.trigger()
    qtbot.waitUntil(lambda: not services.kernel.sketches and not unit.is_busy, timeout=10000)
    window.act_redo.trigger()
    qtbot.waitUntil(lambda: bool(services.kernel.sketches) and not unit.is_busy, timeout=10000)
    assert {c.layer_name for c in canvas.visible_dimensions()} == {"0"}
    table = services.kernel.drawing_layers
    thawed = table.replace(replace(table.get("冻结层"), frozen=False))
    loaded.bus.execute(
        "drawing.layers.set",
        {"layers": thawed.to_mapping(), "dimension_layer": services.kernel.dimension_layer},
        "local",
    )
    window._sync_drawing_layers()
    assert {c.layer_name for c in canvas.visible_dimensions()} == {"0", "冻结层"}
