# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Isolated, locally undoable edits of a shared drawing block definition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, cast, override
from uuid import uuid4

from PySide6.QtCore import QMimeData, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mycad.core.drawing_text import DrawingText, TextStyleTable
from mycad.core.exceptions import ValidationError
from mycad.core.sketch_layers import SketchLayerTable
from mycad.ui.drawing_text_tools import DrawingTextTools
from mycad.ui.sketch_editor import SketchCanvas

if TYPE_CHECKING:
    from mycad.app import AppServices
    from mycad.core.dimension_styles import DimensionStyleTable
    from mycad.core.drawing_blocks import BlockDefinition
    from mycad.core.drawing_raster import DrawingRaster
    from mycad.core.persistence import LoadedDocument
    from mycad.core.sketch import Point2D, Sketch, SketchEntity


class DrawingBlockEditorSession:
    """Keep edits outside the main document until one validated save."""

    def __init__(
        self,
        services: AppServices,
        loaded: LoadedDocument,
        definition_id: str,
        *,
        is_current_document: Callable[[], bool],
        can_write: Callable[[], bool] | None = None,
        source_has_draft: Callable[[], bool] | None = None,
    ) -> None:
        definitions = services.kernel.drawing_block_definitions
        definition = next(
            (item for item in definitions if item.definition_id == definition_id), None
        )
        if definition is None or loaded.document.document_type != "drawing2d":
            raise ValidationError("块定义不存在或当前文档不是独立二维文档。")
        self._services = services
        self._loaded = loaded
        self._is_current_document = is_current_document
        self._can_write = can_write
        self._source_has_draft = source_has_draft
        self._revision = loaded.document.revision
        self._source = definition
        self._source_styles = services.kernel.drawing_text_styles
        self._history = [(definition.entities, definition.texts, self._source_styles)]
        self._index = 0

    @property
    def definition(self) -> BlockDefinition:
        try:
            return replace(self._source, entities=self.entities, texts=self.texts)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    @property
    def entities(self) -> tuple[SketchEntity, ...]:
        return self._history[self._index][0]

    @property
    def texts(self) -> tuple[DrawingText, ...]:
        return self._history[self._index][1]

    @property
    def styles(self) -> TextStyleTable:
        return self._history[self._index][2]

    @property
    def dirty(self) -> bool:
        return (self.entities, self.texts, self.styles) != (
            self._source.entities,
            self._source.texts,
            self._source_styles,
        )

    def belongs_to(self, loaded: LoadedDocument) -> bool:
        """Identify the document whose definition this isolated editor owns."""
        return self._loaded is loaded

    def set_members(
        self,
        entities: tuple[SketchEntity, ...],
        texts: tuple[DrawingText, ...],
        styles: TextStyleTable | None = None,
    ) -> None:
        entities, texts = tuple(entities), tuple(texts)
        styles = styles or self.styles
        if entities or texts:
            try:
                replace(self._source, entities=entities, texts=texts)
                for text in texts:
                    styles.get(text.style_id)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            except KeyError as exc:
                raise ValidationError("块内文字引用的样式不存在。") from exc
        if (entities, texts, styles) == (self.entities, self.texts, self.styles):
            return
        del self._history[self._index + 1 :]
        self._history.append((entities, texts, styles))
        self._index += 1

    def undo(self) -> bool:
        if self._index == 0:
            return False
        self._index -= 1
        return True

    def redo(self) -> bool:
        if self._index + 1 >= len(self._history):
            return False
        self._index += 1
        return True

    def local_layers(self, layers: SketchLayerTable) -> SketchLayerTable:
        """Project all instance permissions onto each effective local member layer."""
        instance_layers = tuple(
            layers.get(item.layer_name)
            for item in self._services.kernel.drawing_block_instances
            if item.definition_id == self._source.definition_id
        )
        if not instance_layers:
            return layers
        any_locked = any(item.locked for item in instance_layers)
        all_visible = all(item.visible for item in instance_layers)
        any_frozen = any(item.frozen for item in instance_layers)
        return SketchLayerTable(
            tuple(
                replace(
                    layer,
                    locked=any_locked or (layer.name.casefold() != "0" and layer.locked),
                    visible=all_visible and (layer.name.casefold() == "0" or layer.visible),
                    frozen=any_frozen or (layer.name.casefold() != "0" and layer.frozen),
                )
                for layer in layers.layers
            )
        )

    def save(self) -> None:
        if self._can_write is not None and not self._can_write():
            raise ValidationError("几何工作线程忙碌，请稍后保存块定义。")
        if (
            not self._is_current_document()
            or self._loaded.document.revision != self._revision
            or self._source not in self._services.kernel.drawing_block_definitions
        ):
            raise ValidationError("块编辑会话已过期，源文档或定义发生变化。")
        if not self.dirty:
            return
        if self._source_has_draft is not None and self._source_has_draft():
            raise ValidationError("请先完成或取消主图纸中的草稿，再保存块定义。")
        definition = self.definition
        # A committed style is a document resource: local undo must not remove
        # it, while future unsaved styles stay confined to their redo states.
        committed_styles = self.styles
        rebased_history: list[
            tuple[tuple[SketchEntity, ...], tuple[DrawingText, ...], TextStyleTable]
        ] = []
        try:
            for entities, texts, styles in self._history:
                by_id = {item.style_id: item for item in styles.styles}
                if any(
                    item.style_id in by_id and by_id[item.style_id] != item
                    for item in committed_styles.styles
                ):
                    raise ValueError("块编辑历史包含冲突的文字样式。")
                missing = tuple(
                    item for item in committed_styles.styles if item.style_id not in by_id
                )
                rebased_history.append(
                    (entities, texts, TextStyleTable((*styles.styles, *missing), styles.current_id))
                )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        try:
            if self.styles != self._source_styles:
                self._loaded.bus.execute(
                    "drawing.objects.batch",
                    {
                        "operations": [
                            {
                                "id": "drawing.text_styles.set",
                                "version": 1,
                                "params": self.styles.to_mapping(),
                            },
                            {
                                "id": "drawing.block.update",
                                "version": 1,
                                "params": definition.to_mapping(),
                            },
                        ]
                    },
                    "local",
                    version=1,
                )
            else:
                self._loaded.bus.execute(
                    "drawing.block.update", definition.to_mapping(), "local", version=1
                )
        except Exception:
            if (
                self._is_current_document()
                and self._source in self._services.kernel.drawing_block_definitions
                and self._loaded.bus.execute_rolled_back_from(self._revision)
            ):
                self._revision = self._loaded.document.revision
            raise
        self._revision = self._loaded.document.revision
        self._source = definition
        self._source_styles = committed_styles
        self._history = rebased_history


class _BlockEditCanvas(SketchCanvas):
    """Route canvas-focused clipboard operations to the isolated tools."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.commit_local_geometry: Callable[[tuple[SketchEntity, ...]], bool] | None = None

    @override
    def supports_clipboard_context_menu(self) -> bool:
        return True

    @override
    def copy_to_clipboard(self) -> bool:
        tools = self.text_tools
        if tools is not None and tools.selected_ids and self.selected_entity_ids:
            from mycad.core.sketch import Sketch, WorkPlaneFrame
            from mycad.ui.drawing_text_tools import TEXT_CLIPBOARD_MIME, encode_text_clipboard

            try:
                if tools.pending or self.has_pending_geometry or self.has_active_edit_gesture:
                    raise ValueError("请先完成或取消当前操作，再复制块内容。")
                error = self.transform_selection_error("copy")
                if error:
                    raise ValueError(error)
                texts = tools.selected()
                entities = tuple(
                    item for item in self.entities if item.entity_id in self.selected_entity_ids
                )
                if len(texts) != len(tools.selected_ids) or len(entities) != len(
                    self.selected_entity_ids
                ):
                    raise ValueError("所选图元或文字已变化，请重新选择。")
                identities = {item.style_id for item in texts}
                styles = TextStyleTable(
                    tuple(item for item in tools.styles.styles if item.style_id in identities),
                    next(iter(identities)),
                )
                sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), entities, layers=self.layer_table)
                data = encode_text_clipboard(texts, styles, sketch, None, (), self.layer_table)
            except (KeyError, TypeError, ValueError, ValidationError) as exc:
                self.message = str(exc)
                self.changed.emit()
                return False
            mime = QMimeData()
            mime.setData(TEXT_CLIPBOARD_MIME, data)
            mime.setText("\n".join(item.text for item in texts))
            QApplication.clipboard().setMimeData(mime)
            self.message = "已复制块内几何与文字；Ctrl+V 粘贴。"
            self.changed.emit()
            return True
        original = self.select_committed_entities
        self.select_committed_entities = True
        try:
            return super().copy_to_clipboard()
        finally:
            self.select_committed_entities = original

    @override
    def begin_clipboard_paste(self) -> bool:
        from mycad.core.drawing_collection_clipboard import DRAWING_COLLECTION_CLIPBOARD_MIME
        from mycad.core.sketch import WorkPlaneFrame
        from mycad.ui.drawing_clipboard import (
            DRAWING_CLIPBOARD_MIME,
            DRAWING_MIXED_CLIPBOARD_MIME,
            DRAWING_RASTER_GROUP_MIME,
            decode_drawing_clipboard_full,
        )
        from mycad.ui.drawing_text_tools import TEXT_CLIPBOARD_MIME

        mime = cast("QMimeData | None", QApplication.clipboard().mimeData())
        if mime is None:
            self.message = "剪贴板中没有可粘贴的几何或文字。"
            self.changed.emit()
            return False
        try:
            if (
                mime.hasFormat(DRAWING_COLLECTION_CLIPBOARD_MIME)
                or mime.hasFormat(DRAWING_MIXED_CLIPBOARD_MIME)
                or mime.hasFormat(DRAWING_RASTER_GROUP_MIME)
            ):
                raise ValueError("块编辑不支持粘贴块、组或图片。")
            if mime.hasFormat(DRAWING_CLIPBOARD_MIME) and not mime.hasFormat(TEXT_CLIPBOARD_MIME):
                sketch, _styles, _text_styles = decode_drawing_clipboard_full(
                    bytes(mime.data(DRAWING_CLIPBOARD_MIME).data())
                )
                if sketch.constraints or sketch.support_face:
                    raise ValueError("块编辑仅支持无约束的几何，不能粘贴尺寸或附着草图。")
                normal = WorkPlaneFrame.xy().normal
                if sum(a * b for a, b in zip(sketch.frame.normal, normal, strict=True)) < 1 - 1e-9:
                    raise ValueError("粘贴几何必须与块编辑平面同向共面。")
                for entity in sketch.entities:
                    try:
                        layer = self.layer_table.get(entity.layer_name)
                    except KeyError as exc:
                        raise ValueError(
                            f"块编辑不能导入不存在的图层 {entity.layer_name}。"
                        ) from exc
                    if layer.locked or not layer.displayed:
                        raise ValueError(f"目标图层 {entity.layer_name} 隐藏或已锁定。")
            elif not mime.hasFormat(TEXT_CLIPBOARD_MIME):
                raise ValueError("块编辑仅支持粘贴几何与文字。")
        except (KeyError, ValueError, ValidationError) as exc:
            self.message = str(exc)
            self.changed.emit()
            return False
        original = self.select_committed_entities
        self.select_committed_entities = True
        try:
            return super().begin_clipboard_paste()
        finally:
            self.select_committed_entities = original

    @override
    def _place_clipboard(self, point: Point2D) -> bool:
        from mycad.core.drawing_blocks import assign_new_curve_point_ids
        from mycad.ui.drawing_clipboard import instantiate_drawing_clipboard

        sketch = self._clipboard_paste
        if sketch is None:
            return super()._place_clipboard(point)
        try:
            for entity in sketch.entities:
                layer = self.layer_table.get(entity.layer_name)
                if layer.locked or not layer.displayed:
                    raise ValueError(f"目标图层 {entity.layer_name} 隐藏或已锁定。")
            delta = (point[0] - self._clipboard_anchor[0], point[1] - self._clipboard_anchor[1])
            entities, constraints = instantiate_drawing_clipboard(sketch, delta)
            if constraints:
                raise ValueError("块编辑不支持粘贴尺寸或约束。")
            entities = tuple(assign_new_curve_point_ids(item) for item in entities)
            if self.commit_local_geometry is None:
                raise ValueError("块编辑无法提交几何粘贴。")
            if not self.commit_local_geometry(entities):
                return False
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            self.message = f"粘贴位置无效：{exc}"
            self.changed.emit()
            return False
        self._clear_clipboard_paste()
        self._clipboard_styles = None
        self._clipboard_text_styles = None
        self.message = f"已粘贴 {len(entities)} 个二维图元；可撤销。"
        self.changed.emit()
        self.point_accepted.emit(point)
        self.update()
        return True

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Paste) and self.begin_clipboard_paste():
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_to_clipboard()
            event.accept()
            return
        super().keyPressEvent(event)


class DrawingBlockEditorDialog(QDialog):
    """A canvas and text controller whose writes remain local until Save."""

    saved = Signal()

    def __init__(
        self,
        session: DrawingBlockEditorSession,
        layers: SketchLayerTable,
        styles: TextStyleTable,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.setWindowTitle(f"块编辑：{session.definition.name}")
        self.resize(900, 650)
        self._syncing = False
        self._initial_view_fitted = False
        self.canvas = _BlockEditCanvas(self)
        self.canvas.commit_local_geometry = self._paste_geometry
        self.canvas.set_layer_table(session.local_layers(layers), "0")
        self.canvas.set_auto_inference_enabled(False)
        self.canvas.set_copy_mode(1)
        self.canvas.entities = list(session.entities)
        self.text_tools = DrawingTextTools(self.canvas, self)
        self.text_tools.sync(session.texts, styles)
        self.text_tools.execute = self._edit_text
        self.text_tools.paste_commit = self._paste_text_and_geometry
        self.text_tools.ignore_unused_paste_dimension_styles = True
        self.canvas.mixed_transform_preview_provider = self._mixed_preview
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        layout.addLayout(toolbar)
        toolbar.addWidget(QLabel("图层"))
        self.layer_combo = QComboBox()
        self.layer_combo.addItems([layer.name for layer in layers.layers])
        self.layer_combo.setCurrentText(self.canvas.active_layer_name)
        self.layer_combo.currentTextChanged.connect(self._set_active_layer)
        toolbar.addWidget(self.layer_combo)
        self.tool_buttons: dict[str, QPushButton] = {}
        for tool in ("选择元素", "点", "直线", "多段线", "矩形", "圆", "圆弧", "椭圆", "样条曲线"):
            button = QPushButton(tool)
            button.clicked.connect(lambda _checked=False, value=tool: self.canvas.set_tool(value))
            toolbar.addWidget(button)
            self.tool_buttons[tool] = button
        for label, kind in (("单行文字", "text"), ("多行文字", "mtext")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, value=kind: self._begin_text(value))
            toolbar.addWidget(button)
        edit_row = QHBoxLayout()
        layout.addLayout(edit_row)
        for label, operation in (
            ("移动", "move"),
            ("复制", "copy"),
            ("旋转", "rotate"),
            ("缩放", "scale"),
            ("镜像", "mirror"),
            ("删除", "erase"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, value=operation: self._start_edit(value))
            self.tool_buttons[label] = button
            edit_row.addWidget(button)
        fit_button = QPushButton("适应窗口")
        fit_button.clicked.connect(self.canvas.fit_view)
        self.tool_buttons["适应窗口"] = fit_button
        edit_row.addWidget(fit_button)
        self.canvas.committed_move_requested.connect(partial(self._mixed_displacement, "move"))
        self.canvas.committed_mixed_copy_requested.connect(
            partial(self._mixed_displacement, "copy")
        )
        self.canvas.committed_rotation_requested.connect(partial(self._mixed_edit, "rotate"))
        self.canvas.committed_rotation_copy_requested.connect(
            partial(self._mixed_edit, "rotate_copy")
        )
        self.canvas.committed_scale_requested.connect(partial(self._mixed_edit, "scale"))
        self.canvas.committed_scale_copy_requested.connect(partial(self._mixed_edit, "scale_copy"))
        self.canvas.committed_mirror_requested.connect(partial(self._mixed_edit, "mirror"))
        self.canvas.committed_mirror_copy_requested.connect(
            partial(self._mixed_edit, "mirror_copy")
        )
        self.canvas.committed_delete_requested.connect(self._mixed_delete)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.text_tools.panel)
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText(
            "块编辑命令：MOVE、COPY、ROTATE、SCALE、MIRROR、ERASE、BSAVE、BCLOSE"
        )
        self.command_input.returnPressed.connect(self._run_command)
        layout.addWidget(self.command_input)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.status_label = QLabel("")
        row.addWidget(self.status_label, 1)
        self.undo_button = QPushButton("撤销")
        self.redo_button = QPushButton("重做")
        self.save_button = QPushButton("保存块")
        self.close_button = QPushButton("关闭块编辑")
        for button in (self.undo_button, self.redo_button, self.save_button, self.close_button):
            row.addWidget(button)
        self.undo_button.clicked.connect(self.undo_local)
        self.redo_button.clicked.connect(self.redo_local)
        self.save_button.clicked.connect(self.save_definition)
        self.close_button.clicked.connect(self.close)
        self.canvas.changed.connect(self._capture_canvas)
        self._undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        self._undo_shortcut.activated.connect(self.undo_local)
        self._redo_shortcut.activated.connect(self.redo_local)

    def _begin_text(self, kind: str) -> None:
        self.text_tools.begin("mtext" if kind == "mtext" else "text")
        self.status_label.setText(self.canvas.message)

    def _start_edit(self, operation: str) -> None:
        if self.text_tools.pending:
            self.status_label.setText("请先完成或取消当前文字操作。")
            return
        if operation == "erase":
            mixed = bool(self.text_tools.selected_ids and self.canvas.selected_entity_ids)
            self.canvas.delete_selected()
            if mixed:
                self.canvas.setFocus()
                return
        else:
            self.canvas.begin_transform(operation)
        self.status_label.setText(self.canvas.message)
        self.canvas.setFocus()

    def _mixed_preview(
        self, operation: str, base: Point2D, value: Point2D | float
    ) -> tuple[tuple[SketchEntity, ...], tuple[DrawingText, ...]]:
        """Project selected members without changing the isolated editing session."""
        from mycad.core.drawing_text import mirror_text, move_text, rotate_text, scale_text
        from mycad.core.sketch_edit import (
            mirror_entities,
            move_entities,
            rotate_entities,
            scale_entities,
        )

        identities = tuple(self.canvas.selected_entity_ids)
        entities = tuple(item for item in self.session.entities if item.entity_id in identities)
        texts = tuple(
            item for item in self.session.texts if item.text_id in self.text_tools.selected_ids
        )
        if operation in {"move", "copy"}:
            delta = cast("Point2D", value)
            return move_entities(entities, identities, delta), tuple(
                move_text(item, delta) for item in texts
            )
        if operation == "rotate":
            angle = cast("float", value)
            return rotate_entities(entities, identities, base, angle), tuple(
                rotate_text(item, angle, base) for item in texts
            )
        if operation == "scale":
            factor = cast("float", value)
            return scale_entities(entities, identities, base, factor), tuple(
                scale_text(item, factor, base, self.text_tools.styles) for item in texts
            )
        if operation == "mirror":
            end = cast("Point2D", value)
            return mirror_entities(entities, identities, base, end), tuple(
                mirror_text(item, base, end) for item in texts
            )
        raise ValueError("块编辑不支持此预览。")

    def _mixed_displacement(
        self, operation: str, identities: tuple[str, ...], delta: Point2D
    ) -> None:
        self._mixed_edit(operation, identities, (0, 0), delta)

    def _mixed_delete(self, identities: tuple[str, ...]) -> None:
        self._mixed_edit("erase", identities, (0, 0), (0, 0))

    def _mixed_edit(
        self,
        operation: str,
        identities: tuple[str, ...],
        base: Point2D,
        value: Point2D | float,
    ) -> None:
        """Apply a geometry-and-text selection as one isolated history step."""
        from mycad.core.drawing_blocks import assign_new_curve_point_ids
        from mycad.core.drawing_text import mirror_text, move_text, rotate_text, scale_text
        from mycad.core.sketch_edit import (
            copy_entities,
            mirror_entities,
            move_entities,
            rotate_entities,
            scale_entities,
        )

        try:
            action = operation.removesuffix("_copy")
            copy_source = operation == "copy" or operation.endswith("_copy")
            error = self.canvas.transform_selection_error(
                "delete_mixed" if action == "erase" else action
            )
            if error:
                raise ValueError(error)
            selected_text = frozenset(self.text_tools.selected_ids)
            geometry = tuple(self.canvas.entities)
            texts = self.session.texts
            if (
                not identities
                or not selected_text
                or any(
                    identity not in {item.entity_id for item in geometry} for identity in identities
                )
                or not selected_text.issubset(item.text_id for item in texts)
            ):
                raise ValueError("所选图元或文字已变化，请重新选择。")
            if action == "erase":
                geometry = tuple(item for item in geometry if item.entity_id not in identities)
                texts = tuple(item for item in texts if item.text_id not in selected_text)
            else:
                text_ids = selected_text
                if copy_source:
                    original_count = len(geometry)
                    geometry = copy_entities(geometry, identities, (0, 0))
                    geometry = (
                        *geometry[:original_count],
                        *(assign_new_curve_point_ids(item) for item in geometry[original_count:]),
                    )
                    identities = tuple(item.entity_id for item in geometry[original_count:])
                    copied_text = tuple(
                        replace(item, text_id=uuid4().hex)
                        for item in texts
                        if item.text_id in selected_text
                    )
                    texts = (*texts, *copied_text)
                    text_ids = frozenset(item.text_id for item in copied_text)
                if action in {"move", "copy"}:
                    delta = cast("Point2D", value)
                    geometry = move_entities(geometry, identities, delta)
                elif action == "rotate":
                    angle = cast("float", value)
                    geometry = rotate_entities(geometry, identities, base, angle)
                elif action == "scale":
                    factor = cast("float", value)
                    geometry = scale_entities(geometry, identities, base, factor)
                elif action == "mirror":
                    end = cast("Point2D", value)
                    geometry = mirror_entities(geometry, identities, base, end)
                else:
                    raise ValueError("块编辑不支持此操作。")
                if copy_source:
                    original_count = len(self.canvas.entities)
                    geometry = (
                        *geometry[:original_count],
                        *(assign_new_curve_point_ids(item) for item in geometry[original_count:]),
                    )

                def transform(item: DrawingText) -> DrawingText:
                    if action in {"move", "copy"}:
                        return move_text(item, cast("Point2D", value))
                    if action == "rotate":
                        return rotate_text(item, cast("float", value), base)
                    if action == "scale":
                        return scale_text(item, cast("float", value), base, self.text_tools.styles)
                    return mirror_text(item, base, cast("Point2D", value))

                texts = tuple(
                    transform(item) if item.text_id in text_ids else item for item in texts
                )
            self.session.set_members(geometry, texts)
            self._restore_local()
            self.status_label.setText("块内容已修改；可在本地撤销或保存。")
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            self.status_label.setText(str(exc))

    def _set_active_layer(self, name: str) -> None:
        previous = self.canvas.active_layer_name
        layer = self.canvas.layer_table.get(name)
        if (
            layer.locked
            or not layer.displayed
            or self.canvas.has_pending_geometry
            or self.canvas.has_active_edit_gesture
            or self.text_tools.pending
        ):
            self.layer_combo.blockSignals(True)
            self.layer_combo.setCurrentText(previous)
            self.layer_combo.blockSignals(False)
            self.status_label.setText("图层不可编辑，或请先完成当前操作。")
            return
        self.canvas.set_layer_table(self.canvas.layer_table, name)
        self.text_tools.sync(self.session.texts, self.session.styles)

    def _run_command(self) -> None:
        command = self.command_input.text().strip().upper()
        self.command_input.clear()
        operations = {
            "MOVE": "move",
            "COPY": "copy",
            "ROTATE": "rotate",
            "SCALE": "scale",
            "MIRROR": "mirror",
            "ERASE": "erase",
        }
        if command in operations:
            self._start_edit(operations[command])
        elif command == "BSAVE":
            self.save_definition()
        elif command == "BCLOSE":
            self.close()
        elif command in {"UNDO", "U"}:
            self.undo_local()
        elif command == "REDO":
            self.redo_local()
        else:
            self.status_label.setText("块编辑支持几何与文字变换、BSAVE、BCLOSE、UNDO 和 REDO。")

    def _capture_canvas(self) -> None:
        if self._syncing or self.canvas.draft_handle_drag_active:
            return
        try:
            self.session.set_members(tuple(self.canvas.entities), self.session.texts)
        except ValidationError as exc:
            self._restore_local()
            self.status_label.setText(str(exc))

    def _validate_local_styles(self, styles: TextStyleTable) -> None:
        if styles.current_id != self.session.styles.current_id or any(
            styles.get(item.style_id) != item for item in self.session.styles.styles
        ):
            raise ValueError("粘贴文字不能更改现有文字样式。")

    def _paste_geometry(self, entities: tuple[SketchEntity, ...]) -> bool:
        try:
            self.session.set_members((*self.session.entities, *entities), self.session.texts)
        except (TypeError, ValueError, ValidationError) as exc:
            self.status_label.setText(str(exc))
            return False
        self._restore_local()
        self.canvas.selected_entity_ids = {item.entity_id for item in entities}
        return True

    def _paste_text_and_geometry(
        self,
        sketch: Sketch,
        texts: tuple[DrawingText, ...],
        styles: TextStyleTable,
        images: tuple[DrawingRaster, ...],
        dimension_styles: DimensionStyleTable | None,
    ) -> bool:
        from mycad.core.cross_sketch_tangency import project_coplanar_entity
        from mycad.core.drawing_blocks import assign_new_curve_point_ids
        from mycad.core.sketch import WorkPlaneFrame

        try:
            if images or sketch.constraints or sketch.support_face or dimension_styles is not None:
                raise ValueError("块编辑仅支持粘贴几何与文字，不支持图片、尺寸或约束。")
            drawing_frame = WorkPlaneFrame.xy()
            if sum(
                a * b for a, b in zip(sketch.frame.normal, drawing_frame.normal, strict=True)
            ) < (1 - 1e-9):
                raise ValueError("粘贴几何必须与块编辑平面同向共面。")
            self._validate_local_styles(styles)
            for item in (*sketch.entities, *texts):
                try:
                    layer = self.canvas.layer_table.get(item.layer_name)
                except KeyError as exc:
                    raise ValueError(f"块编辑不能导入不存在的图层 {item.layer_name}。") from exc
                if layer.locked or not layer.displayed:
                    raise ValueError(f"目标图层 {item.layer_name} 隐藏或已锁定。")
            entities = tuple(
                assign_new_curve_point_ids(
                    project_coplanar_entity(item, sketch.frame, drawing_frame)
                )
                for item in sketch.entities
            )
            self.session.set_members(
                (*self.session.entities, *entities), (*self.session.texts, *texts), styles
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            self.status_label.setText(str(exc))
            return False
        self._restore_local()
        return True

    def _edit_text(self, command: str, params: dict[str, object]) -> bool:
        texts = list(self.session.texts)
        try:
            styles = self.session.styles
            if command == "drawing.text.batch" and "styles" in params:
                styles = TextStyleTable.from_mapping(params["styles"])
                self._validate_local_styles(styles)
            if command in {"drawing.text.add", "drawing.text.update"}:
                item = DrawingText.from_mapping(params)
                if command.endswith(".add"):
                    texts.append(item)
                else:
                    if not any(old.text_id == item.text_id for old in texts):
                        raise ValueError("文字不存在。")
                    texts = [item if old.text_id == item.text_id else old for old in texts]
            elif command == "drawing.text.batch":
                additions = params.get("add", [])
                updates = params.get("update", [])
                removals = params.get("remove", [])
                if (
                    not isinstance(additions, list)
                    or not isinstance(updates, list)
                    or not isinstance(removals, list)
                ):
                    raise ValueError("文字操作格式无效。")
                raw_additions = cast("list[object]", additions)
                raw_updates = cast("list[object]", updates)
                raw_removals = cast("list[object]", removals)
                if not all(isinstance(item, str) for item in raw_removals):
                    raise ValueError("文字操作格式无效。")
                removal_ids = set(cast("list[str]", raw_removals))
                updated = [DrawingText.from_mapping(item) for item in raw_updates]
                by_id = {item.text_id: item for item in updated}
                existing = {item.text_id for item in texts}
                if not set(by_id).issubset(existing) or not removal_ids.issubset(existing):
                    raise ValueError("文字不存在。")
                texts = [
                    by_id.get(item.text_id, item)
                    for item in texts
                    if item.text_id not in removal_ids
                ]
                texts.extend(DrawingText.from_mapping(item) for item in raw_additions)
            else:
                raise ValueError("块编辑仅支持局部文字操作。")
            self.session.set_members(tuple(self.canvas.entities), tuple(texts), styles)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            self.status_label.setText(str(exc))
            return False
        self.text_tools.sync(self.session.texts, self.session.styles)
        self.canvas.update()
        return True

    def _restore_local(self) -> None:
        self._syncing = True
        try:
            self.canvas.restore_isolated_entities(self.session.entities)
            self.text_tools.sync(self.session.texts, self.session.styles)
            self.canvas.update()
        finally:
            self._syncing = False

    def undo_local(self) -> bool:
        if (
            self.canvas.has_pending_geometry
            or self.canvas.has_active_edit_gesture
            or self.text_tools.pending
        ):
            self.status_label.setText("请先完成或取消当前操作。")
            return False
        if not self.session.undo():
            return False
        self._restore_local()
        return True

    def redo_local(self) -> bool:
        if (
            self.canvas.has_pending_geometry
            or self.canvas.has_active_edit_gesture
            or self.text_tools.pending
        ):
            self.status_label.setText("请先完成或取消当前操作。")
            return False
        if not self.session.redo():
            return False
        self._restore_local()
        return True

    def save_definition(self) -> bool:
        if (
            self.canvas.has_pending_geometry
            or self.canvas.has_active_edit_gesture
            or self.text_tools.pending
        ):
            self.status_label.setText("请先完成或取消当前操作。")
            return False
        try:
            self.session.save()
        except Exception as exc:
            self.status_label.setText(str(exc))
            return False
        self.saved.emit()
        self.status_label.setText("块定义已保存。")
        return True

    @override
    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._initial_view_fitted:
            self._initial_view_fitted = True
            self.canvas.fit_view(only_if_all_outside=True)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if (
            self.session.dirty
            or self.canvas.has_pending_geometry
            or self.canvas.has_active_edit_gesture
            or self.text_tools.pending
        ):
            choice = QMessageBox.question(
                self,
                "关闭块编辑",
                "是否保存对块定义的修改？",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if choice == QMessageBox.StandardButton.Cancel or (
                choice == QMessageBox.StandardButton.Save and not self.save_definition()
            ):
                event.ignore()
                return
        event.accept()

    @override
    def reject(self) -> None:
        """Route Escape through the same unsaved-change prompt as window close."""
        self.close()
