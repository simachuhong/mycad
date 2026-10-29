# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The desktop routes workspaces to independently owned editable documents."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.drawing import DrawingView
from mycad.core.drawing_codec import drawing_object_mapping
from mycad.ui.main_window import MainWindow


def managed_window(qtbot: QtBot) -> MainWindow:
    from mycad.ui.document_session import DocumentSession

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    qtbot.addWidget(window)
    window.bind_document(app.new_workspace_document(services, kind="part"))
    return window


def test_workspaces_have_independent_history_and_keep_draft(qtbot: QtBot) -> None:
    window = managed_window(qtbot)
    model = window.loaded_document()
    assert model is not None
    model.bus.execute("feature.box", {"size_x": 4, "size_y": 5, "size_z": 6}, "local")
    assert window.viewport is not None
    window.viewport.refresh()
    assert window.document_session is not None and window.document_session.active is not None
    assert window.viewport.select_body(window.document_session.active.services.kernel.body_ids[0])
    selection = window.viewport.selection()
    window.workspace_tabs.activate("sketch")
    sketch = window.loaded_document()
    assert sketch is not None and sketch is not model
    assert sketch.document.document_kind == "sketch"
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.add_coordinate_point((0, 0))
    draft.canvas.add_coordinate_point((20, 0))
    window.workspace_tabs.activate("drawing")
    drawing = window.loaded_document()
    assert drawing is not None and drawing is not sketch and drawing is not model
    assert drawing.document.document_kind == "drawing"
    window.workspace_tabs.activate("model")
    assert window.loaded_document() is model
    assert window.viewport.selection() == selection
    window.workspace_tabs.activate("sketch")
    assert window.loaded_document() is sketch
    assert window.active_sketch_dialog() is draft
    assert len(draft.canvas.entities) == 1
    assert len(model.document.commands) == 1
    assert sketch.document.commands == ()


def test_multiple_parts_and_internal_sketch_owner(qtbot: QtBot) -> None:
    window = managed_window(qtbot)
    session = window.document_session
    assert session is not None
    original = session.active
    assert original is not None
    second = window.new_session_document("part")
    assert second is not original
    window.act_sketch.trigger()
    assert session.active is second
    assert window.active_workspace == "sketch"
    assert window.loaded_document() is second.loaded
    assert "内部草图" in window.windowTitle()
    window.activate_session_document(original.loaded.document.document_id)
    assert session.active is original
    assert len(session.documents) == 2


def test_independent_sketch_can_feed_model_and_engineering_document(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = managed_window(qtbot)
    source = window.new_session_document("sketch")
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.set_tool("圆")
    draft.canvas.add_coordinate_point((0, 0))
    draft.canvas.add_coordinate_point((5, 0))
    draft.finish_sketch()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy)
    target = window.new_session_document("part")
    window.attach_session_source(
        source.loaded.document.document_id, object_id=source.services.kernel.sketches[0].sketch_id
    )
    qtbot.waitUntil(lambda: not unit.is_busy)
    instance = target.services.kernel.sketches[0]
    target.loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": instance.sketch_id}, "distance": 8},
        "local",
    )
    drawing = window.new_session_document("drawing")
    window.attach_session_source(target.loaded.document.document_id)
    qtbot.waitUntil(lambda: not unit.is_busy)
    assert drawing.services.kernel.document_references[0].file_id == target.loaded.document.file_id
    assert len(drawing.services.kernel.body_ids) == 1
    assert source.services.kernel.body_ids == ()
    assert drawing.workbench is not None
    # This case checks file ownership and replay; projection-process rendering
    # is independently exercised by the drawing view/output tests.
    monkeypatch.setattr(drawing.workbench, "request_update", lambda: None)
    sheet_id = uuid4()
    drawing.loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet_id)}, "local")
    drawing.loaded.bus.execute(
        "drawing.view.create", drawing_object_mapping(DrawingView(uuid4(), sheet_id)), "local"
    )

    def choose(*args: object, **_kwargs: object) -> tuple[str, str]:
        return str(tmp_path / Path(str(args[2])).name), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(choose))
    window.act_save_all.trigger()
    saver = window.document_saver
    assert saver is not None
    qtbot.waitUntil(lambda: not saver.running)
    assert source.path is not None and target.path is not None and drawing.path is not None
    model_data = json.loads(target.path.read_text(encoding="utf-8"))
    drawing_data = json.loads(drawing.path.read_text(encoding="utf-8"))
    assert model_data["reference_locations"][source.loaded.document.file_id] == source.path.name
    assert drawing_data["reference_locations"][target.loaded.document.file_id] == target.path.name
    source.path.unlink()
    reopened_services = app.fork_app_services(drawing.services)
    restored = app.open_app_document(reopened_services, drawing.path)
    assert restored.document.document_kind == "drawing"
    assert len(reopened_services.kernel.body_ids) == 1
    assert len(reopened_services.kernel.drawing_state.views) == 1


def test_internal_sketch_can_be_separated_without_changing_model(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame

    window = managed_window(qtbot)
    session, unit = window.document_session, window.execution_unit
    assert session is not None and session.active is not None and unit is not None
    model = session.active
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 5),))
    model.loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    model.loaded.bus.execute(
        "feature.extrude",
        {"profile": {"type": "sketch", "sketch_id": sketch.sketch_id}, "distance": 8},
        "local",
    )
    original = model.loaded.document.commands
    window.separate_internal_sketch()
    qtbot.waitUntil(lambda: not unit.is_busy and session.active is not model)
    separated = session.active
    assert separated is not None and separated.kind == "sketch"
    assert separated.path is None and separated.needs_save
    assert separated.services.kernel is not model.services.kernel
    assert separated.services.kernel.sketches[0].entities == sketch.entities
    assert model.loaded.document.commands == original
    assert len(model.services.kernel.body_ids) == 1
