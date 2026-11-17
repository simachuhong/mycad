# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Paper-space canvas. Mouse points are paper millimetres, positive Y upwards."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import override
from uuid import UUID

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QHideEvent,
    QKeyEvent,
    QMouseEvent,
    QPen,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)

from mycad.core.drawing_paper import (
    PaperText,
    detail_marker_curves,
    paper_texts,
    section_marker_lines,
    sheet_frame,
)
from mycad.core.drawing_projection import (
    DrawingScene,
    Point2,
)
from mycad.ui.drawing_render import add_paper_text, curve_path, paper_pen


class DrawingCanvas(QGraphicsView):
    note_selected = Signal(object)
    note_edit_requested = Signal(object)
    note_dragged = Signal(object, object, bool)
    note_delete_requested = Signal()
    paper_clicked = Signal(object)
    paper_moved = Signal(object)
    commit_requested = Signal()
    cancel_requested = Signal()
    geometry_clicked = Signal(object, str, object)
    annotation_selected = Signal(object)
    annotation_edit_requested = Signal(object)
    annotation_dragged = Signal(object, object, bool)
    annotation_delete_requested = Signal()
    view_selected = Signal(object)
    view_dragged = Signal(object, str, object, bool)
    drag_cancelled = Signal()
    alignment_requested = Signal(object)
    delete_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setMouseTracking(True)
        self.setBackgroundBrush(QColor("#dce1e7"))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.drawing_scene: DrawingScene | None = None
        self.placing = False
        self._needs_fit = True
        self.selected_view: UUID | None = None
        self.view_selection_guard: Callable[[UUID | None], bool] | None = None
        self.view_statuses: dict[UUID, str] = {}
        self.alignable_views: set[UUID] = set()
        self.deletion_preview: set[UUID] = set()
        self._bounds: dict[UUID, QRectF] = {}
        self._grips: dict[str, QRectF] = {}
        self._grip_items: list[QGraphicsItem] = []
        self._drag_view: UUID | None = None
        self._drag_mode = "move"
        self._drag_start: Point2 = (0, 0)
        self._drag_anchor: Point2 = (0, 0)
        self._drag_scale = 1.0
        self._drag_value: Point2 | float = (0, 0)
        self._drag_started = False
        self.note_mode = False
        self.selected_note: UUID | None = None
        self._drag_note: UUID | None = None
        self._note_bounds: dict[UUID, QRectF] = {}
        self.annotation_mode = False
        self.selected_annotation: UUID | None = None
        self._drag_annotation: UUID | None = None
        self._annotation_drag_position: Point2 = (0, 0)
        self._annotation_bounds: dict[UUID, QRectF] = {}
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def clear_scene(self) -> None:
        self.selected_note = None
        self.note_selected.emit(None)
        self._note_bounds.clear()
        self.selected_annotation = None
        self.annotation_selected.emit(None)
        self.select_view(None)
        self.drawing_scene = None
        self._needs_fit = True
        graphics = self.scene()
        self._grip_items.clear()
        self._annotation_bounds.clear()
        self._bounds.clear()
        self._grips.clear()
        graphics.clear()
        graphics.setSceneRect(0, 0, 297, 210)

    def set_scene(self, scene: DrawingScene) -> None:
        first = self.drawing_scene is None or self.drawing_scene.sheet_id != scene.sheet_id
        self.drawing_scene = scene
        if self.selected_annotation is not None and self.selected_annotation not in {
            a.annotation_id for a in scene.resolved_annotations
        }:
            self.selected_annotation = None
            self.annotation_selected.emit(None)
        if self.selected_note is not None and self.selected_note not in {
            note.note_id for note in scene.notes
        }:
            self.selected_note = None
            self.note_selected.emit(None)
        graphics = self.scene()
        assert graphics is not None
        self._note_bounds.clear()
        self._grip_items.clear()
        self._annotation_bounds.clear()
        self._bounds.clear()
        self._grips.clear()
        graphics.clear()
        w, h = scene.size_mm
        paper = graphics.addRect(0, -h, w, h, QPen(QColor("#929ba5"), 0.15), QColor("white"))
        paper.setZValue(-10)
        for line in sheet_frame(scene):
            graphics.addPath(curve_path(line), paper_pen("FRAME"))
        for line in section_marker_lines(scene):
            graphics.addPath(curve_path(line), paper_pen("SECTION"))
        for curve in detail_marker_curves(scene):
            graphics.addPath(curve_path(curve), paper_pen("DETAIL"))
        for text in paper_texts(scene):
            if text.layer in ("FRAME", "SECTION", "DETAIL"):
                add_paper_text(graphics, text)
        for view in scene.views:
            for hatch in view.hatch:
                pen = paper_pen("HATCH", view.scale)
                status = self.view_statuses.get(view.view_id, "clean")
                if status != "clean":
                    pen.setColor(QColor("#b77512" if status != "failed" else "#bc3540"))
                item = graphics.addPath(curve_path(hatch), pen)
                item.setPos(view.anchor_mm[0], -view.anchor_mm[1])
                item.setScale(view.scale)
                item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            for curve in view.curves:
                pen = paper_pen(curve.visibility.upper(), view.scale)
                status = self.view_statuses.get(view.view_id, "clean")
                if status != "clean":
                    pen.setColor(QColor("#b77512" if status != "failed" else "#bc3540"))
                try:
                    path = curve_path(curve.geometry, tolerance=0.01 / view.scale)
                except ValueError as error:
                    warning = graphics.addText(str(error))
                    warning.setDefaultTextColor(QColor("#b52028"))
                    warning.setPos(view.anchor_mm[0], -view.anchor_mm[1])
                    continue
                item = graphics.addPath(path, pen)
                item.setPos(view.anchor_mm[0], -view.anchor_mm[1])
                item.setScale(view.scale)
                item.setData(0, view.view_id)
                item.setData(1, curve.curve_id)
                bounds = item.sceneBoundingRect()
                previous = self._bounds.get(view.view_id)
                self._bounds[view.view_id] = bounds if previous is None else previous.united(bounds)
        for annotation in scene.resolved_annotations:
            color = (
                paper_pen(annotation.layer).color()
                if annotation.status == "resolved"
                else QColor("#bc3540")
            )
            pen = paper_pen(annotation.layer)
            pen.setColor(color)
            for geometry in annotation.curves:
                item = graphics.addPath(curve_path(geometry), pen)
                item.setData(2, annotation.annotation_id)
                item.setZValue(3)
            label = add_paper_text(
                graphics, PaperText(annotation.position_mm, annotation.text or "中心")
            )
            label.setDefaultTextColor(color)
            label.setData(2, annotation.annotation_id)
            label.setZValue(4)
            self._annotation_bounds[annotation.annotation_id] = label.sceneBoundingRect()
        for note in scene.notes:
            item = add_paper_text(
                graphics, PaperText(note.position_mm, note.text, note.height_mm, note.layer)
            )
            item.setData(3, note.note_id)
            item.setZValue(5)
            self._note_bounds[note.note_id] = item.sceneBoundingRect()
        graphics.setSceneRect(-8, -h - 8, w + 16, h + 16)
        self._draw_grips()
        if first:
            self._needs_fit = True
            if self.isVisible():
                self.fit_view()

    def fit_view(self) -> None:
        self._needs_fit = False
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._draw_grips()

    @override
    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._needs_fit and self.drawing_scene is not None:
            QTimer.singleShot(0, self, self.fit_view)

    def paper_point(self, point: QPointF) -> Point2:
        mapped = self.mapToScene(point.toPoint())
        return mapped.x(), -mapped.y()

    def select_view(self, identity: UUID | None) -> None:
        changed = self.selected_view != identity
        self.selected_view = identity
        self._draw_grips()
        if changed:
            self.view_selected.emit(identity)

    def note_text_position(self, identity: UUID) -> QPoint:
        return self.mapFromScene(self._note_bounds[identity].center())

    def annotation_text_position(self, identity: UUID) -> QPoint:
        return self.mapFromScene(self._annotation_bounds[identity].center())

    def grip_position(self, mode: str) -> QPoint:
        return self.mapFromScene(self._grips[mode].center())

    def _draw_grips(self) -> None:
        graphics = self.scene()
        for item in self._grip_items:
            graphics.removeItem(item)
        self._grip_items.clear()
        self._grips.clear()
        for identity in self.deletion_preview:
            bounds = self._bounds.get(identity)
            if bounds is not None:
                pen = QPen(QColor("#d52d3c"), 0)
                item = graphics.addRect(bounds.adjusted(-2, -2, 2, 2), pen)
                self._grip_items.append(item)
        bounds = self._bounds.get(self.selected_view) if self.selected_view is not None else None
        if bounds is None or self.placing:
            return
        pen = QPen(QColor("#1266bc"), 0, Qt.PenStyle.DashLine)
        self._grip_items.append(graphics.addRect(bounds.adjusted(-1, -1, 1, 1), pen))
        size = 6 / max(abs(self.transform().m11()), 0.01)
        points = {"move": bounds.center(), "scale": bounds.topRight() + QPointF(size, -size)}
        if self.selected_view in self.alignable_views:
            points["alignment"] = bounds.topLeft() + QPointF(-size, -size)
        labels = {
            "move": "拖动视图位置",
            "scale": "拖动等比比例",
            "alignment": "解除 / 恢复父子对齐",
        }
        for mode, point in points.items():
            rect = QRectF(point.x() - size / 2, point.y() - size / 2, size, size)
            self._grips[mode] = rect
            item = graphics.addRect(rect, QPen(QColor("#1266bc"), 0), QColor("#ffffff"))
            item.setZValue(30)
            item.setToolTip(labels[mode])
            self._grip_items.append(item)

    def _pick_view(self, position: QPoint) -> UUID | None:
        for item in self.items(position):
            identity = item.data(0)
            if isinstance(identity, UUID):
                return identity
        point = self.mapToScene(position)
        for identity, bounds in reversed(tuple(self._bounds.items())):
            if bounds.adjusted(-2, -2, 2, 2).contains(point):
                return identity
        return None

    def _pick_curve(self, position: QPoint) -> tuple[UUID, str] | None:
        """Pick a visible stroke within five screen pixels, never a closed path's fill."""
        best: tuple[UUID, str] | None = None
        distance = 5.0
        # QGraphicsPathItem.shape includes closed interiors even with NoBrush.
        # Measure the rendered path in screen coordinates instead of accepting that fill.
        area = QRectF(position.x() - 5, position.y() - 5, 10, 10).toRect()
        for item in self.items(area):
            identity, curve_id = item.data(0), item.data(1)
            if (
                not isinstance(item, QGraphicsPathItem)
                or not isinstance(identity, UUID)
                or not isinstance(curve_id, str)
            ):
                continue
            path = self.viewportTransform().map(item.mapToScene(item.path()))
            for polygon in path.toSubpathPolygons():
                for index in range(1, polygon.count()):
                    a, b = polygon.at(index - 1), polygon.at(index)
                    dx, dy = b.x() - a.x(), b.y() - a.y()
                    length_squared = dx * dx + dy * dy
                    t = (
                        0.0
                        if length_squared == 0
                        else max(
                            0.0,
                            min(
                                1.0,
                                ((position.x() - a.x()) * dx + (position.y() - a.y()) * dy)
                                / length_squared,
                            ),
                        )
                    )
                    candidate = math.hypot(
                        position.x() - a.x() - t * dx, position.y() - a.y() - t * dy
                    )
                    if candidate < distance:
                        distance, best = candidate, (identity, curve_id)
        return best

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.view_selection_guard is not None
            and not self.view_selection_guard(None)
        ):
            event.accept()
            return
        if (
            self.placing
            and not self.annotation_mode
            and not self.note_mode
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.paper_clicked.emit(self.paper_point(event.position()))
            event.accept()
            return
        if self.note_mode and event.button() == Qt.MouseButton.LeftButton:
            self.paper_clicked.emit(self.paper_point(event.position()))
            event.accept()
            return
        if (
            not self.annotation_mode
            and not self.placing
            and event.button() == Qt.MouseButton.LeftButton
            and self.drawing_scene is not None
        ):
            for item in self.items(event.position().toPoint()):
                identity = item.data(3)
                if isinstance(identity, UUID):
                    self.selected_note = identity
                    self.selected_annotation = None
                    self.annotation_selected.emit(None)
                    self.select_view(None)
                    self.note_selected.emit(identity)
                    note = next(n for n in self.drawing_scene.notes if n.note_id == identity)
                    self._drag_note = identity
                    self._drag_start = self.paper_point(event.position())
                    self._drag_anchor = note.position_mm
                    self._drag_started = False
                    self.viewport().grabMouse()
                    event.accept()
                    return
            self.selected_note = None
            self.note_selected.emit(None)
        if self.annotation_mode and event.button() == Qt.MouseButton.LeftButton:
            point = self.paper_point(event.position())
            picked = self._pick_curve(event.position().toPoint())
            if picked is not None:
                self.geometry_clicked.emit(*picked, point)
                event.accept()
                return
            self.paper_clicked.emit(point)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.drawing_scene is not None:
            for item in self.items(event.position().toPoint()):
                identity = item.data(2)
                if isinstance(identity, UUID):
                    self.selected_annotation = identity
                    self.select_view(None)
                    self.annotation_selected.emit(identity)
                    self._drag_annotation = identity
                    self._drag_start = self.paper_point(event.position())
                    annotation = next(
                        a
                        for a in self.drawing_scene.resolved_annotations
                        if a.annotation_id == identity
                    )
                    self._drag_anchor = annotation.position_mm
                    self._drag_started = False
                    self.viewport().grabMouse()
                    event.accept()
                    return
            self.selected_annotation = None
            self.annotation_selected.emit(None)
        if self.placing and event.button() == Qt.MouseButton.LeftButton:
            self.paper_clicked.emit(self.paper_point(event.position()))
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.drawing_scene is not None:
            position = self.mapToScene(event.position().toPoint())
            mode = next(
                (mode for mode, rect in self._grips.items() if rect.contains(position)), None
            )
            identity = self.selected_view if mode else self._pick_view(event.position().toPoint())
            self.select_view(identity)
            if identity is not None:
                if mode == "alignment":
                    self.alignment_requested.emit(identity)
                    event.accept()
                    return
                view = next((v for v in self.drawing_scene.views if v.view_id == identity), None)
                if view is not None:
                    self._drag_view = identity
                    self._drag_mode = mode or "move"
                    self._drag_start = self.paper_point(event.position())
                    self._drag_anchor = view.anchor_mm
                    self._drag_scale = view.scale
                    self._drag_started = False
                    self.viewport().grabMouse()
                    event.accept()
                    return
        super().mousePressEvent(event)

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        point = self.paper_point(event.position())
        if self._drag_note is not None:
            dx, dy = point[0] - self._drag_start[0], point[1] - self._drag_start[1]
            if math.hypot(dx, dy) * abs(self.transform().m11()) > 2:
                self._drag_started = True
            if self._drag_started:
                self._annotation_drag_position = (
                    self._drag_anchor[0] + dx,
                    self._drag_anchor[1] + dy,
                )
                self.note_dragged.emit(self._drag_note, self._annotation_drag_position, False)
            event.accept()
            return
        if self._drag_annotation is not None:
            dx, dy = point[0] - self._drag_start[0], point[1] - self._drag_start[1]
            if math.hypot(dx, dy) * abs(self.transform().m11()) > 2:
                self._drag_started = True
            if self._drag_started:
                self._annotation_drag_position = (
                    self._drag_anchor[0] + dx,
                    self._drag_anchor[1] + dy,
                )
                self.annotation_dragged.emit(
                    self._drag_annotation, self._annotation_drag_position, False
                )
            event.accept()
            return
        if self._drag_view is not None:
            dx, dy = point[0] - self._drag_start[0], point[1] - self._drag_start[1]
            if math.hypot(dx, dy) * abs(self.transform().m11()) > 2:
                self._drag_started = True
            if self._drag_started:
                if self._drag_mode == "scale":
                    before = max(math.dist(self._drag_start, self._drag_anchor), 1e-6)
                    self._drag_value = max(
                        0.001, self._drag_scale * math.dist(point, self._drag_anchor) / before
                    )
                else:
                    self._drag_value = (self._drag_anchor[0] + dx, self._drag_anchor[1] + dy)
                self.view_dragged.emit(self._drag_view, self._drag_mode, self._drag_value, False)
            event.accept()
            return
        self.paper_moved.emit(point)
        super().mouseMoveEvent(event)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_note is not None and event.button() == Qt.MouseButton.LeftButton:
            identity = self._drag_note
            self._drag_note = None
            self.viewport().releaseMouse()
            if self._drag_started:
                self.note_dragged.emit(identity, self._annotation_drag_position, True)
            self._drag_started = False
            event.accept()
            return
        if self._drag_annotation is not None and event.button() == Qt.MouseButton.LeftButton:
            identity = self._drag_annotation
            self._drag_annotation = None
            self.viewport().releaseMouse()
            if self._drag_started:
                self.annotation_dragged.emit(identity, self._annotation_drag_position, True)
            self._drag_started = False
            event.accept()
            return
        if self._drag_view is not None and event.button() == Qt.MouseButton.LeftButton:
            identity = self._drag_view
            self._drag_view = None
            self.viewport().releaseMouse()
            if self._drag_started:
                self.view_dragged.emit(identity, self._drag_mode, self._drag_value, True)
            self._drag_started = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    @override
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.view_selection_guard is not None
            and not self.view_selection_guard(None)
        ):
            event.accept()
            return
        if self.note_mode or self.annotation_mode or self.placing:
            event.accept()
            return
        for item in self.items(event.position().toPoint()):
            identity = item.data(3)
            if isinstance(identity, UUID):
                self.cancel_drag()
                self.selected_note = identity
                self.note_selected.emit(identity)
                self.note_edit_requested.emit(identity)
                event.accept()
                return
        for item in self.items(event.position().toPoint()):
            identity = item.data(2)
            if isinstance(identity, UUID):
                self.cancel_drag()
                self.selected_annotation = identity
                self.annotation_selected.emit(identity)
                self.annotation_edit_requested.emit(identity)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def cancel_drag(self) -> None:
        if (
            self._drag_view is not None
            or self._drag_annotation is not None
            or self._drag_note is not None
        ):
            self._drag_view = None
            self._drag_annotation = None
            self._drag_note = None
            self._drag_started = False
            self.viewport().releaseMouse()
            self.drag_cancelled.emit()

    @override
    def hideEvent(self, event: QHideEvent) -> None:
        self.cancel_drag()
        super().hideEvent(event)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.commit_requested.emit()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancel_drag()
            self.cancel_requested.emit()
        elif event.key() == Qt.Key.Key_Delete:
            if self.selected_note is not None:
                self.note_delete_requested.emit()
            elif self.selected_annotation is not None:
                self.annotation_delete_requested.emit()
            else:
                self.delete_requested.emit()
        else:
            super().keyPressEvent(event)

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self._draw_grips()
        event.accept()
