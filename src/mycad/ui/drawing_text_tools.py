# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Model-space text editing, selection and font styles on the existing canvas."""

from __future__ import annotations

import json
import math
import shlex
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, Literal, cast, override
from uuid import uuid4

from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mycad.core.cross_sketch_tangency import project_coplanar_rotation, project_coplanar_vector
from mycad.core.dimension_styles import DimensionStyleTable
from mycad.core.drawing_raster import DrawingRaster
from mycad.core.drawing_text import DrawingText, TextStyleTable
from mycad.core.sketch import Sketch, WorkPlaneFrame
from mycad.core.sketch_layers import SketchLayerTable
from mycad.core.text_interchange import reconcile_text_styles
from mycad.ui.drawing2d_command_bar import parse_coordinate
from mycad.ui.drawing_clipboard import (
    DRAWING_CLIPBOARD_MIME,
    DRAWING_MIXED_CLIPBOARD_MIME,
    decode_drawing_clipboard_full,
    decode_mixed_clipboard_full,
    instantiate_drawing_clipboard,
    reconcile_clipboard_fonts,
    reconcile_clipboard_styles,
)
from mycad.ui.font_manager import FontManager
from mycad.ui.text_layout import TextLayout, layout_text
from mycad.ui.text_style_dialog import TextStyleDialog

if TYPE_CHECKING:
    from mycad.ui.sketch_editor import SketchCanvas

TEXT_CLIPBOARD_MIME = "application/x-mycad-text+json"
_MAX_CLIPBOARD_BYTES = 4_000_000


def encode_text_clipboard(
    texts: tuple[DrawingText, ...],
    styles: TextStyleTable,
    sketch: Sketch | None,
    dimension_styles: DimensionStyleTable | None,
    images: tuple[DrawingRaster, ...],
    layers: SketchLayerTable,
) -> bytes:
    """Prepare a complete text clipboard payload before publishing it."""
    data = json.dumps(
        {
            "format": "mycad-text",
            "version": 1,
            "texts": [item.to_mapping() for item in texts],
            "styles": styles.to_mapping(),
            "sketch": sketch.to_state_mapping() if sketch else None,
            "dimension_styles": dimension_styles.to_mapping() if dimension_styles else None,
            "images": [image.to_mapping(version=2) for image in images],
            "layers": layers.to_mapping(),
        },
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    if len(data) > _MAX_CLIPBOARD_BYTES:
        raise ValueError("文字剪贴板过大。")
    return data


class TextEditor(QPlainTextEdit):
    """Keep Chinese composition and local text undo inside a native editor."""

    def __init__(self, commit: Callable[[], None], cancel: Callable[[], bool]) -> None:
        super().__init__()
        self._commit, self._cancel = commit, cancel

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            event.accept()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._commit()
            event.accept()
        else:
            super().keyPressEvent(event)


class DrawingTextTools:
    """Own transient edits; durable writes are delegated to the document's Bus bridge."""

    def __init__(self, canvas: SketchCanvas, parent: QWidget | None = None) -> None:
        self.canvas = canvas
        self.parent = parent or canvas
        self.manager = FontManager()
        self.texts: tuple[DrawingText, ...] = ()
        self.styles = TextStyleTable()
        self.selected_ids: set[str] = set()
        self.dirty_fields: set[str] = set()
        self._refreshing = False
        self._selection_snapshot: tuple[DrawingText, ...] = ()
        self.execute: Callable[[str, dict[str, object]], bool] | None = None
        self.paste_commit: (
            Callable[
                [
                    Sketch,
                    tuple[DrawingText, ...],
                    TextStyleTable,
                    tuple[DrawingRaster, ...],
                    DimensionStyleTable | None,
                ],
                bool,
            ]
            | None
        ) = None
        self.ignore_unused_paste_dimension_styles = False
        self.commit_mixed: Callable[[dict[str, object], dict[str, object]], bool] | None = None
        self._cache: dict[DrawingText, TextLayout] = {}
        self._mode: Literal["text", "mtext"] | None = None
        self._editing: DrawingText | None = None
        self._position = (0.0, 0.0)
        self.selection_original: set[str] = set()
        self._paste: tuple[DrawingText, ...] = ()
        self._paste_styles: TextStyleTable | None = None
        self._paste_sketch: Sketch | None = None
        self._paste_rasters: tuple[DrawingRaster, ...] = ()
        self._paste_dimension_styles: DimensionStyleTable | None = None
        self._paste_layers = SketchLayerTable()
        self._preview: DrawingText | None = None
        self.panel = QWidget()
        self.panel.setObjectName("drawingTextProperties")
        form = QFormLayout(self.panel)
        self.selection_label = QLabel("未选择文字")
        self.style_combo = QComboBox()
        self.layer_combo = QComboBox()
        self.height = self._number(0, 10000, 0, " mm")
        self.height.setSpecialValueText("随样式")
        self.width_factor = self._number(0, 100, 0)
        self.width_factor.setSpecialValueText("随样式")
        self.rotation = self._number(-360000, 360000, 0, "°")
        self.x = self._number(-1e9, 1e9, 0, " mm")
        self.y = self._number(-1e9, 1e9, 0, " mm")
        self.box_width = self._number(0, 100000, 50, " mm")
        self.line_spacing = self._number(0.25, 4, 1)
        self.align = QComboBox()
        for label, value in (
            ("左基线", "left"),
            ("中基线", "center"),
            ("右基线", "right"),
            ("左上", "top_left"),
            ("中上", "top_center"),
            ("右上", "top_right"),
            ("左中", "middle_left"),
            ("居中", "middle_center"),
            ("右中", "middle_right"),
            ("左下", "bottom_left"),
            ("中下", "bottom_center"),
            ("右下", "bottom_right"),
        ):
            self.align.addItem(label, value)
        self.content = QPlainTextEdit()
        self.content.setMaximumHeight(90)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        form.addRow(self.selection_label)
        for label, field in (
            ("内容", self.content),
            ("文字样式", self.style_combo),
            ("图层", self.layer_combo),
            ("X", self.x),
            ("Y", self.y),
            ("字高", self.height),
            ("宽度因子", self.width_factor),
            ("旋转", self.rotation),
            ("对齐", self.align),
            ("多行框宽", self.box_width),
            ("行距", self.line_spacing),
        ):
            form.addRow(label, field)
        for key, field in (
            ("height_mm", self.height),
            ("width_factor", self.width_factor),
            ("rotation_deg", self.rotation),
            ("x", self.x),
            ("y", self.y),
            ("box_width_mm", self.box_width),
            ("line_spacing", self.line_spacing),
        ):
            field.valueChanged.connect(partial(self._mark_dirty, key))
        for key, combo in (
            ("style_id", self.style_combo),
            ("layer_name", self.layer_combo),
            ("align", self.align),
        ):
            combo.currentIndexChanged.connect(partial(self._mark_dirty, key))
        self.content.textChanged.connect(lambda: self._mark_dirty("text"))
        self.apply_button = QPushButton("应用到选中文字")
        self.edit_button = QPushButton("画布内编辑")
        self.style_button = QPushButton("文字样式与字体…")
        form.addRow(self.apply_button)
        form.addRow(self.edit_button)
        form.addRow(self.style_button)
        form.addRow(self.warning)
        self.apply_button.clicked.connect(self.apply_properties)
        self.edit_button.clicked.connect(self.edit_selected)
        self.style_button.clicked.connect(self.open_styles)
        self.overlay = QFrame(canvas)
        self.overlay.setObjectName("drawingTextEditor")
        self.overlay.setAutoFillBackground(True)
        self.overlay.setFrameShape(QFrame.Shape.StyledPanel)
        outer = QVBoxLayout(self.overlay)
        outer.setContentsMargins(5, 5, 5, 5)
        self.editor = TextEditor(self.commit, self.cancel)
        self.editor.setPlaceholderText("输入文字；Ctrl+Enter 完成，Esc 取消")
        outer.addWidget(self.editor)
        row = QHBoxLayout()
        done, cancel = QPushButton("完成 Ctrl+Enter"), QPushButton("取消 Esc")
        row.addWidget(done)
        row.addWidget(cancel)
        outer.addLayout(row)
        done.clicked.connect(self.commit)
        cancel.clicked.connect(self.cancel)
        self.overlay.resize(340, 165)
        self.overlay.hide()
        self.editor.textChanged.connect(self._preview_changed)
        canvas.text_tools = self
        canvas.changed.connect(self.refresh_selection)
        self.sync((), self.styles)

    @staticmethod
    def _number(low: float, high: float, value: float, suffix: str = "") -> QDoubleSpinBox:
        field = QDoubleSpinBox()
        field.setRange(low, high)
        field.setDecimals(3)
        field.setValue(value)
        field.setSuffix(suffix)
        return field

    @property
    def pending(self) -> bool:
        return self._mode is not None or self.overlay.isVisible() or bool(self._paste)

    def sync(self, texts: tuple[DrawingText, ...], styles: TextStyleTable) -> None:
        if texts != self.texts or styles != self.styles:
            if (
                self.overlay.isVisible()
                and self._editing is not None
                and self._editing not in texts
            ):
                self.cancel()
            self.texts, self.styles = texts, styles
            self._cache.clear()
            self._selection_snapshot = ()
        self.selected_ids.intersection_update(item.text_id for item in texts)
        current = str(self.style_combo.currentData() or styles.current_id)
        if not self.selected_ids:
            current = styles.current_id
        layer_name = self.layer_combo.currentText() or self.canvas.active_layer_name
        self.layer_combo.clear()
        self.layer_combo.addItems([layer.name for layer in self.canvas.layer_table.layers])
        self.layer_combo.setCurrentText(layer_name)
        self.style_combo.clear()
        for style in styles.styles:
            self.style_combo.addItem(style.name, style.style_id)
        self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(current)))
        self.refresh_selection()
        self.canvas.update()

    def _layout(self, item: DrawingText) -> TextLayout:
        if item not in self._cache:
            self._cache[item] = layout_text(item, self.styles.get(item.style_id), self.manager)
        return self._cache[item]

    @staticmethod
    def _project_text(
        item: DrawingText, source: WorkPlaneFrame, target: WorkPlaneFrame
    ) -> DrawingText:
        direction = project_coplanar_vector((1.0, 0.0), source, target)
        return replace(
            item,
            position_mm=target.world_to_local(source.local_to_world(item.position_mm)),
            rotation_deg=math.degrees(math.atan2(direction[1], direction[0]))
            + project_coplanar_rotation(item.rotation_deg, source, target),
        )

    def display_text(self, item: DrawingText) -> DrawingText | None:
        """Project a persistent drawing text into the current canvas plane."""
        try:
            return self._project_text(item, WorkPlaneFrame.xy(), self.canvas.drawing_view_frame)
        except ValueError:
            return None

    def _screen_transform(self, item: DrawingText) -> QTransform:
        precise = self.canvas.local_to_screen_precise(item.position_mm)
        point = (
            QPointF(self.canvas.local_to_screen(item.position_mm))
            if abs(precise.x()) < 2e9 and abs(precise.y()) < 2e9
            else precise
        )
        transform = QTransform()
        transform.translate(point.x(), point.y())
        transform.rotate(-item.rotation_deg)
        transform.scale(self.canvas.view_scale, self.canvas.view_scale)
        return transform

    def screen_bounds(self, item: DrawingText) -> QRectF:
        return self._screen_transform(item).mapRect(self._layout(item).bounds)

    def model_corners(self, item: DrawingText) -> tuple[tuple[float, float], ...]:
        bounds = self._layout(item).bounds
        angle = math.radians(item.rotation_deg)
        c, sn = math.cos(angle), math.sin(angle)
        return tuple(
            (
                item.position_mm[0] + c * p.x() + sn * p.y(),
                item.position_mm[1] + sn * p.x() - c * p.y(),
            )
            for p in (
                bounds.topLeft(),
                bounds.topRight(),
                bounds.bottomRight(),
                bounds.bottomLeft(),
            )
        )

    def draw(self, painter: QPainter, effective_ids: frozenset[str] = frozenset()) -> None:
        for source in (*self.texts, *((self._preview,) if self._preview else ())):
            if self._editing is not None and source == self._editing and self.overlay.isVisible():
                continue
            item = self.display_text(source)
            if item is None:
                continue
            layer = self.canvas.layer_table.get(item.layer_name)
            if not layer.displayed:
                continue
            painter.save()
            painter.setWorldTransform(self._screen_transform(item))
            painter.setPen(self.canvas.text_color(layer))
            self._layout(item).draw(painter)
            if item.text_id in self.selected_ids or item.text_id in effective_ids:
                pen = QPen(QColor("#008cba"), 1, Qt.PenStyle.DashLine)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.drawRect(self._layout(item).bounds)
            painter.restore()

    def draw_clipboard_preview(
        self,
        painter: QPainter,
        item: DrawingText,
        styles: TextStyleTable,
        source_layers: SketchLayerTable,
    ) -> bool:
        """Draw a clipboard text using its source style without changing document state."""
        try:
            layer = self.canvas.layer_table.get(item.layer_name)
        except KeyError:
            layer = source_layers.get(item.layer_name)
        if not layer.displayed:
            return False
        layout = layout_text(item, styles.get(item.style_id), self.manager)
        transform = self._screen_transform(item)
        viewport = QRectF(self.canvas.rect()).adjusted(-8, -8, 8, 8)
        if not transform.mapRect(layout.bounds).intersects(viewport):
            return False
        painter.save()
        painter.setWorldTransform(transform)
        painter.setPen(self.canvas.text_color(layer))
        layout.draw(painter)
        painter.restore()
        return True

    def hit(self, point: tuple[float, float]) -> DrawingText | None:
        for source in reversed(self.texts):
            item = self.display_text(source)
            if item is None:
                continue
            layer = self.canvas.layer_table.get(item.layer_name)
            if not layer.displayed or layer.locked:
                continue
            c, sn = (
                math.cos(math.radians(item.rotation_deg)),
                math.sin(math.radians(item.rotation_deg)),
            )
            dx, dy = point[0] - item.position_mm[0], point[1] - item.position_mm[1]
            local = QPointF(c * dx + sn * dy, sn * dx - c * dy)
            if self._layout(item).bounds.adjusted(-0.4, -0.4, 0.4, 0.4).contains(local):
                return source
        return None

    def select_box(self, first: QPointF, second: QPointF, modifiers: Qt.KeyboardModifier) -> None:
        rect = QRectF(first, second).normalized()
        crossing = second.x() < first.x()
        selected: set[str] = set()
        for source in self.texts:
            item = self.display_text(source)
            layer = self.canvas.layer_table.get(source.layer_name)
            if item is None or not layer.displayed or layer.locked:
                continue
            bounds = self.screen_bounds(item)
            if rect.contains(bounds) or (crossing and rect.intersects(bounds)):
                selected.add(source.text_id)
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            self.selected_ids = self.selection_original - selected
        elif modifiers & Qt.KeyboardModifier.ControlModifier or self.canvas.transform_selecting:
            self.selected_ids = self.selection_original | selected
        else:
            self.selected_ids = selected

    def mouse_press(self, event: QMouseEvent) -> bool:
        if event.button() == Qt.MouseButton.RightButton and self.pending:
            self.cancel()
            return True
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        if self.overlay.isVisible():
            self._message("请先完成或取消当前文字操作。")
            return True
        point = self.canvas.screen_to_local(event.position())
        if self._paste:
            return self.place_paste(point)
        if self._mode is not None and not self.overlay.isVisible():
            self.place(point)
            return True
        if (
            self.canvas.tool != "选择元素"
            or self.canvas.active_transform is not None
            and not self.canvas.transform_selecting
        ):
            return False
        item = self.hit(point)
        if item is None:
            return False
        additive = bool(
            event.modifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        )
        if not additive and not self.canvas.transform_selecting:
            self.canvas.selected_entity_ids.clear()
            self.canvas.selected_constraint_ids.clear()
            self.canvas.selected_raster_ids.clear()
            self.canvas.selected_block_instance_ids.clear()
            self.selected_ids.clear()
        if item.text_id in self.selected_ids and additive:
            self.selected_ids.remove(item.text_id)
        else:
            self.selected_ids.add(item.text_id)
        self.canvas.message = f"已选择 {len(self.selected_ids)} 个文字对象。"
        self.canvas.changed.emit()
        self.canvas.update()
        return True

    def double_click(self, event: QMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton or self.canvas.active_transform is not None:
            return False
        if self.pending:
            self._message("请先完成或取消当前文字操作。")
            return True
        item = self.hit(self.canvas.screen_to_local(event.position()))
        if item is None:
            return False
        self.selected_ids = {item.text_id}
        self.edit_selected()
        return True

    def begin(self, kind: Literal["text", "mtext"]) -> bool:
        if self.pending:
            self._message("请先完成或取消当前文字操作。")
            return False
        try:
            project_coplanar_vector((0, 0), self.canvas.drawing_view_frame, WorkPlaneFrame.xy())
        except ValueError:
            self._message("文字不在当前工作平面内，请先切换至图纸平面。")
            return False
        if (
            self.canvas.has_pending_geometry
            or self.canvas.has_active_edit_gesture
            or self.canvas.active_transform is not None
        ):
            self._message("请先完成或取消当前操作，再创建文字。")
            return False
        self.cancel()
        if not self.canvas.set_tool("选择元素"):
            return False
        self.selected_ids.clear()
        self.canvas.selected_entity_ids.clear()
        self.canvas.selected_constraint_ids.clear()
        self.canvas.selected_raster_ids.clear()
        self.canvas.selected_block_instance_ids.clear()
        self._mode = kind
        self.layer_combo.setCurrentText(self.canvas.active_layer_name)
        self._message(
            "TEXT：指定插入点。"
            if kind == "text"
            else "MTEXT：指定插入点；框宽可在文字特性中设置。"
        )
        self.canvas.setFocus()
        return True

    def place(self, point: tuple[float, float]) -> None:
        try:
            project_coplanar_vector((0, 0), self.canvas.drawing_view_frame, WorkPlaneFrame.xy())
        except ValueError:
            self._message("文字不在当前工作平面内，请先切换至图纸平面。")
            return
        self._position = point
        self._editing = None
        drawing_point = WorkPlaneFrame.xy().world_to_local(
            self.canvas.drawing_view_frame.local_to_world(point)
        )
        self.x.setValue(drawing_point[0])
        self.y.setValue(drawing_point[1])
        self.editor.clear()
        self._open_editor()

    def _open_editor(self) -> None:
        point = self.canvas.local_to_screen(self._position)
        self.overlay.move(
            max(0, min(point.x(), self.canvas.width() - self.overlay.width())),
            max(0, min(point.y(), self.canvas.height() - self.overlay.height())),
        )
        self.overlay.show()
        self.overlay.raise_()
        self.editor.setFocus()
        style = self.styles.get(str(self.style_combo.currentData()))
        font = self.manager.resolve(style)
        font.setPointSize(13)
        self.editor.setFont(font)
        self._preview_changed()

    def _record(self, text: str) -> DrawingText:
        style_id = str(self.style_combo.currentData() or self.styles.current_id)
        return DrawingText(
            self._editing.text_id if self._editing else uuid4().hex,
            text,
            (self.x.value(), self.y.value()),
            kind=self._editing.kind if self._editing else self._mode or "text",
            style_id=style_id,
            height_mm=self.height.value() or None,
            width_factor=self.width_factor.value() or None,
            rotation_deg=self.rotation.value(),
            align=str(self.align.currentData()),
            box_width_mm=self.box_width.value(),
            line_spacing=self.line_spacing.value(),
            layer_name=self.layer_combo.currentText() or self.canvas.active_layer_name,
        )

    def _preview_changed(self) -> None:
        if self._preview is not None:
            self._cache.pop(self._preview, None)
        self._preview = None
        if self.overlay.isVisible() and self.editor.toPlainText().strip():
            try:
                self._preview = self._record(self.editor.toPlainText())
                missing = self._layout(self._preview).missing_glyphs
                self.warning.setText(f"当前字体缺少字符：{missing}" if missing else "")
            except ValueError as exc:
                self.warning.setText(str(exc))
        self.canvas.update()

    def commit(self) -> None:
        try:
            item = self._record(self.editor.toPlainText())
            if not self._write(
                "drawing.text.update" if self._editing else "drawing.text.add", item.to_mapping()
            ):
                return
        except (ValueError, KeyError) as exc:
            self.warning.setText(str(exc))
            return
        self.cancel()
        self.selected_ids = {item.text_id}
        self._message("文字已保存；可撤销、重做。")

    def cancel(self) -> bool:
        pending = self.pending
        self._mode, self._editing, self._preview = None, None, None
        self._paste, self._paste_styles = (), None
        self._paste_sketch, self._paste_rasters, self._paste_dimension_styles = None, (), None
        self.overlay.hide()
        self.canvas.update()
        return pending

    def _write(self, command: str, params: dict[str, object]) -> bool:
        if self.execute is None:
            self._message("当前文字工具未连接到文档。")
            return False
        try:
            return self.execute(command, params)
        except ValueError as exc:
            self._message(str(exc))
            return False

    def _message(self, message: str) -> None:
        self.canvas.message = message
        self.canvas.changed.emit()
        self.canvas.update()

    def selected(self) -> tuple[DrawingText, ...]:
        return tuple(item for item in self.texts if item.text_id in self.selected_ids)

    def selection_error(self) -> str:
        items = self.selected()
        if len(items) != len(self.selected_ids):
            return "文字选择已失效，请重新选择。"
        if any(
            not self.canvas.layer_table.get(item.layer_name).displayed
            or self.canvas.layer_table.get(item.layer_name).locked
            for item in items
        ):
            return "所选文字位于隐藏或锁定图层。"
        return ""

    def _mark_dirty(self, field: str, _value: object = None) -> None:
        if not self._refreshing:
            self.dirty_fields.add(field)

    def refresh_selection(self) -> None:
        selected = self.selected()
        self.selection_label.setText(f"文字对象：{len(selected)} 个" if selected else "未选择文字")
        if not selected or self.overlay.isVisible() or selected == self._selection_snapshot:
            return
        self._selection_snapshot = selected
        self._refreshing = True
        item = selected[0]
        self.content.setPlainText(item.text)
        self.x.setValue(item.position_mm[0])
        self.y.setValue(item.position_mm[1])
        self.height.setValue(item.height_mm or 0)
        self.width_factor.setValue(item.width_factor or 0)
        self.rotation.setValue(item.rotation_deg)
        self.box_width.setValue(item.box_width_mm)
        self.line_spacing.setValue(item.line_spacing)
        self.align.setCurrentIndex(max(0, self.align.findData(item.align)))
        self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(item.style_id)))
        self.layer_combo.setCurrentText(item.layer_name)
        self._refreshing = False
        self.dirty_fields.clear()
        if len(selected) > 1:
            self.warning.setText("多选文字：仅应用本次编辑的字段，其他属性分别保留。")
            return
        style = self.styles.get(item.style_id)
        missing = self._layout(item).missing_glyphs
        replacement = self.manager.substitution(style)
        message = (
            f"字体 {style.font_family or style.font_file} 不可用，使用 {replacement} 显示。"
            if replacement
            else ""
        )
        self.warning.setText((message + (f" 缺少字符：{missing}" if missing else "")).strip())

    def edit_selected(self) -> None:
        if self.pending:
            self._message("请先完成或取消当前文字操作。")
            return
        if self.selection_error() or len(self.selected()) != 1:
            self._message(self.selection_error() or "请选择一个文字对象。")
            return
        self.refresh_selection()
        self._editing = self.selected()[0]
        displayed = self.display_text(self._editing)
        if displayed is None:
            self._message("文字不在当前工作平面内。")
            self._editing = None
            return
        self._position = displayed.position_mm
        self.editor.setPlainText(self._editing.text)
        self._open_editor()

    def apply_properties(self) -> None:
        if self.pending:
            self._message("请先完成或取消画布文字编辑，再应用特性。")
            return
        if self.selection_error() or not self.selected():
            self._message(self.selection_error() or "请选择文字对象。")
            return
        try:
            updates: list[dict[str, object]] = []
            for item in self.selected():
                self._editing = item
                value = self._record(
                    self.content.toPlainText() if len(self.selected_ids) == 1 else item.text
                )
                if len(self.selected_ids) > 1:
                    source = item.to_mapping()
                    changed = value.to_mapping()
                    for key in self.dirty_fields - {"x", "y"}:
                        source[key] = changed[key]
                    if "x" in self.dirty_fields or "y" in self.dirty_fields:
                        source["position_mm"] = [
                            self.x.value() if "x" in self.dirty_fields else item.position_mm[0],
                            self.y.value() if "y" in self.dirty_fields else item.position_mm[1],
                        ]
                    value = DrawingText.from_mapping(source)
                updates.append(value.to_mapping())
            self._editing = None
            if self._write("drawing.text.batch", {"add": [], "update": updates, "remove": []}):
                self._message("文字特性已更新。")
        except ValueError as exc:
            self._editing = None
            self.warning.setText(str(exc))

    def delete(self) -> bool:
        error = self.selection_error()
        if error:
            self._message(error)
            return False
        if not self.selected_ids:
            return False
        result = self._write(
            "drawing.text.batch", {"add": [], "update": [], "remove": sorted(self.selected_ids)}
        )
        if result:
            self.selected_ids.clear()
        return result

    def transform(
        self,
        operation: str,
        base: tuple[float, float],
        target: tuple[float, float],
        *,
        angle: float | None = None,
        scale: float | None = None,
        copy: bool = False,
    ) -> bool:
        from mycad.core.drawing_text import mirror_text, move_text, rotate_text, scale_text

        if self.selection_error():
            self._message(self.selection_error())
            return False
        try:
            values: list[DrawingText] = []
            for source in self.selected():
                item = self.display_text(source)
                if item is None:
                    raise ValueError("文字不在当前工作平面内。")
                if operation in ("move", "copy"):
                    value = move_text(item, (target[0] - base[0], target[1] - base[1]))
                elif operation == "rotate":
                    value = rotate_text(
                        item,
                        angle
                        if angle is not None
                        else math.degrees(math.atan2(target[1] - base[1], target[0] - base[0])),
                        base,
                    )
                elif operation == "scale":
                    value = scale_text(
                        item,
                        scale if scale is not None else math.dist(base, target),
                        base,
                        self.styles,
                    )
                elif operation == "mirror":
                    value = mirror_text(item, base, target)
                else:
                    return False
                rotation_change = project_coplanar_rotation(
                    value.rotation_deg - item.rotation_deg,
                    self.canvas.drawing_view_frame,
                    WorkPlaneFrame.xy(),
                )
                value = replace(
                    self._project_text(value, self.canvas.drawing_view_frame, WorkPlaneFrame.xy()),
                    rotation_deg=source.rotation_deg + rotation_change,
                )
                if operation == "copy" or copy:
                    value = replace(value, text_id=uuid4().hex)
                values.append(value)
        except ValueError as exc:
            self._message(str(exc))
            return False
        return self._write(
            "drawing.text.batch",
            {
                "add": [item.to_mapping() for item in values]
                if operation == "copy" or copy
                else [],
                "update": []
                if operation == "copy" or copy
                else [item.to_mapping() for item in values],
                "remove": [],
            },
        )

    def open_styles(self) -> None:
        if (
            self.pending
            or self.canvas.has_pending_geometry
            or self.canvas.active_transform is not None
        ):
            self._message("请先完成或取消当前操作，再设置文字样式。")
            return
        dimension_styles = self.canvas.drawing_dimension_styles
        used = {item.style_id for item in self.texts}
        if dimension_styles is not None:
            used.update(
                style.text_style_id
                for style in dimension_styles.styles
                if style.text_style_id is not None
            )
        dialog = TextStyleDialog(self.styles, frozenset(used), self.manager, self.parent)
        if dialog.exec() == int(QDialog.DialogCode.Accepted) and dialog.table != self.styles:
            self._write("drawing.text_styles.set", dialog.table.to_mapping())

    def handle_command(self, source: str) -> bool:
        parts = shlex.split(source) if source.strip() else []
        command = parts[0].upper() if parts else ""
        if command in {"STYLE", "ST"}:
            self.open_styles()
            return True
        if command in {"TEXT", "DTEXT", "MTEXT", "T", "MT"}:
            kind = "mtext" if command in {"MTEXT", "T", "MT"} else "text"
            if not self.begin(kind):
                return True
            if len(parts) > 1:
                try:
                    self.place(parse_coordinate(parts[1], None))
                    if len(parts) >= 5:
                        height, angle = float(parts[2]), float(parts[3])
                        if not math.isfinite(height) or height <= 0 or not math.isfinite(angle):
                            raise ValueError("字高须为正数，旋转角须为有限数值。")
                        if (
                            height > self.height.maximum()
                            or not self.rotation.minimum() <= angle <= self.rotation.maximum()
                        ):
                            raise ValueError("字高或旋转角超出文字工具支持范围。")
                        self.height.setValue(height)
                        self.rotation.setValue(angle)
                        self.editor.setPlainText(" ".join(parts[4:]))
                        self.commit()
                except ValueError as exc:
                    self._message(str(exc))
            return True
        if self._mode is not None and not self.overlay.isVisible():
            try:
                self.place(parse_coordinate(source, None))
            except ValueError as exc:
                self._message(str(exc))
            return True
        return False

    def copy(self) -> bool:
        if not self.selected_ids or self.selection_error():
            return False
        if self.pending or self.canvas.has_pending_geometry or self.canvas.has_active_edit_gesture:
            self._message("请先完成或取消当前操作，再复制文字。")
            return False
        used = {item.style_id for item in self.selected()}
        sketch: Sketch | None = None
        dimension_styles: DimensionStyleTable | None = None
        images = tuple(
            image
            for image in self.canvas.drawing_rasters
            if image.image_id in self.canvas.selected_raster_ids
        )
        if self.canvas.selected_entity_ids:
            saved = self.selected_ids
            self.selected_ids = set()
            try:
                copied = self.canvas.capture_copy_mime()
                if copied is None:
                    return False
            finally:
                self.selected_ids = saved
            if copied.hasFormat(DRAWING_MIXED_CLIPBOARD_MIME):
                sketch, images, dimension_styles, _dimension_fonts = decode_mixed_clipboard_full(
                    bytes(copied.data(DRAWING_MIXED_CLIPBOARD_MIME).data())
                )
            elif copied.hasFormat(DRAWING_CLIPBOARD_MIME):
                sketch, dimension_styles, _dimension_fonts = decode_drawing_clipboard_full(
                    bytes(copied.data(DRAWING_CLIPBOARD_MIME).data())
                )
            else:
                return False
        if dimension_styles is not None:
            used.update(
                style.text_style_id
                for style in dimension_styles.styles
                if style.text_style_id is not None
            )
        styles = TextStyleTable(
            tuple(style for style in self.styles.styles if style.style_id in used), next(iter(used))
        )
        try:
            data = encode_text_clipboard(
                self.selected(), styles, sketch, dimension_styles, images, self.canvas.layer_table
            )
        except ValueError as exc:
            self._message(str(exc))
            return False
        mime = QMimeData()
        mime.setData(TEXT_CLIPBOARD_MIME, data)
        mime.setText("\n".join(item.text for item in self.selected()))
        QApplication.clipboard().setMimeData(mime)
        self._message("文字与所选图形已复制；可粘贴到其他二维图纸。")
        return True

    def begin_paste(self) -> bool:
        if (
            self.pending
            or self.canvas.has_pending_geometry
            or self.canvas.has_active_edit_gesture
            or self.canvas.active_transform is not None
        ):
            return False
        mime = cast("QMimeData | None", QApplication.clipboard().mimeData())
        if mime is None or not mime.hasFormat(TEXT_CLIPBOARD_MIME):
            return False
        try:
            project_coplanar_vector((0, 0), self.canvas.drawing_view_frame, WorkPlaneFrame.xy())
            data = bytes(mime.data(TEXT_CLIPBOARD_MIME).data())
            if not data or len(data) > _MAX_CLIPBOARD_BYTES:
                raise ValueError("文字剪贴板大小无效。")
            raw: object = json.loads(data)
            if not isinstance(raw, dict):
                raise ValueError("文字剪贴板结构无效。")
            record = cast("dict[str, object]", raw)
            if (
                record.get("format") != "mycad-text"
                or type(record.get("version")) is not int
                or record["version"] != 1
                or not isinstance(record.get("texts"), list)
            ):
                raise ValueError("文字剪贴板版本无效。")
            items = tuple(
                DrawingText.from_mapping(item) for item in cast("list[object]", record["texts"])
            )
            if not items or len(items) > 1000:
                raise ValueError("文字剪贴板数量无效。")
            incoming_styles = TextStyleTable.from_mapping(record["styles"])
            for item in items:
                incoming_styles.get(item.style_id)
            raw_images = record.get("images", [])
            if not isinstance(raw_images, list) or len(cast("list[object]", raw_images)) > 1000:
                raise ValueError("剪贴板图片数据无效。")
            images = tuple(
                DrawingRaster.from_mapping(value) for value in cast("list[object]", raw_images)
            )
            sketch = (
                Sketch.from_mapping(record["sketch"]) if record.get("sketch") is not None else None
            )
            dim_styles = (
                DimensionStyleTable.from_mapping(record["dimension_styles"])
                if record.get("dimension_styles") is not None
                else None
            )
            if dim_styles is not None:
                for style in dim_styles.styles:
                    if style.text_style_id is not None:
                        incoming_styles.get(style.text_style_id)
            layers = (
                SketchLayerTable.from_mapping(record["layers"])
                if "layers" in record
                else self.canvas.layer_table
            )
            if not self.canvas.set_tool("选择元素"):
                return False
            self._paste = items
            self._paste_styles = incoming_styles
            self._paste_sketch, self._paste_rasters = sketch, images
            self._paste_dimension_styles, self._paste_layers = dim_styles, layers
            self._message("粘贴文字：指定插入点，Esc 取消。")
            return True
        except (ValueError, KeyError, TypeError) as exc:
            self._message(f"无法粘贴文字：{exc}")
            return False

    def place_paste(self, point: tuple[float, float]) -> bool:
        from mycad.core.drawing_text import move_text

        if not self._paste or self._paste_styles is None:
            return False
        try:
            project_coplanar_vector((0, 0), self.canvas.drawing_view_frame, WorkPlaneFrame.xy())
            table, items = reconcile_text_styles(self._paste, self._paste_styles, self.styles)
            origin = items[0].position_mm
            target = WorkPlaneFrame.xy().world_to_local(
                self.canvas.drawing_view_frame.local_to_world(point)
            )
            delta = (target[0] - origin[0], target[1] - origin[1])
            additions = tuple(
                replace(move_text(item, delta), text_id=uuid4().hex) for item in items
            )
            layers = self.canvas.layer_table
            names = {item.layer_name for item in additions}
            names.update(image.layer_name for image in self._paste_rasters)
            if self._paste_sketch is not None:
                names.update(item.layer_name for item in self._paste_sketch.entities)
            for name in names:
                try:
                    layer = layers.get(name)
                except KeyError:
                    layer = self._paste_layers.get(name)
                    layers = layers.add(layer)
                if not layer.displayed or layer.locked:
                    raise ValueError(f"目标图层 {name} 隐藏或已锁定。")
            images = tuple(
                replace(
                    image,
                    image_id=uuid4().hex,
                    origin_mm=(image.origin_mm[0] + delta[0], image.origin_mm[1] + delta[1]),
                )
                for image in self._paste_rasters
            )
            dimension_styles = self._paste_dimension_styles
            if self._paste_sketch is not None:
                source_sketch = self._paste_sketch
                if self.ignore_unused_paste_dimension_styles and not source_sketch.constraints:
                    dimension_styles = None
                if dimension_styles is not None:
                    current = self.canvas.drawing_dimension_styles
                    if current is None:
                        raise ValueError("当前图纸无法导入标注样式。")
                    dimension_styles, table = reconcile_clipboard_fonts(
                        dimension_styles, self._paste_styles, table
                    )
                    dimension_styles, source_sketch = reconcile_clipboard_styles(
                        source_sketch, dimension_styles, current
                    )
                sketch_delta = project_coplanar_vector(
                    delta, WorkPlaneFrame.xy(), source_sketch.frame
                )
                entities, constraints = instantiate_drawing_clipboard(
                    source_sketch, sketch_delta, styles=dimension_styles
                )
                sketch = Sketch(uuid4().hex, source_sketch.frame, entities, constraints, layers)
            else:
                sketch = Sketch(uuid4().hex, WorkPlaneFrame.xy(), (), layers=layers)
            if self.paste_commit is not None:
                success = self.paste_commit(sketch, additions, table, images, dimension_styles)
            elif not sketch.entities and not images and layers == self.canvas.layer_table:
                success = self._write(
                    "drawing.text.batch",
                    {
                        "add": [item.to_mapping() for item in additions],
                        "update": [],
                        "remove": [],
                        "styles": table.to_mapping(),
                    },
                )
            else:
                raise ValueError("当前文档无法提交混合剪贴板对象。")
            if success:
                self.cancel()
                self._message("文字与所选图形已粘贴；可一次撤销。")
        except (ValueError, KeyError) as exc:
            self._message(f"无法粘贴文字：{exc}")
        return True
