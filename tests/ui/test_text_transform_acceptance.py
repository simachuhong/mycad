# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""User-operation undo/redo for text alone and mixed geometry."""

from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.drawing_text import DrawingText
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.main_window import MainWindow


@pytest.mark.parametrize("mode", ["text", "draft", "saved"])
@pytest.mark.parametrize("operation", ["move", "copy", "rotate", "scale", "mirror", "erase"])
def test_text_transform_is_one_undoable_operation(qtbot: QtBot, mode: str, operation: str) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    tools = canvas.text_tools
    assert tools is not None and tools.execute is not None
    item = DrawingText(uuid4().hex, "ABC", (1, 10), height_mm=4)
    assert tools.execute("drawing.text.add", item.to_mapping())
    line = LineEntity(uuid4().hex, (2, 3), (7, 3))
    if mode == "saved":
        sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (line,))
        app.commit_new_sketch(services, loaded, sketch, session_identity=0)
        editor.set_context_sketches(services.kernel.sketches)
    elif mode == "draft":
        canvas.entities = [line]
    if mode != "text":
        canvas.selected_entity_ids = {line.entity_id}
    tools.sync(services.kernel.drawing_texts, services.kernel.drawing_text_styles)
    tools.selected_ids = {item.text_id}
    canvas.copy_mode = 1
    if operation == "erase":
        assert canvas.delete_selected()
    else:
        canvas.begin_transform(operation, keep_source=False)
        assert canvas.active_transform == operation
        canvas.add_coordinate_point((0, 0), exact_point=True)
        if operation == "rotate":
            assert canvas.apply_rotation_angle(90)
        elif operation == "scale":
            assert canvas.apply_scale_factor(2)
        else:
            canvas.add_coordinate_point(
                (5, 0) if operation == "mirror" else (5, 5), exact_point=True
            )
    qtbot.waitUntil(
        lambda: not window.execution_unit or not window.execution_unit.is_busy, timeout=10000
    )
    actual = services.kernel.drawing_texts
    if operation == "erase":
        assert not actual
    elif operation == "copy":
        assert len(actual) == 2 and actual[0] == item
        assert actual[1].text_id != item.text_id
        assert actual[1].position_mm == pytest.approx((6, 15), abs=1e-8)
    else:
        expected = {"move": (6, 15), "rotate": (-10, 1), "scale": (2, 20), "mirror": (1, -10)}
        assert len(actual) == 1 and actual[0].position_mm == pytest.approx(
            expected[operation], abs=1e-8
        )
    after_text = actual
    after_draft = tuple(canvas.entities)
    after_sketches = services.kernel.sketches
    if mode != "text":
        geometry = (
            after_draft
            if mode == "draft"
            else tuple(entity for sketch in after_sketches for entity in sketch.entities)
        )
        if operation == "erase":
            assert not geometry
        else:
            if operation == "copy":
                assert len(geometry) == 2 and line in geometry
                transformed = next(
                    entity for entity in geometry if entity.entity_id != line.entity_id
                )
            else:
                assert len(geometry) == 1
                transformed = geometry[0]
            assert isinstance(transformed, LineEntity)
            expected_start, expected_end = {
                "move": ((7, 8), (12, 8)),
                "copy": ((7, 8), (12, 8)),
                "rotate": ((-3, 2), (-3, 7)),
                "scale": ((4, 6), (14, 6)),
                "mirror": ((2, -3), (7, -3)),
            }[operation]
            assert transformed.start_mm == pytest.approx(expected_start, abs=1e-8)
            assert transformed.end_mm == pytest.approx(expected_end, abs=1e-8)
    window.request_undo()
    qtbot.waitUntil(
        lambda: not window.execution_unit or not window.execution_unit.is_busy, timeout=10000
    )
    assert services.kernel.drawing_texts == (item,), window.status_command.text()
    if mode == "draft":
        assert tuple(canvas.entities) == (line,)
    elif mode == "saved":
        assert services.kernel.sketches[0].entities == (line,)
    window.request_redo()
    qtbot.waitUntil(
        lambda: not window.execution_unit or not window.execution_unit.is_busy, timeout=10000
    )
    assert services.kernel.drawing_texts == after_text, window.status_command.text()
    assert tuple(canvas.entities) == after_draft
    assert services.kernel.sketches == after_sketches


@pytest.mark.parametrize("condition", ["tangency", "array", "stale"])
def test_mixed_transform_rejects_complex_or_stale_source_without_mutation(
    qtbot: QtBot, condition: str
) -> None:
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    tools = canvas.text_tools
    assert tools is not None and tools.execute is not None
    item = DrawingText(uuid4().hex, "ABC", (1, 10))
    assert tools.execute("drawing.text.add", item.to_mapping())
    line = LineEntity(uuid4().hex, (2, 3), (7, 3))
    assert canvas.replace_draft_entities((line,))
    if condition == "tangency":
        canvas.pending_cross_tangencies = [(line.entity_id, uuid4().hex)]
    elif condition == "array":
        canvas.selected_entity_ids = {line.entity_id}
        command = editor.drawing_command_bar.input
        for value in ("ARRAYRECT", "", "1", "2", "8", "AS", "Y", ""):
            command.setText(value)
            QTest.keyClick(command, Qt.Key.Key_Return)
        assert canvas.pending_associative_arrays
    canvas.selected_entity_ids = {line.entity_id}
    tools.sync(services.kernel.drawing_texts, services.kernel.drawing_text_styles)
    tools.selected_ids = {item.text_id}
    before = (
        loaded.document.commands,
        services.kernel.drawing_texts,
        tuple(canvas.entities),
        tuple(canvas.pending_cross_tangencies),
        tuple(canvas.pending_associative_arrays),
    )
    canvas.begin_transform("move")
    canvas.add_coordinate_point((0, 0), exact_point=True)
    if condition == "stale":
        provider = canvas.source_revision_provider
        assert provider is not None
        canvas.source_revision_provider = lambda: provider() + 1
    canvas.add_coordinate_point((5, 5), exact_point=True)
    qtbot.waitUntil(
        lambda: not window.execution_unit or not window.execution_unit.is_busy, timeout=10000
    )
    assert (
        loaded.document.commands,
        services.kernel.drawing_texts,
        tuple(canvas.entities),
        tuple(canvas.pending_cross_tangencies),
        tuple(canvas.pending_associative_arrays),
    ) == before
    message = canvas.message if condition == "stale" else editor.status_label.text()
    assert "变化" in message if condition == "stale" else "关联" in message
