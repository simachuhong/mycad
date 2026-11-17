# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Drawing chamfer values survive reopening and remain undoable."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.exceptions import ValidationError
from mycad.core.persistence import save_document
from mycad.core.sketch import CircleEntity, LineEntity, PolylineEntity, Sketch, WorkPlaneFrame
from mycad.ui.document_session import DocumentSession
from mycad.ui.main_window import MainWindow


def test_chamfer_values_per_drawing_save_reopen_and_undo(
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
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    command = editor.drawing_command_bar.input
    for value in ("CHAMFER", "D", "2", "3", "A", "4", "30"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert loaded.document.commands[-1].id == "drawing.chamfer_values.set"
    assert window.document_session is not None and window.document_session.active is not None
    first_id = window.document_session.active.loaded.document.document_id
    path = tmp_path / "chamfer.my2d"
    save_document(loaded.document, path)
    window.act_new_drawing.trigger()
    other = window.active_sketch_dialog()
    assert other is not None and other.canvas.chamfer_distance_first == 0
    window.activate_session_document(first_id)
    assert window.active_sketch_dialog() is editor
    assert editor.canvas.chamfer_distance_first == 2 and editor.canvas.chamfer_angle_length == 4
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.drawing_chamfer_values == (2, 3, 4, 30)
    reopened.bus.undo()
    assert restored.kernel.drawing_chamfer_values == (2, 3, 0, 0)
    reopened.bus.redo()
    assert restored.kernel.drawing_chamfer_values == (2, 3, 4, 30)
    reopened_window = MainWindow(services=restored)
    qtbot.addWidget(reopened_window)
    reopened_window.bind_document(reopened)
    reopened_window.show()
    reopened_window.workspace_tabs.activate("sketch")
    reopened_editor = reopened_window.active_sketch_dialog()
    assert reopened_editor is not None
    assert reopened_editor.canvas.chamfer_distance_first == 2
    assert reopened_editor.canvas.chamfer_second_distance == 3
    assert reopened_editor.canvas.chamfer_angle_length == 4
    assert reopened_editor.canvas.chamfer_last_angle == 30


def test_chamfer_write_failure_and_draft_undo_redo(
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
    editor, loaded, unit = (
        window.active_sketch_dialog(),
        window.loaded_document(),
        window.execution_unit,
    )
    assert editor is not None and loaded is not None and unit is not None
    draft = LineEntity("11111111-1111-4111-8111-111111111111", (0, 0), (10, 0))
    assert editor.canvas.replace_draft_entities((draft,))
    original_execute = loaded.bus.execute

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise ValidationError("模拟写入失败")

    monkeypatch.setattr(loaded.bus, "execute", fail_write)
    command = editor.drawing_command_bar.input
    for value in ("CHAMFER", "D", "2", "3"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert "模拟写入失败" in editor.drawing_command_bar.status.text()
    assert editor.canvas.chamfer_distance_first == 0 and not loaded.document.commands
    monkeypatch.setattr(loaded.bus, "execute", original_execute)
    command.setText("3")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.chamfer_distance_first == 2
    command.clear()
    QTest.keyClick(command, Qt.Key.Key_Return)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.chamfer_distance_first == 0 and editor.canvas.entities == [draft]
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.chamfer_distance_first == 2 and editor.canvas.entities == [draft]
    qtbot.waitUntil(lambda: not unit.is_notifying_result, timeout=10000)
    monkeypatch.setattr(loaded.bus, "execute", fail_write)
    for value in ("CHAMFERA", "4"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert "模拟写入失败" in editor.drawing_command_bar.status.text()
    assert editor.canvas.chamfer_distance_first == 2
    monkeypatch.setattr(loaded.bus, "execute", original_execute)
    command.setText("4")
    QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.chamfer_distance_first == 4 and editor.canvas.entities == [draft]


def test_chamfer_settings_keep_staged_mixed_edit_replayable(
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
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), lines), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    assert editor.canvas.replace_draft_entities((LineEntity(uuid4().hex, (30, 0), (40, 0)),))
    command = editor.drawing_command_bar.input
    for value in ("CHAMFER", "D", "2", "3"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((15, 0), (0, 15)):
        QTest.mouseClick(
            editor.canvas, Qt.MouseButton.LeftButton, pos=editor.canvas.local_to_screen(point)
        )
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.mixed_move is not None, editor.status_label.text()
    for value in ("CHAMFER", "D", "4", "5"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert editor.canvas.mixed_move is not None
    assert editor.canvas.mixed_move.source_revision == loaded.document.revision
    command.clear()
    QTest.keyClick(command, Qt.Key.Key_Return)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.chamfer_distance_first == 2 and editor.canvas.mixed_move_is_valid
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert editor.canvas.chamfer_distance_first == 4 and editor.canvas.mixed_move_is_valid
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    assert services.kernel.drawing_chamfer_values == (4, 5, 0, 0)


def test_new_drawing_chamfer_angle_starts_at_zero(
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
    editor = window.active_sketch_dialog()
    assert editor is not None and editor.canvas.chamfer_last_angle == 0
    editor.drawing_command_bar.input.setText("CHAMFERD")
    QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert "0" in editor.drawing_command_bar.status.text()


def test_chamfer_system_variables_persist_and_replay(
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
    for entry in ("CHAMFERA", "2", "CHAMFERB", "3", "CHAMFERC", "4", "CHAMFERD", "30"):
        editor.drawing_command_bar.input.setText(entry)
        QTest.keyClick(editor.drawing_command_bar.input, Qt.Key.Key_Return)
    assert len(loaded.document.commands) == 4
    path = tmp_path / "chamfer-system.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.drawing_chamfer_values == (2, 3, 4, 30)
    reopened.bus.undo()
    assert restored.kernel.drawing_chamfer_values == (2, 3, 4, 0)
    reopened.bus.redo()
    assert restored.kernel.drawing_chamfer_values == (2, 3, 4, 30)


def test_chamfer_setting_preserves_pending_cross_sketch_tangencies(
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
    circles = (CircleEntity(uuid4().hex, (30, 0), 2), CircleEntity(uuid4().hex, (40, 0), 2))
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), circles), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "4"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((31.7, 1.1), (38.3, 1.1)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    pending = tuple(canvas.pending_cross_tangencies)
    assert len(pending) == 2
    for value in ("CHAMFERA", "3"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    assert tuple(canvas.pending_cross_tangencies) == pending
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.chamfer_distance_first == 0 and tuple(canvas.pending_cross_tangencies) == pending
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert canvas.chamfer_distance_first == 3 and tuple(canvas.pending_cross_tangencies) == pending
    editor.finish_button.click()
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=10000
    )
    relations = services.kernel.cross_sketch_tangencies
    assert len(relations) == 2
    path = tmp_path / "pending-tangencies.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    reopened = app.open_app_document(restored, path)
    assert restored.kernel.cross_sketch_tangencies == relations
    reopened.bus.undo()
    assert not restored.kernel.cross_sketch_tangencies
    reopened.bus.redo()
    assert restored.kernel.cross_sketch_tangencies == relations


def test_chamfer_multiple_undo_after_setting_change(
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
    app.commit_new_sketch(
        services, loaded, Sketch(uuid4().hex, WorkPlaneFrame.xy(), (polyline,)), session_identity=0
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("CHAMFER", "D", "2", "3", "M", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.sketches[0].entities != (polyline,),
        timeout=10000,
    )
    for value in ("D", "4", "5"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    saved_setting = loaded.document.commands[-1]
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.sketches[0].entities == (polyline,),
        timeout=10000,
    )
    assert services.kernel.drawing_chamfer_values[:2] == (4, 5)
    assert loaded.document.commands[-1] == replace(saved_setting, ordinal=saved_setting.ordinal - 1)
    command.clear()
    QTest.keyClick(command, Qt.Key.Key_Return)
    window.request_undo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert services.kernel.sketches[0].entities != (polyline,)
    window.request_redo()
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=10000)
    assert services.kernel.sketches[0].entities == (polyline,)
    path = tmp_path / "chamfer-command-undo.my2d"
    save_document(loaded.document, path)
    restored = app.build_app(discoverers=[])
    app.open_app_document(restored, path)
    assert restored.kernel.sketches[0].entities == (polyline,)
    assert restored.kernel.drawing_chamfer_values[:2] == (4, 5)


def test_chamfer_multiple_undo_keeps_later_settings_across_two_edits(
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
    first = PolylineEntity(uuid4().hex, ((0, 0), (20, 0), (20, 20)))
    second = PolylineEntity(uuid4().hex, ((30, 0), (50, 0), (50, 20)))
    app.commit_new_sketch(
        services,
        loaded,
        Sketch(uuid4().hex, WorkPlaneFrame.xy(), (first, second)),
        session_identity=0,
    )
    editor.set_context_sketches(services.kernel.sketches)
    canvas = editor.canvas
    command = editor.drawing_command_bar.input
    for value in ("CHAMFER", "D", "2", "3", "M", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((10, 0)))
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.sketches[0].entities[0] != first, timeout=10000
    )
    for value in ("D", "4", "5", "P"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen((40, 0)))
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.sketches[0].entities[1] != second,
        timeout=10000,
    )
    for value in ("D", "6", "7", "U"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: (
            not unit.is_busy
            and not unit.is_delivering_result
            and services.kernel.sketches[0].entities[1] == second
        ),
        timeout=10000,
    )
    for value in ("CHAMFERA", "8", "FILLETRAD", "3"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    settings_before = tuple(
        item
        for item in loaded.document.commands
        if item.id in {"drawing.chamfer_values.set", "drawing.fillet_radius.set"}
    )
    command.setText("U")
    QTest.keyClick(command, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: not unit.is_busy and services.kernel.sketches[0].entities == (first, second),
        timeout=10000,
    )
    assert services.kernel.drawing_chamfer_values[:2] == (8, 7)
    assert services.kernel.drawing_fillet_radius == 3
    settings_after = tuple(
        item
        for item in loaded.document.commands
        if item.id in {"drawing.chamfer_values.set", "drawing.fillet_radius.set"}
    )
    assert len(settings_after) == len(settings_before)
    assert all(
        new == replace(old, ordinal=new.ordinal)
        for old, new in zip(settings_before, settings_after, strict=True)
    )
