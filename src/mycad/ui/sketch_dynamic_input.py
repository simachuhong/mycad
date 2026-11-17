# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Resolve exact dimensions for interactive part-sketch geometry."""

from functools import partial
from math import atan2, copysign, cos, degrees, hypot, isfinite, radians, sin
from typing import Literal

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QWidget


def resolve_dynamic_point(
    tool: Literal["line", "rectangle", "circle"],
    start: tuple[float, float],
    cursor: tuple[float, float],
    *,
    length: float | None = None,
    angle_deg: float | None = None,
    width: float | None = None,
    height: float | None = None,
    radius: float | None = None,
) -> tuple[float, float]:
    """Apply locked dimensions to the current local-plane pointer position."""
    for value in (length, width, height, radius):
        if value is not None and (not isfinite(value) or value <= 0):
            raise ValueError("尺寸必须是大于零的有限数值。")
    if angle_deg is not None and not isfinite(angle_deg):
        raise ValueError("角度必须是有限数值。")
    dx, dy = cursor[0] - start[0], cursor[1] - start[1]
    if tool == "rectangle":
        return (
            start[0] + (copysign(width, dx) if width is not None else dx),
            start[1] + (copysign(height, dy) if height is not None else dy),
        )
    distance = length if tool == "line" else radius
    if distance is None and angle_deg is None:
        return cursor
    distance = hypot(dx, dy) if distance is None else distance
    angle = radians(angle_deg) if angle_deg is not None else atan2(dy, dx)
    return (start[0] + distance * cos(angle), start[1] + distance * sin(angle))


class _DynamicField(QDoubleSpinBox):
    escape_pressed = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class SketchDynamicInput(QWidget):
    """Dimension fields for the current unfinished part-sketch entity."""

    changed = Signal()
    escape_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tool = "select"
        self.first_label = QLabel(self)
        self.second_label = QLabel(self)
        self.first_value = self._field()
        self.second_value = self._field()
        self.first_lock = QCheckBox("锁定", self)
        self.second_lock = QCheckBox("锁定", self)
        self.circle_mode = QComboBox(self)
        self.circle_mode.setAccessibleName("圆尺寸模式")
        self.circle_mode.addItems(("半径", "直径"))
        self._circle_mode_index = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        for widget in (
            self.first_label,
            self.circle_mode,
            self.first_value,
            self.first_lock,
            self.second_label,
            self.second_value,
            self.second_lock,
        ):
            layout.addWidget(widget)
        layout.addStretch()
        for field, lock in (
            (self.first_value, self.first_lock),
            (self.second_value, self.second_lock),
        ):
            field.valueChanged.connect(self.changed)
            field.lineEdit().textEdited.connect(partial(self._lock_on_edit, lock))
            field.escape_pressed.connect(self.escape_requested)
            lock.toggled.connect(self.changed)
        self.circle_mode.currentIndexChanged.connect(self._circle_mode_changed)
        self.configure("select")

    @staticmethod
    def _lock_on_edit(lock: QCheckBox, _text: str) -> None:
        lock.setChecked(True)

    def _circle_mode_changed(self, index: int) -> None:
        if self.first_lock.isChecked() and index != self._circle_mode_index:
            factor = 2.0 if index == 1 else 0.5
            with QSignalBlocker(self.first_value):
                self.first_value.setValue(self.first_value.value() * factor)
        self._circle_mode_index = index
        self.changed.emit()

    def _field(self) -> _DynamicField:
        field = _DynamicField(self)
        field.setDecimals(6)
        field.setRange(-1e9, 1e9)
        field.setMaximumWidth(110)
        return field

    def configure(self, tool: str) -> None:
        self.clear_locks()
        self._tool = tool
        line = tool in ("line", "continuous")
        circle = tool == "circle"
        arc_angle = tool == "arc_angle"
        self.setVisible(line or circle or arc_angle or tool == "rectangle")
        self.first_label.setText(
            "角度" if arc_angle else "长度" if line else "宽" if tool == "rectangle" else ""
        )
        self.second_label.setText("角度" if line else "高")
        first_name = (
            "角度" if arc_angle else "长度" if line else "宽度" if tool == "rectangle" else "圆尺寸"
        )
        second_name = "角度" if line else "高度"
        self.first_value.setAccessibleName(first_name)
        self.first_lock.setAccessibleName(f"锁定{first_name}")
        self.second_value.setAccessibleName(second_name)
        self.second_lock.setAccessibleName(f"锁定{second_name}")
        self.first_value.setSuffix(" °" if arc_angle else " mm")
        self.second_value.setSuffix(" °" if line else " mm")
        self.circle_mode.setVisible(circle)
        for widget in (self.second_label, self.second_value, self.second_lock):
            widget.setVisible(not (circle or arc_angle))

    def clear_locks(self) -> None:
        self.first_lock.setChecked(False)
        self.second_lock.setChecked(False)

    def resolve(
        self, start: tuple[float, float], cursor: tuple[float, float]
    ) -> tuple[float, float]:
        for field, lock in (
            (self.first_value, self.first_lock),
            (self.second_value, self.second_lock),
        ):
            if lock.isChecked() and not field.hasAcceptableInput():
                raise ValueError("请输入有效的尺寸。")
        first = self.first_value.value() if self.first_lock.isChecked() else None
        second = self.second_value.value() if self.second_lock.isChecked() else None
        if self._tool in ("line", "continuous"):
            return resolve_dynamic_point("line", start, cursor, length=first, angle_deg=second)
        if self._tool == "arc_angle":
            return resolve_dynamic_point("line", start, cursor, angle_deg=first)
        if self._tool == "rectangle":
            return resolve_dynamic_point("rectangle", start, cursor, width=first, height=second)
        if self._tool == "circle":
            radius = (
                first / 2 if first is not None and self.circle_mode.currentIndex() == 1 else first
            )
            return resolve_dynamic_point("circle", start, cursor, radius=radius)
        return cursor

    def update_from_pointer(self, start: tuple[float, float], point: tuple[float, float]) -> None:
        dx, dy = point[0] - start[0], point[1] - start[1]
        if self._tool in ("line", "continuous"):
            values = (hypot(dx, dy), degrees(atan2(dy, dx)))
        elif self._tool == "arc_angle":
            values = (degrees(atan2(dy, dx)), 0.0)
        elif self._tool == "rectangle":
            values = (abs(dx), abs(dy))
        else:
            values = (hypot(dx, dy) * (2 if self.circle_mode.currentIndex() == 1 else 1), 0.0)
        for field, lock, value in zip(
            (self.first_value, self.second_value),
            (self.first_lock, self.second_lock),
            values,
            strict=True,
        ):
            if not lock.isChecked():
                with QSignalBlocker(field):
                    field.setValue(value)
