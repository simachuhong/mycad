# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Interactive 2D command input and explicit planar coordinate parsing."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING, cast, override

from PySide6.QtCore import QCoreApplication, QEvent, Qt, Signal
from PySide6.QtGui import QInputMethodEvent, QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QWidget

from mycad.core.sketch import Point2D

if TYPE_CHECKING:
    from mycad.ui.sketch_editor import SketchCanvas


def parse_coordinate(text: str, base: Point2D | None) -> Point2D:
    """Parse absolute or @relative Cartesian/polar input in sketch units and degrees."""
    value = text.strip()
    relative = value.startswith("@")
    if relative:
        value = value[1:]
        if base is None:
            raise ValueError("相对坐标需要先指定基点。")
    origin = base if relative and base is not None else (0.0, 0.0)
    separator = "<" if "<" in value else ","
    parts = value.split(separator)
    if len(parts) != 2 or any(not item.strip() for item in parts):
        raise ValueError("请输入 x,y、@dx,dy 或距离<角度。")
    try:
        first, second = (float(item.strip()) for item in parts)
    except ValueError as exc:
        raise ValueError("坐标必须是有效数值。") from exc
    if not math.isfinite(first) or not math.isfinite(second):
        raise ValueError("坐标必须是有限数值。")
    if separator == "<":
        if first < 0:
            raise ValueError("极坐标距离不能为负。")
        angle = math.radians(second)
        first, second = first * math.cos(angle), first * math.sin(angle)
    result = (origin[0] + first, origin[1] + second)
    if not all(math.isfinite(component) for component in result):
        raise ValueError("坐标超出可用范围。")
    return result


class _CommandInput(QLineEdit):
    escape_requested = Signal()
    space_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._composing = False

    @override
    def inputMethodEvent(self, event: QInputMethodEvent) -> None:  # noqa: N802
        self._composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._composing and event.key() == Qt.Key.Key_Escape:
            super().keyPressEvent(event)
            # Do not let an ignored Escape bubble up and cancel the CAD gesture.
            event.accept()
            return
        if not self._composing and event.key() == Qt.Key.Key_Escape:
            self.escape_requested.emit()
            event.accept()
            return
        if (
            not self._composing
            and event.key() == Qt.Key.Key_Space
            and not any(character in self.text() for character in (",", "<", "@"))
        ):
            self.space_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class Drawing2DCommandBar(QWidget):
    """Route explicit 2D commands and coordinates to the active sketch canvas."""

    _TOOLS = {
        "L": "直线",
        "LINE": "直线",
        "PL": "多段线",
        "PLINE": "多段线",
        "REC": "矩形",
        "RECTANGLE": "矩形",
        "POL": "多边形",
        "POLYGON": "多边形",
        "C": "圆",
        "CIRCLE": "圆",
        "A": "圆弧",
        "ARC": "圆弧",
        "SPL": "样条曲线",
        "SPLINE": "样条曲线",
        "TR": "修剪",
        "TRIM": "修剪",
        "EX": "延伸",
        "EXTEND": "延伸",
        "F": "二维圆角",
        "FILLET": "二维圆角",
    }
    _DRAWING_TOOLS = frozenset({"直线", "多段线", "矩形", "多边形", "圆", "圆弧", "样条曲线"})
    _TRANSFORMS = {
        "M": "move",
        "MOVE": "move",
        "CO": "copy",
        "COPY": "copy",
        "RO": "rotate",
        "ROTATE": "rotate",
        "MI": "mirror",
        "MIRROR": "mirror",
    }

    def __init__(
        self,
        canvas: SketchCanvas,
        activate: Callable[[str], bool],
        start_transform: Callable[[str], bool],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("drawing2dCommandBar")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._canvas = canvas
        self._activate = activate
        self._start_transform = start_transform
        self._last_point: Point2D | None = None
        self._last_command: str | None = None
        self._last_is_transform = False
        self._accepted = False
        self._circle_diameter = False
        self._fillet_radius_pending = False
        self._copy_mode_pending = False
        self._copy_command_mode_pending = False
        self.status = QLabel("输入命令或坐标。", self)
        self.input = _CommandInput(self)
        self.input.setObjectName("drawing2dCommandInput")
        self.input.setPlaceholderText("命令 / x,y / @dx,dy / @距离<角度")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("命令", self))
        layout.addWidget(self.input, 1)
        layout.addWidget(self.status, 1)
        self.input.returnPressed.connect(self.submit)
        self.input.space_requested.connect(self.submit)
        self.input.escape_requested.connect(self.cancel)
        canvas.point_accepted.connect(self._point_accepted)
        canvas.changed.connect(self._sync_canvas_prompt)

    def _sync_canvas_prompt(self) -> None:
        if self._canvas.tool != "圆" or not self._canvas.has_pending_geometry:
            self._circle_diameter = False
        if self._canvas.tool != "二维圆角":
            self._fillet_radius_pending = False
            self._canvas.circle_fillet_radius_pending = False
        else:
            self._fillet_radius_pending = self._canvas.circle_fillet_radius_pending
        self.status.setText(self._canvas.message)
        self.status.setToolTip(self._canvas.message)

    def continue_from(self, previous: Drawing2DCommandBar) -> None:
        """Retain this document's command and coordinate history across draft commits."""
        self._last_point = previous._last_point
        self._last_command = previous._last_command
        self._last_is_transform = previous._last_is_transform

    def remember_tool(self, tool: str) -> None:
        """Repeat the last supported tool regardless of how it was activated."""
        if tool in self._TOOLS.values():
            self._last_command = tool
            self._last_is_transform = False

    def _point_accepted(self, value: object) -> None:
        if not isinstance(value, tuple):
            return
        point = cast("tuple[object, ...]", value)
        if len(point) == 2 and all(isinstance(item, int | float) for item in point):
            self._last_point = (float(cast("float", point[0])), float(cast("float", point[1])))
            self._accepted = True

    def _canvas_key(self, key: Qt.Key) -> None:
        event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
        QCoreApplication.sendEvent(self._canvas, event)

    def cancel(self) -> None:
        self._fillet_radius_pending = False
        self._copy_mode_pending = False
        self._copy_command_mode_pending = False
        self._canvas.circle_fillet_radius_pending = False
        self._canvas_key(Qt.Key.Key_Escape)
        self._activate("选择元素")
        self.input.clear()
        self.status.setText("命令已取消；草稿保留。")
        self.input.setFocus()

    def submit(self) -> None:
        text = self.input.text().strip()
        upper = text.upper()
        if self._copy_command_mode_pending:
            if not self._canvas.copy_options_available:
                self._copy_command_mode_pending = False
                self.status.setText("复制命令已结束，请重新开始。")
            elif not text:
                self._copy_command_mode_pending = False
                self.status.setText("复制模式未改变；指定基点。")
            elif upper in {"S", "SINGLE", "M", "MULTIPLE"}:
                self._canvas.set_copy_mode(1 if upper in {"S", "SINGLE"} else 0)
                self._copy_command_mode_pending = False
                self.status.setText("复制模式已设置；指定基点。")
            else:
                self.status.setText("请输入 S / Single 或 M / Multiple。")
                return
            self.input.clear()
            self.input.setFocus()
            return
        if self._canvas.copy_options_available and upper in {"MO", "MODE", "M", "MULTIPLE"}:
            if upper in {"MO", "MODE"}:
                self._copy_command_mode_pending = True
                self.status.setText("复制模式：输入 S / Single 或 M / Multiple。")
            else:
                self._canvas.use_multiple_copy_for_command()
                self.status.setText("当前复制使用连续模式；指定基点。")
            self.input.clear()
            self.input.setFocus()
            return
        if self._copy_mode_pending:
            if not text:
                self._copy_mode_pending = False
                self.status.setText(f"COPYMODE 保持为 {self._canvas.copy_mode}。")
            elif text not in {"0", "1"}:
                self.status.setText("COPYMODE 请输入 0（连续）或 1（单次）。")
                return
            else:
                self._canvas.set_copy_mode(int(text))
                self._copy_mode_pending = False
                self.status.setText(f"COPYMODE 已设为 {text}。")
            self.input.clear()
            self.input.setFocus()
            return
        if upper == "COPYMODE":
            if self._canvas.has_pending_geometry or self._canvas.has_active_edit_gesture:
                self.status.setText("请先完成或取消当前操作，再设置 COPYMODE。")
            else:
                self._copy_mode_pending = True
                self.status.setText(f"COPYMODE 当前值 {self._canvas.copy_mode}；输入 0 或 1。")
                self.input.clear()
            return
        if not text:
            if self._canvas.tool == "二维圆角" and self._fillet_radius_pending:
                self.status.setText("二维圆角：请输入大于零的半径。")
                return
            if self._canvas.tool == "二维圆角" and self._canvas.has_active_edit_gesture:
                self.status.setText("二维圆角：请选择第二个圆；Esc 取消。")
                return
            if (
                self._canvas.has_pending_geometry
                or self._canvas.active_transform is not None
                or (self._canvas.tool == "直线" and self._canvas.pending_point_count > 0)
            ):
                self._canvas_key(Qt.Key.Key_Return)
                self.status.setText(self._canvas.message)
            elif self._last_command is not None:
                if self._last_is_transform:
                    self._start_transform(self._last_command)
                else:
                    self._activate(self._last_command)
                self.status.setText(self._canvas.message)
            else:
                self.status.setText("请输入命令。")
            self.input.clear()
            self.input.setFocus()
            return
        if self._canvas.tool == "二维圆角" and upper in {"R", "RADIUS"}:
            self._fillet_radius_pending = True
            self._canvas.circle_fillet_radius_pending = True
            self.status.setText("二维圆角：请输入大于零的半径。")
            self.input.clear()
            return
        if self._canvas.tool == "二维圆角" and self._fillet_radius_pending:
            try:
                self._canvas.set_circle_fillet_radius(float(text))
            except ValueError:
                self.status.setText("请输入大于零的有限圆角半径。")
                return
            self._fillet_radius_pending = False
            self._canvas.circle_fillet_radius_pending = False
            self.input.clear()
            return
        if (
            upper in {"C", "CLOSE"}
            and (self._canvas.has_pending_geometry or self._canvas.pending_point_count > 0)
            and self._canvas.tool in {"直线", "多段线"}
        ):
            self._canvas_key(Qt.Key.Key_C)
            self.status.setText(self._canvas.message)
            self.input.clear()
            return
        if (
            upper in {"U", "UNDO"}
            and self._canvas.active_transform == "copy"
            and not self._canvas.transform_selecting
        ):
            self._canvas.undo_copy_placement()
            self.status.setText(self._canvas.message)
            self.input.clear()
            self.input.setFocus()
            return
        if (
            upper in {"U", "UNDO"}
            and self._canvas.tool == "直线"
            and self._canvas.continuous_lines
            and self._canvas.pending_point_count > 0
        ):
            self._canvas_key(Qt.Key.Key_U)
            if self._canvas.pending_last_point is not None:
                self._last_point = self._canvas.pending_last_point
            self.status.setText(self._canvas.message)
            self.input.clear()
            self.input.setFocus()
            return
        if (
            upper in {"D", "DIAMETER"}
            and self._canvas.tool == "圆"
            and self._canvas.has_pending_geometry
        ):
            self._circle_diameter = True
            self.status.setText("圆：请输入大于零的直径。")
            self.input.clear()
            self.input.setFocus()
            return
        tool = self._TOOLS.get(upper)
        if tool is not None:
            if self._activate(tool):
                self._last_command = tool
                self._last_is_transform = False
                self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        transform = self._TRANSFORMS.get(upper)
        if transform is not None:
            if self._start_transform(transform):
                self._last_command = transform
                self._last_is_transform = True
                self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        if (
            self._canvas.rotation_center is not None
            and not self._canvas.rotation_uses_reference
            and not any(separator in text for separator in (",", "<", "@"))
        ):
            try:
                angle = float(text)
                if not math.isfinite(angle):
                    raise ValueError
            except ValueError:
                self.status.setText("请输入有限的旋转角度或坐标。")
                return
            if self._canvas.apply_rotation_angle(angle):
                self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        if (
            self._canvas.tool == "圆"
            and self._canvas.has_pending_geometry
            and self._canvas.active_transform is None
            and not any(separator in text for separator in (",", "<", "@"))
        ):
            try:
                value = float(text)
                if not math.isfinite(value) or value <= 0:
                    raise ValueError
            except ValueError:
                self.status.setText("请输入大于零的有限半径或直径。")
                return
            center = self._canvas.pending_last_point
            if center is None:
                self.status.setText("圆心已失效，请重新指定。")
                return
            radius = value / 2 if self._circle_diameter else value
            point = (center[0] + radius, center[1])
            if not math.isfinite(point[0]) or point == center:
                self.status.setText("圆尺寸超出可用范围。")
                return
            self._accepted = False
            self._canvas.add_coordinate_point(point, exact_point=True)
            self.status.setText(self._canvas.message)
            if self._accepted:
                self.input.clear()
            self.input.setFocus()
            return
        if not any(separator in text for separator in (",", "<", "@")):
            self.status.setText("未知命令；请输入受支持的命令或坐标。")
            return
        if self._canvas.tool not in self._DRAWING_TOOLS and self._canvas.active_transform is None:
            self.status.setText("未知命令或当前工具不接受坐标。")
            return
        try:
            point = parse_coordinate(text, self._last_point)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._accepted = False
        selecting = self._canvas.transform_selecting
        self._canvas.add_coordinate_point(point, exact_point=True)
        self.status.setText(self._canvas.message)
        if self._accepted or selecting:
            self.input.clear()
        self.input.setFocus()
