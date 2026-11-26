# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The current-document block manager exposes saving definitions to a library."""

from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from pytestqt.qtbot import QtBot

from mycad import app
from mycad.core.drawing_blocks import BlockDefinition
from mycad.core.sketch import LineEntity
from mycad.ui.drawing_block_dialogs import BlockManagerDialog

_ENSURE_METHOD = "_ensure_collection_session"


def _skip_paint(*_args: object) -> None:
    pass


def test_manager_saves_unplaced_definition(qtbot: QtBot) -> None:
    services = app.build_app(discoverers=[])
    loaded = app.new_workspace_document(services, kind="sketch")
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ())
    loaded.bus.execute("drawing.block.create", definition.to_mapping(), "local")
    saved: list[str] = []
    dialog = BlockManagerDialog(
        lambda: app.drawing_collection_snapshot(services),
        lambda _: None,
        lambda _id, _name: None,
        save_to_library=saved.append,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.library_button.click()
    assert saved == [definition.definition_id]
    dialog.close()


def test_export_fillet_draft_to_library_then_cancel_without_committing(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialogButtonBox

    from mycad.libraries.block_store import BlockLibraryStore, LibraryRoot
    from mycad.ui.block_library_dialog import BlockLibrarySaveDialog
    from mycad.ui.drawing_block_dialogs import BlockCreateDialog
    from mycad.ui.main_window import MainWindow

    root = LibraryRoot("local", tmp_path / "library", False)
    store = BlockLibraryStore((root,), tmp_path / "cache")
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_paint)
    monkeypatch.setattr(window, "_block_library_store", lambda: (store, (root,)))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    loaded = window.loaded_document()
    assert editor is not None and loaded is not None
    canvas = editor.canvas
    first = LineEntity(uuid4().hex, (0, 0), (10, 0))
    second = LineEntity(uuid4().hex, (0, 0), (0, 10))
    assert canvas.replace_draft_entities((first, second))
    command = editor.drawing_command_bar.input
    for value in ("FILLET", "R", "2"):
        command.setText(value)
        QTest.keyClick(command, Qt.Key.Key_Return)
    for point in ((8, 0), (0, 8)):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.local_to_screen(point))
    assert len(canvas.constraints) == 4 and len(canvas.entities) == 3
    assert canvas.set_tool("选择元素")
    canvas.selected_entity_ids = {item.entity_id for item in canvas.entities}

    def create() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockCreateDialog)
        dialog.name_field.setText("草稿圆角块")
        dialog.source_mode.setCurrentIndex(1)
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        buttons.button(QDialogButtonBox.StandardButton.Ok).click()

    QTimer.singleShot(0, create)
    editor.block_create_button.click()
    assert canvas.collection_session is not None, editor.drawing_command_bar.status.text()
    before = tuple(loaded.document.commands)

    def save() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockLibrarySaveDialog)
        assert len(dialog.preview.canvas.drawing_block_view().geometry) == 3
        dialog.save_button.click()
        assert "已保存" in dialog.message.text()
        dialog.close()

    def manage() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockManagerDialog)
        QTimer.singleShot(0, save)
        dialog.library_button.click()
        dialog.close()

    QTimer.singleShot(0, manage)
    editor.block_manage_button.click()
    assert tuple(loaded.document.commands) == before
    entries = store.scan("local").entries
    assert len(entries) == 1 and len(store.read(entries[0]).definition.entities) == 3
    editor.cancel_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor, timeout=15000)
    assert tuple(loaded.document.commands) == before
    assert store.read(entries[0]).name == "草稿圆角块"


def test_import_conflicting_library_definition_reports_and_can_cancel(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from mycad.core.block_library import BlockAsset
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.core.sketch_layers import SketchLayerTable
    from mycad.libraries.block_store import BlockLibraryStore, LibraryRoot
    from mycad.ui.block_library_dialog import BlockLibraryDialog
    from mycad.ui.main_window import MainWindow

    root = LibraryRoot("local", tmp_path / "lib", False)
    store = BlockLibraryStore((root,), tmp_path / "cache")
    original = BlockDefinition(uuid4().hex, "同名", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ())
    incoming = BlockDefinition(uuid4().hex, "同名", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ())
    store.save(
        "local",
        "",
        BlockAsset(uuid4().hex, "同名", "", (), incoming, TextStyleTable(), SketchLayerTable()),
        expected_digest=None,
    )
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_paint)
    monkeypatch.setattr(window, "_block_library_store", lambda: (store, (root,)))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    getattr(window, _ENSURE_METHOD)(editor)
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block.create", 1, original.to_mapping(), "local")
    )
    reports: list[str] = []

    def decline(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        reports.append(str(args[2]))
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", decline)

    def browse() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockLibraryDialog)
        qtbot.waitUntil(lambda: dialog.results.count() == 1, timeout=10000)
        dialog.results.setCurrentRow(0)
        dialog.import_button.click()

    QTimer.singleShot(0, browse)
    editor.block_library_button.click()
    qtbot.waitUntil(lambda: bool(reports), timeout=15000)
    assert "同名" in reports[0] and "副本" in reports[0]
    session = editor.canvas.collection_session
    assert session is not None and session.snapshot.block_definitions == (original,)
    editor.cancel_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor, timeout=15000)


@pytest.mark.parametrize(
    "ending", ["finish", "cancel", "cancel_before_browse", "cancel_after_browse"]
)
def test_toolbar_library_imports_saved_definition(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ending: str
) -> None:

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from mycad.core.replay_proposal import ReplayAppend
    from mycad.libraries.block_store import BlockLibraryStore, LibraryRoot
    from mycad.ui.block_library_dialog import BlockLibraryDialog, BlockLibrarySaveDialog
    from mycad.ui.drawing_collection_session import DrawingCollectionSession
    from mycad.ui.main_window import MainWindow

    root = LibraryRoot("local", tmp_path / "library", False)
    store = BlockLibraryStore((root,), tmp_path / "cache")
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_paint)
    monkeypatch.setattr(window, "_block_library_store", lambda: (store, (root,)))

    def accept(*_args: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "question", accept)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    line = LineEntity(uuid4().hex, (0, 0), (1, 0))
    definition = BlockDefinition(uuid4().hex, "B", (line,), ())
    session = cast("DrawingCollectionSession", getattr(window, _ENSURE_METHOD)(editor))
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local")
    )

    def save() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockLibrarySaveDialog)
        dialog.save_button.click()
        assert "已保存" in dialog.message.text()
        dialog.close()

    def manage() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockManagerDialog)
        QTimer.singleShot(0, save)
        dialog.library_button.click()
        dialog.close()

    QTimer.singleShot(0, manage)
    editor.block_manage_button.click()
    assert len(store.scan("local").entries) == 1
    if ending == "cancel_before_browse":
        editor.cancel_button.click()
        qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor, timeout=15000)
        return

    def browse() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockLibraryDialog)
        qtbot.waitUntil(lambda: dialog.results.count() == 1, timeout=10000)
        dialog.results.setCurrentRow(0)
        if ending == "cancel_after_browse":
            dialog.reject()
        else:
            dialog.import_button.click()

    QTimer.singleShot(0, browse)
    editor.block_library_button.click()
    if ending == "cancel_after_browse":
        editor.cancel_button.click()
        qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor, timeout=15000)
        return
    qtbot.waitUntil(lambda: len(session.snapshot.block_definitions) == 2, timeout=15000)
    assert len(session.snapshot.block_definitions) == 2
    assert len(session.snapshot.block_library_origins) == 1
    assert not session.snapshot.block_instances
    if ending == "finish":
        editor.finish_sketch()
    else:
        editor.cancel_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor, timeout=15000)
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(lambda: not unit.is_busy, timeout=15000)


def test_cancelling_collection_session_without_library_dialog(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mycad.core.replay_proposal import ReplayAppend
    from mycad.ui.drawing_collection_session import DrawingCollectionSession
    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_paint)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    getattr(window, _ENSURE_METHOD)(editor)
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ())
    assert editor.canvas.stage_collection_operation(
        ReplayAppend("drawing.block.create", 1, definition.to_mapping(), "local")
    )
    from mycad.core.block_library import BlockAsset
    from mycad.core.block_library_import import prepare_block_library_import
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch_layers import SketchLayerTable

    asset = BlockAsset(uuid4().hex, "B", "", (), definition, TextStyleTable(), SketchLayerTable())
    session = cast("DrawingCollectionSession", editor.canvas.collection_session)
    prepared = prepare_block_library_import(asset, session.snapshot, placement=None)
    assert prepared.operation is not None
    assert editor.canvas.stage_collection_operation(prepared.operation)
    editor.cancel_button.click()
    qtbot.waitUntil(lambda: window.active_sketch_dialog() is not editor, timeout=15000)


def test_block_library_commands_can_be_repeated(qtbot: QtBot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.sketch_editor import SketchEditorDialog

    editor = SketchEditorDialog(select_committed_entities=True)
    qtbot.addWidget(editor)
    editor.show()
    opened: list[str] = []
    editor.block_library_requested.connect(lambda: opened.append("library"))
    editor.block_write_requested.connect(lambda: opened.append("write"))
    bar = editor.drawing_command_bar.input
    bar.setText("BLOCKLIB")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.keyClick(bar, Qt.Key.Key_Return)
    bar.setText("WBLOCK")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert opened == ["library", "library", "write", "write"]


def test_insert_with_empty_document_opens_library(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from mycad.ui.main_window import MainWindow

    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_paint)
    opened: list[object] = []

    def open_library(editor: object) -> None:
        opened.append(editor)

    monkeypatch.setattr(window, "_open_block_library", open_library)
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    bar = editor.drawing_command_bar.input
    bar.setText("INSERT")
    QTest.keyClick(bar, Qt.Key.Key_Return)
    assert opened == [editor]
    editor.cancel_button.click()


def test_insert_dialog_offers_library_for_existing_definitions(qtbot: QtBot) -> None:
    from mycad.ui.drawing_block_dialogs import OPEN_BLOCK_LIBRARY, BlockInsertDialog

    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ())
    dialog = BlockInsertDialog((definition,))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.library_button.click()
    assert dialog.result() == OPEN_BLOCK_LIBRARY


@pytest.mark.parametrize("shared", [False, True], ids=["local", "shared-readonly"])
def test_insert_library_in_new_drawing_and_reopen(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, shared: bool
) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialogButtonBox

    from mycad.core.block_library import BlockAsset
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.persistence import save_document
    from mycad.core.sketch_layers import SketchLayerTable
    from mycad.libraries.block_store import BlockLibraryStore, LibraryRoot
    from mycad.ui.block_library_dialog import BlockLibraryDialog
    from mycad.ui.drawing_block_dialogs import BlockInsertDialog
    from mycad.ui.main_window import MainWindow

    root = LibraryRoot("source", tmp_path / "library", shared)
    writable = LibraryRoot("source", root.path, False)
    store = BlockLibraryStore((writable,), tmp_path / "cache")
    definition = BlockDefinition(
        uuid4().hex, "跨图纸", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ()
    )
    asset = BlockAsset(
        uuid4().hex, "跨图纸", "", (), definition, TextStyleTable(), SketchLayerTable()
    )
    store.save("source", "", asset, expected_digest=None)
    store = BlockLibraryStore((root,), tmp_path / "cache")
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_paint)
    monkeypatch.setattr(window, "_block_library_store", lambda: (store, (root,)))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None

    def place() -> None:
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, BlockInsertDialog):
            QTimer.singleShot(25, place)
            return
        dialog.x_field.setValue(12)
        dialog.y_field.setValue(34)
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        buttons.button(QDialogButtonBox.StandardButton.Ok).click()

    def browse() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, BlockLibraryDialog)
        qtbot.waitUntil(lambda: dialog.results.count() == 1, timeout=10000)
        dialog.results.setCurrentRow(0)
        assert dialog.delete_button.isEnabled() is not shared
        QTimer.singleShot(0, place)
        dialog.insert_button.click()

    QTimer.singleShot(0, browse)
    editor.block_insert_button.click()
    qtbot.waitUntil(
        lambda: (
            editor.canvas.collection_session is not None
            and len(editor.canvas.collection_session.snapshot.block_instances) == 1
        ),
        timeout=15000,
    )
    session = editor.canvas.collection_session
    assert session is not None and session.snapshot.block_instances[0].insertion_mm == (12, 34)
    editor.finish_sketch()
    unit = window.execution_unit
    assert unit is not None
    qtbot.waitUntil(
        lambda: window.active_sketch_dialog() is not editor and not unit.is_busy, timeout=15000
    )
    loaded = window.loaded_document()
    assert loaded is not None
    path = tmp_path / "destination.my2d"
    save_document(loaded.document, path)
    import shutil

    shutil.rmtree(root.path)
    reopened = app.open_app_document(services, path)
    assert services.kernel.drawing_block_instances[0].insertion_mm == (12, 34)
    reopened.bus.undo_operation()
    assert (
        not services.kernel.drawing_block_instances
        and not services.kernel.drawing_block_definitions
    )


@pytest.mark.parametrize("confirmation", ["enter", "right", "click", "escape"])
def test_library_insertion_canvas_preview_enter_and_cancel(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, confirmation: str
) -> None:
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from mycad.core.block_library import BlockAsset
    from mycad.core.drawing_text import TextStyleTable
    from mycad.core.sketch_layers import SketchLayerTable
    from mycad.libraries.block_store import BlockLibraryStore, LibraryRoot
    from mycad.ui.block_library_dialog import BlockLibraryDialog
    from mycad.ui.drawing_block_dialogs import BlockInsertDialog
    from mycad.ui.main_window import MainWindow

    root = LibraryRoot("local", tmp_path / "library", False)
    store = BlockLibraryStore((root,), tmp_path / "cache")
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (4, 0)),), ())
    asset = BlockAsset(uuid4().hex, "B", "", (), definition, TextStyleTable(), SketchLayerTable())
    store.save("local", "", asset, expected_digest=None)
    services = app.build_app(discoverers=[])
    window = MainWindow(services=services)
    monkeypatch.setattr(type(window.viewport), "paintGL", _skip_paint)
    monkeypatch.setattr(window, "_block_library_store", lambda: (store, (root,)))
    qtbot.addWidget(window)
    window.show()
    window.act_new_drawing.trigger()
    editor = window.active_sketch_dialog()
    assert editor is not None
    canvas = editor.canvas
    canvas.set_snapping_enabled(False)

    def place() -> None:
        modal = QApplication.activeModalWidget()
        if not isinstance(modal, BlockInsertDialog):
            QTimer.singleShot(25, place)
            return
        modal.pick_point_button.click()

    def browse() -> None:
        modal = QApplication.activeModalWidget()
        assert isinstance(modal, BlockLibraryDialog)
        qtbot.waitUntil(lambda: modal.results.count() == 1, timeout=10000)
        modal.results.setCurrentRow(0)
        QTimer.singleShot(0, place)
        modal.insert_button.click()

    QTimer.singleShot(0, browse)
    editor.block_library_button.click()
    qtbot.waitUntil(lambda: canvas.block_point_capture_active, timeout=15000)
    point = canvas.local_to_screen((10, 10))
    QTest.mouseMove(canvas, point + QPoint(12, 12))
    QTest.mouseMove(canvas, point)
    qtbot.waitUntil(lambda: canvas.block_library_preview_payload is not None, timeout=15000)
    session = canvas.collection_session
    assert session is not None and not session.snapshot.block_instances
    if confirmation == "escape":
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
        assert (
            not canvas.block_point_capture_active and canvas.block_library_preview_payload is None
        )
        assert not session.snapshot.block_instances and not session.snapshot.block_definitions
    else:
        if confirmation == "right":
            QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=point)
        elif confirmation == "click":
            QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
        else:
            QTest.keyClick(canvas, Qt.Key.Key_Return)
        qtbot.waitUntil(lambda: len(session.snapshot.block_instances) == 1, timeout=15000)
        assert session.snapshot.block_instances[0].insertion_mm == pytest.approx((10, 10), abs=0.2)
        assert canvas.undo_last_operation() and not session.snapshot.block_instances
    editor.cancel_button.click()
