# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Canvas-first associated dimensions; the side tab edits expression only."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolBar,
    QWidget,
)

from mycad.core.drawing import AnnotationKind, DrawingAnnotation, DrawingState
from mycad.core.drawing_annotations import resolve_annotation
from mycad.core.drawing_codec import drawing_object_mapping
from mycad.core.drawing_projection import LineCurve, Point2, ProjectionResult, SceneView
from mycad.core.drawing_references import (
    DrawingGeometryReference,
    reference_for_curve,
    resolve_reference,
)
from mycad.ui.drawing_canvas import DrawingCanvas


class DrawingAnnotationTools(QWidget):
    def __init__(
        self,
        canvas: DrawingCanvas,
        toolbar: QToolBar,
        state: Callable[[], DrawingState],
        projections: Mapping[UUID, ProjectionResult],
        execute: Callable[[str, dict[str, object]], None],
        render: Callable[[], None],
        message: Callable[[str], None],
        clean: Callable[[UUID], bool],
    ) -> None:
        super().__init__()
        self.canvas, self.toolbar = canvas, toolbar
        self._state, self._projections = state, projections
        self._execute, self._render, self._message, self._clean = execute, render, message, clean
        self.selected: UUID | None = None
        self.draft: DrawingAnnotation | None = None
        self._kind: AnnotationKind | None = None
        self._references: list[DrawingGeometryReference] = []
        self._view: UUID | None = None
        self._fingerprint = ""
        self._reattach: UUID | None = None
        self._dragging = False
        self.tool_actions: dict[str, QAction] = {}
        for kind, label in (
            ("horizontal", "水平"),
            ("vertical", "垂直"),
            ("aligned", "对齐"),
            ("radius", "半径"),
            ("diameter", "直径"),
            ("angle", "角度"),
            ("center", "中心标记/线"),
        ):
            action = toolbar.addAction(label)
            action.triggered.connect(
                lambda _checked=False, k=kind: self.begin(cast("AnnotationKind", k))
            )
            self.tool_actions[kind] = action
        form = QFormLayout(self)
        self.description = QLabel("在图中选择几何并放置尺寸。工程图尺寸只测量，不驱动模型。")
        self.description.setWordWrap(True)
        self.precision = QSpinBox()
        self.precision.setRange(0, 8)
        self.precision.setValue(2)
        self.prefix, self.suffix = QLineEdit(), QLineEdit(" mm")
        self.apply_button = QPushButton("应用文字格式")
        self.rebind_button = QPushButton("在图中重附着")
        self.remove_button = QPushButton("删除标注")
        for label, widget in (
            ("", self.description),
            ("小数位", self.precision),
            ("前缀", self.prefix),
            ("后缀", self.suffix),
            ("", self.apply_button),
            ("", self.rebind_button),
            ("", self.remove_button),
        ):
            form.addRow(label, widget)
        self.apply_button.clicked.connect(self.apply_expression)
        self.rebind_button.clicked.connect(self.reattach)
        self.remove_button.clicked.connect(self.delete_selected)
        canvas.geometry_clicked.connect(self.choose)
        canvas.annotation_selected.connect(self.select)
        canvas.annotation_dragged.connect(self.drag_text)
        canvas.annotation_delete_requested.connect(self.delete_selected)
        canvas.drag_cancelled.connect(self.cancel_drag)
        self.select(None)

    @property
    def pending(self) -> bool:
        return bool(self.draft or self._references)

    def begin(self, kind: AnnotationKind) -> None:
        if self.canvas.placing:
            self._message("请先完成或取消视图放置。")
            return
        self.cancel()
        self._kind = kind
        self.canvas.annotation_mode = True
        self.canvas.setFocus()
        self._message(
            "在图中选几何：直线可直接标长度；两圆心可标中心距。选好后单击放置，Esc 取消。"
        )

    def choose(self, identity: object, curve_id: str, point: object) -> None:
        if self._kind is None or not isinstance(identity, UUID):
            return
        position = cast("Point2", point)
        if self.draft is not None:
            self.commit(position)
            return
        if not self._clean(identity):
            self._message("此视图尚未更新完成，请更新后再标注。")
            return
        if self._view is not None and identity != self._view:
            self._message("同一尺寸的几何必须来自同一视图。")
            return
        result = self._projections.get(identity)
        if result is None:
            return
        curve = next((c for c in result.curves if c.curve_id == curve_id), None)
        if curve is None:
            return
        try:
            reference = reference_for_curve(
                curve,
                role="center"
                if self._kind in ("horizontal", "vertical", "aligned")
                else "geometry",
            )
            resolution = resolve_reference(reference, result)
            if resolution.status != "resolved":
                raise ValueError(resolution.message)
            self._view, self._fingerprint = identity, result.source_fingerprint
            if (
                self._kind in ("horizontal", "vertical", "aligned")
                and not self._references
                and isinstance(curve.geometry, LineCurve)
            ):
                self._references = [
                    replace(reference, role="start"),
                    replace(reference, role="end"),
                ]
            else:
                self._references.append(reference)
            count = 1 if self._kind in ("radius", "diameter", "center") else 2
            if len(self._references) < count:
                self._message("请选择第二个关联几何。")
                return
            existing = next(
                (a for a in self._state().annotations if a.annotation_id == self._reattach), None
            )
            if existing is None:
                self.draft = DrawingAnnotation(
                    uuid4(),
                    identity,
                    self._kind,
                    tuple(self._references),
                    position,
                    self.precision.value(),
                    prefix=self.prefix.text(),
                    suffix=self.suffix.text(),
                )
            else:
                self.draft = replace(
                    existing,
                    view_id=identity,
                    references=tuple(self._references),
                    position_mm=position,
                )
            self._message("移动鼠标预览，单击放置；Esc 取消。")
            self._render()
        except ValueError as error:
            self._message(str(error))

    def move_preview(self, point: Point2) -> None:
        if self._kind is not None and self.draft is not None:
            self.draft = replace(self.draft, position_mm=point)
            self._render()

    def click(self, point: Point2) -> None:
        if self.draft is not None and self._kind is not None:
            self.commit(point)

    def commit(self, point: Point2 | None = None) -> None:
        draft = self.draft
        if draft is None or self._kind is None:
            return
        result = self._projections.get(draft.view_id)
        if (
            result is None
            or not self._clean(draft.view_id)
            or result.source_fingerprint != self._fingerprint
        ):
            self._message("模型已变化，标注草稿已保留；Esc 取消后请重新选择几何。")
            return
        if point is not None:
            draft = replace(draft, position_mm=point)
        state = self._state()
        view = SceneView(
            draft.view_id,
            state.effective_anchor(draft.view_id),
            state.effective_scale(draft.view_id),
            result.curves,
        )
        resolved = resolve_annotation(draft, result, view)
        if resolved.status != "resolved":
            self._message(resolved.message)
            return
        command = (
            "drawing.annotation.update"
            if self._reattach is not None
            else "drawing.annotation.create"
        )
        self._execute(command, drawing_object_mapping(draft))
        self.cancel()

    def preview(self, state: DrawingState) -> DrawingState:
        if self.draft is None or self.draft.view_id not in {v.view_id for v in state.views}:
            return state
        annotations = tuple(
            a for a in state.annotations if a.annotation_id != self.draft.annotation_id
        )
        return replace(state, annotations=(*annotations, self.draft))

    def select(self, identity: object) -> None:
        annotation = next(
            (a for a in self._state().annotations if a.annotation_id == identity), None
        )
        self.selected = annotation.annotation_id if annotation else None
        for widget in (self.apply_button, self.rebind_button, self.remove_button):
            widget.setEnabled(annotation is not None)
        if annotation is not None:
            self.precision.setValue(annotation.precision)
            self.prefix.setText(annotation.prefix)
            self.suffix.setText(annotation.suffix)
            self.description.setText(
                "显示未缩放的投影测量值；编辑精度和前后缀，不能覆盖真实尺寸值。"
            )

    def drag_text(self, identity: object, point: object, finished: bool) -> None:
        annotation = next(
            (a for a in self._state().annotations if a.annotation_id == identity), None
        )
        if annotation is None:
            return
        self._dragging = True
        self.draft = replace(annotation, position_mm=cast("Point2", point))
        if finished:
            self._execute(
                "drawing.annotation.update",
                {"annotation_id": str(identity), "position_mm": list(self.draft.position_mm)},
            )
            self.draft = None
            self._dragging = False
        self._render()

    def cancel_drag(self) -> None:
        if self._dragging:
            self.draft = None
            self._dragging = False
            self._render()

    def apply_expression(self) -> None:
        if self.selected is not None:
            self._execute(
                "drawing.annotation.update",
                {
                    "annotation_id": str(self.selected),
                    "precision": self.precision.value(),
                    "prefix": self.prefix.text(),
                    "suffix": self.suffix.text(),
                },
            )

    def reattach(self) -> None:
        annotation = next(
            (a for a in self._state().annotations if a.annotation_id == self.selected), None
        )
        if annotation is not None:
            self.begin(annotation.kind)
            self._reattach = annotation.annotation_id
            self._message("选择新的唯一几何，再单击放置；旧标注保留到确认成功。")

    def delete_selected(self) -> None:
        if self.selected is not None:
            self._execute("drawing.annotation.delete", {"annotation_id": str(self.selected)})
            self.select(None)

    def cancel(self) -> None:
        self.draft = None
        self._kind = None
        self._references.clear()
        self._view = None
        self._reattach = None
        self._dragging = False
        self.canvas.annotation_mode = False
        self._render()
