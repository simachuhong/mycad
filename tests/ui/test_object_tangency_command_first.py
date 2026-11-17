# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Selecting objects after invoking the 2D tangency command."""

from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.sketch import CircleEntity, LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
from mycad.core.sketch_layers import SketchLayer
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow

_SCALE_ATTRIBUTE = "_scale"


def test_object_tangency_command_selects_two_draft_objects(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    canvas.entities = [line, circle]
    setattr(canvas, _SCALE_ATTRIBUTE, 20.0)
    window.act_cross_sketch_tangency.trigger()
    assert canvas.tool == "对象相切选择"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    qtbot.waitUntil(lambda: bool(canvas.constraints), timeout=10000)
    assert canvas.constraints[0].kind == "tangent"
    assert {ref.entity_id for ref in canvas.constraints[0].references} == {
        line.entity_id,
        circle.entity_id,
    }
    assert canvas.undo_last_operation()
    assert not canvas.constraints


def test_object_tangency_command_retains_one_preselection_and_cancels(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    canvas.entities = [line, circle]
    canvas.selected_entity_ids = {line.entity_id}
    window.act_cross_sketch_tangency.trigger()
    assert canvas.tool == "对象相切选择"
    assert canvas.selected_entity_ids == {line.entity_id}
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.tool == "选择元素" and not canvas.selected_entity_ids
    assert not canvas.constraints
    window.act_cross_sketch_tangency.trigger()
    bar = editor.drawing_command_bar.input
    QTest.keyClick(bar, Qt.Key.Key_Return)
    options = window.active_cross_sketch_tangency_dialog()
    assert options is not None
    options.reject()
    window.act_cross_sketch_tangency.trigger()
    assert canvas.tool == "对象相切选择"
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
    assert canvas.tool == "选择元素" and not canvas.constraints


def test_tangency_dialog_can_pick_same_record_objects_on_canvas(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
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
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    other = LineEntity(uuid4().hex, (20, 0), (30, 0))
    first = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle))
    second = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (other,))
    for sketch in (first, second):
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    setattr(canvas, _SCALE_ATTRIBUTE, 20.0)
    window.act_manage_tangencies.trigger()
    dialog = window.active_cross_sketch_tangency_dialog()
    assert dialog is not None
    dialog.canvas_selection_button.click()
    assert canvas.tool == "对象相切选择"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].constraints[0].kind == "tangent"
    loaded.bus.undo()
    assert services.kernel.sketches == (first, second)


def test_object_tangency_command_selects_polyline_edge(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    path = PolylineEntity(uuid4().hex, ((0, 0), (10, 0), (10, 10)))
    circle = CircleEntity(uuid4().hex, (12, 5), 2)
    canvas.entities = [path, circle]
    setattr(canvas, _SCALE_ATTRIBUTE, 20.0)
    window.act_cross_sketch_tangency.trigger()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 8)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((14, 5)))
    qtbot.waitUntil(lambda: bool(canvas.constraints), timeout=10000)
    ref = next(ref for ref in canvas.constraints[0].references if ref.entity_id == path.entity_id)
    assert ref.index == 1
    assert canvas.undo_last_operation()


def test_object_tangency_starts_on_canvas_with_multiple_records(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
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
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    for entity in (line, circle):
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)),
            session_identity=0,
        )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    setattr(canvas, _SCALE_ATTRIBUTE, 20.0)
    window.act_cross_sketch_tangency.trigger()
    assert canvas.tool == "对象相切选择"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    qtbot.waitUntil(
        lambda: (
            bool(services.kernel.cross_sketch_tangencies)
            and not unit.is_busy
            and not unit.is_delivering_result
        ),
        timeout=10000,
    )
    relation = services.kernel.cross_sketch_tangencies[0]
    assert {relation.first.entity_id, relation.second.entity_id} == {
        line.entity_id,
        circle.entity_id,
    }
    assert window.active_cross_sketch_tangency_dialog() is None
    loaded.bus.undo()
    assert not services.kernel.cross_sketch_tangencies


def test_object_tangency_command_auto_stages_draft_and_saved(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
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
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (circle,))
    app.commit_new_sketch(services, loaded, saved, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    canvas.entities = [line]
    setattr(canvas, _SCALE_ATTRIBUTE, 20.0)
    window.act_cross_sketch_tangency.trigger()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    qtbot.waitUntil(
        lambda: len(canvas.pending_cross_tangencies) == 1 and not unit.is_busy, timeout=10000
    )
    assert window.active_cross_sketch_tangency_dialog() is None
    assert canvas.undo_last_operation()
    assert not canvas.pending_cross_tangencies


def test_object_tangency_failed_auto_preview_allows_manual_retry(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
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
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    for entity in (line, circle):
        app.commit_new_sketch(
            services,
            loaded,
            Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)),
            session_identity=0,
        )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    setattr(canvas, _SCALE_ATTRIBUTE, 20.0)
    original_prepare = app.prepare_cross_sketch_tangency

    def reject_preview(*_args: object, **_kwargs: object) -> object:
        raise ValueError("模拟预览失败")

    monkeypatch.setattr(app, "prepare_cross_sketch_tangency", reject_preview)
    window.act_cross_sketch_tangency.trigger()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1, 0)))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    dialog = window.active_cross_sketch_tangency_dialog()
    assert dialog is not None and "模拟预览失败" in dialog.status_label.text()
    assert not services.kernel.cross_sketch_tangencies
    monkeypatch.setattr(app, "prepare_cross_sketch_tangency", original_prepare)
    dialog.preview_button.click()
    qtbot.waitUntil(dialog.commit_button.isEnabled, timeout=10000)
    assert not services.kernel.cross_sketch_tangencies
    dialog.reject()


def test_object_tangency_selection_cancels_when_document_changes(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    for entity in (line, circle):
        app.commit_new_sketch(
            services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (entity,)), session_identity=0
        )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    setattr(canvas, _SCALE_ATTRIBUTE, 20.0)
    window.act_cross_sketch_tangency.trigger()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1, 0)))
    loaded.bus.execute("drawing.fillet_radius.set", {"radius": 2}, "local", version=1)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    assert canvas.tool == "选择元素"
    assert "文档已变化" in canvas.message
    assert not services.kernel.cross_sketch_tangencies


def test_preselected_tangency_rejects_stale_saved_objects(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    services = window.document_session.active.services
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line, circle)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    canvas.selected_entity_ids = {line.entity_id, circle.entity_id}
    loaded.bus.execute("drawing.fillet_radius.set", {"radius": 2}, "local", version=1)
    window.act_cross_sketch_tangency.trigger()
    assert "文档已变化" in canvas.message
    assert not canvas.selected_entity_ids
    assert not services.kernel.cross_sketch_tangencies
    assert not services.kernel.sketches[0].constraints


def test_object_tangency_rejects_first_object_on_locked_layer(qtbot: QtBot) -> None:
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    layers = canvas.layer_table.add(SketchLayer("A"))
    canvas.set_layer_table(layers, "0")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0), layer_name="A")
    circle = CircleEntity(uuid4().hex, (5, 2), 2)
    canvas.entities = [line, circle]
    setattr(canvas, _SCALE_ATTRIBUTE, 20.0)
    window.act_cross_sketch_tangency.trigger()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((1, 0)))
    canvas.set_layer_table(layers.replace(SketchLayer("A", locked=True)), "0")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 4)))
    assert not canvas.constraints
    assert not canvas.selected_entity_ids
    assert "锁定" in canvas.message
