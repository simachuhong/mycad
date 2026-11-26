# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Ellipse sketch rendering and selection."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.sketch import EllipseEntity, SplineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def test_create_ellipse_with_command_and_offset(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(offset_ellipse=services.kernel.offset_ellipse)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("ELLIPSE", "0,0", "5,0", "0,3"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1, editor.canvas.message
    entity = editor.canvas.entities[0]
    assert isinstance(entity, EllipseEntity)
    assert entity.major_radius_mm == pytest.approx(5)
    assert entity.minor_radius_mm == pytest.approx(3)
    assert entity.closed
    for value in ("OFFSET", "0.5"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    command.setText("6,0")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) > 1, editor.canvas.message


def test_create_ellipse_by_canvas_points(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    assert not editor.tool_buttons["椭圆"].icon().isNull()
    assert editor.canvas.set_tool("椭圆")
    editor.canvas.set_snapping_enabled(False)
    editor.canvas.set_grid_snapping_enabled(False)
    for point in ((0, 0), (5, 0), (0, 3)):
        screen = editor.canvas.local_to_screen(point)
        QTest.mouseMove(editor.canvas, screen)
        QTest.mouseClick(editor.canvas, Qt.MouseButton.LeftButton, pos=screen)
    assert len(editor.canvas.entities) == 1
    assert isinstance(editor.canvas.entities[0], EllipseEntity)


@pytest.mark.parametrize(
    ("direction", "end", "expected"), [("CCW", "0,3", 90), ("CW", "0,-3", -90)]
)
def test_create_elliptic_arc_and_offset(
    qtbot: QtBot, direction: str, end: str, expected: int
) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(offset_ellipse=services.kernel.offset_ellipse)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("ELLIPSE", "A", direction, "0,0", "5,0", "0,3", "5,0", end):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1, editor.canvas.message
    arc = editor.canvas.entities[0]
    assert isinstance(arc, EllipseEntity)
    assert arc.start_angle_deg == pytest.approx(0)
    assert arc.sweep_angle_deg == pytest.approx(expected)
    for value in ("OFFSET", "0.5"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=editor.canvas.local_to_screen(arc.point_at(0.5)),
    )
    command.setText("6,0")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) > 1, editor.canvas.message


def test_elliptic_arc_numeric_angles_use_geometric_ray_directions(qtbot: QtBot) -> None:
    import math

    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("ELLIPSE", "A", "0,0", "5,0", "0,3", "45", "135"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1, editor.canvas.message
    arc = editor.canvas.entities[0]
    assert isinstance(arc, EllipseEntity)
    for value, expected in ((0, 45), (1, 135)):
        point = arc.point_at(value)
        assert math.degrees(math.atan2(point[1], point[0])) == pytest.approx(expected)


def test_elliptic_arc_mouse_preview_does_not_commit_or_advance(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    command = editor.drawing_command_bar.input
    assert not editor.ellipse_arc_button.icon().isNull()
    QTest.mouseClick(editor.ellipse_arc_button, Qt.MouseButton.LeftButton)
    for value in ("0,0", "5,0", "0,3"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.pending_point_count == 3
    QTest.mouseMove(editor.canvas, editor.canvas.local_to_screen((5, 0)))
    editor.canvas.grab()
    assert editor.canvas.pending_point_count == 3
    for point in ((5, 0), (0, 3)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert len(editor.canvas.entities) == 1
    assert isinstance(editor.canvas.entities[0], EllipseEntity)


def test_elliptic_arc_rejects_empty_sweep_and_escape_cancels(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("ELLIPSE", "A", "0,0", "5,0", "0,3", "45", "45"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert not editor.canvas.entities
    assert editor.canvas.pending_point_count == 4
    assert "不能相同" in editor.canvas.message
    QTest.keyClick(command, Qt.Key.Key_Escape)
    assert not editor.canvas.has_pending_geometry
    assert not editor.canvas.entities


def test_created_elliptic_arc_offset_save_and_dxf(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.persistence import save_document
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf

    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(offset_ellipse=services.kernel.offset_ellipse)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    command = editor.drawing_command_bar.input
    for value in ("ELLIPSE", "A", "0,0", "5,0", "0,3", "0", "90"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 1, editor.canvas.message
    arc = editor.canvas.entities[0]
    assert isinstance(arc, EllipseEntity)
    for value in ("OFFSET", "0.5"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=editor.canvas.local_to_screen(arc.point_at(0.5)),
    )
    command.setText("6,0")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) > 1, editor.canvas.message
    QTest.keyClick(command, Qt.Key.Key_Escape)
    editor.finish_sketch()
    sketch = editor.result_sketch
    assert sketch is not None
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = tmp_path / "elliptic-arc.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, target)
    assert reopened.kernel.sketches == (sketch,)
    dxf = tmp_path / "elliptic-arc.dxf"
    write_sketch_dxf(sketch, dxf)
    imported = read_sketch_dxf(dxf).sketch
    assert len(imported.entities) == len(sketch.entities)
    imported_arc = imported.entities[0]
    assert isinstance(imported_arc, EllipseEntity)
    assert imported_arc.point_at(0.5) == pytest.approx(arc.point_at(0.5))


def test_ellipse_is_rendered_and_selectable(qtbot: QtBot) -> None:
    editor = SketchEditorDialog()
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    ellipse = EllipseEntity(uuid4().hex, (2, 3), 6, 3, 25, 10, -130)
    assert editor.canvas.replace_draft_entities((ellipse,))
    assert editor.canvas.set_tool("选择元素")
    qtbot.waitExposed(editor)
    QTest.mouseClick(
        editor.canvas,
        Qt.MouseButton.LeftButton,
        pos=editor.canvas.local_to_screen(ellipse.point_at(0.5)),
    )
    assert editor.canvas.selected_entity_ids == {ellipse.entity_id}
    editor.canvas.grab()


@pytest.mark.parametrize(("command_value", "side"), [("T", "5.5,0"), ("0.5", "4,0")])
def test_ellipse_offset_through_command_and_undo(
    qtbot: QtBot, command_value: str, side: str
) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(offset_ellipse=services.kernel.offset_ellipse)
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    ellipse = EllipseEntity(uuid4().hex, (0, 0), 5, 3)
    assert editor.canvas.replace_draft_entities((ellipse,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", command_value):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    command.setText(side)
    QTest.keyClick(command, Qt.Key.Key_Return)
    result = editor.canvas.entities[1:]
    assert result and all(isinstance(item, SplineEntity) for item in result), editor.canvas.message
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.entities == [ellipse]


def test_closed_ellipse_can_be_offset_repeatedly(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        offset_ellipse=services.kernel.offset_ellipse,
        offset_spline_path=services.kernel.offset_spline_path,
    )
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    ellipse = EllipseEntity(uuid4().hex, (0, 0), 5, 3)
    assert editor.canvas.replace_draft_entities((ellipse,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "0.5"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    for value in ("M", "6,0"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    first = tuple(editor.canvas.entities[1:])
    assert first, editor.canvas.message
    command.setText("7,0")
    QTest.keyClick(command, Qt.Key.Key_Return)
    second = editor.canvas.entities[1 + len(first) :]
    assert second, editor.canvas.message


@pytest.mark.parametrize("other_ellipse", [False, True])
def test_saved_ellipse_offset_erase_replays(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, other_ellipse: bool
) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.main_window import MainWindow
    from mycad.ui.viewport import GLViewport

    def no_gl_paint(_self: GLViewport, *_args: object, **_kwargs: object) -> None:
        pass

    monkeypatch.setattr(GLViewport, "paintGL", no_gl_paint)
    services = app.build_app(discoverers=())
    loaded = app.new_document(services, document_type="drawing2d")
    ellipse = EllipseEntity(uuid4().hex, (0, 0), 5, 3)
    second = EllipseEntity(uuid4().hex, (20, 0), 5, 3)
    sketch = Sketch(
        uuid4().hex, WorkPlaneFrame.xy(), (ellipse, second) if other_ellipse else (ellipse,)
    )
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.resize(1400, 900)
    window.show()
    window.workspace_tabs.activate("sketch")
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "E", "Y", "0.5"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    command.setText("6,0")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    assert canvas.entities and all(isinstance(item, SplineEntity) for item in canvas.entities)
    QTest.keyClick(command, Qt.Key.Key_Escape)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
    )
    result = services.kernel.sketches
    target = tmp_path / "ellipse-offset.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    opened = app.open_app_document(reopened, target)
    assert reopened.kernel.sketches == result
    opened.bus.undo()
    assert sketch in reopened.kernel.sketches
