# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Datum bars follow baselines and creation uses the saved default."""

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.ui.drawing_annotation_projection import project_annotation
from mycad.ui.main_window import MainWindow


def test_circle_on_new_rectangle_uses_edge_direction(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Draw and annotate without saving or submitting the rectangle first."""
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    window.act_default_datum_circle.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    assert canvas.set_tool("矩形")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    canvas.add_coordinate_point((80, 25), exact_point=True)
    assert len(canvas.entities) == 1
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    tools.begin_mechanical_datum()
    target = canvas.local_to_screen((35, 25))
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(target),
            QPointF(canvas.mapToGlobal(target)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert tools.datum_target_preview is not None
    assert tools.datum_target_preview[0].y() == pytest.approx(tools.datum_target_preview[1].y())
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=target)
    end = canvas.local_to_screen((50, 50))
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(end),
            QPointF(canvas.mapToGlobal(end)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    preview = tools.mechanical_datum_preview
    assert preview is not None
    assert preview.bar_direction is not None
    _, bar = tools.circular_datum_screen_geometry(preview)
    assert bar[0].y() == pytest.approx(bar[1].y())

    def answer(*args: object, **kwargs: object) -> tuple[str, bool]:
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", answer)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert len(tools.datums) == 1
    assert tools.datums[0].bar_direction is not None
    displayed = tools.display_datum(tools.datums[0])
    assert displayed is not None
    _, bar = tools.circular_datum_screen_geometry(displayed)
    assert bar[0].y() == pytest.approx(bar[1].y())
    assert tools.datums[0].target_mm[1] == pytest.approx(25)
    # Saving must retain the direction even though picking the draft must not
    # fabricate an attachment to a sketch that was absent from command history.
    assert tools.datums[0].attachment is None
    path = tmp_path / "draft-rectangle-datum.my2d"

    def choose_path(*args: object, **kwargs: object) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose_path)
    window.act_save.trigger()
    qtbot.waitUntil(path.exists, timeout=10000)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, path)
    assert len(reopened.kernel.sketches) == 1
    saved = reopened.kernel.drawing_datum_identifiers[0]
    assert saved.bar_direction is not None
    assert abs(saved.bar_direction[0]) == pytest.approx(1)
    assert saved.bar_direction[1] == pytest.approx(0)


def test_bar_direction_rotates_with_drawing_view() -> None:
    datum = DatumIdentifier(
        "9" * 32, "A", (20, 30), (0, 0), symbol_style="circle", bar_direction=(1, 0)
    )
    view = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    projected = project_annotation(datum, WorkPlaneFrame.xy(), view)
    assert isinstance(projected, DatumIdentifier)
    assert projected.bar_direction == pytest.approx((0, -1))


@pytest.mark.parametrize("end", [(80, 0), (0, 80), (60, 40)])
def test_existing_circle_bar_is_parallel_to_attached_line(
    qtbot: QtBot, end: tuple[float, float]
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity("a" * 32, (0, 0), end)
    sketch = Sketch("b" * 32, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = (end[0] / 2, end[1] / 2)
    datum = DatumIdentifier(
        "c" * 32,
        "A",
        (target[0] + 14, target[1] + 23),
        target,
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "geometry"), 0.5
        ),
        layout_mode="shared",
        symbol_style="circle",
    )
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=30
    )
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    _, bar = tools.circular_datum_screen_geometry(services.kernel.drawing_datum_identifiers[0])
    direction = bar[1] - bar[0]
    assert direction.x() * (-end[1]) - direction.y() * end[0] == pytest.approx(0, abs=1e-6)


def test_default_circle_is_saved_and_used_for_preview_and_creation(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    window.act_default_datum_circle.trigger()
    assert window.act_default_datum_circle.isChecked()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity("d" * 32, (0, 0), (80, 0))
    sketch = Sketch("e" * 32, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    canvas = editor.canvas
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    tools.begin_mechanical_datum()
    hover = canvas.local_to_screen((35, 0))
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(hover),
            QPointF(canvas.mapToGlobal(hover)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert tools.datum_target_preview is not None
    assert tools.datum_target_preview[0].y() == pytest.approx(tools.datum_target_preview[1].y())
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((35, 0)))
    end = canvas.local_to_screen((50, 25))
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(end),
            QPointF(canvas.mapToGlobal(end)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    preview = tools.mechanical_datum_preview
    assert preview is not None and preview.symbol_style == "circle"
    _, bar = tools.circular_datum_screen_geometry(preview)
    assert bar[0].y() == pytest.approx(bar[1].y())

    def answer(*args: object, **kwargs: object) -> tuple[str, bool]:
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", answer)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert services.kernel.drawing_datum_identifiers[0].symbol_style == "circle"
    second = MainWindow(services=app.build_app(discoverers=()))
    qtbot.addWidget(second)
    assert second.act_default_datum_circle.isChecked()
    second.act_default_datum_rectangle.trigger()
    assert second.act_default_datum_rectangle.isChecked()
    second.show()
    second.act_new_drawing.trigger()
    other = second.active_sketch_dialog()
    assert other is not None and other.canvas.geometric_tolerance_tools is not None
    other_tools = other.canvas.geometric_tolerance_tools
    other_tools.begin_mechanical_datum()
    QTest.mouseClick(
        other.canvas, Qt.MouseButton.LeftButton, pos=other.canvas.local_to_screen((0, 0))
    )
    end = other.canvas.local_to_screen((15, 20))
    QApplication.sendEvent(
        other.canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(end),
            QPointF(other.canvas.mapToGlobal(end)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    preview = other_tools.mechanical_datum_preview
    assert preview is not None and preview.symbol_style == "rectangle"
    other_tools.cancel()
