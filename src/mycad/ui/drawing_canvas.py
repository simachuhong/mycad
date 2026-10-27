# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Paper-space canvas. Mouse points are paper millimetres, positive Y upwards."""

from __future__ import annotations

import math
from typing import override

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainterPath,
    QPen,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from mycad.core.drawing_projection import (
    ArcCurve,
    CurveGeometry,
    DrawingScene,
    EllipseCurve,
    LineCurve,
    Point2,
)


def curve_path(curve: CurveGeometry) -> QPainterPath:
    path = QPainterPath()
    if isinstance(curve, LineCurve):
        path.moveTo(curve.start[0], -curve.start[1])
        path.lineTo(curve.end[0], -curve.end[1])
        return path
    if isinstance(curve, ArcCurve | EllipseCurve):
        rx = curve.radius if isinstance(curve, ArcCurve) else curve.major_radius
        ry = curve.radius if isinstance(curve, ArcCurve) else curve.minor_radius
        rotation = 0 if isinstance(curve, ArcCurve) else math.radians(curve.rotation_deg)
        # Cubic Bezier conic rendering; exact DTO remains the export truth.
        segments = max(1, math.ceil(abs(curve.sweep_deg) / 90))
        step = math.radians(curve.sweep_deg) / segments

        def point(t: float) -> QPointF:
            x, y = rx * math.cos(t), ry * math.sin(t)
            return QPointF(
                curve.center[0] + x * math.cos(rotation) - y * math.sin(rotation),
                -(curve.center[1] + x * math.sin(rotation) + y * math.cos(rotation)),
            )

        def tangent(t: float) -> QPointF:
            x, y = -rx * math.sin(t), ry * math.cos(t)
            return QPointF(
                x * math.cos(rotation) - y * math.sin(rotation),
                -(x * math.sin(rotation) + y * math.cos(rotation)),
            )

        t = math.radians(curve.start_deg)
        path.moveTo(point(t))
        for _ in range(segments):
            k = 4 / 3 * math.tan(step / 4)
            end = t + step
            path.cubicTo(point(t) + tangent(t) * k, point(end) - tangent(end) * k, point(end))
            t = end
        return path
    # Rational de Boor evaluation for display; no modification to exact spline data.
    knots = tuple(
        k for k, m in zip(curve.knots, curve.multiplicities, strict=True) for _ in range(m)
    )
    n, p = len(curve.poles) - 1, curve.degree
    if curve.periodic:
        raise ValueError("周期样条需要先规范化为非周期精确曲线")

    def evaluate(u: float) -> Point2:
        span = (
            n
            if u >= knots[n + 1]
            else next(i for i in range(p, n + 1) if knots[i] <= u < knots[i + 1])
        )
        d = [
            [
                curve.poles[j][0] * curve.weights[j],
                curve.poles[j][1] * curve.weights[j],
                curve.weights[j],
            ]
            for j in range(span - p, span + 1)
        ]
        for r in range(1, p + 1):
            for j in range(p, r - 1, -1):
                i = span - p + j
                denom = knots[i + p - r + 1] - knots[i]
                a = (u - knots[i]) / denom if denom else 0
                d[j] = [(1 - a) * x + a * y for x, y in zip(d[j - 1], d[j], strict=True)]
        return d[p][0] / d[p][2], d[p][1] / d[p][2]

    points = tuple(evaluate(knots[p] + (knots[n + 1] - knots[p]) * i / 160) for i in range(161))
    path.moveTo(points[0][0], -points[0][1])
    for x, y in points[1:]:
        path.lineTo(x, -y)
    return path


class DrawingCanvas(QGraphicsView):
    paper_clicked = Signal(object)
    paper_moved = Signal(object)
    commit_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setMouseTracking(True)
        self.setBackgroundBrush(QColor("#dce1e7"))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.drawing_scene: DrawingScene | None = None
        self.placing = False
        self._needs_fit = True

    def clear_scene(self) -> None:
        self.drawing_scene = None
        self._needs_fit = True
        graphics = self.scene()
        graphics.clear()
        graphics.setSceneRect(0, 0, 297, 210)

    def set_scene(self, scene: DrawingScene) -> None:
        first = self.drawing_scene is None or self.drawing_scene.sheet_id != scene.sheet_id
        self.drawing_scene = scene
        graphics = self.scene()
        assert graphics is not None
        graphics.clear()
        w, h = scene.size_mm
        paper = graphics.addRect(0, -h, w, h, QPen(QColor("#929ba5"), 0.15), QColor("white"))
        paper.setZValue(-10)
        m = scene.margin_mm
        graphics.addRect(m, -h + m, w - 2 * m, h - 2 * m, QPen(QColor("#303942"), 0.3))
        if scene.title:
            box_height = max(16, 5 * len(scene.title) + 5)
            graphics.addRect(
                w - m - 90, -m - box_height, 90, box_height, QPen(QColor("#303942"), 0.25)
            )
            font = QFont("sans-serif")
            font.setPointSizeF(2.5)
            for index, (key, value) in enumerate(scene.title):
                text = graphics.addText(f"{key}：{value}", font)
                text.setTextWidth(86)
                text.setPos(w - m - 88, -m - box_height + 2 + index * 5)
        for view in scene.views:
            for curve in view.curves:
                pen = QPen(QColor("#26313c"), 0.25 / view.scale)
                if curve.visibility == "hidden":
                    pen.setStyle(Qt.PenStyle.DashLine)
                    pen.setColor(QColor("#687789"))
                elif curve.visibility == "tangent":
                    pen.setStyle(Qt.PenStyle.DotLine)
                try:
                    path = curve_path(curve.geometry)
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
        graphics.setSceneRect(-8, -h - 8, w + 16, h + 16)
        if first:
            self._needs_fit = True
            if self.isVisible():
                self.fit_view()

    def fit_view(self) -> None:
        self._needs_fit = False
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    @override
    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._needs_fit and self.drawing_scene is not None:
            QTimer.singleShot(0, self, self.fit_view)

    def paper_point(self, point: QPointF) -> Point2:
        mapped = self.mapToScene(point.toPoint())
        return mapped.x(), -mapped.y()

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.paper_moved.emit(self.paper_point(event.position()))
        super().mouseMoveEvent(event)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.placing and event.button() == Qt.MouseButton.LeftButton:
            self.paper_clicked.emit(self.paper_point(event.position()))
            event.accept()
            return
        super().mousePressEvent(event)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.commit_requested.emit()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
        else:
            super().keyPressEvent(event)

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        event.accept()
