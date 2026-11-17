# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Common construction properties remain atomic across draft and saved geometry."""

from typing import Literal
from uuid import uuid4

import pytest
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.sketch import LineEntity, Sketch, WorkPlaneFrame
from mycad.ui.main_window import MainWindow
from mycad.ui.viewport import GLViewport


def test_batch_construction_changes_mixed_selection_and_undoes(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    def skip_viewport_paint(self: GLViewport) -> None:
        pass

    monkeypatch.setattr(GLViewport, "paintGL", skip_viewport_paint)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    saved = LineEntity(uuid4().hex, (0, 0), (10, 0))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    draft = LineEntity(uuid4().hex, (0, 5), (10, 5))
    assert editor.canvas.replace_draft_entities((draft,))
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {saved.entity_id, draft.entity_id}
    editor.canvas.changed.emit()
    combo = editor.property_construction_combo
    assert combo is not None
    combo.activated.emit(combo.findData(True))
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.sketches[0].entities[0].construction,
        timeout=15000,
    )
    assert editor.canvas.entities[0].construction
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert not services.kernel.sketches[0].entities[0].construction
    assert not editor.canvas.entities[0].construction
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy and not unit.is_delivering_result, timeout=10000)
    assert services.kernel.sketches[0].entities[0].construction
    assert editor.canvas.entities[0].construction


@pytest.mark.parametrize("source", ["user", "inferred"])
def test_construction_preserves_user_dimensions_on_draft(
    qtbot: QtBot, source: Literal["user", "inferred"]
) -> None:
    from mycad.core.sketch_constraints import SketchConstraint, SketchGeometryReference

    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    dimension = SketchConstraint(
        uuid4().hex,
        "length",
        (SketchGeometryReference(line.entity_id, "geometry"),),
        10,
        "mm",
        driving=False,
        source=source,
    )
    editor.canvas.constraints.append(dimension)
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    combo = editor.property_construction_combo
    assert combo is not None
    combo.activated.emit(combo.findData(True))
    assert editor.canvas.entities[0].construction
    assert editor.canvas.constraints == [dimension]
    editor.canvas.undo_last_operation()
    assert editor.canvas.entities[0] == line
    assert editor.canvas.constraints == [dimension]


@pytest.mark.parametrize("condition", ["locked", "stale"])
def test_construction_rejects_locked_or_stale_selection(
    qtbot: QtBot, monkeypatch: MonkeyPatch, condition: str
) -> None:
    from mycad.core.sketch import SketchLayer

    def skip_viewport_paint(self: GLViewport) -> None:
        pass

    monkeypatch.setattr(GLViewport, "paintGL", skip_viewport_paint)
    services = app.build_app(discoverers=())
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    line = LineEntity(uuid4().hex, (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((line,))
    if condition == "locked":
        layers = editor.layer_table.replace(SketchLayer("0", locked=True))
        editor.set_document_layers(layers, "DIM")
    editor.canvas.set_tool("选择元素")
    editor.canvas.selected_entity_ids = {line.entity_id}
    editor.canvas.changed.emit()
    combo = editor.property_construction_combo
    assert combo is not None
    if condition == "stale":
        saved = LineEntity(uuid4().hex, (0, 5), (10, 5))
        app.commit_new_sketch(
            services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (saved,)), session_identity=0
        )
    before = tuple(loaded.document.commands)
    combo.activated.emit(combo.findData(True))
    assert editor.canvas.entities[0] == line
    assert tuple(loaded.document.commands) == before
    assert ("锁定" if condition == "locked" else "变化") in editor.status_label.text()
