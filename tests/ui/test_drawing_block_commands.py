# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Real command-bar and toolbar paths for creating and inserting blocks."""

from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.sketch import LineEntity
from mycad.ui.drawing_block_dialogs import BlockCreateDialog, BlockInsertDialog
from mycad.ui.main_window import MainWindow

_SESSION_FIELD = "_session_id"
_ENSURE_METHOD = "_ensure_collection_session"
_SYNC_METHOD = "_sync_drawing_layers"


def _skip_gl_paint(*_args: object, **_kwargs: object) -> None:
    pass


@pytest.mark.parametrize("method", ["click", "drag"])
def test_keep_block_after_trimming_uncommitted_rectangle(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, method: str
) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, RectangleEntity

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (20, 10))
    cutter = LineEntity(uuid4().hex, (5, -5), (5, 15))
    assert canvas.replace_draft_entities((rectangle, cutter))
    assert canvas.set_tool("修剪")
    if method == "click":
        canvas.add_coordinate_point((10, 0), exact_point=True)
    else:
        canvas.set_snapping_enabled(False)
        start, end = canvas.local_to_screen((10, -2)), canvas.local_to_screen((10, 2))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    assert isinstance(canvas.entities[0], PolylineEntity), canvas.message
    assert canvas.entities[0].entity_id != rectangle.entity_id
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {item.entity_id for item in canvas.entities}

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("修剪矩形块")
        dialog.source_mode.setCurrentIndex(1)
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        buttons.button(QDialogButtonBox.StandardButton.Ok).click()

    QTimer.singleShot(0, create)
    editor.block_create_button.click()
    assert canvas.collection_session is not None, editor.drawing_command_bar.status.text()
    session = canvas.collection_session
    assert session.snapshot.block_definitions[0].name == "修剪矩形块"
    assert canvas.undo_last_operation() and not session.snapshot.block_definitions
    assert canvas.undo_last_operation() and canvas.entities[0] == rectangle
    assert canvas.redo_last_operation() and isinstance(canvas.entities[0], PolylineEntity)
    assert canvas.redo_last_operation() and session.snapshot.block_definitions
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=15000
    )
    path = tmp_path / f"trimmed-rectangle-{method}.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_block_definitions[0].name == "修剪矩形块"
    reopened.bus.undo_operation()
    assert not services.kernel.drawing_block_definitions
    reopened.bus.redo_operation()
    assert services.kernel.drawing_block_definitions[0].name == "修剪矩形块"


def test_keep_block_after_uncommitted_rectangle_arc_fillet(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    from mycad.core.sketch import ArcEntity, RectangleEntity

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    rectangle = RectangleEntity(uuid4().hex, (-20, 0), (20, -10))
    arc = ArcEntity(uuid4().hex, (0, 5), 2, 180, 180)
    assert canvas.replace_draft_entities((rectangle, arc))
    canvas.set_auto_inference_enabled(True)
    canvas.circle_fillet_radius = 2
    canvas.circle_fillet_trim = True
    assert canvas.set_tool("二维圆角")
    for point in ((-3, 0), (-1.3, 3.5)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 3, canvas.message
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {item.entity_id for item in canvas.entities}

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("矩形圆角块")
        dialog.source_mode.setCurrentIndex(1)
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        buttons.button(QDialogButtonBox.StandardButton.Ok).click()

    QTimer.singleShot(0, create)
    editor.block_create_button.click()
    assert canvas.collection_session is not None, editor.drawing_command_bar.status.text()
    assert canvas.collection_session.snapshot.block_definitions[0].name == "矩形圆角块"


def test_keep_block_after_uncommitted_line_fillet(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.constraints) == 4
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {item.entity_id for item in canvas.entities}

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("草稿圆角块")
        dialog.source_mode.setCurrentIndex(1)
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        buttons.button(QDialogButtonBox.StandardButton.Ok).click()

    QTimer.singleShot(0, create)
    editor.block_create_button.click()
    assert canvas.collection_session is not None, editor.drawing_command_bar.status.text()
    assert canvas.collection_session.snapshot.block_definitions[0].name == "草稿圆角块"


def test_keep_block_after_confirmed_draft_constraint(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    from mycad.core.persistence import save_document
    from mycad.core.sketch import CircleEntity, Sketch
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    first = CircleEntity(uuid4().hex, (0, 0), 10)
    second = CircleEntity(uuid4().hex, (0, 0), 5)
    assert canvas.replace_draft_entities((first, second))
    original = Sketch(
        editor.draft_sketch_id, editor.current_frame(), (first, second), layers=editor.layer_table
    )
    relation = SketchConstraint(
        uuid4().hex,
        "concentric",
        (
            SketchGeometryReference(first.entity_id, "geometry"),
            SketchGeometryReference(second.entity_id, "geometry"),
        ),
    )
    solved = services.kernel.preview_sketch_constraint(original, relation)
    assert solved.status == "success" and solved.sketch is not None
    assert canvas.apply_constraint_solution(
        original, solved.sketch, confirmed_constraint=relation, solve_result=solved
    )
    assert canvas.undo_last_operation() and canvas.redo_last_operation()
    radius = SketchConstraint(
        uuid4().hex, "radius", (SketchGeometryReference(second.entity_id, "geometry"),), 6, "mm"
    )
    dimension = services.kernel.preview_sketch_constraint(solved.sketch, radius)
    assert dimension.status == "success" and dimension.sketch is not None
    assert canvas.apply_constraint_solution(
        solved.sketch, dimension.sketch, confirmed_constraint=radius, solve_result=dimension
    )
    canvas.selected_constraint_ids = {radius.constraint_id}
    assert canvas.delete_selected()
    assert canvas.undo_last_operation() and canvas.redo_last_operation()
    canvas.selected_entity_ids = {first.entity_id, second.entity_id}

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("保留约束块")
        dialog.source_mode.setCurrentIndex(1)
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        buttons.button(QDialogButtonBox.StandardButton.Ok).click()

    QTimer.singleShot(0, create)
    editor.block_create_button.click()
    assert canvas.collection_session is not None, editor.drawing_command_bar.status.text()
    session = canvas.collection_session
    assert session.snapshot.block_definitions[0].name == "保留约束块"
    assert tuple(canvas.constraints) == solved.sketch.constraints
    assert canvas.undo_last_operation() and not session.snapshot.block_definitions
    assert canvas.redo_last_operation() and session.snapshot.block_definitions
    names: list[str] = []

    def inspect_insert() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockInsertDialog)
        names.extend(
            dialog.definition_field.itemText(i) for i in range(dialog.definition_field.count())
        )
        dialog.reject()

    QTimer.singleShot(0, inspect_insert)
    editor.block_insert_button.click()
    assert "保留约束块" in names
    loaded, unit = window.loaded_document(), window.execution_unit
    assert loaded is not None and unit is not None
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=15000
    )
    path = tmp_path / "keep-constrained-block.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_block_definitions[0].name == "保留约束块"
    assert services.kernel.sketches[0].constraints == solved.sketch.constraints
    reopened.bus.undo_operation()
    assert not services.kernel.drawing_block_definitions
    reopened.bus.redo_operation()
    assert services.kernel.drawing_block_definitions[0].name == "保留约束块"


@pytest.mark.parametrize("entry", ["command", "button"])
@pytest.mark.parametrize("confirm", ["enter", "input_enter", "right_click"])
def test_block_selects_objects_after_starting_command(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, entry: str, confirm: str
) -> None:
    from PySide6.QtWidgets import QDialog, QMessageBox

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)

    def discard(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Discard

    monkeypatch.setattr(QMessageBox, "question", discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    try:
        if entry == "command":
            editor.drawing_command_bar.input.setText("BLOCK")
            QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
        else:
            editor.block_create_button.click()
        assert "Enter" in editor.status_label.text()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
        assert line.entity_id in canvas.selected_entity_ids

        def create(dialog: BlockCreateDialog) -> int:
            dialog.name_field.setText("测试块")
            return int(QDialog.DialogCode.Accepted)

        monkeypatch.setattr(BlockCreateDialog, "exec", create)
        if confirm == "enter":
            QTest.keyClick(canvas, Qt.Key.Key_Return)
        elif confirm == "input_enter":
            QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
        else:
            from PySide6.QtCore import QCoreApplication, QPoint
            from PySide6.QtGui import QContextMenuEvent

            checks: list[bool] = []

            def check_context() -> bool:
                checks.append(True)
                return False

            monkeypatch.setattr(canvas, "supports_clipboard_context_menu", check_context)
            QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
            point = QPoint(30, 30)
            QCoreApplication.sendEvent(
                canvas,
                QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, canvas.mapToGlobal(point)),
            )
            assert not checks
            QCoreApplication.sendEvent(
                canvas,
                QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, canvas.mapToGlobal(point)),
            )
            assert checks == [True]
        session = canvas.collection_session
        assert session is not None
        assert len(session.snapshot.block_definitions) == 1
        assert len(session.snapshot.block_instances) == 1
        assert "块" in editor.drawing_command_bar.status.text()
    finally:
        editor.reject()


def test_block_selection_escape_cancels_without_creating_definition(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    editor.block_create_button.click()
    editor.drawing_command_bar.start_measurement("DIST")
    assert "请先完成或取消" in editor.drawing_command_bar.status.text()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas.collection_session is None
    assert line in canvas.entities


def test_block_created_after_selection_is_available_to_insert_immediately(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    command.setText("BLOCK")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("同图块")
        from PySide6.QtWidgets import QDialogButtonBox

        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        buttons.button(QDialogButtonBox.StandardButton.Ok).click()

    QTimer.singleShot(0, create)
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    names: list[str] = []

    def inspect_insert() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockInsertDialog)
        names.extend(
            dialog.definition_field.itemText(i) for i in range(dialog.definition_field.count())
        )
        dialog.reject()

    QTimer.singleShot(0, inspect_insert)
    editor.block_insert_button.click()
    assert "同图块" in names


def test_block_creation_keeps_dialog_and_name_when_conversion_is_rejected(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (2, 0), (2, 3))
    relation = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (relation,))
    app.commit_new_sketch(
        services, loaded, saved, session_identity=cast("int", getattr(window, _SESSION_FIELD))
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {first.entity_id, second.entity_id}
    feedback: list[str] = []

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("连接图形")
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.click()
        if not dialog.isVisible():
            feedback.append("窗口已关闭")
            return
        feedback.append(dialog.message.text())
        assert dialog.name_field.text() == "连接图形"
        dialog.source_mode.setCurrentIndex(1)
        ok.click()

    QTimer.singleShot(0, create)
    editor.block_create_button.click()
    assert feedback and "约束" in feedback[0]
    session = editor.canvas.collection_session
    assert session is not None
    assert [definition.name for definition in session.snapshot.block_definitions] == ["连接图形"]
    assert saved in session.snapshot.sketches
    assert not session.snapshot.block_instances
    names: list[str] = []

    def inspect_insert() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockInsertDialog)
        names.extend(
            dialog.definition_field.itemText(i) for i in range(dialog.definition_field.count())
        )
        dialog.reject()

    QTimer.singleShot(0, inspect_insert)
    editor.block_insert_button.click()
    assert names == ["连接图形"]


def test_block_creation_explains_selected_dimension_without_losing_name(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    from mycad.core.sketch import Sketch
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 4),
    )
    saved = Sketch(uuid4().hex, editor.current_frame(), (line,), (dimension,))
    app.commit_new_sketch(
        services, loaded, saved, session_identity=cast("int", getattr(window, _SESSION_FIELD))
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.selected_constraint_ids = {dimension.constraint_id}
    feedback: list[str] = []

    def attempt() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("含尺寸")
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        buttons.button(QDialogButtonBox.StandardButton.Ok).click()
        if not dialog.isVisible():
            feedback.append("窗口已关闭")
            return
        feedback.append(dialog.message.text())
        assert dialog.name_field.text() == "含尺寸"
        dialog.reject()

    QTimer.singleShot(0, attempt)
    editor.block_create_button.click()
    assert feedback and "尺寸" in feedback[0] and "几何" in feedback[0]
    assert editor.canvas.collection_session is None
    assert services.kernel.drawing_block_definitions == ()


def test_idle_right_click_repeats_block_after_button_creation(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialog

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}

    def create(dialog: BlockCreateDialog) -> int:
        dialog.name_field.setText("重复测试")
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(BlockCreateDialog, "exec", create)
    editor.block_create_button.click()
    assert canvas.collection_session is not None
    assert canvas.set_tool("选择元素")
    canvas.selected_block_instance_ids.clear()
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
    assert "请先选择要创建块" in editor.drawing_command_bar.status.text()
    assert len(canvas.collection_session.snapshot.block_definitions) == 1


def test_idle_right_click_repeats_most_recent_insert(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialog

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}

    def create(dialog: BlockCreateDialog) -> int:
        dialog.name_field.setText("重复插入测试")
        return int(QDialog.DialogCode.Accepted)

    calls: list[bool] = []

    def cancel_insert(_dialog: BlockInsertDialog) -> int:
        calls.append(True)
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(BlockCreateDialog, "exec", create)
    monkeypatch.setattr(BlockInsertDialog, "exec", cancel_insert)
    editor.block_create_button.click()
    assert canvas.set_tool("选择元素")
    canvas.selected_block_instance_ids.clear()
    editor.block_insert_button.click()
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
    assert calls == [True, True]


def test_drawing_from_block_snap_does_not_create_external_association(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from collections.abc import Callable
    from dataclasses import replace

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    member = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Snap", (member,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    assert editor.canvas.set_tool("直线")
    editor.canvas.set_snapping_enabled(True)
    for point in ((10.05, 10), (16, 15)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert len(editor.canvas.entities) == 1
    drawn = editor.canvas.entities[0]
    assert isinstance(drawn, LineEntity)
    assert drawn.start_mm == pytest.approx((10, 10))
    assert editor.canvas.constraints == []
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=15000
    )
    assert len(services.kernel.sketches) == 1
    sketch = services.kernel.sketches[0]
    assert sketch.entities == (drawn,) and sketch.constraints == ()
    path = tmp_path / "block-snap.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.execute(
        "drawing.block_instance.update",
        replace(instance, insertion_mm=(20, 20)).to_mapping(),
        "local",
    )
    assert services.kernel.sketches == (sketch,)


def test_datum_on_block_snap_keeps_coordinate_without_attachment(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from collections.abc import Callable
    from dataclasses import replace

    from PySide6.QtWidgets import QInputDialog

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    member = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Snap", (member,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_snapping_enabled(True)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None

    def label(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", label)
    tools.begin_mechanical_datum()
    for point in ((10.05, 10), (16, 15)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    assert len(services.kernel.drawing_datum_identifiers) == 1
    datum = services.kernel.drawing_datum_identifiers[0]
    assert datum.target_mm == pytest.approx((10, 10))
    assert datum.attachment is None
    path = tmp_path / "datum-block-snap.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.execute(
        "drawing.block_instance.update",
        replace(instance, insertion_mm=(20, 20)).to_mapping(),
        "local",
    )
    assert services.kernel.drawing_datum_identifiers == (datum,)


def test_tolerance_frame_on_block_snap_has_no_persistent_attachment(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from collections.abc import Callable
    from dataclasses import replace

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.persistence import save_document
    from mycad.ui.geometric_tolerance_dialog import GeometricToleranceDialog

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    member = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Snap", (member,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    editor.canvas.set_snapping_enabled(True)
    tools = editor.canvas.geometric_tolerance_tools
    assert tools is not None
    tools.begin_mechanical_frame()
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10.05, 10))
    )

    def accept() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GeometricToleranceDialog)
        dialog.accept()

    QTimer.singleShot(20, accept)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((16, 15))
    )
    assert len(services.kernel.drawing_tolerance_frames) == 1
    frame = services.kernel.drawing_tolerance_frames[0]
    assert frame.leader_target_mm == pytest.approx((10, 10))
    assert frame.leader_attachment is None and frame.leader_annotation_attachment is None
    path = tmp_path / "frame-block-snap.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.execute(
        "drawing.block_instance.update",
        replace(instance, insertion_mm=(20, 20)).to_mapping(),
        "local",
    )
    assert services.kernel.drawing_tolerance_frames == (frame,)


def test_block_manager_deletes_only_unreferenced_definitions_in_draft_timeline(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dataclasses import replace

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.persistence import save_document
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.core.sketch import Sketch
    from mycad.ui.drawing_block_dialogs import BlockManagerDialog
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=int(getattr(window, _SESSION_FIELD)),
        session_identity_provider=lambda: int(getattr(window, _SESSION_FIELD)),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    used = BlockDefinition(uuid4().hex, "Used", (line,), ())
    free = BlockDefinition(uuid4().hex, "Unused", (line,), ())
    instance = BlockInstance(uuid4().hex, used.definition_id, (0, 0))
    for operation in (
        ReplayAppend("drawing.block.create", 1, used.to_mapping(), "local"),
        ReplayAppend("drawing.block.create", 1, free.to_mapping(), "local"),
        ReplayAppend("drawing.block_instance.insert", 1, instance.to_mapping(), "local"),
    ):
        assert editor.canvas.stage_collection_operation(operation)

    def manage() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockManagerDialog)
        try:
            dialog.definition_field.setCurrentIndex(
                dialog.definition_field.findData(used.definition_id)
            )
            dialog.name_field.setText("Unused")
            dialog.rename_button.click()
            assert dialog.message.text() and session.snapshot.block_definitions == (used, free)
            dialog.name_field.setText("Renamed")
            dialog.rename_button.click()
            assert session.snapshot.block_definitions == (replace(used, name="Renamed"), free)
            dialog.name_field.setText("Used")
            dialog.rename_button.click()
            assert session.snapshot.block_definitions == (used, free)
            dialog.remove_button.click()
            assert "引用" in dialog.message.text()
            assert session.snapshot.block_definitions == (used, free)
            dialog.definition_field.setCurrentIndex(
                dialog.definition_field.findData(free.definition_id)
            )
            dialog.remove_button.click()
            assert session.snapshot.block_definitions == (used,)
        finally:
            dialog.close()

    QTimer.singleShot(0, manage)
    window.act_drawing_block_manage.trigger()
    assert loaded.document.commands == ()
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.block_definitions == (used, free)
    assert editor.canvas.redo_last_operation()
    session.commit()
    path = tmp_path / "managed.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_block_definitions == (used,)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (used, free)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (replace(used, name="Renamed"), free)
    reopened.bus.redo_operation()
    assert services.kernel.drawing_block_definitions == (used, free)


@pytest.mark.parametrize("action", ["rename_free", "rename_used", "remove_free"])
@pytest.mark.parametrize("active_session", [False, True])
def test_block_manager_rejects_restricted_layer_before_starting_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str, active_session: bool
) -> None:
    from collections.abc import Callable
    from dataclasses import replace

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.drawing_block_dialogs import BlockManagerDialog

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("Member"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="Member")
    definition = BlockDefinition(uuid4().hex, "Existing", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    if action == "rename_used":
        instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    layers = layers.replace(replace(layers.get("Member"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.set_layer_table(layers, "0")
    if active_session:
        cast("Callable[[object], object]", getattr(window, _ENSURE_METHOD))(editor)
    session = editor.canvas.collection_session
    checkpoint = session.checkpoint() if session is not None else None
    history = tuple(loaded.document.commands)
    messages: list[str] = []

    def manage(dialog: BlockManagerDialog) -> int:
        if action.startswith("rename"):
            dialog.name_field.setText("Changed")
            dialog.rename_button.click()
        else:
            dialog.remove_button.click()
        messages.append(dialog.message.text())
        return 0

    monkeypatch.setattr(BlockManagerDialog, "exec", manage)
    window.act_drawing_block_manage.trigger()
    assert messages and "图层" in messages[0]
    assert editor.canvas.collection_session is session
    if session is not None:
        assert session.checkpoint() == checkpoint
    assert services.kernel.drawing_block_definitions == (definition,)
    assert tuple(loaded.document.commands) == history


@pytest.mark.parametrize("action", ["rename", "remove", "instance"])
def test_block_manager_refreshes_stale_definition_before_action(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from dataclasses import replace

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.core.sketch import Sketch
    from mycad.ui.drawing_block_dialogs import BlockManagerDialog
    from mycad.ui.drawing_collection_session import DrawingCollectionSession

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    draft = Sketch(editor.draft_sketch_id, editor.current_frame(), (), layers=editor.layer_table)
    session = DrawingCollectionSession(
        services,
        loaded,
        ReplayAppend("sketch.create", 58, draft.to_state_mapping(), "local"),
        session_identity=int(getattr(window, _SESSION_FIELD)),
        session_identity_provider=lambda: int(getattr(window, _SESSION_FIELD)),
    )
    editor.canvas.attach_collection_session(session, draft.sketch_id)
    original = BlockDefinition(
        uuid4().hex, "Original", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block.create", 1, original.to_mapping(), "local")
    )
    concurrent = replace(original, name="Concurrent")

    def manage() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockManagerDialog)
        try:
            operation = (
                ReplayAppend(
                    "drawing.block_instance.insert",
                    1,
                    BlockInstance(uuid4().hex, original.definition_id, (5, 5)).to_mapping(),
                    "local",
                )
                if action == "instance"
                else ReplayAppend("drawing.block.update", 1, concurrent.to_mapping(), "local")
            )
            assert editor.canvas.stage_collection_operation(operation)
            if action == "rename":
                dialog.name_field.setText("StaleChoice")
                dialog.rename_button.click()
            else:
                dialog.remove_button.click()
            expected = original if action == "instance" else concurrent
            assert session.snapshot.block_definitions == (expected,)
            assert "变化" in dialog.message.text()
            assert dialog.name_field.text() == expected.name
            assert expected.name in dialog.definition_field.currentText()
            if action == "instance":
                assert "1 个实例" in dialog.definition_field.currentText()
        finally:
            dialog.close()

    QTimer.singleShot(0, manage)
    window.act_drawing_block_manage.trigger()
    assert loaded.document.commands == ()
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.block_definitions == (original,)


def test_block_command_and_insert_button_create_visible_instances(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (1, 1), (3, 1))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("Symbol")
        dialog.base_x.setValue(1)
        dialog.base_y.setValue(1)
        dialog.accept()

    QTimer.singleShot(0, create)
    editor.drawing_command_bar.input.setText("BLOCK")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None
    assert len(session.snapshot.block_definitions) == len(session.snapshot.block_instances) == 1
    assert session.snapshot.sketches[-1].entities == ()
    first = session.snapshot.block_instances[0]
    assert first.insertion_mm == (1, 1)
    assert editor.canvas.selected_block_instance_ids == {first.instance_id}
    assert len(editor.canvas.drawing_block_view().geometry) == 1

    def insert() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockInsertDialog)
        dialog.x_field.setValue(10)
        dialog.y_field.setValue(20)
        dialog.rotation_field.setValue(90)
        dialog.scale_field.setValue(2)
        dialog.accept()

    QTimer.singleShot(0, insert)
    editor.block_insert_button.click()
    assert len(session.snapshot.block_instances) == 2
    second = session.snapshot.block_instances[-1]
    assert second.definition_id == first.definition_id and second.insertion_mm == (10, 20)
    assert second.rotation_deg == 90 and second.scale == 2
    assert len(editor.canvas.drawing_block_view().geometry) == 2
    assert editor.canvas.undo_last_operation() and session.snapshot.block_instances == (first,)
    assert editor.canvas.undo_last_operation()
    assert session.snapshot.block_definitions == () and session.snapshot.sketches[-1].entities == (
        line,
    )
    assert loaded.document.commands == ()


@pytest.mark.parametrize("selected_kind", ["source", "member"])
def test_block_keep_array_geometry_from_command_bar(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, selected_kind: str
) -> None:
    from collections.abc import Callable

    from mycad.core.associative_array import ArrayEntityRef, ArrayMember, AssociativeRectArray
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    source = LineEntity(uuid4().hex, (0, 0), (10, 0))
    member = LineEntity(uuid4().hex, (4, 0), (14, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (source, member))
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=cast("int", getattr(window, _SESSION_FIELD))
    )
    origin = ArrayEntityRef(sketch.sketch_id, source.entity_id)
    target = ArrayEntityRef(sketch.sketch_id, member.entity_id)
    array = AssociativeRectArray(
        uuid4().hex, sketch.frame, 1, 2, 0, 4, (origin,), (ArrayMember(origin, target, 0, 1),)
    )
    loaded.bus.execute("drawing.array.add", {"array": array.to_mapping()}, "local")
    before = app.drawing_collection_snapshot(services)
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    selected = source if selected_kind == "source" else member
    editor.canvas.selected_entity_ids = {selected.entity_id}

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, BlockCreateDialog):
            dialog.name_field.setText("Snapshot")
            dialog.source_mode.setCurrentIndex(1)
            dialog.accept()

    QTimer.singleShot(0, create)
    editor.drawing_command_bar.input.setText("BLOCK")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and len(session.snapshot.block_definitions) == 1
    assert session.snapshot.associative_arrays == before.associative_arrays
    copied = session.snapshot.block_definitions[0].entities[0]
    assert isinstance(copied, LineEntity) and copied.entity_id != selected.entity_id
    assert (copied.start_mm, copied.end_mm) == (selected.start_mm, selected.end_mm)
    assert app.drawing_collection_snapshot(services) == before
    assert editor.canvas.undo_last_operation()
    assert (
        not session.snapshot.block_definitions
        and session.snapshot.associative_arrays == before.associative_arrays
    )


def test_block_command_converts_group_from_coplanar_sketches(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from collections.abc import Callable

    from mycad.core.drawing_blocks import expand_block
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (1, 2), (3, 2))
    rotated = WorkPlaneFrame((10, 20, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    sketches = (
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first,)),
        Sketch(uuid4().hex, rotated, (second,)),
    )
    for sketch in sketches:
        app.commit_new_sketch(
            services, loaded, sketch, session_identity=cast("int", getattr(window, _SESSION_FIELD))
        )
    group = DrawingGroup(
        uuid4().hex,
        tuple(
            DrawingObjectRef("geometry", sketch.entities[0].entity_id, sketch.sketch_id)
            for sketch in sketches
        ),
        name="Coplanar",
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    cast("Callable[[], None]", getattr(window, _SYNC_METHOD))()
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 0))
    )
    assert editor.canvas.selected_geometry_refs == {group.members[0]}
    assert editor.canvas.effective_group_selection() == frozenset(group.members)

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, BlockCreateDialog):
            dialog.name_field.setText("Projected")
            dialog.base_x.setValue(5)
            dialog.base_y.setValue(7)
            dialog.accept()

    QTimer.singleShot(0, create)
    editor.drawing_command_bar.input.setText("BLOCK")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    session = editor.canvas.collection_session
    assert session is not None and app.drawing_collection_snapshot(services) == before
    definition, instance = (
        session.snapshot.block_definitions[0],
        session.snapshot.block_instances[0],
    )
    expanded = expand_block(definition, instance, session.snapshot.text_styles)
    assert [
        (item.start_mm, item.end_mm) for item in expanded.entities if isinstance(item, LineEntity)
    ] == [((0, 0), (20, 0)), ((8, 21), (8, 23))]
    assert session.snapshot.groups[0].members == (
        DrawingObjectRef("block_instance", instance.instance_id),
    )
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=15000
    )
    saved = tmp_path / "ui-coplanar-block.my2d"
    save_document(loaded.document, saved)
    reopened = app.open_app_document(services, saved)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert services.kernel.drawing_block_instances == (instance,)


@pytest.mark.parametrize("mode", ["active", "locked", "changed"])
def test_block_conversion_uses_current_layer_and_rejects_invalid_layer(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    from dataclasses import replace

    from mycad.core.persistence import save_document
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("Other"))
    if mode == "locked":
        layers = layers.replace(replace(layers.get("Other"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.set_layer_table(layers, "0")
    line = LineEntity(uuid4().hex, (0, 0), (3, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.set_layer_table(layers, "0" if mode == "changed" else "Other")
    history = tuple(loaded.document.commands)

    def create(dialog: BlockCreateDialog) -> int:
        dialog.name_field.setText("B")
        if mode == "changed":
            editor.canvas.set_layer_table(layers, "Other")
        return 1

    monkeypatch.setattr(BlockCreateDialog, "exec", create)
    editor.block_create_button.click()
    session = editor.canvas.collection_session
    if mode == "active":
        assert session is not None, editor.status_label.text()
        assert session.snapshot.block_instances[0].layer_name == "Other"
        assert editor.canvas.drawing_block_view().geometry[0].layer.name == "Other"
        assert editor.canvas.undo_last_operation()
        assert session.snapshot.block_instances == ()
        assert editor.canvas.redo_last_operation()
        instance = session.snapshot.block_instances[0]
        assert tuple(loaded.document.commands) == history
        editor.finish_sketch()
        unit = window.execution_unit
        assert unit is not None
        qtbot.waitUntil(
            lambda: not unit.is_busy and window.active_sketch_dialog() is not editor,
            timeout=15000,
        )
        path = tmp_path / "current-layer.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert services.kernel.drawing_block_instances == (instance,)
        reopened.bus.undo_operation()
        assert services.kernel.drawing_block_instances == ()
        return
    assert session is None
    assert ("图层" if mode == "locked" else "变化") in editor.status_label.text()
    assert tuple(editor.canvas.entities) == (line,)
    assert tuple(loaded.document.commands) == history


def test_create_button_keeps_source_and_insert_command_uses_definition(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("Retained")
        dialog.source_mode.setCurrentIndex(1)
        dialog.accept()

    QTimer.singleShot(0, create)
    editor.block_create_button.click()
    session = editor.canvas.collection_session
    assert session is not None and session.snapshot.sketches[-1].entities == (line,)
    assert len(session.snapshot.block_definitions) == 1 and session.snapshot.block_instances == ()

    def insert() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockInsertDialog)
        dialog.x_field.setValue(4)
        dialog.y_field.setValue(5)
        dialog.accept()

    QTimer.singleShot(0, insert)
    editor.drawing_command_bar.input.setText("INSERT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert len(session.snapshot.block_instances) == 1
    assert session.snapshot.block_instances[0].insertion_mm == (4, 5)
    assert session.snapshot.sketches[-1].entities == (line,)
    assert loaded.document.commands == ()


@pytest.mark.parametrize("action", ["create", "insert", "selection"])
def test_block_dialog_rejects_changed_source_before_staging(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from dataclasses import replace

    from mycad.core.drawing_blocks import BlockDefinition

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    revised = replace(line, end_mm=(4, 0))
    definition = BlockDefinition(uuid4().hex, "Original", (line,), ())
    if action != "insert":
        assert editor.canvas.replace_draft_entities((line,))
        editor.canvas.selected_entity_ids = {line.entity_id}
    else:
        loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
        editor.canvas.set_source_context_revision(loaded.document.revision)
    history = tuple(loaded.document.commands)

    def interact() -> None:
        dialog = QApplication.activeModalWidget()
        if action != "insert":
            assert isinstance(dialog, BlockCreateDialog)
            if action == "selection":
                editor.canvas.selected_entity_ids.clear()
            else:
                assert editor.canvas.replace_draft_entities((revised,))
            dialog.name_field.setText("New")
        else:
            assert isinstance(dialog, BlockInsertDialog)
            loaded.bus.execute(
                "drawing.block.update",
                replace(definition, entities=(revised,)).to_mapping(),
                "local",
            )
        dialog.accept()

    QTimer.singleShot(0, interact)
    if action != "insert":
        editor.block_create_button.click()
        assert tuple(editor.canvas.entities) == (line if action == "selection" else revised,)
        assert tuple(loaded.document.commands) == history
        assert services.kernel.drawing_block_definitions == ()
    else:
        editor.block_insert_button.click()
        assert len(loaded.document.commands) == len(history) + 1
        assert services.kernel.drawing_block_definitions[0].entities == (revised,)
    assert editor.canvas.collection_session is None
    assert services.kernel.drawing_block_instances == ()
    assert "变化" in editor.status_label.text()


@pytest.mark.parametrize("action", ["create", "insert"])
def test_block_dialog_rejects_text_started_while_open(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Existing", (line,), ())
    if action == "create":
        assert editor.canvas.replace_draft_entities((line,))
        editor.canvas.selected_entity_ids = {line.entity_id}
    else:
        loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
        editor.canvas.set_source_context_revision(loaded.document.revision)
    history = tuple(loaded.document.commands)
    text_tools = editor.canvas.text_tools
    assert text_tools is not None

    def interact() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog | BlockInsertDialog)
        if isinstance(dialog, BlockCreateDialog):
            dialog.name_field.setText("New")
        assert text_tools.begin("text")
        text_tools.place((5, 5))
        text_tools.editor.setPlainText("Unfinished")
        dialog.accept()

    QTimer.singleShot(0, interact)
    try:
        (editor.block_create_button if action == "create" else editor.block_insert_button).click()
        assert text_tools.pending and text_tools.editor.toPlainText() == "Unfinished"
        assert editor.canvas.collection_session is None
        assert tuple(loaded.document.commands) == history
        assert services.kernel.drawing_block_instances == ()
        assert services.kernel.drawing_block_definitions == (
            () if action == "create" else (definition,)
        )
        assert "完成或取消" in editor.status_label.text()
    finally:
        text_tools.cancel()


@pytest.mark.parametrize("action", ["create", "insert"])
def test_block_canvas_point_capture_rejects_changed_source(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from dataclasses import replace

    from mycad.core.drawing_blocks import BlockDefinition

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    revised = replace(line, end_mm=(4, 0))
    definition = BlockDefinition(uuid4().hex, "Original", (line,), ())
    if action == "create":
        assert editor.canvas.replace_draft_entities((line,))
        editor.canvas.selected_entity_ids = {line.entity_id}
    else:
        loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
        editor.canvas.set_source_context_revision(loaded.document.revision)

    def pick() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog | BlockInsertDialog)
        dialog.pick_point_button.click()

    QTimer.singleShot(0, pick)
    if action == "create":
        editor.block_create_button.click()
        assert editor.canvas.replace_draft_entities((revised,))
    else:
        editor.block_insert_button.click()
        loaded.bus.execute(
            "drawing.block.update", replace(definition, entities=(revised,)).to_mapping(), "local"
        )
    assert editor.canvas.block_point_capture_active
    history = tuple(loaded.document.commands)

    def cancel_unexpected_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, BlockCreateDialog | BlockInsertDialog):
            dialog.reject()

    QTimer.singleShot(0, cancel_unexpected_dialog)
    editor.canvas.add_coordinate_point((9, 9), exact_point=True)
    assert not editor.canvas.block_point_capture_active
    assert "变化" in editor.status_label.text()
    editor.canvas.cursor_changed.emit(1.0, 1.0, "")
    assert "变化" in editor.status_label.text()
    assert editor.canvas.collection_session is None
    assert tuple(loaded.document.commands) == history
    assert services.kernel.drawing_block_instances == ()
    if action == "create":
        assert tuple(editor.canvas.entities) == (revised,)


def test_insert_dialog_rejects_changed_active_layer(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition
    from mycad.core.sketch import SketchLayer

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("Other"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.set_layer_table(layers, "0")
    history = tuple(loaded.document.commands)

    def change_layer() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockInsertDialog)
        editor.canvas.set_layer_table(layers, "Other")
        dialog.accept()

    QTimer.singleShot(0, change_layer)
    editor.block_insert_button.click()
    assert editor.canvas.active_layer_name == "Other"
    assert editor.canvas.collection_session is None
    assert tuple(loaded.document.commands) == history
    assert services.kernel.drawing_block_instances == ()
    assert "变化" in editor.status_label.text()


@pytest.mark.parametrize("restriction", ["instance_locked", "member_hidden", "member_frozen"])
@pytest.mark.parametrize("active_session", [False, True])
def test_insert_rejects_restricted_layers_before_creating_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, restriction: str, active_session: bool
) -> None:
    from collections.abc import Callable
    from dataclasses import replace

    from mycad.core.drawing_blocks import BlockDefinition
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("Insert")).add(SketchLayer("Member"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    definition = BlockDefinition(
        uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="Member"),), ()
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    if restriction == "instance_locked":
        blocked = layers.replace(replace(layers.get("Insert"), locked=True))
    elif restriction == "member_hidden":
        blocked = layers.replace(replace(layers.get("Member"), visible=False))
    else:
        blocked = layers.replace(replace(layers.get("Member"), frozen=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": blocked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    editor.canvas.set_layer_table(blocked, "Insert")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    if active_session:
        cast("Callable[[object], object]", getattr(window, _ENSURE_METHOD))(editor)
    original_session = editor.canvas.collection_session
    checkpoint = original_session.checkpoint() if original_session is not None else None
    history = tuple(loaded.document.commands)

    def insert() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockInsertDialog)
        dialog.accept()

    QTimer.singleShot(0, insert)
    editor.block_insert_button.click()
    assert "图层" in editor.status_label.text()
    editor.canvas.cursor_changed.emit(1.0, 1.0, "")
    assert "图层" in editor.status_label.text()
    assert editor.canvas.collection_session is original_session
    if original_session is not None:
        assert original_session.checkpoint() == checkpoint
    assert tuple(loaded.document.commands) == history
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == ()


def test_cancel_block_dialog_does_not_create_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}

    def cancel() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.reject()

    QTimer.singleShot(0, cancel)
    editor.block_create_button.click()
    assert editor.canvas.collection_session is None and loaded.document.commands == ()
    assert editor.canvas.entities == [line]


@pytest.mark.parametrize("active_session", [False, True])
def test_duplicate_block_name_rejects_without_modifying_source(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, active_session: bool
) -> None:
    from collections.abc import Callable

    from mycad.core.drawing_blocks import BlockDefinition

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    existing = BlockDefinition(
        uuid4().hex, "Existing", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ()
    )
    loaded.bus.execute("drawing.block.create", existing.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    source = LineEntity(uuid4().hex, (2, 0), (4, 0))
    assert editor.canvas.replace_draft_entities((source,))
    editor.canvas.selected_entity_ids = {source.entity_id}
    if active_session:
        cast("Callable[[object], object]", getattr(window, _ENSURE_METHOD))(editor)
    original_session = editor.canvas.collection_session
    checkpoint = original_session.checkpoint() if original_session is not None else None
    before = tuple(loaded.document.commands)

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("existing")
        dialog.accept()

    QTimer.singleShot(0, create)
    editor.block_create_button.click()
    assert editor.canvas.collection_session is original_session
    if original_session is not None:
        assert original_session.checkpoint() == checkpoint
    assert services.kernel.drawing_block_definitions == (existing,)
    assert services.kernel.drawing_block_instances == ()
    assert tuple(editor.canvas.entities) == (source,)
    assert tuple(loaded.document.commands) == before
    assert "名称" in editor.status_label.text()


def test_block_rejects_constrained_sources_before_creating_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (2, 0), (2, 3))
    constraint = SketchConstraint(
        uuid4().hex,
        "coincident",
        (
            SketchGeometryReference(first.entity_id, "end"),
            SketchGeometryReference(second.entity_id, "start"),
        ),
    )
    saved = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second), (constraint,))
    app.commit_new_sketch(
        services, loaded, saved, session_identity=cast("int", getattr(window, _SESSION_FIELD))
    )
    editor.set_context_sketches(services.kernel.sketches)
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {first.entity_id, second.entity_id}
    history = tuple(loaded.document.commands)

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("Constrained")
        dialog.accept()

    QTimer.singleShot(0, create)
    editor.block_create_button.click()
    assert "约束" in editor.status_label.text()
    assert editor.canvas.collection_session is None
    assert tuple(loaded.document.commands) == history
    assert services.kernel.sketches == (saved,)
    assert services.kernel.drawing_block_definitions == ()


def test_block_conversion_attached_group_fails_without_changing_draft_then_can_keep_sources(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    def discard(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Discard

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    monkeypatch.setattr(QMessageBox, "question", discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved_line = LineEntity(uuid4().hex, (0, 0), (5, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved_line,))
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=cast("int", getattr(window, _SESSION_FIELD))
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(saved_line.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    draft_line = LineEntity(uuid4().hex, (0, 5), (5, 5))
    assert canvas.replace_draft_entities((draft_line,))
    canvas.selected_entity_ids = {saved_line.entity_id, draft_line.entity_id}
    history = tuple(loaded.document.commands)

    def create(keep: bool) -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("AttachedSources")
        dialog.source_mode.setCurrentIndex(1 if keep else 0)
        dialog.accept()

    try:
        window.act_drawing_group.trigger()
        session = canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 1
        before = session.snapshot
        checkpoint = session.checkpoint()
        canvas.selected_entity_ids = {saved_line.entity_id, draft_line.entity_id}
        QTimer.singleShot(0, lambda: create(False))
        editor.block_create_button.click()
        assert "附着" in editor.status_label.text()
        canvas.cursor_changed.emit(1.0, 1.0, "")
        assert "附着" in editor.status_label.text()
        assert session.snapshot == before and session.checkpoint() == checkpoint
        assert tuple(loaded.document.commands) == history and canvas.entities == [draft_line]
        QTimer.singleShot(0, lambda: create(True))
        editor.block_create_button.click()
        after = session.snapshot
        assert "块定义" in editor.status_label.text()
        canvas.cursor_changed.emit(1.0, 1.0, "")
        assert "块定义" in editor.status_label.text()
        assert len(after.block_definitions) == 1 and not after.block_instances
        assert after.groups == before.groups and after.datums == (datum,)
        assert canvas.undo_last_operation() and session.snapshot == before
        assert canvas.redo_last_operation() and session.snapshot == after
        editor.finish_sketch()
        qtbot.waitUntil(
            lambda: not unit.is_busy and window.active_sketch_dialog() is not editor,
            timeout=10000,
        )
        path = tmp_path / "attached-group-keep.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert len(services.kernel.drawing_block_definitions) == 1
        assert services.kernel.drawing_datum_identifiers == (datum,)
        reopened.bus.undo_operation()
        assert not services.kernel.drawing_block_definitions
        assert services.kernel.drawing_datum_identifiers == (datum,)
        assert services.kernel.drawing_groups == before.groups
        reopened.bus.redo_operation()
        assert len(services.kernel.drawing_block_definitions) == 1
    finally:
        if window.active_sketch_dialog() is editor:
            editor.reject()


def test_block_and_insert_can_pick_points_on_canvas(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (1, 1), (5, 1))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}

    def request_base() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("Picked")
        dialog.pick_point_button.click()

    QTimer.singleShot(0, request_base)
    editor.block_create_button.click()
    assert editor.canvas.block_point_capture_active

    picked_base: list[tuple[float, float]] = []

    def accept_base() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        picked_base.append((dialog.base_x.value(), dialog.base_y.value()))
        dialog.accept()

    QTimer.singleShot(0, accept_base)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((1, 1))
    )
    assert picked_base == [pytest.approx((1, 1))]
    session = editor.canvas.collection_session
    assert session is not None and session.snapshot.block_instances[
        0
    ].insertion_mm == pytest.approx((1, 1))

    def request_insertion() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockInsertDialog)
        dialog.rotation_field.setValue(30)
        dialog.scale_field.setValue(2)
        dialog.pick_point_button.click()

    QTimer.singleShot(0, request_insertion)
    editor.block_insert_button.click()
    assert editor.canvas.block_point_capture_active

    picked_insert: list[tuple[float, float, float, float]] = []

    def accept_insertion() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockInsertDialog)
        picked_insert.append(
            (
                dialog.x_field.value(),
                dialog.y_field.value(),
                dialog.rotation_field.value(),
                dialog.scale_field.value(),
            )
        )
        dialog.accept()

    QTimer.singleShot(0, accept_insertion)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((10, 10))
    )
    assert picked_insert == [pytest.approx((10, 10, 30, 2), abs=0.15)]
    assert len(session.snapshot.block_instances) == 2
    assert session.snapshot.block_instances[-1].insertion_mm == pytest.approx((10, 10), abs=0.15)
    assert session.snapshot.block_instances[-1].rotation_deg == 30
    assert loaded.document.commands == ()


@pytest.mark.parametrize("action", ["create", "insert"])
@pytest.mark.parametrize("plane", ["tilted", "offset"])
def test_block_canvas_point_rejects_non_coplanar_work_plane(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str, plane: str
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition
    from mycad.ui.drawing_block_dialogs import PICK_POINT

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    if action == "insert":
        definition = BlockDefinition(uuid4().hex, "Existing", (line,), ())
        loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    if plane == "tilted":
        editor.plane_combo.setCurrentText("XZ")
    else:
        editor.origin_fields["Z"].setValue(5)
    if action == "create":
        assert editor.canvas.replace_draft_entities((line,))
        editor.canvas.selected_entity_ids = {line.entity_id}
    history = tuple(loaded.document.commands)

    def request_point(_dialog: BlockCreateDialog | BlockInsertDialog) -> int:
        return PICK_POINT

    monkeypatch.setattr(
        BlockCreateDialog if action == "create" else BlockInsertDialog, "exec", request_point
    )
    (editor.block_create_button if action == "create" else editor.block_insert_button).click()
    assert not editor.canvas.block_point_capture_active
    assert "共面" in editor.status_label.text()
    assert editor.canvas.collection_session is None
    assert tuple(loaded.document.commands) == history


@pytest.mark.parametrize("change_after_request", [False, True])
def test_block_insert_canvas_point_uses_stable_coplanar_frame(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, change_after_request: bool
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.ui.drawing_block_dialogs import PICK_POINT

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Existing", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    rotated = WorkPlaneFrame((0, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    current = [WorkPlaneFrame.xy() if change_after_request else rotated]
    monkeypatch.setattr(editor, "current_frame", lambda: current[0])
    results: list[tuple[float, float]] = []
    calls = 0

    def request_point(dialog: BlockInsertDialog) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return PICK_POINT
        results.append((dialog.x_field.value(), dialog.y_field.value()))
        return 1

    monkeypatch.setattr(BlockInsertDialog, "exec", request_point)
    editor.block_insert_button.click()
    assert editor.canvas.block_point_capture_active
    if change_after_request:
        current[0] = rotated
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((3, 4))
    )
    if change_after_request:
        assert results == [] and "变化" in editor.status_label.text()
        assert editor.canvas.collection_session is None
    else:
        assert results == [pytest.approx((-4, 3), abs=0.15)]
        session = editor.canvas.collection_session
        assert session is not None, editor.status_label.text()
        assert session.snapshot.block_instances[0].insertion_mm == pytest.approx((-4, 3), abs=0.15)


@pytest.mark.parametrize("scale", ["1e-10", "1e10"])
def test_block_insert_accepts_precise_positive_scale(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, scale: str
) -> None:
    from PySide6.QtWidgets import QDialog, QInputDialog

    from mycad.core.drawing_blocks import BlockDefinition

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    extent = 1e10 if scale == "1e-10" else 1e-10
    line = LineEntity(uuid4().hex, (0, 0), (extent, 0))
    definition = BlockDefinition(uuid4().hex, "Large", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)

    def exact_input(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return scale, True

    notices: list[str] = []

    def insert(dialog: BlockInsertDialog) -> int:
        dialog.scale_exact_button.click()
        notices.append(dialog.scale_notice.text())
        return QDialog.DialogCode.Accepted.value

    monkeypatch.setattr(QInputDialog, "getText", exact_input)
    monkeypatch.setattr(BlockInsertDialog, "exec", insert)
    editor.block_insert_button.click()
    assert len(notices) == 1 and repr(float(scale)) in notices[0]
    session = editor.canvas.collection_session
    assert session is not None, editor.status_label.text()
    assert session.snapshot.block_instances[0].scale == float(scale)
    assert len(loaded.document.commands) == 1


@pytest.mark.parametrize("invalid", ["0", "-1", "nan", "1e-9999"])
def test_block_insert_rejects_invalid_exact_scale(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QInputDialog

    def exact_input(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return invalid, True

    monkeypatch.setattr(QInputDialog, "getText", exact_input)
    dialog = BlockInsertDialog(())
    qtbot.addWidget(dialog)
    dialog.scale_exact_button.click()
    assert dialog.scale_field.input_error is not None
    assert dialog.scale_notice.text()
    buttons = dialog.findChild(QDialogButtonBox)
    assert buttons is not None
    button = buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert button is not None
    button.click()
    assert dialog.result() != QDialog.DialogCode.Accepted.value


@pytest.mark.parametrize("restriction", ["locked", "hidden"])
@pytest.mark.parametrize("active_session", [False, True])
def test_explode_rejects_restricted_member_without_creating_session(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, restriction: str, active_session: bool
) -> None:
    from collections.abc import Callable
    from dataclasses import replace

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("Member"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    first = LineEntity(uuid4().hex, (0, 0), (2, 0))
    second = LineEntity(uuid4().hex, (0, 1), (2, 1), layer_name="Member")
    definition = BlockDefinition(uuid4().hex, "B", (first, second), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5))
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    layer = layers.get("Member")
    blocked = layers.replace(
        replace(layer, locked=True) if restriction == "locked" else replace(layer, visible=False)
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": blocked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    editor.canvas.set_layer_table(blocked, "0")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    if active_session:
        cast("Callable[[object], object]", getattr(window, _ENSURE_METHOD))(editor)
    session = editor.canvas.collection_session
    checkpoint = session.checkpoint() if session is not None else None
    history = tuple(loaded.document.commands)
    editor.drawing_command_bar.input.setText("EXPLODE")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert "图层" in editor.status_label.text()
    editor.canvas.cursor_changed.emit(1.0, 1.0, "")
    assert "图层" in editor.status_label.text()
    assert editor.canvas.collection_session is session
    if session is not None:
        assert session.checkpoint() == checkpoint
    assert tuple(loaded.document.commands) == history
    assert services.kernel.drawing_block_instances == (instance,)
    assert services.kernel.drawing_groups == (group,)


def test_explode_command_on_selected_block_undoes_as_one_step(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.replay_proposal import ReplayAppend

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    editor.canvas.selected_entity_ids = {line.entity_id}

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("Explode")
        dialog.accept()

    QTimer.singleShot(0, create)
    editor.block_create_button.click()
    session = editor.canvas.collection_session
    assert session is not None and len(session.snapshot.block_instances) == 1
    instance = session.snapshot.block_instances[0]
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local")
    )
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    before = session.snapshot
    editor.drawing_command_bar.input.setText("EXPLODE")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert session.snapshot.block_instances == ()
    assert len(session.snapshot.block_definitions) == 1
    assert sum(len(sketch.entities) for sketch in session.snapshot.sketches) == 1
    assert len(session.snapshot.groups) == 1
    assert session.snapshot.groups[0].members[0].kind == "geometry"
    assert editor.canvas.undo_last_operation() and session.snapshot == before
    assert loaded.document.commands == ()


def test_block_only_clipboard_from_canvas_pastes_shared_definition(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    definition = BlockDefinition(
        uuid4().hex, "Copied", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    try:
        assert editor.canvas.copy_to_clipboard()
        assert editor.canvas.begin_clipboard_paste()
        editor.canvas.add_coordinate_point((10, 10), exact_point=True)
        session = editor.canvas.collection_session
        assert session is not None and len(session.snapshot.block_instances) == 2
        copy = session.snapshot.block_instances[-1]
        assert (
            copy.instance_id != instance.instance_id
            and copy.definition_id == definition.definition_id
        )
        assert copy.insertion_mm == (10, 10)
        assert editor.canvas.undo_last_operation() and session.snapshot.block_instances == (
            instance,
        )
    finally:
        QApplication.clipboard().clear()


@pytest.mark.parametrize("cancel_method", ["escape", "right_click"])
@pytest.mark.parametrize("active_session", [False, True])
def test_cancelling_block_clipboard_paste_stops_placement(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, cancel_method: str, active_session: bool
) -> None:
    from collections.abc import Callable

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    draft_first = LineEntity(uuid4().hex, (0, 1), (2, 1))
    draft_second = LineEntity(uuid4().hex, (0, 2), (2, 2))
    if active_session:
        cast("Callable[[object], object]", getattr(window, _ENSURE_METHOD))(editor)
    else:
        assert editor.canvas.replace_draft_entities((draft_first,))
        assert editor.canvas.replace_draft_entities((draft_first, draft_second))
        assert editor.canvas.undo_last_operation()
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    history = tuple(loaded.document.commands)
    try:
        assert editor.canvas.copy_to_clipboard()
        assert editor.canvas.begin_clipboard_paste()
        session = editor.canvas.collection_session
        assert session is not None
        checkpoint, before = session.checkpoint(), session.snapshot
        if cancel_method == "escape":
            QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
        else:
            QTest.mouseClick(
                editor.canvas, Qt.MouseButton.RightButton, pos=editor.canvas.rect().center()
            )
        assert not editor.canvas.clipboard_paste_active
        assert editor.canvas.collection_paste_preview is None
        if active_session:
            assert editor.canvas.collection_session is session
            assert session.checkpoint() == checkpoint and session.snapshot == before
        else:
            assert editor.canvas.collection_session is None
            guard = loaded.bus.acquire_drawing_write_guard()
            loaded.bus.release_drawing_write_guard(guard)
            assert editor.canvas.redo_last_operation()
            assert tuple(editor.canvas.entities) == (draft_first, draft_second)
            assert editor.canvas.undo_last_operation()
            assert tuple(editor.canvas.entities) == (draft_first,)
        assert tuple(loaded.document.commands) == history
        assert editor.canvas.begin_clipboard_paste()
        session = editor.canvas.collection_session
        assert session is not None
        editor.canvas.add_coordinate_point((10, 10), exact_point=True)
        assert len(session.snapshot.block_instances) == 2
    finally:
        QApplication.clipboard().clear()


def test_cancel_block_paste_allows_block_editing_without_a_draft(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    try:
        assert editor.canvas.copy_to_clipboard()
        assert editor.canvas.begin_clipboard_paste()
        QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
        editor.canvas.selected_block_instance_ids = {instance.instance_id}
        editor.drawing_command_bar.input.setText("BEDIT")
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
        block_editor = window.active_block_editor()
        assert block_editor is not None
        block_editor.close()
    finally:
        QApplication.clipboard().clear()


def test_cancel_paste_keeps_session_with_new_operations(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.replay_proposal import ReplayAppend

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    try:
        assert editor.canvas.copy_to_clipboard()
        assert editor.canvas.begin_clipboard_paste()
        session = editor.canvas.collection_session
        assert session is not None
        group = DrawingGroup(
            uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),)
        )
        session.stage(ReplayAppend("drawing.group.create", 1, group.to_mapping(), "local"))
        before = session.snapshot
        QTest.keyClick(editor.canvas, Qt.Key.Key_Escape)
        assert editor.canvas.collection_session is session
        assert session.snapshot == before and session.snapshot.groups == (group,)
        assert not editor.canvas.clipboard_paste_active
    finally:
        QApplication.clipboard().clear()


def test_block_clipboard_cross_document_preview_matches_committed_instance(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance, expand_block
    from mycad.core.drawing_collection_clipboard import (
        DRAWING_COLLECTION_CLIPBOARD_MIME,
        decode_collection_clipboard,
    )
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.drawing_text import DrawingText

    source_services = app.build_app(discoverers=[])
    source_window = MainWindow(services=source_services)
    monkeypatch.setattr(type(source_window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(source_window)
    source_window.show()
    source_window.act_new_drawing.trigger()
    source_editor, source = source_window.active_sketch_dialog(), source_window.loaded_document()
    assert source_editor is not None and source is not None
    definition = BlockDefinition(
        uuid4().hex,
        "Shared",
        (LineEntity(uuid4().hex, (0, 0), (2, 0)),),
        (DrawingText(uuid4().hex, "A", (1, 1)),),
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5), 90, 2)
    source.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    source.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),), name="Group"
    )
    source.bus.execute("drawing.group.create", group.to_mapping(), "local")
    source_editor.canvas.set_source_context_revision(source.document.revision)
    source_editor.canvas.selected_block_instance_ids = {instance.instance_id}
    try:
        assert source_editor.canvas.copy_to_clipboard()
        mime = QApplication.clipboard().mimeData()
        assert mime is not None
        payload = decode_collection_clipboard(
            bytes(mime.data(DRAWING_COLLECTION_CLIPBOARD_MIME).data())
        )
        target_services = app.build_app(discoverers=[])
        target_window = MainWindow(services=target_services)
        monkeypatch.setattr(type(target_window.viewport), "paintGL", _skip_gl_paint)
        qtbot.addWidget(target_window)
        target_window.show()
        target_window.act_new_drawing.trigger()
        editor, loaded = target_window.active_sketch_dialog(), target_window.loaded_document()
        assert editor is not None and loaded is not None
        conflict = BlockDefinition(
            uuid4().hex, "Shared", (LineEntity(uuid4().hex, (0, 0), (3, 0)),), ()
        )
        loaded.bus.execute("drawing.block.create", conflict.to_mapping(), "local")
        editor.canvas.set_source_context_revision(loaded.document.revision)
        assert editor.canvas.begin_clipboard_paste()
        provider = editor.canvas.collection_paste_preview_provider
        assert provider is not None
        preview = provider(payload, (6, 5))
        assert len(preview.payload.sketches) == 1 and len(preview.payload.texts) == 1
        editor.canvas.collection_paste_preview = preview
        editor.canvas.add_coordinate_point((10, 10), exact_point=True)
        session = editor.canvas.collection_session
        assert session is not None and len(session.snapshot.block_instances) == 1
        pasted = session.snapshot.block_instances[0]
        copied_def = next(
            item
            for item in session.snapshot.block_definitions
            if item.definition_id == pasted.definition_id
        )
        expanded = expand_block(copied_def, pasted, session.snapshot.text_styles)
        assert preview.payload.sketches[0].sketch_id == pasted.instance_id
        assert preview.payload.sketches[0].entities == expanded.entities
        assert preview.payload.texts == expanded.texts
        assert pasted.insertion_mm == (10, 10) and pasted.rotation_deg == 90 and pasted.scale == 2
        assert copied_def.name != conflict.name and session.snapshot.groups[0].members == (
            DrawingObjectRef("block_instance", pasted.instance_id),
        )
        assert editor.canvas.undo_last_operation()
        assert session.snapshot.block_instances == () and session.snapshot.block_definitions == (
            conflict,
        )
    finally:
        QApplication.clipboard().clear()


def test_full_mixed_group_cross_document_clipboard_from_block_seed(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from collections.abc import Callable
    from dataclasses import replace
    from typing import Any, cast

    import ezdxf
    from PySide6.QtGui import QImage, QPainter

    from mycad.core.detached_dimension import DetachedDimension
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance, expand_block
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_text import DrawingText
    from mycad.core.geometric_tolerance import (
        DatumAttachment,
        DatumIdentifier,
        DatumReference,
        FeatureControlFrame,
        ToleranceRow,
    )
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.formats.dxf_collection_import import prepare_dxf_collection_import
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    source_services = app.build_app(discoverers=[])
    source_window = MainWindow(services=source_services)
    monkeypatch.setattr(type(source_window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(source_window)
    source_window.show()
    source_window.act_new_drawing.trigger()
    editor, source = source_window.active_sketch_dialog(), source_window.loaded_document()
    assert editor is not None and source is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 2),
    )
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,), (dimension,))
    app.commit_new_sketch(source_services, source, sketch, session_identity=1)
    text = DrawingText(uuid4().hex, "Label", (3, 8))
    image = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (3, 2),
        2,
        2,
    )
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (20, 10),
        (0, 0),
        layout_mode="shared",
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    frame = FeatureControlFrame(
        uuid4().hex,
        (ToleranceRow("position", 0.1, 2, datums=(DatumReference("A", datum.datum_id),)),),
        (10, 10),
    )
    reference = DetachedDimension(uuid4().hex, "rotated", (0, 0), (10, 0), (0, 5), 0, 10)
    inner_text = DrawingText(
        uuid4().hex, "Inside", (1, 1), kind="mtext", height_mm=2, box_width_mm=6
    )
    definition = BlockDefinition(
        uuid4().hex, "Shared", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), (inner_text,)
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (4, 5), 90, 2)
    source.bus.execute("drawing.text.add", text.to_mapping(), "local")
    source.bus.execute("drawing.raster.add", image.to_mapping(), "local", version=1)
    source.bus.execute(
        "drawing.tolerance.batch",
        {"add_frames": [frame.to_mapping()], "add_datums": [datum.to_mapping()]},
        "local",
    )
    source.bus.execute(
        "drawing.reference_dimensions.batch", {"add": [reference.to_mapping()]}, "local"
    )
    source.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    source.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id),
            DrawingObjectRef("text", text.text_id),
            DrawingObjectRef("raster", image.image_id),
            DrawingObjectRef("tolerance", frame.frame_id),
            DrawingObjectRef("datum", datum.datum_id),
            DrawingObjectRef("reference_dimension", reference.dimension_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
        name="Mixed",
    )
    source.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.set_context_sketches(source_services.kernel.sketches)
    editor.canvas.set_source_context_revision(source.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    try:
        source_before = app.drawing_collection_snapshot(source_services)
        editor.canvas.begin_transform("move")
        editor.canvas.add_coordinate_point((0, 0), exact_point=True)
        editor.canvas.add_coordinate_point((0, 12), exact_point=True)
        source_session = editor.canvas.collection_session
        assert source_session is not None
        moved = source_session.snapshot
        moved_sketch = next(item for item in moved.sketches if item.sketch_id == sketch.sketch_id)
        moved_line = moved_sketch.entities[0]
        assert isinstance(moved_line, LineEntity)
        assert moved_line.start_mm == pytest.approx((0, 12))
        assert moved_sketch.constraints[0].position_mm == pytest.approx((5, 14))
        assert moved.texts[0].position_mm == pytest.approx((3, 20))
        assert moved.rasters[0].origin_mm == pytest.approx((3, 14))
        assert moved.frames[0].position_mm == pytest.approx((10, 22))
        assert moved.datums[0].position_mm == pytest.approx((20, 22))
        assert moved.datums[0].target_mm == pytest.approx((0, 12))
        assert moved.datums[0].attachment == datum.attachment
        assert moved.reference_dimensions[0].first_mm == pytest.approx((0, 12))
        assert moved.block_instances[0].insertion_mm == pytest.approx((4, 17))
        assert app.drawing_collection_snapshot(source_services) == source_before
        assert editor.canvas.undo_last_operation()
        restored = source_session.snapshot
        assert (
            replace(restored, sketches=tuple(item for item in restored.sketches if item.entities))
            == source_before
        )
        assert editor.canvas.redo_last_operation()
        assert source_session.snapshot == moved
        assert editor.canvas.undo_last_operation()
        editor.canvas.selected_block_instance_ids = {instance.instance_id}
        assert editor.canvas.copy_to_clipboard()
        target_services = app.build_app(discoverers=[])
        target_window = MainWindow(services=target_services)
        monkeypatch.setattr(type(target_window.viewport), "paintGL", _skip_gl_paint)
        qtbot.addWidget(target_window)
        target_window.show()
        target_window.act_new_drawing.trigger()
        target_editor, target = (
            target_window.active_sketch_dialog(),
            target_window.loaded_document(),
        )
        unit = target_window.execution_unit
        assert target_editor is not None and target is not None and unit is not None
        assert target_editor.canvas.begin_clipboard_paste()
        monkeypatch.setattr(target_editor.canvas, "_cursor", (50, 50))
        image_preview = QImage(100, 100, QImage.Format.Format_ARGB32)
        painter = QPainter(image_preview)
        try:
            cast("Callable[..., None]", vars(type(target_editor.canvas))["_draw_preview"])(
                target_editor.canvas, painter
            )
        finally:
            painter.end()
        preview_candidate = target_editor.canvas.collection_paste_preview
        assert preview_candidate is not None
        assert target.document.commands == ()
        assert len(preview_candidate.payload.rasters) == 1
        assert len(preview_candidate.payload.frames) == len(preview_candidate.payload.datums) == 1
        assert len(preview_candidate.payload.reference_dimensions) == 1
        target_editor.canvas.add_coordinate_point((50, 50), exact_point=True)
        session = target_editor.canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 1
        assert {item.kind for item in session.snapshot.groups[0].members} == {
            item.kind for item in group.members
        }
        copied_geometry = next(
            item for item in session.snapshot.groups[0].members if item.kind == "geometry"
        )
        copied_dimension = next(
            item for item in session.snapshot.groups[0].members if item.kind == "dimension"
        )
        copied_sketch = next(
            item
            for item in session.snapshot.sketches
            if item.sketch_id == copied_geometry.sketch_id
        )
        assert copied_sketch.constraints[0].constraint_id == copied_dimension.object_id
        assert copied_sketch.constraints[0].references[0].entity_id == copied_geometry.object_id
        copied_datum = session.snapshot.datums[0]
        assert copied_datum.attachment is not None
        assert copied_datum.attachment.sketch_id == copied_geometry.sketch_id
        assert copied_datum.attachment.reference.entity_id == copied_geometry.object_id
        assert session.snapshot.frames[0].rows[0].datums[0].datum_id == copied_datum.datum_id
        preview_sketch = next(
            item
            for item in preview_candidate.payload.sketches
            if item.sketch_id == copied_sketch.sketch_id
        )
        assert preview_sketch.entities == copied_sketch.entities
        assert preview_sketch.constraints == copied_sketch.constraints
        assert preview_candidate.payload.rasters == session.snapshot.rasters
        assert preview_candidate.payload.frames == session.snapshot.frames
        assert preview_candidate.payload.datums == session.snapshot.datums
        assert (
            preview_candidate.payload.reference_dimensions == session.snapshot.reference_dimensions
        )
        assert target.document.commands == ()
        assert session.snapshot.rasters[0].png_base64 == image.png_base64
        assert (
            session.snapshot.block_instances[0].definition_id
            == session.snapshot.block_definitions[0].definition_id
        )
        expansion = expand_block(
            session.snapshot.block_definitions[0],
            session.snapshot.block_instances[0],
            session.snapshot.text_styles,
        )
        assert preview_candidate.payload.texts == (*session.snapshot.texts, *expansion.texts)
        assert expansion.texts[0].height_mm == pytest.approx(4)
        assert expansion.texts[0].box_width_mm == pytest.approx(12)
        assert expansion.texts[0].rotation_deg == pytest.approx(90)
        preview_block = next(
            item
            for item in preview_candidate.payload.sketches
            if item.sketch_id == session.snapshot.block_instances[0].instance_id
        )
        assert preview_block.entities == expansion.entities
        pasted = session.snapshot
        assert target_editor.canvas.undo_last_operation()
        assert session.snapshot.groups == () and session.snapshot.block_instances == ()
        assert target_editor.canvas.redo_last_operation()
        assert session.snapshot == pasted
        target_editor.finish_sketch()
        qtbot.waitUntil(
            lambda: not unit.is_busy and target_window.active_sketch_dialog() is not target_editor,
            timeout=15000,
        )
        committed = replace(
            pasted, sketches=tuple(item for item in pasted.sketches if item.entities)
        )
        assert app.drawing_collection_snapshot(target_services) == committed
        path = tmp_path / "full-group-paste.my2d"
        save_document(target.document, path)
        reopened = app.open_app_document(target_services, path)
        assert app.drawing_collection_snapshot(target_services) == committed
        reopened.bus.undo_operation()
        assert target_services.kernel.drawing_groups == ()
        assert target_services.kernel.drawing_block_instances == ()
        assert target_services.kernel.drawing_rasters == ()
        reopened.bus.redo_operation()
        assert app.drawing_collection_snapshot(target_services) == committed
        preview = prepare_dxf_output_preview(target_services.kernel)
        assert any("图片未导出" in warning for warning in preview.report.warnings)
        assert any(
            "Mixed" in warning and "不完整" in warning for warning in preview.report.warnings
        )
        exchange = tmp_path / "full-group-paste.dxf"
        exchange.write_bytes(preview.dxf_bytes)
        imported = read_sketch_dxf(exchange)
        assert imported.datum_identifiers[0].attachment is not None
        assert (
            imported.datum_identifiers[0].attachment.reference.entity_id
            == imported.sketch.entities[0].entity_id
        )
        assert (
            imported.tolerance_frames[0].rows[0].datums[0].datum_id
            == imported.datum_identifiers[0].datum_id
        )
        assert imported.block_definitions[0].texts[0].text == inner_text.text
        assert imported.block_definitions[0].texts[0].height_mm == pytest.approx(2)
        assert imported.block_definitions[0].texts[0].box_width_mm == pytest.approx(6)
        assert len(imported.groups) == 1
        assert {item.kind for item in imported.groups[0].members} == {
            "geometry",
            "dimension",
            "text",
            "tolerance",
            "datum",
            "reference_dimension",
            "block_instance",
        }
        native = cast("Callable[..., Any]", vars(ezdxf)["readfile"])(exchange)
        native.blocks.get("Shared").query("LINE")[0].dxf.end = (7, 0, 0)
        native.modelspace().query('INSERT[name=="Shared"]')[0].dxf.insert = (77, 88, 0)
        native.modelspace().query("TEXT")[0].dxf.text = "Changed externally"
        changed_path = tmp_path / "full-group-external-change.dxf"
        native.saveas(changed_path)
        changed = read_sketch_dxf(changed_path)
        changed_line = changed.block_definitions[0].entities[0]
        assert isinstance(changed_line, LineEntity) and changed_line.end_mm == (7, 0)
        assert changed.block_instances[0].insertion_mm == (77, 88)
        assert changed.texts[0].text == "Changed externally"
        assert {item.kind for item in changed.groups[0].members} == {
            "geometry",
            "dimension",
            "text",
            "tolerance",
            "datum",
            "reference_dimension",
            "block_instance",
        }
        import_states = [committed]
        for _ in range(2):
            prepared = prepare_dxf_collection_import(imported, import_states[-1])
            assert any("块名称冲突" in warning for warning in prepared.warnings)
            assert any("组名称冲突" in warning for warning in prepared.warnings)
            reopened.bus.execute(
                prepared.operation.command_id,
                prepared.operation.params,
                "local",
                version=prepared.operation.version,
            )
            import_states.append(app.drawing_collection_snapshot(target_services))
        latest = import_states[-1]
        assert (
            len(latest.groups) == len(latest.block_instances) == len(latest.block_definitions) == 3
        )
        assert len({item.name.casefold() for item in latest.groups if item.name is not None}) == 3
        assert len({item.name.casefold() for item in latest.block_definitions}) == 3
        assert all(item.texts[0].text == inner_text.text for item in latest.block_definitions)
        assert len({item.instance_id for item in latest.block_instances}) == 3
        assert all(
            set(first.members).isdisjoint(second.members)
            for index, first in enumerate(latest.groups)
            for second in latest.groups[index + 1 :]
        )
        for group_index, item in enumerate(latest.groups):
            expected_kinds = {
                "geometry",
                "dimension",
                "text",
                "tolerance",
                "datum",
                "reference_dimension",
                "block_instance",
            }
            if group_index == 0:
                expected_kinds.add("raster")
            assert {member.kind for member in item.members} == expected_kinds
            geometry = next(member for member in item.members if member.kind == "geometry")
            datum_ref = next(member for member in item.members if member.kind == "datum")
            frame_ref = next(member for member in item.members if member.kind == "tolerance")
            latest_datum = next(
                value for value in latest.datums if value.datum_id == datum_ref.object_id
            )
            latest_frame = next(
                value for value in latest.frames if value.frame_id == frame_ref.object_id
            )
            assert latest_datum.attachment is not None
            assert latest_datum.attachment.sketch_id == geometry.sketch_id
            assert latest_datum.attachment.reference.entity_id == geometry.object_id
            assert latest_frame.rows[0].datums[0].datum_id == latest_datum.datum_id
        repeated_path = tmp_path / "full-group-repeated.my2d"
        save_document(reopened.document, repeated_path)
        repeated = app.open_app_document(target_services, repeated_path)
        assert app.drawing_collection_snapshot(target_services) == import_states[-1]
        repeated.bus.undo_operation()
        assert app.drawing_collection_snapshot(target_services) == import_states[-2]
        repeated.bus.undo_operation()
        assert app.drawing_collection_snapshot(target_services) == import_states[0]
    finally:
        QApplication.clipboard().clear()


def test_mixed_group_clipboard_repeated_paste_preserves_groups_and_shared_definition(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=int(getattr(window, _SESSION_FIELD))
    )
    definition = BlockDefinition(
        uuid4().hex, "Mixed", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_entity_ids = {line.entity_id}
    try:
        assert editor.canvas.copy_to_clipboard()
        for point in ((0, 5), (0, 10)):
            assert editor.canvas.begin_clipboard_paste()
            editor.canvas.add_coordinate_point(point, exact_point=True)
        session = editor.canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 3
        assert session.snapshot.block_definitions == (definition,)
        first, second = session.snapshot.block_instances[1:]
        assert (
            first.instance_id != second.instance_id
            and first.definition_id == second.definition_id == definition.definition_id
        )
        assert first.insertion_mm == (5, 5) and second.insertion_mm == (5, 10)
        for group_copy, block in zip(session.snapshot.groups[1:], (first, second), strict=True):
            assert DrawingObjectRef("block_instance", block.instance_id) in group_copy.members
            assert len(group_copy.members) == 2
        assert editor.canvas.undo_last_operation()
        assert (
            session.snapshot.block_instances == (instance, first)
            and len(session.snapshot.groups) == 2
        )
        assert editor.canvas.undo_last_operation()
        assert session.snapshot.block_instances == (instance,) and session.snapshot.groups == (
            group,
        )
    finally:
        QApplication.clipboard().clear()
