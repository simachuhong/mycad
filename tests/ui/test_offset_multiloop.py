# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The drawing offset command commits split paths as one undoable operation."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.sketch import PolylineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


@pytest.mark.parametrize("gap_type", [1, 2])
def test_through_point_at_corner_join_commits(qtbot: QtBot, gap_type: int) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(offset_closed_path=services.kernel.offset_closed_path)
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10), (0, 10)), True)
    editor.canvas.replace_draft_entities((source,))
    editor.canvas.set_offset_gap_type(gap_type)
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "T"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((5, 0))
    )
    command.setText("-1,-2")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 2, editor.canvas.message


@pytest.mark.parametrize("method", ["distance", "through", "multiple"])
def test_split_preview_commit_and_undo(qtbot: QtBot, method: str) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        offset_closed_path=services.kernel.offset_closed_path,
    )
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    points = (
        (0, 0),
        (4, 0),
        (4, 1),
        (6, 1),
        (6, 0),
        (10, 0),
        (10, 4),
        (6, 4),
        (6, 3),
        (4, 3),
        (4, 4),
        (0, 4),
    )
    source = PolylineEntity(uuid4().hex, points, True)
    editor.canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "T" if method == "through" else "1.1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((2, 0))
    )
    if method == "multiple":
        command.setText("M")
        QTest.keyClick(command, Qt.Key.Key_Return)
    command.setText("2,1.1")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 3
    assert not editor.canvas.selected_entity_ids
    first, second = editor.canvas.entities[1:]
    assert isinstance(first, PolylineEntity) and isinstance(second, PolylineEntity)
    assert first.closed and second.closed
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.entities == [source]
    QTest.keyClick(command, Qt.Key.Key_Escape)
    assert editor.canvas.redo_last_operation()
    assert editor.canvas.entities == [source, first, second]


@pytest.mark.parametrize("gap_type", [1, 2])
def test_split_path_supports_round_and_chamfer_modes(qtbot: QtBot, gap_type: int) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        offset_closed_path=services.kernel.offset_closed_path,
    )
    qtbot.addWidget(editor)
    editor.show()
    source = PolylineEntity(
        uuid4().hex,
        (
            (0, 0),
            (4, 0),
            (4, 1),
            (6, 1),
            (6, 0),
            (10, 0),
            (10, 4),
            (6, 4),
            (6, 3),
            (4, 3),
            (4, 4),
            (0, 4),
        ),
        True,
    )
    editor.canvas.replace_draft_entities((source,))
    editor.canvas.set_offset_gap_type(gap_type)
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "1.1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((2, 0))
    )
    command.setText("2,1.1")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 3, editor.canvas.message
    assert all(
        isinstance(item, PolylineEntity) and item.closed for item in editor.canvas.entities[1:]
    )


def test_split_preview_is_reused_when_committed(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        offset_closed_path=services.kernel.offset_closed_path,
    )
    qtbot.addWidget(editor)
    editor.resize(1200, 800)
    editor.show()
    canvas = editor.canvas
    source = PolylineEntity(
        uuid4().hex,
        (
            (0, 0),
            (4, 0),
            (4, 1),
            (6, 1),
            (6, 0),
            (10, 0),
            (10, 4),
            (6, 4),
            (6, 3),
            (4, 3),
            (4, 4),
            (0, 4),
        ),
        True,
    )
    assert canvas.replace_draft_entities((source,))
    canvas.begin_interactive_offset()
    canvas.set_interactive_offset_distance(1.1)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((2, 0)))
    side = canvas.local_to_screen((2, 1.1))
    QTest.mouseMove(canvas, side)
    preview = canvas.transform_preview_entities
    assert len(preview) == 2 and canvas.entities == [source]
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=side)
    assert tuple(canvas.entities) == (source, *preview)


def test_split_results_save_reopen_and_dxf_roundtrip(tmp_path: Path) -> None:
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.formats.providers.dxf_provider import read_sketch_dxf, write_sketch_dxf

    services = app.build_app(discoverers=())
    source = PolylineEntity(
        uuid4().hex,
        (
            (0, 0),
            (4, 0),
            (4, 1),
            (6, 1),
            (6, 0),
            (10, 0),
            (10, 4),
            (6, 4),
            (6, 3),
            (4, 3),
            (4, 4),
            (0, 4),
        ),
        True,
    )
    copies = services.kernel.offset_closed_path(source, 1.1, 1)
    assert len(copies) == 2
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, *copies))
    loaded = app.new_document(services, document_type="drawing2d")
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    target = tmp_path / "split.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    app.open_app_document(reopened, target)
    assert reopened.kernel.sketches == (sketch,)
    target_dxf = tmp_path / "split.dxf"
    write_sketch_dxf(sketch, target_dxf)
    imported = read_sketch_dxf(target_dxf).sketch
    assert len(imported.entities) == 3
    paths = [item for item in imported.entities if isinstance(item, PolylineEntity)]
    assert len(paths) == 3 and all(item.closed for item in paths)
    assert [item.points_mm for item in paths] == pytest.approx(
        [item.points_mm for item in (source, *copies)]
    )
    assert [item.bulges for item in paths] == pytest.approx(
        [item.bulges for item in (source, *copies)]
    )


@pytest.mark.parametrize("through", [False, True])
def test_split_curved_polyline_in_drawing(qtbot: QtBot, through: bool) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True,
        offset_closed_path=services.kernel.offset_closed_path,
    )
    qtbot.addWidget(editor)
    editor.show()
    source = PolylineEntity(
        uuid4().hex,
        (
            (0, 0),
            (4, 0),
            (4, 1),
            (6, 1),
            (6, 0),
            (10, 0),
            (10, 4),
            (6, 4),
            (6, 3),
            (4, 3),
            (4, 4),
            (0, 4),
        ),
        True,
        bulges=(0, 0, 0, 0, 0, 0, 0.2, 0, 0, 0, 0, 0),
    )
    assert editor.canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "T" if through else "1.1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((2, 0))
    )
    command.setText("2,1.1")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 3, editor.canvas.message
    copies = editor.canvas.entities[1:]
    assert all(isinstance(item, PolylineEntity) and item.closed for item in copies)
    assert any(isinstance(item, PolylineEntity) and item.bulges for item in copies)


def test_open_path_after_local_collapse_remains_editable(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True, offset_closed_path=services.kernel.offset_closed_path
    )
    qtbot.addWidget(editor)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (6, 4)))
    assert editor.canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((1, 0))
    )
    command.setText("0,1")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) == 2, editor.canvas.message
    result = editor.canvas.entities[-1]
    assert isinstance(result, PolylineEntity) and not result.closed
    assert result.points_mm[0] == pytest.approx((0, 2))


def test_split_curved_polyline_chamfer_mode(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True, offset_closed_path=services.kernel.offset_closed_path
    )
    qtbot.addWidget(editor)
    editor.show()
    source = PolylineEntity(
        uuid4().hex,
        (
            (0, 0),
            (4, 0),
            (4, 1),
            (6, 1),
            (6, 0),
            (10, 0),
            (10, 4),
            (6, 4),
            (6, 3),
            (4, 3),
            (4, 4),
            (0, 4),
        ),
        True,
        bulges=(0, 0, 0, 0, 0, 0, 0.2, 0, 0, 0, 0, 0),
    )
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.set_offset_gap_type(2)
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "1.1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((2, 0))
    )
    command.setText("2,1.1")
    QTest.keyClick(command, Qt.Key.Key_Return)
    copies = editor.canvas.entities[1:]
    assert len(copies) == 2, editor.canvas.message
    assert any(isinstance(item, PolylineEntity) and item.bulges for item in copies)


def test_open_curved_path_can_offset_after_local_collapse(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True, offset_closed_path=services.kernel.offset_closed_path
    )
    qtbot.addWidget(editor)
    editor.show()
    source = PolylineEntity(
        uuid4().hex,
        ((0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (6, 4), (8, 4)),
        bulges=(0, 0, 0, 0, 0, 0.2),
    )
    assert editor.canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((1, 0))
    )
    command.setText("0,1")
    QTest.keyClick(command, Qt.Key.Key_Return)
    copies = editor.canvas.entities[1:]
    assert copies, editor.canvas.message
    assert all(isinstance(item, PolylineEntity) and not item.closed for item in copies)
    assert any(isinstance(item, PolylineEntity) and item.bulges for item in copies)


def test_open_curved_offset_can_pass_through_point(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=())
    editor = SketchEditorDialog(
        select_committed_entities=True, offset_closed_path=services.kernel.offset_closed_path
    )
    qtbot.addWidget(editor)
    editor.show()
    source = PolylineEntity(
        uuid4().hex,
        ((0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (6, 4), (8, 4)),
        bulges=(0, 0, 0, 0, 0, 0.2),
    )
    assert editor.canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "T"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((1, 0))
    )
    command.setText("0,3")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(editor.canvas.entities) > 1, editor.canvas.message


def test_split_erase_saved_source_replays_atomically(
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
    source = PolylineEntity(
        uuid4().hex,
        (
            (0, 0),
            (4, 0),
            (4, 1),
            (6, 1),
            (6, 0),
            (10, 0),
            (10, 4),
            (6, 4),
            (6, 3),
            (4, 3),
            (4, 4),
            (0, 4),
        ),
        True,
    )
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
    command = editor.drawing_command_bar.input
    for value in ("OFFSET", "E", "Y", "1.1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((2, 0))
    )
    command.setText("2,1.1")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: editor.canvas.mixed_move is not None and not unit.is_busy, timeout=10000
    )
    assert len(editor.canvas.entities) == 2
    assert not any(
        item.entity_id == source.entity_id for item, _layer in editor.canvas.background_entities
    )
    QTest.keyClick(command, Qt.Key.Key_Escape)
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
    )
    results = services.kernel.sketches
    assert sum(len(item.entities) for item in results) == 2
    target = tmp_path / "split-erase.my2d"
    save_document(loaded.document, target)
    reopened = app.build_app(discoverers=())
    opened = app.open_app_document(reopened, target)
    assert reopened.kernel.sketches == results
    opened.bus.undo()
    assert sketch in reopened.kernel.sketches
    assert sum(len(item.entities) for item in reopened.kernel.sketches) == 1
    opened.bus.redo()
    assert reopened.kernel.sketches == results
