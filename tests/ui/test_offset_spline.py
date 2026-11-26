# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Spline offsets can be selected, placed and undone from the drawing command."""

import math
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.sketch import SplineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def test_spline_offset_preview_is_reused_when_committed(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(offset_spline=services.kernel.offset_spline)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    source = SplineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5), (10, 5)))
    assert canvas.replace_draft_entities((source,))
    canvas.begin_interactive_offset()
    canvas.set_interactive_offset_distance(1)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 2.5)))
    side = canvas.local_to_screen((4, 3.5))
    QTest.mouseMove(canvas, side)
    preview = canvas.transform_preview_entities
    assert len(preview) > 1 and canvas.entities == [source], canvas.message
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=side)
    assert tuple(canvas.entities) == (source, *preview)


@pytest.mark.parametrize("through", [False, True])
def test_multiple_spline_offsets_complete_whole_path(qtbot: QtBot, through: bool) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        offset_spline=services.kernel.offset_spline,
        offset_spline_path=services.kernel.offset_spline_path,
    )
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    source = SplineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5), (10, 5)))
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "T" if through else "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 2.5)))
    command.setText("M")
    QTest.keyClick(command, Qt.Key.Key_Return)
    command.setText("4.292893218813452,3.207106781186548" if through else "4,3.5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    first = tuple(canvas.entities[1:])
    assert len(first) > 1, canvas.message
    command.setText("3.585786437626905,3.914213562373095" if through else "3,5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    second = tuple(canvas.entities[1 + len(first) :])
    assert second and all(isinstance(piece, SplineEntity) for piece in second), canvas.message
    start = second[0]
    end = second[-1]
    assert isinstance(start, SplineEntity) and isinstance(end, SplineEntity)
    assert start.control_points_mm[0] == pytest.approx((0, 2), abs=0.003)
    assert end.control_points_mm[-1] == pytest.approx((10, 7), abs=0.003)
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert tuple(canvas.entities) == (source, *first)
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [source]


def test_multiple_spline_offsets_erase_the_entire_previous_path(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        offset_spline=services.kernel.offset_spline,
        offset_spline_path=services.kernel.offset_spline_path,
    )
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    source = SplineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5), (10, 5)))
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "E", "Y", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 2.5)))
    for value in ("M", "4,3.5"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    first = tuple(canvas.entities)
    assert len(first) > 1 and source not in first, canvas.message
    command.setText("3,5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert not any(piece in canvas.entities for piece in first), canvas.message
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert tuple(canvas.entities) == first
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [source]


def test_multiple_spline_offsets_erase_saved_source_and_replay(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    source = SplineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5), (10, 5)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
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
    for value in ("OFFSET", "E", "Y", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 2.5)))
    for value in ("M", "4,3.5"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: canvas.mixed_move is not None and not unit.is_busy, timeout=10000)
    first = tuple(canvas.entities)
    assert len(first) > 1, canvas.message
    command.setText("3,5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert not any(piece in canvas.entities for piece in first), canvas.message
    final = tuple(canvas.entities)
    QTest.keyClick(command, Qt.Key.Key_Escape)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
    )
    result = services.kernel.sketches
    assert tuple(entity for item in result for entity in item.entities) == final
    target = tmp_path / "multiple-spline.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    opened = app.open_app_document(reopened, target)
    assert reopened.kernel.sketches == result
    opened.bus.undo()
    assert tuple(entity for item in reopened.kernel.sketches for entity in item.entities) == first
    opened.bus.undo()
    assert tuple(entity for item in reopened.kernel.sketches for entity in item.entities) == (
        source,
    )


@pytest.mark.parametrize("through", [False, True])
def test_multibranch_spline_offset_commits_and_undoes_atomically(
    qtbot: QtBot, through: bool
) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(offset_spline=services.kernel.offset_spline)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    source = SplineEntity(
        uuid4().hex,
        (
            (0, 0),
            (2, -0.30887313143051287),
            (4, -14.544001272786543),
            (6, -11.928687954497818),
            (8, -2.1618404888753933),
            (10, -14.31667550479806),
            (12, 0.8198072473745395),
            (14, 0),
        ),
    )
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "T" if through else "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    point = source.point_at(0.5)
    previous, following = source.point_at(0.499), source.point_at(0.501)
    dx, dy = following[0] - previous[0], following[1] - previous[1]
    length = math.hypot(dx, dy)
    side = (point[0] - dy / length, point[1] + dx / length)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    command.setText(f"{side[0]},{side[1]}")
    QTest.keyClick(command, Qt.Key.Key_Return)
    copies = canvas.entities[1:]
    assert copies and all(isinstance(piece, SplineEntity) for piece in copies), canvas.message
    gaps = [
        math.dist(left.control_points_mm[-1], right.control_points_mm[0])
        for left, right in zip(copies, copies[1:], strict=False)
        if isinstance(left, SplineEntity) and isinstance(right, SplineEntity)
    ]
    assert sum(gap > 0.001 for gap in gaps) == 1
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [source]
    QTest.keyClick(command, Qt.Key.Key_Escape)
    assert canvas.redo_last_operation()
    assert canvas.entities == [source, *copies]


def test_multiple_offset_repeats_all_spline_branches(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        offset_spline=services.kernel.offset_spline,
        offset_spline_path=services.kernel.offset_spline_path,
    )
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    source = SplineEntity(
        uuid4().hex,
        (
            (0, 0),
            (2, -0.30887313143051287),
            (4, -14.544001272786543),
            (6, -11.928687954497818),
            (8, -2.1618404888753933),
            (10, -14.31667550479806),
            (12, 0.8198072473745395),
            (14, 0),
        ),
    )
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    point = source.point_at(0.5)
    previous, following = source.point_at(0.499), source.point_at(0.501)
    dx, dy = following[0] - previous[0], following[1] - previous[1]
    length = math.hypot(dx, dy)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    command.setText("M")
    QTest.keyClick(command, Qt.Key.Key_Return)
    first = tuple(canvas.entities[0:0])
    for offset in (1, 2):
        side = (point[0] - offset * dy / length, point[1] + offset * dx / length)
        command.setText(f"{side[0]},{side[1]}")
        QTest.keyClick(command, Qt.Key.Key_Return)
        if offset == 1:
            first = tuple(canvas.entities[1:])
            assert first, canvas.message
    second = tuple(canvas.entities[1 + len(first) :])
    assert second and all(isinstance(piece, SplineEntity) for piece in second), canvas.message
    gaps = [
        math.dist(left.control_points_mm[-1], right.control_points_mm[0])
        for left, right in zip(second, second[1:], strict=False)
        if isinstance(left, SplineEntity) and isinstance(right, SplineEntity)
    ]
    assert any(gap > 0.001 for gap in gaps)


def test_offset_spline_with_closed_branch_is_one_undoable_operation(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(offset_spline=services.kernel.offset_spline)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    source = SplineEntity(
        uuid4().hex,
        (
            (0, 0),
            (-6.786802587550828, -4.4473769780254),
            (-6.977086685631252, -11.85600115039905),
            (-4.030346433512766, 3.774678688938385),
            (-11.919812531441856, 6.223357645296851),
            (-5.211271800158748, -7.731866967633548),
            (-8.694942377770245, -8.718534142072972),
            (6.691872686821082, 3.9656816441476934),
        ),
    )
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    point = source.point_at(0.05)
    before, after = source.point_at(0.049), source.point_at(0.051)
    dx, dy = after[0] - before[0], after[1] - before[1]
    length = math.hypot(dx, dy)
    side = (point[0] - dy / length, point[1] + dx / length)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    command.setText(f"{side[0]},{side[1]}")
    QTest.keyClick(command, Qt.Key.Key_Return)
    copies = canvas.entities[1:]
    assert copies and all(isinstance(piece, SplineEntity) for piece in copies), canvas.message
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [source]


def test_drawing_spline_offset_uses_selected_side_and_undo(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        offset_closed_path=services.kernel.offset_closed_path,
        offset_spline=services.kernel.offset_spline,
    )
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    source = SplineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5), (10, 5)))
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 2.5)))
    command.setText("4,3.5")
    QTest.keyClick(command, Qt.Key.Key_Return)
    copies = canvas.entities[1:]
    assert copies and all(isinstance(item, SplineEntity) for item in copies), canvas.message
    first = copies[0]
    assert isinstance(first, SplineEntity)
    assert first.control_points_mm[0] == pytest.approx((0, 1), abs=0.001)
    assert "独立" in canvas.message and "0.001" in canvas.message
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [source]


@pytest.mark.parametrize("through", [False, True])
def test_spline_can_offset_to_right_or_through_point(qtbot: QtBot, through: bool) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True, offset_spline=services.kernel.offset_spline
    )
    qtbot.addWidget(editor)
    editor.show()
    source = SplineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5), (10, 5)))
    assert editor.canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "T" if through else "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 2.5))
    )
    command.setText("5.707106781186547,1.7928932188134525")
    QTest.keyClick(command, Qt.Key.Key_Return)
    copies = editor.canvas.entities[1:]
    assert copies, editor.canvas.message
    first = copies[0]
    assert isinstance(first, SplineEntity)
    assert first.control_points_mm[0] == pytest.approx((0, -1), abs=0.001)


def test_spline_offset_save_reopen_and_dxf(tmp_path: Path) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf

    services = app.build_app(discoverers=())
    source = SplineEntity(uuid4().hex, ((0, 0), (5, 0), (5, 5), (10, 5)))
    copies = services.kernel.offset_spline(source, 1)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, *copies))
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = tmp_path / "spline-offset.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    opened = app.open_app_document(reopened, target)
    assert reopened.kernel.sketches == (sketch,)
    opened.bus.undo()
    assert reopened.kernel.sketches == ()
    opened.bus.redo()
    assert reopened.kernel.sketches == (sketch,)
    dxf = tmp_path / "spline-offset.dxf"
    write_sketch_dxf(sketch, dxf)
    imported = read_sketch_dxf(dxf).sketch
    assert len(imported.entities) == len(sketch.entities)
    assert [
        item.control_points_mm for item in imported.entities if isinstance(item, SplineEntity)
    ] == pytest.approx([item.control_points_mm for item in (source, *copies)])


def test_multibranch_spline_offset_save_reopen_and_dxf(tmp_path: Path) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf

    services = app.build_app(discoverers=())
    source = SplineEntity(
        uuid4().hex,
        (
            (0, 0),
            (2, -0.30887313143051287),
            (4, -14.544001272786543),
            (6, -11.928687954497818),
            (8, -2.1618404888753933),
            (10, -14.31667550479806),
            (12, 0.8198072473745395),
            (14, 0),
        ),
    )
    copies = services.kernel.offset_spline(source, 1)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, *copies))
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = tmp_path / "split-spline.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    opened = app.open_app_document(reopened, target)
    assert reopened.kernel.sketches == (sketch,)
    opened.bus.undo()
    assert reopened.kernel.sketches == ()
    opened.bus.redo()
    assert reopened.kernel.sketches == (sketch,)
    dxf = tmp_path / "split-spline.dxf"
    write_sketch_dxf(sketch, dxf)
    imported = read_sketch_dxf(dxf).sketch
    assert [
        item.control_points_mm for item in imported.entities if isinstance(item, SplineEntity)
    ] == pytest.approx([item.control_points_mm for item in (source, *copies)])


def test_closed_branch_save_reopen_and_dxf(tmp_path: Path) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf

    services = app.build_app(discoverers=())
    source = SplineEntity(
        uuid4().hex,
        (
            (0, 0),
            (-6.786802587550828, -4.4473769780254),
            (-6.977086685631252, -11.85600115039905),
            (-4.030346433512766, 3.774678688938385),
            (-11.919812531441856, 6.223357645296851),
            (-5.211271800158748, -7.731866967633548),
            (-8.694942377770245, -8.718534142072972),
            (6.691872686821082, 3.9656816441476934),
        ),
    )
    copies = services.kernel.offset_spline(source, 1)
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, *copies))
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = tmp_path / "closed-branch.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    opened = app.open_app_document(reopened, target)
    assert reopened.kernel.sketches == (sketch,)
    opened.bus.undo()
    assert reopened.kernel.sketches == ()
    opened.bus.redo()
    assert reopened.kernel.sketches == (sketch,)
    dxf = tmp_path / "closed-branch.dxf"
    write_sketch_dxf(sketch, dxf)
    imported = read_sketch_dxf(dxf).sketch
    assert [
        piece.control_points_mm for piece in imported.entities if isinstance(piece, SplineEntity)
    ] == pytest.approx([piece.control_points_mm for piece in (source, *copies)])
