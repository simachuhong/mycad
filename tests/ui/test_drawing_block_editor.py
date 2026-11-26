# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Block editing operates on one isolated geometry and text timeline."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.drawing_blocks import BlockDefinition, BlockInstance
from mycad.core.drawing_text import DrawingText
from mycad.core.sketch import LineEntity
from mycad.ui.drawing_block_editor import DrawingBlockEditorDialog, DrawingBlockEditorSession

_SESSION_FIELD = "_session_id"
_SYNC_METHOD = "_sync_drawing_layers"


def _skip_gl(*_args: object, **_kwargs: object) -> None:
    pass


def _cancel_close(*_args: object, **_kwargs: object) -> object:
    from PySide6.QtWidgets import QMessageBox

    return QMessageBox.StandardButton.Cancel


def _discard_close(*_args: object, **_kwargs: object) -> object:
    from PySide6.QtWidgets import QMessageBox

    return QMessageBox.StandardButton.Discard


@pytest.mark.parametrize("same_content", [False, True])
def test_cross_document_block_edit_updates_only_destination_definition(
    tmp_path: Path, same_content: bool
) -> None:
    from mycad.core.drawing_collection_clipboard import (
        capture_collection_clipboard,
        prepare_collection_paste,
    )
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    source = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Shared", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (5, 5))
    group = DrawingGroup(uuid4().hex, (DrawingObjectRef("block_instance", instance.instance_id),))
    source.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    source.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    source.bus.execute("drawing.group.create", group.to_mapping(), "local")
    source_state = app.drawing_collection_snapshot(services)
    payload = capture_collection_clipboard(source_state, group.members)
    source_path = tmp_path / "source.my2d"
    save_document(source.document, source_path)

    target = app.new_workspace_document(services, kind="sketch")
    target_definition = (
        definition
        if same_content
        else replace(definition, entities=(replace(line, end_mm=(4, 0)),))
    )
    target_instance = BlockInstance(uuid4().hex, target_definition.definition_id, (0, 0))
    target.bus.execute("drawing.block.create", target_definition.to_mapping(), "local")
    target.bus.execute("drawing.block_instance.insert", target_instance.to_mapping(), "local")
    operation = prepare_collection_paste(payload, app.drawing_collection_snapshot(services), (8, 0))
    target.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    before_edit = app.drawing_collection_snapshot(services)
    copied_instance = before_edit.block_instances[-1]
    assert (copied_instance.definition_id == target_definition.definition_id) is same_content
    current = [True]
    editor = DrawingBlockEditorSession(
        services, target, copied_instance.definition_id, is_current_document=lambda: current[0]
    )
    edit_line = editor.entities[0]
    assert isinstance(edit_line, LineEntity)
    editor.set_members((replace(edit_line, end_mm=(7, 0)),), ())
    editor.save()
    after_edit = app.drawing_collection_snapshot(services)
    edited = next(
        item
        for item in after_edit.block_definitions
        if item.definition_id == copied_instance.definition_id
    )
    edited_line = edited.entities[0]
    assert isinstance(edited_line, LineEntity) and edited_line.end_mm == (7, 0)
    if not same_content:
        assert target_definition in after_edit.block_definitions
    else:
        assert all(
            item.definition_id == edited.definition_id for item in after_edit.block_instances
        )
    target_path = tmp_path / "target.my2d"
    save_document(target.document, target_path)
    reopened_target = app.open_app_document(services, target_path)
    reopened_target.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before_edit
    reopened_target.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after_edit

    current[0] = False
    app.open_app_document(services, source_path)
    assert app.drawing_collection_snapshot(services) == source_state
    editor.set_members((replace(edit_line, end_mm=(9, 0)),), ())
    with pytest.raises(ValidationError, match="过期"):
        editor.save()
    assert editor.dirty and app.drawing_collection_snapshot(services) == source_state


def test_mixed_move_preview_is_isolated_and_cancelled(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    text = DrawingText(uuid4().hex, "Text", (0, 3))
    definition = BlockDefinition(uuid4().hex, "Preview", (line,), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.canvas.selected_entity_ids = {line.entity_id}
    dialog.text_tools.selected_ids = {text.text_id}
    history = tuple(loaded.document.commands)
    dialog.canvas.begin_transform("move")
    dialog.canvas.add_coordinate_point((0, 0), exact_point=True)
    QTest.keyPress(dialog.canvas, Qt.Key.Key_Shift)
    QTest.mouseMove(dialog.canvas, dialog.canvas.local_to_screen((4, 5)))
    QTest.keyRelease(dialog.canvas, Qt.Key.Key_Shift)
    assert dialog.canvas.transform_preview_entities == (
        replace(line, start_mm=(4, 5), end_mm=(6, 5)),
    )
    assert dialog.canvas.mixed_transform_preview_texts == (replace(text, position_mm=(4, 8)),)
    assert session.entities == (line,) and session.texts == (text,)
    assert tuple(loaded.document.commands) == history
    dialog.canvas.cancel_transform()
    assert dialog.canvas.transform_preview_entities == ()
    assert dialog.canvas.mixed_transform_preview_texts == ()


@pytest.mark.parametrize(
    ("operation", "target", "expected_end", "expected_text"),
    (
        ("copy", (4, 5), (6, 5), (4, 8)),
        ("rotate", (0, 10), (0, 2), (-3, 0)),
        ("scale", (2, 0), (4, 0), (0, 6)),
        ("mirror", (10, 0), (2, 0), (0, -3)),
    ),
)
def test_mixed_transform_preview_matches_commit(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    target: tuple[float, float],
    expected_end: tuple[float, float],
    expected_text: tuple[float, float],
) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication, QMessageBox

    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    text = DrawingText(uuid4().hex, "Text", (0, 3))
    definition = BlockDefinition(uuid4().hex, "Preview", (line,), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.canvas.selected_entity_ids = {line.entity_id}
    dialog.text_tools.selected_ids = {text.text_id}
    dialog.canvas.begin_transform(operation)
    dialog.canvas.add_coordinate_point((0, 0), exact_point=True)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(dialog.canvas.local_to_screen(target)),
        QPointF(dialog.canvas.mapToGlobal(dialog.canvas.local_to_screen(target))),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ShiftModifier,
    )
    QApplication.sendEvent(dialog.canvas, event)
    preview_line = dialog.canvas.transform_preview_entities[0]
    assert isinstance(preview_line, LineEntity)
    preview_text = dialog.canvas.mixed_transform_preview_texts[0]
    assert preview_line.end_mm == pytest.approx(expected_end)
    assert preview_text.position_mm == pytest.approx(expected_text)
    dialog.canvas.add_coordinate_point(target, exact_point=True)
    result_line, result_text = session.entities[-1], session.texts[-1]
    assert isinstance(result_line, LineEntity)
    assert result_line.end_mm == pytest.approx(preview_line.end_mm)
    assert result_text.position_mm == pytest.approx(preview_text.position_mm)
    assert result_text.rotation_deg == pytest.approx(preview_text.rotation_deg)
    assert result_text.height_mm == preview_text.height_mm
    assert dialog.canvas.transform_preview_entities == ()
    assert dialog.canvas.mixed_transform_preview_texts == ()
    assert dialog.undo_local() and session.entities == (line,) and session.texts == (text,)


@pytest.mark.parametrize("operation", ("rotate", "scale"))
def test_mixed_reference_preview_matches_commit(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication, QMessageBox

    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    text = DrawingText(uuid4().hex, "Text", (0, 3))
    definition = BlockDefinition(uuid4().hex, "Reference", (line,), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    canvas.selected_entity_ids = {line.entity_id}
    dialog.text_tools.selected_ids = {text.text_id}
    canvas.begin_transform(operation)
    canvas.add_coordinate_point((0, 0), exact_point=True)
    if operation == "rotate":
        assert canvas.start_rotation_reference()
        canvas.set_rotation_reference_angle(0)
        assert canvas.start_rotation_target_points()
        target = (5.0, 9.0)
        expected_end, expected_text = (0, 2), (-3, 0)
    else:
        assert canvas.start_scale_reference()
        assert canvas.apply_scale_length(2)
        assert canvas.start_scale_target_points()
        target = (9.0, 5.0)
        expected_end, expected_text = (4, 0), (0, 6)
    canvas.add_coordinate_point((5, 5), exact_point=True)
    point = canvas.local_to_screen(target)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(point),
        QPointF(canvas.mapToGlobal(point)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ShiftModifier,
    )
    QApplication.sendEvent(canvas, event)
    preview_line = canvas.transform_preview_entities[0]
    assert isinstance(preview_line, LineEntity)
    assert preview_line.end_mm == pytest.approx(expected_end)
    assert canvas.mixed_transform_preview_texts[0].position_mm == pytest.approx(expected_text)
    assert session.entities == (line,) and session.texts == (text,)
    same_point = canvas.local_to_screen((5, 5))
    invalid = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(same_point),
        QPointF(canvas.mapToGlobal(same_point)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ShiftModifier,
    )
    QApplication.sendEvent(canvas, invalid)
    assert canvas.transform_preview_entities == ()
    assert canvas.mixed_transform_preview_texts == ()
    QApplication.sendEvent(canvas, event)
    assert canvas.mixed_transform_preview_texts[0].position_mm == pytest.approx(expected_text)
    canvas.add_coordinate_point(target, exact_point=True)
    assert session.entities[0] == preview_line
    assert session.texts[0].position_mm == pytest.approx(expected_text)
    assert canvas.mixed_transform_preview_texts == ()
    assert dialog.undo_local() and session.entities == (line,) and session.texts == (text,)


def test_block_editor_pastes_text_style_locally_and_saves_atomically(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from collections.abc import Callable, Mapping
    from typing import cast

    from PySide6.QtCore import QMimeData, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    from mycad.core.drawing_blocks import expand_block
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.persistence import save_document
    from mycad.ui.drawing_text_tools import TEXT_CLIPBOARD_MIME

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "PasteStyle", (line,), ())
    instances = tuple(BlockInstance(uuid4().hex, definition.definition_id, (x, 0)) for x in (1, 9))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for instance in instances:
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    original_styles = services.kernel.drawing_text_styles
    original_commands = loaded.document.commands
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(session, services.kernel.drawing_layers, original_styles)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    qtbot.addWidget(dialog)
    dialog.show()
    foreign = TextStyle(style_id="standard", name="标准", height_mm=8)
    text = DrawingText(uuid4().hex, "Foreign", (0, 0), style_id=foreign.style_id)
    data = {
        "format": "mycad-text",
        "version": 1,
        "texts": [text.to_mapping()],
        "styles": TextStyleTable((foreign,), foreign.style_id).to_mapping(),
        "sketch": None,
        "dimension_styles": None,
        "images": [],
        "layers": services.kernel.drawing_layers.to_mapping(),
    }
    mime = QMimeData()
    mime.setData(TEXT_CLIPBOARD_MIME, json.dumps(data).encode("utf-8"))
    clipboard = QApplication.clipboard()
    clipboard.setMimeData(mime)
    try:
        dialog.canvas.setFocus()
        QTest.keyClick(dialog.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert dialog.text_tools.pending
        QTest.mouseClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 4))
        )
        assert len(session.texts) == 1
        pasted = session.texts[0]
        assert pasted.position_mm == (5, 4) and pasted.style_id != "standard"
        assert dialog.text_tools.styles.get(pasted.style_id).height_mm == 8
        assert loaded.document.commands == original_commands
        assert services.kernel.drawing_text_styles == original_styles
        assert dialog.undo_local() and session.texts == ()
        assert session.styles == original_styles and dialog.text_tools.styles == original_styles
        assert dialog.redo_local() and session.texts == (pasted,)
        assert dialog.text_tools.styles.get(pasted.style_id).height_mm == 8
        apply = cast(
            "Callable[[object, str, Mapping[str, object]], None]",
            vars(type(services.kernel))["_apply_drawing_block"],
        )
        failed = False

        def fail_once(command_id: str, params: Mapping[str, object]) -> None:
            nonlocal failed
            if command_id == "drawing.block.update" and not failed:
                failed = True
                raise RuntimeError("simulated block update failure")
            apply(services.kernel, command_id, params)

        monkeypatch.setattr(services.kernel, "_apply_drawing_block", fail_once)
        assert not dialog.save_definition() and failed
        assert "simulated block update failure" in dialog.status_label.text()
        assert loaded.document.commands == original_commands
        assert services.kernel.drawing_text_styles == original_styles
        assert services.kernel.drawing_block_definitions == (definition,)
        assert session.dirty and session.texts == (pasted,)
        assert session.styles.get(pasted.style_id).height_mm == 8
        assert dialog.save_definition(), dialog.status_label.text()
        assert loaded.document.commands[-1].id == "drawing.objects.batch"
        assert services.kernel.drawing_text_styles.get(pasted.style_id).height_mm == 8
        assert services.kernel.drawing_block_definitions[0].texts == (pasted,)
        for instance in instances:
            expanded = expand_block(
                services.kernel.drawing_block_definitions[0],
                instance,
                services.kernel.drawing_text_styles,
            )
            assert expanded.texts[0].position_mm == (instance.insertion_mm[0] + 5, 4)
            assert expanded.texts[0].height_mm == 8
        assert dialog.undo_local() and session.texts == ()
        assert dialog.save_definition(), dialog.status_label.text()
        assert services.kernel.drawing_block_definitions == (definition,)
        committed_styles = services.kernel.drawing_text_styles
        assert committed_styles.get(pasted.style_id).height_mm == 8
        assert session.styles == committed_styles
        assert dialog.redo_local() and session.texts == (pasted,)
        assert dialog.save_definition(), dialog.status_label.text()
        assert services.kernel.drawing_text_styles.get(pasted.style_id).height_mm == 8
        path = tmp_path / "block-pasted-style.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        reopened.bus.undo_operation()
        assert services.kernel.drawing_block_definitions == (definition,)
        assert services.kernel.drawing_text_styles == committed_styles
        reopened.bus.undo_operation()
        assert services.kernel.drawing_block_definitions[0].texts == (pasted,)
        reopened.bus.undo_operation()
        assert services.kernel.drawing_text_styles == original_styles
        assert services.kernel.drawing_block_instances == instances
        reopened.bus.redo_operation()
        assert services.kernel.drawing_block_definitions[0].texts == (pasted,)
        assert services.kernel.drawing_text_styles.get(pasted.style_id).height_mm == 8
    finally:
        clipboard.clear()
        dialog.close()


def test_block_editor_copies_and_pastes_geometry_and_text_as_one_step(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from PySide6.QtCore import QMimeData, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import SketchEntity
    from mycad.ui.drawing_text_tools import TEXT_CLIPBOARD_MIME

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    text = DrawingText(uuid4().hex, "Label", (1, 1))
    definition = BlockDefinition(uuid4().hex, "MixedClipboard", (line,), (text,))
    instance = BlockInstance(uuid4().hex, definition.definition_id, (10, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    before = loaded.document.commands
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    qtbot.addWidget(dialog)
    dialog.show()
    clipboard = QApplication.clipboard()
    clipboard.clear()
    try:
        dialog.canvas.selected_entity_ids = {line.entity_id}
        dialog.text_tools.selected_ids = {text.text_id}
        dialog.canvas.setFocus()
        QTest.keyClick(dialog.canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        assert clipboard.mimeData().hasFormat(TEXT_CLIPBOARD_MIME)
        raw = json.loads(bytes(clipboard.mimeData().data(TEXT_CLIPBOARD_MIME).data()))
        raw["dimension_styles"] = services.kernel.drawing_dimension_styles.to_mapping()
        mime = QMimeData()
        mime.setData(TEXT_CLIPBOARD_MIME, json.dumps(raw).encode("utf-8"))
        clipboard.setMimeData(mime)
        QTest.keyClick(dialog.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert dialog.text_tools.pending
        original_set = session.set_members
        failed = False

        def fail_once(
            entities: tuple[SketchEntity, ...],
            texts: tuple[DrawingText, ...],
            styles: TextStyleTable | None = None,
        ) -> None:
            nonlocal failed
            if len(entities) > 1 and len(texts) > 1 and not failed:
                failed = True
                raise ValidationError("simulated local paste failure")
            original_set(entities, texts, styles)

        monkeypatch.setattr(session, "set_members", fail_once)
        QTest.mouseClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
        )
        assert failed and dialog.text_tools.pending
        assert session.entities == (line,) and session.texts == (text,)
        assert "simulated local paste failure" in dialog.status_label.text()
        assert loaded.document.commands == before
        QTest.mouseClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
        )
        assert len(session.entities) == len(session.texts) == 2
        copied_line = session.entities[1]
        assert isinstance(copied_line, LineEntity)
        assert copied_line.entity_id != line.entity_id
        assert copied_line.start_mm == (4, 4) and copied_line.end_mm == (6, 4)
        assert session.texts[1].position_mm == (5, 5) and session.texts[1].text_id != text.text_id
        assert loaded.document.commands == before
        assert dialog.undo_local() and session.entities == (line,) and session.texts == (text,)
        assert dialog.redo_local() and len(session.entities) == len(session.texts) == 2
        assert dialog.save_definition()
        path = tmp_path / "block-mixed-clipboard.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        reopened.bus.undo_operation()
        assert services.kernel.drawing_block_definitions == (definition,)
        assert services.kernel.drawing_block_instances == (instance,)
    finally:
        clipboard.clear()
        dialog.close()


def test_block_mixed_copy_failure_preserves_system_clipboard(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad.ui import drawing_text_tools

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    text = DrawingText(uuid4().hex, "Label", (1, 1))
    definition = BlockDefinition(uuid4().hex, "CopyFailure", (line,), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    before = loaded.document.commands
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.show()
    clipboard = QApplication.clipboard()
    clipboard.setText("previous clipboard")
    try:
        dialog.canvas.selected_entity_ids = {line.entity_id}
        dialog.text_tools.selected_ids = {text.text_id}
        monkeypatch.setattr(drawing_text_tools, "_MAX_CLIPBOARD_BYTES", 100)
        dialog.canvas.setFocus()
        QTest.keyClick(dialog.canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        assert clipboard.text() == "previous clipboard"
        assert "过大" in dialog.canvas.message
        assert session.entities == (line,) and session.texts == (text,) and not session.dirty
        assert loaded.document.commands == before
    finally:
        clipboard.clear()
        dialog.close()


def test_cross_document_mixed_clipboard_pastes_into_block_editor(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.persistence import save_document
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.drawing_text_tools import TEXT_CLIPBOARD_MIME
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    qtbot.addWidget(window)
    window.show()
    source = window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    style = TextStyle("standard", "标准", height_mm=8)
    source.loaded.bus.execute(
        "drawing.text_styles.set", TextStyleTable((style,), style.style_id).to_mapping(), "local"
    )
    text = DrawingText(uuid4().hex, "Source", (1, 1), style_id=style.style_id)
    source.loaded.bus.execute("drawing.text.add", text.to_mapping(), "local")
    from collections.abc import Callable
    from typing import cast

    cast("Callable[[MainWindow], None]", vars(type(window))["_sync_drawing_layers"])(window)
    editor.canvas.set_source_context_revision(source.loaded.document.revision)
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    assert editor.canvas.replace_draft_entities((line,))
    tools = editor.canvas.text_tools
    assert tools is not None
    editor.canvas.selected_entity_ids = {line.entity_id}
    tools.selected_ids = {text.text_id}
    clipboard = QApplication.clipboard()
    try:
        assert editor.canvas.copy_to_clipboard(), editor.canvas.message
        assert clipboard.mimeData().hasFormat(TEXT_CLIPBOARD_MIME)
        source_commands = source.loaded.document.commands
        target = window.new_session_document("sketch")
        target_editor = window.active_sketch_dialog()
        assert target_editor is not None and target_editor is not editor
        target_line = LineEntity(uuid4().hex, (10, 10), (12, 10))
        definition = BlockDefinition(uuid4().hex, "CrossPaste", (target_line,), ())
        instance = BlockInstance(uuid4().hex, definition.definition_id, (20, 0))
        target.loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
        target.loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
        target_editor.canvas.set_source_context_revision(target.loaded.document.revision)
        target_editor.canvas.selected_block_instance_ids = {instance.instance_id}
        target_editor.drawing_command_bar.input.setText("BEDIT")
        QTest.keyClick(target_editor.drawing_command_bar.input, Qt.Key.Key_Return)
        block_editor = window.active_block_editor()
        assert block_editor is not None
        block_editor.canvas.setFocus()
        QTest.keyClick(block_editor.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert block_editor.text_tools.pending
        QTest.mouseClick(
            block_editor.canvas,
            Qt.MouseButton.LeftButton,
            pos=block_editor.canvas.local_to_screen((5, 5)),
        )
        assert len(block_editor.session.entities) == 2 and len(block_editor.session.texts) == 1
        pasted_line = block_editor.session.entities[1]
        assert isinstance(pasted_line, LineEntity)
        assert (pasted_line.start_mm, pasted_line.end_mm) == ((4, 4), (6, 4))
        pasted_text = block_editor.session.texts[0]
        assert pasted_text.position_mm == (5, 5) and pasted_text.style_id != "standard"
        assert block_editor.session.styles.get(pasted_text.style_id).height_mm == 8
        assert block_editor.save_definition()
        block_editor.close()
        path = tmp_path / "cross-document-block-paste.my2d"
        save_document(target.loaded.document, path)
        reopened = app.open_app_document(target.services, path)
        reopened.bus.undo_operation()
        assert target.services.kernel.drawing_block_definitions == (definition,)
        reopened.bus.redo_operation()
        assert target.services.kernel.drawing_block_definitions[0].texts == (pasted_text,)
        window.activate_session_document(source.loaded.document.document_id)
        assert source.loaded.document.commands == source_commands
        assert window.active_sketch_dialog() is editor and tuple(editor.canvas.entities) == (line,)
        assert source.services.kernel.drawing_texts == (text,)
    finally:
        clipboard.clear()


@pytest.mark.parametrize("cancel_before_retry", [False, True])
def test_block_editor_copies_and_pastes_geometry_with_new_curve_identities(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel_before_retry: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import PolylineEntity, SketchEntity
    from mycad.ui.drawing_clipboard import DRAWING_CLIPBOARD_MIME

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = PolylineEntity(uuid4().hex, ((0, 0), (2, 0), (2, 2)))
    definition = BlockDefinition(uuid4().hex, "GeometryCopy", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    qtbot.addWidget(dialog)
    dialog.show()
    clipboard = QApplication.clipboard()
    try:
        dialog.canvas.selected_entity_ids = {line.entity_id}
        dialog.canvas.setFocus()
        QTest.keyClick(dialog.canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        assert clipboard.mimeData().hasFormat(DRAWING_CLIPBOARD_MIME)
        QTest.keyClick(dialog.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert dialog.canvas.clipboard_paste_active
        original_set = session.set_members
        failed = False

        def fail_once(
            entities: tuple[SketchEntity, ...],
            texts: tuple[DrawingText, ...],
            styles: TextStyleTable | None = None,
        ) -> None:
            nonlocal failed
            if len(entities) > 1 and not failed:
                failed = True
                raise ValidationError("simulated geometry paste failure")
            original_set(entities, texts, styles)

        monkeypatch.setattr(session, "set_members", fail_once)
        QTest.mouseClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
        )
        assert failed and dialog.canvas.clipboard_paste_active
        assert session.entities == tuple(dialog.canvas.entities) == (line,)
        assert "simulated geometry paste failure" in dialog.status_label.text()
        if cancel_before_retry:
            QTest.keyClick(dialog.canvas, Qt.Key.Key_Escape)
            assert not dialog.canvas.clipboard_paste_active
            assert session.entities == tuple(dialog.canvas.entities) == (line,)
            QTest.keyClick(dialog.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
            assert dialog.canvas.clipboard_paste_active
        QTest.mouseClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
        )
        assert len(session.entities) == 2 and isinstance(session.entities[1], PolylineEntity)
        copied = session.entities[1]
        assert copied.entity_id != line.entity_id and len(copied.point_ids) == 3
        assert len(set(copied.point_ids)) == 3
        assert copied.points_mm == ((5, 5), (7, 5), (7, 7))
        assert dialog.undo_local() and session.entities == (line,)
        assert dialog.redo_local() and session.entities[1] == copied
        assert loaded.document.commands[-1].id == "drawing.block.create"
        assert dialog.save_definition()
        path = tmp_path / "block-geometry-clipboard.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert services.kernel.drawing_block_definitions[0].entities[1] == copied
        reopened.bus.undo_operation()
        assert services.kernel.drawing_block_definitions == (definition,)
        reopened.bus.redo_operation()
        assert services.kernel.drawing_block_definitions[0].entities[1] == copied
    finally:
        clipboard.clear()
        dialog.close()


@pytest.mark.parametrize(
    "kind", ["constraint", "mixed_constraint", "mixed_image", "image", "block", "layer"]
)
def test_block_editor_rejects_unsupported_clipboard_without_partial_changes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    import json

    from PySide6.QtCore import QMimeData, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    from mycad.core.drawing_collection_clipboard import (
        DRAWING_COLLECTION_CLIPBOARD_MIME,
        DrawingCollectionClipboard,
        encode_collection_clipboard,
    )
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.drawing_clipboard import DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard
    from mycad.ui.drawing_text_tools import TEXT_CLIPBOARD_MIME

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Restricted", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    before = loaded.document.commands
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    qtbot.addWidget(dialog)
    dialog.show()
    source = LineEntity(
        uuid4().hex, (0, 0), (3, 0), layer_name="Foreign" if kind == "layer" else "0"
    )
    constraint = SketchConstraint(
        uuid4().hex, "length", (SketchGeometryReference(source.entity_id, "geometry"),), 3, "mm"
    )
    layers = services.kernel.drawing_layers
    if kind == "layer":
        layers = layers.add(SketchLayer("Foreign"))
    sketch = Sketch(
        uuid4().hex,
        WorkPlaneFrame.xy(),
        (source,),
        (constraint,) if kind in {"constraint", "mixed_constraint"} else (),
        layers,
    )
    mime = QMimeData()
    if kind in {"mixed_constraint", "mixed_image"}:
        text = DrawingText(uuid4().hex, "Mixed", (0, 0))
        images = (
            [
                DrawingRaster(
                    uuid4().hex,
                    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAACXBIWXMAAA7EAAAOxAGVKw4b"
                    "AAAAFElEQVQImWNk+M/wn4GBgYGJAQoAHhgCAh6YW2QAAAAASUVORK5CYII=",
                    (1, 1),
                    2,
                    2,
                ).to_mapping(version=2)
            ]
            if kind == "mixed_image"
            else []
        )
        data = {
            "format": "mycad-text",
            "version": 1,
            "texts": [text.to_mapping()],
            "styles": TextStyleTable().to_mapping(),
            "sketch": sketch.to_state_mapping(),
            "dimension_styles": None,
            "images": images,
            "layers": layers.to_mapping(),
        }
        mime.setData(TEXT_CLIPBOARD_MIME, json.dumps(data).encode("utf-8"))
    elif kind == "image":
        mime.setImageData(QImage(2, 2, QImage.Format.Format_ARGB32))
    elif kind == "block":
        other = BlockDefinition(uuid4().hex, "Nested", (source,), ())
        instance = BlockInstance(uuid4().hex, other.definition_id, (0, 0))
        payload = DrawingCollectionClipboard(
            (),
            (),
            (),
            (),
            TextStyleTable(),
            layers,
            block_definitions=(other,),
            block_instances=(instance,),
        )
        mime.setData(DRAWING_COLLECTION_CLIPBOARD_MIME, encode_collection_clipboard(payload))
    else:
        mime.setData(DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard(sketch))
    clipboard = QApplication.clipboard()
    clipboard.setMimeData(mime)
    try:
        dialog.canvas.setFocus()
        QTest.keyClick(dialog.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        if kind in {"mixed_constraint", "mixed_image"}:
            assert dialog.text_tools.pending
            QTest.mouseClick(
                dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
            )
            assert dialog.text_tools.pending
            assert ("约束" if kind == "mixed_constraint" else "图片") in dialog.status_label.text()
            dialog.text_tools.cancel()
        else:
            assert not dialog.canvas.clipboard_paste_active
            assert dialog.canvas.message
        assert session.entities == (line,) and session.texts == () and not session.dirty
        assert loaded.document.commands == before
    finally:
        clipboard.clear()
        dialog.close()


@pytest.mark.parametrize("kind", ["geometry", "mixed"])
@pytest.mark.parametrize("plane", ["rotated", "reverse", "offset"])
def test_block_editor_clipboard_requires_same_facing_coplanar_geometry(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, kind: str, plane: str
) -> None:
    import json

    from PySide6.QtCore import QMimeData, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.drawing_clipboard import DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard
    from mycad.ui.drawing_text_tools import TEXT_CLIPBOARD_MIME

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    existing = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Plane", (existing,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    before = loaded.document.commands
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    qtbot.addWidget(dialog)
    dialog.show()
    frame = (
        WorkPlaneFrame((0, 0, 0), (0, 1, 0), (1, 0, 0), (0, 0, -1))
        if plane == "reverse"
        else WorkPlaneFrame((0, 0, 1 if plane == "offset" else 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1))
    )
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, frame, (line,))
    mime = QMimeData()
    if kind == "geometry":
        mime.setData(DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard(sketch))
    else:
        text = DrawingText(uuid4().hex, "Text", (1, 1))
        data = {
            "format": "mycad-text",
            "version": 1,
            "texts": [text.to_mapping()],
            "styles": TextStyleTable().to_mapping(),
            "sketch": sketch.to_state_mapping(),
            "dimension_styles": None,
            "images": [],
            "layers": sketch.layers.to_mapping(),
        }
        mime.setData(TEXT_CLIPBOARD_MIME, json.dumps(data).encode("utf-8"))
    clipboard = QApplication.clipboard()
    clipboard.setMimeData(mime)
    try:
        dialog.canvas.setFocus()
        QTest.keyClick(dialog.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        if kind == "geometry" and plane != "rotated":
            assert not dialog.canvas.clipboard_paste_active
        else:
            assert dialog.canvas.clipboard_paste_active or dialog.text_tools.pending
            QTest.mouseClick(
                dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
            )
        if plane == "rotated":
            assert len(session.entities) == 2 and isinstance(session.entities[1], LineEntity)
            copied = session.entities[1]
            assert copied.start_mm == ((5, 5) if kind == "geometry" else (4, 4))
            assert copied.end_mm == ((5, 7) if kind == "geometry" else (4, 6))
            if kind == "mixed":
                assert len(session.texts) == 1 and session.texts[0].position_mm == (5, 5)
            assert dialog.undo_local() and session.entities == (existing,)
        else:
            assert session.entities == (existing,) and session.texts == () and not session.dirty
            if kind == "mixed":
                assert dialog.text_tools.pending
                dialog.text_tools.cancel()
        assert loaded.document.commands == before
    finally:
        clipboard.clear()
        dialog.close()


def test_block_editor_canvas_text_copy_and_paste_shortcuts(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    from mycad.ui.drawing_text_tools import TEXT_CLIPBOARD_MIME

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    text = DrawingText(uuid4().hex, "Label", (1, 1))
    definition = BlockDefinition(uuid4().hex, "TextCopy", (), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    qtbot.addWidget(dialog)
    dialog.show()
    clipboard = QApplication.clipboard()
    try:
        dialog.text_tools.selected_ids = {text.text_id}
        dialog.canvas.setFocus()
        QTest.keyClick(dialog.canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        assert clipboard.mimeData().hasFormat(TEXT_CLIPBOARD_MIME)
        QTest.keyClick(dialog.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert dialog.text_tools.pending
        QTest.mouseClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((4, 5))
        )
        assert len(session.texts) == 2 and session.texts[1].text == text.text
        assert session.texts[1].position_mm == (4, 5) and session.texts[1].text_id != text.text_id
        assert dialog.undo_local() and session.texts == (text,)
        assert loaded.document.commands[-1].id == "drawing.block.create"
    finally:
        clipboard.clear()
        dialog.close()


def test_block_editor_context_menu_copies_and_pastes_mixed_selection(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import SketchEntity
    from mycad.ui.drawing_text_tools import TEXT_CLIPBOARD_MIME

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    text = DrawingText(uuid4().hex, "Label", (1, 1))
    definition = BlockDefinition(uuid4().hex, "Context", (line,), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    canvas = dialog.canvas
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {line.entity_id}
    dialog.text_tools.selected_ids = {text.text_id}
    seen: list[str] = []

    def open_and_choose(label: str) -> None:
        def choose() -> None:
            menu = QApplication.activePopupWidget()
            if not isinstance(menu, QMenu):
                return
            action = next((item for item in menu.actions() if item.text().startswith(label)), None)
            if action is None or not action.isEnabled():
                menu.close()
                return
            seen.append(label)
            QTest.mouseClick(
                menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center()
            )

        QTimer.singleShot(0, choose)
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(20, 20), QPoint(20, 20))
        canvas.contextMenuEvent(event)

    clipboard = QApplication.clipboard()
    try:
        for label in ("复制", "粘贴"):
            open_and_choose(label)
        assert seen == ["复制", "粘贴"]
        assert clipboard.mimeData().hasFormat(TEXT_CLIPBOARD_MIME)
        assert dialog.text_tools.pending
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((5, 5)))
        assert len(session.entities) == len(session.texts) == 2
        assert dialog.undo_local() and session.entities == (line,) and session.texts == (text,)
        canvas.selected_entity_ids.clear()
        dialog.text_tools.selected_ids = {text.text_id}
        open_and_choose("删除")
        assert seen[-1] == "删除" and session.entities == (line,) and session.texts == ()
        assert dialog.undo_local() and session.texts == (text,)
        original = session.set_members
        failed = False

        def fail_once(
            entities: tuple[SketchEntity, ...],
            texts: tuple[DrawingText, ...],
            styles: TextStyleTable | None = None,
        ) -> None:
            nonlocal failed
            if not entities and not texts and not failed:
                failed = True
                raise ValidationError("simulated mixed delete failure")
            original(entities, texts, styles)

        monkeypatch.setattr(session, "set_members", fail_once)
        canvas.selected_entity_ids = {line.entity_id}
        dialog.text_tools.selected_ids = {text.text_id}
        open_and_choose("删除")
        assert failed and session.entities == (line,) and session.texts == (text,)
        assert tuple(canvas.entities) == (line,)
        assert "simulated mixed delete failure" in dialog.status_label.text()
        open_and_choose("删除")
        assert session.entities == session.texts == ()
        assert dialog.undo_local() and session.entities == (line,) and session.texts == (text,)
        assert dialog.redo_local() and session.entities == session.texts == ()
        assert dialog.undo_local()
        assert len(loaded.document.commands) == 1
        path = tmp_path / "block-context-menu.my2d"
        save_document(loaded.document, path)
        app.open_app_document(services, path)
        assert services.kernel.drawing_block_definitions == (definition,)
    finally:
        clipboard.clear()
        dialog.close()


def test_block_context_menu_preserves_unfinished_text_edit(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    text = DrawingText(uuid4().hex, "Before", (1, 1))
    definition = BlockDefinition(uuid4().hex, "PendingText", (), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    assert dialog.canvas.set_tool("选择元素")
    dialog.text_tools.selected_ids = {text.text_id}
    dialog.text_tools.edit_selected()
    dialog.text_tools.editor.setPlainText("Unfinished")
    assert dialog.text_tools.pending
    opened: list[bool] = []

    def choose_delete() -> None:
        menu = QApplication.activePopupWidget()
        if not isinstance(menu, QMenu):
            return
        opened.append(True)
        action = next(item for item in menu.actions() if item.text().startswith("删除"))
        if action.isEnabled():
            QTest.mouseClick(
                menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center()
            )
        else:
            menu.close()

    try:
        QTimer.singleShot(0, choose_delete)
        dialog.canvas.contextMenuEvent(
            QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(20, 20), QPoint(20, 20))
        )
        QApplication.processEvents()
        assert not opened
        assert dialog.text_tools.pending and dialog.text_tools.editor.toPlainText() == "Unfinished"
        assert session.texts == (text,) and not session.dirty
        assert services.kernel.drawing_block_definitions == (definition,)
        QTest.keyClick(dialog.canvas, Qt.Key.Key_Delete)
        assert dialog.text_tools.pending and dialog.text_tools.editor.toPlainText() == "Unfinished"
        assert session.texts == (text,) and not session.dirty
        QTest.keyClick(
            dialog.text_tools.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier
        )
        assert session.texts[0].text == "Unfinished"
        assert dialog.undo_local() and session.texts == (text,)
    finally:
        dialog.close()


def test_block_text_tool_switch_preserves_unfinished_text_edit(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox, QPushButton

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    text = DrawingText(uuid4().hex, "Before", (1, 1))
    definition = BlockDefinition(uuid4().hex, "TextSwitch", (), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    dialog.text_tools.selected_ids = {text.text_id}
    dialog.text_tools.edit_selected()
    dialog.text_tools.editor.setPlainText("Unfinished")
    try:
        next(item for item in dialog.findChildren(QPushButton) if item.text() == "多行文字").click()
        assert dialog.text_tools.pending and dialog.text_tools.editor.toPlainText() == "Unfinished"
        assert dialog.text_tools.overlay.isVisible()
        assert "完成或取消" in dialog.status_label.text()
        assert session.texts == (text,) and not session.dirty
        QTest.keyClick(
            dialog.text_tools.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier
        )
        assert session.texts[0].text == "Unfinished"
        assert dialog.undo_local() and session.texts == (text,)
    finally:
        dialog.close()


def test_block_repeated_text_edit_preserves_unfinished_input(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    text = DrawingText(uuid4().hex, "Before", (1, 1))
    definition = BlockDefinition(uuid4().hex, "EditAgain", (), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    tools = dialog.text_tools
    tools.selected_ids = {text.text_id}
    tools.edit_selected()
    tools.editor.setPlainText("Unfinished")
    try:
        tools.edit_selected()
        assert tools.pending and tools.editor.toPlainText() == "Unfinished"
        assert session.texts == (text,) and not session.dirty
        QTest.mouseDClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((1, 1))
        )
        assert tools.pending and tools.editor.toPlainText() == "Unfinished"
        assert tools.selected_ids == {text.text_id}
        QTest.keyClick(tools.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        assert session.texts[0].text == "Unfinished"
        assert dialog.undo_local() and session.texts == (text,)
    finally:
        dialog.close()


def test_block_geometry_paste_waits_for_unfinished_text_edit(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QMimeData, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.ui.drawing_clipboard import DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    text = DrawingText(uuid4().hex, "Before", (1, 1))
    definition = BlockDefinition(uuid4().hex, "PasteDuringText", (), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    dialog.text_tools.selected_ids = {text.text_id}
    dialog.text_tools.edit_selected()
    dialog.text_tools.editor.setPlainText("Unfinished")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    mime = QMimeData()
    mime.setData(DRAWING_CLIPBOARD_MIME, encode_drawing_clipboard(sketch))
    clipboard = QApplication.clipboard()
    clipboard.setMimeData(mime)
    try:
        QTest.keyClick(dialog.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert not dialog.canvas.clipboard_paste_active
        assert dialog.text_tools.pending and dialog.text_tools.editor.toPlainText() == "Unfinished"
        assert session.texts == (text,) and session.entities == () and not session.dirty
        QTest.keyClick(
            dialog.text_tools.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier
        )
        assert session.texts[0].text == "Unfinished"
        QTest.keyClick(dialog.canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert dialog.canvas.clipboard_paste_active
        QTest.mouseClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
        )
        assert len(session.entities) == 1, (dialog.canvas.message, dialog.status_label.text())
        assert (
            dialog.undo_local() and session.entities == () and session.texts[0].text == "Unfinished"
        )
    finally:
        clipboard.clear()
        dialog.close()


def test_block_editor_text_field_keeps_native_paste_shortcut(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "NativePaste", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.show()
    clipboard = QApplication.clipboard()
    clipboard.setText("plain text")
    try:
        assert dialog.text_tools.begin("text")
        dialog.text_tools.place((0, 0))
        field = dialog.text_tools.editor
        field.setFocus()
        QTest.keyClick(field, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert field.toPlainText() == "plain text"
        assert session.texts == () and not session.dirty
        dialog.text_tools.cancel()
    finally:
        clipboard.clear()
        dialog.close()


def test_block_save_keeps_unsaved_style_redo_local(tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "StyleRedo", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    original = services.kernel.drawing_text_styles
    style_a, style_b = TextStyle("style-a", "A"), TextStyle("style-b", "B", height_mm=7)
    table_a = TextStyleTable((*original.styles, style_a), original.current_id)
    table_b = TextStyleTable((*table_a.styles, style_b), original.current_id)
    text_a = DrawingText(uuid4().hex, "A", (0, 0), style_id=style_a.style_id)
    text_b = DrawingText(uuid4().hex, "B", (0, 2), style_id=style_b.style_id)
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    session.set_members((line,), (text_a,), table_a)
    session.set_members((line,), (text_a, text_b), table_b)
    assert session.undo() and session.texts == (text_a,)
    session.save()
    assert services.kernel.drawing_text_styles == table_a
    assert session.redo() and session.styles == table_b
    assert services.kernel.drawing_text_styles == table_a
    session.save()
    assert services.kernel.drawing_text_styles == table_b
    path = tmp_path / "block-style-redo.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.drawing_text_styles == table_a
    assert services.kernel.drawing_block_definitions[0].texts == (text_a,)
    reopened.bus.redo_operation()
    assert services.kernel.drawing_text_styles == table_b
    assert services.kernel.drawing_block_definitions[0].texts == (text_a, text_b)


def test_block_style_save_survives_optimized_sketch_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Callable
    from typing import cast

    from mycad.core.drawing_blocks import expand_block
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.persistence import save_document
    from mycad.core.sketch import Sketch, WorkPlaneFrame

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (4, 0))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
    loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local", version=3)
    definition = BlockDefinition(uuid4().hex, "RebuildStyle", (line,), ())
    instances = tuple(BlockInstance(uuid4().hex, definition.definition_id, (x, 0)) for x in (1, 9))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for instance in instances:
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    original = services.kernel.drawing_text_styles
    extra = TextStyle("rebuild-style", "Rebuild", height_mm=8)
    styles = TextStyleTable((*original.styles, extra), original.current_id)
    text = DrawingText(uuid4().hex, "Text", (2, 3), style_id=extra.style_id)
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    session.set_members((line,), (text,), styles)
    session.save()
    updated = services.kernel.drawing_block_definitions[0]
    regenerate = cast(
        "Callable[..., object]", vars(type(services.kernel))["_regenerate_with_sketches"]
    )
    calls = 0

    def track(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return regenerate(services.kernel, *args, **kwargs)

    monkeypatch.setattr(services.kernel, "_regenerate_with_sketches", track)
    revised = replace(sketch, entities=(replace(line, end_mm=(6, 0)),))
    state = revised.to_state_mapping()
    loaded.bus.execute(
        "drawing.sketch.revise",
        {
            "revisions": [
                {
                    "sketch_id": sketch.sketch_id,
                    "base_state_sha256": sketch.local_state_digest(),
                    "entities": state["entities"],
                    "constraints": state["constraints"],
                }
            ]
        },
        "local",
        version=79,
    )
    assert calls == 1
    assert services.kernel.drawing_block_definitions == (updated,)
    assert services.kernel.drawing_block_instances == instances
    assert services.kernel.drawing_text_styles == styles
    for instance in instances:
        assert expand_block(updated, instance, styles).texts[0].height_mm == 8
    path = tmp_path / "block-style-rebuild.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert services.kernel.sketches == (sketch,)
    assert services.kernel.drawing_block_definitions == (updated,)
    assert services.kernel.drawing_text_styles == styles
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_text_styles == original
    reopened.bus.redo_operation()
    reopened.bus.redo_operation()
    assert services.kernel.sketches == (revised,)
    assert services.kernel.drawing_block_definitions == (updated,)
    assert services.kernel.drawing_text_styles == styles


def test_block_edited_style_survives_group_explode_and_dxf(tmp_path: Path) -> None:
    from mycad.core.drawing_block_transactions import prepare_block_explode
    from mycad.core.drawing_blocks import expand_block
    from mycad.core.drawing_groups import DrawingGroup, DrawingObjectRef
    from mycad.core.drawing_text import TextStyle, TextStyleTable
    from mycad.core.persistence import save_document
    from mycad.formats.dxf_preview import prepare_dxf_output_preview
    from mycad.formats.providers.dxf_provider import read_sketch_dxf

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "EditedStyle", (line,), ())
    first = BlockInstance(uuid4().hex, definition.definition_id, (10, 20), 90, 2)
    second = BlockInstance(uuid4().hex, definition.definition_id, (30, 0))
    group = DrawingGroup(
        uuid4().hex, (DrawingObjectRef("block_instance", first.instance_id),), name="EditedGroup"
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for instance in (first, second):
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.bus.execute("drawing.group.create", group.to_mapping(), "local")
    original_styles = services.kernel.drawing_text_styles
    added_style = TextStyle("edited-style", "Edited", height_mm=8)
    styles = TextStyleTable((*original_styles.styles, added_style), original_styles.current_id)
    text = DrawingText(uuid4().hex, "Block text", (1, 2), style_id=added_style.style_id)
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    session.set_members((line,), (text,), styles)
    session.save()
    before = app.drawing_collection_snapshot(services)
    expanded = expand_block(before.block_definitions[0], first, styles)
    operation = prepare_block_explode(before, first.instance_id)
    loaded.bus.execute(operation.command_id, operation.params, "local", version=operation.version)
    after = app.drawing_collection_snapshot(services)
    assert after.block_instances == (second,)
    assert len(after.texts) == 1 and after.texts[0].position_mm == expanded.texts[0].position_mm
    assert after.texts[0].height_mm == 16 and after.texts[0].style_id == added_style.style_id
    assert {item.kind for item in after.groups[0].members} == {"geometry", "text"}
    dxf = tmp_path / "edited-style-exploded.dxf"
    dxf.write_bytes(prepare_dxf_output_preview(services.kernel).dxf_bytes)
    imported = read_sketch_dxf(dxf)
    assert len(imported.groups) == 1 and {item.kind for item in imported.groups[0].members} == {
        "geometry",
        "text",
    }
    assert len(imported.texts) == 1 and imported.texts[0].height_mm == 16
    assert imported.texts[0].position_mm == expanded.texts[0].position_mm
    assert len(imported.block_instances) == 1 and imported.text_styles is not None
    assert imported.text_styles.get(imported.texts[0].style_id).height_mm == 8
    native = tmp_path / "edited-style-exploded.my2d"
    save_document(loaded.document, native)
    reopened = app.open_app_document(services, native)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_text_styles == original_styles
    reopened.bus.redo_operation()
    reopened.bus.redo_operation()
    assert app.drawing_collection_snapshot(services) == after


def test_editor_canvas_and_text_share_local_undo_and_save(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    text = DrawingText(uuid4().hex, "Label", (1, 1))
    definition = BlockDefinition(uuid4().hex, "Local", (line,), (text,))
    instances = tuple(BlockInstance(uuid4().hex, definition.definition_id, (x, 0)) for x in (1, 9))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for instance in instances:
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.show()
    history = tuple(loaded.document.commands)
    revised_line = replace(line, end_mm=(4, 0))
    assert dialog.canvas.replace_draft_entities((revised_line,))
    revised_text = replace(text, text="Changed")
    assert dialog.text_tools.execute is not None
    assert dialog.text_tools.execute("drawing.text.update", revised_text.to_mapping())
    assert tuple(loaded.document.commands) == history
    assert dialog.undo_local() and dialog.text_tools.texts == (text,)
    assert tuple(dialog.canvas.entities) == (revised_line,)
    assert dialog.undo_local() and tuple(dialog.canvas.entities) == (line,)
    assert dialog.redo_local() and dialog.redo_local()
    assert dialog.save_definition()
    assert services.kernel.drawing_block_definitions[0].entities == (revised_line,)
    assert services.kernel.drawing_block_definitions[0].texts == (revised_text,)
    assert services.kernel.drawing_block_instances == instances
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (definition,)


def test_block_editor_move_command_transforms_geometry_and_text_as_one_local_step(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    text = DrawingText(uuid4().hex, "Text", (0, 3))
    definition = BlockDefinition(uuid4().hex, "Mixed", (line,), (text,))
    instances = tuple(BlockInstance(uuid4().hex, definition.definition_id, (x, 0)) for x in (0, 10))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for instance in instances:
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    history = tuple(loaded.document.commands)
    dialog.canvas.selected_entity_ids = {line.entity_id}
    dialog.text_tools.selected_ids = {text.text_id}
    dialog.command_input.setText("MOVE")
    QTest.keyClick(dialog.command_input, Qt.Key.Key_Return)
    dialog.canvas.add_coordinate_point((0, 0), exact_point=True)
    dialog.canvas.add_coordinate_point((0, 4), exact_point=True)
    moved_line = replace(line, start_mm=(0, 4), end_mm=(2, 4))
    moved_text = replace(text, position_mm=(0, 7))
    assert session.entities == (moved_line,) and session.texts == (moved_text,)
    assert tuple(loaded.document.commands) == history
    assert dialog.undo_local() and session.entities == (line,) and session.texts == (text,)
    assert (
        dialog.redo_local() and session.entities == (moved_line,) and session.texts == (moved_text,)
    )
    assert dialog.save_definition()
    assert services.kernel.drawing_block_definitions[0].entities == (moved_line,)
    assert services.kernel.drawing_block_definitions[0].texts == (moved_text,)
    assert services.kernel.drawing_block_instances == instances
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (definition,)
    dialog.close()


@pytest.mark.parametrize("command", ["COPY", "ROTATE", "SCALE", "MIRROR", "ERASE"])
def test_block_editor_mixed_edit_commands_are_atomic_and_locally_undoable(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1, 1), (3, 1))
    text = DrawingText(uuid4().hex, "Text", (1, 2))
    definition = BlockDefinition(uuid4().hex, "Mixed", (line,), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    history = tuple(loaded.document.commands)
    dialog.canvas.selected_entity_ids = {line.entity_id}
    dialog.text_tools.selected_ids = {text.text_id}
    dialog.command_input.setText(command)
    QTest.keyClick(dialog.command_input, Qt.Key.Key_Return)
    if command != "ERASE":
        dialog.canvas.add_coordinate_point((0, 0), exact_point=True)
        if command == "ROTATE":
            assert dialog.canvas.apply_rotation_angle(90)
        elif command == "SCALE":
            assert dialog.canvas.apply_scale_factor(2)
        else:
            dialog.canvas.add_coordinate_point(
                (4, 0) if command == "COPY" else (1, 0), exact_point=True
            )
    if command == "ERASE":
        assert session.entities == () and session.texts == ()
    elif command in {"COPY", "MIRROR"}:
        assert len(session.entities) == len(session.texts) == 2
        assert session.entities[0] == line and session.texts[0] == text
        assert (
            session.entities[-1].entity_id != line.entity_id
            and session.texts[-1].text_id != text.text_id
        )
        assert session.texts[-1].position_mm == pytest.approx(
            (5, 2) if command == "COPY" else (1, -2)
        )
    else:
        assert session.texts[0].position_mm == pytest.approx(
            (-2, 1) if command == "ROTATE" else (2, 4)
        )
        assert session.entities != (line,)
    assert tuple(loaded.document.commands) == history
    assert dialog.undo_local() and session.entities == (line,) and session.texts == (text,)
    assert dialog.redo_local()
    dialog.close()


def test_block_editor_move_button_operates_on_clicked_geometry(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (4, 0))
    definition = BlockDefinition(uuid4().hex, "Line", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    dialog.tool_buttons["选择元素"].click()
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((2, 0))
    )
    assert dialog.canvas.selected_entity_ids == {line.entity_id}
    dialog.tool_buttons["移动"].click()
    dialog.canvas.add_coordinate_point((0, 0), exact_point=True)
    dialog.canvas.add_coordinate_point((0, 5), exact_point=True)
    assert session.entities == (replace(line, start_mm=(0, 5), end_mm=(4, 5)),)
    assert dialog.undo_local() and session.entities == (line,)
    assert services.kernel.drawing_block_definitions == (definition,)
    dialog.close()


def test_block_editor_box_selects_geometry_and_text_for_mixed_move(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (4, 0))
    text = DrawingText(uuid4().hex, "T", (8, 3))
    definition = BlockDefinition(uuid4().hex, "Mixed", (line,), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    dialog.tool_buttons["选择元素"].click()
    start = dialog.canvas.local_to_screen((-4, 10))
    end = dialog.canvas.local_to_screen((20, -4))
    QTest.mousePress(dialog.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(dialog.canvas, end)
    QTest.mouseRelease(dialog.canvas, Qt.MouseButton.LeftButton, pos=end)
    assert dialog.canvas.selected_entity_ids == {line.entity_id}
    assert dialog.text_tools.selected_ids == {text.text_id}
    dialog.tool_buttons["移动"].click()
    dialog.canvas.add_coordinate_point((0, 0), exact_point=True)
    dialog.canvas.add_coordinate_point((0, 4), exact_point=True)
    assert session.entities == (replace(line, start_mm=(0, 4), end_mm=(4, 4)),)
    assert session.texts == (replace(text, position_mm=(8, 7)),)
    assert dialog.undo_local() and session.entities == (line,) and session.texts == (text,)
    dialog.close()


def test_block_editor_move_button_operates_on_selected_text(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    text = DrawingText(uuid4().hex, "Text", (1, 2))
    definition = BlockDefinition(uuid4().hex, "TextOnly", (), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    dialog.text_tools.selected_ids = {text.text_id}
    dialog.tool_buttons["移动"].click()
    dialog.canvas.add_coordinate_point((0, 0), exact_point=True)
    dialog.canvas.add_coordinate_point((0, 5), exact_point=True)
    assert session.texts == (replace(text, position_mm=(1, 7)),)
    assert dialog.undo_local() and session.texts == (text,)
    assert services.kernel.drawing_block_definitions == (definition,)
    dialog.close()


@pytest.mark.parametrize("operation", ["移动", "复制", "旋转", "缩放", "镜像", "删除"])
def test_block_editor_multiple_texts_transform_as_one_local_step(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    texts = (DrawingText(uuid4().hex, "A", (1, 0)), DrawingText(uuid4().hex, "B", (2, 0)))
    definition = BlockDefinition(uuid4().hex, "TextOnly", (), texts)
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    history = tuple(loaded.document.commands)
    dialog.text_tools.selected_ids = {item.text_id for item in texts}
    dialog.tool_buttons[operation].click()
    if operation != "删除":
        dialog.canvas.add_coordinate_point((0, 0), exact_point=True)
        target = (
            (0, 1) if operation in {"旋转", "镜像"} else (2, 0) if operation == "缩放" else (0, 3)
        )
        dialog.canvas.add_coordinate_point(target, exact_point=True)
    changed = session.texts
    if operation == "删除":
        assert changed == ()
    elif operation in {"复制", "镜像"}:
        assert len(changed) == 4 and changed[:2] == texts
        expected_copies = ((1, 3), (2, 3)) if operation == "复制" else ((-1, 0), (-2, 0))
        for item, position in zip(changed[2:], expected_copies, strict=True):
            assert item.position_mm == pytest.approx(position)
        assert {item.text_id for item in changed[2:]}.isdisjoint(item.text_id for item in texts)
    else:
        expected = (
            ((0, 1), (0, 2))
            if operation == "旋转"
            else ((2, 0), (4, 0))
            if operation == "缩放"
            else ((1, 3), (2, 3))
        )
        assert len(changed) == 2
        for item, position in zip(changed, expected, strict=True):
            assert item.position_mm == pytest.approx(position)
    assert tuple(loaded.document.commands) == history
    assert dialog.undo_local() and session.texts == texts
    assert dialog.redo_local() and session.texts == changed


def test_block_editor_mixed_delete_rejects_locked_member_without_changes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Detail"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (4, 0), layer_name="Detail")
    text = DrawingText(uuid4().hex, "Text", (0, 3))
    definition = BlockDefinition(uuid4().hex, "Mixed", (line,), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    locked = layers.replace(replace(layers.get("Detail"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(session, locked, services.kernel.drawing_text_styles)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    dialog.canvas.selected_entity_ids = {line.entity_id}
    dialog.text_tools.selected_ids = {text.text_id}
    dialog.tool_buttons["删除"].click()
    assert "锁定" in dialog.status_label.text()
    assert session.entities == (line,) and session.texts == (text,) and not session.dirty
    assert services.kernel.drawing_block_definitions == (definition,)
    dialog.close()


def test_block_editor_mirror_copy_allocates_curve_points_for_rotated_rectangle(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.sketch import PolylineEntity, RectangleEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    rectangle = RectangleEntity(uuid4().hex, (0, 0), (3, 1))
    text = DrawingText(uuid4().hex, "Text", (1, 2))
    definition = BlockDefinition(uuid4().hex, "Mixed", (rectangle,), (text,))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    dialog.canvas.selected_entity_ids = {rectangle.entity_id}
    dialog.text_tools.selected_ids = {text.text_id}
    dialog.command_input.setText("MIRROR")
    QTest.keyClick(dialog.command_input, Qt.Key.Key_Return)
    dialog.canvas.add_coordinate_point((0, 0), exact_point=True)
    dialog.canvas.add_coordinate_point((1, 2), exact_point=True)
    copied = session.entities[-1]
    assert isinstance(copied, PolylineEntity) and len(copied.point_ids) == 4
    assert dialog.save_definition()
    assert services.kernel.drawing_block_definitions[0].entities[-1] == copied
    assert dialog.undo_local() and session.entities == (rectangle,) and session.texts == (text,)
    dialog.close()


def test_bedit_command_opens_selected_block_and_blocks_unfinished_draft(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Entry", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    draft = LineEntity(uuid4().hex, (4, 0), (6, 0))
    assert editor.canvas.replace_draft_entities((draft,))
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert window.active_block_editor() is None
    assert "草稿" in editor.status_label.text()
    assert editor.canvas.undo_last_operation()
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    block_editor = window.active_block_editor()
    assert block_editor is not None
    assert block_editor.canvas.replace_draft_entities((replace(line, end_mm=(5, 0)),))
    block_editor.command_input.setText("BSAVE")
    QTest.keyClick(block_editor.command_input, Qt.Key.Key_Return)
    assert services.kernel.drawing_block_definitions[0].entities == (replace(line, end_mm=(5, 0)),)
    block_editor.command_input.setText("BCLOSE")
    QTest.keyClick(block_editor.command_input, Qt.Key.Key_Return)
    assert window.active_block_editor() is None


def test_bedit_rejects_empty_draft_with_staged_saved_object_edit(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.sketch import Sketch
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
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
    saved_line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    saved = Sketch(uuid4().hex, editor.current_frame(), (saved_line,))
    app.commit_new_sketch(
        services, loaded, saved, session_identity=int(getattr(window, _SESSION_FIELD))
    )
    definition = BlockDefinition(
        uuid4().hex, "Existing", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (40, 40))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    getattr(window, _SYNC_METHOD)()
    draft_line = LineEntity(uuid4().hex, (0, 10), (10, 10))
    assert editor.canvas.replace_draft_entities((draft_line,))
    history = tuple(loaded.document.commands)
    command = editor.drawing_command_bar.input
    for value in ("TRIM", "ERASE"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((5, 0), (5, 10)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: editor.canvas.mixed_move is not None and not unit.is_busy, timeout=15000
    )
    assert editor.canvas.entities == [] and editor.canvas.collection_session is None
    staged = editor.canvas.mixed_move
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    command.setText("BEDIT")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert window.active_block_editor() is None
    assert "草稿" in editor.status_label.text()
    assert editor.canvas.mixed_move == staged
    assert tuple(loaded.document.commands) == history
    assert services.kernel.sketches == (saved,)
    assert editor.canvas.undo_last_operation()
    assert editor.canvas.entities == [draft_line]
    assert saved_line in (entity for entity, _ in editor.canvas.background_entities)
    assert tuple(loaded.document.commands) == history


def test_bedit_can_select_unreferenced_definition_and_save(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QInputDialog

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Unreferenced", (line,), ())
    other = BlockDefinition(uuid4().hex, "Other", (LineEntity(uuid4().hex, (0, 0), (1, 1)),), ())
    loaded.bus.execute("drawing.block.create", other.to_mapping(), "local")
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    options: list[str] = []

    def choose(
        _parent: object, _title: str, _label: str, items: list[str], *_args: object
    ) -> tuple[str, bool]:
        options.extend(items)
        return "Unreferenced", True

    monkeypatch.setattr(QInputDialog, "getItem", choose)
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    block_editor = window.active_block_editor()
    assert options == ["Other", "Unreferenced"] and block_editor is not None
    revised = replace(line, end_mm=(5, 0))
    assert block_editor.canvas.replace_draft_entities((revised,))
    assert block_editor.save_definition()
    assert services.kernel.drawing_block_definitions[1].entities == (revised,)
    block_editor.close()
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (other, definition)


@pytest.mark.parametrize("choice", ("cancel", "invalid", "changed", "session_changed"))
def test_bedit_definition_picker_does_not_open_on_cancel_or_stale_choice(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, choice: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QInputDialog

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Unreferenced", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    history = tuple(loaded.document.commands)

    def select(
        _parent: object, _title: str, _label: str, _items: list[str], *_args: object
    ) -> tuple[str, bool]:
        if choice == "changed":
            updated = replace(definition, name="Changed")
            loaded.bus.execute("drawing.block.update", updated.to_mapping(), "local")
        elif choice == "session_changed":
            identity = vars(window)["_session_id"]
            assert isinstance(identity, int)
            monkeypatch.setattr(window, "_session_id", identity + 1)
        return ("Missing" if choice == "invalid" else "Unreferenced", choice != "cancel")

    monkeypatch.setattr(QInputDialog, "getItem", select)
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert window.active_block_editor() is None
    if choice == "cancel":
        assert tuple(loaded.document.commands) == history
    else:
        assert "变化" in editor.status_label.text()
        assert len(loaded.document.commands) == len(history) + (choice == "changed")


def test_bedit_picker_rechecks_draft_created_while_open(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QInputDialog

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Unreferenced", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    draft = LineEntity(uuid4().hex, (2, 2), (3, 3))
    history = tuple(loaded.document.commands)

    def choose(
        _parent: object, _title: str, _label: str, _items: list[str], *_args: object
    ) -> tuple[str, bool]:
        assert editor.canvas.replace_draft_entities((draft,))
        return "Unreferenced", True

    monkeypatch.setattr(QInputDialog, "getItem", choose)
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert window.active_block_editor() is None
    assert "草稿" in editor.status_label.text()
    assert tuple(editor.canvas.entities) == (draft,)
    assert tuple(loaded.document.commands) == history


def test_editor_escape_close_requires_save_discard_or_cancel(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Close", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.canvas.replace_draft_entities((replace(line, end_mm=(4, 0)),))
    monkeypatch.setattr(QMessageBox, "question", _cancel_close)
    dialog.reject()
    assert dialog.isVisible() and session.dirty
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.reject()
    assert not dialog.isVisible()
    assert services.kernel.drawing_block_definitions == (definition,)


def test_editor_canvas_shortcuts_undo_only_local_changes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Keys", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.show()
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.canvas.setFocus()
    qtbot.waitUntil(dialog.isActiveWindow)
    assert dialog.canvas.replace_draft_entities((replace(line, end_mm=(4, 0)),))
    QTest.keyClick(dialog.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert tuple(dialog.canvas.entities) == (line,)
    assert len(loaded.document.commands) == 1
    QTest.keyClick(
        dialog.canvas,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert tuple(dialog.canvas.entities) == (replace(line, end_mm=(4, 0)),)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.close()


def test_block_editor_draws_line_from_toolbar(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Draw", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    dialog.tool_buttons["直线"].click()
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
    )
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((8, 5))
    )
    assert len(session.entities) == 2 and session.dirty
    assert len(loaded.document.commands) == 1
    dialog.close()


def test_block_editor_failed_drawing_keeps_canvas_and_history_consistent(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.exceptions import ValidationError
    from mycad.core.persistence import save_document
    from mycad.core.sketch import SketchEntity

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "DrawFailure", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    commands = loaded.document.commands
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    original = session.set_members
    failed = False

    def fail_once(
        entities: tuple[SketchEntity, ...],
        texts: tuple[DrawingText, ...],
        styles: TextStyleTable | None = None,
    ) -> None:
        nonlocal failed
        if len(entities) > 1 and not failed:
            failed = True
            raise ValidationError("simulated drawing history failure")
        original(entities, texts, styles)

    monkeypatch.setattr(session, "set_members", fail_once)
    try:
        dialog.tool_buttons["直线"].click()
        QTest.mouseClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
        )
        QTest.mouseClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((8, 5))
        )
        assert failed
        assert tuple(dialog.canvas.entities) == session.entities == (line,)
        assert not session.dirty and loaded.document.commands == commands
        assert "simulated drawing history failure" in dialog.status_label.text()
        QTest.keyClick(dialog.canvas, Qt.Key.Key_Escape)
        dialog.tool_buttons["直线"].click()
        QTest.mouseClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
        )
        QTest.mouseClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((8, 5))
        )
        assert len(session.entities) == 2 and tuple(dialog.canvas.entities) == session.entities
        QTest.keyClick(dialog.canvas, Qt.Key.Key_Escape)
        assert dialog.undo_local() and session.entities == (line,)
        assert dialog.redo_local() and len(session.entities) == 2
        assert dialog.save_definition() and len(loaded.document.commands) == len(commands) + 1
        saved = session.definition
        path = tmp_path / "block-drawing-retry.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert services.kernel.drawing_block_definitions == (saved,)
        reopened.bus.undo_operation()
        assert services.kernel.drawing_block_definitions == (definition,)
        reopened.bus.redo_operation()
        assert services.kernel.drawing_block_definitions == (saved,)
    finally:
        dialog.close()


def test_block_editor_creates_text_from_canvas(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox, QPushButton

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Text", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    button = next(item for item in dialog.findChildren(QPushButton) if item.text() == "单行文字")
    button.click()
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
    )
    assert dialog.text_tools.overlay.isVisible()
    dialog.text_tools.editor.setPlainText("Local text")
    QTest.keyClick(dialog.text_tools.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert len(session.texts) == 1 and session.texts[0].text == "Local text"
    assert services.kernel.drawing_block_definitions == (definition,)
    assert dialog.undo_local() and session.texts == ()
    dialog.close()


def test_close_prompts_when_text_edit_pending_before_first_commit(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox, QPushButton

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Pending", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.show()
    next(item for item in dialog.findChildren(QPushButton) if item.text() == "单行文字").click()
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
    )
    dialog.text_tools.editor.setPlainText("Uncommitted")
    assert not session.dirty and dialog.text_tools.pending
    monkeypatch.setattr(QMessageBox, "question", _cancel_close)
    dialog.close()
    assert dialog.isVisible() and dialog.text_tools.editor.toPlainText() == "Uncommitted"
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.close()
    assert not dialog.isVisible()
    assert services.kernel.drawing_block_definitions == (definition,)


def test_block_editor_text_input_keeps_native_undo(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox, QPushButton

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "TextUndo", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    next(item for item in dialog.findChildren(QPushButton) if item.text() == "单行文字").click()
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
    )
    editor = dialog.text_tools.editor
    editor.setFocus()
    QTest.keyClicks(editor, "abc")
    assert editor.toPlainText() == "abc"
    QTest.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert editor.toPlainText() == ""
    assert not session.dirty and len(loaded.document.commands) == 1
    QTest.keyClick(
        editor,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert editor.toPlainText() == "abc"
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert len(session.texts) == 1 and session.texts[0].text == "abc"
    assert dialog.undo_local() and session.texts == ()
    assert len(loaded.document.commands) == 1
    dialog.close()


def test_block_editor_layer_choice_applies_to_new_geometry_and_text(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox, QPushButton

    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Detail"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Layers", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(session, layers, services.kernel.drawing_text_styles)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    dialog.layer_combo.setCurrentText("Detail")
    dialog.tool_buttons["直线"].click()
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
    )
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((8, 5))
    )
    assert session.entities[-1].layer_name == "Detail"
    next(item for item in dialog.findChildren(QPushButton) if item.text() == "单行文字").click()
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 8))
    )
    dialog.text_tools.editor.setPlainText("Detail")
    QTest.keyClick(dialog.text_tools.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert session.texts[-1].layer_name == "Detail"
    dialog.close()


def test_block_editor_zero_layer_uses_instance_layer_permissions(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Insert"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Inherited", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), layer_name="Insert")
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    locked = layers.replace(replace(layers.get("0"), locked=True))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(session, locked, services.kernel.drawing_text_styles)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    assert not dialog.canvas.layer_table.get("0").locked
    assert dialog.canvas.replace_draft_entities((replace(line, end_mm=(4, 0)),))
    assert dialog.save_definition()
    assert services.kernel.drawing_layers.get("0").locked
    assert services.kernel.drawing_block_definitions[0].entities == (replace(line, end_mm=(4, 0)),)
    dialog.close()


def test_local_undo_refreshes_snap_geometry(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Snap", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    assert dialog.canvas.replace_draft_entities((replace(line, end_mm=(8, 0)),))
    dialog.canvas.set_snapping_enabled(True)
    dialog.canvas.set_grid_snapping_enabled(False)
    assert dialog.canvas.snap_annotation_point((8, 0)) == ((8, 0), "端点")
    assert dialog.undo_local()
    assert dialog.canvas.snap_annotation_point((2, 0)) == ((2, 0), "端点")
    assert dialog.canvas.snap_annotation_point((8, 0)) == ((8, 0), "")
    dialog.close()


def test_block_editor_refuses_locked_layer_and_preserves_pending_geometry(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Locked", locked=True)).add(
        SketchLayer("Open")
    )
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Choice", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(session, layers, services.kernel.drawing_text_styles)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    dialog.layer_combo.setCurrentText("Locked")
    assert dialog.layer_combo.currentText() == "0" and dialog.canvas.active_layer_name == "0"
    dialog.tool_buttons["直线"].click()
    QTest.mouseClick(
        dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen((5, 5))
    )
    assert dialog.canvas.has_pending_geometry
    dialog.layer_combo.setCurrentText("Open")
    assert dialog.layer_combo.currentText() == "0" and dialog.canvas.has_pending_geometry
    dialog.close()


@pytest.mark.parametrize("change", [{"locked": True}, {"visible": False}, {"frozen": True}])
def test_block_editor_applies_instance_permissions_to_nonzero_member_layer(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, change: dict[str, bool]
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Insert")).add(SketchLayer("Detail"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="Detail")
    definition = BlockDefinition(uuid4().hex, "Shared", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for layer in ("0", "Insert"):
        instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0), layer_name=layer)
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    restricted = layers.replace(replace(layers.get("Insert"), **change))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": restricted.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(session, restricted, services.kernel.drawing_text_styles)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    effective = dialog.canvas.layer_table.get("Detail")
    if change.get("locked"):
        assert effective.locked
        dialog.canvas.selected_entity_ids = {line.entity_id}
        dialog.canvas.begin_transform("move")
        assert "锁定" in dialog.canvas.message
        assert session.entities == (line,)
    else:
        assert not effective.displayed
        assert line not in dialog.canvas.selectable_entities()
    dialog.layer_combo.setCurrentText("Detail")
    assert dialog.canvas.active_layer_name != "Detail"
    assert services.kernel.drawing_layers == restricted
    dialog.close()


@pytest.mark.parametrize("change", [{"locked": True}, {"visible": False}, {"frozen": True}])
def test_block_editor_preserves_nonzero_member_layer_permissions(
    change: dict[str, bool],
) -> None:
    from mycad.core.sketch_layers import SketchLayer

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    layers = services.kernel.drawing_layers.add(SketchLayer("Detail"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (2, 0), layer_name="Detail")
    definition = BlockDefinition(uuid4().hex, "Shared", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    restricted = layers.replace(replace(layers.get("Detail"), **change))
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    local = session.local_layers(restricted)
    assert local.get("Detail") == restricted.get("Detail")
    assert local.get("0") == restricted.get("0")


def test_block_editor_retains_local_edits_after_instance_layer_changes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.persistence import save_document
    from mycad.core.sketch_layers import SketchLayer
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    layers = services.kernel.drawing_layers.add(SketchLayer("Insert"))
    loaded.bus.execute(
        "drawing.layers.set", {"layers": layers.to_mapping(), "dimension_layer": "DIM"}, "local"
    )
    line = LineEntity(uuid4().hex, (0, 0), (3, 0))
    definition = BlockDefinition(uuid4().hex, "SharedLayer", (line,), ())
    instances = (
        BlockInstance(uuid4().hex, definition.definition_id, (0, 0)),
        BlockInstance(uuid4().hex, definition.definition_id, (10, 0), layer_name="Insert"),
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for instance in instances:
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    getattr(window, _SYNC_METHOD)()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instances[0].instance_id}
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    dialog = window.active_block_editor()
    assert dialog is not None
    modified = replace(line, end_mm=(7, 0))
    try:
        assert dialog.canvas.replace_draft_entities((modified,))
        locked = layers.replace(replace(layers.get("Insert"), locked=True))
        loaded.bus.execute(
            "drawing.layers.set", {"layers": locked.to_mapping(), "dimension_layer": "DIM"}, "local"
        )
        history = tuple(loaded.document.commands)
        dialog.command_input.setText("BSAVE")
        QTest.keyClick(dialog.command_input, Qt.Key.Key_Return)
        assert "过期" in dialog.status_label.text() or "变化" in dialog.status_label.text()
        assert dialog.session.dirty and dialog.session.entities == (modified,)
        assert tuple(loaded.document.commands) == history
        assert services.kernel.drawing_block_definitions == (definition,)
        assert services.kernel.drawing_block_instances == instances
        assert dialog.undo_local() and dialog.session.entities == (line,)
        assert dialog.redo_local() and dialog.session.entities == (modified,)
        dialog.close()
        path = tmp_path / "stale-block-layer.my2d"
        save_document(loaded.document, path)
        reopened = app.open_app_document(services, path)
        assert services.kernel.drawing_block_definitions == (definition,)
        assert services.kernel.drawing_block_instances == instances
        assert services.kernel.drawing_layers.get("Insert").locked
        reopened.bus.undo_operation()
        assert not services.kernel.drawing_layers.get("Insert").locked
        reopened.bus.redo_operation()
        assert services.kernel.drawing_layers.get("Insert").locked
    finally:
        if dialog.isVisible():
            dialog.close()


def test_close_save_with_expired_source_keeps_editor_open(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Stale", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: False
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.canvas.replace_draft_entities((replace(line, end_mm=(4, 0)),))

    def save_choice(*_args: object, **_kwargs: object) -> object:
        return QMessageBox.StandardButton.Save

    monkeypatch.setattr(QMessageBox, "question", save_choice)
    dialog.close()
    assert dialog.isVisible() and session.dirty and "过期" in dialog.status_label.text()
    assert session.entities == (replace(line, end_mm=(4, 0)),)
    assert services.kernel.drawing_block_definitions == (definition,)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.close()


def test_block_editor_grip_preview_is_one_undoable_step(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    definition = BlockDefinition(uuid4().hex, "Grip", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    history = tuple(loaded.document.commands)
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.resize(900, 650)
    dialog.show()
    qtbot.waitExposed(dialog)
    canvas = dialog.canvas
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {line.entity_id}
    start = canvas.local_to_screen((10, 0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, canvas.local_to_screen((12, 0)), delay=30)
    QTest.mouseMove(canvas, canvas.local_to_screen((14, 0)), delay=30)
    assert tuple(canvas.entities) != (line,)
    assert session.entities == (line,) and not session.dirty
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.entities == [line] and session.entities == (line,)
    assert not dialog.undo_local()
    canvas.selected_entity_ids = {line.entity_id}
    start = canvas.local_to_screen((10, 0))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas, canvas.local_to_screen((12, 0)), delay=30)
    QTest.mouseMove(canvas, canvas.local_to_screen((14, 0)), delay=30)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((14, 0)))
    changed = session.entities
    assert changed != (line,) and tuple(canvas.entities) == changed
    assert dialog.undo_local() and session.entities == (line,)
    assert not dialog.undo_local()
    assert dialog.redo_local() and session.entities == changed
    assert tuple(loaded.document.commands) == history
    assert dialog.save_definition()
    assert services.kernel.drawing_block_definitions[0].entities == changed
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (definition,)


def test_block_editor_retains_unrenderable_change_after_save_failure(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.drawing_blocks import expand_block
    from mycad.core.sketch import CircleEntity

    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    circle = CircleEntity(uuid4().hex, (0, 0), 1)
    definition = BlockDefinition(uuid4().hex, "Small", (circle,), ())
    instances = (
        BlockInstance(uuid4().hex, definition.definition_id, (0, 0)),
        BlockInstance(uuid4().hex, definition.definition_id, (10, 0), scale=1e-6),
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for instance in instances:
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    history = tuple(loaded.document.commands)
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.show()
    tiny = replace(circle, radius_mm=1e-7)
    assert dialog.canvas.replace_draft_entities((tiny,))
    assert not dialog.save_definition()
    assert "展开" in dialog.status_label.text()
    assert dialog.isVisible() and session.dirty and session.entities == (tiny,)
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == instances
    assert tuple(loaded.document.commands) == history
    fixed = replace(circle, radius_mm=2)
    assert dialog.canvas.replace_draft_entities((fixed,))
    assert dialog.save_definition()
    updated = services.kernel.drawing_block_definitions[0]
    assert updated.entities == (fixed,)
    assert all(
        expand_block(updated, item, services.kernel.drawing_text_styles).entities
        for item in instances
    )
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (definition,)


def test_block_editor_rejects_excluded_commands_and_keeps_drawing_local(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.core.drawing_blocks import expand_block
    from mycad.core.persistence import save_document

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    source = LineEntity(uuid4().hex, (-5, -5), (-3, -5))
    definition = BlockDefinition(uuid4().hex, "LocalOnly", (source,), ())
    instances = (
        BlockInstance(uuid4().hex, definition.definition_id, (0, 0)),
        BlockInstance(uuid4().hex, definition.definition_id, (10, 10), 30, 2),
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for item in instances:
        loaded.bus.execute("drawing.block_instance.insert", item.to_mapping(), "local")
    before = app.drawing_collection_snapshot(services)
    history = tuple(loaded.document.commands)
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.tool_buttons["直线"].click()
    for point in ((0, 0), (10, 0), (10, 0), (10, 8)):
        QTest.mouseClick(
            dialog.canvas, Qt.MouseButton.LeftButton, pos=dialog.canvas.local_to_screen(point)
        )
    assert len(session.entities) == 3 and not dialog.canvas.constraints
    local = (session.entities, session.texts)
    assert session.dirty and app.drawing_collection_snapshot(services) == before
    for command in ("GROUP", "BLOCK", "INSERT", "DIM", "ARRAY", "TOLERANCE"):
        dialog.command_input.setText(command)
        QTest.keyClick(dialog.command_input, Qt.Key.Key_Return)
        assert "块编辑支持" in dialog.status_label.text()
        assert (session.entities, session.texts) == local and not dialog.canvas.constraints
        assert tuple(loaded.document.commands) == history
    assert dialog.save_definition() and len(loaded.document.commands) == len(history) + 1
    updated = services.kernel.drawing_block_definitions[0]
    assert updated.entities == local[0]
    assert all(
        len(expand_block(updated, item, services.kernel.drawing_text_styles).entities) == 3
        for item in instances
    )
    dialog.close()
    path = tmp_path / "block-local-tools.my2d"
    save_document(loaded.document, path)
    reopened = app.open_app_document(services, path)
    reopened.bus.undo_operation()
    assert app.drawing_collection_snapshot(services) == before
    reopened.bus.redo_operation()
    assert services.kernel.drawing_block_definitions == (updated,)


@pytest.mark.parametrize("kind", ["geometry", "text", "mixed"])
def test_block_editor_fits_far_contents_on_open_and_on_demand(qtbot: QtBot, kind: str) -> None:
    from PySide6.QtCore import QRectF

    from mycad.core.drawing_text import DrawingText

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (1e9, 1e9), (1e9 + 10, 1e9))
    text = DrawingText(uuid4().hex, "Block", (1e9 + 2, 1e9 + 2))
    definition = BlockDefinition(
        uuid4().hex,
        "Far content",
        (line,) if kind in ("geometry", "mixed") else (),
        (text,) if kind in ("text", "mixed") else (),
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    before = tuple(loaded.document.commands)
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    point = (1e9 + 2, 1e9 + 2 if kind != "geometry" else 1e9)
    assert QRectF(dialog.canvas.rect()).contains(dialog.canvas.local_to_screen_precise(point))
    assert dialog.canvas.zoom_view_window((-10, -10), (10, 10))
    assert not QRectF(dialog.canvas.rect()).contains(dialog.canvas.local_to_screen_precise(point))
    dialog.tool_buttons["适应窗口"].click()
    assert QRectF(dialog.canvas.rect()).contains(dialog.canvas.local_to_screen_precise(point))
    assert not session.dirty and tuple(loaded.document.commands) == before
    dialog.close()


def test_bedit_command_opens_far_definition_ready_for_canvas_edit(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtTest import QTest

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (1e9, 1e9), (1e9 + 10, 1e9))
    definition = BlockDefinition(uuid4().hex, "Far edit", (line,), ())
    first = BlockInstance(uuid4().hex, definition.definition_id, (0, 0))
    second = BlockInstance(uuid4().hex, definition.definition_id, (20, 30), 30, 2)
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for instance in (first, second):
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {first.instance_id}
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    block_editor = window.active_block_editor()
    assert block_editor is not None
    canvas = block_editor.canvas
    midpoint = (1e9 + 5, 1e9)
    assert QRectF(canvas.rect()).contains(canvas.local_to_screen_precise(midpoint))
    assert canvas.set_tool("选择元素")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(midpoint))
    assert canvas.selected_entity_ids == {line.entity_id}
    block_editor.tool_buttons["移动"].click()
    canvas.add_coordinate_point((1e9, 1e9), exact_point=True)
    canvas.add_coordinate_point((1e9 + 3, 1e9 + 1), exact_point=True)
    moved = replace(line, start_mm=(1e9 + 3, 1e9 + 1), end_mm=(1e9 + 13, 1e9 + 1))
    assert block_editor.session.entities == (moved,)
    assert services.kernel.drawing_block_definitions == (definition,)
    assert block_editor.save_definition()
    assert services.kernel.drawing_block_definitions[0].entities == (moved,)
    assert services.kernel.drawing_block_instances == (first, second)
    block_editor.close()
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (definition,)


def test_block_save_backend_failure_keeps_local_edits_and_can_retry(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Callable, Mapping
    from typing import cast

    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Retry", (line,), ())
    instances = tuple(
        BlockInstance(uuid4().hex, definition.definition_id, (offset, 0)) for offset in (0, 10)
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    for instance in instances:
        loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    before = loaded.document.commands
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)

    def save_choice(*_args: object, **_kwargs: object) -> object:
        return QMessageBox.StandardButton.Save

    monkeypatch.setattr(QMessageBox, "question", save_choice)
    dialog.show()
    modified = replace(line, end_mm=(4, 0))
    assert dialog.canvas.replace_draft_entities((modified,))
    apply = cast(
        "Callable[[object, str, Mapping[str, object]], None]",
        vars(type(services.kernel))["_apply_drawing_block"],
    )
    failed = False

    def fail(command_id: str, params: Mapping[str, object]) -> None:
        nonlocal failed
        if command_id == "drawing.block.update" and not failed:
            failed = True
            raise RuntimeError("simulated backend failure")
        apply(services.kernel, command_id, params)

    monkeypatch.setattr(services.kernel, "_apply_drawing_block", fail)
    dialog.close()
    assert dialog.isVisible() and session.dirty and session.entities == (modified,)
    assert "simulated backend failure" in dialog.status_label.text()
    assert loaded.document.commands == before
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == instances
    assert dialog.undo_local() and session.entities == (line,)
    assert dialog.redo_local() and session.entities == (modified,)
    assert dialog.save_definition() and not session.dirty
    assert services.kernel.drawing_block_definitions[0].entities == (modified,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (definition,)
    assert services.kernel.drawing_block_instances == instances
    dialog.close()


def test_late_block_save_failure_allows_retry_without_losing_undo_history(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Callable
    from typing import cast

    from PySide6.QtWidgets import QMessageBox

    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "LateRetry", (line,), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    before = loaded.document.commands
    revision = loaded.document.revision
    session = DrawingBlockEditorSession(
        services, loaded, definition.definition_id, is_current_document=lambda: True
    )
    dialog = DrawingBlockEditorDialog(
        session, services.kernel.drawing_layers, services.kernel.drawing_text_styles
    )
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    dialog.show()
    modified = replace(line, end_mm=(4, 0))
    assert dialog.canvas.replace_draft_entities((modified,))
    record = cast("Callable[[object, object], None]", vars(type(loaded.bus))["_record_operation"])
    failed = False

    def fail_once(before_state: object) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("simulated late history failure")
        record(loaded.bus, before_state)

    monkeypatch.setattr(loaded.bus, "_record_operation", fail_once)
    assert not dialog.save_definition() and failed
    assert loaded.document.revision > revision and loaded.document.commands == before
    assert session.dirty and session.entities == (modified,)
    assert services.kernel.drawing_block_definitions == (definition,)
    assert dialog.save_definition(), dialog.status_label.text()
    assert services.kernel.drawing_block_definitions[0].entities == (modified,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (definition,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == ()
    dialog.close()


def test_bedit_rejects_unfinished_datum_placement(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QInputDialog

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Entry", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    tolerance = editor.canvas.geometric_tolerance_tools
    assert tolerance is not None

    def datum_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "A", True

    monkeypatch.setattr(QInputDialog, "getText", datum_name)
    tolerance.begin_datum()
    assert tolerance.pending
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    before = loaded.document.commands
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert window.active_block_editor() is None
    assert tolerance.pending and loaded.document.commands == before
    assert "完成" in editor.status_label.text() or "完成" in window.status_command.text()
    tolerance.cancel()
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    block_editor = window.active_block_editor()
    assert block_editor is not None
    block_editor.close()


@pytest.mark.parametrize("close_target", ("window", "document"))
def test_closing_main_document_respects_unsaved_block_editor(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, close_target: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.persistence import save_document
    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Close", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    entry.loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    entry.loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    entry.path = tmp_path / "block-close.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    editor.canvas.set_source_context_revision(entry.loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    block_editor = window.active_block_editor()
    assert block_editor is not None
    modified = replace(line, end_mm=(5, 0))
    assert block_editor.canvas.replace_draft_entities((modified,))
    questions: list[str] = []

    def cancel(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        questions.append(str(message))
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)
    if close_target == "window":
        window.close()
    else:
        window.close_active_document()
    assert questions and window.isVisible() and block_editor.isVisible()
    assert block_editor.session.dirty and block_editor.session.entities == (modified,)
    assert entry.services.kernel.drawing_block_definitions == (definition,)
    assert window.document_session is not None
    assert window.document_session.find(entry.loaded.document.document_id) is entry
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    block_editor.close()


@pytest.mark.parametrize("close_target", ("window", "document"))
def test_closing_main_document_saves_block_before_document_prompt(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, close_target: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.persistence import save_document
    from mycad.ui.document_session import DocumentSession, SessionDocument
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    entry = window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "CloseSave", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    entry.loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    entry.loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    entry.path = tmp_path / "block-close-save.my2d"
    save_document(entry.loaded.document, entry.path)
    entry.loaded.document.mark_clean()
    editor.canvas.set_source_context_revision(entry.loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    block_editor = window.active_block_editor()
    assert block_editor is not None
    modified = replace(line, end_mm=(5, 0))
    assert block_editor.canvas.replace_draft_entities((modified,))
    prompts: list[tuple[SessionDocument, ...]] = []

    def save_block(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Save

    def cancel_document(entries: tuple[SessionDocument, ...]) -> None:
        prompts.append(entries)

    monkeypatch.setattr(QMessageBox, "question", save_block)
    monkeypatch.setattr(window, "_ask_session_close_dialog", cancel_document)
    if close_target == "window":
        window.close()
    else:
        window.close_active_document()
    assert prompts == [(entry,)] and window.isVisible()
    assert window.active_block_editor() is None
    assert entry.loaded.document.is_dirty
    assert entry.services.kernel.drawing_block_definitions[0].entities == (modified,)
    entry.loaded.bus.undo_operation()
    assert entry.services.kernel.drawing_block_definitions == (definition,)


def test_closing_unrelated_document_keeps_block_editor_open(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from mycad.ui.document_session import DocumentSession
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    source = window.new_session_document("sketch")
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "OtherDocument", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    source.loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    source.loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(source.loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    block_editor = window.active_block_editor()
    assert block_editor is not None
    modified = replace(line, end_mm=(5, 0))
    assert block_editor.canvas.replace_draft_entities((modified,))
    questions: list[str] = []

    def cancel(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        questions.append(str(message))
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)
    other = window.new_session_document("sketch", placeholder=True)
    assert window.loaded_document() is other.loaded
    window.close_active_document()
    assert window.document_session is not None
    assert window.document_session.find(other.loaded.document.document_id) is None
    assert window.loaded_document() is source.loaded
    assert not questions and window.active_block_editor() is block_editor
    assert block_editor.session.dirty and block_editor.session.entities == (modified,)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    block_editor.close()


@pytest.mark.parametrize("action", ("new", "open"))
def test_replacing_single_document_respects_unsaved_block_editor(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    other_services = app.fork_app_services(services)
    other = app.new_workspace_document(other_services, kind="sketch")
    path = tmp_path / "other.my2d"
    save_document(other.document, path)
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Single", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.document.mark_clean()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    block_editor = window.active_block_editor()
    assert block_editor is not None
    modified = replace(line, end_mm=(5, 0))
    assert block_editor.canvas.replace_draft_entities((modified,))
    questions: list[str] = []

    def cancel(
        _parent: object, _title: object, message: object, *_args: object, **_kwargs: object
    ) -> QMessageBox.StandardButton:
        questions.append(str(message))
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)
    if action == "new":
        window.act_new_drawing.trigger()
    else:
        window.open_document_path(path)
    assert questions and window.loaded_document() is loaded
    assert window.active_block_editor() is block_editor
    assert block_editor.session.dirty and block_editor.session.entities == (modified,)
    assert services.kernel.drawing_block_definitions == (definition,)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
    block_editor.close()


@pytest.mark.parametrize("action", ("new", "open"))
def test_replacing_single_document_prompts_for_saved_block_change(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from mycad.core.persistence import save_document
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    other_services = app.fork_app_services(services)
    other = app.new_workspace_document(other_services, kind="sketch")
    path = tmp_path / "other.my2d"
    save_document(other.document, path)
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "SingleSave", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    loaded.document.mark_clean()
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    block_editor = window.active_block_editor()
    assert block_editor is not None
    modified = replace(line, end_mm=(5, 0))
    assert block_editor.canvas.replace_draft_entities((modified,))
    prompts: list[str] = []

    def save_block(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Save

    def cancel_document() -> str:
        prompts.append("document")
        return "cancel"

    monkeypatch.setattr(QMessageBox, "question", save_block)
    monkeypatch.setattr(window, "_ask_save_dialog", cancel_document)
    if action == "new":
        window.act_new_drawing.trigger()
    else:
        window.open_document_path(path)
    assert prompts == ["document"] and window.loaded_document() is loaded
    assert window.active_block_editor() is None and loaded.document.is_dirty
    assert services.kernel.drawing_block_definitions[0].entities == (modified,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (definition,)


def test_block_save_waits_for_running_document_worker(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
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
    definition = BlockDefinition(uuid4().hex, "Busy", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    block_editor = window.active_block_editor()
    assert block_editor is not None

    def save_choice(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Save

    monkeypatch.setattr(QMessageBox, "question", save_choice)
    modified = replace(line, end_mm=(5, 0))
    assert block_editor.canvas.replace_draft_entities((modified,))
    before = loaded.document.commands
    release = Event()
    started = Event()

    def worker() -> None:
        started.set()
        release.wait(10)

    assert unit.submit(worker, operation="test-running-worker", session_id=unit.session_id)
    try:
        qtbot.waitUntil(started.is_set, timeout=5000)
        assert unit.is_busy
        block_editor.close()
        assert block_editor.isVisible()
        assert "忙" in block_editor.status_label.text()
        assert loaded.document.commands == before
        assert services.kernel.drawing_block_definitions == (definition,)
        assert block_editor.session.dirty and block_editor.session.entities == (modified,)
    finally:
        release.set()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    assert block_editor.save_definition()
    assert services.kernel.drawing_block_definitions[0].entities == (modified,)
    loaded.bus.undo_operation()
    assert services.kernel.drawing_block_definitions == (definition,)
    block_editor.close()


@pytest.mark.parametrize("draft_kind", ("geometry", "datum"))
def test_block_save_rejects_draft_started_after_editor_open(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, draft_kind: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QInputDialog

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "DraftAfterEdit", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    block_editor = window.active_block_editor()
    assert block_editor is not None
    modified = replace(line, end_mm=(5, 0))
    assert block_editor.canvas.replace_draft_entities((modified,))
    tolerance = editor.canvas.geometric_tolerance_tools
    assert tolerance is not None
    if draft_kind == "geometry":
        draft = LineEntity(uuid4().hex, (4, 0), (6, 0))
        assert editor.canvas.replace_draft_entities((draft,))
    else:

        def datum_name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
            return "A", True

        monkeypatch.setattr(QInputDialog, "getText", datum_name)
        tolerance.begin_datum()
        assert tolerance.pending
    before = loaded.document.commands
    assert not block_editor.save_definition()
    assert "草稿" in block_editor.status_label.text()
    assert loaded.document.commands == before
    assert services.kernel.drawing_block_definitions == (definition,)
    assert block_editor.session.dirty and block_editor.session.entities == (modified,)
    if draft_kind == "geometry":
        assert editor.canvas.undo_last_operation()
    else:
        tolerance.cancel()
    assert block_editor.save_definition()
    assert services.kernel.drawing_block_definitions[0].entities == (modified,)
    block_editor.close()


def test_block_save_checks_reopened_main_canvas_for_draft(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Callable
    from typing import cast

    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (2, 0))
    definition = BlockDefinition(uuid4().hex, "Reopened", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    block_editor = window.active_block_editor()
    assert block_editor is not None
    modified = replace(line, end_mm=(5, 0))
    assert block_editor.canvas.replace_draft_entities((modified,))
    editor.reject()
    assert window.active_sketch_dialog() is None
    start = cast("Callable[[MainWindow], None]", vars(type(window))["_on_sketch_start"])
    start(window)
    reopened = window.active_sketch_dialog()
    assert reopened is not None and reopened is not editor
    draft = LineEntity(uuid4().hex, (4, 0), (6, 0))
    assert reopened.canvas.replace_draft_entities((draft,))
    before = loaded.document.commands
    assert not block_editor.save_definition()
    assert "草稿" in block_editor.status_label.text()
    assert loaded.document.commands == before
    assert services.kernel.drawing_block_definitions == (definition,)
    assert block_editor.session.dirty and block_editor.session.entities == (modified,)
    assert reopened.canvas.undo_last_operation()
    assert block_editor.save_definition()
    assert services.kernel.drawing_block_definitions[0].entities == (modified,)
    assert reopened.canvas.source_context_revision == loaded.document.revision
    displayed = reopened.canvas.drawing_block_view().geometry
    assert len(displayed) == 1 and displayed[0].instance_id == instance.instance_id
    assert isinstance(displayed[0].entity, LineEntity)
    assert displayed[0].entity.end_mm == (7, 2)
    block_editor.close()


def test_block_edit_remains_available_when_new_main_draft_is_committed(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
    monkeypatch.setattr(QMessageBox, "question", _discard_close)
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
    definition = BlockDefinition(uuid4().hex, "EditDuringDraft", (line,), ())
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.set_source_context_revision(loaded.document.revision)
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    editor.drawing_command_bar.input.setText("BEDIT")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    block_editor = window.active_block_editor()
    assert block_editor is not None
    modified = replace(line, end_mm=(5, 0))
    assert block_editor.canvas.replace_draft_entities((modified,))
    draft = LineEntity(uuid4().hex, (4, 0), (6, 0))
    assert editor.canvas.replace_draft_entities((draft,))
    assert not block_editor.save_definition()
    editor.finish_sketch()
    qtbot.waitUntil(
        lambda: not unit.is_busy and window.active_sketch_dialog() is not editor, timeout=15000
    )
    after_commit = loaded.document.commands
    assert any(draft in sketch.entities for sketch in services.kernel.sketches)
    assert block_editor.isVisible()
    assert not block_editor.save_definition()
    assert "过期" in block_editor.status_label.text()
    assert block_editor.session.dirty and block_editor.session.entities == (modified,)
    assert services.kernel.drawing_block_definitions == (definition,)
    assert loaded.document.commands == after_commit
    assert block_editor.undo_local()
    assert block_editor.redo_local()
    assert block_editor.session.entities == (modified,)
    block_editor.close()


def test_bedit_waits_for_running_document_worker(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Callable
    from threading import Event
    from typing import cast

    from mycad.ui.main_window import MainWindow
    from mycad.ui.sketch_editor import SketchEditorDialog

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
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
        uuid4().hex, "BusyOpen", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    instance = BlockInstance(uuid4().hex, definition.definition_id, (2, 2))
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    loaded.bus.execute("drawing.block_instance.insert", instance.to_mapping(), "local")
    editor.canvas.selected_block_instance_ids = {instance.instance_id}
    release, started = Event(), Event()

    def worker() -> None:
        started.set()
        release.wait(10)

    edit_block = cast(
        "Callable[[MainWindow, SketchEditorDialog], None]",
        vars(type(window))["_edit_drawing_block"],
    )
    assert unit.submit(worker, operation="test-running-worker", session_id=unit.session_id)
    try:
        qtbot.waitUntil(started.is_set, timeout=5000)
        edit_block(window, editor)
        assert window.active_block_editor() is None and "忙" in editor.status_label.text()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)
    edit_block(window, editor)
    block_editor = window.active_block_editor()
    assert block_editor is not None
    block_editor.close()


def test_bedit_rechecks_worker_after_definition_picker(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Callable
    from threading import Event
    from typing import cast

    from PySide6.QtWidgets import QInputDialog

    from mycad.ui.main_window import MainWindow
    from mycad.ui.sketch_editor import SketchEditorDialog

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_gl)
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
        uuid4().hex, "Picker", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    release = Event()

    def worker() -> None:
        release.wait(10)

    def choose_and_start(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        assert unit.submit(worker, operation="test-picker-worker", session_id=unit.session_id)
        return definition.name, True

    monkeypatch.setattr(QInputDialog, "getItem", choose_and_start)
    edit_block = cast(
        "Callable[[MainWindow, SketchEditorDialog], None]",
        vars(type(window))["_edit_drawing_block"],
    )
    try:
        edit_block(window, editor)
        assert unit.is_busy and window.active_block_editor() is None
        assert "忙" in editor.status_label.text()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)

    def choose(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return definition.name, True

    monkeypatch.setattr(QInputDialog, "getItem", choose)
    edit_block(window, editor)
    block_editor = window.active_block_editor()
    assert block_editor is not None
    block_editor.close()
