# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Direct canvas placement owns a transient group until Enter."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.drawing import DrawingSheet, DrawingState
from mycad.ui.drawing_tools import ViewPlacement


def test_place_base_then_first_angle_projected_view_without_committing() -> None:
    sheet = DrawingSheet(uuid4())
    state = DrawingState(sheets=(sheet,))
    placement = ViewPlacement(sheet, scale=0.5)
    placement.click((90, 140))
    ghost = placement.preview((92, 70))
    assert ghost is not None and ghost.direction == "top"
    assert ghost.offset_mm == (0, -70)
    placement.click((92, 70))
    placed = placement.finish()
    assert len(placed) == 2
    assert placed[1].parent_id == placed[0].view_id
    assert placed[0].scale == 0.5
    assert not state.views


def test_escape_discards_entire_uncommitted_group() -> None:
    placement = ViewPlacement(DrawingSheet(uuid4()))
    placement.click((90, 100))
    placement.click((160, 103))
    placement.cancel()
    assert placement.finish() == ()


def test_canvas_group_enter_and_undo(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtCore import QPointF, Qt

    from mycad.app import build_app, new_document
    from mycad.core.drawing_projection import LineCurve, ProjectedCurve, ProjectionResult
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 40, "size_y": 20, "size_z": 8}, "test")
    sheet = uuid4()
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    window.bind_document(loaded)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench.begin_placement()
    placement = bench.placement
    assert placement is not None
    for identity in (
        placement.base_id,
        *(placement.projected_id(d) for d in ("top", "bottom", "left", "right")),
    ):
        bench.projections[identity] = ProjectionResult(
            identity, "fixture", 1, (ProjectedCurve("line", LineCurve((0, 0), (20, 0))),)
        )
    bench.canvas.placing = True
    for point in (QPointF(90, -140), QPointF(90, -70)):
        QTest.mouseClick(
            bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=bench.canvas.mapFromScene(point)
        )
    assert len(loaded.document.commands) == 2
    assert len(placement.pending) == 2, (placement.pending, bench.hint.text())
    QTest.keyClick(bench.canvas, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 3 and bench.placement is None)
    assert len(services.kernel.drawing_state.views) == 2
    window.request_undo()
    qtbot.waitUntil(lambda: not services.kernel.drawing_state.views)
    assert len(loaded.document.commands) == 2


def test_new_document_clears_previous_sheet_canvas(qtbot: QtBot) -> None:
    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    loaded = new_document(services)
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(uuid4())})
    window.bind_document(loaded)
    assert window.drawing_workbench.canvas.drawing_scene is not None
    window.bind_document(new_document(services))
    assert window.drawing_workbench.canvas.drawing_scene is None


def test_unnormalized_periodic_spline_is_not_drawn_as_its_control_polygon() -> None:
    from mycad.core.drawing_projection import SplineCurve
    from mycad.ui.drawing_canvas import curve_path

    curve = SplineCurve(((0, 0), (10, 0), (5, 10)), 2, (0, 1, 2, 3), (1, 1, 1, 1), (1, 1, 1), True)
    with pytest.raises(ValueError, match="周期"):
        curve_path(curve)


def test_real_model_projection_is_placed_in_canvas(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtCore import QPointF, Qt

    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute(
        "feature.box", {"size_x": 40, "size_y": 24, "size_z": 8, "center": [6, 9, 13]}
    )
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    bench = window.drawing_workbench
    bench.begin_placement()
    qtbot.waitUntil(lambda: bench.canvas.placing, timeout=60000)
    assert bench.placement is not None
    assert bench.placement.base_id in bench.projections
    bench.canvas.fit_view()
    for point in (QPointF(90, -140), QPointF(90, -70), QPointF(180, -140)):
        pos = bench.canvas.mapFromScene(point)
        QTest.mouseMove(bench.canvas.viewport(), pos)
        QTest.mouseClick(bench.canvas.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    QTest.keyClick(bench.canvas, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: len(services.kernel.drawing_state.views) == 3 and bench.placement is None,
        timeout=10000,
    )
    qtbot.waitUntil(lambda: window.execution_unit is not None and not window.execution_unit.is_busy)
    scene = bench.canvas.drawing_scene
    assert scene is not None and len(scene.views) == 3
    assert not scene.issues
    screenshot = tmp_path / "engineering-workspace.png"
    assert window.grab().save(str(screenshot))
    print(f"Engineering workspace screenshot: {screenshot}")
    window.resize(960, 600)
    qtbot.wait(50)
    narrow = tmp_path / "engineering-narrow.png"
    assert window.grab().save(str(narrow))
    bench.parameter_dock.setFloating(True)
    bench.parameter_dock.show()
    qtbot.wait(50)
    floating = tmp_path / "engineering-floating.png"
    assert window.grab().save(str(floating))
    assert bench.parameter_dock.grab().save(str(tmp_path / "engineering-settings.png"))
    print(f"Narrow/floating screenshots: {narrow}, {floating}")


def test_changed_model_pauses_uncommitted_placement(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 10, "size_z": 5})
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(uuid4())})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    bench.begin_placement()
    placement = bench.placement
    assert placement is not None
    placement.click((90, 140))
    bench.canvas.placing = True
    loaded.bus.execute("feature.box", {"size_x": 30, "size_y": 10, "size_z": 5})
    bench.refresh()
    assert bench.placement is placement and len(placement.pending) == 1
    assert not bench.canvas.placing
    assert "更新预览" in bench.hint.text()
    bench.cancel_placement()


def test_pending_engineering_group_blocks_document_replacement(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(uuid4())})
    loaded.document.mark_clean()
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    bench = window.drawing_workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    bench.begin_placement()
    assert bench.placement is not None
    bench.placement.click((90, 140))
    assert not window.close()
    assert "工程图" in window.status_command.text()
    bench.cancel_placement()


def test_opened_sheet_fits_on_first_activation_only(qtbot: QtBot) -> None:
    from PySide6.QtCore import QRectF

    from mycad.app import build_app, new_document
    from mycad.ui.main_window import MainWindow

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(uuid4())})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.workspace_tabs.activate("drawing")
    qtbot.wait(50)
    canvas = window.drawing_workbench.canvas
    paper = canvas.mapFromScene(QRectF(0, -210, 297, 210)).boundingRect()
    assert paper.height() > canvas.viewport().height() * 0.8
    canvas.scale(1.7, 1.7)
    transform = canvas.transform()
    window.workspace_tabs.activate("model")
    window.workspace_tabs.activate("drawing")
    qtbot.wait(50)
    assert canvas.transform() == transform
