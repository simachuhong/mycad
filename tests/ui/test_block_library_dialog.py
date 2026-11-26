# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""The library browser shows actual assets and reports unavailable sources."""

from dataclasses import replace
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from pytestqt.qtbot import QtBot

from mycad.core.block_library import BlockAsset
from mycad.core.drawing_blocks import BlockDefinition
from mycad.core.drawing_text import DrawingText, TextStyleTable
from mycad.core.sketch import LineEntity
from mycad.core.sketch_layers import SketchLayerTable
from mycad.libraries.block_store import BlockLibraryStore, LibraryRoot
from mycad.ui.block_library_dialog import BlockLibraryDialog


def test_browser_lists_searches_and_previews_assets(qtbot: QtBot, tmp_path: Path) -> None:
    root = LibraryRoot("local", tmp_path / "lib", False)
    store = BlockLibraryStore((root,), tmp_path / "cache")
    definition = BlockDefinition(
        uuid4().hex,
        "垫片",
        (LineEntity(uuid4().hex, (0, 0), (5, 0)),),
        (DrawingText(uuid4().hex, "M10", (1, 1)),),
    )
    asset = BlockAsset(
        uuid4().hex, "垫片", "说明", ("紧固件",), definition, TextStyleTable(), SketchLayerTable()
    )
    store.save("local", "紧固件", asset, expected_digest=None)
    dialog = BlockLibraryDialog(store, (root,))
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.results.count() == 1, timeout=10000)
    assert dialog.results.item(0).text() == "垫片"
    dialog.results.setCurrentRow(0)
    assert dialog.selected_entry() is not None
    assert dialog.preview.canvas.drawing_block_view().geometry
    assert dialog.preview.canvas.drawing_block_view().texts
    dialog.search.setText("不存在")
    assert dialog.results.count() == 0
    dialog.close()


def test_browser_reports_offline_shared_root(qtbot: QtBot, tmp_path: Path) -> None:
    root = LibraryRoot("shared", tmp_path / "offline", True)
    store = BlockLibraryStore((root,), tmp_path / "cache")
    dialog = BlockLibraryDialog(store, (root,))
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: "不可用" in dialog.message.text(), timeout=10000)
    dialog.close()


def test_scan_ignores_stale_root_and_finishes_after_dialog_destroyed(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    from shiboken6 import isValid

    from mycad.libraries.block_store import LibraryScan

    local = LibraryRoot("local", tmp_path / "local", False)
    shared = LibraryRoot("shared", tmp_path / "shared", True)
    local.path.mkdir()
    shared.path.mkdir()
    store = BlockLibraryStore((local, shared), tmp_path / "cache")
    definition = BlockDefinition(
        uuid4().hex, "本地", (LineEntity(uuid4().hex, (0, 0), (1, 0)),), ()
    )
    asset = BlockAsset(
        uuid4().hex, "本地", "", (), definition, TextStyleTable(), SketchLayerTable()
    )
    store.save("local", "", asset, expected_digest=None)
    started = Event()
    release = Event()
    completed = Event()
    original = store.scan

    def scan(root_id: str) -> LibraryScan:
        if root_id == "local":
            started.set()
            assert release.wait(10)
        result = original(root_id)
        if root_id == "local":
            completed.set()
        return result

    monkeypatch.setattr(store, "scan", scan)
    dialog = BlockLibraryDialog(store, (local, shared))
    dialog.show()
    qtbot.waitUntil(started.is_set, timeout=10000)
    dialog.source.setCurrentIndex(1)
    qtbot.waitUntil(lambda: dialog.message.text() == "块库为空。", timeout=10000)
    release.set()
    qtbot.waitUntil(completed.is_set, timeout=10000)
    qtbot.wait(100)
    assert dialog.source.currentData() == "shared" and dialog.results.count() == 0
    assert dialog.message.text() == "块库为空。"

    release.clear()
    started.clear()
    completed.clear()
    dialog.source.setCurrentIndex(0)
    qtbot.waitUntil(started.is_set, timeout=10000)
    dialog.close()
    dialog.deleteLater()
    qtbot.waitUntil(lambda: not isValid(dialog), timeout=10000)
    release.set()
    qtbot.waitUntil(completed.is_set, timeout=10000)
    qtbot.wait(100)


def test_save_dialog_keeps_input_after_failure_and_reports_success(qtbot: QtBot) -> None:
    from mycad.ui.block_library_dialog import BlockLibrarySaveDialog

    seen: list[tuple[str, str, tuple[str, ...], str]] = []

    def save(name: str, description: str, tags: tuple[str, ...], category: str) -> str:
        seen.append((name, description, tags, category))
        if len(seen) == 1:
            raise ValueError("写入失败")
        return "/library/block.myblock"

    dialog = BlockLibrarySaveDialog("B", save)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.name_field.setText("垫片")
    dialog.tags_field.setText("紧固件, 标准")
    dialog.save_button.click()
    assert dialog.isVisible() and dialog.name_field.text() == "垫片"
    assert "写入失败" in dialog.message.text()
    dialog.save_button.click()
    assert seen[-1] == ("垫片", "", ("紧固件", "标准"), "")
    assert "/library/block.myblock" in dialog.message.text()
    dialog.close()


def test_save_dialog_previews_definition_at_local_origin(qtbot: QtBot) -> None:
    from mycad.ui.block_library_dialog import BlockLibrarySaveDialog

    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ())
    asset = BlockAsset(uuid4().hex, "B", "", (), definition, TextStyleTable(), SketchLayerTable())

    def save(_name: str, _description: str, _tags: tuple[str, ...], _category: str) -> str:
        return "saved"

    dialog = BlockLibrarySaveDialog("B", save, preview_asset=asset)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.preview.canvas.drawing_block_view().geometry
    assert "基点 (0, 0)" in dialog.preview_caption.text()
    assert "比例 1" in dialog.preview_caption.text()
    dialog.close()


def test_preview_fits_curve_and_text(qtbot: QtBot) -> None:
    from mycad.core.sketch import PolylineEntity
    from mycad.ui.block_library_preview import BlockLibraryPreviewWidget

    curve = PolylineEntity(uuid4().hex, ((100, 100), (200, 100), (200, 150)))
    text = DrawingText(uuid4().hex, "中文", (150, 130))
    definition = BlockDefinition(uuid4().hex, "预览", (curve,), (text,))
    asset = BlockAsset(
        uuid4().hex, "预览", "", (), definition, TextStyleTable(), SketchLayerTable()
    )
    widget = BlockLibraryPreviewWidget()
    qtbot.addWidget(widget)
    widget.resize(400, 300)
    widget.show()
    widget.set_asset(asset)
    for point in ((100, 100), (200, 150)):
        assert widget.canvas.rect().contains(widget.canvas.local_to_screen(point))
    assert len(widget.canvas.drawing_block_view().texts) == 1
    widget.close()


def test_shared_root_can_be_added_and_removed_without_deleting_files(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QFileDialog

    local = LibraryRoot("local", tmp_path / "local", False)
    shared = LibraryRoot("team", tmp_path / "team", True)
    local.path.mkdir()
    shared.path.mkdir()
    marker = shared.path / "marker.txt"
    marker.write_text("keep", encoding="utf-8")
    roots = (local,)
    store = BlockLibraryStore(roots, tmp_path / "cache")

    def configure(add: bool, path: Path):
        assert path == shared.path
        configured = (local, shared) if add else (local,)
        return BlockLibraryStore(configured, tmp_path / "cache"), configured

    dialog = BlockLibraryDialog(store, roots, configure_shared=configure)
    qtbot.addWidget(dialog)
    dialog.show()

    def pick_directory(*_args: object, **_kwargs: object) -> str:
        return str(shared.path)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", pick_directory)
    dialog.add_shared_button.click()
    assert dialog.source.count() == 2 and dialog.source.currentData() == "team"
    dialog.remove_shared_button.click()
    assert dialog.source.count() == 1 and marker.read_text(encoding="utf-8") == "keep"
    dialog.close()


def test_local_library_rename_delete_and_restore(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    root = LibraryRoot("local", tmp_path / "lib", False)
    store = BlockLibraryStore((root,), tmp_path / "cache")
    definition = BlockDefinition(uuid4().hex, "B", (LineEntity(uuid4().hex, (0, 0), (2, 0)),), ())
    asset = BlockAsset(uuid4().hex, "B", "", (), definition, TextStyleTable(), SketchLayerTable())
    store.save("local", "", asset, expected_digest=None)
    dialog = BlockLibraryDialog(store, (root,))
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.results.count() == 1, timeout=10000)
    dialog.results.setCurrentRow(0)

    def name(*_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "新名", True

    def confirm(*_args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        return QMessageBox.StandardButton.Yes

    def choose(*args: object, **_kwargs: object) -> tuple[str, bool]:
        items = args[3]
        assert isinstance(items, list)
        values = cast("list[str]", items)
        return next(item for item in values if item.startswith("已删除")), True

    monkeypatch.setattr(QInputDialog, "getText", name)
    monkeypatch.setattr(QMessageBox, "question", confirm)
    monkeypatch.setattr(QInputDialog, "getItem", choose)
    dialog.rename_button.click()
    qtbot.waitUntil(
        lambda: dialog.results.count() == 1 and dialog.results.item(0).text() == "新名",
        timeout=10000,
    )
    dialog.results.setCurrentRow(0)
    dialog.delete_button.click()
    qtbot.waitUntil(lambda: dialog.results.count() == 0, timeout=10000)
    dialog.restore_button.click()
    qtbot.waitUntil(lambda: dialog.results.count() == 1, timeout=10000)
    assert dialog.results.item(0).text() == "新名"
    dialog.close()


def test_dxf_selection_shows_issues_and_selects_multiple(qtbot: QtBot) -> None:
    from mycad.core.block_library_import import AssetIssue
    from mycad.ui.block_library_dxf import DxfBlockSelectionDialog

    line = LineEntity(uuid4().hex, (0, 0), (1, 1))
    a = BlockDefinition(uuid4().hex, "A", (line,), ())
    b = BlockDefinition(uuid4().hex, "B", (replace(line, entity_id=uuid4().hex),), ())
    assets = tuple(
        BlockAsset(
            uuid4().hex, definition.name, "", (), definition, TextStyleTable(), SketchLayerTable()
        )
        for definition in (a, b)
    )
    dialog = DxfBlockSelectionDialog(assets, (AssetIssue("unsupported", "NESTED 不支持"),))
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.selected_assets() == assets
    assert "NESTED" in dialog.issues.text()
    dialog.list.item(1).setSelected(False)
    assert dialog.selected_assets() == (assets[0],)
    dialog.close()


def test_dxf_import_and_previewed_export(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog

    from mycad.formats.block_library_dxf import write_block_asset_dxf
    from mycad.formats.providers.dxf_provider import read_sketch_dxf
    from mycad.ui.block_library_dxf import DxfBlockSelectionDialog
    from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog

    root = LibraryRoot("local", tmp_path / "lib", False)
    root.path.mkdir()
    store = BlockLibraryStore((root,), tmp_path / "cache")
    definition = BlockDefinition(uuid4().hex, "DXF", (LineEntity(uuid4().hex, (0, 0), (2, 1)),), ())
    asset = BlockAsset(uuid4().hex, "DXF", "", (), definition, TextStyleTable(), SketchLayerTable())
    source, output = tmp_path / "source.dxf", tmp_path / "output.dxf"
    write_block_asset_dxf(asset, source)
    dialog = BlockLibraryDialog(store, (root,))
    qtbot.addWidget(dialog)
    dialog.show()

    def open_file(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(source), "DXF"

    def save_file(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(output), "DXF"

    def accept_import() -> None:
        modal = QApplication.activeModalWidget()
        assert isinstance(modal, DxfBlockSelectionDialog)
        modal.accept()

    def accept_export() -> None:
        modal = QApplication.activeModalWidget()
        assert isinstance(modal, DxfOutputPreviewDialog)
        modal.accept()

    monkeypatch.setattr(QFileDialog, "getOpenFileName", open_file)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_file)
    QTimer.singleShot(0, accept_import)
    dialog.import_dxf_button.click()
    qtbot.waitUntil(lambda: dialog.results.count() == 1, timeout=10000)
    dialog.results.setCurrentRow(0)
    QTimer.singleShot(0, accept_export)
    dialog.export_dxf_button.click()
    assert output.exists() and len(read_sketch_dxf(output).block_instances) == 1
    dialog.close()


def test_dxf_modelspace_dialog_captures_name_and_base(qtbot: QtBot) -> None:
    from mycad.ui.block_library_dxf import DxfModelspaceDialog

    dialog = DxfModelspaceDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.name_field.setText("Model")
    dialog.x_field.setValue(12.5)
    dialog.y_field.setValue(-4)
    assert dialog.name_field.text() == "Model"
    assert (dialog.x_field.value(), dialog.y_field.value()) == (12.5, -4)
    dialog.close()


def test_dxf_modelspace_import_requires_confirmation(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog

    from mycad.core.sketch import Sketch, WorkPlaneFrame
    from mycad.formats.providers.dxf_provider import write_sketches_dxf
    from mycad.ui.block_library_dxf import DxfModelspaceDialog

    root = LibraryRoot("local", tmp_path / "lib", False)
    root.path.mkdir()
    store = BlockLibraryStore((root,), tmp_path / "cache")
    sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (LineEntity(uuid4().hex, (1, 2), (3, 2)),))
    source = tmp_path / "model.dxf"
    write_sketches_dxf((sketch,), source)
    dialog = BlockLibraryDialog(store, (root,))
    qtbot.addWidget(dialog)
    dialog.show()

    def open_file(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return str(source), "DXF"

    def accept_model() -> None:
        modal = QApplication.activeModalWidget()
        assert isinstance(modal, DxfModelspaceDialog)
        modal.name_field.setText("MODEL")
        modal.x_field.setValue(1)
        modal.y_field.setValue(2)
        modal.accept()

    monkeypatch.setattr(QFileDialog, "getOpenFileName", open_file)
    QTimer.singleShot(0, accept_model)
    dialog.import_modelspace_button.click()
    qtbot.waitUntil(lambda: dialog.results.count() == 1, timeout=10000)
    entry = store.scan("local").entries[0]
    line = entry.asset.definition.entities[0]
    assert isinstance(line, LineEntity) and line.start_mm == (0, 0)
    dialog.close()


def test_preview_reports_font_substitution(qtbot: QtBot, tmp_path: Path) -> None:
    from mycad.core.drawing_text import TextStyle

    root = LibraryRoot("local", tmp_path / "lib", False)
    store = BlockLibraryStore((root,), tmp_path / "cache")
    style = TextStyle(style_id="missing", name="missing", font_family="MyCAD No Such Font 91F2")
    definition = BlockDefinition(
        uuid4().hex, "Text", (), (DrawingText(uuid4().hex, "文字", (0, 0), style_id="missing"),)
    )
    asset = BlockAsset(
        uuid4().hex,
        "Text",
        "",
        (),
        definition,
        TextStyleTable((style,), "missing"),
        SketchLayerTable(),
    )
    store.save("local", "", asset, expected_digest=None)
    dialog = BlockLibraryDialog(store, (root,))
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.results.count() == 1, timeout=10000)
    dialog.results.setCurrentRow(0)
    assert "字体" in dialog.details.text() and "替代" in dialog.details.text()
    dialog.close()
