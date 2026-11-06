# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Compact operation-specific controls for nonmodal modeling commands."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolBar,
    QWidget,
)

from mycad.core.sketch import LineEntity, Sketch
from mycad.core.viewport_protocol import PlanarFaceFrame
from mycad.ui.cad_icons import set_button_icon
from mycad.ui.command_strip import install_command_strip
from mycad.ui.modeling_handles import DimensionHandle, dimension_handle

_MODE_OPTIONS = (("替换", "new"), ("添加", "add"), ("切除", "cut"))
_PROFILE_OPTIONS = (("圆形", "circle"), ("矩形", "rect"))
_DEPTH_OPTIONS = (("盲孔", "blind"), ("贯穿", "through_all"))
_TOOL_OPTIONS = (("长方体", "box"), ("圆柱体", "cylinder"))
_BODY_BOOLEAN_OPTIONS = (("并集", "union"), ("差集", "difference"), ("交集", "intersection"))
_BODY_TRANSFORM_OPTIONS = (
    ("移动", "move"),
    ("旋转", "rotate"),
    ("镜像替换", "mirror"),
    ("复制", "copy"),
)
_BODY_PATTERN_OPTIONS = (("线性", "linear"), ("环形", "circular"))
_AXIS_OPTIONS = (("X 轴", "X"), ("Y 轴", "Y"), ("Z 轴", "Z"))
_MIRROR_OPTIONS = (("YZ 面", "X"), ("XZ 面", "Y"), ("XY 面", "Z"))


class _DistanceSpinBox(QDoubleSpinBox):
    accepted = Signal()
    activated = Signal()
    _input_start_value = 0.0
    input_validity_changed = Signal(bool)

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        self._input_start_value = self.value()
        self.activated.emit()
        super().focusInEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.setValue(self._input_start_value)
            self.text_input_changed("")
            self.accepted.emit()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.hasAcceptableInput():
                self.interpretText()
                if self.value() != 0 or self.property("allowZero") is True:
                    self.accepted.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def text_input_changed(self, _text: str) -> None:
        try:
            nonzero = float(self.cleanText()) != 0 or self.property("allowZero") is True
        except ValueError:
            nonzero = False
        self.input_validity_changed.emit(self.hasAcceptableInput() and nonzero)

    def finish_text_input(self) -> None:
        self.text_input_changed("")


class ModelingCommandBar(QToolBar):
    """One-line command controls above the viewport, never over the model."""

    parameters_changed = Signal(object)
    commit_requested = Signal()
    cancel_requested = Signal()
    dimension_changed = Signal()
    distance_accepted = Signal()
    distance_input_validity_changed = Signal(bool)
    select_source_requested = Signal()
    position_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("建模命令", parent)
        self.setObjectName("modelingCommandBar")
        self.setMovable(False)
        self.setFloatable(False)
        self.setAllowedAreas(Qt.ToolBarArea.TopToolBarArea)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._command_id: str | None = None
        self._controls: dict[str, QWidget] = {}
        self._placement_point = (0.0, 0.0, 0.0)
        self._active_dimension = ""
        self._invalid_fields: set[str] = set()
        self._field_containers: dict[str, QWidget] = {}
        self._content: QWidget | None = None
        self._commit_button: QPushButton | None = None
        self._cancel_button: QPushButton | None = None
        self._select_source_button: QPushButton | None = None
        self._preview_label: QLabel | None = None
        self._selection_label: QLabel | None = None
        self._sketches: dict[str, Sketch] = {}
        self._selected_region: tuple[str, tuple[str, ...]] | None = None
        self.setFixedHeight(42)

    @property
    def command_id(self) -> str | None:
        """Command currently represented by the controls."""

        return self._command_id

    def configure(
        self,
        command_id: str,
        selection_prompt: str = "",
        sketch_ids: Sequence[str] = (),
        sketches: Sequence[Sketch] = (),
    ) -> None:
        """Build compact controls for a built-in command."""

        self._clear_controls()
        self._command_id = command_id
        self._selected_region = None
        self._sketches = {sketch.sketch_id: sketch for sketch in sketches}
        self._active_dimension = {
            "feature.box": "size_z",
            "feature.cylinder": "height",
            "feature.sphere": "radius",
            "feature.extrude": "distance",
            "feature.revolve": "angle_deg",
            "modify.chamfer": "distance",
            "feature.hole": "depth_value",
            "feature.hole_pattern": "pattern_radius",
            "modify.boolean_cut": "tool_size_z",
            "modify.boolean_intersect": "tool_size_z",
        }.get(command_id, "")
        self._invalid_fields.clear()
        self._placement_point = (0.0, 0.0, 0.0)
        content = QWidget(self)
        content.setObjectName("modelingCommandBarContent")
        layout = QHBoxLayout(content)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(6)
        title = QLabel(self._label_for(command_id), content)
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)
        layout.addSpacing(8)

        if command_id == "feature.box":
            self._number(layout, "size_x", "X", 20.0)
            self._number(layout, "size_y", "Y", 20.0)
            self._number(layout, "size_z", "Z", 10.0)
            self._mode(layout)
        elif command_id == "feature.cylinder":
            self._number(layout, "radius", "半径", 5.0)
            self._number(layout, "height", "高度", 10.0)
            self._mode(layout)
        elif command_id == "feature.sphere":
            self._number(layout, "radius", "半径", 10.0)
            for axis in "xyz":
                coordinate = self._number(
                    layout,
                    f"center_{axis}",
                    axis.upper(),
                    0.0,
                    minimum=-1_000_000.0,
                    allow_zero=True,
                )
                coordinate.setDecimals(6)
            position = QPushButton("定位球心", content)
            position.clicked.connect(self.position_requested)
            layout.addWidget(position)
            self._mode(layout)
            self._controls["mode"].setToolTip(
                "替换删除当前实体；添加合并相交实体或保留分离实体；切除从当前实体中减去球体。"
            )
        elif command_id in {"feature.extrude", "feature.revolve"}:
            if command_id == "feature.extrude":
                self._combo(
                    layout,
                    "extrudeSource",
                    "来源",
                    (("模型平面", "face"), ("XY 截面", "profile"), ("草图", "sketch")),
                    "face",
                )
                self._combo(
                    layout,
                    "sketchProfile",
                    "草图",
                    (("选择已提交草图", ""),)
                    + tuple(
                        (f"草图 {index + 1} · {sketch_id[:8]}", sketch_id)
                        for index, sketch_id in enumerate(sketch_ids)
                    ),
                    "",
                )
            else:
                self._combo(
                    layout,
                    "revolveSource",
                    "来源",
                    (("XY 截面", "profile"), ("草图", "sketch")),
                    "profile",
                )
                self._combo(
                    layout,
                    "sketchProfile",
                    "草图",
                    (("选择已提交草图", ""),)
                    + tuple(
                        (f"草图 {index + 1} · {sketch_id[:8]}", sketch_id)
                        for index, sketch_id in enumerate(sketch_ids)
                    ),
                    "",
                )
            self._combo(
                layout,
                "sketchRegion",
                "区域",
                (("全部区域", "all"), ("选中区域", "selected")),
                "all",
            )
            self._combo(layout, "profileType", "截面", _PROFILE_OPTIONS, "circle")
            self._number(layout, "radius", "R", 5.0)
            self._number(layout, "profile_width", "宽", 10.0)
            self._number(layout, "profile_height", "高", 10.0)
            if command_id == "feature.extrude":
                self._number(layout, "distance", "距离", 10.0, minimum=-1_000_000.0)
                self._controls["distance"].setToolTip("正值沿所选面外法向添加；负值向内切除。")
                self._combo(
                    layout,
                    "extentMode",
                    "范围",
                    (("单侧", "one_sided"), ("对称（总深度）", "symmetric")),
                    "one_sided",
                )
                self._controls["extentMode"].setToolTip("对称范围将总深度平分到草图平面两侧。")
            else:
                self._combo(
                    layout,
                    "axis",
                    "轴",
                    (("X 轴", "X"), ("Y 轴", "Y"), ("Z 轴", "Z")),
                    "X",
                )
                self._combo(
                    layout,
                    "axisSource",
                    "轴来源",
                    (("全局轴", "global"), ("构造线", "sketch_line")),
                    "global",
                )
                self._combo(
                    layout,
                    "axisLine",
                    "轴线",
                    (("选择构造线", ""),),
                    "",
                )
                self._number(layout, "angle_deg", "角度", 360.0, unit="°", minimum=0.000001)
            self._mode(layout)
            self._set_profile_visibility()
            if command_id == "feature.extrude":
                self._set_extrude_source_visibility()
            else:
                self._set_revolve_source_visibility()
        elif command_id in {"feature.hole", "feature.hole_pattern"}:
            if command_id == "feature.hole":
                self._combo(
                    layout,
                    "holeSource",
                    "来源",
                    (("面上点位", "face"), ("草图", "sketch")),
                    "face",
                )
                self._combo(
                    layout,
                    "sketchProfile",
                    "草图",
                    (("选择已提交草图", ""),)
                    + tuple(
                        (f"草图 {index + 1} · {sketch_id[:8]}", sketch_id)
                        for index, sketch_id in enumerate(sketch_ids)
                    ),
                    "",
                )
            self._number(layout, "diameter", "孔径", 5.0)
            self._combo(layout, "depthKind", "深度", _DEPTH_OPTIONS, "blind")
            self._number(layout, "depth_value", "深度值", 10.0)
            if command_id == "feature.hole_pattern":
                self._combo(
                    layout,
                    "patternCenter",
                    "阵列中心",
                    (("点击位置", "picked"), ("面形心", "face_center")),
                    "picked",
                ).setToolTip("面形心取目标面的面积中心；环形面的中心可位于孔洞内。")
                self._number(layout, "pattern_radius", "阵列半径", 20.0)
                self._integer(layout, "pattern_count", "数量", 4, minimum=2, maximum=64)
                self._number(
                    layout,
                    "start_angle_deg",
                    "起始角",
                    0.0,
                    unit="°",
                    minimum=-3600.0,
                )
            self._set_depth_visibility()
            if command_id == "feature.hole":
                self._set_hole_source_visibility()
        elif command_id == "modify.chamfer":
            self._number(layout, "distance", "等距", 1.0)
        elif command_id in {"modify.boolean_cut", "modify.boolean_intersect"}:
            self._combo(layout, "toolType", "刀具", _TOOL_OPTIONS, "box")
            self._number(layout, "tool_size_x", "X", 10.0)
            self._number(layout, "tool_size_y", "Y", 10.0)
            self._number(layout, "tool_size_z", "Z", 10.0)
            self._number(layout, "tool_radius", "R", 5.0)
            self._number(layout, "tool_height", "高", 10.0)
            self._set_tool_visibility()
        elif command_id == "modify.boolean_bodies":
            self._combo(layout, "bodyOperation", "运算", _BODY_BOOLEAN_OPTIONS, "union")
            self._combo(
                layout,
                "keepTool",
                "刀具体",
                (("运算后消耗", "false"), ("保留原体", "true")),
                "false",
            )
        elif command_id == "modify.body_transform":
            self._combo(layout, "transformOperation", "操作", _BODY_TRANSFORM_OPTIONS, "move")
            for key, label in (("move_x", "ΔX"), ("move_y", "ΔY"), ("move_z", "ΔZ")):
                self._number(
                    layout,
                    key,
                    label,
                    10.0 if key == "move_x" else 0.0,
                    minimum=-1_000_000.0,
                    allow_zero=True,
                )
            self._combo(layout, "rotateAxis", "旋转轴", _AXIS_OPTIONS, "Z")
            for key, label in (
                ("rotate_x", "轴心 X"),
                ("rotate_y", "轴心 Y"),
                ("rotate_z", "轴心 Z"),
            ):
                self._number(layout, key, label, 0.0, minimum=-1_000_000.0, allow_zero=True)
            self._number(
                layout,
                "rotate_angle",
                "角度",
                90.0,
                unit="°",
                minimum=-3600.0,
                maximum=3600.0,
            )
            self._combo(layout, "mirrorPlane", "镜像面", _MIRROR_OPTIONS, "X")
            for key, label in (
                ("mirror_x", "平面 X"),
                ("mirror_y", "平面 Y"),
                ("mirror_z", "平面 Z"),
            ):
                self._number(layout, key, label, 0.0, minimum=-1_000_000.0, allow_zero=True)
            self._set_transform_visibility()
        elif command_id == "modify.body_pattern":
            self._combo(layout, "patternKind", "类型", _BODY_PATTERN_OPTIONS, "linear")
            self._integer(layout, "body_pattern_count", "数量", 2, minimum=2, maximum=64)
            for key, label in (
                ("spacing_x", "步距 X"),
                ("spacing_y", "步距 Y"),
                ("spacing_z", "步距 Z"),
            ):
                self._number(
                    layout,
                    key,
                    label,
                    10.0 if key == "spacing_x" else 0.0,
                    minimum=-1_000_000.0,
                    allow_zero=True,
                )
            self._combo(layout, "patternAxis", "旋转轴", _AXIS_OPTIONS, "Z")
            for key, label in (
                ("pattern_x", "中心 X"),
                ("pattern_y", "中心 Y"),
                ("pattern_z", "中心 Z"),
            ):
                self._number(layout, key, label, 0.0, minimum=-1_000_000.0, allow_zero=True)
            self._number(layout, "pattern_angle", "角度", 360.0, unit="°", maximum=360.0)
            self._set_pattern_visibility()
        else:
            raise ValueError(f"unsupported modeling command {command_id!r}")

        self._selection_label = QLabel(selection_prompt, content)
        self._selection_label.setObjectName("modelingSelectionStatus")
        self._selection_label.setMinimumWidth(72)
        self._selection_label.setToolTip(selection_prompt)
        layout.addSpacing(6)
        layout.addWidget(self._selection_label)
        select_source = QPushButton("选择源对象", content)
        select_source.setObjectName("modelingSelectSource")
        select_source.setToolTip("返回源模型后选择对象，预览将重新生成。")
        select_source.clicked.connect(self.select_source_requested)
        layout.addWidget(select_source)
        self._select_source_button = select_source
        self._preview_label = QLabel("等待输入", content)
        self._preview_label.setObjectName("modelingPreviewStatus")
        layout.addWidget(self._preview_label)
        layout.addStretch(1)
        commit_button = QPushButton("应用并执行", content)
        set_button_icon(commit_button, "confirm")
        commit_button.setObjectName("modelingCommitButton")
        commit_button.setToolTip("仅当当前参数的预览有效时可执行")
        commit_button.setEnabled(False)
        commit_button.clicked.connect(self.commit_requested)
        cancel_button = QPushButton("取消", content)
        set_button_icon(cancel_button, "cancel")
        cancel_button.setObjectName("modelingCancelButton")
        cancel_button.clicked.connect(self.cancel_requested)
        self._commit_button = commit_button
        self._cancel_button = cancel_button
        self._content = install_command_strip(self, content, (commit_button, cancel_button))

    def values(self) -> dict[str, object]:
        """Return the current controls in the command's public schema shape."""

        command_id = self._command_id
        if command_id == "feature.box":
            return {
                "size_x": self._number_value("size_x"),
                "size_y": self._number_value("size_y"),
                "size_z": self._number_value("size_z"),
                "center": list(self._placement_point),
                "mode": self._choice("mode"),
            }
        if command_id == "feature.cylinder":
            return {
                "radius": self._number_value("radius"),
                "height": self._number_value("height"),
                "center": list(self._placement_point),
                "mode": self._choice("mode"),
            }
        if command_id == "feature.sphere":
            return {
                "radius": self._number_value("radius"),
                "center": [self._number_value(f"center_{axis}") for axis in "xyz"],
                "mode": self._choice("mode"),
            }
        if command_id == "modify.chamfer":
            return {"distance": self._number_value("distance")}
        if command_id == "modify.boolean_bodies":
            return {
                "operation": self._choice("bodyOperation"),
                "keep_tool": self._choice("keepTool") == "true",
            }
        if command_id == "modify.body_transform":
            operation = self._choice("transformOperation")
            if operation in {"move", "copy"}:
                transform: dict[str, object] = {
                    "operation": operation,
                    "translation_mm": [
                        self._number_value("move_x"),
                        self._number_value("move_y"),
                        self._number_value("move_z"),
                    ],
                }
            elif operation == "rotate":
                transform = {
                    "operation": operation,
                    "axis_unit": self._axis_vector(self._choice("rotateAxis")),
                    "center_mm": [
                        self._number_value("rotate_x"),
                        self._number_value("rotate_y"),
                        self._number_value("rotate_z"),
                    ],
                    "angle_deg": self._number_value("rotate_angle"),
                }
            else:
                transform = {
                    "operation": "mirror",
                    "plane_normal_unit": self._axis_vector(self._choice("mirrorPlane")),
                    "plane_origin_mm": [
                        self._number_value("mirror_x"),
                        self._number_value("mirror_y"),
                        self._number_value("mirror_z"),
                    ],
                }
            return {"transform": transform}
        if command_id == "modify.body_pattern":
            kind = self._choice("patternKind")
            if kind == "linear":
                pattern: dict[str, object] = {
                    "kind": kind,
                    "count": self._integer_value("body_pattern_count"),
                    "spacing_mm": [
                        self._number_value("spacing_x"),
                        self._number_value("spacing_y"),
                        self._number_value("spacing_z"),
                    ],
                }
            else:
                pattern = {
                    "kind": kind,
                    "count": self._integer_value("body_pattern_count"),
                    "axis_unit": self._axis_vector(self._choice("patternAxis")),
                    "center_mm": [
                        self._number_value("pattern_x"),
                        self._number_value("pattern_y"),
                        self._number_value("pattern_z"),
                    ],
                    "angle_deg": self._number_value("pattern_angle"),
                }
            return {"pattern": pattern}
        if command_id in {"feature.extrude", "feature.revolve"}:
            if command_id == "feature.extrude" and self._choice("extrudeSource") == "face":
                distance = self._number_value("distance")
                return {
                    "profile": {"type": "face"},
                    "distance": distance,
                    "mode": "add" if distance >= 0 else "cut",
                }
            if command_id == "feature.extrude" and self._choice("extrudeSource") == "sketch":
                extrude_sketch_params: dict[str, object] = {
                    "profile": self._sketch_profile(),
                    "mode": self._choice("mode"),
                    "extent_mode": self._choice("extentMode"),
                }
                if self._choice("extentMode") != "to_face":
                    extrude_sketch_params["distance"] = self._number_value("distance")
                return extrude_sketch_params
            if command_id == "feature.revolve" and self._choice("revolveSource") == "sketch":
                sketch_params: dict[str, object] = {
                    "profile": self._sketch_profile(),
                    "angle_deg": self._number_value("angle_deg"),
                    "mode": self._choice("mode"),
                }
                if self._choice("axisSource") == "sketch_line":
                    sketch_params["axis_reference"] = {
                        "type": "sketch_line",
                        "sketch_id": self._choice("sketchProfile"),
                        "entity_id": self._choice("axisLine"),
                    }
                else:
                    sketch_params["axis"] = self._choice("axis")
                return sketch_params
            profile_type = self._choice("profileType")
            center = list(self._placement_point[:2])
            profile: dict[str, object] = {"type": profile_type, "center": center}
            if profile_type == "circle":
                profile["radius"] = self._number_value("radius")
            else:
                profile["width"] = self._number_value("profile_width")
                profile["height"] = self._number_value("profile_height")
            params: dict[str, object] = {"profile": profile, "mode": self._choice("mode")}
            if command_id == "feature.extrude":
                params["distance"] = self._number_value("distance")
                params["extent_mode"] = self._choice("extentMode")
            else:
                params["axis"] = self._choice("axis")
                params["angle_deg"] = self._number_value("angle_deg")
            return params
        if command_id in {"feature.hole", "feature.hole_pattern"}:
            if command_id == "feature.hole" and self._choice("holeSource") == "sketch":
                return {
                    "profile": {"type": "sketch", "sketch_id": self._choice("sketchProfile")},
                    "depth": self._depth_value(),
                }
            base_hole: dict[str, object] = {
                "position": {"kind": "center"},
                "diameter": self._number_value("diameter"),
                "depth": self._depth_value(),
            }
            if command_id == "feature.hole":
                return base_hole
            return {
                "base_hole": base_hole,
                "pattern": {
                    "kind": "polar",
                    "radius": self._number_value("pattern_radius"),
                    "count": self._integer_value("pattern_count"),
                    "start_angle_deg": self._number_value("start_angle_deg"),
                },
            }
        if command_id in {"modify.boolean_cut", "modify.boolean_intersect"}:
            tool_type = self._choice("toolType")
            tool: dict[str, object] = {"type": tool_type, "center": list(self._placement_point)}
            if tool_type == "box":
                tool.update(
                    {
                        "size_x": self._number_value("tool_size_x"),
                        "size_y": self._number_value("tool_size_y"),
                        "size_z": self._number_value("tool_size_z"),
                    }
                )
            else:
                tool.update(
                    {
                        "radius": self._number_value("tool_radius"),
                        "height": self._number_value("tool_height"),
                    }
                )
            return {"tool": tool}
        return {}

    def hole_pattern_uses_face_center(self) -> bool:
        return (
            self._command_id == "feature.hole_pattern"
            and self._choice("patternCenter") == "face_center"
        )

    def set_placement_point(self, point: Sequence[float]) -> None:
        """Set the current workplane pick and publish updated values."""

        if len(point) != 3:
            raise ValueError("workplane point requires three coordinates")
        self._placement_point = (float(point[0]), float(point[1]), float(point[2]))
        if self._command_id == "feature.sphere":
            for axis, value in zip("xyz", point, strict=True):
                control = self._controls[f"center_{axis}"]
                if isinstance(control, QDoubleSpinBox):
                    with QSignalBlocker(control):
                        control.setValue(float(value))
        self._emit_values()

    def set_selection_status(self, message: str) -> None:
        """Show the active geometric selection prompt or result."""

        if self._selection_label is not None:
            self._selection_label.setText(message)
            self._selection_label.setToolTip(message)

    def extrude_distance(self) -> float:
        return self._number_value("distance")

    def set_extrude_distance(self, value: float) -> None:
        self.set_dimension_value(value)

    def set_dimension_value(self, value: float) -> None:
        control = self._controls.get(self._active_dimension)
        if not isinstance(control, _DistanceSpinBox):
            return
        with QSignalBlocker(control):
            control.setValue(value)
        self._invalid_fields.discard(self._active_dimension)
        self._emit_values()

    def focus_extrude_distance(self, text: str) -> None:
        self.focus_dimension(text)

    def focus_dimension(self, text: str) -> None:
        control = self._controls.get(self._active_dimension)
        if not isinstance(control, _DistanceSpinBox):
            return
        control.setFocus(Qt.FocusReason.OtherFocusReason)
        control.selectAll()
        edit = control.findChild(QLineEdit)
        if text and edit is not None:
            edit.setText(text)
            control.text_input_changed(text)
            if control.hasAcceptableInput():
                control.interpretText()
            edit.setCursorPosition(len(text))

    def dimension(self, face: PlanarFaceFrame | None) -> tuple[DimensionHandle, float] | None:
        key = self._active_dimension
        # A hidden depth or profile field must not keep a stale manipulator.
        field = self._field_containers.get(key)
        if field is None or field.isHidden():
            defaults = ("diameter", "tool_height", "tool_size_z", "radius", "distance")
            key = next(
                (
                    k
                    for k in defaults
                    if k in self._field_containers and not self._field_containers[k].isHidden()
                ),
                "",
            )
            self._active_dimension = key
        control = self._controls.get(key)
        if not isinstance(control, _DistanceSpinBox) or self._command_id is None:
            return None
        origin = face.origin if face is not None else self._placement_point
        normal = face.normal if face is not None else (0.0, 0.0, 1.0)
        spec = dimension_handle(
            self._command_id,
            key,
            control.accessibleName(),
            origin,
            normal,
            axis=self._choice("axis") if "axis" in self._controls else "X",
            ring_radius=self._number_value("pattern_radius")
            if "pattern_radius" in self._controls
            else 20.0,
        )
        return spec, control.value()

    def input_valid(self) -> bool:
        if not all(self._field_containers[key].isHidden() for key in self._invalid_fields):
            return False
        needs_sketch = (
            self._command_id == "feature.extrude" and self._choice("extrudeSource") == "sketch"
        ) or (self._command_id == "feature.revolve" and self._choice("revolveSource") == "sketch")
        needs_sketch = needs_sketch or (
            self._command_id == "feature.hole" and self._choice("holeSource") == "sketch"
        )
        if needs_sketch and not self._choice("sketchProfile"):
            return False
        needs_axis_line = (
            self._command_id == "feature.revolve"
            and self._choice("revolveSource") == "sketch"
            and self._choice("axisSource") == "sketch_line"
        )
        return not needs_axis_line or bool(self._choice("axisLine"))

    def _activate_dimension(self, key: str) -> None:
        if key == self._active_dimension:
            return
        self._active_dimension = key
        self.dimension_changed.emit()

    def _field_validity(self, key: str, valid: bool) -> None:
        if valid:
            self._invalid_fields.discard(key)
        else:
            self._invalid_fields.add(key)
        self.distance_input_validity_changed.emit(self.input_valid())

    def set_preview_valid(self, valid: bool) -> None:
        """Only allow confirmation when the latest geometry preview succeeded."""

        if self._commit_button is not None:
            self._commit_button.setProperty("previewValid", valid)
            self._commit_button.setEnabled(valid and not self.is_busy())
        if self._preview_label is not None:
            self._preview_label.setText("预览有效" if valid else "等待预览")

    def set_busy(self, busy: bool) -> None:
        """Lock command parameters during the serialized model write."""

        for control in self._controls.values():
            control.setEnabled(not busy)
        if self._commit_button is not None:
            self._commit_button.setEnabled(
                False if busy else self._commit_button.property("previewValid") is True
            )
            self._commit_button.setProperty("busy", busy)
        if self._cancel_button is not None:
            self._cancel_button.setEnabled(not busy)
        if self._select_source_button is not None:
            self._select_source_button.setEnabled(not busy)

    def is_busy(self) -> bool:
        """Whether a commit is currently being written."""

        return self._commit_button is not None and self._commit_button.property("busy") is True

    def _clear_controls(self) -> None:
        for action in self.actions():
            self.removeAction(action)
            action.deleteLater()
        if self._content is not None:
            self._content.deleteLater()
        self._controls.clear()
        self._field_containers.clear()
        self._content = None
        self._commit_button = None
        self._cancel_button = None
        self._select_source_button = None
        self._preview_label = None
        self._selection_label = None

    @staticmethod
    def _label_for(command_id: str) -> str:
        return {
            "feature.box": "长方体",
            "feature.cylinder": "圆柱体",
            "feature.sphere": "球体",
            "feature.extrude": "拉伸",
            "feature.revolve": "旋转",
            "feature.hole": "孔",
            "feature.hole_pattern": "孔阵列",
            "modify.boolean_cut": "差集",
            "modify.boolean_intersect": "交集",
            "modify.boolean_bodies": "实体布尔",
            "modify.body_transform": "实体变换",
            "modify.body_pattern": "实体阵列",
            "modify.chamfer": "倒角",
        }[command_id]

    def _number(
        self,
        layout: QHBoxLayout,
        key: str,
        label: str,
        value: float,
        *,
        unit: str = "mm",
        minimum: float = 0.000001,
        allow_zero: bool = False,
        maximum: float | None = None,
    ) -> QDoubleSpinBox:
        container = self._field(layout, key, label)
        spin = _DistanceSpinBox(container)
        spin.setObjectName(key)
        spin.setProperty("allowZero", allow_zero or key == "start_angle_deg")
        spin.setAccessibleName(label)
        spin.setToolTip(f"{label}：点击此尺寸切换视口手柄；Enter 接受，Esc 恢复")
        spin.setDecimals(3)
        spin.setRange(
            max(0.001, minimum) if minimum > 0 else minimum,
            maximum if maximum is not None else 360.0 if key == "angle_deg" else 1_000_000.0,
        )
        spin.setValue(value)
        spin.setSingleStep(1.0)
        spin.setSuffix(f" {unit}")
        spin.setFixedWidth(92)
        field_layout = container.layout()
        if isinstance(field_layout, QHBoxLayout):
            field_layout.addWidget(spin)
        self._controls[key] = spin
        spin.valueChanged.connect(self._emit_values)

        def on_validity(valid: bool) -> None:
            self._field_validity(key, valid)

        spin.accepted.connect(self.distance_accepted)
        spin.activated.connect(lambda: self._activate_dimension(key))
        spin.input_validity_changed.connect(on_validity)
        spin.editingFinished.connect(spin.finish_text_input)
        edit = spin.findChild(QLineEdit)
        if edit is not None:
            edit.textEdited.connect(spin.text_input_changed)
        return spin

    def _integer(
        self,
        layout: QHBoxLayout,
        key: str,
        label: str,
        value: int,
        *,
        minimum: int,
        maximum: int,
    ) -> QSpinBox:
        container = self._field(layout, key, label)
        spin = QSpinBox(container)
        spin.setObjectName(key)
        spin.setAccessibleName(label)
        spin.setToolTip(f"{label}：点击此尺寸切换视口手柄；Enter 接受，Esc 恢复")
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setFixedWidth(72)
        field_layout = container.layout()
        if isinstance(field_layout, QHBoxLayout):
            field_layout.addWidget(spin)
        self._controls[key] = spin
        spin.valueChanged.connect(self._emit_values)
        return spin

    def _combo(
        self,
        layout: QHBoxLayout,
        key: str,
        label: str,
        options: Sequence[tuple[str, str]],
        selected: str,
    ) -> QComboBox:
        container = self._field(layout, key, label)
        combo = QComboBox(container)
        combo.setObjectName(key)
        combo.setAccessibleName(label)
        for text, value in options:
            combo.addItem(text, value)
        index = combo.findData(selected)
        combo.setCurrentIndex(max(0, index))
        combo.setFixedWidth(98)
        field_layout = container.layout()
        if isinstance(field_layout, QHBoxLayout):
            field_layout.addWidget(combo)
        self._controls[key] = combo
        combo.currentIndexChanged.connect(self._on_choice_changed)
        return combo

    def _mode(self, layout: QHBoxLayout) -> None:
        self._combo(layout, "mode", "方式", _MODE_OPTIONS, "new")

    def _field(self, layout: QHBoxLayout, key: str, label: str) -> QWidget:
        container = QWidget(self)
        container.setObjectName(f"{key}Field")
        field_layout = QHBoxLayout(container)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(3)
        label_widget = QLabel(label, container)
        label_widget.setBuddy(container)
        field_layout.addWidget(label_widget)
        layout.addWidget(container)
        self._field_containers[key] = container
        return container

    def _number_value(self, key: str) -> float:
        control = self._controls[key]
        return float(cast("QDoubleSpinBox", control).value())

    def _integer_value(self, key: str) -> int:
        control = self._controls[key]
        return int(cast("QSpinBox", control).value())

    def _choice(self, key: str) -> str:
        control = cast("QComboBox", self._controls[key])
        return str(control.currentData())

    def _depth_value(self) -> dict[str, object]:
        kind = self._choice("depthKind")
        if kind == "through_all":
            return {"kind": kind}
        return {"kind": "blind", "value": self._number_value("depth_value")}

    def _set_profile_visibility(self) -> None:
        is_circle = self._choice("profileType") == "circle"
        self._field_containers["radius"].setVisible(is_circle)
        self._field_containers["profile_width"].setVisible(not is_circle)
        self._field_containers["profile_height"].setVisible(not is_circle)

    def _set_depth_visibility(self) -> None:
        self._field_containers["depth_value"].setVisible(self._choice("depthKind") == "blind")

    def _set_tool_visibility(self) -> None:
        is_box = self._choice("toolType") == "box"
        for key in ("tool_size_x", "tool_size_y", "tool_size_z"):
            self._field_containers[key].setVisible(is_box)
        for key in ("tool_radius", "tool_height"):
            self._field_containers[key].setVisible(not is_box)

    def _set_transform_visibility(self) -> None:
        operation = self._choice("transformOperation")
        is_move_or_copy = operation in {"move", "copy"}
        is_rotate = operation == "rotate"
        is_mirror = operation == "mirror"
        for key in ("move_x", "move_y", "move_z"):
            self._field_containers[key].setVisible(is_move_or_copy)
        for key in ("rotateAxis", "rotate_x", "rotate_y", "rotate_z", "rotate_angle"):
            self._field_containers[key].setVisible(is_rotate)
        for key in ("mirrorPlane", "mirror_x", "mirror_y", "mirror_z"):
            self._field_containers[key].setVisible(is_mirror)

    def _set_pattern_visibility(self) -> None:
        is_linear = self._choice("patternKind") == "linear"
        for key in ("spacing_x", "spacing_y", "spacing_z"):
            self._field_containers[key].setVisible(is_linear)
        for key in ("patternAxis", "pattern_x", "pattern_y", "pattern_z", "pattern_angle"):
            self._field_containers[key].setVisible(not is_linear)

    @staticmethod
    def _axis_vector(axis: str) -> list[float]:
        return {
            "X": [1.0, 0.0, 0.0],
            "Y": [0.0, 1.0, 0.0],
            "Z": [0.0, 0.0, 1.0],
        }[axis]

    def _on_choice_changed(self, _index: int) -> None:
        if self._command_id in {"feature.extrude", "feature.revolve"}:
            if "profileType" in self._controls:
                self._set_profile_visibility()
                if self._command_id == "feature.extrude":
                    self._set_extrude_source_visibility()
                else:
                    if self.sender() is self._controls.get("sketchProfile"):
                        self._refresh_revolve_axis_lines()
                    self._set_revolve_source_visibility()
        elif self._command_id in {"feature.hole", "feature.hole_pattern"}:
            self._set_depth_visibility()
            if self._command_id == "feature.hole":
                self._set_hole_source_visibility()
        elif self._command_id in {"modify.boolean_cut", "modify.boolean_intersect"}:
            self._set_tool_visibility()
        elif self._command_id == "modify.body_transform":
            self._set_transform_visibility()
        elif self._command_id == "modify.body_pattern":
            self._set_pattern_visibility()
        self.distance_input_validity_changed.emit(self.input_valid())
        self._emit_values()

    def set_selected_sketch_region(self, sketch_id: str, entity_ids: tuple[str, ...]) -> None:
        """Offer the selected region while retaining an explicit all-regions option."""
        self._selected_region = (sketch_id, entity_ids)
        control = cast("QComboBox", self._controls["sketchRegion"])
        control.setCurrentIndex(control.findData("selected"))
        if self._command_id == "feature.extrude":
            self._set_extrude_source_visibility()
        else:
            self._set_revolve_source_visibility()

    def _sketch_profile(self) -> dict[str, object]:
        sketch_id = self._choice("sketchProfile")
        profile: dict[str, object] = {"type": "sketch", "sketch_id": sketch_id}
        if (
            self._selected_region is not None
            and self._selected_region[0] == sketch_id
            and self._choice("sketchRegion") == "selected"
        ):
            profile["boundary_entity_ids"] = list(self._selected_region[1])
        return profile

    def _set_extrude_source_visibility(self) -> None:
        is_face = self._choice("extrudeSource") == "face"
        is_sketch = self._choice("extrudeSource") == "sketch"
        extent_control = cast("QComboBox", self._controls["extentMode"])
        extent_options = [("单侧", "one_sided"), ("对称（总深度）", "symmetric")]
        if is_sketch:
            extent_options.append(("到面", "to_face"))
        current_extent = self._choice("extentMode")
        if current_extent == "to_face" and not is_sketch:
            current_extent = "one_sided"
        with QSignalBlocker(extent_control):
            extent_control.clear()
            for label, value in extent_options:
                extent_control.addItem(label, value)
            extent_control.setCurrentIndex(max(0, extent_control.findData(current_extent)))
        to_face = is_sketch and current_extent == "to_face"
        self._field_containers["profileType"].setVisible(not is_face and not is_sketch)
        self._field_containers["sketchProfile"].setVisible(is_sketch)
        self._field_containers["sketchRegion"].setVisible(
            is_sketch
            and self._selected_region is not None
            and self._selected_region[0] == self._choice("sketchProfile")
        )
        self._field_containers["mode"].setVisible(not is_face)
        self._field_containers["radius"].setVisible(not is_face and not is_sketch)
        self._field_containers["profile_width"].setVisible(not is_face and not is_sketch)
        self._field_containers["profile_height"].setVisible(not is_face and not is_sketch)
        self._field_containers["extentMode"].setVisible(not is_face)
        self._field_containers["distance"].setVisible(not to_face)

    def _set_revolve_source_visibility(self) -> None:
        is_sketch = self._choice("revolveSource") == "sketch"
        for key in ("profileType", "radius", "profile_width", "profile_height"):
            self._field_containers[key].setVisible(not is_sketch)
        self._field_containers["sketchProfile"].setVisible(is_sketch)
        self._field_containers["sketchRegion"].setVisible(
            is_sketch
            and self._selected_region is not None
            and self._selected_region[0] == self._choice("sketchProfile")
        )
        use_sketch_axis = is_sketch and self._choice("axisSource") == "sketch_line"
        self._field_containers["axisSource"].setVisible(is_sketch)
        self._field_containers["axis"].setVisible(not use_sketch_axis)
        self._field_containers["axisLine"].setVisible(use_sketch_axis)

    def _refresh_revolve_axis_lines(self) -> None:
        control = cast("QComboBox", self._controls["axisLine"])
        sketch = self._sketches.get(self._choice("sketchProfile"))
        options = [("选择构造线", "")]
        if sketch is not None:
            options.extend(
                (f"构造线 · {entity.entity_id[:8]}", entity.entity_id)
                for entity in sketch.entities
                if isinstance(entity, LineEntity) and entity.construction
            )
        with QSignalBlocker(control):
            current = str(control.currentData())
            control.clear()
            for label, value in options:
                control.addItem(label, value)
            index = control.findData(current)
            control.setCurrentIndex(max(0, index))

    def _set_hole_source_visibility(self) -> None:
        is_sketch = self._choice("holeSource") == "sketch"
        self._field_containers["sketchProfile"].setVisible(is_sketch)
        self._field_containers["diameter"].setVisible(not is_sketch)

    def _emit_values(self, *_args: object) -> None:
        if self._command_id is not None:
            self.parameters_changed.emit(self.values())
