# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Canvas dimension command lifecycle: pick, preview, place and edit."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, cast, override
from uuid import uuid4

from PySide6.QtCore import QEvent, QObject, QPointF, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QWidget,
)

from mycad.core.angular_dimension import AngularSector, angular_sector
from mycad.core.cross_sketch_tangency import project_coplanar_vector
from mycad.core.dimension_styles import DimensionStyle
from mycad.core.polyline_curves import polyline_arc_segment
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    Point2D,
    PointEntity,
    PolylineEntity,
    RectangleEntity,
    Sketch,
    SketchEntity,
)
from mycad.core.sketch_constraints import (
    DIMENSION_KINDS,
    SketchConstraint,
    SketchConstraintSolveResult,
    SketchGeometryReference,
)
from mycad.ui.cad_icons import set_button_icon
from mycad.ui.dimension_presets import DimensionPresetDialog

if TYPE_CHECKING:
    from mycad.ui.sketch_editor import DimensionLayout, SketchEditorDialog

DEFAULT_NEW_DRAWING_DIMENSION_SCALE = 0.8

COMMANDS = (
    ("smart", "智能标注", "DIM · 选择线、圆、弧或两个捕捉点，移动鼠标并点击放置"),
    ("horizontal", "水平", "DIMLINEAR · 两点的水平投影距离"),
    ("vertical", "垂直", "DIMLINEAR · 两点的垂直投影距离"),
    ("aligned", "对齐", "DIMALIGNED · 沿两点连线的真实距离"),
    ("angle", "角度", "DIMANGULAR · 选择两条直线或线段，再点击放置角度"),
    ("radius", "半径", "DIMRADIUS · 选择圆或圆弧，点击放置半径"),
    ("diameter", "直径", "DIMDIAMETER · 选择圆或圆弧，点击放置直径"),
    ("arc_length", "弧长", "DIMARC · 选择圆弧，点击放置弧长"),
    ("continue", "连续", "DIMCONTINUE · 选择已有线性尺寸或沿上一尺寸的终点继续"),
    ("baseline", "基线", "DIMBASELINE · 选择已有尺寸或沿本组第一尺寸的起点标注"),
    ("ordinate", "坐标", "DIMORDINATE · 拾取基准点、测量点，再沿 X/Y 方向放置"),
)


def _point_segment_distance(p: Point2D, a: Point2D, b: Point2D) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = min(
        1.0, max(0.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / max(dx * dx + dy * dy, 1e-20))
    )
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def _point_references(entity: SketchEntity) -> tuple[SketchGeometryReference, ...]:
    identity = entity.entity_id
    if isinstance(entity, PointEntity):
        return (SketchGeometryReference(identity, "vertex", 0),)
    if isinstance(entity, CircleEntity):
        return (SketchGeometryReference(identity, "center"),)
    if isinstance(entity, ArcEntity):
        return tuple(SketchGeometryReference(identity, kind) for kind in ("start", "end", "center"))
    if isinstance(entity, LineEntity):
        return tuple(SketchGeometryReference(identity, kind) for kind in ("start", "end"))
    count = (
        4
        if isinstance(entity, RectangleEntity)
        else len(entity.points_mm)
        if isinstance(entity, PolylineEntity)
        else len(entity.control_points_mm)
    )
    return tuple(SketchGeometryReference(identity, "vertex", i) for i in range(count))


def _segment_references(entity: SketchEntity) -> tuple[SketchGeometryReference, ...]:
    if isinstance(entity, LineEntity):
        return (SketchGeometryReference(entity.entity_id, "geometry"),)
    if isinstance(entity, RectangleEntity):
        count = 4
    elif isinstance(entity, PolylineEntity):
        count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
        if entity.bulges:
            return tuple(
                SketchGeometryReference(entity.entity_id, "segment", i)
                for i in range(count)
                if entity.bulges[i] == 0
            )
    else:
        return ()
    return tuple(SketchGeometryReference(entity.entity_id, "segment", i) for i in range(count))


def _segment_ends(
    entity: SketchEntity, ref: SketchGeometryReference
) -> tuple[SketchGeometryReference, ...]:
    if isinstance(entity, LineEntity):
        return (
            SketchGeometryReference(entity.entity_id, "start"),
            SketchGeometryReference(entity.entity_id, "end"),
        )
    count = (
        4 if isinstance(entity, RectangleEntity) else len(cast("PolylineEntity", entity).points_mm)
    )
    index = ref.index or 0
    return (
        SketchGeometryReference(entity.entity_id, "vertex", index),
        SketchGeometryReference(entity.entity_id, "vertex", (index + 1) % count),
    )


class DimensionTools(QObject):
    """One shared pointer workflow for local drafts and committed sketches."""

    committed_requested = Signal(object, object)
    preview_requested = Signal(object, object, int)
    status_changed = Signal(str)
    command_reset = Signal()
    operation_started = Signal()

    def __init__(self, editor: SketchEditorDialog) -> None:
        super().__init__(editor)
        self.editor = editor
        self.canvas = editor.canvas
        self.mode: str | None = None
        self._command_linear_direction: Point2D | None = None
        self._preset_format: tuple[int, float] | None = None
        self._drawing_style: DimensionStyle | None = None
        self._follow_drawing_style = False
        self._previous_format: tuple[int, float] | None = None
        self.drawing_style_manager: Callable[[], None] | None = None
        self._new_dimension_driving = True
        self._new_anchor_mode = "auto"
        self.references: list[SketchGeometryReference] = []
        self.original: Sketch | None = None
        self.candidate: SketchConstraint | None = None
        self.last_dimension: tuple[Sketch, SketchConstraint] | None = None
        self.baseline_reference: SketchGeometryReference | None = None
        self._editing = False
        self._input_valid = True
        self._dragging: str | None = None
        self._drag_start = QPointF()
        self._drag_moved = False
        self._new_driving = False
        self._busy = False
        self._branch_confirmed = False
        self._presentation_only = False
        self._preview_result: (
            tuple[Sketch, SketchConstraint, SketchConstraintSolveResult] | None
        ) = None
        self._preview_generation = 0
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(100)
        self._preview_timer.timeout.connect(self._send_preview)
        self.buttons: dict[str, QToolButton] = {}
        for key, label, tip in COMMANDS:
            button = QToolButton()
            button.setText(label)
            button.setToolTip(tip + "；Esc 取消，滚轮缩放／中键平移")
            button.setCheckable(True)
            button.setIconSize(QSize(24, 24))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setObjectName("dimension-" + key)
            set_button_icon(button, "dim-" + key)
            button.clicked.connect(lambda _checked=False, command=key: self.start(command))
            editor.dimension_toolbar.addWidget(button)
            self.buttons[key] = button
        self.preset_button = QToolButton()
        self.preset_button.setText("标注预设")
        self.preset_button.setToolTip("保存并选择本机新建标注的精度和比例预设")
        self.preset_button.setIconSize(QSize(24, 24))
        self.preset_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        set_button_icon(self.preset_button, "settings")
        self.preset_button.clicked.connect(self.open_format_presets)
        editor.dimension_toolbar.addWidget(self.preset_button)
        editor.dimension_toolbar.addWidget(QLabel("标注层"))
        self.layer_combo = QComboBox()
        self.layer_combo.setMinimumWidth(105)
        editor.dimension_toolbar.addWidget(self.layer_combo)
        self.layer_combo.currentIndexChanged.connect(self._layer_changed)
        self.sync_layer_combo()
        self.command_bar = QWidget()
        self.command_bar.setObjectName("dimensionCommandBar")
        row = QHBoxLayout(self.command_bar)
        self.command_row = row
        row.setContentsMargins(4, 2, 4, 2)
        self.prompt = QLabel("选择图元或捕捉点")
        self.prompt.setWordWrap(True)
        self.prompt.setMinimumWidth(100)
        self.prompt.setMaximumWidth(280)
        self.driving_check = QCheckBox("驱动尺寸")
        self.driving_check.setChecked(True)
        self.anchor_combo = QComboBox()
        self.anchor_combo.setObjectName("dimensionAnchorMode")
        for text, mode in (
            ("自动固定", "auto"),
            ("固定起点", "start"),
            ("固定终点", "end"),
            ("中心对称", "symmetric"),
        ):
            self.anchor_combo.addItem(text, mode)
        self.anchor_combo.setToolTip(
            "本次修改的固定方式；自动优先遵守已有定位关系，否则保持首点/圆心。不会增加永久固定关系。"
        )
        self.diagnostics_label = QLabel()
        self.diagnostics_label.setObjectName("dimensionSolveDiagnostics")
        self.diagnostics_label.setWordWrap(True)
        self.driving_check.setToolTip("关闭：参考尺寸，仅显示实测值；开启：修改数值将改变几何")
        self.value_editor = QDoubleSpinBox()
        self.value_editor.setObjectName("dimensionInlineValue")
        self.value_editor.setDecimals(4)
        self.value_editor.setRange(-1e9, 1e9)
        self.value_editor.setKeyboardTracking(False)
        self.value_editor.setReadOnly(False)
        self.precision = QSpinBox()
        self.precision.setRange(0, 8)
        self.precision.setValue(2)
        self.precision.setPrefix("小数 ")
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.1, 100)
        self.scale.setValue(
            DEFAULT_NEW_DRAWING_DIMENSION_SCALE if self.canvas.select_committed_entities else 1
        )
        self.scale.setPrefix("比例 ")
        self.text_override = QLineEdit()
        self.text_override.setObjectName("dimensionTextOverride")
        # Qt counts UTF-16 units; a Unicode character may occupy two units.
        self.text_override.setMaxLength(512)
        self.text_override.setPlaceholderText("标注文字")
        self.text_override.setToolTip("留空显示默认尺寸；<> 代表实际数值，文字不会改变驱动值。")
        self.text_override.setMaximumWidth(150)
        self.text_override_label = QLabel("文字")
        self.apply_button = QPushButton("确认修改")
        self.cancel_button = QPushButton("取消 / Esc")
        for widget in (
            self.prompt,
            self.driving_check,
            self.anchor_combo,
            self.value_editor,
            self.precision,
            self.scale,
            self.text_override_label,
            self.text_override,
            self.apply_button,
            self.cancel_button,
        ):
            row.addWidget(widget)
        row.addWidget(self.diagnostics_label)
        self.inline_box = QWidget(self.canvas)
        self.inline_box.setObjectName("dimensionInlineEditor")
        self.inline_box.setStyleSheet("background: #f0fdfa; border: 1px solid #157080;")
        self.inline_layout = QHBoxLayout(self.inline_box)
        self.inline_layout.setContentsMargins(3, 3, 3, 3)
        self.inline_box.hide()
        editor.dimension_controls_layout.addWidget(self.command_bar)
        self.command_bar.hide()
        self.value_editor.valueChanged.connect(self._value_changed)
        self.driving_check.toggled.connect(self._driving_changed)
        self.anchor_combo.currentIndexChanged.connect(self._anchor_changed)
        self.precision.valueChanged.connect(self._format_changed)
        self.scale.valueChanged.connect(self._format_changed)
        self.text_override.textChanged.connect(self._text_override_changed)
        self.apply_button.clicked.connect(self.apply_edit)
        self.cancel_button.clicked.connect(self.cancel)
        self.canvas.installEventFilter(self)
        self.value_editor.installEventFilter(self)
        self.canvas.changed.connect(self._check_source)
        editor.plane_combo.currentTextChanged.connect(self.cancel)

    def sync_layer_combo(self) -> None:
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        self.layer_combo.addItem("使用当前层", ".")
        for layer in self.editor.layer_table.layers:
            self.layer_combo.addItem(layer.name, layer.name)
        self.layer_combo.setCurrentIndex(self.layer_combo.findData(self.editor.dimension_layer))
        self.layer_combo.blockSignals(False)

    def _layer_changed(self, _index: int) -> None:
        target = str(self.layer_combo.currentData())
        self.editor.request_layer_update(self.editor.layer_table, target)

    def _local(self, sketch: Sketch, point: Point2D) -> Point2D:
        return sketch.frame.world_to_local(self.editor.current_frame().local_to_world(point))

    def _display(self, dimension: SketchConstraint) -> SketchConstraint:
        if self.original is None:
            return dimension

        def moved(p: Point2D | None) -> Point2D | None:
            if p is None or self.original is None:
                return None
            return self.editor.current_frame().world_to_local(self.original.frame.local_to_world(p))

        return replace(
            dimension,
            position_mm=moved(dimension.position_mm),
            text_position_mm=moved(dimension.text_position_mm),
        )

    def _sketches(self) -> tuple[Sketch, ...]:
        visible = set(self.canvas.dimension_entities())
        return tuple(
            s
            for s in self.editor.dimension_sources()
            if any(e.entity_id in visible for e in s.entities)
        )

    def _current(self, original: Sketch) -> Sketch | None:
        return next((s for s in self._sketches() if s.sketch_id == original.sketch_id), None)

    def _check_source(self) -> None:
        if self.original is not None and not self._busy:
            current = self._current(self.original)
            if current != self.original:
                self.cancel()

    def start(self, mode: str) -> None:
        self.operation_started.emit()
        self.cancel()
        self.text_override.clear()
        if self._preset_format is not None:
            self.precision.setValue(self._preset_format[0])
            self.scale.setValue(self._preset_format[1])
        self.driving_check.setChecked(self._new_dimension_driving)
        self.anchor_combo.setCurrentIndex(self.anchor_combo.findData(self._new_anchor_mode))
        self._sync_anchor_control()
        if mode not in ("continue", "baseline"):
            self.last_dimension = None
            self.baseline_reference = None
        self.canvas.end_line_chain()
        self.editor.tool_combo.setCurrentText("选择元素")
        self.mode = mode
        self.buttons["smart" if mode == "linear" else mode].setChecked(True)
        self.command_bar.show()
        self.apply_button.hide()
        self.canvas.setFocus()
        self.prompt.setText(
            "拾取基准点，再拾取测量点" if mode == "ordinate" else "选择图元或捕捉点"
        )
        if mode in ("continue", "baseline"):
            if self.last_dimension is not None:
                self._seed_chain(*self.last_dimension)
            else:
                self.prompt.setText("选择已有线性尺寸")
        self._status(self.prompt.text())

    def _seed_chain(self, sketch: Sketch, dimension: SketchConstraint) -> None:
        if dimension.kind not in ("length", "distance"):
            self._status("连续／基线标注需要线性尺寸")
            return
        current = self._current(sketch)
        if current is None:
            return
        if not any(c.constraint_id == dimension.constraint_id for c in current.constraints):
            self.last_dimension = None
            self.baseline_reference = None
            self._status("原尺寸已被撤销或删除，请选择已有线性尺寸")
            return
        refs = dimension.references
        if dimension.kind == "length":
            entity = next(e for e in sketch.entities if e.entity_id == refs[0].entity_id)
            refs = _segment_ends(entity, refs[0])
        first = (self.baseline_reference or refs[0]) if self.mode == "baseline" else refs[-1]
        if first.entity_id not in {e.entity_id for e in current.entities}:
            self.baseline_reference = None
            self._status("尺寸引用已改变，请选择已有线性尺寸")
            return
        self.original = current
        self.references = [first]
        self.canvas.dimension_references = tuple(self.references)
        self.prompt.setText("拾取下一个测量点")

    def cancel(self, *_args: object) -> None:
        if self.mode is not None or self._editing:
            self.canvas.clear_dimension_snap_preview()
        self.mode = None
        self._command_linear_direction = None
        self.command_reset.emit()
        self.references = []
        self.original = None
        self.candidate = None
        self._editing = False
        self._input_valid = True
        self._new_driving = False
        self._drag_moved = False
        self._dragging = None
        self._branch_confirmed = False
        self._presentation_only = False
        self._preview_result = None
        self._preview_generation += 1
        self._preview_timer.stop()
        self._busy = False
        self._hide_inline_value()
        self.canvas.dimension_candidate = None
        self.canvas.dimension_references = ()
        self.editor.clear_dimension_preview()
        self.command_bar.hide()
        self.diagnostics_label.clear()
        for button in self.buttons.values():
            button.setChecked(False)
        self.canvas.update()

    def _status(self, text: str) -> None:
        self.editor.status_label.setText(text)
        self.prompt.setText(text)
        self.status_changed.emit(text)

    def set_drawing_style_manager(self, manager: Callable[[], None]) -> None:
        """Expose the document style manager instead of the local preset entry."""
        self.drawing_style_manager = manager
        self.preset_button.setText("标注样式")
        self.preset_button.setToolTip("管理当前图纸标注样式，也可打开本机标注预设。")

    def open_format_presets(self) -> None:
        if self.mode is not None or self._editing:
            self._status("请先完成或取消当前标注，再设置标注预设。")
            return
        if self.drawing_style_manager is not None:
            self.drawing_style_manager()
            return
        self.open_local_format_presets()

    def open_local_format_presets(self) -> None:
        dialog = DimensionPresetDialog(
            QSettings("MyCAD", "MyCAD"), self.precision.value(), self.scale.value(), self.editor
        )
        if dialog.exec() == int(QDialog.DialogCode.Accepted):
            self._drawing_style = None
            self._follow_drawing_style = False
            self._previous_format = None
            self.precision.setValue(dialog.precision.value())
            self.scale.setValue(dialog.scale.value())
            self._preset_format = (self.precision.value(), self.scale.value())
            self._status("新建标注的格式预设已应用。")

    def set_drawing_style(self, style: DimensionStyle | None) -> None:
        """Choose the current drawing style for subsequently created dimensions."""
        if not self._follow_drawing_style and style is not None:
            self._previous_format = (self.precision.value(), self.scale.value())
        self._drawing_style = style
        self._follow_drawing_style = True
        if style is not None:
            self._preset_format = (style.precision, style.scale)
            self.precision.setValue(style.precision)
            self.scale.setValue(style.scale)
        elif self._previous_format is not None:
            self._preset_format = self._previous_format
            self.precision.setValue(self._previous_format[0])
            self.scale.setValue(self._previous_format[1])

    @property
    def drawing_style_active(self) -> bool:
        return self._follow_drawing_style

    @property
    def command_editing_value(self) -> bool:
        return self._editing and self._new_driving

    def command_point(self, point: Point2D) -> bool:
        """Apply a command-line point through the same path as a canvas pick."""
        if self.mode is None or self._busy or self._editing:
            return False
        before = (
            self.original,
            tuple(self.references),
            self.candidate,
            self.mode,
            self._editing,
            self._busy,
        )
        self._click(point)
        return before != (
            self.original,
            tuple(self.references),
            self.candidate,
            self.mode,
            self._editing,
            self._busy,
        )

    def command_value(self, value: float) -> bool:
        if not self.command_editing_value or not math.isfinite(value):
            return False
        if not self.value_editor.minimum() <= value <= self.value_editor.maximum():
            self._status("尺寸值超出允许范围。")
            return False
        self.value_editor.setValue(value)
        self.apply_edit()
        return self._busy or not self.command_editing_value

    def command_accept_value(self) -> bool:
        return self.command_value(self.value_editor.value())

    def command_linear_axis(self, axis: str) -> bool:
        if self.mode not in ("linear", "horizontal", "vertical") or axis not in (
            "horizontal",
            "vertical",
        ):
            return False
        self.mode = axis
        self._command_linear_direction = None
        if self.candidate is not None:
            location = self._display(self.candidate).position_mm
            if location is not None:
                self._build_candidate(location)
        label = "水平尺寸" if axis == "horizontal" else "垂直尺寸"
        self._status(
            f"{label}：指定标注位置。" if self.candidate else f"{label}：选择对象或两个点。"
        )
        return True

    def command_linear_rotation(self, angle: float) -> bool:
        if self.mode not in ("linear", "horizontal", "vertical") or not math.isfinite(angle):
            return False
        radians = math.radians(angle % 360.0)
        self._command_linear_direction = (math.cos(radians), math.sin(radians))
        self.mode = "horizontal"
        if self.candidate is not None:
            location = self._display(self.candidate).position_mm
            if location is not None:
                self._build_candidate(location)
        self._status("旋转线性尺寸：指定标注位置。")
        return True

    def _entities(self) -> dict[str, SketchEntity]:
        return {e.entity_id: e for e in self.canvas.visible_snap_entities()}

    def _pick(self, point: Point2D) -> tuple[Sketch, tuple[SketchGeometryReference, ...]] | None:
        entities = self._entities()
        candidates: list[tuple[float, Sketch, tuple[SketchGeometryReference, ...]]] = []
        tolerance = 12 / self.canvas.view_scale
        for sketch in self._sketches():
            if self.original is not None and sketch.sketch_id != self.original.sketch_id:
                continue
            for source in sketch.entities:
                entity = entities.get(source.entity_id)
                layer = sketch.layers.get(source.layer_name)
                if (
                    entity is None
                    or not layer.displayed
                    or (layer.locked and self.driving_check.isChecked())
                ):
                    continue
                if self.mode not in ("angle", "radius", "diameter", "arc_length"):
                    for ref in _point_references(entity):
                        location = self.canvas.point_for_reference(ref, entities)
                        if location is not None and math.dist(point, location) <= tolerance:
                            candidates.append(
                                (math.dist(point, location) - tolerance * 2, sketch, (ref,))
                            )
                if self.references and self.mode != "angle":
                    continue
                if isinstance(entity, PolylineEntity) and self.mode in (
                    "smart",
                    "radius",
                    "diameter",
                    "arc_length",
                ):
                    for index, bulge in enumerate(entity.bulges):
                        if bulge == 0:
                            continue
                        arc = polyline_arc_segment(entity, index)
                        angle = math.degrees(
                            math.atan2(point[1] - arc.center_mm[1], point[0] - arc.center_mm[0])
                        )
                        offset = (
                            (angle - arc.start_angle_deg) % 360
                            if arc.sweep_angle_deg > 0
                            else (arc.start_angle_deg - angle) % 360
                        )
                        distance = abs(math.dist(point, arc.center_mm) - arc.radius_mm)
                        if offset <= abs(arc.sweep_angle_deg) + 1e-7 and distance <= tolerance:
                            candidates.append(
                                (
                                    distance,
                                    sketch,
                                    (SketchGeometryReference(entity.entity_id, "segment", index),),
                                )
                            )
                if isinstance(entity, CircleEntity | ArcEntity):
                    if self.mode not in ("smart", "radius", "diameter", "arc_length"):
                        continue
                    if self.mode == "arc_length" and not isinstance(entity, ArcEntity):
                        continue
                    angle = math.degrees(
                        math.atan2(point[1] - entity.center_mm[1], point[0] - entity.center_mm[0])
                    )
                    if isinstance(entity, ArcEntity):
                        offset = (
                            (angle - entity.start_angle_deg) % 360
                            if entity.sweep_angle_deg > 0
                            else (entity.start_angle_deg - angle) % 360
                        )
                        if offset > abs(entity.sweep_angle_deg) + 1e-7:
                            continue
                    distance = abs(math.dist(point, entity.center_mm) - entity.radius_mm)
                    if distance <= tolerance:
                        candidates.append(
                            (
                                distance,
                                sketch,
                                (SketchGeometryReference(entity.entity_id, "geometry"),),
                            )
                        )
                elif self.mode not in ("radius", "diameter", "arc_length", "ordinate"):
                    for ref in _segment_references(entity):
                        segment = self.canvas.line_for_reference(ref, entities)
                        if segment is not None:
                            distance = _point_segment_distance(point, *segment)
                            if distance <= tolerance:
                                refs = (
                                    (ref,) if self.mode == "angle" else _segment_ends(entity, ref)
                                )
                                candidates.append((distance, sketch, refs))
        if not candidates:
            return None
        _, sketch, refs = min(candidates, key=lambda item: item[0])
        return sketch, refs

    def _measure(self, sketch: Sketch, constraint: SketchConstraint) -> float:
        entities = {e.entity_id: e for e in sketch.entities}
        first = constraint.references[0]
        if constraint.kind in ("length", "distance"):
            if constraint.kind == "length":
                segment = self.canvas.line_for_reference(first, entities)
            else:
                a = self.canvas.point_for_reference(first, entities)
                b = self.canvas.point_for_reference(constraint.references[1], entities)
                segment = (a, b) if a is not None and b is not None else None
            if segment is None:
                raise ValueError("无法测量该引用")
            a, b = segment
            if constraint.axis == "aligned":
                return math.dist(a, b)
            delta = (
                (b[0] - a[0]) * constraint.projection_axis[0]
                + (b[1] - a[1]) * constraint.projection_axis[1]
                if constraint.projection_axis is not None
                else b[0] - a[0]
                if constraint.axis in ("horizontal", "ordinate_x")
                else b[1] - a[1]
            )
            return delta if constraint.axis.startswith("ordinate_") else abs(delta)
        if constraint.kind == "angle":
            a = self.canvas.line_for_reference(first, entities)
            b = self.canvas.line_for_reference(constraint.references[1], entities)
            if a is None or b is None:
                raise ValueError("请选择两条直线或线段")
            u = (a[1][0] - a[0][0], a[1][1] - a[0][1])
            v = (b[1][0] - b[0][0], b[1][1] - b[0][1])
            cross = u[0] * v[1] - u[1] * v[0]
            if abs(cross) < 1e-10:
                raise ValueError("平行直线不能放置角度尺寸")
            return math.degrees(math.atan2(cross, u[0] * v[0] + u[1] * v[1]))
        entity = entities[first.entity_id]
        if (
            isinstance(entity, PolylineEntity)
            and first.kind == "segment"
            and first.index is not None
        ):
            entity = polyline_arc_segment(entity, first.index)
        if not isinstance(entity, CircleEntity | ArcEntity):
            raise ValueError("请选择圆或圆弧")
        if constraint.kind == "arc_length" and isinstance(entity, ArcEntity):
            return entity.radius_mm * abs(math.radians(entity.sweep_angle_deg))
        return entity.radius_mm * (2 if constraint.kind == "diameter" else 1)

    def _angle_sector(self, sketch: Sketch, constraint: SketchConstraint) -> AngularSector | None:
        if constraint.kind != "angle" or constraint.position_mm is None:
            return None
        entities = {entity.entity_id: entity for entity in sketch.entities}
        first = self.canvas.line_for_reference(constraint.references[0], entities)
        second = self.canvas.line_for_reference(constraint.references[1], entities)
        if first is None or second is None:
            return None
        return angular_sector(first, second, constraint.position_mm)

    def _build_candidate(self, point: Point2D) -> bool:
        if self.original is None or not self.references:
            return False
        frame = self.editor.current_frame()
        refs = tuple(self.references)
        first_entity = next(e for e in self.original.entities if e.entity_id == refs[0].entity_id)
        kind = "distance"
        axis = "aligned"
        if self.mode == "angle":
            if len(refs) != 2:
                return False
            kind = "angle"
        elif (
            isinstance(first_entity, CircleEntity | ArcEntity) and refs[0].kind == "geometry"
        ) or (
            isinstance(first_entity, PolylineEntity)
            and refs[0].kind == "segment"
            and refs[0].index is not None
            and bool(first_entity.bulges)
            and first_entity.bulges[refs[0].index] != 0
        ):
            kind = (
                ("diameter" if isinstance(first_entity, CircleEntity) else "radius")
                if self.mode == "smart"
                else str(self.mode)
            )
        elif len(refs) != 2:
            return False
        elif self.mode in ("horizontal", "vertical"):
            axis = self.mode
        elif self.mode in ("continue", "baseline") and self.last_dimension is not None:
            axis = self.last_dimension[1].axis
        elif self.mode in ("smart", "linear", "ordinate"):
            entities = self._entities()
            a = self.canvas.point_for_reference(refs[0], entities)
            b = self.canvas.point_for_reference(refs[1], entities)
            if a is not None and b is not None:
                if point[1] < min(a[1], b[1]) or point[1] > max(a[1], b[1]):
                    axis = "horizontal"
                elif point[0] < min(a[0], b[0]) or point[0] > max(a[0], b[0]):
                    axis = "vertical"
            if self.mode == "ordinate":
                axis = "ordinate_y" if axis == "vertical" else "ordinate_x"
        projection_axis: Point2D | None = None
        if axis != "aligned":
            if self._command_linear_direction is not None:
                projection_axis = project_coplanar_vector(
                    self._command_linear_direction, frame, self.original.frame
                )
            elif self.mode in ("continue", "baseline") and self.last_dimension is not None:
                projection_axis = self.last_dimension[1].projection_axis
            elif (
                self.original.frame.u_axis != frame.u_axis
                or self.original.frame.v_axis != frame.v_axis
            ):
                view_axis: Point2D = (
                    (1.0, 0.0) if axis in ("horizontal", "ordinate_x") else (0.0, 1.0)
                )
                projection_axis = project_coplanar_vector(view_axis, frame, self.original.frame)
        try:
            candidate = SketchConstraint.from_mapping(
                {
                    "constraint_id": self.candidate.constraint_id
                    if self.candidate is not None
                    else uuid4().hex,
                    "kind": kind,
                    "references": [r.to_mapping() for r in refs],
                    "source": "user",
                    "anchor_mode": str(self.anchor_combo.currentData())
                    if kind in ("length", "distance")
                    else "auto",
                    "layer_name": self.editor.canvas.active_layer_name
                    if self.editor.dimension_layer == "."
                    else self.editor.dimension_layer,
                    "driving": False,
                    "unit": "deg" if kind == "angle" else "mm",
                    "axis": axis,
                    **({"projection_axis": list(projection_axis)} if projection_axis else {}),
                    "position_mm": list(self._local(self.original, point)),
                    "precision": self.precision.value(),
                    "scale": self.scale.value(),
                    **({"style_name": self._drawing_style.name} if self._drawing_style else {}),
                    **(
                        {"text_override": self.text_override.text()}
                        if self.text_override.text()
                        else {}
                    ),
                }
            )
            target = self.editor.layer_table.get(candidate.layer_name or "0")
            if not target.displayed or target.locked:
                raise ValueError("标注层已关闭、冻结或锁定，请先更改图层状态或标注层")
            measured = self._measure(self.original, candidate)
            if kind != "angle" and not axis.startswith("ordinate_") and measured <= 1e-10:
                raise ValueError("尺寸投影为零，请移动鼠标切换方向")
            self.candidate = replace(candidate, value=measured)
            self._sync_anchor_control()
            self.canvas.dimension_candidate = self._display(self.candidate)
            self.value_editor.blockSignals(True)
            sector = self._angle_sector(self.original, self.candidate)
            self.value_editor.setValue(
                math.degrees(sector.sweep) if sector is not None else measured
            )
            self.value_editor.blockSignals(False)
            self._status("移动鼠标，点击放置尺寸；可在标注选项设置文字，Esc 取消")
        except ValueError as exc:
            self.candidate = None
            self.canvas.dimension_candidate = None
            self._status(str(exc))
        self.canvas.update()
        return self.candidate is not None

    def _click(self, point: Point2D) -> None:
        if self._busy:
            return
        if self.candidate is not None:
            if not self._build_candidate(point):
                return
            if self.driving_check.isChecked():
                self._editing = True
                self._new_driving = True
                self.apply_button.show()
                self.value_editor.setFocus()
                self.value_editor.selectAll()
                self._show_inline_value()
                self._value_changed()
                self._status("输入驱动尺寸并确认；Esc 取消")
            else:
                self.apply_edit()
            return
        hit = self._dimension_at(point)
        if self.mode in ("continue", "baseline") and hit is not None and not self.references:
            sketch, dimension, _part = hit
            self.last_dimension = (sketch, dimension)
            self.baseline_reference = None
            self._seed_chain(sketch, dimension)
            return
        picked = self._pick(point)
        if picked is None:
            self._status("请在同一草图的可见图元或捕捉点上拾取")
            return
        sketch, refs = picked
        self.original = sketch
        for ref in refs:
            if ref not in self.references:
                self.references.append(ref)
        self.canvas.dimension_references = tuple(self.references)
        self._build_candidate(point)
        if (
            self.candidate is None
            and len(self.references) == 1
            and (self.references[0].kind != "geometry" or self.mode == "angle")
        ):
            self._status("选择第二个捕捉点" if self.mode != "angle" else "选择第二条直线或线段")

    def _dimension_at(self, point: Point2D) -> tuple[Sketch, SketchConstraint, str] | None:
        screen = QPointF(self.canvas.local_to_screen(point))
        entities = self.canvas.dimension_entities()
        label_rectangles = self.canvas.dimension_label_rectangles()
        visible_ids = {dimension.constraint_id for dimension in self.canvas.visible_dimensions()}
        candidates: list[tuple[Sketch, SketchConstraint, DimensionLayout | None]] = []
        for sketch in self._sketches():
            for dimension in reversed(sketch.constraints):
                if (
                    dimension.kind not in DIMENSION_KINDS
                    or dimension.constraint_id not in visible_ids
                ):
                    continue
                layer = self.canvas.annotation_layer(dimension)
                if not layer.displayed or layer.locked:
                    continue
                if any(ref.entity_id not in entities for ref in dimension.references):
                    continue
                previous = self.original
                self.original = sketch
                shown = self._display(dimension)
                self.original = previous
                layout = self.canvas.dimension_layout(shown, entities)
                candidates.append((sketch, dimension, layout))
        for sketch, dimension, _layout in candidates:
            label_rect = label_rectangles.get(dimension.constraint_id)
            if label_rect is not None and label_rect.adjusted(-4, -4, 4, 4).contains(screen):
                return (sketch, dimension, "text")
        local_point = (screen.x(), screen.y())
        for sketch, dimension, layout in candidates:
            if layout is None:
                continue
            draggable_lines = (
                layout.lines[2:]
                if dimension.kind in ("length", "distance")
                and not dimension.axis.startswith("ordinate_")
                else layout.lines
            )
            for a, b in (
                *draggable_lines,
                *self.canvas.dimension_arrow_segments(layout, dimension.scale, dimension),
            ):
                if _point_segment_distance(local_point, (a.x(), a.y()), (b.x(), b.y())) <= 5:
                    return (sketch, dimension, "line")
        return None

    def edit(self, sketch: Sketch, dimension: SketchConstraint) -> None:
        layer = self.canvas.annotation_layer(dimension)
        if not layer.displayed or layer.locked:
            self._status("标注层不可编辑，请先显示、解冻或解锁")
            return
        self.operation_started.emit()
        self.cancel()
        self.editor.tool_combo.setCurrentText("选择元素")
        self.original = sketch
        self.candidate = dimension
        self._editing = True
        selectable = {e.entity_id for e in self.canvas.selectable_entities()}
        self.canvas.selected_entity_ids = {
            ref.entity_id for ref in dimension.references if ref.entity_id in selectable
        }
        self.canvas.selected_constraint_ids = {dimension.constraint_id}
        self.canvas.changed.emit()
        self.anchor_combo.blockSignals(True)
        self.anchor_combo.setCurrentIndex(self.anchor_combo.findData(dimension.anchor_mode))
        self.anchor_combo.blockSignals(False)
        self.command_bar.show()
        self.apply_button.show()
        self.value_editor.blockSignals(True)
        sector = self._angle_sector(sketch, dimension)
        self.value_editor.setValue(
            math.degrees(sector.sweep) if sector is not None else dimension.value or 0
        )
        self.value_editor.blockSignals(False)
        self.driving_check.setChecked(dimension.driving)
        self.precision.blockSignals(True)
        self.scale.blockSignals(True)
        self.precision.setValue(dimension.precision)
        self.scale.setValue(dimension.scale)
        self.precision.blockSignals(False)
        self.scale.blockSignals(False)
        self.text_override.blockSignals(True)
        self.text_override.setText(dimension.text_override or "")
        self.text_override.blockSignals(False)
        self.value_editor.setReadOnly(not dimension.driving)
        self.value_editor.setFocus()
        self.value_editor.selectAll()
        self._sync_anchor_control()
        self._show_inline_value()
        self._status("编辑尺寸；参考尺寸显示实测值，驱动尺寸改变几何")

    def _hide_inline_value(self) -> None:
        self.inline_box.hide()
        self.command_row.insertWidget(3, self.value_editor)

    def _show_inline_value(self) -> None:
        if self.candidate is None:
            return
        layout = self.canvas.dimension_layout(
            self._display(self.candidate), self.canvas.dimension_entities()
        )
        if layout is not None:
            self.inline_layout.addWidget(self.value_editor)
            self.inline_box.adjustSize()
            self.inline_box.move(
                max(0, min(self.canvas.width() - self.inline_box.width(), int(layout.label.x()))),
                max(
                    0,
                    min(
                        self.canvas.height() - self.inline_box.height(), int(layout.label.y() + 12)
                    ),
                ),
            )
            self.inline_box.show()
            self.inline_box.raise_()
            self.value_editor.window().activateWindow()
            self.value_editor.setFocus()
            self.value_editor.selectAll()

    def _sync_anchor_control(self) -> None:
        self.anchor_combo.setEnabled(
            self.driving_check.isChecked()
            and (self.candidate is None or self.candidate.kind in ("length", "distance"))
        )

    def _anchor_changed(self, _index: int) -> None:
        mode = str(self.anchor_combo.currentData())
        if not self._editing or self._new_driving:
            self._new_anchor_mode = mode
        if self.candidate is not None and self.candidate.kind in ("length", "distance"):
            self.candidate = replace(self.candidate, anchor_mode=mode)
            self._preview_result = None
            self._branch_confirmed = False
            self._value_changed()

    def _driving_changed(self, driving: bool) -> None:
        if not self._editing or self._new_driving:
            self._new_dimension_driving = driving
        self.value_editor.setReadOnly(not driving)
        self._sync_anchor_control()
        self._value_changed()

    def _format_changed(self, *_args: object) -> None:
        if self._preset_format is not None and self.mode is not None and not self._editing:
            self._preset_format = (self.precision.value(), self.scale.value())
            if self._drawing_style is not None and (
                self.precision.value() != self._drawing_style.precision
                or self.scale.value() != self._drawing_style.scale
            ):
                self._drawing_style = None
                self._follow_drawing_style = False
        if self.candidate is not None:
            changed = (
                self.candidate.precision != self.precision.value()
                or self.candidate.scale != self.scale.value()
            )
            self.candidate = replace(
                self.candidate,
                precision=self.precision.value(),
                scale=self.scale.value(),
                style_name=None if changed else self.candidate.style_name,
            )
            self.canvas.dimension_candidate = self._display(self.candidate)
            self.canvas.update()
            if self._editing and self.candidate.driving and self._input_valid:
                self._queue_preview()

    def _text_override_changed(self, text: str) -> None:
        if len(text) > 256 or (text and not text.isprintable()):
            self._input_valid = False
            self.apply_button.setEnabled(False)
            self._status("标注文字须为 256 字以内的可显示字符")
            return
        self._input_valid = True
        if self.candidate is not None:
            self.candidate = replace(self.candidate, text_override=text or None)
            self.canvas.dimension_candidate = self._display(self.candidate)
            self.canvas.update()
            if self._editing and self.candidate.driving:
                self._preview_result = None
                self._queue_preview()
            else:
                self.apply_button.setEnabled(True)

    def _value_changed(self, *_args: object) -> None:
        if self.candidate is None or self.original is None:
            return
        if len(self.text_override.text()) > 256 or (
            self.text_override.text() and not self.text_override.text().isprintable()
        ):
            self._input_valid = False
            return
        try:
            value = (
                self.value_editor.value()
                if self.driving_check.isChecked()
                else self._measure(self.original, self.candidate)
            )
            if self.driving_check.isChecked():
                sector = self._angle_sector(self.original, self.candidate)
                if sector is not None and value >= 0:
                    value = sector.solver_degrees(value)
            revised = replace(self.candidate, driving=self.driving_check.isChecked(), value=value)
            if revised != self.candidate:
                self._branch_confirmed = False
                self._preview_result = None
            self.candidate = revised
            self._sync_anchor_control()
            self._input_valid = True
            self.canvas.dimension_candidate = self._display(self.candidate)
            self.canvas.update()
            if not self.candidate.driving:
                self.apply_button.setText("确认修改")
                self.apply_button.setEnabled(True)
                self.editor.clear_dimension_preview()
            if self._editing and self.candidate.driving:
                self._queue_preview()
        except ValueError as exc:
            self._input_valid = False
            self._preview_result = None
            self.apply_button.setEnabled(False)
            self._status(str(exc))

    def _queue_preview(self) -> None:
        if self.original is None or self.candidate is None:
            return
        if (
            self._preview_result is not None
            and self._preview_result[:2] == (self.original, self.candidate)
            and self._preview_result[2].status == "success"
        ):
            return
        self._preview_generation += 1
        self.editor.clear_dimension_preview()
        self.diagnostics_label.setText("求解中…")
        self.apply_button.setText("预览中…")
        self.apply_button.setEnabled(False)
        if self.original.sketch_id == self.editor.draft_sketch_id:
            result = self.editor.preview_dimension(self.original, self.candidate)
            self.complete_preview(self._preview_generation, self.original, self.candidate, result)
        else:
            self._preview_timer.start()

    def _send_preview(self) -> None:
        if self.original is not None and self.candidate is not None:
            self.preview_requested.emit(self.original, self.candidate, self._preview_generation)

    def complete_preview(
        self,
        generation: int,
        original: Sketch,
        candidate: SketchConstraint,
        result: SketchConstraintSolveResult,
    ) -> None:
        if generation != self._preview_generation or (self.original, self.candidate) != (
            original,
            candidate,
        ):
            return
        if self._current(original) != original:
            self.cancel()
            self._status("草图已改变，请重新拾取尺寸")
            return
        self._preview_result = (original, candidate, result)
        self.apply_button.setEnabled(True)
        self.apply_button.setText("确认修改" if result.status == "success" else "重试预览")
        self.editor.show_dimension_preview(result)
        dof = result.degrees_of_freedom
        details = [f"自由度 {dof}" if dof is not None and dof >= 0 else "自由度待确定"]
        if result.status == "success" and dof is not None:
            details.append("欠约束" if dof > 0 else "完全约束")
        if result.status != "success":
            details.append("冲突或无法满足固定方式")
        if result.conflicting_constraint_ids:
            details.append(f"冲突 {len(result.conflicting_constraint_ids)} 项")
        if result.redundant_constraint_ids:
            details.append(f"冗余 {len(result.redundant_constraint_ids)} 项")
        self.diagnostics_label.setText("；".join(details))
        self._status(
            "驱动预览就绪，确认修改后应用"
            if result.status == "success"
            else result.message or "尺寸预览失败"
        )

    def accepted_preview(
        self, original: Sketch, candidate: SketchConstraint
    ) -> SketchConstraintSolveResult | None:
        if self._preview_result is not None and self._preview_result[:2] == (original, candidate):
            return self._preview_result[2]
        return None

    def apply_edit(self) -> None:
        if self.original is None or self.candidate is None or self._busy:
            return
        if not self._presentation_only:
            self._value_changed()
        if not self._input_valid:
            return
        original, candidate = self.original, self.candidate
        if self._current(original) != original:
            self.cancel()
            self._status("草图已改变，请重新拾取尺寸")
            return
        previewed = self.accepted_preview(original, candidate)
        if candidate.driving and not self._presentation_only and previewed is None:
            self._queue_preview()
            previewed = self.accepted_preview(original, candidate)
            if previewed is None:
                self._status("正在预览驱动尺寸，请等待后确认")
                return
        if previewed is not None and previewed.status != "success":
            self._status(previewed.message or "尺寸预览失败")
            return
        if previewed is not None and previewed.branch_changes and not self._branch_confirmed:
            self._branch_confirmed = True
            linked_previews = self.canvas.dimension_linked_sources
            self.editor.show_dimension_preview(previewed)
            self.editor.show_linked_dimension_previews(linked_previews)
            self._status(
                "几何分支将改变："
                + "；".join(c.message for c in previewed.branch_changes)
                + "；再次确认应用"
            )
            self.apply_button.show()
            return
        if original.sketch_id != self.editor.draft_sketch_id:
            self._busy = True
            self.apply_button.setEnabled(False)
            self.committed_requested.emit(original, candidate)
            return
        result = previewed or self.editor.preview_dimension(original, candidate)
        if result.status != "success" or result.sketch is None:
            self._status(result.message or "尺寸求解失败，几何保持原状")
            return
        if result.branch_changes and not self._branch_confirmed:
            self._branch_confirmed = True
            self.editor.show_dimension_preview(result)
            self._status(
                "几何分支将改变："
                + "；".join(c.message for c in result.branch_changes)
                + "；再次确认应用"
            )
            self.apply_button.show()
            # The next explicit click is the branch-change confirmation.
            return
        self._busy = True
        accepted = self.canvas.apply_constraint_solution(original, result.sketch)
        self._busy = False
        if accepted:
            self.complete_commit(original, candidate, result)
        else:
            self._status("草稿已改变，请重新拾取尺寸")

    def complete_commit(
        self, original: Sketch, candidate: SketchConstraint, result: SketchConstraintSolveResult
    ) -> None:
        self._busy = False
        self.apply_button.setEnabled(True)
        if result.status != "success" or result.sketch is None:
            self._status(result.message or "尺寸提交失败，历史未改变")
            return
        current = self._current(original)
        if current is None:
            self.cancel()
            return
        solved = next(
            (c for c in result.sketch.constraints if c.constraint_id == candidate.constraint_id),
            candidate,
        )
        self.last_dimension = (current, solved)
        if self.baseline_reference is None and solved.kind == "distance":
            self.baseline_reference = solved.references[0]
        mode = self.mode
        self.candidate = None
        self.references = []
        self.original = None
        self._preview_result = None
        self.canvas.dimension_candidate = None
        self.canvas.dimension_references = ()
        self.editor.clear_dimension_preview()
        self._hide_inline_value()
        self.canvas.setFocus()
        if self._editing and not self._new_driving:
            self.cancel()
        elif mode in ("continue", "baseline"):
            self._seed_chain(current, solved)
        elif mode == "ordinate":
            self.original = current
            self.references = [solved.references[0]]
        self._editing = False
        self._new_driving = False
        self.apply_button.hide()
        self._status("尺寸已应用；继续拾取，Esc 退出" if self.mode else "尺寸已修改；可撤销")
        self.canvas.update()

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            if (
                watched is self.canvas
                and event.key() == Qt.Key.Key_Escape
                and self.canvas.saved_handle_drag_active
            ):
                return False
            if event.key() == Qt.Key.Key_Escape and (self.mode or self._editing or self._dragging):
                self.cancel()
                self.canvas.setFocus()
                return True
            if (
                watched is self.canvas
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and (self.mode or self._editing)
            ):
                if self._editing:
                    self.value_editor.interpretText()
                    self.apply_edit()
                else:
                    self.cancel()
                return True
            if watched is self.value_editor and event.key() in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
            ):
                self.value_editor.interpretText()
                self.apply_edit()
                return True
            if (
                event.key() == Qt.Key.Key_Shift
                and self.mode in ("smart", "horizontal", "vertical", "aligned")
                and self.references
            ):
                self.mode = {
                    "smart": "horizontal",
                    "horizontal": "vertical",
                    "vertical": "aligned",
                    "aligned": "horizontal",
                }[self.mode]
                if self.candidate is not None and self.candidate.position_mm is not None:
                    position = self._display(self.candidate).position_mm
                    if position is not None:
                        self._build_candidate(position)
                return True
        if watched is not self.canvas or not isinstance(event, QMouseEvent):
            return False
        if event.type() == QEvent.Type.MouseMove:
            self.canvas.track_crosshair_pointer(event.position().toPoint())
        point = self.canvas.screen_to_local(event.position())
        if (
            event.type() == QEvent.Type.MouseButtonDblClick
            and event.button() == Qt.MouseButton.LeftButton
        ):
            hit = self._dimension_at(point)
            if hit is not None:
                self.edit(hit[0], hit[1])
                return True
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.RightButton and (self.mode or self._editing):
                if self._editing:
                    self.value_editor.interpretText()
                    self.apply_edit()
                else:
                    self.cancel()
                return True
            if event.button() == Qt.MouseButton.LeftButton:
                if self._editing:
                    return True
                if self.mode:
                    self.canvas.clear_dimension_snap_preview()
                    self._click(point)
                    return True
                if self.editor.tool_combo.currentText() == "选择元素":
                    hit = self._dimension_at(point)
                    if hit is not None:
                        self.original, self.candidate, self._dragging = hit
                        self._presentation_only = True
                        self._drag_start = event.position()
                        self._drag_moved = False
                        self.canvas.setFocus()
                        return True
        if event.type() == QEvent.Type.MouseMove and not self.canvas.is_panning:
            if self._dragging and self.original and self.candidate:
                if (event.position() - self._drag_start).manhattanLength() < 4:
                    return True
                self._drag_moved = True
                p = self._local(self.original, point)
                self.candidate = (
                    replace(self.candidate, text_position_mm=p)
                    if self._dragging == "text"
                    else replace(self.candidate, position_mm=p, text_position_mm=None)
                )
                self.canvas.dimension_candidate = self._display(self.candidate)
                self.canvas.update()
                return True
            if self.mode and not self._editing:
                hit = self._pick(point) if self.candidate is None else None
                point_reference = bool(
                    hit is not None
                    and len(hit[1]) == 1
                    and hit[1][0].kind in ("start", "end", "center", "vertex")
                    and hit[1][0] not in self.references
                )
                self.canvas.update_dimension_snap_preview(point, show_snap=point_reference)
                if self.references:
                    self._build_candidate(point)
                else:
                    if hit is None:
                        self.canvas.dimension_candidate = None
                        self.canvas.dimension_references = ()
                    else:
                        original, references = self.original, self.references
                        self.original, picked = hit
                        self.references = list(picked)
                        self.canvas.dimension_references = picked
                        self._build_candidate((point[0], point[1] + 18 / self.canvas.view_scale))
                        self.original, self.references = original, references
                        self.candidate = None
                    self.canvas.update()
                return True
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self._dragging
        ):
            self._dragging = None
            if not self._drag_moved:
                identity = self.candidate.constraint_id if self.candidate is not None else None
                self.cancel()
                if identity is not None:
                    modifiers = event.modifiers()
                    subtractive = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
                    additive = bool(modifiers & Qt.KeyboardModifier.ControlModifier) or (
                        self.canvas.active_transform == "erase" and self.canvas.transform_selecting
                    )
                    if not additive and not subtractive:
                        self.canvas.selected_constraint_ids.clear()
                        self.canvas.selected_entity_ids.clear()
                        self.canvas.selected_raster_ids.clear()
                    if subtractive or (
                        additive and identity in self.canvas.selected_constraint_ids
                    ):
                        self.canvas.selected_constraint_ids.discard(identity)
                    else:
                        self.canvas.selected_constraint_ids.add(identity)
                    self.canvas.changed.emit()
                    self.canvas.update()
                return True
            self._editing = True
            self.apply_edit()
            return True
        return False
