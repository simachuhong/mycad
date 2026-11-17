# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Polyline option after selecting a fillet source."""

from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad.core.sketch import PolylineEntity
from mycad.ui.sketch_editor import SketchEditorDialog


def test_fillet_pick_then_polyline_closes_open_path(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((-2, 0), (10, 0), (10, 10), (0, 10), (0, -2)))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 0)))
    command.setText("P")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity)
    assert canvas.entities[0].closed, canvas.message
    assert canvas.undo_last_operation()
    assert canvas.entities == [source]


def test_fillet_pick_then_polyline_no_trim_preserves_source(qtbot: QtBot) -> None:
    from mycad.core.sketch import ArcEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((-2, 0), (10, 0), (10, 10), (0, 10), (0, -2)))
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 0)))
    command.setText("P")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 2, canvas.message
    assert canvas.entities[0] == source
    assert isinstance(canvas.entities[1], ArcEntity)
    assert len([item for item in canvas.constraints if item.kind == "tangent"]) == 2
    assert canvas.undo_last_operation()
    assert canvas.entities == [source]


def test_saved_polyline_pick_then_p_commits_and_undoes(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    source = PolylineEntity(uuid4().hex, ((-2, 0), (10, 0), (10, 10), (0, 10), (0, -2)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 0)))
    count = loaded.document.command_count
    command.setText("P")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: loaded.document.command_count > count, timeout=10000)
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    result = services.kernel.sketches[0].entities[0]
    assert isinstance(result, PolylineEntity) and result.closed
    loaded.bus.undo()
    assert services.kernel.sketches[0].entities == (source,)


def test_saved_polyline_pick_then_p_no_trim_preserves_source(qtbot: QtBot) -> None:
    from mycad import app
    from mycad.core.sketch import ArcEntity, Sketch, WorkPlaneFrame
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    source = PolylineEntity(uuid4().hex, ((-2, 0), (10, 0), (10, 10), (0, 10), (0, -2)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source,))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.set_auto_inference_enabled(True)
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 0)))
    command.setText("P")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], ArcEntity), canvas.message
    assert services.kernel.sketches[0] == sketch
    assert len(canvas.pending_cross_tangencies) == 2
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert services.kernel.sketches[0] == sketch
    assert len(services.kernel.cross_sketch_tangencies) == 2
    loaded.bus.undo()
    assert services.kernel.sketches == (sketch,)


def test_pick_arc_segment_then_p_closes_open_polyline(qtbot: QtBot) -> None:
    import math

    from mycad.core.polyline_curves import polyline_curve_segments
    from mycad.core.sketch import ArcEntity

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(
        uuid4().hex,
        ((-2, 0), (10, 0), (10, 10), (0, 10), (0, -2)),
        bulges=(0.2, 0, 0, 0.2),
    )
    segments = polyline_curve_segments(source.points_mm, source.bulges, False, source.entity_id)
    first = segments[0]
    assert isinstance(first, ArcEntity)
    angle = math.radians(first.start_angle_deg + 0.3 * first.sweep_angle_deg)
    pick = (
        first.center_mm[0] + first.radius_mm * math.cos(angle),
        first.center_mm[1] + first.radius_mm * math.sin(angle),
    )
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(pick))
    command.setText("P")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert len(canvas.entities) == 1 and isinstance(canvas.entities[0], PolylineEntity)
    assert canvas.entities[0].closed, canvas.message
    assert canvas.undo_last_operation()
    assert canvas.entities == [source]


def test_polyline_pick_then_p_supports_multiple(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    first = PolylineEntity(uuid4().hex, ((-2, 0), (10, 0), (10, 10), (0, 10), (0, -2)))
    second = PolylineEntity(uuid4().hex, ((28, 0), (40, 0), (40, 10), (30, 10), (30, -2)))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "1", "M"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((3, 0), (33, 0)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
        command.setText("P")
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert all(isinstance(item, PolylineEntity) and item.closed for item in canvas.entities), (
        canvas.message
    )
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities[1] == second


def test_polyline_pick_then_p_no_solution_can_cancel(qtbot: QtBot) -> None:
    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.resize(1200, 900)
    editor.show()
    source = PolylineEntity(uuid4().hex, ((-2, 0), (10, 0), (10, 10), (0, 10), (0, -2)))
    canvas = editor.canvas
    assert canvas.replace_draft_entities((source,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "500"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((3, 0)))
    command.setText("P")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert canvas.entities == [source]
    assert canvas.has_active_edit_gesture
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.entities == [source]
    assert not canvas.has_active_edit_gesture
