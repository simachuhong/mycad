# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Interactive, isolated design-bound hole workflow."""

from __future__ import annotations

from collections.abc import Mapping
from math import pi
from pathlib import Path
from typing import cast

import pytest
from pytestqt.qtbot import QtBot

from mycad.app import build_app, new_document
from mycad.ui.bound_hole_task import BoundHoleTask
from mycad.ui.main_window import MainWindow


def test_bound_hole_upgrade_preview_cancel_preserves_source(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    before = loaded.document.commands
    version = loaded.document.archive_version
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    viewport = window.viewport
    unit = window.execution_unit
    assert viewport is not None and unit is not None
    task = BoundHoleTask(
        services,
        loaded,
        viewport,
        unit,
        session_identity=window.drawing_workbench.session_id,
        current_session=lambda: window.drawing_workbench.session_id,
        parent=window,
    )
    qtbot.addWidget(task)
    task.show()
    assert "升级" in task.status_label.text()
    task.start()
    qtbot.waitUntil(lambda: task.scene is not None, timeout=20000)
    assert loaded.document.archive_version == version
    assert loaded.document.commands == before
    assert not task.confirm_button.isEnabled()
    task.reject()
    assert loaded.document.archive_version == version
    assert loaded.document.commands == before
    window.close()


def test_stale_bound_hole_does_not_start_or_clear_current_preview(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    viewport, unit = window.viewport, window.execution_unit
    assert viewport is not None and unit is not None
    session = [7]
    task = BoundHoleTask(
        services, loaded, viewport, unit, session_identity=7, current_session=lambda: session[0]
    )
    qtbot.addWidget(task)
    finished: list[int] = []
    task.finished.connect(finished.append)
    session[0] = 8
    cleared: list[bool] = []
    submitted: list[bool] = []

    def record_clear() -> None:
        cleared.append(True)

    def reject_submit(*_args: object, **_kwargs: object) -> bool:
        submitted.append(True)
        return False

    monkeypatch.setattr(viewport, "clear_candidate_preview", record_clear)
    monkeypatch.setattr(unit, "submit", reject_submit)
    monkeypatch.setattr(task, "_binding", {"kind": "bound_face"})
    monkeypatch.setattr(task, "_preview_params", {"diameter": 2.0})
    task.diameter_field.setValue(task.diameter_field.value() + 1.0)
    task.start()
    task.preview()
    task.commit()
    task.reject()
    session[0] = 7
    task.start()
    task.preview()
    task.commit()
    task.diameter_field.setValue(task.diameter_field.value() + 1.0)
    task.accept()
    assert not cleared and not submitted
    assert len(finished) == 1


def test_bound_hole_result_after_session_change_does_not_show_old_scene(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    before = loaded.document.commands
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    viewport, unit = window.viewport, window.execution_unit
    assert viewport is not None and unit is not None
    session = [unit.session_id]
    task = BoundHoleTask(
        services,
        loaded,
        viewport,
        unit,
        session_identity=session[0],
        current_session=lambda: session[0],
    )
    qtbot.addWidget(task)
    shown: list[bool] = []
    delivered: list[bool] = []

    def record_scene(*_args: object, **_kwargs: object) -> None:
        shown.append(True)

    def change_session(_result: object) -> None:
        session[0] += 1
        delivered.append(True)

    monkeypatch.setattr(viewport, "show_interaction_scene", record_scene)
    unit.result_ready.connect(change_session)
    task.start()
    qtbot.waitUntil(lambda: bool(delivered) and not unit.is_busy, timeout=20000)
    qtbot.waitUntil(lambda: not unit.is_delivering_result, timeout=20000)
    assert not shown and task.scene is None
    assert loaded.document.commands == before


@pytest.mark.parametrize("notification", ["idle", "result"])
@pytest.mark.parametrize("switch_session", [False, True])
@pytest.mark.parametrize("has_preview", [False, True])
def test_bound_hole_waits_during_result_notification(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    notification: str,
    switch_session: bool,
    has_preview: bool,
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    viewport, unit = window.viewport, window.execution_unit
    assert viewport is not None and unit is not None
    session = [unit.session_id]
    task = BoundHoleTask(
        services,
        loaded,
        viewport,
        unit,
        session_identity=session[0],
        current_session=lambda: session[0],
    )
    qtbot.addWidget(task)
    monkeypatch.setattr(task, "_binding", {"kind": "bound_face"})
    preview = {"diameter": 2.0} if has_preview else None
    monkeypatch.setattr(task, "_preview_params", preview)
    cleared: list[bool] = []
    observed: list[tuple[int, bool]] = []
    task.confirm_button.setEnabled(True)

    def record_clear() -> None:
        cleared.append(True)

    def on_result(_result: object) -> None:
        task.diameter_field.setValue(task.diameter_field.value() + 1.0)
        task.diameter_field.setValue(task.diameter_field.value() + 1.0)
        task.start()
        observed.append((len(cleared), task.confirm_button.isEnabled()))
        if switch_session:
            session[0] += 1

    def on_idle(busy: bool) -> None:
        if not busy:
            on_result(None)

    monkeypatch.setattr(viewport, "clear_candidate_preview", record_clear)
    if notification == "idle":
        unit.busy_changed.connect(on_idle)
    else:
        unit.result_ready.connect(on_result)
    assert unit.submit(lambda: None, operation="test-bound-handover", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed) and not unit.is_delivering_result, timeout=10000)
    assert observed == [(0, False)]
    if switch_session:
        qtbot.wait(100)
        assert not cleared
    else:
        qtbot.waitUntil(task.preview_button.isEnabled, timeout=5000)
        assert len(cleared) == int(has_preview)
    assert not task.confirm_button.isEnabled()
    task.reject()


def test_bound_hole_new_preview_supersedes_deferred_clear(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    viewport, unit = window.viewport, window.execution_unit
    assert viewport is not None and unit is not None
    task = BoundHoleTask(
        services,
        loaded,
        viewport,
        unit,
        session_identity=unit.session_id,
        current_session=lambda: unit.session_id,
    )
    qtbot.addWidget(task)
    monkeypatch.setattr(task, "_binding", {"kind": "bound_face"})
    monkeypatch.setattr(task, "_preview_params", {"diameter": 2.0})
    cleared: list[bool] = []

    def record_clear() -> None:
        cleared.append(True)

    def on_result(_result: object) -> None:
        unit.result_ready.disconnect(on_result)
        task.diameter_field.setValue(task.diameter_field.value() + 1.0)

    monkeypatch.setattr(viewport, "clear_candidate_preview", record_clear)
    unit.result_ready.connect(on_result)
    assert unit.submit(
        lambda: None,
        operation="test-bound-followup",
        session_id=unit.session_id,
        on_complete=lambda _result: task.start(),
    )
    qtbot.waitUntil(lambda: task.scene is not None and not unit.is_busy, timeout=20000)
    qtbot.waitUntil(lambda: not unit.is_delivering_result, timeout=10000)
    qtbot.wait(100)
    assert cleared == [True]
    task.reject()


def test_bound_hole_deferred_clear_waits_for_followup_work(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    services = build_app(discoverers=[])
    loaded = new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    viewport, unit = window.viewport, window.execution_unit
    assert viewport is not None and unit is not None
    task = BoundHoleTask(
        services,
        loaded,
        viewport,
        unit,
        session_identity=unit.session_id,
        current_session=lambda: unit.session_id,
    )
    qtbot.addWidget(task)
    monkeypatch.setattr(task, "_binding", {"kind": "bound_face"})
    monkeypatch.setattr(task, "_preview_params", {"diameter": 2.0})
    cleared: list[bool] = []
    entered, release = Event(), Event()

    def record_clear() -> None:
        cleared.append(True)

    def change_before_followup(_result: object) -> None:
        unit.result_ready.disconnect(change_before_followup)
        task.diameter_field.setValue(task.diameter_field.value() + 1.0)

    def followup() -> None:
        entered.set()
        assert release.wait(10)

    def start_followup(_result: object) -> None:
        assert unit.submit(
            followup, operation="test-bound-followup-wait", session_id=unit.session_id
        )

    monkeypatch.setattr(viewport, "clear_candidate_preview", record_clear)
    unit.result_ready.connect(change_before_followup)
    assert unit.submit(
        lambda: None,
        operation="test-bound-followup-start",
        session_id=unit.session_id,
        on_complete=start_followup,
    )
    try:
        qtbot.waitUntil(entered.is_set, timeout=10000)
        qtbot.wait(250)
        assert not cleared
    finally:
        release.set()
    qtbot.waitUntil(lambda: len(cleared) == 1, timeout=10000)
    assert not unit.is_busy
    task.reject()


@pytest.mark.parametrize("committing", [False, True])
def test_bound_hole_cancel_waits_until_result_notification_finishes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, committing: bool
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    viewport, unit = window.viewport, window.execution_unit
    assert viewport is not None and unit is not None
    task = BoundHoleTask(
        services,
        loaded,
        viewport,
        unit,
        session_identity=unit.session_id,
        current_session=lambda: unit.session_id,
    )
    qtbot.addWidget(task)
    monkeypatch.setattr(task, "_committing", committing)
    finished: list[int] = []
    observed: list[int] = []
    task.finished.connect(finished.append)

    def on_result(_result: object) -> None:
        task.reject()
        observed.append(len(finished))

    unit.result_ready.connect(on_result)
    assert unit.submit(lambda: None, operation="test-bound-cancel", session_id=unit.session_id)
    qtbot.waitUntil(lambda: bool(observed) and not unit.is_delivering_result, timeout=10000)
    assert observed == [0]
    if committing:
        qtbot.wait(100)
        assert not finished and "提交" in task.status_label.text()
        monkeypatch.setattr(task, "_committing", False)
        task.reject()
    else:
        qtbot.waitUntil(lambda: bool(finished), timeout=10000)
    assert len(finished) == 1


def test_bound_hole_cancel_finishes_after_unrelated_work(qtbot: QtBot) -> None:
    from threading import Event

    services = build_app(discoverers=[])
    loaded = new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    viewport, unit = window.viewport, window.execution_unit
    assert viewport is not None and unit is not None
    task = BoundHoleTask(
        services,
        loaded,
        viewport,
        unit,
        session_identity=unit.session_id,
        current_session=lambda: unit.session_id,
    )
    qtbot.addWidget(task)
    finished: list[int] = []
    task.finished.connect(finished.append)
    entered, release = Event(), Event()

    def work() -> None:
        entered.set()
        assert release.wait(10)

    assert unit.submit(work, operation="test-unrelated-work", session_id=unit.session_id)
    try:
        qtbot.waitUntil(entered.is_set, timeout=5000)
        task.reject()
        assert not finished
    finally:
        release.set()
    qtbot.waitUntil(lambda: bool(finished), timeout=5000)
    assert len(finished) == 1


def test_bound_hole_cancel_blocks_completion_callback_restart(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    viewport, unit = window.viewport, window.execution_unit
    assert viewport is not None and unit is not None
    task = BoundHoleTask(
        services,
        loaded,
        viewport,
        unit,
        session_identity=unit.session_id,
        current_session=lambda: unit.session_id,
    )
    qtbot.addWidget(task)
    cleared: list[bool] = []
    callback_clears: list[int] = []
    finished: list[int] = []
    task.finished.connect(finished.append)

    def record_clear() -> None:
        cleared.append(True)

    def on_result(_result: object) -> None:
        task.reject()

    def on_complete(_result: object) -> None:
        task.start()
        callback_clears.append(len(cleared))

    monkeypatch.setattr(viewport, "clear_candidate_preview", record_clear)
    unit.result_ready.connect(on_result)
    assert unit.submit(
        lambda: None,
        operation="test-cancel-restart",
        session_id=unit.session_id,
        on_complete=on_complete,
    )
    qtbot.waitUntil(lambda: bool(finished), timeout=10000)
    assert callback_clears == [0] and cleared == [True]
    assert not unit.is_busy


def test_bound_hole_select_preview_and_commit_upgrade(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from mycad.app import open_app_document
    from mycad.core.persistence import save_document

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    before = loaded.document.commands
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    viewport = window.viewport
    unit = window.execution_unit
    assert viewport is not None and unit is not None
    window.action_catalog.get("ui.feature.bound_hole").trigger()
    task = window.bound_hole_task
    assert task is not None
    qtbot.waitUntil(lambda: task.scene is not None, timeout=20000)
    scene = task.scene
    assert scene is not None and scene.viewport is not None
    viewport.set_orientation("top")
    viewport.fit_view()
    position = viewport.project_world_point((2, 1, 3))
    assert position is not None
    QTest.mouseClick(
        viewport, Qt.MouseButton.LeftButton, pos=QPoint(round(position[0]), round(position[1]))
    )
    assert task.preview_button.isEnabled()
    assert task.u_field.value() == pytest.approx(2.0, abs=0.2)
    assert task.v_field.value() == pytest.approx(1.0, abs=0.2)
    second = viewport.project_world_point((-2, 1, 3))
    assert second is not None
    QTest.mouseClick(
        viewport, Qt.MouseButton.LeftButton, pos=QPoint(round(second[0]), round(second[1]))
    )
    assert task.u_field.value() == pytest.approx(-2.0, abs=0.2)
    task.diameter_field.setValue(2.0)
    task.depth_field.setValue(2.0)
    task.u_field.setValue(1.0)
    task.v_field.setValue(0.0)
    task.preview()
    qtbot.waitUntil(lambda: task.confirm_button.isEnabled(), timeout=20000)
    assert loaded.document.commands == before
    assert loaded.document.archive_version < 5
    task.commit()
    qtbot.waitUntil(lambda: len(loaded.document.commands) == 2 and not unit.is_busy, timeout=20000)
    command = loaded.document.commands[-1]
    assert loaded.document.archive_version == 5
    assert command.id == "feature.hole" and command.version == 3
    assert command.params["position"] == {"kind": "local", "uv_mm": [1.0, 0.0]}
    target = command.params["target_face"]
    assert isinstance(target, dict)
    assert cast("Mapping[str, object]", target).get("kind") == "bound_face"
    loaded.bus.edit_and_replay(0, {"size_x": 20, "size_y": 20, "size_z": 8}, "local", "加厚")
    assert services.kernel.mass_properties().volume == pytest.approx(3200 - 2 * pi)
    loaded.bus.undo()
    assert services.kernel.mass_properties().volume == pytest.approx(3200)
    loaded.bus.redo()
    assert services.kernel.mass_properties().volume == pytest.approx(3200 - 2 * pi)
    archive = tmp_path / "bound-hole.my3d"
    save_document(loaded.document, archive)
    reopened = open_app_document(services, archive)
    assert reopened.document.commands == loaded.document.commands
    assert services.kernel.mass_properties().volume == pytest.approx(3200 - 2 * pi)
    window.close()


def test_bound_hole_action_opens_command_bar_and_cancel(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    before = loaded.document.commands
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.action_catalog.get("ui.feature.bound_hole").trigger()
    task = window.bound_hole_task
    assert task is not None
    qtbot.waitUntil(lambda: task.scene is not None, timeout=20000)
    assert window.findChild(BoundHoleTask) is task
    window.close()
    assert window.isVisible() and window.bound_hole_task is task
    assert "完成或取消绑定孔" in window.status_command.text()
    window.request_undo()
    assert loaded.document.commands == before
    assert "完成或取消绑定孔" in window.status_command.text()
    window.act_save.trigger()
    assert "完成或取消绑定孔" in window.status_command.text()
    window.act_export.trigger()
    assert "完成或取消绑定孔" in window.status_command.text()
    window.workspace_tabs.activate("drawing")
    assert window.active_workspace == "model"
    assert "完成或取消绑定孔" in window.status_command.text()
    task.cancel_button.click()
    assert window.bound_hole_task is None
    assert loaded.document.commands == before
    window.close()


def test_bound_hole_invalid_position_preserves_inputs_and_can_retry(qtbot: QtBot) -> None:
    from mycad.ui.viewport import SelectionState

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    before = loaded.document.commands
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.action_catalog.get("ui.feature.bound_hole").trigger()
    task = window.bound_hole_task
    viewport = window.viewport
    assert task is not None and viewport is not None
    qtbot.waitUntil(lambda: task.scene is not None, timeout=20000)
    scene = task.scene
    assert scene is not None and scene.viewport is not None
    face = scene.viewport.faces[0]
    viewport.selection_changed.emit(
        SelectionState(
            scene.viewport.geometry_revision, "face", (face.body_id,), (face.topology_id,)
        )
    )
    task.u_field.setValue(500.0)
    task.preview()
    qtbot.waitUntil(lambda: "预览失败" in task.status_label.text(), timeout=20000)
    assert not task.confirm_button.isEnabled()
    assert task.u_field.value() == 500.0
    assert loaded.document.commands == before and loaded.document.archive_version < 5
    task.u_field.setValue(0.0)
    task.diameter_field.setValue(2.0)
    task.depth_field.setValue(2.0)
    task.preview()
    qtbot.waitUntil(lambda: task.confirm_button.isEnabled(), timeout=20000)
    task.depth_field.setValue(1.0)
    assert not task.confirm_button.isEnabled()
    task.select_face_button.click()
    qtbot.waitUntil(lambda: task.scene is not None, timeout=20000)
    assert not task.confirm_button.isEnabled()
    task.cancel_button.click()
    assert loaded.document.commands == before
    window.close()


def test_bound_hole_cancel_during_upgrade_preview_preserves_source(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    from mycad.app import ReplayCandidatePreview, ReplayCandidateSession

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    before = loaded.document.commands
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    started, release = Event(), Event()
    original = ReplayCandidateSession.preview

    def delayed_preview(
        candidate: ReplayCandidateSession, *, current_session_identity: int
    ) -> ReplayCandidatePreview:
        started.set()
        assert release.wait(20)
        return original(candidate, current_session_identity=current_session_identity)

    monkeypatch.setattr(ReplayCandidateSession, "preview", delayed_preview)
    try:
        window.action_catalog.get("ui.feature.bound_hole").trigger()
        task = window.bound_hole_task
        assert task is not None
        qtbot.waitUntil(started.is_set, timeout=10000)
        task.cancel_button.click()
        assert window.bound_hole_task is task
    finally:
        release.set()
    qtbot.waitUntil(lambda: window.bound_hole_task is None, timeout=20000)
    assert loaded.document.commands == before and loaded.document.archive_version < 5
    window.close()


def test_bound_hole_rejects_unsupported_cylinder_side(qtbot: QtBot) -> None:
    from mycad.ui.viewport import SelectionState

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.cylinder", {"radius": 10, "height": 6})
    before = loaded.document.commands
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.action_catalog.get("ui.feature.bound_hole").trigger()
    task = window.bound_hole_task
    viewport = window.viewport
    assert task is not None and viewport is not None
    qtbot.waitUntil(lambda: task.scene is not None, timeout=20000)
    scene = task.scene
    assert scene is not None and scene.viewport is not None
    for face in scene.viewport.faces:
        viewport.selection_changed.emit(
            SelectionState(
                scene.viewport.geometry_revision, "face", (face.body_id,), (face.topology_id,)
            )
        )
        if "无法绑定此面" in task.status_label.text():
            break
    assert "无法绑定此面" in task.status_label.text()
    assert not task.preview_button.isEnabled() and not task.confirm_button.isEnabled()
    assert loaded.document.commands == before
    task.cancel_button.click()
    window.close()


def test_bound_hole_stale_source_cannot_commit_and_keeps_inputs(qtbot: QtBot) -> None:
    from mycad.ui.viewport import SelectionState

    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.action_catalog.get("ui.feature.bound_hole").trigger()
    task, viewport = window.bound_hole_task, window.viewport
    assert task is not None and viewport is not None
    qtbot.waitUntil(lambda: task.scene is not None, timeout=20000)
    scene = task.scene
    assert scene is not None and scene.viewport is not None
    face = scene.viewport.faces[0]
    viewport.selection_changed.emit(
        SelectionState(
            scene.viewport.geometry_revision, "face", (face.body_id,), (face.topology_id,)
        )
    )
    task.u_field.setValue(1.0)
    task.diameter_field.setValue(2.0)
    task.depth_field.setValue(2.0)
    task.preview()
    qtbot.waitUntil(lambda: task.confirm_button.isEnabled(), timeout=20000)
    loaded.bus.execute("feature.box", {"size_x": 12, "size_y": 12, "size_z": 6})
    latest = loaded.document.commands
    task.commit()
    qtbot.waitUntil(lambda: "来源已变化" in task.status_label.text(), timeout=20000)
    assert loaded.document.commands == latest
    assert task.u_field.value() == 1.0 and task.diameter_field.value() == 2.0
    assert not task.confirm_button.isEnabled() and not task.preview_button.isEnabled()
    task.cancel_button.click()
    window.close()


def test_bound_hole_cancel_preserves_existing_redo(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    loaded.bus.execute("feature.box", {"size_x": 20, "size_y": 20, "size_z": 6})
    loaded.bus.execute("feature.cylinder", {"radius": 2, "height": 4})
    loaded.bus.undo()
    before = loaded.document.commands
    version = loaded.document.archive_version
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.action_catalog.get("ui.feature.bound_hole").trigger()
    task = window.bound_hole_task
    assert task is not None
    qtbot.waitUntil(lambda: task.scene is not None, timeout=20000)
    task.cancel_button.click()
    assert loaded.document.commands == before and loaded.document.archive_version == version
    loaded.bus.redo()
    assert loaded.document.commands[-1].id == "feature.cylinder"
    window.close()


def test_bound_hole_empty_part_explains_missing_geometry(qtbot: QtBot) -> None:
    services = build_app(discoverers=[])
    loaded = new_document(services)
    window = MainWindow(services=services)
    qtbot.addWidget(window)
    window.bind_document(loaded)
    window.show()
    window.action_catalog.get("ui.feature.bound_hole").trigger()
    task = window.bound_hole_task
    assert task is not None
    qtbot.waitUntil(lambda: "没有可绑定的实体面" in task.status_label.text(), timeout=20000)
    assert not task.preview_button.isEnabled() and not task.confirm_button.isEnabled()
    assert not loaded.document.commands and loaded.document.archive_version < 5
    task.cancel_button.click()
    window.close()
