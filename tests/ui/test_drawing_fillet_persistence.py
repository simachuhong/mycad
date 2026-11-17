# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The active drawing owns its persistent fillet radius."""

from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    PolylineEntity,
    Sketch,
    WorkPlaneFrame,
)
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow


def test_fillet_radius_per_drawing_save_reopen_and_undo(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services, document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    first, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert first is not None and loaded is not None
    assert window.document_session is not None and window.document_session.active is not None
    first_services = window.document_session.active.services
    for value in ("FILLET", "R", "4"):
        first.drawing_command_bar.input.setText(value)
        QTest.keyClick(first.drawing_command_bar.input, Qt.Key.Key_Return)
    assert first.canvas.circle_fillet_radius == 4
    assert first_services.kernel.drawing_fillet_radius == 4
    assert loaded.document.commands[-1].id == "drawing.fillet_radius.set"
    assert window.document_session is not None and window.document_session.active is not None
    first_id = window.document_session.active.loaded.document.document_id
    window.act_new_drawing.trigger()
    second = window.active_sketch_dialog()
    assert second is not None and second.canvas.circle_fillet_radius == 0
    window.activate_session_document(first_id)
    assert window.active_sketch_dialog() is first and first.canvas.circle_fillet_radius == 4
    path = tmp_path / "fillet-radius.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.drawing_fillet_radius == 4
    reopened.bus.undo()
    assert restored.kernel.drawing_fillet_radius == 0
    reopened.bus.redo()
    assert restored.kernel.drawing_fillet_radius == 4
    reopened_window = MainWindow(services=restored)
    qtbot.addWidget(reopened_window)
    reopened_window.bind_document(reopened)
    reopened_window.show()
    reopened_window.workspace_tabs.activate("sketch")
    reopened_editor = reopened_window.active_sketch_dialog()
    assert reopened_editor is not None and reopened_editor.canvas.circle_fillet_radius == 4


def test_fillet_radius_undo_with_draft_preserves_geometry(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, unit = window.active_sketch_dialog(), window.execution_unit
    assert editor is not None and unit is not None
    draft = LineEntity("11111111-1111-4111-8111-111111111111", (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((draft,))
    for value in ("FILLETRAD", "5"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert editor.canvas.circle_fillet_radius == 5
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.circle_fillet_radius == 0 and editor.canvas.entities == [draft]
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.circle_fillet_radius == 5 and editor.canvas.entities == [draft]


def test_fillet_radius_failed_write_keeps_input_and_retries(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    original_execute = loaded.bus.execute

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise ValidationError("模拟写入失败")

    monkeypatch.setattr(loaded.bus, "execute", fail_write)
    for value in ("FILLETRAD", "5"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert "模拟写入失败" in editor.drawing_command_bar.status.text()
    assert editor.canvas.circle_fillet_radius == 0 and not loaded.document.commands
    monkeypatch.setattr(loaded.bus, "execute", original_execute)
    editor.drawing_command_bar.input.setText("5")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert editor.canvas.circle_fillet_radius == 5
    assert len(loaded.document.commands) == 1


def test_two_point_radius_failed_write_can_retry(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    original_execute = loaded.bus.execute

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise ValidationError("模拟写入失败")

    monkeypatch.setattr(loaded.bus, "execute", fail_write)
    for value in ("FILLET", "R", "0,0", "3,4"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert editor.canvas.circle_fillet_radius == 0 and not loaded.document.commands
    monkeypatch.setattr(loaded.bus, "execute", original_execute)
    editor.drawing_command_bar.input.setText("3,4")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert editor.canvas.circle_fillet_radius == 5
    assert loaded.document.commands[-1].id == "drawing.fillet_radius.set"


def test_mouse_radius_failed_write_reports_error_and_can_retry(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
    window = MainWindow(services=app.build_app(discoverers=[]), document_session=DocumentSession())
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    window.act_new_drawing.trigger()
    editor, loaded = window.active_sketch_dialog(), window.loaded_document()
    assert editor is not None and loaded is not None
    original_execute = loaded.bus.execute

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise ValidationError("模拟写入失败")

    monkeypatch.setattr(loaded.bus, "execute", fail_write)
    for value in ("FILLET", "R", "0,0"):
        editor.drawing_command_bar.input.setText(value)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((3, 4))
    )
    assert "模拟写入失败" in editor.drawing_command_bar.status.text()
    assert editor.canvas.circle_fillet_radius_pending and not loaded.document.commands
    monkeypatch.setattr(loaded.bus, "execute", original_execute)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((3, 4))
    )
    assert not editor.canvas.circle_fillet_radius_pending
    assert loaded.document.commands[-1].id == "drawing.fillet_radius.set"


def test_radius_change_after_first_saved_pick_keeps_selection(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
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
    first = LineEntity(uuid4().hex, (0, 0), (20, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 20))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second))
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    command = editor.drawing_command_bar.input
    command.setText("FILLET")
    QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((15, 0))
    )
    assert editor.canvas.has_active_edit_gesture
    for value in ("R", "3"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(
        editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen((0, 15))
    )
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert any(
        isinstance(entity, ArcEntity) and entity.radius_mm == 3 for entity in editor.canvas.entities
    ), editor.status_label.text()


def test_radius_change_keeps_staged_mixed_edit_replayable(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
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
    lines = (LineEntity(uuid4().hex, (0, 0), (20, 0)), LineEntity(uuid4().hex, (0, 0), (0, 20)))
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines)
    app.commit_new_sketch(services, loaded, sketch, session_identity=0)
    editor.set_context_sketches(services.kernel.sketches)
    draft = LineEntity(uuid4().hex, (30, 0), (40, 0))
    assert editor.canvas.replace_draft_entities((draft,))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((15, 0), (0, 15)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.mixed_move is not None, editor.status_label.text()
    for value in ("FILLET", "R", "3"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.mixed_move is not None
    assert editor.canvas.mixed_move.source_revision == loaded.document.revision
    command.clear()
    QTest.keyClick(command, Qt.Key.Key_Return)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.circle_fillet_radius == 2
    assert editor.canvas.mixed_move is not None and editor.canvas.mixed_move_is_valid
    assert editor.canvas.mixed_move.source_revision == loaded.document.revision
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.circle_fillet_radius == 3
    assert editor.canvas.mixed_move is not None and editor.canvas.mixed_move_is_valid
    assert editor.canvas.mixed_move.source_revision == loaded.document.revision
    editor.finish_button.click()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert window.active_sketch_dialog() is not editor, editor.status_label.text()
    assert services.kernel.drawing_fillet_radius == 3


@pytest.mark.parametrize("change_radius", [False, True])
def test_fillet_multiple_undo_on_saved_polyline(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch, change_radius: bool
) -> None:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
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
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "M", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.sketches[0].entities != (polyline,),
        timeout=10000,
    )
    if change_radius:
        for value in ("R", "3"):
            command.setText(value)
            QTest.keyClick(command, Qt.Key.Key_Return)
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.sketches[0].entities == (polyline,),
        timeout=10000,
    )
    assert services.kernel.drawing_fillet_radius == (3 if change_radius else 2)
    command.clear()
    QTest.keyClick(command, Qt.Key.Key_Return)
    if change_radius:
        window.request_undo()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
        assert services.kernel.sketches[0].entities != (polyline,)
        window.request_redo()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    else:
        window.request_redo()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
        assert services.kernel.sketches[0].entities != (polyline,)
        window.request_undo()
        qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert services.kernel.sketches[0].entities == (polyline,)
    path = tmp_path / "fillet-command-undo.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    app.open_app_document(restored, path)
    assert restored.kernel.sketches[0].entities == (polyline,)
    assert restored.kernel.drawing_fillet_radius == (3 if change_radius else 2)


def test_fillet_multiple_undo_preserves_saved_and_draft_order(
    qtbot: QtBot, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)

    def isolated_settings(*_args: object) -> QSettings:
        return settings

    monkeypatch.setattr("mycad.ui.main_window.QSettings", isolated_settings)
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
    polyline = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)))
    circles = (CircleEntity(uuid4().hex, (30, 0), 2), CircleEntity(uuid4().hex, (40, 0), 2))
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline, *circles)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2", "M", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.sketches[0].entities[0] != polyline,
        timeout=10000,
    )
    for value in ("R", "4", "T", "N"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((31.7, 1.1), (38.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.entities) == 1 and len(canvas.pending_cross_tangencies) == 2
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert not canvas.entities and not canvas.pending_cross_tangencies
    assert services.kernel.sketches[0].entities[0] != polyline
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.sketches[0].entities[0] == polyline,
        timeout=10000,
    )
    assert services.kernel.drawing_fillet_radius == 4
