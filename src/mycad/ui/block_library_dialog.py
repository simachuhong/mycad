# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Browse validated local or shared block assets without blocking the canvas."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mycad.core.block_library import BlockAsset
from mycad.core.exceptions import ValidationError
from mycad.libraries.block_store import BlockLibraryStore, LibraryEntry, LibraryRoot, LibraryScan
from mycad.ui.block_library_preview import BlockLibraryPreviewWidget

IMPORT_DEFINITION = 10
INSERT_BLOCK = 11


class _ScanWorker(QThread):
    """Retain each thread until Qt signals it has completely stopped."""

    completed = Signal(int, object)
    _active: set[_ScanWorker] = set()

    def __init__(self, store: BlockLibraryStore, root_id: str, generation: int) -> None:
        super().__init__()
        self.store = store
        self.root_id = root_id
        self.generation = generation
        self._active.add(self)
        self.finished.connect(self._release)

    def run(self) -> None:
        try:
            result = self.store.scan(self.root_id)
        except (OSError, ValueError) as exc:
            result = exc
        self.completed.emit(self.generation, result)

    def _release(self) -> None:
        self._active.discard(self)
        self.deleteLater()


class BlockLibraryDialog(QDialog):
    """A searchable list of block files with their real rendered definition."""

    def __init__(
        self,
        store: BlockLibraryStore,
        roots: tuple[LibraryRoot, ...],
        parent: QWidget | None = None,
        *,
        configure_shared: Callable[[bool, Path], tuple[BlockLibraryStore, tuple[LibraryRoot, ...]]]
        | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("块库")
        self.resize(850, 560)
        self._store = store
        self._roots = roots
        self._configure_shared = configure_shared
        self._generation = 0
        self._workers: dict[int, _ScanWorker] = {}
        self._entries: tuple[LibraryEntry, ...] = ()
        self._notice = ""
        self.source = QComboBox()
        for root in roots:
            self.source.addItem(
                f"{'共享（只读）' if root.read_only else '本地'} · {root.path}", root.root_id
            )
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名称、说明或标签")
        self.results = QListWidget()
        self.preview = BlockLibraryPreviewWidget()
        self.details = QLabel("请选择块。")
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.import_button = QPushButton("仅导入定义")
        self.insert_button = QPushButton("插入图纸")
        self.rename_button = QPushButton("重命名")
        self.delete_button = QPushButton("移入回收站")
        self.restore_button = QPushButton("恢复…")
        self.import_dxf_button = QPushButton("导入 DXF…")
        self.import_modelspace_button = QPushButton("DXF 模型空间入库…")
        self.export_dxf_button = QPushButton("导出 DXF…")
        refresh = QPushButton("刷新")
        self.add_shared_button = QPushButton("添加共享目录…")
        self.remove_shared_button = QPushButton("移除共享目录")
        self.add_shared_button.setVisible(configure_shared is not None)
        self.remove_shared_button.setVisible(configure_shared is not None)
        close = QPushButton("关闭")
        top = QHBoxLayout()
        top.addWidget(self.source, 1)
        top.addWidget(refresh)
        top.addWidget(self.add_shared_button)
        top.addWidget(self.remove_shared_button)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.search)
        left_layout.addWidget(self.results)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.preview, 1)
        right_layout.addWidget(self.details)
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        buttons = QHBoxLayout()
        buttons.addWidget(self.import_button)
        buttons.addWidget(self.insert_button)
        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.restore_button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        exchange = QHBoxLayout()
        exchange.addWidget(self.import_dxf_button)
        exchange.addWidget(self.import_modelspace_button)
        exchange.addWidget(self.export_dxf_button)
        exchange.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.message)
        layout.addLayout(exchange)
        layout.addLayout(buttons)
        self.source.currentIndexChanged.connect(self.refresh)
        self.add_shared_button.clicked.connect(self._add_shared)
        self.remove_shared_button.clicked.connect(self._remove_shared)
        refresh.clicked.connect(self.refresh)
        self.search.textChanged.connect(self._filter)
        self.results.currentRowChanged.connect(self._select)
        self.results.itemDoubleClicked.connect(self._double_click)
        self.import_button.clicked.connect(lambda: self._finish(IMPORT_DEFINITION))
        self.insert_button.clicked.connect(lambda: self._finish(INSERT_BLOCK))
        self.rename_button.clicked.connect(self._rename)
        self.delete_button.clicked.connect(self._delete)
        self.restore_button.clicked.connect(self._restore)
        self.import_dxf_button.clicked.connect(self._import_dxf)
        self.import_modelspace_button.clicked.connect(self._import_dxf_modelspace)
        self.export_dxf_button.clicked.connect(self._export_dxf)
        close.clicked.connect(self.reject)
        self._select()
        self.refresh()

    @property
    def store(self) -> BlockLibraryStore:
        return self._store

    def _configure(self, add: bool, path: Path) -> None:
        if self._configure_shared is None:
            return
        try:
            self._store, self._roots = self._configure_shared(add, path)
        except (OSError, ValueError, ValidationError) as exc:
            self.message.setText(str(exc))
            return
        self.source.blockSignals(True)
        self.source.clear()
        selected = 0
        for index, root in enumerate(self._roots):
            self.source.addItem(
                f"{'共享（只读）' if root.read_only else '本地'} · {root.path}", root.root_id
            )
            if add and root.path == path:
                selected = index
        self.source.setCurrentIndex(selected)
        self.source.blockSignals(False)
        self.refresh()

    def _add_shared(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择共享块库目录")
        if path:
            self._configure(True, Path(path))

    def _remove_shared(self) -> None:
        identity = self.source.currentData()
        root = next((item for item in self._roots if item.root_id == identity), None)
        if root is not None and root.read_only:
            self._configure(False, root.path)

    def refresh(self) -> None:
        root = next(
            (item for item in self._roots if item.root_id == self.source.currentData()), None
        )
        self.remove_shared_button.setEnabled(root is not None and root.read_only)
        self.restore_button.setEnabled(root is not None and not root.read_only)
        self.import_dxf_button.setEnabled(any(not item.read_only for item in self._roots))
        self.import_modelspace_button.setEnabled(any(not item.read_only for item in self._roots))
        self._generation += 1
        root_id = self.source.currentData()
        self._entries = ()
        self._filter()
        if not isinstance(root_id, str):
            self.message.setText("没有可用的块库目录。")
            return
        self.message.setText("正在读取块库…")
        worker = _ScanWorker(self._store, root_id, self._generation)
        self._workers[self._generation] = worker
        worker.completed.connect(self._scanned)
        worker.start()

    def _scanned(self, generation: int, value: object) -> None:
        self._workers.pop(generation, None)
        if generation != self._generation:
            return
        if not isinstance(value, LibraryScan):
            self.message.setText(f"无法读取块库：{value}")
            return
        self._entries = value.entries
        status = (
            "；".join(issue.message for issue in value.issues)
            if value.issues
            else ("" if value.entries else "块库为空。")
        )
        self.message.setText("；".join(item for item in (self._notice, status) if item))
        self._notice = ""
        self._filter()

    def _filter(self) -> None:
        term = self.search.text().strip().casefold()
        self.results.clear()
        for entry in self._entries:
            asset = entry.asset
            if (
                term
                and term not in " ".join((asset.name, asset.description, *asset.tags)).casefold()
            ):
                continue
            item = QListWidgetItem(asset.name)
            item.setData(256, entry)
            item.setToolTip(entry.relative_path)
            self.results.addItem(item)
        self._select()

    def selected_entry(self) -> LibraryEntry | None:
        item = cast("QListWidgetItem | None", self.results.currentItem())
        value = item.data(256) if item is not None else None
        return value if isinstance(value, LibraryEntry) else None

    def _select(self) -> None:
        entry = self.selected_entry()
        self.import_button.setEnabled(entry is not None)
        self.insert_button.setEnabled(entry is not None)
        self.export_dxf_button.setEnabled(entry is not None)
        root = next(
            (item for item in self._roots if item.root_id == self.source.currentData()), None
        )
        writable = root is not None and not root.read_only
        self.rename_button.setEnabled(entry is not None and writable)
        self.delete_button.setEnabled(entry is not None and writable)
        self.preview.set_asset(entry.asset if entry is not None else None)
        if entry is None:
            self.details.setText("请选择块。")
            return
        asset = entry.asset
        notices: list[str] = []
        tools = self.preview.canvas.text_tools
        if tools is not None:
            for identity in dict.fromkeys(text.style_id for text in asset.definition.texts):
                style = asset.text_styles.get(identity)
                substitute = tools.manager.substitution(style)
                if substitute:
                    notices.append(
                        f"字体 {style.font_family or style.font_file} 不可用，预览替代为 {substitute}。"
                    )
        self.details.setText(
            f"{asset.name}\n{asset.description}\n{entry.relative_path}\n"
            f"几何 {len(asset.definition.entities)} 项，文字 {len(asset.definition.texts)} 项；单位 mm。"
            + ("\n" + "\n".join(notices) if notices else "")
        )

    def _import_dxf(self) -> None:
        from mycad.formats.block_library_dxf import read_dxf_block_assets
        from mycad.formats.providers.dxf_provider import DxfUnitOverrideRequired
        from mycad.ui.block_library_dxf import DxfBlockSelectionDialog

        filename, _ = QFileDialog.getOpenFileName(self, "导入 DXF 块", "", "DXF 图纸 (*.dxf)")
        if not filename:
            return
        try:
            try:
                assets, issues = read_dxf_block_assets(Path(filename))
            except DxfUnitOverrideRequired:
                unit, accepted = QInputDialog.getItem(
                    self,
                    "DXF 单位",
                    "选择源文件的长度单位",
                    ["mm", "cm", "m", "inch", "ft", "mil", "micron"],
                    0,
                    False,
                )
                if not accepted:
                    return
                assets, issues = read_dxf_block_assets(Path(filename), unit_override=unit)
            if not assets:
                self.message.setText(
                    "没有可导入的块。" + "；".join(item.message for item in issues)
                )
                return
            selection = DxfBlockSelectionDialog(assets, issues, self)
            accepted = selection.exec() == QDialog.DialogCode.Accepted
            chosen = selection.selected_assets() if accepted else ()
            selection.deleteLater()
            if not accepted:
                return
            root = next((item for item in self._roots if not item.read_only), None)
            if root is None:
                raise ValueError("没有可写入的本地块库。")
            errors: list[str] = []
            saved = 0
            for asset in chosen:
                try:
                    self._store.save(root.root_id, "", asset, expected_digest=None)
                    saved += 1
                except (OSError, ValueError, ValidationError) as exc:
                    errors.append(f"{asset.name}：{exc}")
            self._notice = f"已导入 {saved} 个块。" + "；".join(errors)
            self.source.setCurrentIndex(
                next(i for i, item in enumerate(self._roots) if item.root_id == root.root_id)
            )
            self.refresh()
        except (OSError, ValueError, ValidationError) as exc:
            self.message.setText(f"DXF 导入失败：{exc}")

    def _import_dxf_modelspace(self) -> None:
        from mycad.formats.block_library_dxf import read_dxf_modelspace_asset
        from mycad.formats.providers.dxf_provider import DxfUnitOverrideRequired
        from mycad.ui.block_library_dxf import DxfModelspaceDialog

        filename, _ = QFileDialog.getOpenFileName(self, "选择 DXF 模型空间", "", "DXF 图纸 (*.dxf)")
        if not filename:
            return
        form = DxfModelspaceDialog(self)
        accepted = form.exec() == QDialog.DialogCode.Accepted
        name = form.name_field.text().strip()
        base = (form.x_field.value(), form.y_field.value())
        form.deleteLater()
        if not accepted:
            return
        try:
            try:
                asset = read_dxf_modelspace_asset(Path(filename), name=name, base_mm=base)
            except DxfUnitOverrideRequired:
                unit, accepted = QInputDialog.getItem(
                    self,
                    "DXF 单位",
                    "选择源文件的长度单位",
                    ["mm", "cm", "m", "inch", "ft", "mil", "micron"],
                    0,
                    False,
                )
                if not accepted:
                    return
                asset = read_dxf_modelspace_asset(
                    Path(filename), name=name, base_mm=base, unit_override=unit
                )
            root = next((item for item in self._roots if not item.read_only), None)
            if root is None:
                raise ValueError("没有可写入的本地块库。")
            self._store.save(root.root_id, "", asset, expected_digest=None)
            self._notice = f"模型空间已保存为块 {asset.name}。"
            self.source.setCurrentIndex(
                next(i for i, item in enumerate(self._roots) if item.root_id == root.root_id)
            )
            self.refresh()
        except (OSError, ValueError, ValidationError) as exc:
            self.message.setText(f"模型空间入库失败：{exc}")

    def _export_dxf(self) -> None:
        from mycad.formats.block_library_dxf import prepare_block_asset_dxf_preview
        from mycad.ui.dxf_output_preview import DxfOutputPreviewDialog

        entry = self.selected_entry()
        if entry is None:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "导出块 DXF", entry.asset.name + ".dxf", "DXF 图纸 (*.dxf)"
        )
        if not filename:
            return
        try:
            asset = self._store.read(entry)
            preview = prepare_block_asset_dxf_preview(asset)
            dialog = DxfOutputPreviewDialog(preview, filename, self)
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            dialog.deleteLater()
            if not accepted:
                return
            preview.write(Path(filename))
            self.message.setText(f"DXF 已导出：{filename}；{preview.report}")
        except (OSError, ValueError, ValidationError) as exc:
            self.message.setText(f"DXF 导出失败：{exc}")

    def _rename(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            return
        name, accepted = QInputDialog.getText(self, "重命名块", "名称", text=entry.asset.name)
        if not accepted:
            return
        try:
            asset = self._store.read(entry)
            name = name.strip()
            if not name:
                raise ValueError("请输入块名称。")
            updated = replace(asset, name=name, definition=replace(asset.definition, name=name))
            category = str(Path(entry.relative_path).parent)
            self._store.save(
                entry.root_id,
                "" if category == "." else category,
                updated,
                expected_digest=entry.file_digest,
            )
            self.refresh()
        except (OSError, ValueError, ValidationError) as exc:
            self.message.setText(str(exc))

    def _delete(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            return
        choice = QMessageBox.question(self, "移入回收站", f"将块“{entry.asset.name}”移入回收站？")
        if choice != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.trash(entry)
            self.refresh()
        except (OSError, ValueError, ValidationError) as exc:
            self.message.setText(str(exc))

    def _restore(self) -> None:
        root_id = self.source.currentData()
        if not isinstance(root_id, str):
            return
        try:
            receipts = self._store.list_recovery(root_id)
            if not receipts:
                self.message.setText("没有可恢复的块或历史版本。")
                return
            labels = [
                f"{'已删除' if item.file_digest is None else '历史版本'} · {item.relative_path} · {Path(item.previous_version_path or '').name}"
                for item in receipts
            ]
            chosen, accepted = QInputDialog.getItem(self, "恢复块", "选择版本", labels, 0, False)
            if accepted and chosen in labels:
                self._store.restore(receipts[labels.index(chosen)])
                self.refresh()
        except (OSError, ValueError, ValidationError) as exc:
            self.message.setText(str(exc))

    def _double_click(self, _item: QListWidgetItem) -> None:
        self._finish(INSERT_BLOCK)

    def _finish(self, result: int) -> None:
        if self.selected_entry() is not None:
            self.done(result)


class BlockLibrarySaveDialog(QDialog):
    """Save one definition immediately, keeping edits visible if the write fails."""

    def __init__(
        self,
        name: str,
        save: Callable[[str, str, tuple[str, ...], str], str],
        parent: QWidget | None = None,
        *,
        preview_asset: BlockAsset | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("保存到块库")
        self.resize(600, 480 if preview_asset is not None else 260)
        self._save = save
        self.name_field = QLineEdit(name)
        self.description_field = QLineEdit()
        self.tags_field = QLineEdit()
        self.category_field = QLineEdit()
        self.tags_field.setPlaceholderText("多个标签用逗号分隔")
        self.category_field.setPlaceholderText("留空保存到本地库根目录")
        self.message = QLabel("保存后立即写入块库；取消草稿不会删除块库文件。")
        self.message.setWordWrap(True)
        self.save_button = QPushButton("保存")
        close = QPushButton("关闭")
        form = QFormLayout()
        form.addRow("名称", self.name_field)
        form.addRow("说明", self.description_field)
        form.addRow("标签", self.tags_field)
        form.addRow("分类", self.category_field)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        self.preview_caption = QLabel("块定义预览：基点 (0, 0)，比例 1")
        self.preview = BlockLibraryPreviewWidget()
        self.preview.set_asset(preview_asset)
        self.preview.setVisible(preview_asset is not None)
        self.preview_caption.setVisible(preview_asset is not None)
        layout.addWidget(self.preview_caption)
        layout.addWidget(self.preview, 1)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addLayout(buttons)
        self.save_button.clicked.connect(self._save_clicked)
        close.clicked.connect(self.accept)

    def _save_clicked(self) -> None:
        tags = tuple(tag.strip() for tag in self.tags_field.text().split(",") if tag.strip())
        try:
            path = self._save(
                self.name_field.text().strip(),
                self.description_field.text(),
                tags,
                self.category_field.text().strip(),
            )
        except (OSError, ValueError, ValidationError) as exc:
            self.message.setText(str(exc))
            return
        self.message.setText(f"已保存到块库：{path}；取消草稿不会删除该文件。")
        self.save_button.setEnabled(False)
