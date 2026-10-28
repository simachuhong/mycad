# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Plain text authored directly on paper; all durable changes use the Bus."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import cast, override
from uuid import UUID, uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
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

from mycad.core.drawing import DrawingNote, DrawingState
from mycad.core.drawing_codec import drawing_object_mapping
from mycad.core.drawing_projection import Point2
from mycad.ui.drawing_canvas import DrawingCanvas


class PaperNoteEditor(QPlainTextEdit):
    commit_requested = Signal()
    cancel_requested = Signal()

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.commit_requested.emit()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class DrawingNoteTools(QWidget):
    def __init__(
        self,
        canvas: DrawingCanvas,
        state: Callable[[], DrawingState],
        sheet: Callable[[], UUID | None],
        execute: Callable[[str, dict[str, object], Callable[[], None] | None], None],
        render: Callable[[], None],
        message: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.canvas = canvas
        self._state, self._sheet = state, sheet
        self._execute, self._render, self._message = execute, render, message
        self.selected: UUID | None = None
        self.draft: DrawingNote | None = None
        self._active = False
        self._sheet_id: UUID | None = None
        self._editing_id: UUID | None = None
        self._position: Point2 = (0, 0)
        self._dragging = False
        self._layer = "TEXT"
        form = QFormLayout(self)
        hint = QLabel(
            "点击“文本标注”，再单击纸面输入。Enter 换行，Ctrl+Enter 完成，Esc 取消。双击文字编辑，拖动移动，Delete 删除。"
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        self.height_field = QDoubleSpinBox()
        self.height_field.setRange(0.1, 100)
        self.height_field.setDecimals(2)
        self.height_field.setValue(3.5)
        self.height_field.setSuffix(" mm")
        form.addRow("纸面字高", self.height_field)
        self.edit_button = QPushButton("编辑选中文字")
        self.apply_button = QPushButton("应用字高")
        self.delete_button = QPushButton("删除选中文字")
        for button in (self.edit_button, self.apply_button, self.delete_button):
            form.addRow(button)
        self.edit_button.clicked.connect(lambda: self.edit(self.selected))
        self.apply_button.clicked.connect(self.apply_height)
        self.delete_button.clicked.connect(self.delete_selected)
        self.overlay = QFrame(canvas.viewport())
        self.overlay.setFrameShape(QFrame.Shape.StyledPanel)
        self.overlay.setAutoFillBackground(True)
        layout = QVBoxLayout(self.overlay)
        layout.setContentsMargins(5, 5, 5, 5)
        self.editor = PaperNoteEditor()
        self.editor.setPlaceholderText("输入图纸说明…")
        layout.addWidget(self.editor)
        buttons = QHBoxLayout()
        done, cancel = QPushButton("完成 Ctrl+Enter"), QPushButton("取消 Esc")
        buttons.addWidget(done)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.overlay.hide()
        done.clicked.connect(self.commit)
        cancel.clicked.connect(self.cancel)
        self.editor.commit_requested.connect(self.commit)
        self.editor.cancel_requested.connect(self.cancel)
        self.editor.textChanged.connect(self._preview_text)
        self.height_field.valueChanged.connect(self._preview_text)
        canvas.paper_clicked.connect(self.click)
        canvas.note_selected.connect(self.select)
        canvas.note_edit_requested.connect(self.edit)
        canvas.note_dragged.connect(self.drag)
        canvas.note_delete_requested.connect(self.delete_selected)
        canvas.drag_cancelled.connect(self.cancel_drag)
        self.select(None)

    @property
    def pending(self) -> bool:
        return self._active or self._dragging

    def begin(self) -> None:
        self.cancel()
        self._sheet_id = self._sheet()
        if self._sheet_id is None:
            return
        self._active = True
        self._layer = "TEXT"
        self.canvas.selected_note = None
        self.canvas.note_selected.emit(None)
        self.canvas.note_mode = True
        self.canvas.setFocus()
        self._message("在纸面单击文字位置，然后直接输入；Ctrl+Enter 完成，Esc 取消。")
        self._render()

    def click(self, point: object) -> None:
        if not self._active or self.overlay.isVisible() or not isinstance(point, tuple):
            return
        x, y = cast("Point2", point)
        self._position = (float(x), float(y))
        self.editor.clear()
        self._open_editor()

    def _open_editor(self) -> None:
        from PySide6.QtCore import QPointF

        position = self.canvas.mapFromScene(QPointF(self._position[0], -self._position[1]))
        width = min(340, max(180, self.canvas.viewport().width() - 16))
        height = min(155, max(100, self.canvas.viewport().height() - 16))
        self.overlay.setGeometry(
            max(0, min(position.x(), self.canvas.viewport().width() - width)),
            max(0, min(position.y(), self.canvas.viewport().height() - height)),
            width,
            height,
        )
        self.overlay.show()
        self.overlay.raise_()
        self.editor.setFocus()

    def _preview_text(self) -> None:
        if not self._active or self._sheet_id is None:
            return
        text = self.editor.toPlainText()
        try:
            self.draft = (
                DrawingNote(
                    self._editing_id or uuid4(),
                    self._sheet_id,
                    text,
                    self._position,
                    self.height_field.value(),
                    self._layer,
                )
                if text.strip()
                else None
            )
        except ValueError as error:
            self.draft = None
            self._message(str(error))
        self._render()

    def preview(self, state: DrawingState) -> DrawingState:
        if self.draft is None or self.draft.sheet_id not in {s.sheet_id for s in state.sheets}:
            return state
        return replace(
            state,
            notes=tuple(n for n in state.notes if n.note_id != self.draft.note_id) + (self.draft,),
        )

    def commit(self) -> None:
        if self.draft is None:
            self._message("文字不能为空；输入后按 Ctrl+Enter 完成，或 Esc 取消。")
            return
        if self._sheet_id != self._sheet() or self._sheet_id not in {
            s.sheet_id for s in self._state().sheets
        }:
            self.cancel()
            return
        command = "drawing.note.update" if self._editing_id is not None else "drawing.note.create"
        self._execute(command, drawing_object_mapping(self.draft), self.cancel)

    def select(self, identity: object) -> None:
        note = next((n for n in self._state().notes if n.note_id == identity), None)
        self.selected = note.note_id if note else None
        for button in (self.edit_button, self.apply_button, self.delete_button):
            button.setEnabled(note is not None)
        if note is not None:
            self.height_field.setValue(note.height_mm)

    def edit(self, identity: object) -> None:
        note = next((n for n in self._state().notes if n.note_id == identity), None)
        if note is None:
            return
        self.cancel()
        self._active = True
        self._sheet_id = note.sheet_id
        self._editing_id = note.note_id
        self._position = note.position_mm
        self._layer = note.layer
        self.height_field.setValue(note.height_mm)
        self.editor.setPlainText(note.text)
        self.canvas.note_mode = True
        self._open_editor()

    def apply_height(self) -> None:
        if self.selected is not None:
            self._execute(
                "drawing.note.update",
                {"note_id": str(self.selected), "height_mm": self.height_field.value()},
                None,
            )

    def delete_selected(self) -> None:
        if self.selected is not None and not self.pending:
            self._execute("drawing.note.delete", {"note_id": str(self.selected)}, None)
            self.select(None)

    def drag(self, identity: object, point: object, final: bool) -> None:
        note = next((n for n in self._state().notes if n.note_id == identity), None)
        if note is None or self._active or not isinstance(point, tuple):
            return
        x, y = cast("Point2", point)
        self.draft = replace(note, position_mm=(float(x), float(y)))
        self._dragging = True
        if final:
            self._execute(
                "drawing.note.update", drawing_object_mapping(self.draft), self.cancel_drag
            )
        self._render()

    def cancel_drag(self) -> None:
        if self._dragging:
            self._dragging = False
            self.draft = None
            self._render()

    def cancel(self) -> None:
        self._active = False
        self._editing_id = None
        self._sheet_id = None
        self.draft = None
        self.overlay.hide()
        self.canvas.note_mode = False
        self.canvas.setFocus()
        self._render()
