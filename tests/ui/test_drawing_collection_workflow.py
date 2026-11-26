# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""User-facing GROUP and BLOCK workflow across draft and persisted history."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.drawing_groups import DrawingObjectRef
from mycad.core.persistence import save_document
from mycad.core.sketch import LineEntity, Sketch
from mycad.ui.drawing_block_dialogs import BlockCreateDialog, BlockInsertDialog
from mycad.ui.main_window import MainWindow

_SESSION_FIELD = "_session_id"
_SYNC_METHOD = "_sync_drawing_layers"


def _skip_gl(*_args: object, **_kwargs: object) -> None:
    pass


def _discard(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
    return QMessageBox.StandardButton.Discard


@pytest.mark.parametrize("grouped", [False, True])
def test_block_context_menu_copies_pastes_and_deletes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, grouped: bool
) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QMenu

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_collection_clipboard import DRAWING_COLLECTION_CLIPBOARD_MIME
    from mycad.core.drawing_groups import DrawingGroup

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    definition = BlockDefinition(
        uuid4().hex, "Context", (LineEntity(uuid4().hex, (0, 0), (3, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    if grouped:
        group = DrawingGroup(
            uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),)
        )
        loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    history = tuple(loaded.document.commands)
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    assert canvas.set_tool("选择元素")
    canvas.selected_block_instance_ids = {instance.instance_id}
    seen: list[str] = []

    def choose(label: str) -> None:
        def on_open() -> None:
            popup = QApplication.activePopupWidget()
            if not isinstance(popup, QMenu):
                return
            action = next((item for item in popup.actions() if item.text().startswith(label)), None)
            if action is None or not action.isEnabled():
                popup.close()
                return
            seen.append(label)
            QTest.mouseClick(
                popup, Qt.MouseButton.LeftButton, pos=popup.actionGeometry(action).center()
            )

        QTimer.singleShot(0, on_open)
        canvas.contextMenuEvent(
            QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(20, 20), QPoint(20, 20))
        )

    clipboard = QApplication.clipboard()
    clipboard.clear()
    try:
        choose("复制")
        assert seen == ["复制"] and clipboard.mimeData().hasFormat(
            DRAWING_COLLECTION_CLIPBOARD_MIME
        )
        choose("粘贴")
        assert seen == ["复制", "粘贴"] and canvas.clipboard_paste_active
        canvas.add_coordinate_point((10, 0), exact_point=True)
        session = canvas.collection_session
        assert session is not None and len(session.snapshot.block_instances) == 2
        assert len(session.snapshot.groups) == (2 if grouped else 0)
        assert canvas.undo_last_operation() and session.snapshot.block_instances == (instance,)
        canvas.selected_block_instance_ids = {instance.instance_id}
        choose("删除")
        assert seen[-1] == "删除" and session.snapshot.block_instances == ()
        assert session.snapshot.block_definitions == (definition,) and session.snapshot.groups == ()
        assert canvas.undo_last_operation() and session.snapshot.block_instances == (instance,)
        assert tuple(loaded.document.commands) == history
        assert canvas.redo_last_operation() and session.snapshot.block_instances == ()
        editor.finish_sketch()
        unit = window.execution_unit
        assert unit is not None
        qtbot.waitUntil(
            lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
        )
        path = tmp_path / "context-block.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert services.kernel.drawing_block_instances == ()
        reopened.bus.undo_operation()
        assert services.kernel.drawing_block_instances == (instance,)
        assert len(services.kernel.drawing_groups) == (1 if grouped else 0)
        reopened.bus.redo_operation()
        assert services.kernel.drawing_block_instances == ()
    finally:
        clipboard.clear()
        editor.reject()


def test_group_context_menu_copies_from_datum_seed(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QMenu

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.geometric_tolerance import DatumIdentifier

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    definition = BlockDefinition(
        uuid4().hex, "DatumContext", (LineEntity(uuid4().hex, (0, 0), (3, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    datum = DatumIdentifier(uuid4().hex, "A", (4, 4), (0, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute(
        "drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local", version=28
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("block_instance", instance.instance_id),
            DrawingObjectRef("datum", datum.datum_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    assert canvas.set_tool("选择元素")
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    tools.selected_ids = {datum.datum_id}
    tools.selected_id = datum.datum_id
    tools.selected_kind = "datum"
    seen: list[str] = []

    def choose() -> None:
        popup = QApplication.activePopupWidget()
        if not isinstance(popup, QMenu):
            return
        action = next(item for item in popup.actions() if item.text().startswith("复制"))
        if not action.isEnabled():
            popup.close()
            return
        seen.append("复制")
        QTest.mouseClick(
            popup, Qt.MouseButton.LeftButton, pos=popup.actionGeometry(action).center()
        )

    clipboard = QApplication.clipboard()
    clipboard.clear()
    try:
        QTimer.singleShot(0, choose)
        canvas.contextMenuEvent(
            QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(20, 20), QPoint(20, 20))
        )
        assert seen == ["复制"]
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point((10, 0), exact_point=True)
        session = canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 2
        assert len(session.snapshot.block_instances) == len(session.snapshot.datums) == 2
        assert canvas.undo_last_operation() and session.snapshot.groups == (group,)
    finally:
        clipboard.clear()
        editor.reject()


def test_numeric_group_copy_from_dimension_seed_preserves_association(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        position_mm=(5, 4),
    )
    sketch = Sketch(uuid4().hex, editor.current_frame(), (line,), (dimension,))
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=int(getattr(window, _SESSION_FIELD))
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    history = tuple(loaded.document.commands)
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    canvas.selected_constraint_ids = {dimension.constraint_id}
    canvas.selected_dimension_refs = {
        DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id)
    }
    try:
        editor.delta_u_field.setValue(20)
        editor.numeric_move_button.click()
        session = canvas.collection_session
        assert session is not None
        moved_sketch = next(
            item for item in session.snapshot.sketches if item.sketch_id == sketch.sketch_id
        )
        moved_line = moved_sketch.entities[0]
        assert isinstance(moved_line, LineEntity) and moved_line.start_mm == (20, 0)
        assert moved_sketch.constraints[0].position_mm == (25, 4)
        assert moved_sketch.constraints[0].references[0].entity_id == line.entity_id
        assert tuple(loaded.document.commands) == history
        assert canvas.undo_last_operation()
        assert (
            next(item for item in session.snapshot.sketches if item.sketch_id == sketch.sketch_id)
            == sketch
        )
        canvas.selected_constraint_ids = {dimension.constraint_id}
        canvas.selected_dimension_refs = {
            DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id)
        }
        editor.numeric_copy_button.click()
        assert len(session.snapshot.groups) == 2, editor.status_label.text()
        after = session.snapshot
        copied = after.groups[1]
        copied_dimension = next(item for item in copied.members if item.kind == "dimension")
        copied_line = next(item for item in copied.members if item.kind == "geometry")
        target = next(item for item in after.sketches if item.sketch_id == copied_line.sketch_id)
        constraint = next(
            item for item in target.constraints if item.constraint_id == copied_dimension.object_id
        )
        assert constraint.references[0].entity_id == copied_line.object_id
        assert constraint.position_mm == (25, 4)
        assert tuple(loaded.document.commands) == history
        assert canvas.undo_last_operation() and session.snapshot.groups == (group,)
        assert canvas.redo_last_operation() and session.snapshot == after
        editor.finish_sketch()
        qtbot.waitUntil(
            lambda: not unit.is_busy and window.active_sketch_dialog() is not editor,
            timeout=10000,
        )
        path = tmp_path / "numeric-dimension.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert services.kernel.drawing_groups == after.groups
        reopened.bus.undo_operation()
        assert services.kernel.drawing_groups == (group,)
        reopened.bus.redo_operation()
        target = next(
            item for item in services.kernel.sketches if item.sketch_id == copied_line.sketch_id
        )
        assert (
            next(
                item
                for item in target.constraints
                if item.constraint_id == copied_dimension.object_id
            )
            .references[0]
            .entity_id
            == copied_line.object_id
        )
    finally:
        if window.active_sketch_dialog() is editor:
            editor.reject()


def test_group_context_menu_copies_from_dimension_seed(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QMenu

    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
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
    sketch = Sketch(uuid4().hex, editor.current_frame(), (line,), (dimension,))
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=int(getattr(window, _SESSION_FIELD))
    )
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    history = tuple(loaded.document.commands)
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    assert canvas.set_tool("选择元素")
    canvas.selected_constraint_ids = {dimension.constraint_id}
    canvas.selected_dimension_refs = {
        DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id)
    }
    seen: list[str] = []
    option = "复制"

    def choose() -> None:
        popup = QApplication.activePopupWidget()
        if not isinstance(popup, QMenu):
            return
        action = next(item for item in popup.actions() if item.text().startswith(option))
        if not action.isEnabled():
            popup.close()
            return
        seen.append(option)
        QTest.mouseClick(
            popup, Qt.MouseButton.LeftButton, pos=popup.actionGeometry(action).center()
        )

    clipboard = QApplication.clipboard()
    clipboard.clear()
    try:
        QTimer.singleShot(0, choose)
        canvas.contextMenuEvent(
            QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(20, 20), QPoint(20, 20))
        )
        assert seen == ["复制"]
        assert canvas.begin_clipboard_paste()
        canvas.add_coordinate_point((20, 0), exact_point=True)
        session = canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 2
        copied = session.snapshot.groups[1]
        copied_dimension = next(item for item in copied.members if item.kind == "dimension")
        copied_line = next(item for item in copied.members if item.kind == "geometry")
        target = next(
            item for item in session.snapshot.sketches if item.sketch_id == copied_line.sketch_id
        )
        constraint = next(
            item for item in target.constraints if item.constraint_id == copied_dimension.object_id
        )
        assert constraint.references[0].entity_id == copied_line.object_id
        assert canvas.undo_last_operation() and session.snapshot.groups == (group,)
        canvas.selected_constraint_ids = {dimension.constraint_id}
        canvas.selected_dimension_refs = {
            DrawingObjectRef("dimension", dimension.constraint_id, sketch.sketch_id)
        }
        option = "删除"
        QTimer.singleShot(0, choose)
        canvas.contextMenuEvent(
            QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(20, 20), QPoint(20, 20))
        )
        assert seen == ["复制", "删除"] and session.snapshot.groups == ()
        target = next(
            item for item in session.snapshot.sketches if item.sketch_id == sketch.sketch_id
        )
        assert not target.entities and not target.constraints
        assert canvas.undo_last_operation() and session.snapshot.groups == (group,)
        assert tuple(loaded.document.commands) == history
        assert canvas.redo_last_operation() and session.snapshot.groups == ()
        editor.finish_sketch()
        unit = window.execution_unit
        assert unit is not None
        qtbot.waitUntil(
            lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
        )
        path = tmp_path / "context-dimension-group.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert not services.kernel.drawing_groups
        reopened.bus.undo_operation()
        assert services.kernel.drawing_groups == (group,)
        assert services.kernel.sketches[0].entities == (line,)
        assert services.kernel.sketches[0].constraints == (dimension,)
        reopened.bus.redo_operation()
        assert not services.kernel.drawing_groups
    finally:
        clipboard.clear()
        editor.reject()


def test_collection_paste_waits_for_unfinished_datum(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QInputDialog

    import mycad.ui.geometric_tolerance_tools as tolerance_module
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    datum_prompts: list[bool] = []

    def datum_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        datum_prompts.append(True)
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", datum_name)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    definition = BlockDefinition(
        uuid4().hex, "PendingDatum", (LineEntity(uuid4().hex, (0, 0), (3, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    history = tuple(loaded.document.commands)
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    canvas.selected_block_instance_ids = {instance.instance_id}
    clipboard = QApplication.clipboard()
    try:
        assert canvas.copy_to_clipboard()
        tolerance = canvas.geometric_tolerance_tools
        assert tolerance is not None
        tolerance.begin_datum()
        assert tolerance.pending
        assert not canvas.begin_clipboard_paste()
        assert tolerance.pending and not canvas.clipboard_paste_active
        assert canvas.collection_session is None and tuple(loaded.document.commands) == history
        assert tolerance.cancel()
        assert canvas.begin_clipboard_paste()
        preview = canvas.collection_paste_preview
        for begin in (
            tolerance.begin_datum,
            tolerance.begin_mechanical_frame,
            tolerance.begin_mechanical_datum,
        ):
            begin()
            assert len(datum_prompts) == 1 and not tolerance.pending
            assert canvas.clipboard_paste_active and canvas.collection_paste_preview == preview

        def unexpected_dialog(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("公差对话框不应在粘贴期间打开")

        with monkeypatch.context() as guard:
            guard.setattr(tolerance_module, "GeometricToleranceDialog", unexpected_dialog)
            tolerance.begin_frame()
        assert not tolerance.pending and canvas.collection_paste_preview == preview
        canvas.add_coordinate_point((10, 0), exact_point=True)
        session = canvas.collection_session
        assert session is not None and len(session.snapshot.block_instances) == 2
        assert canvas.undo_last_operation() and session.snapshot.block_instances == (instance,)
    finally:
        clipboard.clear()
        editor.reject()


@pytest.mark.parametrize(
    "action", ["group", "ungroup", "group_edit", "explode", "create", "insert", "manage"]
)
def test_collection_menu_action_waits_for_unfinished_datum(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from PySide6.QtWidgets import QDialog, QInputDialog

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)

    def datum_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", datum_name)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    definition = BlockDefinition(
        uuid4().hex, "Pending", (LineEntity(uuid4().hex, (0, 0), (3, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    history = tuple(loaded.document.commands)
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    canvas.selected_block_instance_ids = {instance.instance_id}
    tolerance = canvas.geometric_tolerance_tools
    assert tolerance is not None
    tolerance.begin_datum()
    assert tolerance.pending
    canvas.selected_block_instance_ids = {instance.instance_id}
    actions = {
        "group": window.act_drawing_group,
        "ungroup": window.act_drawing_ungroup,
        "group_edit": window.act_drawing_group_edit,
        "explode": window.act_drawing_block_explode,
        "create": window.act_drawing_block_create,
        "insert": window.act_drawing_block_insert,
        "manage": window.act_drawing_block_manage,
    }
    dialogs: list[bool] = []

    def cancel_unexpected_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, QDialog):
            dialogs.append(True)
            dialog.reject()

    try:
        QTimer.singleShot(0, cancel_unexpected_dialog)
        actions[action].trigger()
        QApplication.processEvents()
        assert not dialogs
        assert tolerance.pending and canvas.collection_session is None
        assert tuple(loaded.document.commands) == history
        assert services.kernel.drawing_block_instances == (instance,)
        assert services.kernel.drawing_groups == ()
        assert "完成或取消" in editor.status_label.text()
        assert tolerance.cancel()
        if action in {"group", "explode"}:
            actions[action].trigger()
            session = canvas.collection_session
            assert session is not None
            if action == "group":
                assert len(session.snapshot.groups) == 1
            else:
                assert session.snapshot.block_instances == ()
            assert canvas.undo_last_operation() and session.snapshot.block_instances == (instance,)
            assert session.snapshot.groups == () and tuple(loaded.document.commands) == history
    finally:
        tolerance.cancel()
        editor.reject()


def test_group_menu_waits_for_unfinished_text(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    definition = BlockDefinition(
        uuid4().hex, "PendingText", (LineEntity(uuid4().hex, (0, 0), (3, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    history = tuple(loaded.document.commands)
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    text_tools = canvas.text_tools
    assert text_tools is not None and text_tools.begin("text")
    text_tools.place((5, 5))
    text_tools.editor.setPlainText("Unfinished")
    canvas.selected_block_instance_ids = {instance.instance_id}
    try:
        command = editor.drawing_command_bar.input
        command.setText("MOVE")
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert text_tools.pending and text_tools.editor.toPlainText() == "Unfinished"
        assert canvas.collection_session is None and canvas.active_transform is None
        editor.delta_u_field.setValue(10)
        editor.numeric_move_button.click()
        assert text_tools.pending and text_tools.editor.toPlainText() == "Unfinished"
        assert canvas.collection_session is None and tuple(loaded.document.commands) == history
        window.act_drawing_group.trigger()
        assert text_tools.pending and text_tools.editor.toPlainText() == "Unfinished"
        assert canvas.collection_session is None and tuple(loaded.document.commands) == history
        assert "完成或取消" in editor.status_label.text()
        assert text_tools.cancel()
        window.act_drawing_group.trigger()
        session = canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 1
        assert canvas.undo_last_operation() and not session.snapshot.groups
    finally:
        text_tools.cancel()
        editor.reject()


def test_group_empty_selection_hint_survives_cursor_and_clears_after_creation(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (3, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    history = tuple(loaded.document.commands)
    try:
        command.setText("GROUP")
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert "请先选择要编组的对象" in editor.status_label.text()
        canvas.cursor_changed.emit(1.0, 1.0, "")
        assert "请先选择要编组的对象" in editor.status_label.text()
        assert canvas.collection_session is None and tuple(loaded.document.commands) == history
        canvas.selected_entity_ids = {line.entity_id}
        command.setText("GROUP")
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert canvas.collection_session is not None
        assert "暂存匿名组" in editor.status_label.text()
        canvas.cursor_changed.emit(1.0, 1.0, "")
        assert "暂存匿名组" in editor.status_label.text()
    finally:
        editor.reject()


@pytest.mark.parametrize("confirm", ["canvas_enter", "input_enter", "right_click"])
def test_group_command_selects_objects_then_confirms(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, confirm: str
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    try:
        command.setText("GROUP")
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert "Enter" in editor.status_label.text()
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
        assert line.entity_id in canvas.selected_entity_ids
        assert "Enter" in editor.status_label.text()
        if confirm == "right_click":
            QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
        else:
            QTest.keyClick(canvas if confirm == "canvas_enter" else command, Qt.Key.Key_Return)
        assert canvas.collection_session is not None
        assert canvas.collection_session.snapshot.groups[0].members == (
            DrawingObjectRef("geometry", line.entity_id, editor.draft_sketch_id),
        )
    finally:
        editor.reject()


def test_group_selection_escape_cancels_without_creating_group(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    try:
        command.setText("GROUP")
        QTest.keyClick(command, Qt.Key.Key_Return)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
        QTest.keyClick(canvas, Qt.Key.Key_Return)
        assert canvas.collection_session is None
        assert line in canvas.entities
    finally:
        editor.reject()


def test_idle_right_click_repeats_group_command(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    command = editor.drawing_command_bar.input
    try:
        command.setText("GROUP")
        QTest.keyClick(command, Qt.Key.Key_Return)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
        QTest.keyClick(canvas, Qt.Key.Key_Return)
        assert canvas.collection_session is not None
        canvas.selected_entity_ids.clear()
        canvas.selected_geometry_refs.clear()
        QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
        assert "请先选择要编组的对象" in editor.drawing_command_bar.status.text()
        assert len(canvas.collection_session.snapshot.groups) == 1
    finally:
        editor.reject()


def test_group_command_selects_multiple_objects_with_control(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    lines = (
        LineEntity(uuid4().hex, (0, 0), (10, 0)),
        LineEntity(uuid4().hex, (0, 10), (10, 10)),
    )
    assert canvas.replace_draft_entities(lines)
    command = editor.drawing_command_bar.input
    try:
        command.setText("GROUP")
        QTest.keyClick(command, Qt.Key.Key_Return)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
        QTest.mouseClick(
            canvas,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ControlModifier,
            canvas.local_to_screen((5, 10)),
        )
        QTest.keyClick(canvas, Qt.Key.Key_Return)
        assert canvas.collection_session is not None
        assert {
            item.object_id for item in canvas.collection_session.snapshot.groups[0].members
        } == {line.entity_id for line in lines}
    finally:
        editor.reject()


@pytest.mark.parametrize("confirm", ["enter", "right_click"])
def test_group_confirmation_reports_result_and_suppresses_context_menu(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, confirm: str
) -> None:
    from PySide6.QtCore import QCoreApplication, QPoint
    from PySide6.QtGui import QContextMenuEvent

    context_checks: list[bool] = []
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas

    def check_context() -> bool:
        context_checks.append(True)
        return False

    monkeypatch.setattr(canvas, "supports_clipboard_context_menu", check_context)
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert canvas.replace_draft_entities((line,))
    command_bar = editor.drawing_command_bar
    try:
        command_bar.input.setText("GROUP")
        QTest.keyClick(command_bar.input, Qt.Key.Key_Return)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 0)))
        if confirm == "enter":
            QTest.keyClick(canvas, Qt.Key.Key_Return)
        else:
            QTest.mouseClick(canvas, Qt.MouseButton.RightButton)
            point = QPoint(30, 30)
            event = QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse, point, canvas.mapToGlobal(point)
            )
            QCoreApplication.sendEvent(canvas, event)
            assert not context_checks
            QCoreApplication.sendEvent(
                canvas,
                QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, canvas.mapToGlobal(point)),
            )
            assert len(context_checks) == 1
        assert canvas.collection_session is not None
        assert any("GROUP" in entry and "已" in entry for entry in command_bar.history)
        assert "GROUP" in command_bar.status.text()
    finally:
        editor.reject()


def test_numeric_move_applies_to_complete_draft_group(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0, 0), (3, 0))
    second = LineEntity(uuid4().hex, (0, 5), (3, 5))
    assert canvas.replace_draft_entities((first, second))
    canvas.selected_entity_ids = {first.entity_id, second.entity_id}
    try:
        window.act_drawing_group.trigger()
        session = canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 1
        history = tuple(loaded.document.commands)
        canvas.selected_entity_ids = {first.entity_id}
        editor.delta_u_field.setValue(10)
        editor.delta_v_field.setValue(2)
        editor.numeric_move_button.click()
        moved = {item.entity_id: item for item in canvas.entities}
        moved_first, moved_second = moved[first.entity_id], moved[second.entity_id]
        assert isinstance(moved_first, LineEntity) and isinstance(moved_second, LineEntity)
        assert moved_first.start_mm == (10, 2)
        assert moved_second.start_mm == (10, 7)
        assert tuple(loaded.document.commands) == history
        assert canvas.undo_last_operation()
        assert tuple(canvas.entities) == (first, second)
        assert canvas.redo_last_operation()
        assert {item.entity_id: item for item in canvas.entities} == moved
    finally:
        editor.reject()


def test_numeric_copy_does_not_expand_overlapping_groups_recursively(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.replay_proposal import ReplayAppend

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    canvas = editor.canvas
    lines = tuple(LineEntity(uuid4().hex, (0, y), (3, y)) for y in (0, 5, 10))
    assert canvas.replace_draft_entities(lines)
    canvas.selected_entity_ids = {lines[0].entity_id, lines[1].entity_id}
    try:
        window.act_drawing_group.trigger()
        session = canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 1
        first_group = session.snapshot.groups[0]
        overlap = DrawingGroup(
            uuid4().hex,
            tuple(
                DrawingObjectRef("geometry", line.entity_id, editor.draft_sketch_id)
                for line in lines[1:]
            ),
        )
        assert canvas.stage_collection_operation(
            ReplayAppend("drawing.group.create", 1, overlap.to_mapping(), "local")
        )
        before = session.snapshot
        canvas.selected_entity_ids = {lines[0].entity_id}
        editor.delta_u_field.setValue(10)
        editor.numeric_copy_button.click()
        after = session.snapshot
        copied = tuple(item for item in canvas.entities if isinstance(item, LineEntity))
        assert {line.start_mm for line in copied} == {(0, 0), (0, 5), (0, 10), (10, 0), (10, 5)}
        assert len(after.groups) == 3 and after.groups[:2] == (first_group, overlap)
        assert len(after.groups[2].members) == 2
        assert canvas.undo_last_operation() and session.snapshot == before
        assert canvas.redo_last_operation() and session.snapshot == after
        editor.finish_sketch()
        qtbot.waitUntil(
            lambda: not unit.is_busy and window.active_sketch_dialog() is not editor,
            timeout=10000,
        )
        path = tmp_path / "overlapping-numeric-copy.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert len(services.kernel.drawing_groups) == 3
        reopened.bus.undo_operation()
        assert services.kernel.drawing_groups == (first_group, overlap)
        reopened.bus.redo_operation()
        assert len(services.kernel.drawing_groups) == 3
    finally:
        if window.active_sketch_dialog() is editor:
            editor.reject()


def test_numeric_partial_copy_of_unselectable_group_stays_independent(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from mycad.core.replay_proposal import ReplayAppend

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    lines = tuple(LineEntity(uuid4().hex, (0, y), (3, y)) for y in (0, 5))
    assert canvas.replace_draft_entities(lines)
    canvas.selected_entity_ids = {line.entity_id for line in lines}
    try:
        window.act_drawing_group.trigger()
        session = canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 1
        group = replace(session.snapshot.groups[0], selectable=False)
        assert canvas.stage_collection_operation(
            ReplayAppend("drawing.group.update", 1, group.to_mapping(), "local")
        )
        before = session.snapshot
        history = tuple(loaded.document.commands)
        canvas.selected_entity_ids = {lines[0].entity_id}
        editor.delta_u_field.setValue(10)
        editor.numeric_copy_button.click()
        after = session.snapshot
        copied = tuple(item for item in canvas.entities if isinstance(item, LineEntity))
        assert {line.start_mm for line in copied} == {(0, 0), (0, 5), (10, 0)}
        assert after.groups == (group,) and tuple(loaded.document.commands) == history
        assert canvas.undo_last_operation() and session.snapshot == before
        assert canvas.redo_last_operation() and session.snapshot == after
    finally:
        editor.reject()


@pytest.mark.parametrize("operation", ["copy", "rotate", "mirror"])
def test_numeric_transform_applies_to_complete_draft_group(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0, 0), (3, 0))
    second = LineEntity(uuid4().hex, (0, 5), (3, 5))
    assert canvas.replace_draft_entities((first, second))
    canvas.selected_entity_ids = {first.entity_id, second.entity_id}
    try:
        window.act_drawing_group.trigger()
        session = canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 1
        original_group = session.snapshot.groups[0]
        history = tuple(loaded.document.commands)
        canvas.selected_entity_ids = {first.entity_id}
        editor.delta_u_field.setValue(10)
        editor.delta_v_field.setValue(2)
        editor.angle_field.setValue(90)
        editor.mirror_keep_source_check.setChecked(False)
        button = {
            "copy": editor.numeric_copy_button,
            "rotate": editor.numeric_rotate_button,
            "mirror": editor.numeric_mirror_button,
        }[operation]
        button.click()
        after = session.snapshot
        lines = tuple(item for item in canvas.entities if isinstance(item, LineEntity))
        if operation == "copy":
            assert len(lines) == 4 and len(after.groups) == 2
            assert {line.start_mm for line in lines} == {(0, 0), (0, 5), (10, 2), (10, 7)}
            assert after.groups[0] == original_group
            assert len(after.groups[1].members) == 2
        else:
            assert len(lines) == 2 and after.groups == (original_group,)
            transformed = {line.entity_id: line for line in lines}
            assert transformed[second.entity_id].start_mm == pytest.approx(
                (-5, 0) if operation == "rotate" else (0, -5)
            )
        assert tuple(loaded.document.commands) == history
        assert canvas.undo_last_operation()
        assert tuple(canvas.entities) == (first, second)
        assert session.snapshot.groups == (original_group,)
        assert canvas.redo_last_operation() and session.snapshot == after
    finally:
        editor.reject()


@pytest.mark.parametrize("operation", ["move", "copy", "rotate", "mirror"])
def test_numeric_move_group_from_datum_seed(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.geometric_tolerance import DatumIdentifier
    from mycad.core.sketch import WorkPlaneFrame

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (3, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=int(getattr(window, _SESSION_FIELD))
    )
    datum = DatumIdentifier(uuid4().hex, "A", (4, 4), (0, 0))
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("datum", datum.datum_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    tools = canvas.geometric_tolerance_tools
    assert tools is not None
    tools.selected_ids = {datum.datum_id}
    tools.selected_id = datum.datum_id
    tools.selected_kind = "datum"
    try:
        editor.delta_u_field.setValue(10)
        editor.delta_v_field.setValue(2)
        editor.angle_field.setValue(90)
        editor.mirror_keep_source_check.setChecked(False)
        {
            "move": editor.numeric_move_button,
            "copy": editor.numeric_copy_button,
            "rotate": editor.numeric_rotate_button,
            "mirror": editor.numeric_mirror_button,
        }[operation].click()
        session = canvas.collection_session
        assert session is not None
        if operation in {"rotate", "mirror"}:
            assert session.snapshot.datums == (datum,)
            assert session.snapshot.groups == (group,)
            assert "不支持" in canvas.message
            return
        if operation == "copy":
            assert len(session.snapshot.groups) == 2
            assert len(session.snapshot.datums) == 2
            assert session.snapshot.datums[1].position_mm == (14, 6)
        else:
            assert session.snapshot.datums[0].position_mm == (14, 6)
            result = next(
                item for item in session.snapshot.sketches if item.sketch_id == sketch.sketch_id
            )
            moved = result.entities[0]
            assert isinstance(moved, LineEntity)
            assert moved.start_mm == (10, 2)
        assert canvas.undo_last_operation()
        assert session.snapshot.datums == (datum,)
        assert session.snapshot.groups == (group,)
    finally:
        editor.reject()


@pytest.mark.parametrize("restriction", ["locked", "hidden", "frozen"])
@pytest.mark.parametrize("operation", ["move", "copy", "rotate"])
def test_numeric_group_move_rejects_locked_block_member(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, restriction: str, operation: str
) -> None:
    from dataclasses import replace

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.drawing_text import DrawingText
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("Inner"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    definition = BlockDefinition(
        uuid4().hex,
        "LockedMember",
        (LineEntity(uuid4().hex, (0, 0), (3, 0), layer_name="Inner"),),
        (),
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    text = DrawingText(uuid4().hex, "Label", (2, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("text", text.text_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    source_layer = layers.get("Inner")
    restricted = (
        replace(source_layer, visible=False)
        if restriction == "hidden"
        else replace(source_layer, frozen=True)
        if restriction == "frozen"
        else replace(source_layer, locked=True)
    )
    locked = layers.replace(restricted)
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    history = tuple(loaded.document.commands)
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    text_tools = canvas.text_tools
    assert text_tools is not None
    text_tools.selected_ids = {text.text_id}
    try:
        editor.delta_u_field.setValue(10)
        editor.angle_field.setValue(30)
        {
            "move": editor.numeric_move_button,
            "copy": editor.numeric_copy_button,
            "rotate": editor.numeric_rotate_button,
        }[operation].click()
        session = canvas.collection_session
        assert session is not None
        assert session.snapshot.texts == (text,) and session.snapshot.block_instances == (instance,)
        assert session.snapshot.groups == (group,) and tuple(loaded.document.commands) == history
        assert any(word in editor.status_label.text() for word in ("锁定", "隐藏", "冻结"))
        canvas.cursor_changed.emit(1.0, 1.0, "")
        assert any(word in editor.status_label.text() for word in ("锁定", "隐藏", "冻结"))
    finally:
        editor.reject()


def test_numeric_group_move_translates_attached_datum_and_block_once(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dataclasses import replace

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.geometric_tolerance import DatumAttachment, DatumIdentifier
    from mycad.core.sketch import WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchGeometryReference

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    app.commit_new_sketch(
        services, loaded, sketch, session_identity=int(getattr(window, _SESSION_FIELD))
    )
    definition = BlockDefinition(
        uuid4().hex, "AttachedNumeric", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    datum = DatumIdentifier(
        uuid4().hex,
        "A",
        (4, 4),
        (0, 0),
        attachment=DatumAttachment(
            sketch.sketch_id, SketchGeometryReference(line.entity_id, "start")
        ),
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute("drawing.tolerance.batch", {"add_datums": [datum.to_mapping()]}, "local")
    group = DrawingGroup(
        uuid4().hex,
        (
            DrawingObjectRef("geometry", line.entity_id, sketch.sketch_id),
            DrawingObjectRef("datum", datum.datum_id),
            DrawingObjectRef("block_instance", instance.instance_id),
        ),
    )
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    history = tuple(loaded.document.commands)
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    canvas.selected_entity_ids = {line.entity_id}
    try:
        editor.delta_u_field.setValue(2)
        editor.delta_v_field.setValue(3)
        editor.numeric_move_button.click()
        session = canvas.collection_session
        assert session is not None
        after = session.snapshot
        moved_line = next(item for item in after.sketches if item.sketch_id == sketch.sketch_id)
        moved_entity = moved_line.entities[0]
        assert isinstance(moved_entity, LineEntity) and moved_entity.start_mm == (2, 3)
        assert after.datums[0].target_mm == (2, 3)
        assert after.datums[0].position_mm == (6, 7)
        assert after.datums[0].attachment == datum.attachment
        assert after.block_instances[0].insertion_mm == (7, 8)
        assert after.groups == (group,) and tuple(loaded.document.commands) == history
        assert canvas.undo_last_operation()
        undone = replace(
            session.snapshot,
            sketches=tuple(
                item
                for item in session.snapshot.sketches
                if item.sketch_id != editor.draft_sketch_id
            ),
        )
        assert undone == before
        assert canvas.redo_last_operation() and session.snapshot == after
        committed_after = replace(
            after,
            sketches=tuple(
                item for item in after.sketches if item.sketch_id != editor.draft_sketch_id
            ),
        )
        editor.finish_sketch()
        qtbot.waitUntil(
            lambda: not unit.is_busy and window.active_sketch_dialog() is not editor,
            timeout=10000,
        )
        path = tmp_path / "numeric-attached.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert app.drawing_collection_snapshot(services) == committed_after
        reopened.bus.undo_operation()
        assert app.drawing_collection_snapshot(services) == before
        reopened.bus.redo_operation()
        assert app.drawing_collection_snapshot(services) == committed_after
    finally:
        if window.active_sketch_dialog() is editor:
            editor.reject()


def test_numeric_move_mixed_block_group_reopens_as_one_step(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    definition = BlockDefinition(
        uuid4().hex, "NumericMixed", (LineEntity(uuid4().hex, (0, 0), (3, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 5))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    line = LineEntity(uuid4().hex, (0, 0), (3, 0))
    assert canvas.replace_draft_entities((line,))
    canvas.selected_entity_ids = {line.entity_id}
    canvas.selected_block_instance_ids = {instance.instance_id}
    try:
        window.act_drawing_group.trigger()
        session = canvas.collection_session
        assert session is not None and len(session.snapshot.groups) == 1
        before = session.snapshot
        canvas.selected_block_instance_ids.clear()
        canvas.selected_entity_ids = {line.entity_id}
        editor.delta_u_field.setValue(10)
        editor.delta_v_field.setValue(2)
        editor.numeric_move_button.click()
        after = session.snapshot
        assert after.block_instances[0].insertion_mm == (10, 7)
        moved = next(item for item in canvas.entities if item.entity_id == line.entity_id)
        assert isinstance(moved, LineEntity) and moved.start_mm == (10, 2)
        assert canvas.undo_last_operation() and session.snapshot == before
        assert canvas.redo_last_operation() and session.snapshot == after
        editor.finish_sketch()
        qtbot.waitUntil(
            lambda: not unit.is_busy and window.active_sketch_dialog() is not editor,
            timeout=10000,
        )
        path = tmp_path / "numeric-mixed.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert services.kernel.drawing_block_instances[0].insertion_mm == (10, 7)
        assert any(moved in item.entities for item in services.kernel.sketches)
        assert services.kernel.drawing_groups == after.groups
        reopened.bus.undo_operation()
        assert services.kernel.drawing_block_instances == (instance,)
        assert any(line in item.entities for item in services.kernel.sketches)
        assert services.kernel.drawing_groups == before.groups
        reopened.bus.redo_operation()
        assert services.kernel.drawing_block_instances[0].insertion_mm == (10, 7)
        assert any(moved in item.entities for item in services.kernel.sketches)
        assert services.kernel.drawing_groups == after.groups
    finally:
        if window.active_sketch_dialog() is editor:
            editor.reject()


def test_offset_waits_for_unfinished_datum(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QInputDialog

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)

    def datum_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", datum_name)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    line = LineEntity(uuid4().hex, (0, 0), (3, 0))
    assert canvas.replace_draft_entities((line,))
    history = tuple(loaded.document.commands)
    tolerance = canvas.geometric_tolerance_tools
    assert tolerance is not None
    command = editor.drawing_command_bar.input
    try:
        tolerance.begin_datum()
        assert tolerance.pending
        canvas.selected_entity_ids = {line.entity_id}
        command.setText("OFFSET")
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert tolerance.pending and canvas.active_transform is None
        assert canvas.selected_entity_ids == {line.entity_id}
        assert canvas.collection_session is None and tuple(loaded.document.commands) == history
        assert "完成或取消" in canvas.message
        assert tolerance.cancel()
        command.setText("OFFSET")
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert canvas.active_transform == "offset"
        canvas.cancel_transform()
    finally:
        tolerance.cancel()
        editor.reject()


@pytest.mark.parametrize("operation", ["MOVE", "COPY", "ROTATE", "SCALE"])
def test_block_transform_waits_for_unfinished_datum(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from PySide6.QtWidgets import QInputDialog

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)

    def datum_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", datum_name)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    definition = BlockDefinition(
        uuid4().hex, "PendingTransform", (LineEntity(uuid4().hex, (0, 0), (3, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    history = tuple(loaded.document.commands)
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    tolerance = canvas.geometric_tolerance_tools
    assert tolerance is not None
    command = editor.drawing_command_bar.input
    try:
        tolerance.begin_datum()
        assert tolerance.pending
        canvas.selected_block_instance_ids = {instance.instance_id}
        command.setText(operation)
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert tolerance.pending and canvas.collection_session is None
        assert canvas.active_transform is None and tuple(loaded.document.commands) == history
        assert "完成或取消" in canvas.message
        assert tolerance.cancel()
        command.setText(operation)
        QTest.keyClick(command, Qt.Key.Key_Return)
        assert canvas.active_transform == operation.lower()
        canvas.cancel_transform()
    finally:
        tolerance.cancel()
        editor.reject()


@pytest.mark.parametrize("annotation", ["datum", "frame"])
def test_delete_block_waits_for_unfinished_datum(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, annotation: str
) -> None:
    from PySide6.QtWidgets import QInputDialog

    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)

    def datum_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", datum_name)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    definition = BlockDefinition(
        uuid4().hex, "DatumDelete", (LineEntity(uuid4().hex, (0, 0), (3, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    history = tuple(loaded.document.commands)
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    tolerance = canvas.geometric_tolerance_tools
    assert tolerance is not None
    try:
        if annotation == "datum":
            tolerance.begin_datum()
        else:
            tolerance.begin_mechanical_frame()
        assert tolerance.pending
        canvas.selected_block_instance_ids = {instance.instance_id}
        QTest.keyClick(canvas, Qt.Key.Key_Delete)
        assert tolerance.pending and canvas.collection_session is None
        assert tuple(loaded.document.commands) == history
        assert services.kernel.drawing_block_instances == (instance,)
        assert "完成或取消" in canvas.message
        assert tolerance.cancel()
        QTest.keyClick(canvas, Qt.Key.Key_Delete)
        session = canvas.collection_session
        assert session is not None and not session.snapshot.block_instances
        assert canvas.undo_last_operation() and session.snapshot.block_instances == (instance,)
    finally:
        tolerance.cancel()
        editor.reject()


@pytest.mark.parametrize("annotation", ["datum", "frame"])
def test_picture_context_menu_waits_for_unfinished_datum(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, annotation: str
) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QInputDialog, QMenu

    from mycad.core.drawing_raster import DrawingRaster

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard)

    def datum_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "A", True

    def coordinate(*_args: object, **_kwargs: object) -> tuple[float, bool]:
        return 10.0, True

    monkeypatch.setattr(QInputDialog, "getText", datum_name)
    monkeypatch.setattr(QInputDialog, "getDouble", coordinate)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    picture = DrawingRaster(
        uuid4().hex,
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
        "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
        (2, 2),
        2,
        2,
    )
    loaded.bus.execute("drawing.raster.add", picture.to_mapping(version=2), "local", version=3)
    history = tuple(loaded.document.commands)
    getattr(window, _SYNC_METHOD)()
    canvas = editor.canvas
    canvas.set_source_context_revision(loaded.document.revision)
    tolerance = canvas.geometric_tolerance_tools
    assert tolerance is not None
    shown: list[str] = []

    def choose_move() -> None:
        popup = QApplication.activePopupWidget()
        if not isinstance(popup, QMenu):
            return
        shown.append("menu")
        action = next(item for item in popup.actions() if item.text() == "移动图片")
        QTest.mouseClick(
            popup, Qt.MouseButton.LeftButton, pos=popup.actionGeometry(action).center()
        )

    try:
        if annotation == "datum":
            tolerance.begin_datum()
        else:
            tolerance.begin_mechanical_frame()
        assert tolerance.pending
        canvas.selected_raster_ids = {picture.image_id}
        canvas.selected_raster_id = picture.image_id
        QTimer.singleShot(0, choose_move)
        canvas.contextMenuEvent(
            QContextMenuEvent(QContextMenuEvent.Reason.Keyboard, QPoint(20, 20), QPoint(20, 20))
        )
        QApplication.processEvents()
        assert not shown and tolerance.pending
        assert canvas.collection_session is None and tuple(loaded.document.commands) == history
        assert services.kernel.drawing_rasters == (picture,)
        assert tolerance.cancel()
        QTimer.singleShot(0, choose_move)
        canvas.contextMenuEvent(
            QContextMenuEvent(QContextMenuEvent.Reason.Keyboard, QPoint(20, 20), QPoint(20, 20))
        )
        assert shown == ["menu"]
        assert services.kernel.drawing_rasters[0].origin_mm == (10, 10)
        loaded.bus.undo_operation()
        assert services.kernel.drawing_rasters == (picture,)
    finally:
        tolerance.cancel()
        editor.reject()


def test_cross_document_group_paste_previews_shared_block_instances(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
    from mycad.core.drawing_groups import DrawingGroup
    from mycad.core.drawing_text import DrawingText, TextStyle, TextStyleTable

    monkeypatch.setattr(QMessageBox, "question", _discard)
    services = app.build_app(discoverers=[])
    source_window = MainWindow(services=services)
    monkeypatch.setattr(type(source_window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(source_window)
    source_window.show()
    source_window.act_new_drawing.trigger()
    source_editor, source = source_window.active_sketch_dialog(), source_window.loaded_document()
    assert source_editor is not None and source is not None
    styles = TextStyleTable((TextStyle(height_mm=7),), "standard")
    source.bus.execute("drawing.text_styles.set", styles.to_mapping(), "local")
    text = DrawingText(uuid4().hex, "Shared", (1, 1))
    definition = BlockDefinition(
        uuid4().hex, "Shared", (LineEntity(uuid4().hex, (0, 0), (4, 0)),), (text,)
    )
    first = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    second = BlockInstance(uuid4().hex, definition.definition_id, (12, 0), 90, 2)
    source.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for instance in (first, second):
        source.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    group = DrawingGroup(
        uuid4().hex,
        tuple(DrawingObjectRef("block_instance", item.instance_id) for item in (first, second)),
        name="SharedInstances",
    )
    source.bus.execute("drawing.group.create", group.to_mapping(), "local")
    getattr(source_window, _SYNC_METHOD)()
    source_editor.canvas.set_source_context_revision(source.document.revision)
    source_editor.canvas.selected_block_instance_ids = {first.instance_id}
    clipboard = QApplication.clipboard()
    try:
        assert source_editor.canvas.copy_to_clipboard()
        target_services = app.build_app(discoverers=[])
        target_window = MainWindow(services=target_services)
        monkeypatch.setattr(type(target_window.viewport), "paintGL", _skip_gl)
        qtbot.addWidget(target_window)
        target_window.show()
        target_window.act_new_drawing.trigger()
        editor, loaded = target_window.active_sketch_dialog(), target_window.loaded_document()
        unit = target_window.execution_unit
        assert editor is not None and loaded is not None and unit is not None
        conflict = BlockDefinition(
            uuid4().hex, "Shared", (LineEntity(uuid4().hex, (0, 0), (9, 0)),), ()
        )
        loaded.bus.execute("drawing.block.create", conflict.to_mapping(), "local")
        getattr(target_window, _SYNC_METHOD)()
        editor.canvas.set_source_context_revision(loaded.document.revision)
        history = tuple(loaded.document.commands)
        assert editor.canvas.begin_clipboard_paste()
        monkeypatch.setattr(editor.canvas, "_cursor", (20.0, 10.0))
        editor.canvas.grab()
        preview = editor.canvas.collection_paste_preview
        assert preview is not None
        assert len(preview.payload.sketches) == 2 and len(preview.payload.texts) == 2
        preview_ids = {item.sketch_id for item in preview.payload.sketches}
        assert len(preview_ids) == 2
        editor.canvas.add_coordinate_point((20, 10), exact_point=True)
        session = editor.canvas.collection_session
        assert session is not None
        assert {item.instance_id for item in session.snapshot.block_instances} == preview_ids
        assert len(session.snapshot.block_definitions) == 2
        copied = session.snapshot.block_definitions[-1]
        assert copied.name == "Shared 副本"
        assert all(
            item.definition_id == copied.definition_id for item in session.snapshot.block_instances
        )
        assert session.snapshot.text_styles.get(copied.texts[0].style_id).height_mm == 7
        assert set(session.snapshot.groups[0].members) == {
            DrawingObjectRef("block_instance", item) for item in preview_ids
        }
        assert tuple(loaded.document.commands) == history
        assert editor.canvas.undo_last_operation() and not session.snapshot.block_instances
        assert editor.canvas.redo_last_operation()
        editor.finish_sketch()
        qtbot.waitUntil(
            lambda: not unit.is_busy and target_window.active_sketch_dialog() is not editor,
            timeout=10000,
        )
        path = tmp_path / "cross-document-shared.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(target_services, path)
        assert {
            item.instance_id for item in target_services.kernel.drawing_block_instances
        } == preview_ids
        reopened.bus.undo_operation()
        assert not target_services.kernel.drawing_block_instances
        reopened.bus.redo_operation()
        assert {
            item.instance_id for item in target_services.kernel.drawing_block_instances
        } == preview_ids
    finally:
        clipboard.clear()


@pytest.mark.parametrize("cancel_draft", [False, True])
def test_group_copy_block_edit_explode_from_user_commands(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cancel_draft: bool
) -> None:
    services = app.build_app(discoverers=[])
    monkeypatch.setattr(QMessageBox, "question", _discard)
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    first = LineEntity(uuid4().hex, (0, 0), (8, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (first,))
    app.commit_new_sketch(
        services, loaded, saved, session_identity=int(getattr(window, _SESSION_FIELD))
    )
    getattr(window, _SYNC_METHOD)()
    second = LineEntity(uuid4().hex, (0, 10), (8, 10))
    assert editor.canvas.replace_draft_entities((second,))
    assert editor.canvas.set_tool("选择元素")
    for y, modifiers in (
        (0, Qt.KeyboardModifier.NoModifier),
        (10, Qt.KeyboardModifier.ControlModifier),
    ):
        QTest.mouseClick(
            editor.canvas,
            Qt.MouseButton.LeftButton,
            modifiers,
            editor.canvas.local_to_screen((4, y)),
        )

    def command(text: str) -> None:
        assert editor is not None
        editor.drawing_command_bar.input.setText(text)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)

    original_history = tuple(loaded.document.commands)
    command("GROUP")
    session = editor.canvas.collection_session
    assert session is not None and len(session.snapshot.groups) == 1
    original_group = session.snapshot.groups[0]
    assert len(original_group.members) == 2
    command("COPY")
    editor.canvas.add_coordinate_point((0, 0), exact_point=True)
    editor.canvas.add_coordinate_point((20, 0), exact_point=True)
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Escape)
    assert len(session.snapshot.groups) == 2
    copied_state = session.snapshot
    assert editor.canvas.set_tool("选择元素")
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((4, 0))
    )

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("Workflow")
        dialog.accept()

    QTimer.singleShot(0, create)
    command("BLOCK")
    assert len(session.snapshot.block_definitions) == 1, editor.canvas.message
    assert len(session.snapshot.block_instances) == 1
    first_instance = session.snapshot.block_instances[0]
    assert session.snapshot.groups[0].members == (
        DrawingObjectRef("block_instance", first_instance.instance_id),
    )

    def insert() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockInsertDialog)
        dialog.x_field.setValue(40)
        dialog.rotation_field.setValue(90)
        dialog.scale_field.setValue(2)
        dialog.accept()

    QTimer.singleShot(0, insert)
    command("INSERT")
    assert len(session.snapshot.block_instances) == 2
    inserted_state = session.snapshot
    second_instance = inserted_state.block_instances[-1]
    assert tuple(loaded.document.commands) == original_history
    assert editor.canvas.undo_last_operation() and len(session.snapshot.block_instances) == 1
    assert editor.canvas.undo_last_operation() and session.snapshot == copied_state
    assert editor.canvas.redo_last_operation() and editor.canvas.redo_last_operation()
    assert session.snapshot == inserted_state
    editor.canvas.selected_block_instance_ids = {first_instance.instance_id}
    command("BEDIT")
    assert window.active_block_editor() is None
    assert "草稿" in editor.status_label.text()
    if cancel_draft:
        editor.reject()
        assert tuple(loaded.document.commands) == original_history
        assert services.kernel.sketches == (saved,)
        assert services.kernel.drawing_groups == ()
        assert services.kernel.drawing_block_definitions == ()
        assert services.kernel.drawing_block_instances == ()
        return
    editor.finish_sketch()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
    )
    editor = window.active_sketch_dialog()
    assert editor is not None
    editor.canvas.selected_block_instance_ids = {first_instance.instance_id}
    command("BEDIT")
    block_editor = window.active_block_editor()
    assert block_editor is not None
    block_editor.tool_buttons["直线"].click()
    block_editor.canvas.add_coordinate_point((0, 5), exact_point=True)
    block_editor.canvas.add_coordinate_point((5, 5), exact_point=True)
    if block_editor.canvas.has_pending_geometry:
        QTest.keyClick(block_editor.canvas, Qt.Key.Key_Escape)
    block_editor.command_input.setText("BSAVE")
    QTest.keyClick(block_editor.command_input, Qt.Key.Key_Return)
    assert len(services.kernel.drawing_block_definitions[0].entities) == 3
    view = editor.canvas.drawing_block_view()
    first_view = [
        item.entity for item in view.geometry if item.instance_id == first_instance.instance_id
    ]
    second_view = [
        item.entity for item in view.geometry if item.instance_id == second_instance.instance_id
    ]
    assert len(first_view) == len(second_view) == 3
    assert any(
        isinstance(item, LineEntity)
        and item.start_mm == pytest.approx((0, 5))
        and item.end_mm == pytest.approx((5, 5))
        for item in first_view
    )
    assert any(
        isinstance(item, LineEntity)
        and item.start_mm == pytest.approx((30, 0))
        and item.end_mm == pytest.approx((30, 10))
        for item in second_view
    )
    block_editor.command_input.setText("BCLOSE")
    QTest.keyClick(block_editor.command_input, Qt.Key.Key_Return)
    assert window.active_block_editor() is None
    editor.canvas.selected_block_instance_ids = {first_instance.instance_id}
    command("EXPLODE")
    explode_session = editor.canvas.collection_session
    assert explode_session is not None, editor.canvas.message
    assert len(explode_session.snapshot.block_instances) == 1
    assert len(explode_session.snapshot.groups[0].members) == 3
    assert (
        editor.canvas.undo_last_operation() and len(explode_session.snapshot.block_instances) == 2
    )
    assert (
        editor.canvas.redo_last_operation() and len(explode_session.snapshot.block_instances) == 1
    )
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=10000
    )
    path = tmp_path / "group-block-workflow.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    assert len(services.kernel.drawing_block_instances) == 1
    reopened.bus.undo_operation()
    assert len(services.kernel.drawing_block_instances) == 2
    reopened.bus.undo_operation()
    assert len(services.kernel.drawing_block_definitions[0].entities) == 2
    reopened.bus.undo_operation()
    assert len(services.kernel.drawing_block_instances) == 1
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == ()
    assert len(services.kernel.drawing_groups) == 2
    reopened.bus.undo_operation()
    assert len(services.kernel.drawing_groups) == 1
    reopened.bus.undo_operation()
    assert services.kernel.drawing_groups == ()
    for _ in range(6):
        reopened.bus.redo_operation()
    assert len(services.kernel.drawing_block_instances) == 1
    assert len(services.kernel.drawing_block_definitions[0].entities) == 3
    assert len(services.kernel.drawing_groups[0].members) == 3
