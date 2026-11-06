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
    window.new_session_document("sketch")
    sketch = window.loaded_document()
    assert sketch is not None and sketch is not model
    assert sketch.document.document_kind == "sketch"
    draft = window.active_sketch_dialog()
    assert draft is not None
    draft.canvas.add_coordinate_point((0, 0))
    draft.canvas.add_coordinate_point((20, 0))
    window.new_session_document("drawing")
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
    assert window.active_workspace == "model"
    assert window.loaded_document() is second.loaded
    assert window.part_sketch_task is not None
    window.activate_session_document(original.loaded.document.document_id)
    assert session.active is original
    assert len(session.documents) == 2


def test_workspace_returns_to_previous_recent_document_after_closing_last_used(
    qtbot: QtBot,
) -> None:
    window = managed_window(qtbot)
    first = window.new_session_document("sketch")
    second = window.new_session_document("sketch")
    third = window.new_session_document("sketch")
    drawing = window.new_session_document("drawing")
    window.activate_session_document(second.loaded.document.document_id)
    window.activate_session_document(first.loaded.document.document_id)
    window.activate_session_document(third.loaded.document.document_id)
    window.close_active_document()
    session = window.document_session
    assert session is not None and session.active is drawing
    window.workspace_tabs.activate("sketch")
    assert session.active is first
    assert window.loaded_document() is first.loaded
    window.close_active_document()
    assert session.active is drawing
    window.workspace_tabs.activate("sketch")
    assert session.active is second


def test_unactivated_session_document_remains_available_after_active_closes() -> None:
    from mycad.ui.document_session import DocumentSession, SessionDocument

    session = DocumentSession()
    first_services = app.build_app(discoverers=[])
    second_services = app.fork_app_services(first_services)
    first = SessionDocument(
        first_services, app.new_workspace_document(first_services, kind="sketch")
    )
    second = SessionDocument(
        second_services, app.new_workspace_document(second_services, kind="sketch")
    )
    session.add(first)
    session.activate(first.loaded.document.document_id)
    session.add(second)
    assert session.latest("sketch") is first
    session.remove(first.loaded.document.document_id)
    assert session.latest("sketch") is second


def test_invalid_existing_symlink_does_not_break_session_path_check(
    qtbot: QtBot, tmp_path: Path
) -> None:
    loop = tmp_path / "loop.my3d"
    try:
        loop.symlink_to(loop.name)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")
    window = managed_window(qtbot)
    session = window.document_session
    assert session is not None and session.active is not None
    session.active.path = loop
    other = window.new_session_document("part")
    path = tmp_path / "valid.my3d"
    session.check_path(other, path)
    assert session.active is other
    from mycad.core.persistence import save_document

    source_services = app.fork_app_services(other.services)
    source = app.new_workspace_document(source_services, kind="part")
    save_document(source.document, path)
    window.open_document_path(path)
    qtbot.waitUntil(lambda: session.active is not other, timeout=10000)
    assert session.active is not None and session.active.path == path


def test_engineering_document_projects_its_attached_part(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QInputDialog, QMenu

    from mycad.core.drawing_projection import LineCurve
    from mycad.core.persistence import save_document
    from mycad.ui.document_session import DocumentSession

    window = managed_window(qtbot)
    window.show()
    part = window.new_session_document("part")
    part.loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 10, "size_z": 5}, "local")
    original_history = part.loaded.document.commands
    drawing = window.new_session_document("drawing")
    unit = window.execution_unit
    assert unit is not None and drawing.workbench is not None
    assert drawing.workbench.choose_source_button.isVisible()

    def choose_source(
        _parent: object, _title: str, _label: str, items: list[str], *_args: object
    ) -> tuple[str, bool]:
        return items[-1], True

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(choose_source))
    drawing.workbench.choose_source_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    bench = drawing.workbench
    assert bench.base_action.isEnabled()
    bench.begin_placement()
    qtbot.waitUntil(lambda: bench.placement is not None and bench.canvas.placing, timeout=30000)
    assert bench.placement is not None
    result = bench.projections.get(bench.placement.base_id)
    assert result is not None and result.curves
    QTest.mouseClick(
        bench.canvas.viewport(),
        Qt.MouseButton.LeftButton,
        pos=bench.canvas.mapFromScene(QPointF(90, -140)),
    )
    QTest.keyClick(bench.canvas, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: bool(drawing.services.kernel.drawing_state.views) and not unit.is_busy,
        timeout=10000,
    )
    assert part.loaded.document.commands == original_history
    assert drawing.services.kernel.drawing_state.views[0].source.kind == "current_part"
    identity = drawing.services.kernel.drawing_state.views[0].view_id
    qtbot.waitUntil(
        lambda: identity in bench.projections and bench.canvas.drawing_scene is not None,
        timeout=30000,
    )
    scene = bench.canvas.drawing_scene
    assert scene is not None
    scene_view = next(view for view in scene.views if view.view_id == identity)
    curve = next(
        curve
        for curve in scene_view.curves
        if isinstance(curve.geometry, LineCurve) and curve.source is not None
    )
    geometry = curve.geometry
    assert isinstance(geometry, LineCurve)
    midpoint = scene_view.to_paper(
        ((geometry.start[0] + geometry.end[0]) / 2, (geometry.start[1] + geometry.end[1]) / 2)
    )
    bench.canvas.fit_view()
    bench.annotations.begin("aligned")
    QTest.mouseClick(
        bench.canvas.viewport(),
        Qt.MouseButton.LeftButton,
        pos=bench.canvas.mapFromScene(QPointF(midpoint[0], -midpoint[1])),
    )
    assert bench.annotations.draft is not None, bench.hint.text()
    QTest.mouseClick(
        bench.canvas.viewport(),
        Qt.MouseButton.LeftButton,
        pos=bench.canvas.mapFromScene(QPointF(110, -120)),
    )
    qtbot.waitUntil(
        lambda: len(drawing.services.kernel.drawing_state.annotations) == 1 and not unit.is_busy,
        timeout=10000,
    )
    annotation = drawing.services.kernel.drawing_state.annotations[0]
    old_fingerprint = drawing.services.kernel.drawing_source_fingerprint
    window.activate_session_document(part.loaded.document.document_id)
    part.loaded.bus.execute(
        "feature.box", {"size_x": 4, "size_y": 3, "size_z": 2, "center": [30, 0, 0]}, "local"
    )
    window.activate_session_document(drawing.loaded.document.document_id)
    document_menu = next(
        action.menu() for action in window.menuBar().actions() if action.text() == "文档"
    )
    assert isinstance(document_menu, QMenu)
    update_reference = next(
        action for action in document_menu.actions() if action.text() == "更新来源引用"
    )
    update_reference.trigger()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    new_fingerprint = drawing.services.kernel.drawing_source_fingerprint
    assert new_fingerprint != old_fingerprint
    bench.update_requested()
    qtbot.waitUntil(
        lambda: (
            (result := bench.projections.get(identity)) is not None
            and result.source_fingerprint == new_fingerprint
        ),
        timeout=30000,
    )
    assert len(part.loaded.document.commands) == 2
    assert (
        drawing.services.kernel.drawing_state.annotations[0].annotation_id
        == annotation.annotation_id
    )
    assert not bench.output_scene().issues
    for kind in ("pdf", "dxf"):
        output = tmp_path / f"associated-model.{kind}"
        bench.export_to(kind, output)
        qtbot.waitUntil(lambda path=output: path.is_file() and not unit.is_busy, timeout=10000)
        assert output.stat().st_size > 0

    def choose(*args: object, **_kwargs: object) -> tuple[str, str]:
        return str(tmp_path / Path(str(args[2])).name), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(choose))
    window.act_save_all.trigger()
    saver = window.document_saver
    assert saver is not None
    qtbot.waitUntil(lambda: not saver.running, timeout=10000)
    assert part.path is not None and drawing.path is not None
    reopened_services = app.fork_app_services(drawing.services)
    restored = app.open_app_document(reopened_services, drawing.path)
    assert restored.document.document_kind == "drawing"
    assert len(reopened_services.kernel.body_ids) == len(drawing.services.kernel.body_ids)
    assert reopened_services.kernel.drawing_source_fingerprint == new_fingerprint
    assert len(reopened_services.kernel.drawing_state.views) == 1
    assert len(reopened_services.kernel.drawing_state.annotations) == 1
    source_archive = part.path.read_bytes()
    part.path.unlink()
    missing_services = app.fork_app_services(drawing.services)
    missing = app.open_app_document(missing_services, drawing.path)
    messages = app.reference_association_status(missing_services, missing, drawing.path)
    assert any("来源文件缺失" in message for message in messages)
    assert missing_services.kernel.drawing_source_fingerprint == new_fingerprint
    assert len(missing_services.kernel.drawing_state.views) == 1
    assert len(missing_services.kernel.drawing_state.annotations) == 1
    reopened_window = MainWindow(
        services=app.fork_app_services(drawing.services), document_session=DocumentSession()
    )
    qtbot.addWidget(reopened_window)
    reopened_window.show()
    reopened_window.open_document_path(drawing.path)
    qtbot.waitUntil(lambda: "来源文件缺失" in reopened_window.status_command.text(), timeout=10000)
    other_services = app.fork_app_services(drawing.services)
    other = app.new_workspace_document(other_services, kind="part")
    save_document(other.document, part.path)
    messages = app.reference_association_status(missing_services, missing, drawing.path)
    assert any("身份不匹配" in message for message in messages)
    assert missing_services.kernel.drawing_source_fingerprint == new_fingerprint
    window.activate_session_document(part.loaded.document.document_id)
    window.close_active_document()
    assert window.document_session is not None
    assert window.document_session.find(part.loaded.document.document_id) is None
    window.activate_session_document(drawing.loaded.document.document_id)
    before = drawing.loaded.document.commands
    errors: list[str] = []
    monkeypatch.setattr(window, "_show_error", errors.append)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *_args: (str(part.path), ""))
    )
    update_reference.trigger()
    qtbot.waitUntil(lambda: bool(errors), timeout=10000)
    assert "身份不匹配" in errors[-1]
    assert drawing.loaded.document.commands == before
    assert drawing.services.kernel.drawing_source_fingerprint == new_fingerprint
    adopted_volume = drawing.services.kernel.mass_properties().volume
    part.path.write_bytes(source_archive)
    update_reference.trigger()
    qtbot.waitUntil(
        lambda: len(drawing.loaded.document.commands) == len(before) + 1 and not unit.is_busy,
        timeout=10000,
    )
    assert drawing.services.kernel.mass_properties().volume == pytest.approx(adopted_volume)
    relocated_fingerprint = drawing.services.kernel.drawing_source_fingerprint
    bench.update_requested()
    qtbot.waitUntil(
        lambda: (
            (result := bench.projections.get(identity)) is not None
            and result.source_fingerprint == relocated_fingerprint
        ),
        timeout=30000,
    )
    assert not bench.output_scene().issues
    assert any(
        "关联有效" in message
        for message in app.reference_association_status(
            drawing.services, drawing.loaded, drawing.path, locations=drawing.reference_locations
        )
    )
    changed_services = app.fork_app_services(drawing.services)
    changed_source = app.open_app_document(changed_services, part.path)
    changed_source.bus.execute("feature.cylinder", {"radius": 7, "height": 8}, "local")
    save_document(changed_source.document, part.path)
    command_count = len(drawing.loaded.document.commands)
    update_reference.trigger()
    qtbot.waitUntil(
        lambda: len(drawing.loaded.document.commands) == command_count + 1 and not unit.is_busy,
        timeout=10000,
    )
    changed_fingerprint = drawing.services.kernel.drawing_source_fingerprint
    bench.update_requested()
    qtbot.waitUntil(
        lambda: (
            (result := bench.projections.get(identity)) is not None
            and result.source_fingerprint == changed_fingerprint
        ),
        timeout=30000,
    )
    with pytest.raises(ValueError) as blocked:
        bench.output_scene()
    assert "标注" in str(blocked.value) or "关联" in str(blocked.value)
    assert drawing.services.kernel.drawing_state.annotations
    annotation_id = drawing.services.kernel.drawing_state.annotations[0].annotation_id
    old_annotation = drawing.services.kernel.drawing_state.annotations[0]
    bench.annotations.select(annotation_id)
    bench.annotations.reattach()
    changed_projection = bench.projections[identity]
    for curve in changed_projection.curves:
        if isinstance(curve.geometry, LineCurve) and curve.source is not None:
            bench.annotations.choose(identity, curve.curve_id, (90.0, 140.0))
            break
    assert bench.annotations.draft is None
    assert "多个" in bench.hint.text()
    assert drawing.services.kernel.drawing_state.annotations[0].annotation_id == annotation_id
    bench.annotations.cancel()
    changed_source.bus.execute("feature.box", {"size_x": 12, "size_y": 9, "size_z": 6}, "local")
    save_document(changed_source.document, part.path)
    command_count = len(drawing.loaded.document.commands)
    update_reference.trigger()
    qtbot.waitUntil(
        lambda: len(drawing.loaded.document.commands) == command_count + 1 and not unit.is_busy,
        timeout=10000,
    )
    final_fingerprint = drawing.services.kernel.drawing_source_fingerprint
    bench.update_requested()
    qtbot.waitUntil(
        lambda: (
            (result := bench.projections.get(identity)) is not None
            and result.source_fingerprint == final_fingerprint
        ),
        timeout=30000,
    )
    bench.annotations.select(annotation_id)
    bench.annotations.reattach()
    for curve in bench.projections[identity].curves:
        if isinstance(curve.geometry, LineCurve) and curve.source is not None:
            bench.annotations.choose(identity, curve.curve_id, (90.0, 140.0))
            if bench.annotations.draft is not None:
                break
    assert bench.annotations.draft is not None, bench.hint.text()
    command_count = len(drawing.loaded.document.commands)
    bench.annotations.click((115.0, 125.0))
    qtbot.waitUntil(
        lambda: len(drawing.loaded.document.commands) == command_count + 1 and not unit.is_busy,
        timeout=10000,
    )
    rebound = drawing.services.kernel.drawing_state.annotations[0]
    assert rebound.annotation_id == annotation_id and rebound != old_annotation
    assert not bench.output_scene().issues
    window.request_undo()
    qtbot.waitUntil(
        lambda: len(drawing.loaded.document.commands) == command_count and not unit.is_busy,
        timeout=10000,
    )
    assert drawing.services.kernel.drawing_state.annotations[0] == old_annotation
    window.request_redo()
    qtbot.waitUntil(
        lambda: len(drawing.loaded.document.commands) == command_count + 1 and not unit.is_busy,
        timeout=10000,
    )
    assert drawing.services.kernel.drawing_state.annotations[0] == rebound
    assert not bench.output_scene().issues


def test_engineering_document_places_attached_sketch(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QInputDialog

    window = managed_window(qtbot)
    window.show()
    source = window.new_session_document("sketch")
    draft = window.active_sketch_dialog()
    unit = window.execution_unit
    assert draft is not None and unit is not None
    draft.canvas.add_coordinate_point((0, 0), exact_point=True)
    draft.canvas.add_coordinate_point((20, 5), exact_point=True)
    draft.canvas.end_line_chain()
    draft.finish_sketch()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    source_history = source.loaded.document.commands
    drawing = window.new_session_document("drawing")
    assert drawing.workbench is not None

    def choose_source(
        _parent: object, _title: str, _label: str, items: list[str], *_args: object
    ) -> tuple[str, bool]:
        return items[-1], True

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(choose_source))
    drawing.workbench.choose_source_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    bench = drawing.workbench
    assert bench.sketch_view_action.isEnabled()
    bench.begin_sketch_placement()
    qtbot.waitUntil(lambda: bench.placement is not None and bench.canvas.placing, timeout=30000)
    assert bench.placement is not None
    result = bench.projections.get(bench.placement.base_id)
    assert result is not None and result.curves
    QTest.mouseClick(
        bench.canvas.viewport(),
        Qt.MouseButton.LeftButton,
        pos=bench.canvas.mapFromScene(QPointF(90, -140)),
    )
    QTest.keyClick(bench.canvas, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: bool(drawing.services.kernel.drawing_state.views) and not unit.is_busy,
        timeout=10000,
    )
    assert drawing.services.kernel.drawing_state.views[0].source.kind == "sketch"
    assert source.loaded.document.commands == source_history


def test_cancelling_engineering_source_selection_keeps_document_unchanged(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QInputDialog

    window = managed_window(qtbot)
    window.show()
    source = window.new_session_document("part")
    drawing = window.new_session_document("drawing")
    assert drawing.workbench is not None
    before = drawing.loaded.document.commands
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *_args: ("", False)))
    drawing.workbench.choose_source_button.click()
    assert drawing.loaded.document.commands == before
    assert not drawing.services.kernel.document_references
    assert window.loaded_document() is drawing.loaded
    assert source.loaded.document.commands == ()


@pytest.mark.parametrize("operation", ["move", "delete"])
def test_inactive_document_reports_pending_view_edits(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.document_session import SessionDocument
    from mycad.ui.unsaved_documents_dialog import UnsavedDocumentsDialog

    window = managed_window(qtbot)
    window.show()
    part = window.new_session_document("part")
    part.loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 8, "size_z": 6})
    drawing = window.new_session_document("drawing")
    unit = window.execution_unit
    assert unit is not None
    window.attach_session_source(part.loaded.document.document_id)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert drawing.workbench is not None
    bench = drawing.workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    sheet = uuid4()
    drawing.loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    view = DrawingView(uuid4(), sheet)
    drawing.loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    drawing.loaded.document.mark_clean()
    drawing.path = tmp_path / "drawing.my2d"
    bench.refresh()
    bench.canvas.select_view(view.view_id)
    if operation == "move":
        bench.canvas.view_dragged.emit(view.view_id, "move", (90.0, 100.0), False)
    else:
        bench.preview_delete()
    window.activate_session_document(part.loaded.document.document_id)
    qtbot.waitUntil(lambda: window.loaded_document() is part.loaded, timeout=10000)
    assert drawing.needs_save
    dialog = UnsavedDocumentsDialog((drawing,))
    qtbot.addWidget(dialog)
    assert "视图操作未确认" in dialog.list.item(0).text()
    prompted: list[tuple[SessionDocument, ...]] = []

    def cancel_close(entries: tuple[SessionDocument, ...]) -> None:
        prompted.append(entries)

    monkeypatch.setattr(window, "_ask_session_close_dialog", cancel_close)
    assert not window.close()
    assert prompted and drawing in prompted[-1]
    window.activate_session_document(drawing.loaded.document.document_id)
    qtbot.waitUntil(lambda: window.loaded_document() is drawing.loaded, timeout=10000)
    QTest.keyClick(bench.canvas, Qt.Key.Key_Escape)
    assert not bench.has_pending_view_edit
    assert not drawing.needs_save


@pytest.mark.parametrize("label", ["选择工程图来源", "更新来源引用", "解除来源关联", "直接关联"])
def test_pending_view_edit_blocks_reference_commands(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, label: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QInputDialog, QMenu

    window = managed_window(qtbot)
    window.show()
    part = window.new_session_document("part")
    part.loaded.bus.execute("feature.box", {"size_x": 10, "size_y": 8, "size_z": 6})
    drawing = window.new_session_document("drawing")
    unit = window.execution_unit
    assert unit is not None and drawing.workbench is not None
    window.attach_session_source(part.loaded.document.document_id)
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    bench = drawing.workbench
    monkeypatch.setattr(bench, "request_update", lambda: None)
    sheet = uuid4()
    drawing.loaded.bus.execute("drawing.sheet.create", {"sheet_id": str(sheet)})
    view = DrawingView(uuid4(), sheet)
    drawing.loaded.bus.execute("drawing.view.create", drawing_object_mapping(view))
    bench.refresh()
    bench.canvas.select_view(view.view_id)
    bench.preview_delete()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    before = drawing.loaded.document.commands
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *_args: ("", False)))
    menu = next(action.menu() for action in window.menuBar().actions() if action.text() == "文档")
    assert isinstance(menu, QMenu)
    if label == "直接关联":
        window.attach_session_source(part.loaded.document.document_id)
    else:
        next(action for action in menu.actions() if action.text() == label).trigger()
    assert not unit.is_busy and drawing.loaded.document.commands == before
    assert bench.has_pending_view_edit and bench.confirm_delete_action.isVisible()
    assert "工程图视图" in window.status_command.text()
    QTest.keyClick(bench.canvas, Qt.Key.Key_Escape)


def test_pending_part_sketch_blocks_attaching_a_source(qtbot: QtBot) -> None:
    from mycad.core.sketch import CircleEntity, Sketch, WorkPlaneFrame

    window = managed_window(qtbot)
    window.show()
    source = window.new_session_document("sketch")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (CircleEntity(uuid4().hex, (0, 0), 5),))
    source.loaded.bus.execute("sketch.create", sketch.to_mapping(version=3), "local")
    target = window.new_session_document("part")
    window.act_sketch.trigger()
    task = window.part_sketch_task
    assert task is not None
    task.lock_plane()
    task.select_tool("line")
    task.place_uv((0, 0))
    task.place_uv((10, 2))
    before = task.session.sketch
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    window.attach_session_source(source.loaded.document.document_id, object_id=sketch.sketch_id)
    assert target.loaded.document.commands == ()
    assert task.session.sketch == before
    assert "草图尚未提交" in window.status_command.text()
    task.reject()


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
    assert drawing.workbench.base_action.isEnabled()
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
