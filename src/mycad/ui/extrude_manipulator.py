# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""A projected normal handle with local gestures and unobtrusive distance input."""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QLocale, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QDoubleValidator,
    QFocusEvent,
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QLineEdit, QWidget

from mycad.core.viewport_protocol import PlanarFaceFrame, Point3
from mycad.ui.modeling_handles import DimensionHandle, cross

ScreenPoint = tuple[float, float]
ProjectPoint = Callable[[Point3], ScreenPoint | None]
CameraRay = Callable[[float, float], tuple[Point3, Point3] | None]


def axis_parameter(frame: PlanarFaceFrame, ray: tuple[Point3, Point3]) -> float | None:
    """Closest point on the normal axis to a camera ray, in signed millimetres."""
    origin, direction = ray
    offset = tuple(origin[i] - frame.origin[i] for i in range(3))
    alignment = sum(frame.normal[i] * direction[i] for i in range(3))
    denominator = 1.0 - alignment * alignment
    # Looking almost along the axis is ill-conditioned; do not invent a 2D axis.
    if denominator < 0.0025:
        return None
    normal_offset = sum(frame.normal[i] * offset[i] for i in range(3))
    ray_offset = sum(direction[i] * offset[i] for i in range(3))
    return (normal_offset - alignment * ray_offset) / denominator


class _DistanceEdit(QLineEdit):
    accepted = Signal()
    cancelled = Signal()
    editing_started = Signal()
    focus_left = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accepted.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        # QObject event filters are unnecessary: input ownership is local here.
        self.editing_started.emit()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.focus_left.emit()


class _HandleCanvas(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.base = QPointF()
        self.anchor = QPointF()
        self.tip = QPointF()
        self.arc: list[QPointF] = []
        self.label = "距离"
        self.axis_visible = False
        self.hot = False
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#326CB5"), 1.5, Qt.PenStyle.DashLine))
        painter.drawLine(self.base, self.anchor)
        for first, second in zip(self.arc, self.arc[1:], strict=False):
            painter.drawLine(first, second)
        painter.drawText(self.tip + QPointF(10, -10), self.label)
        color = QColor("#E28B17" if self.hot else "#1665B3")
        painter.setPen(QPen(QColor("white"), 6.0))
        if self.axis_visible:
            painter.drawLine(self.anchor, self.tip)
        painter.setPen(QPen(color, 3.0))
        if self.axis_visible:
            painter.drawLine(self.anchor, self.tip)
            delta = self.tip - self.anchor
            length = math.hypot(delta.x(), delta.y())
            ux, uy = delta.x() / length, delta.y() / length
            for side in (-1, 1):
                painter.drawLine(
                    self.tip,
                    self.tip - QPointF(ux * 12 + side * uy * 7, uy * 12 - side * ux * 7),
                )
        painter.setBrush(QColor("white"))
        painter.drawEllipse(self.anchor, 5.0, 5.0)
        if not self.axis_visible:
            painter.drawEllipse(self.anchor, 10.0, 10.0)
        painter.end()


class ExtrudeManipulator(QObject):
    """Own only transient interaction; the window owns previews and commits."""

    distance_changed = Signal(float)
    input_validity_changed = Signal(bool)
    toolbar_input_requested = Signal(str)
    hint_changed = Signal(str)

    def __init__(self, parent: QWidget, project: ProjectPoint, camera_ray: CameraRay) -> None:
        super().__init__(parent)
        self._host = parent
        self._project = project
        self._camera_ray = camera_ray
        self._frame: PlanarFaceFrame | None = None
        self._dimension: DimensionHandle | None = None
        self._bounds: tuple[Point3, ...] = ()
        self._value = 0.0
        self._locked = False
        self._press: ScreenPoint | None = None
        self._following = False
        self._moved = False
        self._start_parameter: float | None = None
        self._start_value = 0.0
        self._gesture_value = 0.0
        self._editing = False
        self._edit_value = 0.0
        self._input_valid = True
        self._projection_signature: tuple[ScreenPoint | None, ...] | None = None
        self._canvas = _HandleCanvas(parent)
        self._edit = _DistanceEdit(parent)
        self._edit.setObjectName("extrudeDynamicDistance")
        self._edit.setAccessibleName("沿拉伸方向的距离，毫米")
        self._edit.setFixedSize(130, 30)
        self._edit.setToolTip("距离 mm：正值外拉，负值内推；Enter 定距，Esc 恢复")
        self._edit.setStyleSheet(
            "QLineEdit {background:#FFFFFF; color:#163B65; border:1px solid #2774C5;"
            "border-radius:3px; padding:3px;}"
        )
        validator = QDoubleValidator(-1_000_000.0, 1_000_000.0, 3, self._edit)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        validator.setLocale(QLocale.c())
        self._edit.setValidator(validator)
        self._edit.textEdited.connect(self._text_edited)
        self._edit.editing_started.connect(self._begin_edit)
        self._edit.focus_left.connect(self._finish_edit_on_blur)
        self._edit.accepted.connect(self.accept_input)
        self._edit.cancelled.connect(self.cancel_input)
        self._edit.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.refresh)

    @property
    def dimension(self) -> DimensionHandle | None:
        return self._dimension

    @property
    def active(self) -> bool:
        return self._frame is not None

    @property
    def adjusting(self) -> bool:
        return self._following or self._press is not None

    @property
    def input_valid(self) -> bool:
        return self._input_valid

    def configure(
        self, frame: PlanarFaceFrame, distance: float, bounds: tuple[Point3, ...]
    ) -> None:
        self.clear()
        self._dimension = DimensionHandle("distance", "距离", frame, minimum=-1_000_000.0)
        self._frame = frame
        self._canvas.label = "距离 mm"
        validator = self._edit.validator()
        if isinstance(validator, QDoubleValidator):
            validator.setRange(-1_000_000.0, 1_000_000.0, 3)
        self._bounds = bounds
        self._value = distance
        self._edit.setEnabled(True)
        self._edit.setText(f"{distance:.3f}")
        self._canvas.show()
        self._timer.start()
        self.refresh()

    def configure_dimension(
        self, dimension: DimensionHandle, value: float, bounds: tuple[Point3, ...]
    ) -> None:
        if self._dimension == dimension and self.active:
            self.set_distance(value)
            return
        self.configure(dimension.frame, value, bounds)
        self._dimension = dimension
        self._canvas.label = dimension.label + (" °" if dimension.angular else " mm")
        self._edit.setAccessibleName(self._canvas.label)
        self._edit.setToolTip(f"{self._canvas.label}；Enter 接受尺寸，Esc 恢复")
        validator = self._edit.validator()
        if isinstance(validator, QDoubleValidator):
            validator.setRange(dimension.minimum, dimension.maximum, 3)
        self.refresh()

    def clear(self) -> None:
        self._timer.stop()
        self._frame = None
        self._dimension = None
        self._canvas.arc = []
        self._press = None
        self._following = False
        self._editing = False
        self._locked = False
        self._input_valid = True
        self._projection_signature = None
        self._canvas.hide()
        self._edit.hide()
        self._host.unsetCursor()

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self._edit.setEnabled(not locked)
        if locked:
            self.finish_gesture()
            self._editing = False

    def set_distance(self, value: float) -> None:
        self._value = value
        if not self._editing:
            self._edit.setText(f"{value:.3f}")
        self.refresh()

    def set_bounds(self, bounds: tuple[Point3, ...]) -> None:
        self._bounds = bounds
        self.refresh()

    def _parameter_at(self, point: ScreenPoint) -> float | None:
        ray = self._camera_ray(*point)
        frame, dimension = self._frame, self._dimension
        if frame is None or ray is None or dimension is None:
            return None
        if not dimension.angular:
            value = axis_parameter(frame, ray)
            return None if value is None else value / dimension.scale
        denominator = sum(frame.normal[i] * ray[1][i] for i in range(3))
        if abs(denominator) < 0.05:
            return None
        t = sum((frame.origin[i] - ray[0][i]) * frame.normal[i] for i in range(3)) / denominator
        if t < 0:
            return None
        vector = tuple(ray[0][i] + ray[1][i] * t - frame.origin[i] for i in range(3))
        if sum(v * v for v in vector) < 1e-8:
            return None
        tangent = cross(frame.normal, dimension.radial)
        return math.degrees(
            math.atan2(
                sum(vector[i] * tangent[i] for i in range(3)),
                sum(vector[i] * dimension.radial[i] for i in range(3)),
            )
        )

    def _publish(self, value: float) -> None:
        dimension = self._dimension
        if dimension is None:
            return
        value = round(max(dimension.minimum, min(dimension.maximum, value)), 3)
        self._value = value
        if not self._editing:
            self._edit.setText(f"{value:.3f}")
        self.distance_changed.emit(value)
        self.refresh()

    def rebase(self, point: ScreenPoint) -> None:
        """After navigation, use the new camera without changing the distance."""
        self._start_parameter = self._parameter_at(point)
        self._start_value = self._value

    def hit(self, point: ScreenPoint) -> bool:
        if not self.active or self._locked:
            return False
        self.refresh()
        if self._canvas.isHidden():
            return False
        a, b = self._canvas.anchor, self._canvas.tip
        dx, dy = b.x() - a.x(), b.y() - a.y()
        denominator = dx * dx + dy * dy
        ratio = (
            0.0
            if denominator == 0
            else max(
                0.0, min(1.0, ((point[0] - a.x()) * dx + (point[1] - a.y()) * dy) / denominator)
            )
        )
        return math.hypot(point[0] - a.x() - ratio * dx, point[1] - a.y() - ratio * dy) <= 10

    def press(self, point: ScreenPoint) -> bool:
        if not self.active or self._locked:
            return False
        if self._following:
            self.finish_gesture()
            return True
        if not self.hit(point):
            if self._editing:
                self.cancel_input()
            return False
        if self._editing:
            self.accept_input()
            if not self._input_valid:
                return True
        if not self._canvas.axis_visible:
            self.hint_changed.emit("当前视角无法可靠拖动此尺寸；请旋转视图或直接输入数值。")
            self.start_input("")
            return True
        self._press = point
        self._moved = False
        self._gesture_value = self._value
        self.rebase(point)
        self._canvas.hot = True
        self._host.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.hint_changed.emit("拖动尺寸手柄；单击/松开定值，直接键入数值，Esc 恢复。")
        return True

    def move(self, point: ScreenPoint) -> bool:
        if not self.active or self._locked:
            return False
        if self.adjusting:
            self.refresh()
            if self._press is not None:
                if math.dist(point, self._press) <= 3 and not self._moved:
                    return True
                self._moved = True
            parameter = self._parameter_at(point)
            if self._start_parameter is None:
                self.rebase(point)
                return True
            if parameter is not None:
                delta = parameter - self._start_parameter
                if self._dimension is not None and self._dimension.angular:
                    delta = (delta + 180.0) % 360.0 - 180.0
                    self._start_parameter = parameter
                    self._start_value = self._value
                self._publish(self._start_value + delta)
            return True
        hot = self.hit(point)
        self._canvas.hot = hot
        if hot:
            self._host.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self._host.unsetCursor()
        return hot

    def release(self) -> bool:
        if self._press is None:
            return False
        self._press = None
        if self._moved:
            self.finish_gesture()
        else:
            self._following = True
        return True

    def finish_gesture(self) -> None:
        self._press = None
        self._following = False
        self._canvas.hot = False
        self._host.unsetCursor()
        self.hint_changed.emit("尺寸已确定；可继续选择或旋转，预览就绪后右键/应用提交。")

    def cancel_gesture(self) -> None:
        self.finish_gesture()
        self._publish(self._gesture_value)

    def _begin_edit(self) -> None:
        if not self._editing:
            self._edit_value = self._value
            self._editing = True
            self.finish_gesture()

    def start_input(self, text: str) -> None:
        if not self.active or self._locked:
            return
        if self._edit.isHidden():
            self.finish_gesture()
            self.toolbar_input_requested.emit(text)
            return
        self._edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self._edit.selectAll()
        if text:
            self._edit.setText(text)
            self._text_edited(text)

    def _text_edited(self, text: str) -> None:
        self._begin_edit()
        try:
            value = float(text)
        except ValueError:
            value = 0.0
        valid = (
            self._edit.hasAcceptableInput()
            and math.isfinite(value)
            and (
                value != 0
                or (self._dimension is not None and self._dimension.key == "start_angle_deg")
            )
        )
        self._input_valid = valid
        self.input_validity_changed.emit(valid)
        if valid:
            self._publish(value)
        else:
            self.hint_changed.emit("请输入此尺寸允许范围内的数值；输入完成前不能确认。")

    def accept_input(self) -> None:
        self._text_edited(self._edit.text())
        if self._input_valid:
            self._editing = False
            self.finish_gesture()
            self._host.setFocus(Qt.FocusReason.OtherFocusReason)

    def cancel_input(self) -> None:
        self._editing = False
        self._input_valid = True
        self.input_validity_changed.emit(True)
        self._publish(self._edit_value)
        self._host.setFocus(Qt.FocusReason.OtherFocusReason)

    def _finish_edit_on_blur(self) -> None:
        if not self._editing:
            return
        self._editing = False
        if not self._input_valid:
            self._input_valid = True
            self.input_validity_changed.emit(True)
            self._publish(self._edit_value)
        self._edit.setText(f"{self._value:.3f}")

    def handle_key(self, event: QKeyEvent) -> bool:
        if not self.active or self._locked:
            return False
        if event.key() == Qt.Key.Key_Escape:
            if self._editing:
                self.cancel_input()
                return True
            if self.adjusting:
                self.cancel_gesture()
                return True
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.adjusting:
            self.finish_gesture()
            return True
        text = event.text()
        if event.key() == Qt.Key.Key_D:
            self.start_input("")
            return True
        if len(text) == 1 and (text.isdigit() or text in "+-."):
            self.start_input(text)
            return True
        return False

    def refresh(self) -> None:
        frame = self._frame
        if frame is None:
            return
        signature = (
            self._project(frame.origin),
            self._project(tuple_add(frame.origin, frame.normal)),
            self._project(tuple_add(frame.origin, self._dimension.radial))
            if self._dimension is not None
            else None,
        )
        if signature != self._projection_signature and self.adjusting:
            self._start_parameter = None
        self._projection_signature = signature
        dimension = self._dimension
        if dimension is None:
            return
        self._canvas.arc = []
        if dimension.angular:
            tangent = cross(frame.normal, dimension.radial)

            def ring_point(degrees: float) -> Point3:
                angle = math.radians(degrees)
                vector = tuple(
                    frame.origin[i]
                    + dimension.ring_radius
                    * (dimension.radial[i] * math.cos(angle) + tangent[i] * math.sin(angle))
                    for i in range(3)
                )
                return vector[0], vector[1], vector[2]

            world_end, after = ring_point(self._value), ring_point(self._value + 1.0)
            for step in range(73):
                projected = self._project(ring_point(step * 5.0))
                if projected is not None:
                    self._canvas.arc.append(QPointF(*projected))
        else:
            end = tuple(
                frame.origin[i] + frame.normal[i] * self._value * dimension.scale for i in range(3)
            )
            world_end = (end[0], end[1], end[2])
            after = tuple_add(world_end, frame.normal)
        base, anchor, beyond = (self._project(point) for point in (frame.origin, world_end, after))
        if base is None or anchor is None or beyond is None:
            self._canvas.hide()
            self._edit.hide()
            return
        self._canvas.setGeometry(self._host.rect())
        self._canvas.show()
        dx, dy = beyond[0] - anchor[0], beyond[1] - anchor[1]
        length = math.hypot(dx, dy)
        self._canvas.axis_visible = length > 1e-5 and self._parameter_at(anchor) is not None
        ux, uy = (dx / length, dy / length) if length > 1e-5 else (0.0, -1.0)
        # Keep the action target accessible when a large extent leaves the screen.
        width, height = self._host.width(), self._host.height()
        ax = max(72.0, min(width - 72.0, anchor[0]))
        ay = max(72.0, min(height - 72.0, anchor[1]))
        self._canvas.base = QPointF(*base)
        self._canvas.anchor = QPointF(ax, ay)
        self._canvas.tip = (
            QPointF(ax + ux * 55, ay + uy * 55) if self._canvas.axis_visible else QPointF(ax, ay)
        )
        self._canvas.raise_()
        self._canvas.update()
        self._edit.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, self.adjusting)
        self._position_input()
        self._edit.raise_()

    def _position_input(self) -> None:
        # A conservative projected model box keeps the editor out of the model.
        points = [point for corner in self._bounds if (point := self._project(corner)) is not None]
        points.append((self._canvas.anchor.x(), self._canvas.anchor.y()))
        if points:
            xs, ys = zip(*points, strict=True)
            model = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)).adjusted(
                -8, -8, 8, 8
            )
        else:
            model = QRectF()
        x, y = self._canvas.tip.x(), self._canvas.tip.y()
        w, h = self._edit.width(), self._edit.height()
        width, height = self._host.width(), self._host.height()
        candidates = (
            (x + 14, y + 12),
            (x - w - 14, y + 12),
            (x + 14, y - h - 12),
            (width - w - 10, 10),
            (10, 10),
            (width - w - 10, height - h - 10),
            (10, height - h - 10),
        )
        for px, py in candidates:
            rect = QRectF(max(4, min(width - w - 4, px)), max(4, min(height - h - 4, py)), w, h)
            if not rect.intersects(model):
                self._edit.move(round(rect.x()), round(rect.y()))
                self._edit.show()
                return
        if self._editing:
            text = self._edit.text()
            self._editing = False
            self._input_valid = True
            self.toolbar_input_requested.emit(text)
        self._edit.hide()


def tuple_add(left: Point3, right: Point3) -> Point3:
    return left[0] + right[0], left[1] + right[1], left[2] + right[2]
