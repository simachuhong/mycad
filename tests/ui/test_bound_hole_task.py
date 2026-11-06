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
