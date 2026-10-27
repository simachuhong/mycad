# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Mouse-transparent, scale-independent orientation and world-origin cues."""

from __future__ import annotations

from collections.abc import Callable
from math import hypot
from typing import override

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QMatrix4x4, QPainter, QPaintEvent, QPen, QPolygonF, QVector3D
from PySide6.QtWidgets import QWidget

from mycad.ui.theme import ThemeName, theme_tokens

AxisVector = tuple[float, float, float]


class CoordinateIndicator(QWidget):
    """Orientation is always visible; the optional O marker is the real origin."""

    axis_labels = ("X", "Y", "Z")

    def __init__(
        self,
        parent: QWidget,
        view_matrix: Callable[[], QMatrix4x4],
        project_origin: Callable[[], tuple[float, float] | None],
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("全局 XYZ 方向指示器")
        self._view_matrix = view_matrix
        self._project_origin = project_origin
        self._theme: ThemeName = "light"
        self.origin_visible = False
        self._scene_key: object = None
        self.show()

    def axis_vectors(self) -> tuple[AxisVector, ...]:
        """Use the actual camera rotation, with screen Y pointing down."""
        matrix = self._view_matrix()
        vectors = (matrix.mapVector(QVector3D(*axis)) for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
        return tuple((v.x(), -v.y(), v.z()) for v in vectors)

    def set_theme(self, theme: ThemeName) -> None:
        self._theme = theme
        self.update()

    def set_origin_visible(self, visible: bool) -> None:
        self.origin_visible = visible
        self.update()

    def sync_scene(self) -> None:
        """Refresh only on camera/size changes, avoiding a GL repaint loop."""
        parent = self.parentWidget()
        if parent is None:
            return
        if self.geometry() != parent.rect():
            self.setGeometry(parent.rect())
        key = (self.axis_vectors(), self._project_origin(), self.size())
        if key != self._scene_key:
            self._scene_key = key
            self.update()

    def _draw_triad(self, painter: QPainter, center: QPointF, length: float) -> None:
        colors = (
            ("#BD323A", "#147D46", "#245FCC")
            if self._theme == "light"
            else ("#FF8189", "#68D49A", "#84B2FF")
        )
        vectors = self.axis_vectors()
        # Draw nearer axes last. Letters and arrowheads supplement colour.
        for index in sorted(range(3), key=lambda i: vectors[i][2]):
            x, y, z = vectors[index]
            color = QColor(colors[index])
            painter.setPen(QPen(color, 2.2))
            painter.setBrush(color)
            magnitude = hypot(x, y)
            if magnitude < 0.08:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(center, 5, 5)
                if z > 0:
                    painter.setBrush(color)
                    painter.drawEllipse(center, 1.6, 1.6)
                else:
                    painter.drawLine(center + QPointF(-3, -3), center + QPointF(3, 3))
                    painter.drawLine(center + QPointF(-3, 3), center + QPointF(3, -3))
                label = center + QPointF(11, -10)
            else:
                end = center + QPointF(x * length, y * length)
                unit = QPointF(x / magnitude, y / magnitude)
                normal = QPointF(-unit.y(), unit.x())
                painter.drawLine(center, end)
                painter.drawPolygon(
                    QPolygonF([end, end - unit * 7 + normal * 3, end - unit * 7 - normal * 3])
                )
                label = end + unit * 14
            painter.drawText(
                QRectF(label.x() - 9, label.y() - 9, 18, 18),
                Qt.AlignmentFlag.AlignCenter,
                self.axis_labels[index],
            )

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tokens = theme_tokens(self._theme)
        # Logical pixels keep the cue consistent at all camera distances / DPI.
        panel = QRectF(8, max(4, self.height() - 164), 148, 156)
        painter.setPen(QPen(QColor(tokens.divider), 1))
        background = QColor(tokens.panel)
        background.setAlpha(235)
        painter.setBrush(background)
        painter.drawRoundedRect(panel, 9, 9)
        painter.setPen(QColor(tokens.secondary_text))
        painter.drawText(panel.adjusted(10, 7, -10, -125), Qt.AlignmentFlag.AlignLeft, "全局 XYZ")
        font = painter.font()
        font.setPointSizeF(10)
        font.setBold(True)
        painter.setFont(font)
        self._draw_triad(painter, QPointF(panel.center().x(), panel.top() + 88), 42)
        origin = self._project_origin() if self.origin_visible else None
        if origin is not None:
            point = QPointF(*origin)
            safe = QRectF(self.rect()).adjusted(80, 80, -80, -80)
            if safe.contains(point) and not panel.adjusted(-60, -60, 60, 60).contains(point):
                self._draw_triad(painter, point, 32)
                painter.setPen(QColor(tokens.text))
                painter.drawText(point + QPointF(-30, 65), "O (0, 0, 0)")
        painter.end()
