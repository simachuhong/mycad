# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Interactive 2D sketch draft editor; it does not write the document."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import cast, override
from uuid import uuid4

from PySide6.QtCore import (
    QByteArray,
    QCoreApplication,
    QEvent,
    QPoint,
    QPointF,
    QRectF,
    QSignalBlocker,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QHideEvent,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
    QShortcut,
    QShowEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mycad.core.circle_fillet import circle_fillet_notrim
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
    SketchSupportFace,
    SplineEntity,
    WorkPlaneFrame,
)
from mycad.core.sketch_constraints import (
    DIMENSION_KINDS,
    SketchConstraint,
    SketchConstraintSolveResult,
    SketchGeometryReference,
)
from mycad.core.sketch_edit import (
    circular_array_entities,
    copy_entities,
    extend_curve_at,
    linear_array_entities,
    mirror_entities,
    move_entities,
    move_sketch_handle,
    offset_entities,
    rotate_entities,
    split_entity_at,
    trim_curve_at,
)
from mycad.core.sketch_layers import (
    DEFAULT_DIM_LAYER,
    SKETCH_LINETYPES,
    STANDARD_LINEWEIGHTS_MM,
    SketchLayer,
    SketchLayerTable,
    SketchLinetype,
    merge_layer_tables,
)
from mycad.ui.cad_icons import set_button_icon
from mycad.ui.dimension_tools import DimensionTools
from mycad.ui.drawing2d_command_bar import Drawing2DCommandBar
from mycad.ui.layer_panel import DrawingLayerPanel
from mycad.ui.sketch_dynamic_input import SketchDynamicInput
from mycad.ui.sketch_navigation import SketchNavigator
from mycad.ui.sketch_selection import entity_in_selection_box
from mycad.ui.workspace_console import MessageLabel

_SNAP_RADIUS_PX = 12.0
_SNAP_PRIORITY = {
    "端点": 0,
    "交点": 1,
    "垂足": 2,
    "切点": 3,
    "圆心": 4,
    "中点": 5,
    "中心": 6,
}


@dataclass(frozen=True)
class DimensionLayout:
    lines: tuple[tuple[QPointF, QPointF], ...]
    arrows: tuple[tuple[QPointF, QPointF], ...]
    label: QPointF


@dataclass(frozen=True)
class MixedMoveState:
    transaction_id: str
    source_revision: int
    original_draft: Sketch
    original_saved: tuple[Sketch, ...]
    current_saved: tuple[Sketch, ...]
    base_background: tuple[tuple[SketchEntity, SketchLayer], ...]
    overlay_background: tuple[tuple[SketchEntity, SketchLayer], ...]


@dataclass(frozen=True)
class _DraftState:
    entities: tuple[SketchEntity, ...]
    constraints: tuple[SketchConstraint, ...]
    selected_ids: frozenset[str]
    layers: SketchLayerTable
    active_layer_name: str
    line_points: tuple[Point2D, ...] = ()
    history_position: int = 0
    mixed_move: MixedMoveState | None = None


def _cross(first: Point2D, second: Point2D) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _distance(first: Point2D, second: Point2D) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _distance_to_segment(point: Point2D, start: Point2D, end: Point2D) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator <= 1e-20:
        return _distance(point, start)
    ratio = min(
        1.0,
        max(0.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denominator),
    )
    return _distance(point, (start[0] + ratio * dx, start[1] + ratio * dy))


def _arc_sweep(start_angle: float, end_angle: float, direction: str) -> float:
    if direction == "顺时针":
        return -((start_angle - end_angle) % 360.0)
    return (end_angle - start_angle) % 360.0


def _angle_on_arc(angle: float, start_angle: float, sweep_angle: float) -> bool:
    if abs(sweep_angle) >= 360.0:
        return True
    offset = (angle - start_angle) % 360.0 if sweep_angle > 0.0 else (start_angle - angle) % 360.0
    return offset <= abs(sweep_angle) + 1e-9


def _segment_circle_intersections(
    start: Point2D,
    end: Point2D,
    center: Point2D,
    radius: float,
) -> tuple[Point2D, ...]:
    delta = (end[0] - start[0], end[1] - start[1])
    relative = (start[0] - center[0], start[1] - center[1])
    a = delta[0] * delta[0] + delta[1] * delta[1]
    if a <= 1e-12:
        return ()
    b = 2.0 * (relative[0] * delta[0] + relative[1] * delta[1])
    c = relative[0] * relative[0] + relative[1] * relative[1] - radius * radius
    discriminant = b * b - 4.0 * a * c
    if discriminant < -1e-12:
        return ()
    root = math.sqrt(max(0.0, discriminant))
    parameters = (
        (-b / (2.0 * a),)
        if root <= 1e-12
        else (
            (-b - root) / (2.0 * a),
            (-b + root) / (2.0 * a),
        )
    )
    return tuple(
        (start[0] + delta[0] * parameter, start[1] + delta[1] * parameter)
        for parameter in parameters
        if -1e-12 <= parameter <= 1.0 + 1e-12
    )


def _circle_circle_intersections(
    first_center: Point2D,
    first_radius: float,
    second_center: Point2D,
    second_radius: float,
) -> tuple[Point2D, ...]:
    delta = (second_center[0] - first_center[0], second_center[1] - first_center[1])
    distance = math.hypot(*delta)
    if (
        distance <= 1e-12
        or distance > first_radius + second_radius + 1e-12
        or distance < abs(first_radius - second_radius) - 1e-12
    ):
        return ()
    along = (first_radius**2 - second_radius**2 + distance**2) / (2.0 * distance)
    height_squared = max(0.0, first_radius**2 - along**2)
    base = (
        first_center[0] + along * delta[0] / distance,
        first_center[1] + along * delta[1] / distance,
    )
    height = math.sqrt(height_squared)
    if height <= 1e-12:
        return (base,)
    perpendicular = (-delta[1] * height / distance, delta[0] * height / distance)
    return (
        (base[0] + perpendicular[0], base[1] + perpendicular[1]),
        (base[0] - perpendicular[0], base[1] - perpendicular[1]),
    )


class SketchLayerManagerDialog(QDialog):
    """Edit a draft sketch's layer table before the single Bus submission."""

    def __init__(
        self,
        layers: SketchLayerTable,
        *,
        used_names: tuple[str, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("草图图层")
        self.layer_table = layers
        self.used_names = used_names
        self._color_rgb = layers.layers[0].color_rgb
        root = QVBoxLayout(self)
        controls = QGridLayout()
        self.layer_combo = QComboBox()
        self.layer_combo.addItems(tuple(layer.name for layer in layers.layers))
        self.name_label = QLabel()
        self.color_button = QPushButton()
        self.linetype_combo = QComboBox()
        self.linetype_combo.addItems(SKETCH_LINETYPES)
        self.lineweight_combo = QComboBox()
        for value in STANDARD_LINEWEIGHTS_MM:
            self.lineweight_combo.addItem(f"{value:g} mm", value)
        self.visible_check = QCheckBox("可见")
        self.visible_check.setChecked(True)
        self.locked_check = QCheckBox("锁定")
        self.color_button.clicked.connect(self._choose_color)
        self.layer_combo.currentTextChanged.connect(self._load_layer)
        controls.addWidget(QLabel("图层"), 0, 0)
        controls.addWidget(self.layer_combo, 0, 1, 1, 2)
        controls.addWidget(QLabel("名称"), 1, 0)
        controls.addWidget(self.name_label, 1, 1, 1, 2)
        controls.addWidget(QLabel("颜色"), 2, 0)
        controls.addWidget(self.color_button, 2, 1, 1, 2)
        controls.addWidget(QLabel("线型"), 3, 0)
        controls.addWidget(self.linetype_combo, 3, 1, 1, 2)
        controls.addWidget(QLabel("线宽"), 4, 0)
        controls.addWidget(self.lineweight_combo, 4, 1, 1, 2)
        controls.addWidget(self.visible_check, 5, 1)
        controls.addWidget(self.locked_check, 5, 2)
        root.addLayout(controls)

        actions = QHBoxLayout()
        self.add_button = QPushButton("新建图层")
        self.remove_button = QPushButton("删除图层")
        self.apply_button = QPushButton("应用属性")
        self.close_button = QPushButton("完成")
        actions.addWidget(self.add_button)
        actions.addWidget(self.remove_button)
        actions.addWidget(self.apply_button)
        actions.addWidget(self.close_button)
        root.addLayout(actions)
        self.status_label = QLabel()
        root.addWidget(self.status_label)
        self.add_button.clicked.connect(self._prompt_add_layer)
        self.remove_button.clicked.connect(self._remove_layer)
        self.apply_button.clicked.connect(self._apply_layer_properties)
        self.close_button.clicked.connect(self.accept)
        self._load_layer(self.layer_combo.currentText())

    @property
    def current_layer_name(self) -> str:
        """Return the selected draft layer name."""
        return self.layer_combo.currentText()

    def add_layer(self, name: str) -> bool:
        """Add one named layer, returning False with an explanation on invalid input."""
        try:
            self.layer_table = self.layer_table.add(SketchLayer(name))
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return False
        self.layer_combo.addItem(name)
        self.layer_combo.setCurrentText(name)
        self.status_label.setText(f"已创建图层 {name}。")
        return True

    def set_color_rgb(self, color_rgb: tuple[int, int, int]) -> None:
        """Set the current layer color from a palette or test harness."""
        self._color_rgb = color_rgb
        self._sync_color_button()

    @override
    def accept(self) -> None:
        if not self._apply_layer_properties():
            return
        super().accept()

    def _prompt_add_layer(self) -> None:
        name, accepted = QInputDialog.getText(self, "新建图层", "图层名称")
        if accepted:
            self.add_layer(name)

    def _remove_layer(self) -> None:
        name = self.layer_combo.currentText()
        try:
            self.layer_table = self.layer_table.remove(name, used_names=self.used_names)
        except (KeyError, ValueError) as exc:
            self.status_label.setText(str(exc))
            return
        blocker = QSignalBlocker(self.layer_combo)
        self.layer_combo.clear()
        self.layer_combo.addItems(
            tuple(layer.name for layer in self.layer_table.layers if not layer.frozen)
        )
        self.layer_combo.setCurrentText("0")
        del blocker
        self._load_layer(self.layer_combo.currentText())
        self.status_label.setText(f"已删除图层 {name}。")

    def _choose_color(self) -> None:
        initial = QColor(*self._color_rgb)
        color = QColorDialog.getColor(initial, self, "选择图层颜色")
        if color.isValid():
            self.set_color_rgb((color.red(), color.green(), color.blue()))

    def _sync_color_button(self) -> None:
        red, green, blue = self._color_rgb
        self.color_button.setText(f"#{red:02X}{green:02X}{blue:02X}")
        self.color_button.setStyleSheet(
            f"background-color: rgb({red}, {green}, {blue}); color: white;"
        )

    def _load_layer(self, name: str) -> None:
        if not name:
            return
        layer = self.layer_table.get(name)
        self.name_label.setText(layer.name)
        self._color_rgb = layer.color_rgb
        self._sync_color_button()
        self.linetype_combo.setCurrentText(layer.linetype)
        weight_index = self.lineweight_combo.findData(layer.lineweight_mm)
        self.lineweight_combo.setCurrentIndex(weight_index)
        self.visible_check.setChecked(layer.visible)
        self.locked_check.setChecked(layer.locked)

    def _apply_layer_properties(self) -> bool:
        name = self.layer_combo.currentText()
        if not name:
            self.status_label.setText("至少需要一个有效图层。")
            return False
        lineweight = self.lineweight_combo.currentData()
        if not isinstance(lineweight, int | float) or isinstance(lineweight, bool):
            self.status_label.setText("请选择有效线宽。")
            return False
        try:
            layer = SketchLayer(
                name,
                self._color_rgb,
                cast("SketchLinetype", self.linetype_combo.currentText()),
                float(lineweight),
                self.visible_check.isChecked(),
                self.locked_check.isChecked(),
            )
            self.layer_table = self.layer_table.replace(layer)
        except (KeyError, ValueError) as exc:
            self.status_label.setText(str(exc))
            return False
        self.status_label.setText(f"已更新图层 {name} 的属性。")
        return True


class _CursorDimensionEntry(QLineEdit):
    next_requested = Signal()
    accept_requested = Signal()
    cancel_requested = Signal()

    @override
    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            key = cast("QKeyEvent", event)
            if key.key() == Qt.Key.Key_Tab:
                self.next_requested.emit()
                return True
        return super().event(event)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept_requested.emit()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class SketchCanvas(QWidget):
    """Grid canvas with local coordinates, cursor preview, pan/zoom and snaps."""

    changed = Signal()
    point_accepted = Signal(object)
    history_recorded = Signal()
    deleting = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    cursor_changed = Signal(float, float, str)
    pointer_moved = Signal(QPoint)
    pointer_left = Signal()
    committed_move_requested = Signal(object, object)
    committed_rotation_requested = Signal(object, object, object)
    committed_mirror_requested = Signal(object, object, object)
    committed_delete_requested = Signal(object)
    copy_mode_changed = Signal(int)

    def __init__(
        self, parent: QWidget | None = None, *, select_committed_entities: bool = False
    ) -> None:
        super().__init__(parent)
        self.setMinimumSize(160, 60)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.entities: list[SketchEntity] = []
        self.background_entities: tuple[tuple[SketchEntity, SketchLayer], ...] = ()
        self.mixed_move: MixedMoveState | None = None
        self._invalid_mixed_transactions: set[str] = set()
        self.select_committed_entities = select_committed_entities
        self.layer_table = SketchLayerTable()
        self.active_layer_name = "0"
        self.document_layer_table: SketchLayerTable | None = None
        self.preserve_document_layers = False
        self._undo_history: list[_DraftState] = []
        self._redo_history: list[_DraftState] = []
        self.history_position = 0
        self._next_history_position = 0
        self.constraints: list[SketchConstraint] = []
        self.dimension_preview: Sketch | None = None
        self.dimension_error_entity_ids: frozenset[str] = frozenset()
        self.dimension_error_constraint_ids: frozenset[str] = frozenset()
        self.dimension_candidate: SketchConstraint | None = None
        self.dimension_references: tuple[SketchGeometryReference, ...] = ()
        self.background_constraints: tuple[SketchConstraint, ...] = ()
        self._snap_candidates_cache: tuple[tuple[Point2D, str], ...] | None = None
        self._snapping_enabled = True
        self._grid_snapping_enabled = False
        self.grid_visible = True
        self._orthogonal_enabled = False
        self._auto_inference_enabled = True
        self.tool = "直线"
        self.continuous_lines = False
        self.ucs_plane = "XY"
        self.construction = False
        self.closed_polyline = False
        self.polygon_sides = 6
        self.polygon_circumscribed = False
        self.arc_direction = "逆时针"
        self.circle_fillet_radius = 1.0
        self.circle_fillet_radius_pending = False
        self._circle_fillet_first: tuple[CircleEntity, Point2D] | None = None
        self._scale = 5.0
        self._pan = QPointF(0.0, 0.0)
        self._first: Point2D | None = None
        self._points: list[Point2D] = []
        self._cursor: Point2D | None = None
        self._last_placement_raw: Point2D | None = None
        self.dynamic_point_resolver: Callable[[Point2D, Point2D], Point2D] | None = None
        self.dynamic_key_handler: Callable[[QKeyEvent], bool] | None = None
        self.dynamic_click_guard: Callable[[], bool] | None = None
        self._snap_kind = ""
        self._hovered_line_edit_entity_id: str | None = None
        self._line_edit_preview_original: SketchEntity | None = None
        self._line_edit_preview_result: tuple[SketchEntity, ...] = ()
        self.selected_entity_ids: set[str] = set()
        self.selected_constraint_ids: set[str] = set()
        self._hovered_entity_id: str | None = None
        self._selection_anchor: QPointF | None = None
        self._selection_corner = QPointF()
        self._selection_waiting_click = False
        self._selection_original: frozenset[str] = frozenset()
        self._selection_modifiers = Qt.KeyboardModifier.NoModifier
        self._panning = False
        self._last_mouse = QPoint()
        self._drag_solver: (
            Callable[
                [
                    tuple[SketchEntity, ...],
                    tuple[SketchConstraint, ...],
                    SketchGeometryReference,
                    Point2D,
                ],
                SketchConstraintSolveResult,
            ]
            | None
        ) = None
        self._drag_reference: SketchGeometryReference | None = None
        self._drag_entity_id: str | None = None
        self._drag_origin: Point2D | None = None
        self._drag_original_entities: tuple[SketchEntity, ...] | None = None
        self._drag_original_constraints: tuple[SketchConstraint, ...] | None = None
        self._drag_original_selection: frozenset[str] | None = None
        self._drag_last_entities: tuple[SketchEntity, ...] | None = None
        self._drag_last_constraints: tuple[SketchConstraint, ...] | None = None
        self._drag_branch_warning = ""
        self._transform_operation: str | None = None
        self._transform_base: Point2D | None = None
        self._transform_selecting = False
        self._transform_reference_mode = False
        self._transform_reference: Point2D | None = None
        self._transform_keep_source = True
        self._transform_angle_text = ""
        self._transform_preview: tuple[SketchEntity, ...] = ()
        self._copy_placements: list[tuple[Point2D, int, int]] = []
        self.copy_mode = 0
        self._copy_repeat = True
        self._trim_drag_start: Point2D | None = None
        self._trim_drag_last: Point2D | None = None
        self._trim_drag_original_entities: tuple[SketchEntity, ...] | None = None
        self._trim_drag_original_constraints: tuple[SketchConstraint, ...] | None = None
        self._trim_drag_original_selection: frozenset[str] | None = None
        self._trim_drag_candidate_entities: tuple[SketchEntity, ...] | None = None
        self._trim_drag_changed_count = 0
        self._trim_drag_last_error: str | None = None
        self._trim_drag_moved = False
        self.message: str = "选择绘图工具；单击画布放置几何。"

    def local_to_screen(self, point: Point2D) -> QPoint:
        """Convert a local millimetre point to canvas pixels for UI automation."""
        center_x = self.width() / 2.0 + self._pan.x()
        center_y = self.height() / 2.0 + self._pan.y()
        return QPoint(
            round(center_x + point[0] * self._scale),
            round(center_y - point[1] * self._scale),
        )

    def screen_to_local(self, point: QPointF) -> Point2D:
        center_x = self.width() / 2.0 + self._pan.x()
        center_y = self.height() / 2.0 + self._pan.y()
        return ((point.x() - center_x) / self._scale, (center_y - point.y()) / self._scale)

    @property
    def has_pending_geometry(self) -> bool:
        if self.tool == "直线" and self.continuous_lines and len(self._points) >= 2:
            return False  # The next segment is only a rubber band, not unfinished geometry.
        return self._first is not None or bool(self._points)

    @property
    def can_close_chain(self) -> bool:
        return self.tool in {"直线", "多段线"} and len(self._points) >= 3

    def end_line_chain(self) -> None:
        self._first = None
        self._points.clear()
        self._snap_kind = ""
        self.message = "连续直线已结束；已完成线段保留。指定新起点继续绘图。"
        self.changed.emit()
        self.update()

    def close_chain(self) -> None:
        if not self.can_close_chain:
            self.message = "闭合至少需要三个不同的点。"
            self.changed.emit()
            return
        if self.tool == "多段线":
            self.finish_polyline(close=True)
        else:
            self._accept_point(self._points[0], exact_point=True)

    def fit_view(self) -> None:
        points: list[Point2D] = []
        for entity in (*self.entities, *(e for e, _layer in self.background_entities)):
            layer = (
                self._layer(entity)
                if entity in self.entities
                else next(
                    layer
                    for e, layer in self.background_entities
                    if e.entity_id == entity.entity_id
                )
            )
            if layer.frozen:
                continue
            if isinstance(entity, CircleEntity | ArcEntity):
                x, y = entity.center_mm
                radius = entity.radius_mm
                points.extend(((x - radius, y - radius), (x + radius, y + radius)))
            else:
                points.extend(point for _reference, point in self._entity_handles(entity))
        dimension_entities = self.dimension_entities()
        for constraint in (*self.constraints, *self.background_constraints):
            if constraint.kind not in DIMENSION_KINDS or self.annotation_layer(constraint).frozen:
                continue
            layout = self.dimension_layout(constraint, dimension_entities)
            if layout is not None:
                points.append(self.screen_to_local(layout.label))
                points.extend(
                    self.screen_to_local(point) for line in layout.lines for point in line
                )
        if not points:
            self._scale = 5.0
            self._pan = QPointF()
        else:
            left = min(point[0] for point in points)
            right = max(point[0] for point in points)
            bottom = min(point[1] for point in points)
            top = max(point[1] for point in points)
            self._scale = min(
                60.0,
                max(
                    1e-6,
                    min(
                        max(1, self.width() - 80) / max(1.0, right - left),
                        max(1, self.height() - 80) / max(1.0, top - bottom),
                    ),
                ),
            )
            self._pan = QPointF(-(left + right) * self._scale / 2, (bottom + top) * self._scale / 2)
        self.update()

    def copy_view_from(self, other: SketchCanvas) -> None:
        self._scale = other._scale
        self._pan = QPointF(other._pan)
        self.update()

    def set_background_sketches(self, sketches: tuple[Sketch, ...], frame: WorkPlaneFrame) -> None:
        """Project parallel canonical planes without making source geometry editable."""
        background: list[tuple[SketchEntity, SketchLayer]] = []
        constraints: list[SketchConstraint] = []
        for sketch in sketches:
            source = sketch.frame
            if source.u_axis != frame.u_axis or source.v_axis != frame.v_axis:
                continue
            delta = tuple(a - b for a, b in zip(source.origin_mm, frame.origin_mm, strict=True))
            if abs(sum(a * b for a, b in zip(delta, frame.normal, strict=True))) > 1e-7:
                continue
            shift = (
                sum(a * b for a, b in zip(delta, frame.u_axis, strict=True)),
                sum(a * b for a, b in zip(delta, frame.v_axis, strict=True)),
            )
            if not sketch.entities:
                continue
            entities = move_entities(
                sketch.entities, tuple(entity.entity_id for entity in sketch.entities), shift
            )
            table = (
                merge_layer_tables(sketch.layers, self.document_layer_table)
                if self.document_layer_table is not None
                else sketch.layers
            )
            background.extend((entity, table.get(entity.layer_name)) for entity in entities)
            constraints.extend(
                replace(
                    c,
                    position_mm=None
                    if c.position_mm is None
                    else (c.position_mm[0] + shift[0], c.position_mm[1] + shift[1]),
                    text_position_mm=None
                    if c.text_position_mm is None
                    else (c.text_position_mm[0] + shift[0], c.text_position_mm[1] + shift[1]),
                )
                for c in sketch.constraints
            )
        self.background_constraints = tuple(constraints)
        projected = tuple(background)
        mixed = self.mixed_move
        if mixed is not None:
            if (
                projected == mixed.base_background
                and mixed.transaction_id not in self._invalid_mixed_transactions
            ):
                projected = mixed.overlay_background
            else:
                self._invalid_mixed_transactions.add(mixed.transaction_id)
                self.message = "来源或工作平面已变化；暂存变换不能提交，请撤销或取消。"
        if self.background_entities != projected:
            self._cancel_selection_box()
        self.background_entities = projected
        self.selected_entity_ids.intersection_update(
            entity.entity_id for entity in self.selectable_entities()
        )
        self._snap_candidates_cache = None
        self.update()

    def visible_snap_entities(self) -> tuple[SketchEntity, ...]:
        return (
            *self._visible_entities(),
            *(entity for entity, layer in self.background_entities if layer.displayed),
        )

    def set_layer_table(
        self, layers: SketchLayerTable, active_layer_name: str, *, record_history: bool = False
    ) -> None:
        """Replace the draft layer table and current drawing layer."""
        self._cancel_active_edit_gesture()
        layers.get(active_layer_name)
        if record_history and layers != self.layer_table:
            self._record_undo()
        self.layer_table = layers
        self.active_layer_name = active_layer_name
        self._snap_candidates_cache = None
        self.update()

    def dimension_entities(self) -> dict[str, SketchEntity]:
        entities = {
            e.entity_id: e for e in (*self.entities, *(e for e, _layer in self.background_entities))
        }
        if self.dimension_preview is not None:
            entities.update((e.entity_id, e) for e in self.dimension_preview.entities)
        return entities

    def dimension_constraints(self) -> tuple[SketchConstraint, ...]:
        constraints = {
            c.constraint_id: c for c in (*self.background_constraints, *self.constraints)
        }
        if self.dimension_preview is not None:
            constraints.update((c.constraint_id, c) for c in self.dimension_preview.constraints)
        return tuple(constraints.values())

    def annotation_layer(self, constraint: SketchConstraint) -> SketchLayer:
        entities = self.dimension_entities()
        first = entities.get(constraint.references[0].entity_id)
        name = constraint.layer_name or (first.layer_name if first is not None else "0")
        if self.document_layer_table is not None:
            return self.document_layer_table.get(name)
        if constraint in self.background_constraints:
            for entity, layer in self.background_entities:
                if (
                    first is not None
                    and entity.entity_id == first.entity_id
                    and constraint.layer_name is None
                ):
                    return layer
        try:
            return self.layer_table.get(name)
        except KeyError:
            return DEFAULT_DIM_LAYER if name.casefold() == "dim" else SketchLayer(name)

    def visible_dimensions(self) -> tuple[SketchConstraint, ...]:
        return tuple(
            c
            for c in self.dimension_constraints()
            if c.kind in DIMENSION_KINDS and self.annotation_layer(c).displayed
        )

    def set_drag_solver(
        self,
        solver: Callable[
            [
                tuple[SketchEntity, ...],
                tuple[SketchConstraint, ...],
                SketchGeometryReference,
                Point2D,
            ],
            SketchConstraintSolveResult,
        ],
    ) -> None:
        """Install the optional solver used to preview constrained handle drags."""
        self._drag_solver = solver

    def _layer(self, entity: SketchEntity) -> SketchLayer:
        return self.layer_table.get(entity.layer_name)

    def _visible_entities(self) -> tuple[SketchEntity, ...]:
        return tuple(entity for entity in self.entities if self._layer(entity).displayed)

    def selectable_entities(self) -> tuple[SketchEntity, ...]:
        """Include committed drawing geometry while keeping part references separate."""
        return (
            *self._visible_entities(),
            *(
                entity
                for entity, layer in self.background_entities
                if self.select_committed_entities and layer.displayed
            ),
        )

    def _selected_committed_entities(self) -> bool:
        return self.select_committed_entities and any(
            entity.entity_id in self.selected_entity_ids
            for entity, _layer in self.background_entities
        )

    def _merge_hidden_entities(
        self,
        original: tuple[SketchEntity, ...],
        updated_visible: tuple[SketchEntity, ...],
    ) -> tuple[SketchEntity, ...]:
        """Reinsert hidden geometry at its nearest surviving visible successor."""
        updated_ids = {entity.entity_id for entity in updated_visible}
        hidden_before: dict[str, list[SketchEntity]] = {}
        trailing_hidden: list[SketchEntity] = []
        for index, entity in enumerate(original):
            if self._layer(entity).displayed:
                continue
            successor = next(
                (
                    candidate.entity_id
                    for candidate in original[index + 1 :]
                    if self._layer(candidate).displayed and candidate.entity_id in updated_ids
                ),
                None,
            )
            if successor is None:
                trailing_hidden.append(entity)
            else:
                hidden_before.setdefault(successor, []).append(entity)
        merged: list[SketchEntity] = []
        for entity in updated_visible:
            merged.extend(hidden_before.pop(entity.entity_id, ()))
            merged.append(entity)
        for remaining in hidden_before.values():
            merged.extend(remaining)
        merged.extend(trailing_hidden)
        return tuple(merged)

    def _current_layer_can_draw(self) -> bool:
        layer = self.layer_table.get(self.active_layer_name)
        return layer.displayed and not layer.locked

    def set_tool(self, tool: str) -> bool:
        if self.has_pending_geometry:
            self.message = "当前图元未完成；先完成图元或按 Esc 清除。"
            self.changed.emit()
            self.update()
            return False
        self._cancel_active_edit_gesture()
        if tool != "选择元素":
            self.selected_entity_ids.clear()
            self.selected_constraint_ids.clear()
        self.tool = tool
        self._hovered_line_edit_entity_id = None
        self._clear_line_edit_preview()
        self._hovered_entity_id = None
        self._first = None
        self._points.clear()
        self.message = (
            f"二维圆角（不修剪，R={self.circle_fillet_radius:g}）：请选择第一个圆；命令栏 R 修改半径。"
            if tool == "二维圆角"
            else "修剪：单击删除曲线段，或按住左键拖过多个区段；Shift+单击临时延伸，Esc 取消。"
            if tool == "修剪"
            else "延伸：直线和开放多段线端点延至最近有效交点；圆弧端点沿原方向延至最近有效交点。"
            if tool == "延伸"
            else "分割：单击目标直线、矩形边或多段线路径，靠近交点区段；选中区间的首段保留原身份。"
            if tool == "分割"
            else "选择：点选或在空白处拖拽/两次单击框选；左→右全包含，右→左包含或相交；Ctrl 加选，Shift 减选；Delete 删除所选对象。"
            if tool == "选择元素"
            else f"{tool}：单击画布按提示放置点。"
        )
        if self.isVisible() and tool in {"修剪", "延伸", "分割"}:
            position = self.mapFromGlobal(QCursor.pos())
            if self.rect().contains(position):
                self._cursor = self.screen_to_local(QPointF(position))
                self._hovered_line_edit_entity_id = (
                    self._extend_target_at(self._cursor)
                    if tool == "延伸"
                    else self._trim_target_at(self._cursor, lines_only=tool == "分割")
                )
                self._refresh_line_edit_preview(None if tool == "分割" else tool)
        self.update()
        self.changed.emit()
        return True

    def replace_draft_entities(
        self, entities: tuple[SketchEntity, ...], *, select_new: bool = False
    ) -> bool:
        """Replace draft geometry and keep selection identities valid."""
        if tuple(self.entities) == entities:
            return False
        try:
            self._reject_user_constraint_reference_edits(entities)
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            self.update()
            return False
        original_entities = tuple(self.entities)
        self._record_undo()
        previous_ids = {entity.entity_id for entity in original_entities}
        self.entities = list(entities)
        removed_relations = self._preserve_satisfied_relations(
            entities, original_entities=original_entities
        )
        if removed_relations:
            self.message = f"几何已变更；移除了 {removed_relations} 条失效或需重新确认的自动关系。"
        available_ids = {entity.entity_id for entity in self.entities}
        self.selected_entity_ids.intersection_update(
            entity.entity_id for entity in self.selectable_entities()
        )
        if select_new:
            self.selected_entity_ids.update(available_ids - previous_ids)
        self._snap_candidates_cache = None
        self.changed.emit()
        self.update()
        return True

    def apply_mixed_move(self, state: MixedMoveState, entities: tuple[SketchEntity, ...]) -> None:
        """Record one validated provisional move across draft and committed geometry."""
        original = tuple(self.entities)
        self._reject_user_constraint_reference_edits(entities)
        self._record_undo()
        self.entities = list(entities)
        self._preserve_satisfied_relations(entities, original_entities=original)
        self.mixed_move = state
        self.background_entities = state.overlay_background
        self._snap_candidates_cache = None
        self.message = "混合变换已暂存；完成草图时统一提交，可撤销。"
        self.changed.emit()
        self.update()

    def mixed_move_timeline(self) -> tuple[tuple[tuple[Sketch, ...], Sketch], ...]:
        """Return retained provisional states in the order they must be replayed."""
        mixed = self.mixed_move
        if mixed is None:
            return ()
        states = (*self._undo_history, self._draft_state())
        result: list[tuple[tuple[Sketch, ...], Sketch]] = []
        for state in states:
            pending = state.mixed_move
            if pending is None or pending.transaction_id != mixed.transaction_id:
                continue
            draft = replace(
                mixed.original_draft,
                entities=state.entities,
                constraints=state.constraints,
                layers=state.layers,
            )
            item = (pending.current_saved, draft)
            if not result or result[-1] != item:
                result.append(item)
        return tuple(result)

    @property
    def mixed_move_is_valid(self) -> bool:
        return self.mixed_move is None or (
            self.mixed_move.transaction_id not in self._invalid_mixed_transactions
        )

    def delete_selected(self) -> bool:
        """Erase draft selection and its dependent relations as one undo step."""
        if self.has_pending_geometry or self.has_active_edit_gesture:
            self.message = "请先完成当前操作，或按 Esc 取消预览，再删除所选对象。"
            self.changed.emit()
            return False
        if self._selected_committed_entities() and not self.selected_constraint_ids:
            if any(entity.entity_id in self.selected_entity_ids for entity in self.entities):
                self.message = "暂不支持同时删除草稿和已提交图元；请选择同类对象。"
                self.changed.emit()
                return False
            if self.mixed_move is not None:
                self.message = "请先完成或撤销暂存变换，再删除已提交图元。"
                self.changed.emit()
                return False
            if any(
                (layer.locked or not layer.displayed)
                and entity.entity_id in self.selected_entity_ids
                for entity, layer in self.background_entities
            ):
                self.message = "选择包含已锁定或隐藏图层；图元未修改。"
                self.changed.emit()
                return False
            self.committed_delete_requested.emit(tuple(self.selected_entity_ids))
            return True
        error = self.transform_selection_error("delete") if not self.selected_constraint_ids else ""
        if error:
            self.message = error
            self.changed.emit()
            return False
        entity_ids = {
            entity.entity_id
            for entity in self.entities
            if entity.entity_id in self.selected_entity_ids and not self.selected_constraint_ids
        }
        constraints = [
            constraint
            for constraint in self.constraints
            if constraint.constraint_id in self.selected_constraint_ids
            or any(ref.entity_id in entity_ids for ref in constraint.references)
        ]
        if any(
            constraint.constraint_id in self.selected_constraint_ids
            and (
                self.annotation_layer(constraint).locked
                or not self.annotation_layer(constraint).displayed
            )
            for constraint in constraints
        ):
            self.message = "选择包含已锁定或隐藏图层的约束；草图未修改。"
            self.changed.emit()
            return False
        if not entity_ids and not constraints:
            return False
        self.deleting.emit()
        self._record_undo()
        self.entities = [entity for entity in self.entities if entity.entity_id not in entity_ids]
        removed_constraints = {constraint.constraint_id for constraint in constraints}
        self.constraints = [
            constraint
            for constraint in self.constraints
            if constraint.constraint_id not in removed_constraints
        ]
        self.selected_entity_ids.difference_update(entity_ids)
        self.selected_constraint_ids.difference_update(removed_constraints)
        self._snap_candidates_cache = None
        self._snap_kind = ""
        self._hovered_entity_id = None
        self._hovered_line_edit_entity_id = None
        self._clear_line_edit_preview()
        self.message = (
            f"已删除 {len(entity_ids)} 个图元及 {len(constraints)} 条约束；Ctrl+Z 可撤销。"
        )
        self.changed.emit()
        self.update()
        return True

    def _reject_user_constraint_reference_edits(
        self,
        entities: tuple[SketchEntity, ...],
        *,
        original_entities: tuple[SketchEntity, ...] | None = None,
    ) -> None:
        """Keep direct draft edits from silently breaking confirmed relations."""
        baseline = original_entities if original_entities is not None else tuple(self.entities)
        current_by_id = {entity.entity_id: entity for entity in baseline}
        updated_by_id = {entity.entity_id: entity for entity in entities}
        changed_ids = {
            entity_id
            for entity_id in current_by_id.keys() | updated_by_id.keys()
            if current_by_id.get(entity_id) != updated_by_id.get(entity_id)
        }
        for constraint in self.constraints:
            if constraint.source != "user":
                continue
            if any(reference.entity_id in changed_ids for reference in constraint.references):
                raise ValueError(
                    "本次编辑会改变用户约束引用的图元；请先处理相关约束再改几何。草稿未变。"
                )

    @property
    def view_scale(self) -> float:
        return self._scale

    @property
    def is_panning(self) -> bool:
        return self._panning

    @property
    def can_undo(self) -> bool:
        return (
            bool(self._undo_history)
            and not self.has_pending_geometry
            and not self.has_active_edit_gesture
        )

    @property
    def can_redo(self) -> bool:
        return (
            bool(self._redo_history)
            and (not self.has_pending_geometry or (self.tool == "直线" and self.continuous_lines))
            and not self.has_active_edit_gesture
        )

    @property
    def has_active_edit_gesture(self) -> bool:
        """Whether a pointer edit is displaying an unconfirmed draft preview."""
        return (
            self._transform_operation is not None
            or self._circle_fillet_first is not None
            or self._trim_drag_start is not None
            or self._drag_reference is not None
            or self._selection_anchor is not None
        )

    def _cancel_active_edit_gesture(self) -> bool:
        cancelled_selection = self._cancel_selection_box()
        return (
            self.cancel_transform()
            or self._cancel_circle_fillet()
            or self._cancel_trim_drag()
            or self._cancel_handle_drag()
            or cancelled_selection
        )

    def _cancel_circle_fillet(self) -> bool:
        if self._circle_fillet_first is None and not self.circle_fillet_radius_pending:
            return False
        self._circle_fillet_first = None
        self.circle_fillet_radius_pending = False
        self.selected_entity_ids.clear()
        self.message = "已取消圆角选取；草稿未变。"
        self.changed.emit()
        self.update()
        return True

    def set_circle_fillet_radius(self, radius: float) -> None:
        if not math.isfinite(radius) or radius <= 1e-10:
            raise ValueError("圆角半径必须是大于零的有限数值。")
        self.circle_fillet_radius = radius
        self.message = f"二维圆角（不修剪，R={radius:g}）：请选择圆。"
        self.changed.emit()

    def _circle_fillet_pick(self, point: Point2D) -> None:
        if self.circle_fillet_radius_pending:
            self.message = "请先在命令栏输入有效的圆角半径。"
        elif not self._current_layer_can_draw():
            self.message = "当前图层隐藏或已锁定，无法创建圆角。"
        else:
            identity = self._hit_entity_at(point)
            entity = next(
                (item for item in self.selectable_entities() if item.entity_id == identity), None
            )
            if not isinstance(entity, CircleEntity):
                self.message = "请点选唯一的圆；当前仅支持两个圆的非修剪外切圆角。"
            elif self._circle_fillet_first is None:
                self._circle_fillet_first = (entity, point)
                self.selected_entity_ids = {entity.entity_id}
                self.message = "二维圆角：请选择第二个圆；Esc 取消。"
            else:
                first, first_pick = self._circle_fillet_first
                try:
                    if first not in self.selectable_entities():
                        raise ValueError("第一个圆已失效，请按 Esc 后重新选择。")
                    arc = circle_fillet_notrim(
                        first,
                        entity,
                        first_pick,
                        point,
                        self.circle_fillet_radius,
                        uuid4().hex,
                        layer_name=self.active_layer_name,
                    )
                except ValueError as exc:
                    self.message = str(exc)
                else:
                    self._circle_fillet_first = None
                    self.selected_entity_ids.clear()
                    if self.replace_draft_entities((*self.entities, arc)):
                        self.message = "二维圆角已创建；原圆保留，未建立相切约束。可继续选择圆。"
        self.changed.emit()
        self.update()

    def _record_undo(self) -> None:
        self._undo_history.append(self._draft_state())
        self._advance_history()

    def _advance_history(self) -> None:
        self._next_history_position += 1
        self.history_position = self._next_history_position
        self._redo_history.clear()
        self.history_recorded.emit()

    def _draft_state(self) -> _DraftState:
        return _DraftState(
            tuple(self.entities),
            tuple(self.constraints),
            frozenset(self.selected_entity_ids),
            self.layer_table,
            self.active_layer_name,
            tuple(self._points) if self.tool == "直线" and self.continuous_lines else (),
            self.history_position,
            self.mixed_move,
        )

    def _restore_draft_state(self, state: _DraftState) -> None:
        previous_mixed = self.mixed_move
        self.mixed_move = state.mixed_move
        if (
            state.mixed_move is not None
            and state.mixed_move.transaction_id not in self._invalid_mixed_transactions
        ):
            self.background_entities = state.mixed_move.overlay_background
        elif (
            state.mixed_move is None
            and previous_mixed is not None
            and previous_mixed.transaction_id not in self._invalid_mixed_transactions
        ):
            self.background_entities = previous_mixed.base_background
        self.history_position = state.history_position
        if self.tool == "直线" and self.continuous_lines:
            self._points = list(state.line_points)
            self._first = self._points[-1] if self._points else None
        self.entities = list(state.entities)
        self.constraints = list(state.constraints)
        self.selected_entity_ids = set(state.selected_ids)
        self.layer_table = (
            (self.document_layer_table or state.layers)
            if self.preserve_document_layers
            else state.layers
        )
        if self.document_layer_table is not None:
            self.document_layer_table = self.layer_table
        self.active_layer_name = state.active_layer_name
        try:
            active = self.layer_table.get(self.active_layer_name)
            if active.frozen:
                self.active_layer_name = "0"
        except KeyError:
            self.active_layer_name = "0"
        self.selected_entity_ids.intersection_update(
            entity.entity_id for entity in self.selectable_entities()
        )
        self._snap_candidates_cache = None
        self._snap_kind = ""
        self._hovered_entity_id = None
        self._hovered_line_edit_entity_id = None
        self._clear_line_edit_preview()

    def _hit_entity_at(self, point: Point2D) -> str | None:
        tolerance = _SNAP_RADIUS_PX / self._scale
        candidates: list[tuple[float, str]] = []
        for entity in self.selectable_entities():
            if isinstance(entity, PointEntity):
                distance = _distance(point, entity.position_mm)
            elif isinstance(entity, SplineEntity):
                points = entity.sampled_points()
                distance = min(
                    _distance_to_segment(point, start, end)
                    for start, end in zip(points, points[1:], strict=False)
                )
            elif isinstance(entity, LineEntity):
                distance = _distance_to_segment(point, entity.start_mm, entity.end_mm)
            elif isinstance(entity, PolylineEntity):
                segments = list(zip(entity.points_mm, entity.points_mm[1:], strict=False))
                if entity.closed:
                    segments.append((entity.points_mm[-1], entity.points_mm[0]))
                distance = min(_distance_to_segment(point, start, end) for start, end in segments)
            elif isinstance(entity, RectangleEntity):
                x1, y1 = entity.first_corner_mm
                x2, y2 = entity.opposite_corner_mm
                corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                distance = min(
                    _distance_to_segment(point, start, end)
                    for start, end in zip(corners, (*corners[1:], corners[0]), strict=True)
                )
            elif isinstance(entity, CircleEntity):
                distance = abs(_distance(point, entity.center_mm) - entity.radius_mm)
            else:
                dx, dy = point[0] - entity.center_mm[0], point[1] - entity.center_mm[1]
                angle = math.degrees(math.atan2(dy, dx))
                if _angle_on_arc(angle, entity.start_angle_deg, entity.sweep_angle_deg):
                    distance = abs(math.hypot(dx, dy) - entity.radius_mm)
                else:
                    endpoints = tuple(
                        (
                            entity.center_mm[0] + entity.radius_mm * math.cos(math.radians(value)),
                            entity.center_mm[1] + entity.radius_mm * math.sin(math.radians(value)),
                        )
                        for value in (
                            entity.start_angle_deg,
                            entity.start_angle_deg + entity.sweep_angle_deg,
                        )
                    )
                    distance = min(_distance(point, endpoint) for endpoint in endpoints)
            if distance <= tolerance:
                candidates.append((distance, entity.entity_id))
        candidates.sort()
        if not candidates:
            return None
        if len(candidates) > 1 and (candidates[1][0] - candidates[0][0]) * self._scale <= 1.0:
            return None
        return candidates[0][1]

    def _select_at(self, point: Point2D, *, additive: bool, subtractive: bool = False) -> None:
        identity = self._hit_entity_at(point)
        if not additive and not subtractive:
            self.selected_entity_ids.clear()
        if identity is not None:
            if subtractive:
                self.selected_entity_ids.discard(identity)
            elif additive and identity in self.selected_entity_ids:
                self.selected_entity_ids.remove(identity)
            else:
                self.selected_entity_ids.add(identity)
            self.message = f"已选择 {len(self.selected_entity_ids)} 个草图元素。"
        else:
            self.message = "未命中唯一草图元素；请靠近目标或缩放视图后重试。"
        self.changed.emit()
        self.update()

    def _begin_selection_box(self, event: QMouseEvent) -> None:
        self._selection_anchor = event.position()
        self._selection_corner = event.position()
        self._selection_waiting_click = False
        self._selection_original = frozenset(self.selected_entity_ids)
        self._selection_modifiers = event.modifiers()
        self._hovered_entity_id = None
        self._snap_kind = ""
        self.message = "指定选框对角点：左→右仅选完全包含，右→左选包含或相交；Esc 取消。"
        self.changed.emit()
        self.update()

    def _cancel_selection_box(self) -> bool:
        if self._selection_anchor is None:
            return False
        self.selected_entity_ids = set(self._selection_original)
        self._selection_anchor = None
        self._selection_waiting_click = False
        self.message = "已取消框选。"
        self.changed.emit()
        self.update()
        return True

    def _finish_selection_box(self, position: QPointF) -> None:
        anchor = self._selection_anchor
        if anchor is None:
            return
        crossing = position.x() < anchor.x()
        first, second = self.screen_to_local(anchor), self.screen_to_local(position)
        identities = {
            entity.entity_id
            for entity in self.selectable_entities()
            if entity_in_selection_box(entity, first, second, crossing=crossing)
        }
        if self._selection_modifiers & Qt.KeyboardModifier.ShiftModifier:
            self.selected_entity_ids = set(self._selection_original) - identities
        elif (
            self._selection_modifiers & Qt.KeyboardModifier.ControlModifier
            or self._transform_selecting
        ):
            self.selected_entity_ids = set(self._selection_original) | identities
        else:
            self.selected_entity_ids = identities
        self._selection_anchor = None
        self._selection_waiting_click = False
        mode = "交叉选择" if crossing else "窗口选择"
        self.message = f"{mode} · 已选择 {len(self.selected_entity_ids)} 个草图元素。"
        if self._transform_selecting:
            self.message += " Enter / 右键结束选择，然后指定基点。"
        self.changed.emit()
        self.update()

    @staticmethod
    def _entity_handles(
        entity: SketchEntity,
    ) -> tuple[tuple[SketchGeometryReference, Point2D], ...]:
        if isinstance(entity, PointEntity):
            return ((SketchGeometryReference(entity.entity_id, "vertex", 0), entity.position_mm),)
        if isinstance(entity, SplineEntity):
            return tuple(
                (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                for index, point in enumerate(entity.control_points_mm)
            )
        if isinstance(entity, LineEntity):
            return (
                (SketchGeometryReference(entity.entity_id, "start"), entity.start_mm),
                (SketchGeometryReference(entity.entity_id, "end"), entity.end_mm),
            )
        if isinstance(entity, PolylineEntity):
            return tuple(
                (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                for index, point in enumerate(entity.points_mm)
            )
        if isinstance(entity, RectangleEntity):
            first_u, first_v = entity.first_corner_mm
            opposite_u, opposite_v = entity.opposite_corner_mm
            corners = (
                (first_u, first_v),
                (opposite_u, first_v),
                (opposite_u, opposite_v),
                (first_u, opposite_v),
            )
            return tuple(
                (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                for index, point in enumerate(corners)
            )
        if isinstance(entity, CircleEntity):
            return ((SketchGeometryReference(entity.entity_id, "center"), entity.center_mm),)
        start = math.radians(entity.start_angle_deg)
        end = math.radians(entity.start_angle_deg + entity.sweep_angle_deg)
        return (
            (SketchGeometryReference(entity.entity_id, "center"), entity.center_mm),
            (
                SketchGeometryReference(entity.entity_id, "start"),
                (
                    entity.center_mm[0] + entity.radius_mm * math.cos(start),
                    entity.center_mm[1] + entity.radius_mm * math.sin(start),
                ),
            ),
            (
                SketchGeometryReference(entity.entity_id, "end"),
                (
                    entity.center_mm[0] + entity.radius_mm * math.cos(end),
                    entity.center_mm[1] + entity.radius_mm * math.sin(end),
                ),
            ),
        )

    @staticmethod
    def entity_point_references(
        entity: SketchEntity,
    ) -> tuple[tuple[SketchGeometryReference, Point2D], ...]:
        """Return stable point references and positions for canvas picking."""
        return SketchCanvas._entity_handles(entity)

    def _control_point_at(
        self, point: Point2D
    ) -> tuple[SketchEntity, SketchGeometryReference, Point2D] | None:
        candidates = [
            (entity, reference, handle, _distance(point, handle))
            for entity in self._visible_entities()
            for reference, handle in self._entity_handles(entity)
            if _distance(point, handle) * self._scale <= 10.0
        ]
        candidates.sort(key=lambda item: item[3])
        if not candidates:
            return None
        if len(candidates) > 1 and (candidates[1][3] - candidates[0][3]) * self._scale <= 1.0:
            return None
        entity, reference, handle, _distance_mm = candidates[0]
        return entity, reference, handle

    def _begin_handle_drag(
        self, entity: SketchEntity, reference: SketchGeometryReference, origin: Point2D
    ) -> None:
        if self._layer(entity).locked:
            self.message = "目标图元所在图层已锁定；无法拖动。"
            self.changed.emit()
            return
        self._drag_reference = reference
        self._drag_entity_id = entity.entity_id
        self._drag_origin = origin
        self._drag_original_entities = tuple(self.entities)
        self._drag_original_constraints = tuple(self.constraints)
        self._drag_original_selection = frozenset(self.selected_entity_ids)
        self._drag_last_entities = tuple(self.entities)
        self._drag_last_constraints = tuple(self.constraints)
        self._drag_branch_warning = ""
        self.selected_entity_ids = {entity.entity_id}
        self.message = "正在拖动草图控制点；约束冲突时不会替换上一个有效预览。"
        self.changed.emit()
        self.update()

    @property
    def transform_preview_entities(self) -> tuple[SketchEntity, ...]:
        return self._transform_preview

    @property
    def active_transform(self) -> str | None:
        return self._transform_operation

    @property
    def transform_selecting(self) -> bool:
        return self._transform_operation is not None and self._transform_selecting

    def begin_transform(
        self, operation: str, *, reference_rotation: bool = False, keep_source: bool = True
    ) -> None:
        if operation not in {"move", "copy", "rotate", "mirror"} or self.has_pending_geometry:
            return
        if not self.set_tool("选择元素"):
            return
        error = self.transform_selection_error(operation)
        if error:
            self.message = error
            self.changed.emit()
            return
        self._transform_operation = operation
        self._transform_reference_mode = reference_rotation
        self._transform_reference = None
        self._transform_keep_source = keep_source
        self._copy_repeat = self.copy_mode == 0
        self._transform_angle_text = ""
        self._transform_selecting = not bool(self.selected_entity_ids)
        self._transform_base = None
        self._transform_preview = ()
        self._copy_placements.clear()
        self.message = (
            "选择要变换的图元，Enter / 右键结束选择。"
            if self._transform_selecting
            else self._transform_point_hint()
        )
        self.changed.emit()
        self.setFocus()

    def configure_active_transform(self, *, reference_rotation: bool, keep_source: bool) -> None:
        """Refresh the current preview when its visible options change."""
        if self._transform_operation == "rotate":
            if reference_rotation == self._transform_reference_mode:
                return
            self._transform_reference_mode = reference_rotation
            self._transform_reference = None
            self._transform_angle_text = ""
        elif self._transform_operation == "mirror":
            if keep_source == self._transform_keep_source:
                return
            self._transform_keep_source = keep_source
        else:
            return
        self._transform_preview = ()
        self.message = self._transform_point_hint()
        if not self._transform_selecting and self._cursor is not None:
            self._transform_point(self._cursor, commit=False)
        self.changed.emit()
        self.update()

    def cancel_transform(self) -> bool:
        if self._transform_operation is None:
            return False
        self._transform_operation = None
        self._transform_base = None
        self._transform_preview = ()
        self._transform_selecting = False
        self._transform_reference = None
        self._transform_angle_text = ""
        self._copy_placements.clear()
        self.message = "已结束变换；已完成的修改保留。"
        self.changed.emit()
        self.update()
        return True

    def set_copy_mode(self, mode: int) -> None:
        """Set independent 2D copy behavior: 0 repeats, 1 places once."""
        if mode not in (0, 1):
            raise ValueError("COPYMODE 必须为 0 或 1。")
        if self.copy_mode != mode:
            self.copy_mode = mode
            self.copy_mode_changed.emit(mode)
        if self.copy_options_available:
            self._copy_repeat = mode == 0

    @property
    def copy_options_available(self) -> bool:
        """Whether COPY is waiting for its base point after selection."""
        return (
            self._transform_operation == "copy"
            and not self._transform_selecting
            and self._transform_base is None
        )

    def use_multiple_copy_for_command(self) -> None:
        """Enable repetition for the current COPY without changing its preference."""
        if not self.copy_options_available:
            raise ValueError("请先选择对象，再设置当前复制模式。")
        self._copy_repeat = True

    def transform_selection_error(self, operation: str) -> str:
        """Explain why the selection cannot be transformed without changing geometry."""
        if self._selected_committed_entities() and operation not in {
            "move",
            "copy",
            "rotate",
            "mirror",
        }:
            return "选择包含已提交图元；几何修改请通过历史编辑，当前选择已保留。"
        if operation in {"move", "copy", "rotate", "mirror"} and any(
            layer.locked and entity.entity_id in self.selected_entity_ids
            for entity, layer in self.background_entities
        ):
            return "选择包含已锁定图层；草稿未修改。"
        if any(
            self._layer(entity).locked
            for entity in self.entities
            if entity.entity_id in self.selected_entity_ids
        ):
            return "选择包含已锁定图层；草稿未修改。"
        if any(
            not self._layer(entity).displayed
            for entity in self.entities
            if entity.entity_id in self.selected_entity_ids
        ):
            return "选择包含隐藏图层；草稿未修改。"
        if operation == "move" and any(
            constraint.source == "user"
            and any(
                reference.entity_id in self.selected_entity_ids
                for reference in constraint.references
            )
            for constraint in self.constraints
        ):
            return "本次移动会改变用户约束引用的图元；请先处理相关约束再改几何。草稿未变。"
        return ""

    def copy_selected_to_draft(self, delta: Point2D) -> tuple[SketchEntity, ...]:
        """Copy selected draft and visible committed geometry into the draft."""
        background = tuple(
            entity
            for entity, _layer in self.background_entities
            if entity.entity_id in self.selected_entity_ids
        )
        original_background_ids = {entity.entity_id for entity in background}
        source = (*self.entities, *background)
        selected = tuple(
            entity.entity_id for entity in source if entity.entity_id in self.selected_entity_ids
        )
        return tuple(
            entity
            for entity in copy_entities(source, selected, delta)
            if entity.entity_id not in original_background_ids
        )

    def rotation_draft_error(self, center: Point2D, angle: float) -> str:
        """Check the selected draft geometry before dispatching a mixed rotation."""
        selected = tuple(
            entity.entity_id
            for entity in self.entities
            if entity.entity_id in self.selected_entity_ids
        )
        if not selected:
            return ""
        try:
            candidate = rotate_entities(tuple(self.entities), selected, center, angle)
            self._reject_user_constraint_reference_edits(candidate)
        except ValueError as exc:
            return str(exc)
        return ""

    def mirror_draft_error(self, start: Point2D, end: Point2D) -> str:
        """Check selected draft geometry before dispatching a mixed mirror."""
        selected = tuple(
            entity.entity_id
            for entity in self.entities
            if entity.entity_id in self.selected_entity_ids
        )
        if not selected:
            return ""
        try:
            candidate = mirror_entities(tuple(self.entities), selected, start, end)
            self._reject_user_constraint_reference_edits(candidate)
        except ValueError as exc:
            return str(exc)
        return ""

    def mirror_selected_to_draft(self, start: Point2D, end: Point2D) -> tuple[SketchEntity, ...]:
        """Mirror new copies of selected draft and committed entities into the draft."""
        original_ids = {entity.entity_id for entity in self.entities}
        copied = self.copy_selected_to_draft((0.0, 0.0))
        copies = tuple(
            entity.entity_id for entity in copied if entity.entity_id not in original_ids
        )
        return mirror_entities(copied, copies, start, end)

    def _finish_transform_selection(self) -> None:
        if self._selection_anchor is not None:
            self._finish_selection_box(self._selection_corner)
        if self._transform_selecting and self.selected_entity_ids:
            error = self.transform_selection_error(self._transform_operation or "move")
            if error:
                self.message = error
                self.changed.emit()
                return
            self._transform_selecting = False
            self.message = self._transform_point_hint()
            self.changed.emit()

    def _transform_point_hint(self) -> str:
        if self._transform_operation == "rotate":
            if self._transform_base is None:
                return "旋转：指定旋转中心；Esc 取消。"
            if self._transform_reference_mode and self._transform_reference is None:
                return "参考旋转：指定起始参考点，再指定目标方向。"
            return "旋转：指定目标方向，或键入角度后按 Enter；Esc 取消。"
        if self._transform_operation == "mirror":
            return (
                "镜像：指定镜像轴第一点；Esc 取消。"
                if self._transform_base is None
                else "镜像：指定镜像轴第二点；两点定义无限长镜像轴，Esc 取消。"
            )
        return (
            "指定移动/复制基点；Esc 取消。"
            if self._transform_base is None
            else "指定目标点，或按 Enter 使用基点作为位移；Esc 取消。"
        )

    def _transform_copies_source(self) -> bool:
        return self._transform_operation == "copy" or (
            self._transform_operation == "mirror" and self._transform_keep_source
        )

    def _transform_pointer_point(
        self, raw: Point2D, *, disable_snapping: bool
    ) -> tuple[Point2D, str]:
        point, kind = (
            (raw, "") if self._transform_selecting or disable_snapping else self._snapped(raw)
        )
        base = self._transform_base
        if (
            self._transform_operation in {"move", "copy"}
            and base is not None
            and not self._transform_selecting
            and self._orthogonal_enabled
            and kind in {"", "栅格"}
        ):
            if abs(point[0] - base[0]) >= abs(point[1] - base[1]):
                point = (point[0], base[1])
            else:
                point = (base[0], point[1])
            kind = "正交"
        return point, kind

    def _transform_candidate(
        self, point: Point2D, *, angle_deg: float | None = None
    ) -> tuple[SketchEntity, ...]:
        base = self._transform_base
        if base is None:
            return ()
        transform_entities = (
            (*self.entities, *(entity for entity, _layer in self.background_entities))
            if self._selected_committed_entities()
            else tuple(self.entities)
        )
        selected = tuple(
            entity.entity_id
            for entity in transform_entities
            if entity.entity_id in self.selected_entity_ids
        )
        error = self.transform_selection_error(self._transform_operation or "move")
        if error:
            raise ValueError(error)
        delta = (point[0] - base[0], point[1] - base[1])
        if angle_deg is None and math.hypot(*delta) <= 1e-9:
            raise ValueError("两点重合；请指定不同的方向点。")
        if self._transform_operation == "copy":
            candidate = self.copy_selected_to_draft(delta)
            self._reject_user_constraint_reference_edits(candidate)
            return candidate
        if self._transform_operation == "mirror" and self._transform_keep_source:
            candidate = self.mirror_selected_to_draft(base, point)
            self._reject_user_constraint_reference_edits(candidate)
            return candidate
        entities = transform_entities
        if self._transform_operation == "rotate":
            if angle_deg is None:
                angle_deg = math.degrees(math.atan2(delta[1], delta[0]))
                reference = self._transform_reference
                if reference is not None:
                    angle_deg -= math.degrees(
                        math.atan2(reference[1] - base[1], reference[0] - base[0])
                    )
            candidate = rotate_entities(entities, selected, base, angle_deg)
        elif self._transform_operation == "mirror":
            if self._transform_keep_source:
                source_ids = {entity.entity_id for entity in entities}
                entities = copy_entities(entities, selected, (0.0, 0.0))
                selected = tuple(
                    entity.entity_id for entity in entities if entity.entity_id not in source_ids
                )
            candidate = mirror_entities(entities, selected, base, point)
        else:
            operation = copy_entities if self._transform_operation == "copy" else move_entities
            candidate = operation(entities, selected, delta)
        self._reject_user_constraint_reference_edits(candidate)
        return candidate

    @property
    def rotation_center(self) -> Point2D | None:
        return self._transform_base if self._transform_operation == "rotate" else None

    @property
    def rotation_uses_reference(self) -> bool:
        return self._transform_operation == "rotate" and self._transform_reference_mode

    def apply_rotation_angle(self, angle_deg: float) -> bool:
        """Apply an explicit relative angle about the currently picked center."""
        if self._transform_operation != "rotate" or self._transform_base is None:
            return False
        try:
            candidate = self._transform_candidate(self._transform_base, angle_deg=angle_deg)
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            return False
        if self._selected_committed_entities():
            self._commit_saved_rotation(angle_deg)
        else:
            self._show_transform_candidate(candidate, commit=True)
        return True

    def _commit_saved_rotation(self, angle_deg: float) -> None:
        center = self._transform_base
        assert center is not None
        selected = tuple(self.selected_entity_ids)
        self.cancel_transform()
        self.committed_rotation_requested.emit(selected, center, angle_deg)

    def _show_transform_candidate(
        self, candidate: tuple[SketchEntity, ...], *, commit: bool, point: Point2D | None = None
    ) -> None:
        selected = self.selected_entity_ids
        source_ids = {entity.entity_id for entity in self.entities}
        is_copy = self._transform_copies_source()
        self._transform_preview = tuple(
            entity
            for entity in candidate
            if (entity.entity_id not in source_ids if is_copy else entity.entity_id in selected)
        )
        if commit:
            if (
                self._transform_operation == "copy"
                and self.select_committed_entities
                and self._copy_repeat
            ):
                original_selection = set(selected)
                previous_position = self.history_position
                if self.replace_draft_entities(candidate):
                    assert point is not None
                    self._copy_placements.append((point, previous_position, self.history_position))
                    self.selected_entity_ids = original_selection
                    self._transform_preview = ()
                    self.message = "已复制；指定下一个目标点，U 撤销，Enter / 右键结束。"
                self.changed.emit()
                self.update()
                return
            label = {"move": "移动", "copy": "复制", "rotate": "旋转", "mirror": "镜像"}[
                self._transform_operation or "move"
            ]
            self.cancel_transform()
            self.message = f"已{label}所选图元；可撤销。"
            if self.replace_draft_entities(candidate, select_new=is_copy) and is_copy:
                self.selected_entity_ids = {
                    entity.entity_id for entity in candidate if entity.entity_id not in source_ids
                }
            self.changed.emit()
        else:
            self.message = self._transform_point_hint()
            self.changed.emit()
        self.update()

    def _transform_point(self, point: Point2D, *, commit: bool) -> None:
        if self._transform_selecting:
            if commit:
                self._select_at(point, additive=True)
                self.message = "继续选择图元；Enter / 右键结束选择。"
                self.changed.emit()
            return
        if self._transform_base is None:
            if commit:
                self._transform_base = point
                self.point_accepted.emit(point)
                self.message = self._transform_point_hint()
                self.changed.emit()
                self.update()
            return
        if (
            self._transform_operation == "rotate"
            and self._transform_reference_mode
            and self._transform_reference is None
        ):
            if commit:
                if _distance(point, self._transform_base) <= 1e-9:
                    self.message = "参考点不能与旋转中心重合。"
                else:
                    self._transform_reference = point
                    self.point_accepted.emit(point)
                    self.message = self._transform_point_hint()
                self.changed.emit()
                self.update()
            return
        try:
            candidate = self._transform_candidate(point)
        except ValueError as exc:
            self._transform_preview = ()
            self.message = str(exc)
            self.changed.emit()
            self.update()
            return
        if commit and self._transform_operation == "move" and self._selected_committed_entities():
            base = self._transform_base
            assert base is not None
            selected = tuple(self.selected_entity_ids)
            delta = (point[0] - base[0], point[1] - base[1])
            self.cancel_transform()
            self.committed_move_requested.emit(selected, delta)
            self.point_accepted.emit(point)
            return
        if commit and self._transform_operation == "rotate" and self._selected_committed_entities():
            base = self._transform_base
            assert base is not None
            angle = math.degrees(math.atan2(point[1] - base[1], point[0] - base[0]))
            if self._transform_reference is not None:
                reference = self._transform_reference
                angle -= math.degrees(math.atan2(reference[1] - base[1], reference[0] - base[0]))
            self._commit_saved_rotation(angle)
            self.point_accepted.emit(point)
            return
        if (
            commit
            and self._transform_operation == "mirror"
            and not self._transform_keep_source
            and self._selected_committed_entities()
        ):
            start = self._transform_base
            assert start is not None
            selected = tuple(self.selected_entity_ids)
            self.cancel_transform()
            self.committed_mirror_requested.emit(selected, start, point)
            self.point_accepted.emit(point)
            return
        self._show_transform_candidate(candidate, commit=commit, point=point)
        if commit and tuple(self.entities) == candidate:
            self.point_accepted.emit(point)

    def _confirm_transform_default(self) -> None:
        if self._transform_selecting:
            self._finish_transform_selection()
        elif self._transform_operation == "copy" and self._transform_base is not None:
            if self.select_committed_entities and not self._copy_placements:
                u, v = self._transform_base
                self._transform_point((2 * u, 2 * v), commit=True)
            else:
                self.cancel_transform()
                self.message = "复制已结束；已放置的副本保留。"
                self.changed.emit()
        elif self._transform_operation == "move" and self._transform_base is not None:
            u, v = self._transform_base
            self._transform_point((2 * u, 2 * v), commit=True)

    @property
    def copy_last_point(self) -> Point2D | None:
        """Last retained copy destination, or its original base point."""
        if self._transform_operation != "copy":
            return None
        return self._copy_placements[-1][0] if self._copy_placements else self._transform_base

    def undo_copy_placement(self) -> bool:
        """Undo only the latest placement in the active repeated-copy gesture."""
        if self._transform_operation != "copy" or not self._copy_placements:
            self.message = "没有可撤销的复制；请选择目标点。"
            self.changed.emit()
            return False
        _point, before, after = self._copy_placements[-1]
        if (
            self.history_position != after
            or not self._undo_history
            or self._undo_history[-1].history_position != before
        ):
            self.message = "草稿历史已变化，无法撤销该复制；请结束当前命令。"
            self.changed.emit()
            return False
        self._redo_history.append(self._draft_state())
        self._restore_draft_state(self._undo_history.pop())
        self._copy_placements.pop()
        self._transform_preview = ()
        self.message = "已撤销上一个副本；指定下一个目标点。"
        if self.copy_last_point is not None:
            self.point_accepted.emit(self.copy_last_point)
        self.changed.emit()
        self.update()
        return True

    def _begin_trim_drag(self, point: Point2D) -> None:
        self._clear_line_edit_preview()
        self._trim_drag_start = point
        self._trim_drag_last = point
        self._hovered_line_edit_entity_id = self._trim_target_at(point)
        self._trim_drag_original_entities = tuple(self.entities)
        self._trim_drag_original_constraints = tuple(self.constraints)
        self._trim_drag_original_selection = frozenset(self.selected_entity_ids)
        self._trim_drag_candidate_entities = tuple(self.entities)
        self._trim_drag_changed_count = 0
        self._trim_drag_last_error = None
        self._trim_drag_moved = False

    def _clear_trim_drag(self) -> None:
        self._clear_line_edit_preview()
        self._trim_drag_start = None
        self._trim_drag_last = None
        self._trim_drag_original_entities = None
        self._trim_drag_original_constraints = None
        self._trim_drag_original_selection = None
        self._trim_drag_candidate_entities = None
        self._trim_drag_changed_count = 0
        self._trim_drag_last_error = None
        self._trim_drag_moved = False

    def _update_trim_drag(self, point: Point2D) -> None:
        start = self._trim_drag_start
        previous = self._trim_drag_last
        candidate_entities = self._trim_drag_candidate_entities
        if start is None or previous is None or candidate_entities is None:
            return
        if _distance(point, start) * self._scale > 3.0:
            self._trim_drag_moved = True
        if not self._trim_drag_moved:
            self._trim_drag_last = point
            return

        sample_count = max(1, math.ceil(_distance(previous, point) * self._scale / 6.0))
        for sample_index in range(sample_count + 1):
            ratio = sample_index / sample_count
            sample = (
                previous[0] + ratio * (point[0] - previous[0]),
                previous[1] + ratio * (point[1] - previous[1]),
            )
            self.entities = list(candidate_entities)
            self._snap_candidates_cache = None
            target_id = self._trim_target_at(sample)
            if target_id is None:
                continue
            target = next(
                (entity for entity in candidate_entities if entity.entity_id == target_id),
                None,
            )
            if target is None:
                continue
            if self._layer(target).locked:
                self._trim_drag_last_error = "目标图元所在图层已锁定；草图未修改。"
                continue
            visible = tuple(
                entity for entity in candidate_entities if self._layer(entity).displayed
            )
            try:
                updated_visible = trim_curve_at(
                    visible,
                    sample,
                    hit_tolerance_mm=_SNAP_RADIUS_PX / self._scale,
                    target_entity_id=target_id,
                    allow_endpoint_intersections=True,
                )
            except ValueError as exc:
                self._trim_drag_last_error = str(exc)
                continue
            updated = self._merge_hidden_entities(candidate_entities, updated_visible)
            if updated == candidate_entities:
                continue
            candidate_entities = updated
            self._trim_drag_candidate_entities = updated
            self._trim_drag_changed_count += 1

        self._trim_drag_candidate_entities = candidate_entities
        self._trim_drag_last = point
        self.entities = list(candidate_entities)
        self._snap_candidates_cache = None
        self.message = (
            f"拖动修剪预览 · 已选 {self._trim_drag_changed_count} 个区段；松开保留，Esc 取消。"
            if self._trim_drag_changed_count
            else self._trim_drag_last_error or "拖过要修剪的曲线区段；松开完成，Esc 取消。"
        )
        self.changed.emit()
        self.update()

    def _finish_trim_drag(self) -> bool:
        start = self._trim_drag_start
        original = self._trim_drag_original_entities
        original_constraints = self._trim_drag_original_constraints
        original_selection = self._trim_drag_original_selection
        candidate = self._trim_drag_candidate_entities
        moved = self._trim_drag_moved
        changed_count = self._trim_drag_changed_count
        last_error = self._trim_drag_last_error
        if start is None or original is None or original_constraints is None or candidate is None:
            return False
        if not moved:
            self.entities = list(original)
            self.constraints = list(original_constraints)
            self.selected_entity_ids = set(original_selection or ())
            self._snap_candidates_cache = None
            self._clear_trim_drag()
            self._hovered_line_edit_entity_id = None
            self._accept_point(start)
            return True
        if candidate != original:
            try:
                self._reject_user_constraint_reference_edits(candidate, original_entities=original)
            except ValueError as exc:
                self.entities = list(original)
                self.constraints = list(original_constraints)
                self.selected_entity_ids = set(original_selection or ())
                self._snap_candidates_cache = None
                self.message = str(exc)
                self._clear_trim_drag()
                self._hovered_line_edit_entity_id = None
                self.changed.emit()
                self.update()
                return True
            self._undo_history.append(
                _DraftState(
                    original,
                    original_constraints,
                    original_selection or frozenset(),
                    self.layer_table,
                    self.active_layer_name,
                    history_position=self.history_position,
                    mixed_move=self.mixed_move,
                )
            )
            self._advance_history()
            self.entities = list(candidate)
            self.constraints = list(original_constraints)
            removed_relations = self._preserve_satisfied_relations(
                candidate, original_entities=original
            )
            available = {entity.entity_id for entity in candidate}
            self.selected_entity_ids.intersection_update(available)
            self._snap_candidates_cache = None
            self.message = f"拖动修剪完成；本次移除了 {changed_count} 个选定区段。"
            if removed_relations:
                self.message += f" 已移除 {removed_relations} 条失效或需重新确认的自动关系。"
        else:
            self.entities = list(original)
            self.constraints = list(original_constraints)
            self.selected_entity_ids = set(original_selection or ())
            self._snap_candidates_cache = None
            self.message = last_error or "拖动路径没有命中可修剪区段；草图未修改。"
        self._clear_trim_drag()
        self._hovered_line_edit_entity_id = None
        self.changed.emit()
        self.update()
        return True

    def _cancel_trim_drag(self) -> bool:
        original = self._trim_drag_original_entities
        original_constraints = self._trim_drag_original_constraints
        if original is None or original_constraints is None:
            return False
        self.entities = list(original)
        self.constraints = list(original_constraints)
        self.selected_entity_ids = set(self._trim_drag_original_selection or ())
        self._snap_candidates_cache = None
        self._clear_trim_drag()
        self._hovered_line_edit_entity_id = None
        self.message = "已取消拖动修剪；草图几何保持原样。"
        self.changed.emit()
        self.update()
        return True

    def _drag_target(self, raw_point: Point2D) -> tuple[Point2D, str]:
        origin = self._drag_origin
        if origin is None or not self._snapping_enabled:
            return raw_point, ""
        candidates = tuple(
            candidate
            for candidate in self._snap_candidates()
            if _distance(candidate[0], origin) > 1e-9
        )
        nearest = min(
            candidates,
            key=lambda candidate: (
                _distance(raw_point, candidate[0]),
                _SNAP_PRIORITY.get(candidate[1], len(_SNAP_PRIORITY)),
            ),
            default=None,
        )
        if (
            nearest is not None
            and _distance(raw_point, nearest[0]) * self._scale <= _SNAP_RADIUS_PX
        ):
            return nearest
        return raw_point, ""

    def _solve_handle_drag(
        self,
        entities: tuple[SketchEntity, ...],
        constraints: tuple[SketchConstraint, ...],
        reference: SketchGeometryReference,
        point: Point2D,
    ) -> tuple[tuple[SketchEntity, ...], tuple[SketchConstraint, ...]] | None:
        if self._drag_solver is None:
            if constraints:
                return None
            try:
                return move_sketch_handle(entities, reference, point), constraints
            except ValueError as exc:
                self.message = str(exc)
                return None
        try:
            result = self._drag_solver(entities, constraints, reference, point)
        except (RuntimeError, TypeError, ValueError) as exc:
            self.message = f"约束拖动求解失败；当前几何保持原样：{exc}"
            return None
        if result.status == "success" and result.sketch is not None:
            self._drag_branch_warning = "；".join(
                f"{change.message}（{'、'.join(identity[:8] for identity in change.entity_ids)}）"
                for change in result.branch_changes
            )
            return result.sketch.entities, result.sketch.constraints
        if result.status == "unavailable" and not constraints:
            try:
                return move_sketch_handle(entities, reference, point), constraints
            except ValueError as exc:
                self.message = str(exc)
                return None
        self.message = result.message or "草图约束无法满足拖动位置。"
        return None

    def _clear_handle_drag(self) -> None:
        self._drag_reference = None
        self._drag_entity_id = None
        self._drag_origin = None
        self._drag_original_entities = None
        self._drag_original_constraints = None
        self._drag_original_selection = None
        self._drag_last_entities = None
        self._drag_last_constraints = None
        self._drag_branch_warning = ""

    def _cancel_handle_drag(self) -> bool:
        if self._drag_original_entities is None or self._drag_original_constraints is None:
            return False
        self.entities = list(self._drag_original_entities)
        self.constraints = list(self._drag_original_constraints)
        self.selected_entity_ids = set(self._drag_original_selection or ())
        self._snap_candidates_cache = None
        self._clear_handle_drag()
        self.message = "已取消控制点拖动；草图几何保持原样。"
        self.changed.emit()
        self.update()
        return True

    def _finish_handle_drag(self) -> bool:
        original = self._drag_original_entities
        original_constraints = self._drag_original_constraints
        current = self._drag_last_entities
        current_constraints = self._drag_last_constraints
        if (
            original is None
            or original_constraints is None
            or current is None
            or current_constraints is None
        ):
            return False
        if current != original or current_constraints != original_constraints:
            self._undo_history.append(
                _DraftState(
                    original,
                    original_constraints,
                    self._drag_original_selection or frozenset(),
                    self.layer_table,
                    self.active_layer_name,
                    history_position=self.history_position,
                    mixed_move=self.mixed_move,
                )
            )
            self._advance_history()
            self.entities = list(current)
            self.constraints = list(current_constraints)
            self._snap_candidates_cache = None
            self.message = "草图控制点已更新；当前约束保持满足，可撤销本次拖动。"
            if self._drag_branch_warning:
                self.message += f" 分支变化：{self._drag_branch_warning}。请核对当前几何。"
        else:
            self.entities = list(original)
            self.constraints = list(original_constraints)
            self.message = "控制点未移动；草图保持原样。"
        self._clear_handle_drag()
        self.changed.emit()
        self.update()
        return True

    def set_arc_direction(self, direction: str) -> None:
        self.arc_direction = direction
        self.update()

    def set_construction(self, construction: bool) -> None:
        self.construction = construction

    def set_snapping_enabled(self, enabled: bool) -> None:
        self._snapping_enabled = enabled
        self._snap_kind = ""
        self.message = "几何捕捉已启用。" if enabled else "几何捕捉已关闭；当前草图仍可按坐标绘制。"
        self.changed.emit()
        self.update()

    def set_orthogonal_enabled(self, enabled: bool) -> None:
        """Constrain unsnapped line/polyline points to the nearest axis."""
        self._orthogonal_enabled = enabled
        self.message = (
            "正交输入已启用；直线和折线按位移较大的方向锁轴。" if enabled else "正交输入已关闭。"
        )
        self.changed.emit()
        self.update()

    def set_auto_inference_enabled(self, enabled: bool) -> None:
        """Snap near-axis straight lines and retain the inferred relation."""
        self._auto_inference_enabled = enabled
        self.message = (
            "自动关系已启用；接近水平/竖直的直线会吸附并保留关系。"
            if enabled
            else "自动关系已关闭；绘图结果不会自动吸附到水平/竖直方向。"
        )
        self.changed.emit()
        self.update()

    def set_closed_polyline(self, closed: bool) -> None:
        self.closed_polyline = closed

    @property
    def pending_point_count(self) -> int:
        return len(self._points)

    @property
    def pending_last_point(self) -> Point2D | None:
        return self._points[-1] if self._points else None

    @property
    def current_snap_kind(self) -> str:
        return self._snap_kind

    @property
    def hovered_trim_target_id(self) -> str | None:
        """Return the uniquely preselected curve identity while trim is active."""
        return self._hovered_line_edit_entity_id

    @property
    def hovered_line_edit_target_id(self) -> str | None:
        """Return the uniquely preselected entity identity for the active edit tool."""
        return self._hovered_line_edit_entity_id

    @property
    def previewed_line_edit_original(self) -> SketchEntity | None:
        """Return the unmodified entity ghosted by a valid edit preview."""
        return self._line_edit_preview_original

    @property
    def previewed_line_edit_entities(self) -> tuple[SketchEntity, ...]:
        """Return candidate edit entities without applying them to the draft."""
        return self._line_edit_preview_result

    def _trim_target_at(self, point: Point2D, *, lines_only: bool = False) -> str | None:
        tolerance = _SNAP_RADIUS_PX / self._scale
        candidates: list[tuple[SketchEntity, float]] = []
        for entity in self._visible_entities():
            if isinstance(entity, PointEntity | SplineEntity):
                continue
            if isinstance(entity, LineEntity):
                distance = _distance_to_segment(point, entity.start_mm, entity.end_mm)
            elif isinstance(entity, PolylineEntity):
                points = entity.points_mm
                segments = tuple(zip(points, points[1:], strict=False))
                if entity.closed:
                    segments = (*segments, (points[-1], points[0]))
                distance = min(_distance_to_segment(point, start, end) for start, end in segments)
            elif isinstance(entity, RectangleEntity):
                x1, y1 = entity.first_corner_mm
                x2, y2 = entity.opposite_corner_mm
                corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                distance = min(
                    _distance_to_segment(point, start, end)
                    for start, end in zip(corners, (*corners[1:], corners[0]), strict=True)
                )
            elif not lines_only:
                dx, dy = point[0] - entity.center_mm[0], point[1] - entity.center_mm[1]
                radius_distance = math.hypot(dx, dy)
                if isinstance(entity, CircleEntity):
                    distance = abs(radius_distance - entity.radius_mm)
                else:
                    angle = math.degrees(math.atan2(dy, dx))
                    if _angle_on_arc(angle, entity.start_angle_deg, entity.sweep_angle_deg):
                        distance = abs(radius_distance - entity.radius_mm)
                    else:
                        endpoints = tuple(
                            (
                                entity.center_mm[0]
                                + entity.radius_mm * math.cos(math.radians(value)),
                                entity.center_mm[1]
                                + entity.radius_mm * math.sin(math.radians(value)),
                            )
                            for value in (
                                entity.start_angle_deg,
                                entity.start_angle_deg + entity.sweep_angle_deg,
                            )
                        )
                        distance = min(_distance(point, endpoint) for endpoint in endpoints)
            else:
                continue
            if distance <= tolerance:
                candidates.append((entity, distance))
        candidates.sort(key=lambda item: item[1])
        if not candidates:
            return None
        if len(candidates) > 1 and (candidates[1][1] - candidates[0][1]) * self._scale <= 1.0:
            return None
        return candidates[0][0].entity_id

    def _extend_target_at(self, point: Point2D) -> str | None:
        tolerance = _SNAP_RADIUS_PX / self._scale
        candidates: list[tuple[LineEntity | ArcEntity | PolylineEntity, float]] = []
        for entity in self._visible_entities():
            if isinstance(entity, LineEntity):
                endpoints = (entity.start_mm, entity.end_mm)
            elif isinstance(entity, ArcEntity):
                endpoints = tuple(
                    (
                        entity.center_mm[0] + entity.radius_mm * math.cos(math.radians(angle)),
                        entity.center_mm[1] + entity.radius_mm * math.sin(math.radians(angle)),
                    )
                    for angle in (
                        entity.start_angle_deg,
                        entity.start_angle_deg + entity.sweep_angle_deg,
                    )
                )
            elif isinstance(entity, PolylineEntity) and not entity.closed:
                endpoints = (entity.points_mm[0], entity.points_mm[-1])
            else:
                continue
            candidates.extend(
                (entity, _distance(point, endpoint))
                for endpoint in endpoints
                if _distance(point, endpoint) <= tolerance
            )
        candidates.sort(key=lambda item: item[1])
        if not candidates:
            return None
        if len(candidates) > 1 and (candidates[1][1] - candidates[0][1]) * self._scale <= 1.0:
            return None
        return candidates[0][0].entity_id

    def _clear_line_edit_preview(self) -> None:
        self._line_edit_preview_original = None
        self._line_edit_preview_result = ()

    def _refresh_line_edit_preview(self, mode: str | None) -> None:
        self._clear_line_edit_preview()
        target_id = self._hovered_line_edit_entity_id
        point = self._cursor
        if mode not in {"修剪", "延伸"} or target_id is None or point is None:
            return
        visible_entities = self._visible_entities()
        original = next(
            (entity for entity in visible_entities if entity.entity_id == target_id), None
        )
        if original is None or self._layer(original).locked:
            return
        operation = trim_curve_at if mode == "修剪" else extend_curve_at
        try:
            updated_visible = operation(
                visible_entities,
                point,
                hit_tolerance_mm=_SNAP_RADIUS_PX / self._scale,
                target_entity_id=target_id,
            )
            updated = self._merge_hidden_entities(tuple(self.entities), updated_visible)
            self._reject_user_constraint_reference_edits(updated)
        except ValueError:
            return
        if updated_visible == visible_entities:
            return
        original_ids = {entity.entity_id for entity in visible_entities}
        result = tuple(
            entity
            for entity in updated_visible
            if entity.entity_id == target_id or entity.entity_id not in original_ids
        )
        if result:
            self._line_edit_preview_original = original
            self._line_edit_preview_result = result

    def add_coordinate_point(self, point: Point2D, *, exact_point: bool = False) -> None:
        """Add a point; explicit numeric input bypasses snap and inference."""
        if self.dynamic_click_guard is not None and not self.dynamic_click_guard():
            self.message = "请先修正光标尺寸输入，或按 Esc 取消。"
            self.changed.emit()
            return
        self._accept_point(point, exact_point=exact_point)

    def refresh_dynamic_preview(self) -> None:
        if self._first is None or self._last_placement_raw is None:
            return
        point, self._snap_kind = self._placement_point(self._last_placement_raw)
        if self.dynamic_point_resolver is not None:
            try:
                resolved = self.dynamic_point_resolver(self._first, point)
                if resolved != point:
                    self._snap_kind = ""
                point = resolved
            except ValueError as exc:
                self.message = str(exc)
                self.changed.emit()
                return
        self._cursor = point
        self.cursor_changed.emit(*point, self._snap_kind)
        self.update()

    def finish_polyline(self, *, close: bool = False) -> None:
        if self.tool == "样条曲线":
            self.finish_spline()
            return
        if not self._current_layer_can_draw():
            self.message = "当前图层隐藏或已锁定，无法创建图元。"
            self.changed.emit()
            return
        if len(self._points) < 2:
            self.message = "多段线至少需要两个点。"
            self.changed.emit()
            return
        points = list(self._points)
        closed = close or self.closed_polyline
        if closed and points[-1] == points[0]:
            points.pop()
        try:
            entity = PolylineEntity(
                uuid4().hex,
                tuple(points),
                closed=closed,
                construction=self.construction,
                layer_name=self.active_layer_name,
            )
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            return
        self._record_undo()
        self.entities.append(entity)
        self.constraints.extend(self._inferred_constraints_for_entity(entity))
        self._snap_candidates_cache = None
        self._points.clear()
        self.message = "多段线已加入草稿。"
        self.changed.emit()
        self.update()

    def finish_spline(self) -> None:
        if not self._current_layer_can_draw():
            self.message = "当前图层隐藏或锁定，无法完成样条。"
            self.changed.emit()
            return
        try:
            entity = SplineEntity(
                uuid4().hex, tuple(self._points), self.construction, self.active_layer_name
            )
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            return
        self._record_undo()
        self.entities.append(entity)
        self._points.clear()
        self._first = None
        self._snap_candidates_cache = None
        self.message = "三次 B 样条已加入草稿；选择后可拖动控制点。"
        self.changed.emit()
        self.update()

    def undo_last_operation(self) -> bool:
        if not self.can_undo:
            return False
        self._redo_history.append(self._draft_state())
        self._restore_draft_state(self._undo_history.pop())
        self.message = "已撤销上一项草稿操作。"
        self.changed.emit()
        self.update()
        return True

    def discard_redo_history(self) -> None:
        """A new document command abandons future operations on the draft branch."""
        self._redo_history.clear()
        self.changed.emit()

    def redo_last_operation(self) -> bool:
        if not self.can_redo:
            return False
        self._undo_history.append(self._draft_state())
        self._restore_draft_state(self._redo_history.pop())
        self.message = "已重做上一项草稿操作。"
        self.changed.emit()
        self.update()
        return True

    def _segments(self) -> list[tuple[Point2D, Point2D]]:
        segments: list[tuple[Point2D, Point2D]] = []
        for entity in self.visible_snap_entities():
            if isinstance(entity, LineEntity):
                segments.append((entity.start_mm, entity.end_mm))
            elif isinstance(entity, PolylineEntity):
                segments.extend(zip(entity.points_mm, entity.points_mm[1:], strict=False))
                if entity.closed:
                    segments.append((entity.points_mm[-1], entity.points_mm[0]))
            elif isinstance(entity, RectangleEntity):
                x1, y1 = entity.first_corner_mm
                x2, y2 = entity.opposite_corner_mm
                corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                segments.extend(zip(corners, (*corners[1:], corners[0]), strict=True))
        return segments

    def _snap_candidates(self) -> list[tuple[Point2D, str]]:
        if self._snap_candidates_cache is not None:
            return list(self._snap_candidates_cache)
        candidates: list[tuple[Point2D, str]] = []
        segments = self._segments()
        circular_curves: list[tuple[Point2D, float, float, float]] = []
        for entity in self.visible_snap_entities():
            if isinstance(entity, PointEntity):
                candidates.append((entity.position_mm, "点"))
            elif isinstance(entity, SplineEntity):
                candidates.extend(
                    ((entity.control_points_mm[0], "端点"), (entity.control_points_mm[-1], "端点"))
                )
            elif isinstance(entity, LineEntity):
                candidates.extend(
                    (
                        (entity.start_mm, "端点"),
                        (entity.end_mm, "端点"),
                        (
                            (
                                (entity.start_mm[0] + entity.end_mm[0]) / 2.0,
                                (entity.start_mm[1] + entity.end_mm[1]) / 2.0,
                            ),
                            "中点",
                        ),
                    )
                )
            elif isinstance(entity, PolylineEntity):
                candidates.extend((point, "端点") for point in entity.points_mm)
            elif isinstance(entity, CircleEntity | ArcEntity):
                candidates.append((entity.center_mm, "圆心"))
                if isinstance(entity, ArcEntity):
                    circular_curves.append(
                        (
                            entity.center_mm,
                            entity.radius_mm,
                            entity.start_angle_deg,
                            entity.sweep_angle_deg,
                        )
                    )
                    for angle in (
                        entity.start_angle_deg,
                        entity.start_angle_deg + entity.sweep_angle_deg,
                    ):
                        radians = math.radians(angle)
                        candidates.append(
                            (
                                (
                                    entity.center_mm[0] + entity.radius_mm * math.cos(radians),
                                    entity.center_mm[1] + entity.radius_mm * math.sin(radians),
                                ),
                                "端点",
                            )
                        )
                else:
                    circular_curves.append((entity.center_mm, entity.radius_mm, 0.0, 360.0))
            else:
                x1, y1 = entity.first_corner_mm
                x2, y2 = entity.opposite_corner_mm
                corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
                candidates.extend((point, "端点") for point in corners)
                candidates.append((((x1 + x2) / 2.0, (y1 + y2) / 2.0), "中心"))
        for first_index, (start, end) in enumerate(segments):
            candidates.append((((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0), "中点"))
            vector_a = (end[0] - start[0], end[1] - start[1])
            for other_start, other_end in segments[first_index + 1 :]:
                vector_b = (
                    other_end[0] - other_start[0],
                    other_end[1] - other_start[1],
                )
                divisor = _cross(vector_a, vector_b)
                if abs(divisor) <= 1e-12:
                    continue
                delta = (other_start[0] - start[0], other_start[1] - start[1])
                first_ratio = _cross(delta, vector_b) / divisor
                second_ratio = _cross(delta, vector_a) / divisor
                if 0.0 <= first_ratio <= 1.0 and 0.0 <= second_ratio <= 1.0:
                    candidates.append(
                        (
                            (
                                start[0] + first_ratio * vector_a[0],
                                start[1] + first_ratio * vector_a[1],
                            ),
                            "交点",
                        )
                    )
        for start, end in segments:
            for center, radius, start_angle, sweep_angle in circular_curves:
                for point in _segment_circle_intersections(start, end, center, radius):
                    angle = math.degrees(math.atan2(point[1] - center[1], point[0] - center[0]))
                    if _angle_on_arc(angle, start_angle, sweep_angle):
                        candidates.append((point, "交点"))
        for index, first_curve in enumerate(circular_curves):
            for second_curve in circular_curves[index + 1 :]:
                points = _circle_circle_intersections(
                    first_curve[0], first_curve[1], second_curve[0], second_curve[1]
                )
                for point in points:
                    first_angle = math.degrees(
                        math.atan2(point[1] - first_curve[0][1], point[0] - first_curve[0][0])
                    )
                    second_angle = math.degrees(
                        math.atan2(point[1] - second_curve[0][1], point[0] - second_curve[0][0])
                    )
                    if _angle_on_arc(first_angle, first_curve[2], first_curve[3]) and _angle_on_arc(
                        second_angle, second_curve[2], second_curve[3]
                    ):
                        candidates.append((point, "交点"))
        self._snap_candidates_cache = tuple(candidates)
        return candidates

    def apply_constraint_solution(self, original: Sketch, solved: Sketch) -> bool:
        """Apply one isolated solve atomically as a locally undoable draft edit."""
        if (
            tuple(self.entities) != original.entities
            or tuple(self.constraints) != original.constraints
        ):
            return False
        self._record_undo()
        self.entities = list(solved.entities)
        self.constraints = list(solved.constraints)
        self._snap_candidates_cache = None
        self.message = "尺寸已应用到草稿；可撤销。完成草图后写入文档。"
        self.changed.emit()
        self.update()
        return True

    def configure_polygon(self, sides: int, *, circumscribed: bool) -> None:
        if not 3 <= sides <= 128:
            raise ValueError("正多边形边数须为 3–128。")
        self.polygon_sides = sides
        self.polygon_circumscribed = circumscribed
        self.update()

    def set_grid_visible(self, visible: bool) -> None:
        self.grid_visible = visible
        self.update()

    def grid_spacing_mm(self) -> float:
        base = 10.0 ** math.floor(math.log10(24.0 / self._scale))
        return next(step * base for step in (1, 2, 5, 10) if step * base * self._scale >= 24)

    def set_grid_snapping_enabled(self, enabled: bool) -> None:
        self._grid_snapping_enabled = enabled
        self.update()

    def _snapped(self, point: Point2D) -> tuple[Point2D, str]:
        snap_limit = _SNAP_RADIUS_PX / self._scale
        candidates = self._snap_candidates() if self._snapping_enabled else []
        if self._snapping_enabled and self.can_close_chain:
            start = self._points[0]
            if _distance(point, start) <= snap_limit:
                return start, "闭合首点"
        anchor = self._points[-1] if self.tool == "多段线" and self._points else self._first
        if self.tool == "直线" and self._first is not None:
            anchor = self._first
        if self._snapping_enabled and anchor is not None and self.tool in {"直线", "多段线"}:
            candidates.extend(self._reference_snap_candidates(anchor))
        nearest = min(
            candidates,
            key=lambda candidate: (
                _distance(point, candidate[0]),
                _SNAP_PRIORITY.get(candidate[1], len(_SNAP_PRIORITY)),
            ),
            default=None,
        )
        if nearest is not None and _distance(point, nearest[0]) <= snap_limit:
            return nearest
        if self._snapping_enabled and _distance(point, (0.0, 0.0)) <= snap_limit:
            return (0.0, 0.0), "UCS 原点"
        if self._grid_snapping_enabled:
            step = self.grid_spacing_mm()
            grid_point = (round(point[0] / step) * step, round(point[1] / step) * step)
            if _distance(point, grid_point) <= snap_limit:
                return grid_point, "栅格"
        return point, ""

    def _reference_snap_candidates(self, anchor: Point2D) -> list[tuple[Point2D, str]]:
        """Find feet and curve tangencies from the current line endpoint."""
        candidates: list[tuple[Point2D, str]] = []
        for start, end in self._segments():
            delta = (end[0] - start[0], end[1] - start[1])
            length_squared = delta[0] ** 2 + delta[1] ** 2
            if length_squared <= 1e-24:
                continue
            ratio = (
                (anchor[0] - start[0]) * delta[0] + (anchor[1] - start[1]) * delta[1]
            ) / length_squared
            if 0.0 <= ratio <= 1.0:
                candidates.append(
                    (
                        (start[0] + ratio * delta[0], start[1] + ratio * delta[1]),
                        "垂足",
                    )
                )

        for entity in self.visible_snap_entities():
            if isinstance(entity, CircleEntity):
                center = entity.center_mm
                radius = entity.radius_mm
                start_angle, sweep_angle = 0.0, 360.0
            elif isinstance(entity, ArcEntity):
                center = entity.center_mm
                radius = entity.radius_mm
                start_angle, sweep_angle = entity.start_angle_deg, entity.sweep_angle_deg
            else:
                continue
            delta_x, delta_y = anchor[0] - center[0], anchor[1] - center[1]
            distance = math.hypot(delta_x, delta_y)
            if distance <= radius + 1e-12:
                continue
            center_angle = math.degrees(math.atan2(delta_y, delta_x))
            tangent_offset = math.degrees(math.acos(radius / distance))
            for angle in (center_angle + tangent_offset, center_angle - tangent_offset):
                if not _angle_on_arc(angle, start_angle, sweep_angle):
                    continue
                radians = math.radians(angle)
                candidates.append(
                    (
                        (
                            center[0] + radius * math.cos(radians),
                            center[1] + radius * math.sin(radians),
                        ),
                        "切点",
                    )
                )
        return candidates

    def _placement_point(
        self, raw_point: Point2D, *, temporarily_disable_snapping: bool = False
    ) -> tuple[Point2D, str]:
        snap_temporarily_disabled = temporarily_disable_snapping
        point, snap_kind = (
            (raw_point, "临时关闭捕捉") if snap_temporarily_disabled else self._snapped(raw_point)
        )
        if (snap_kind and not snap_temporarily_disabled) or self.tool not in {"直线", "多段线"}:
            return point, snap_kind
        anchor = self._points[-1] if self.tool == "多段线" and self._points else self._first
        if anchor is None:
            return point, snap_kind
        if self.tool == "直线" and self._auto_inference_enabled and not snap_temporarily_disabled:
            inferred = self._near_axis_point(anchor, point)
            if inferred is not None:
                return inferred
        if self._orthogonal_enabled:
            if abs(point[0] - anchor[0]) >= abs(point[1] - anchor[1]):
                relation = "水平关系" if self.tool == "直线" else ""
                status = relation
                if snap_temporarily_disabled:
                    status = f"临时关闭捕捉 · {relation}" if relation else "临时关闭捕捉"
                return (point[0], anchor[1]), status
            relation = "竖直关系" if self.tool == "直线" else ""
            status = relation
            if snap_temporarily_disabled:
                status = f"临时关闭捕捉 · {relation}" if relation else "临时关闭捕捉"
            return (anchor[0], point[1]), status
        return point, snap_kind

    def _near_axis_point(self, anchor: Point2D, point: Point2D) -> tuple[Point2D, str] | None:
        """Return an exact axis endpoint when its angular deviation is below five degrees."""
        delta_u, delta_v = point[0] - anchor[0], point[1] - anchor[1]
        if math.hypot(delta_u, delta_v) * self._scale < 8.0:
            return None
        tangent = math.tan(math.radians(5.0))
        if abs(delta_v) <= abs(delta_u) * tangent:
            return (point[0], anchor[1]), "水平关系"
        if abs(delta_u) <= abs(delta_v) * tangent:
            return (anchor[0], point[1]), "竖直关系"
        return None

    def _line_inferred_constraints(self, line: LineEntity) -> tuple[SketchConstraint, ...]:
        if not self._auto_inference_enabled:
            return ()
        kind = (
            "horizontal"
            if abs(line.start_mm[1] - line.end_mm[1]) <= 1e-12
            else "vertical"
            if abs(line.start_mm[0] - line.end_mm[0]) <= 1e-12
            else None
        )
        if kind is None:
            return ()
        return (
            SketchConstraint(
                uuid4().hex,
                kind,
                (SketchGeometryReference(line.entity_id, "geometry"),),
                source="inferred",
            ),
        )

    @staticmethod
    def _stable_point_references(
        entity: SketchEntity,
    ) -> tuple[tuple[SketchGeometryReference, Point2D], ...]:
        if isinstance(entity, PointEntity):
            return ((SketchGeometryReference(entity.entity_id, "vertex", 0), entity.position_mm),)
        if isinstance(entity, SplineEntity):
            return ()
        if isinstance(entity, LineEntity):
            return (
                (SketchGeometryReference(entity.entity_id, "start"), entity.start_mm),
                (SketchGeometryReference(entity.entity_id, "end"), entity.end_mm),
            )
        if isinstance(entity, PolylineEntity):
            if entity.closed:
                return tuple(
                    (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                    for index, point in enumerate(entity.points_mm)
                )
            return (
                (SketchGeometryReference(entity.entity_id, "start"), entity.points_mm[0]),
                *(
                    (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                    for index, point in enumerate(entity.points_mm[1:-1], start=1)
                ),
                (SketchGeometryReference(entity.entity_id, "end"), entity.points_mm[-1]),
            )
        if isinstance(entity, RectangleEntity):
            first_u, first_v = entity.first_corner_mm
            opposite_u, opposite_v = entity.opposite_corner_mm
            corners = (
                (first_u, first_v),
                (opposite_u, first_v),
                (opposite_u, opposite_v),
                (first_u, opposite_v),
            )
            return tuple(
                (SketchGeometryReference(entity.entity_id, "vertex", index), point)
                for index, point in enumerate(corners)
            )
        if isinstance(entity, CircleEntity):
            return ((SketchGeometryReference(entity.entity_id, "center"), entity.center_mm),)
        start = math.radians(entity.start_angle_deg)
        end = math.radians(entity.start_angle_deg + entity.sweep_angle_deg)
        return (
            (SketchGeometryReference(entity.entity_id, "center"), entity.center_mm),
            (
                SketchGeometryReference(entity.entity_id, "start"),
                (
                    entity.center_mm[0] + entity.radius_mm * math.cos(start),
                    entity.center_mm[1] + entity.radius_mm * math.sin(start),
                ),
            ),
            (
                SketchGeometryReference(entity.entity_id, "end"),
                (
                    entity.center_mm[0] + entity.radius_mm * math.cos(end),
                    entity.center_mm[1] + entity.radius_mm * math.sin(end),
                ),
            ),
        )

    def _inferred_constraints_for_entity(
        self, entity: SketchEntity
    ) -> tuple[SketchConstraint, ...]:
        if not self._auto_inference_enabled:
            return ()
        inferred: list[SketchConstraint] = []
        if isinstance(entity, LineEntity):
            inferred.extend(self._line_inferred_constraints(entity))
        previous_entities = tuple(
            candidate for candidate in self.entities if candidate.entity_id != entity.entity_id
        )
        existing_points = tuple(
            (reference, point)
            for candidate in previous_entities
            for reference, point in self._stable_point_references(candidate)
        )
        for new_reference, new_point in self._stable_point_references(entity):
            matches = tuple(
                reference
                for reference, point in existing_points
                if _distance(new_point, point) <= 1e-9
            )
            if len(matches) != 1:
                continue
            inferred.append(
                SketchConstraint(
                    uuid4().hex,
                    "coincident",
                    (new_reference, matches[0]),
                    source="inferred",
                )
            )
        return tuple(inferred)

    def _preserve_satisfied_relations(
        self,
        entities: tuple[SketchEntity, ...],
        *,
        original_entities: tuple[SketchEntity, ...] | None = None,
    ) -> int:
        previous_count = len(self.constraints)
        by_id = {entity.entity_id: entity for entity in entities}
        original_by_id = {
            entity.entity_id: entity
            for entity in (
                original_entities if original_entities is not None else tuple(self.entities)
            )
        }
        retained: list[SketchConstraint] = []
        for constraint in self.constraints:
            if constraint.source != "inferred":
                retained.append(constraint)
                continue
            retargeted_vertex = False
            for reference in constraint.references:
                if reference.kind != "vertex":
                    continue
                original_entity = original_by_id.get(reference.entity_id)
                updated_entity = by_id.get(reference.entity_id)
                if original_entity is None or updated_entity is None:
                    continue
                if isinstance(original_entity, PolylineEntity) != isinstance(
                    updated_entity, PolylineEntity
                ) or isinstance(original_entity, RectangleEntity) != isinstance(
                    updated_entity, RectangleEntity
                ):
                    retargeted_vertex = True
                    break
                if (
                    isinstance(original_entity, PolylineEntity)
                    and isinstance(updated_entity, PolylineEntity)
                    and (
                        len(original_entity.points_mm) != len(updated_entity.points_mm)
                        or original_entity.closed != updated_entity.closed
                    )
                ):
                    retargeted_vertex = True
                    break
            if retargeted_vertex:
                continue
            if constraint.kind in ("horizontal", "vertical"):
                entity = by_id.get(constraint.references[0].entity_id)
                if not isinstance(entity, LineEntity):
                    continue
                residual = (
                    abs(entity.start_mm[1] - entity.end_mm[1])
                    if constraint.kind == "horizontal"
                    else abs(entity.start_mm[0] - entity.end_mm[0])
                )
                satisfied = residual <= 1e-9
            elif constraint.kind == "coincident":
                first = self.point_for_reference(constraint.references[0], by_id)
                second = self.point_for_reference(constraint.references[1], by_id)
                satisfied = (
                    first is not None and second is not None and _distance(first, second) <= 1e-9
                )
            else:
                satisfied = False
            if satisfied:
                retained.append(constraint)
        self.constraints = retained
        return previous_count - len(retained)

    @staticmethod
    def point_for_reference(
        reference: SketchGeometryReference,
        entities: dict[str, SketchEntity],
    ) -> Point2D | None:
        entity = entities.get(reference.entity_id)
        if entity is None:
            return None
        if isinstance(entity, SplineEntity):
            if reference.kind == "start":
                return entity.control_points_mm[0]
            if reference.kind == "end":
                return entity.control_points_mm[-1]
            if (
                reference.kind == "vertex"
                and reference.index is not None
                and reference.index < len(entity.control_points_mm)
            ):
                return entity.control_points_mm[reference.index]
        if isinstance(entity, LineEntity):
            if reference.kind == "start":
                return entity.start_mm
            if reference.kind == "end":
                return entity.end_mm
        elif isinstance(entity, PolylineEntity):
            if reference.kind == "start":
                return entity.points_mm[0]
            if reference.kind == "end":
                return entity.points_mm[-1]
            if reference.kind == "vertex" and reference.index is not None:
                return (
                    entity.points_mm[reference.index]
                    if reference.index < len(entity.points_mm)
                    else None
                )
        elif isinstance(entity, RectangleEntity):
            first_u, first_v = entity.first_corner_mm
            opposite_u, opposite_v = entity.opposite_corner_mm
            corners = (
                (first_u, first_v),
                (opposite_u, first_v),
                (opposite_u, opposite_v),
                (first_u, opposite_v),
            )
            if reference.kind == "vertex" and reference.index is not None:
                return corners[reference.index] if reference.index < len(corners) else None
        elif isinstance(entity, CircleEntity) and reference.kind == "center":
            return entity.center_mm
        elif isinstance(entity, ArcEntity):
            if reference.kind == "center":
                return entity.center_mm
            if reference.kind in ("start", "end"):
                angle = entity.start_angle_deg + (
                    entity.sweep_angle_deg if reference.kind == "end" else 0.0
                )
                radians = math.radians(angle)
                return (
                    entity.center_mm[0] + entity.radius_mm * math.cos(radians),
                    entity.center_mm[1] + entity.radius_mm * math.sin(radians),
                )
        return None

    def _accept_point(
        self,
        raw_point: Point2D,
        *,
        operation_override: str | None = None,
        temporarily_disable_snapping: bool = False,
        exact_point: bool = False,
    ) -> None:
        if (
            self.tool in {"直线", "多段线", "圆", "圆弧", "矩形", "多边形", "样条曲线"}
            and not self._current_layer_can_draw()
        ):
            self.message = "当前图层隐藏或已锁定，无法创建图元。"
            self.changed.emit()
            return
        if self._transform_operation is not None:
            point = raw_point if exact_point else self._snapped(raw_point)[0]
            self._transform_point(point, commit=True)
            return
        active_tool = operation_override or self.tool
        if active_tool in {"修剪", "延伸", "分割"}:
            self._clear_line_edit_preview()
        point, snap_kind = (
            (raw_point, "")
            if exact_point or active_tool in {"修剪", "延伸", "分割"}
            else self._placement_point(
                raw_point, temporarily_disable_snapping=temporarily_disable_snapping
            )
        )
        if not exact_point and self._first is not None and self.dynamic_point_resolver is not None:
            try:
                resolved = self.dynamic_point_resolver(self._first, point)
                if resolved != point:
                    snap_kind = ""
                point = resolved
            except ValueError as exc:
                self.message = str(exc)
                self.changed.emit()
                return
        self._snap_kind = snap_kind
        self._cursor = point
        if active_tool in {"修剪", "延伸", "分割"}:
            operation = {
                "修剪": trim_curve_at,
                "延伸": extend_curve_at,
                "分割": split_entity_at,
            }[active_tool]
            target_id = (
                self._extend_target_at(point)
                if active_tool == "延伸"
                else self._trim_target_at(point, lines_only=active_tool == "分割")
            )
            self._hovered_line_edit_entity_id = target_id
            if target_id is None:
                self.message = (
                    "请点选唯一可延伸端点。"
                    if active_tool == "延伸"
                    else "请点选唯一可修剪曲线段。"
                    if active_tool == "修剪"
                    else "请点选唯一可分割直线、矩形边或多段线段。"
                )
                self.changed.emit()
                self.update()
                return
            target = next(
                (entity for entity in self.entities if entity.entity_id == target_id), None
            )
            if target is not None and self._layer(target).locked:
                self.message = "目标图元所在图层已锁定；草图未修改。"
                self.changed.emit()
                self.update()
                return
            try:
                visible_entities = self._visible_entities()
                updated_visible = operation(
                    visible_entities,
                    point,
                    hit_tolerance_mm=_SNAP_RADIUS_PX / self._scale,
                    target_entity_id=target_id,
                )
                updated = self._merge_hidden_entities(tuple(self.entities), updated_visible)
                self._reject_user_constraint_reference_edits(updated)
            except ValueError as exc:
                self.message = str(exc)
            else:
                if updated != tuple(self.entities):
                    self._record_undo()
                original_entities = tuple(self.entities)
                self.entities = list(updated)
                removed_relations = self._preserve_satisfied_relations(
                    updated, original_entities=original_entities
                )
                self._snap_candidates_cache = None
                available_ids = {entity.entity_id for entity in self.entities}
                self.selected_entity_ids.intersection_update(available_ids)
                self.message = (
                    "修剪完成；源图元身份保留在首个剩余曲线片段。"
                    if active_tool == "修剪"
                    else "已延伸目标曲线到最近交点；图元身份保持不变。"
                    if active_tool == "延伸"
                    else "已分割目标图元；第一段保留原身份，第二段取得新身份。"
                )
                if removed_relations:
                    self.message += f" 已移除 {removed_relations} 条失效或需重新确认的自动关系。"
            self._hovered_line_edit_entity_id = None
            self.changed.emit()
            self.update()
            return
        if self.tool == "多段线":
            if len(self._points) >= 3 and point == self._points[0]:
                self.finish_polyline(close=True)
                return
            if self._points and point == self._points[-1]:
                self.message = "相邻点不能重合；请指定下一个点。"
                self.changed.emit()
                return
            self._points.append(point)
            self.point_accepted.emit(point)
            self.message = f"多段线：已放置 {len(self._points)} 个点；按 Enter 或按钮完成。"
            self.changed.emit()
            self.update()
            return
        if self.tool == "样条曲线":
            if self._points and point == self._points[-1]:
                self.message = "请选择不同的下一个控制点。"
            else:
                self._points.append(point)
                self.point_accepted.emit(point)
                self.message = f"样条：已放置 {len(self._points)} 个控制点，至少四点；Enter / 右键完成，Esc 取消。"
            self.changed.emit()
            self.update()
            return
        if self._first is None:
            self._first = point
            self._points = [point]
            self.point_accepted.emit(point)
            self.message = self._next_point_hint()
            self.changed.emit()
            self.update()
            return
        try:
            entity = self._make_entity(self._first, point)
        except ValueError as exc:
            self.message = str(exc)
            self.changed.emit()
            return
        if entity is None and self.tool == "圆弧" and len(self._points) == 2:
            self.point_accepted.emit(point)
            self.changed.emit()
            self.update()
            return
        if entity is not None:
            if self.layer_table.get(entity.layer_name).locked:
                self.message = "目标图层已锁定；草图未修改。"
                self.changed.emit()
                self.update()
                return
            self._record_undo()
            self.entities.append(entity)
            self.point_accepted.emit(point)
            self.constraints.extend(self._inferred_constraints_for_entity(entity))
            self._snap_candidates_cache = None
        if self.tool == "直线" and self.continuous_lines and entity is not None:
            if len(self._points) >= 3 and point == self._points[0]:
                self.end_line_chain()
                self.message = "首尾已精确闭合；可指定新起点。"
            else:
                self._points.append(point)
                self._first = point
                self.message = "直线：指定下一点；Enter 结束，C 闭合，U 退回上一段，Esc 结束。"
        else:
            self._first = None
            self._points.clear()
            self.message = f"{self.tool}已加入草稿。可继续绘制或点击完成草图。"
        self.changed.emit()
        self.update()

    def _next_point_hint(self) -> str:
        if self.tool == "圆弧":
            return "圆弧：依次指定圆心、起点、终点。"
        if self.tool == "圆":
            return "圆：已指定圆心，再指定半径。"
        if self.tool == "多边形":
            return "正多边形：中心已指定；内接模式指定顶点，外切模式指定边中点。"
        return f"{self.tool}：再指定一个点。"

    def _polygon_points(self, center: Point2D, radius_point: Point2D) -> tuple[Point2D, ...]:
        radius = _distance(center, radius_point)
        if radius <= 1e-9:
            raise ValueError("正多边形半径必须大于零。")
        angle = math.atan2(radius_point[1] - center[1], radius_point[0] - center[0])
        step = math.tau / self.polygon_sides
        if self.polygon_circumscribed:
            radius /= math.cos(step / 2.0)
            angle += step / 2.0
        return tuple(
            (
                center[0] + radius * math.cos(angle + index * step),
                center[1] + radius * math.sin(angle + index * step),
            )
            for index in range(self.polygon_sides)
        )

    def _make_entity(self, first: Point2D, second: Point2D) -> SketchEntity | None:
        identity = uuid4().hex
        if self.tool == "直线":
            return LineEntity(identity, first, second, self.construction, self.active_layer_name)
        if self.tool == "多边形":
            return PolylineEntity(
                identity,
                self._polygon_points(first, second),
                True,
                self.construction,
                self.active_layer_name,
            )
        if self.tool == "矩形":
            return RectangleEntity(
                identity, first, second, self.construction, self.active_layer_name
            )
        if self.tool == "圆":
            return CircleEntity(
                identity,
                first,
                _distance(first, second),
                self.construction,
                self.active_layer_name,
            )
        if self.tool == "圆弧":
            if len(self._points) == 1:
                self._points.append(second)
                self.message = "圆弧：起点已指定，再指定终点。"
                self.changed.emit()
                self.update()
                return None
            center, start = self._points[0], self._points[1]
            radius = _distance(center, start)
            start_angle = math.degrees(math.atan2(start[1] - center[1], start[0] - center[0]))
            end_angle = math.degrees(math.atan2(second[1] - center[1], second[0] - center[0]))
            sweep = _arc_sweep(start_angle, end_angle, self.arc_direction)
            if abs(sweep) <= 1e-9:
                raise ValueError("圆弧终点必须与起点不同。")
            return ArcEntity(
                identity,
                center,
                radius,
                start_angle,
                sweep,
                self.construction,
                self.active_layer_name,
            )
        return None

    def _draw_entity(
        self,
        painter: QPainter,
        entity: SketchEntity,
        *,
        highlighted: bool = False,
        layer: SketchLayer | None = None,
    ) -> None:
        layer = self._layer(entity) if layer is None else layer
        if not layer.displayed:
            return
        color = (
            QColor(210, 45, 45)
            if entity.entity_id in self.dimension_error_entity_ids
            else QColor(0, 139, 139)
            if highlighted
            else QColor(128, 138, 145)
            if entity.construction
            else QColor(*layer.color_rgb)
        )
        line_styles = {
            "CONTINUOUS": Qt.PenStyle.SolidLine,
            "DASHED": Qt.PenStyle.DashLine,
            "DOTTED": Qt.PenStyle.DotLine,
            "DASHDOT": Qt.PenStyle.DashDotLine,
        }
        style = (
            Qt.PenStyle.SolidLine
            if highlighted
            else Qt.PenStyle.DashLine
            if entity.construction
            else line_styles[layer.linetype]
        )
        width = 3.0 if highlighted else 1.0 + min(2.0, layer.lineweight_mm * 2.0)
        painter.setPen(
            QPen(
                color,
                width,
                style,
            )
        )
        if isinstance(entity, PointEntity):
            point = self.local_to_screen(entity.position_mm)
            painter.drawLine(point.x() - 4, point.y(), point.x() + 4, point.y())
            painter.drawLine(point.x(), point.y() - 4, point.x(), point.y() + 4)
        elif isinstance(entity, SplineEntity):
            points = entity.sampled_points()
            for start, end in zip(points, points[1:], strict=False):
                painter.drawLine(self.local_to_screen(start), self.local_to_screen(end))
        elif isinstance(entity, LineEntity):
            painter.drawLine(
                self.local_to_screen(entity.start_mm), self.local_to_screen(entity.end_mm)
            )
        elif isinstance(entity, PolylineEntity):
            points = [self.local_to_screen(point) for point in entity.points_mm]
            for start, end in zip(points, points[1:], strict=False):
                painter.drawLine(start, end)
            if entity.closed:
                painter.drawLine(points[-1], points[0])
        elif isinstance(entity, RectangleEntity):
            first = self.local_to_screen(entity.first_corner_mm)
            opposite = self.local_to_screen(entity.opposite_corner_mm)
            painter.drawRect(QRectF(QPointF(first), QPointF(opposite)).normalized())
        else:
            center = self.local_to_screen(entity.center_mm)
            radius_px = entity.radius_mm * self._scale
            bounds = QRectF(
                center.x() - radius_px, center.y() - radius_px, radius_px * 2, radius_px * 2
            )
            if isinstance(entity, CircleEntity):
                painter.drawEllipse(bounds)
            else:
                painter.drawArc(
                    bounds,
                    round(entity.start_angle_deg * 16),
                    round(entity.sweep_angle_deg * 16),
                )

    def _draw_preview(self, painter: QPainter) -> None:
        if self._cursor is None:
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(Qt.GlobalColor.darkCyan, 1.5, Qt.PenStyle.DashLine))
        cursor = self.local_to_screen(self._cursor)
        if self.tool == "多边形" and self._first is not None:
            try:
                points = self._polygon_points(self._first, self._cursor)
            except ValueError:
                points = ()
            if points:
                for start, end in zip(points, (*points[1:], points[0]), strict=True):
                    painter.drawLine(self.local_to_screen(start), self.local_to_screen(end))
                painter.drawLine(self.local_to_screen(self._first), cursor)
        if self.tool == "样条曲线" and self._points:
            control_points = (*self._points, self._cursor)
            for start, end in zip(control_points, control_points[1:], strict=False):
                painter.drawLine(self.local_to_screen(start), self.local_to_screen(end))
            if len(control_points) >= 4:
                try:
                    preview = SplineEntity("00000000000000000000000000000000", control_points)
                    self._draw_entity(painter, preview, highlighted=True)
                except ValueError:
                    pass
        if self.tool in ("直线", "矩形", "圆", "圆弧") and self._first is not None:
            first = self.local_to_screen(self._first)
            if self.tool == "直线":
                painter.drawLine(first, cursor)
            elif self.tool == "矩形":
                painter.drawRect(QRectF(QPointF(first), QPointF(cursor)).normalized())
            elif self.tool == "圆":
                radius = math.hypot(cursor.x() - first.x(), cursor.y() - first.y())
                painter.drawEllipse(QPointF(first), radius, radius)
            elif self.tool == "圆弧" and len(self._points) > 1:
                center = self.local_to_screen(self._points[0])
                start = self.local_to_screen(self._points[1])
                radius = math.hypot(start.x() - center.x(), start.y() - center.y())
                start_angle = math.degrees(
                    math.atan2(center.y() - start.y(), start.x() - center.x())
                )
                end_angle = math.degrees(
                    math.atan2(center.y() - cursor.y(), cursor.x() - center.x())
                )
                sweep = _arc_sweep(start_angle, end_angle, self.arc_direction)
                painter.drawArc(
                    QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
                    round(start_angle * 16),
                    round(sweep * 16),
                )
        elif self.tool == "多段线" and self._points:
            points = [self.local_to_screen(point) for point in (*self._points, self._cursor)]
            for start, end in zip(points, points[1:], strict=False):
                painter.drawLine(start, end)
        if self._snap_kind:
            painter.setPen(QPen(Qt.GlobalColor.red, 1.5))
            painter.drawEllipse(cursor, 5.0, 5.0)

    def constraint_anchor(
        self,
        constraint: SketchConstraint,
        entities: dict[str, SketchEntity],
    ) -> Point2D | None:
        if constraint.position_mm is not None:
            return constraint.position_mm
        reference = constraint.references[0]
        if constraint.kind == "coincident":
            first = self.point_for_reference(reference, entities)
            second = self.point_for_reference(constraint.references[1], entities)
            if first is not None and second is not None:
                return ((first[0] + second[0]) / 2.0, (first[1] + second[1]) / 2.0)
        if constraint.kind == "distance":
            first = self.point_for_reference(reference, entities)
            second = self.point_for_reference(constraint.references[1], entities)
            if first is not None and second is not None:
                return ((first[0] + second[0]) / 2.0, (first[1] + second[1]) / 2.0)
        if constraint.kind in ("length", "angle"):
            segment = self.line_for_reference(reference, entities)
            if segment is not None:
                return (
                    (segment[0][0] + segment[1][0]) / 2.0,
                    (segment[0][1] + segment[1][1]) / 2.0,
                )
        entity = entities.get(reference.entity_id)
        if isinstance(entity, CircleEntity | ArcEntity) and (
            constraint.kind in ("radius", "diameter", "arc_length", "concentric")
            or reference.kind == "center"
        ):
            return entity.center_mm
        point = self.point_for_reference(reference, entities)
        if point is not None:
            return point
        segment = self.line_for_reference(reference, entities)
        if segment is not None:
            return (
                (segment[0][0] + segment[1][0]) / 2.0,
                (segment[0][1] + segment[1][1]) / 2.0,
            )
        if isinstance(entity, LineEntity):
            return (
                (entity.start_mm[0] + entity.end_mm[0]) / 2.0,
                (entity.start_mm[1] + entity.end_mm[1]) / 2.0,
            )
        if isinstance(entity, RectangleEntity):
            return (
                (entity.first_corner_mm[0] + entity.opposite_corner_mm[0]) / 2.0,
                (entity.first_corner_mm[1] + entity.opposite_corner_mm[1]) / 2.0,
            )
        return None

    @staticmethod
    def line_for_reference(
        reference: SketchGeometryReference,
        entities: dict[str, SketchEntity],
    ) -> tuple[Point2D, Point2D] | None:
        entity = entities.get(reference.entity_id)
        if isinstance(entity, LineEntity) and reference.kind == "geometry":
            return (entity.start_mm, entity.end_mm)
        if isinstance(entity, PolylineEntity) and reference.kind == "segment":
            index = reference.index
            segment_count = len(entity.points_mm) if entity.closed else len(entity.points_mm) - 1
            if index is not None and 0 <= index < segment_count:
                return (
                    entity.points_mm[index],
                    entity.points_mm[(index + 1) % len(entity.points_mm)],
                )
        if isinstance(entity, RectangleEntity) and reference.kind == "segment":
            index = reference.index
            x1, y1 = entity.first_corner_mm
            x2, y2 = entity.opposite_corner_mm
            corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
            if index is not None and 0 <= index < len(corners):
                return (corners[index], corners[(index + 1) % len(corners)])
        return None

    def dimension_layout(
        self, constraint: SketchConstraint, entities: dict[str, SketchEntity]
    ) -> DimensionLayout | None:
        """Screen-space annotation only; geometry and values come from the solver."""
        if (
            constraint.position_mm is not None
            or constraint.axis != "aligned"
            or constraint.kind == "arc_length"
        ):
            from mycad.ui.dimension_layout import placed_dimension_layout

            return placed_dimension_layout(self, constraint, entities)
        reference = constraint.references[0]
        offset = 26.0 * constraint.scale
        if constraint.kind in {"length", "distance"}:
            if constraint.kind == "length":
                segment = self.line_for_reference(reference, entities)
            else:
                first = self.point_for_reference(reference, entities)
                second = self.point_for_reference(constraint.references[1], entities)
                segment = (first, second) if first is not None and second is not None else None
            if segment is None:
                return None
            a, b = (QPointF(self.local_to_screen(point)) for point in segment)
            delta = b - a
            length = math.hypot(delta.x(), delta.y())
            if length < 1e-9:
                return None
            normal = QPointF(delta.y(), -delta.x()) / length
            p, q = a + normal * offset, b + normal * offset
            return DimensionLayout(
                ((a, p + normal * 5), (b, q + normal * 5), (p, q)), ((p, q), (q, p)), (p + q) / 2
            )
        if constraint.kind in {"radius", "diameter"}:
            entity = entities.get(reference.entity_id)
            if not isinstance(entity, CircleEntity | ArcEntity):
                return None
            angle = (
                math.radians(entity.start_angle_deg + entity.sweep_angle_deg / 2)
                if isinstance(entity, ArcEntity)
                else math.pi / 4
            )
            center = QPointF(self.local_to_screen(entity.center_mm))
            direction = QPointF(math.cos(angle), -math.sin(angle))
            reach = entity.radius_mm * self._scale
            rim = center + direction * reach
            label = rim + direction * offset
            opposite = center - direction * reach if constraint.kind == "diameter" else center
            arrows = (
                ((rim, opposite), (opposite, rim))
                if constraint.kind == "diameter"
                else ((rim, center),)
            )
            return DimensionLayout(((opposite, label),), arrows, label)
        if constraint.kind == "angle" and constraint.value is not None:
            first_line = self.line_for_reference(reference, entities)
            second_line = self.line_for_reference(constraint.references[1], entities)
            if first_line is None or second_line is None:
                return None
            a, b = (QPointF(self.local_to_screen(point)) for point in first_line)
            c, d = (QPointF(self.local_to_screen(point)) for point in second_line)
            u, v = b - a, d - c
            cross = u.x() * v.y() - u.y() * v.x()
            if abs(cross) < 1e-9:
                return None
            delta = c - a
            center = a + u * ((delta.x() * v.y() - delta.y() * v.x()) / cross)
            start = math.atan2(u.y(), u.x())
            sweep = -math.radians(constraint.value)
            radius = max(32.0, offset * 1.5)
            points = tuple(
                center
                + QPointF(math.cos(start + sweep * i / 32), math.sin(start + sweep * i / 32))
                * radius
                for i in range(33)
            )
            lines = (
                *tuple(zip(points, points[1:], strict=False)),
                (center, points[0]),
                (center, points[-1]),
            )
            return DimensionLayout(
                lines,
                ((points[0], points[1]), (points[-1], points[-2])),
                center
                + QPointF(math.cos(start + sweep / 2), math.sin(start + sweep / 2)) * (radius + 10),
            )
        return None

    @staticmethod
    def _draw_dimension_lines(painter: QPainter, layout: DimensionLayout) -> None:
        for start, end in layout.lines:
            painter.drawLine(start, end)
        for tip, toward in layout.arrows:
            delta = toward - tip
            length = math.hypot(delta.x(), delta.y())
            if length < 1e-9:
                continue
            along = delta / length
            side = QPointF(-along.y(), along.x())
            painter.drawLine(tip, tip + along * 7 + side * 3)
            painter.drawLine(tip, tip + along * 7 - side * 3)

    def _draw_constraint_overlays(self, painter: QPainter) -> None:
        painter.save()
        entities = self.dimension_entities()
        glyphs = {
            "coincident": "◎",
            "horizontal": "H",
            "vertical": "V",
            "parallel": "∥",
            "perpendicular": "⊥",
            "tangent": "T",
            "concentric": "◎",
            "equal": "=",
            "fixed": "◆",
        }
        stacked: dict[tuple[int, int], int] = {}
        label_font = QFont(painter.font())
        label_font.setPointSize(8)
        painter.setFont(label_font)
        candidate = self.dimension_candidate
        dimensions = tuple(
            c
            for c in self.dimension_constraints()
            if candidate is None or c.constraint_id != candidate.constraint_id
        )
        for constraint in (*dimensions, *((candidate,) if candidate is not None else ())):
            layer = self.annotation_layer(constraint)
            if not layer.displayed:
                continue
            label_color = (
                QColor(210, 45, 45)
                if constraint.constraint_id in self.dimension_error_constraint_ids
                else QColor(0, 145, 180)
                if constraint.constraint_id in self.selected_constraint_ids
                else QColor(*layer.color_rgb)
            )
            dimension_pen = QPen(
                label_color,
                max(
                    2.5 if constraint.constraint_id in self.selected_constraint_ids else 1.0,
                    layer.lineweight_mm * 4,
                ),
            )
            dimension_pen.setStyle(
                {
                    "CONTINUOUS": Qt.PenStyle.SolidLine,
                    "DASHED": Qt.PenStyle.DashLine,
                    "DOTTED": Qt.PenStyle.DotLine,
                    "DASHDOT": Qt.PenStyle.DashDotLine,
                }[layer.linetype]
            )
            if any(reference.entity_id not in entities for reference in constraint.references):
                continue
            anchor = self.constraint_anchor(constraint, entities)
            if anchor is None:
                continue
            if constraint.kind in DIMENSION_KINDS:
                if constraint.value is None:
                    continue
                value = f"{constraint.value:.{constraint.precision}f}"
                if constraint.kind == "angle":
                    label = f"{value}°"
                elif constraint.kind == "arc_length":
                    label = f"⌒{value} mm"
                elif constraint.kind == "radius":
                    label = f"R{value} mm"
                elif constraint.kind == "diameter":
                    label = f"⌀{value} mm"
                else:
                    label = f"{value} mm"
            else:
                label = glyphs.get(constraint.kind, "?")
            screen = QPointF(self.local_to_screen(anchor))
            layout = self.dimension_layout(constraint, entities)
            if layout is not None:
                painter.setPen(dimension_pen)
                self._draw_dimension_lines(painter, layout)
                screen = layout.label
                if not constraint.driving:
                    label = f"({label})"
            key = (round(screen.x() / 24.0), round(screen.y() / 18.0))
            stack = stacked.get(key, 0)
            stacked[key] = stack + 1
            width = max(24, painter.fontMetrics().horizontalAdvance(label) + 10)
            x = screen.x() - width / 2 if layout is not None else screen.x() + 7.0
            rect = QRectF(x, screen.y() - 10.0 + stack * 18.0, width, 18.0)
            painter.setPen(QPen(label_color, 1.0))
            if constraint.kind in DIMENSION_KINDS:
                painter.fillRect(rect, QColor(255, 255, 255, 235))
            else:
                painter.setBrush(QColor(240, 253, 250, 235))
                painter.drawRoundedRect(rect, 3.0, 3.0)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    @override
    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        origin = self.local_to_screen((0.0, 0.0))
        if self.grid_visible:
            painter.setPen(
                QPen(QColor(170, 180, 190), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            )
            grid_mm = self.grid_spacing_mm()
            left, top = self.screen_to_local(QPointF(0.0, 0.0))
            right, bottom = self.screen_to_local(QPointF(self.width(), self.height()))
            for column in range(math.ceil(left / grid_mm), math.floor(right / grid_mm) + 1):
                for row in range(math.ceil(bottom / grid_mm), math.floor(top / grid_mm) + 1):
                    painter.drawPoint(self.local_to_screen((column * grid_mm, row * grid_mm)))
        painter.setPen(QPen(Qt.GlobalColor.gray, 1.4))
        painter.drawLine(0, origin.y(), self.width(), origin.y())
        painter.drawLine(origin.x(), 0, origin.x(), self.height())
        for entity, layer in self.background_entities:
            self._draw_entity(
                painter,
                entity,
                layer=layer,
                highlighted=self.select_committed_entities
                and (
                    entity.entity_id in self.selected_entity_ids
                    or entity.entity_id == self._hovered_entity_id
                ),
            )
        for entity in self.entities:
            if (
                self._line_edit_preview_original is not None
                and entity.entity_id == self._line_edit_preview_original.entity_id
            ):
                continue
            painter.save()
            if (
                self._transform_operation is not None
                and not self._transform_copies_source()
                and self._transform_preview
                and entity.entity_id in self.selected_entity_ids
            ):
                painter.setOpacity(0.25)
            self._draw_entity(
                painter,
                entity,
                highlighted=entity.entity_id in self.selected_entity_ids
                or entity.entity_id == self._hovered_entity_id,
            )
            painter.restore()
            if entity.entity_id in self.selected_entity_ids:
                painter.setPen(QPen(QColor(0, 100, 110), 1.0))
                painter.setBrush(QColor(225, 250, 250))
                for _reference, handle in self._entity_handles(entity):
                    screen = self.local_to_screen(handle)
                    painter.drawRect(QRectF(screen.x() - 4.0, screen.y() - 4.0, 8.0, 8.0))
        for preview_entity in self._transform_preview:
            self._draw_entity(painter, preview_entity, highlighted=True)
        if self._transform_base is not None:
            painter.setPen(QPen(QColor(0, 120, 140), 1.2, Qt.PenStyle.DashLine))
            base_screen = self.local_to_screen(self._transform_base)
            painter.drawEllipse(base_screen, 4, 4)
            if self._cursor is not None:
                painter.drawLine(base_screen, self.local_to_screen(self._cursor))
            if self._transform_reference is not None:
                painter.drawLine(base_screen, self.local_to_screen(self._transform_reference))
        if self._line_edit_preview_original is not None and self._line_edit_preview_result:
            painter.save()
            painter.setOpacity(0.28)
            self._draw_entity(painter, self._line_edit_preview_original)
            painter.restore()
            for entity in self._line_edit_preview_result:
                self._draw_entity(painter, entity, highlighted=True)
        elif (
            self.tool in {"修剪", "延伸", "分割"} and self._hovered_line_edit_entity_id is not None
        ):
            hovered = next(
                (
                    entity
                    for entity in self.entities
                    if entity.entity_id == self._hovered_line_edit_entity_id
                ),
                None,
            )
            if hovered is not None:
                self._draw_entity(painter, hovered, highlighted=True)
        if self.dimension_references:
            entities = {e.entity_id: e for e in self.visible_snap_entities()}
            painter.save()
            painter.setPen(QPen(QColor(0, 145, 180), 2.0))
            for reference in self.dimension_references:
                point = self.point_for_reference(reference, entities)
                if point is not None:
                    screen = self.local_to_screen(point)
                    painter.drawRect(QRectF(screen.x() - 4, screen.y() - 4, 8, 8))
                else:
                    segment = self.line_for_reference(reference, entities)
                    if segment is not None:
                        painter.drawLine(
                            self.local_to_screen(segment[0]), self.local_to_screen(segment[1])
                        )
            painter.restore()
        self._draw_constraint_overlays(painter)
        if self.dimension_preview is not None:
            painter.save()
            painter.setOpacity(0.65)
            for entity in self.dimension_preview.entities:
                self._draw_entity(
                    painter,
                    entity,
                    layer=self.dimension_preview.layers.get(entity.layer_name),
                    highlighted=True,
                )
            painter.restore()
        self._draw_preview(painter)
        self._draw_ucs(painter)
        if self._selection_anchor is not None:
            crossing = self._selection_corner.x() < self._selection_anchor.x()
            color = QColor(35, 155, 75) if crossing else QColor(45, 105, 210)
            painter.setPen(
                QPen(color, 1.0, Qt.PenStyle.DashLine if crossing else Qt.PenStyle.SolidLine)
            )
            color.setAlpha(35)
            painter.setBrush(color)
            painter.drawRect(QRectF(self._selection_anchor, self._selection_corner).normalized())
        painter.end()

    def _draw_ucs(self, painter: QPainter) -> None:
        origin = self.local_to_screen((0.0, 0.0))
        at_origin = 30 <= origin.x() <= self.width() - 85 and 85 <= origin.y() <= self.height() - 30
        base = origin if at_origin else QPoint(35, self.height() - 35)
        labels = {"XY": ("X", "Y"), "XZ": ("X", "−Z"), "YZ": ("Y", "Z")}.get(
            self.ucs_plane, ("U", "V")
        )
        painter.save()
        painter.setBrush(QColor(255, 255, 255, 220))
        painter.setPen(Qt.PenStyle.NoPen)
        if not at_origin:
            painter.drawRoundedRect(QRectF(base.x() - 10, base.y() - 80, 110, 103), 4, 4)
        colors = {"X": "#b42f35", "Y": "#247443", "Z": "#2865bd", "U": "#b42f35", "V": "#247443"}
        for end, label in ((base + QPoint(55, 0), labels[0]), (base + QPoint(0, -55), labels[1])):
            painter.setPen(QPen(QColor(colors[label.removeprefix("−")]), 2.0))
            painter.drawLine(base, end)
            arrow = (
                (QPoint(-7, -4), QPoint(-7, 4))
                if end.y() == base.y()
                else (QPoint(-4, 7), QPoint(4, 7))
            )
            for delta in arrow:
                painter.drawLine(end, end + delta)
            painter.drawText(end + QPoint(5, -6), label)
        painter.setPen(QPen(QColor("#334155"), 1.0))
        painter.drawRect(base.x() - 3, base.y() - 3, 6, 6)
        painter.drawText(base + QPoint(8, 17), "O · UCS" if at_origin else "UCS · 原点屏外")
        painter.restore()

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.dynamic_click_guard is not None
            and not self.dynamic_click_guard()
        ):
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.selected_constraint_ids:
            self.selected_constraint_ids.clear()
            self.changed.emit()
            self.update()
        if self._selection_anchor is not None:
            if event.button() == Qt.MouseButton.LeftButton:
                self._finish_selection_box(event.position())
                event.accept()
                return
            if event.button() == Qt.MouseButton.RightButton:
                self._cancel_selection_box()
                event.accept()
                return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._cancel_selection_box()
        if self._transform_operation is not None and event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
        ):
            if event.button() == Qt.MouseButton.RightButton:
                self._confirm_transform_default()
            else:
                raw = self.screen_to_local(event.position())
                if self._transform_selecting and self._hit_entity_at(raw) is None:
                    self._begin_selection_box(event)
                    event.accept()
                    return
                if (
                    self._transform_selecting
                    and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                ):
                    self._select_at(raw, additive=True, subtractive=True)
                    event.accept()
                    return
                point, _kind = self._transform_pointer_point(
                    raw,
                    disable_snapping=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                )
                self._transform_point(point, commit=True)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton and self.tool in {
            "直线",
            "多段线",
            "样条曲线",
        }:
            self.keyPressEvent(
                QKeyEvent(
                    QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
                )
            )
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._last_mouse = event.position().toPoint()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            point = self.screen_to_local(event.position())
            if self.tool == "二维圆角":
                self._circle_fillet_pick(point)
                event.accept()
                return
            if self.tool == "修剪":
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self._cursor = point
                    self._accept_point(point, operation_override="延伸")
                    event.accept()
                    return
                self._begin_trim_drag(point)
                self._cursor = point
                self.changed.emit()
                self.update()
                event.accept()
                return
            if self.tool == "选择元素":
                if not event.modifiers() & (
                    Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                ):
                    handle = self._control_point_at(point)
                    if handle is not None:
                        self._begin_handle_drag(handle[0], handle[1], handle[2])
                        event.accept()
                        return
                if self._hit_entity_at(point) is None:
                    self._begin_selection_box(event)
                    event.accept()
                    return
                self._select_at(
                    point,
                    additive=bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier),
                    subtractive=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                )
            else:
                self._accept_point(
                    point,
                    temporarily_disable_snapping=bool(
                        event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                    )
                    and self.tool in {"直线", "多段线", "圆", "圆弧", "矩形", "多边形", "样条曲线"},
                )
                self.pointer_moved.emit(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        position = event.position().toPoint()
        if self._selection_anchor is not None:
            self._selection_corner = event.position()
            self._cursor = self.screen_to_local(event.position())
            self._snap_kind = ""
            mode = (
                "交叉选择（包含或相交）"
                if position.x() < self._selection_anchor.x()
                else "窗口选择（完全包含）"
            )
            self.message = f"{mode} · 指定对角点，Esc 取消。"
            self.cursor_changed.emit(*self._cursor, "")
            self.changed.emit()
            self.update()
            event.accept()
            return
        if self._panning:
            delta = position - self._last_mouse
            self._pan += QPointF(delta)
            self._last_mouse = position
        if (
            self._drag_reference is not None
            and self._drag_original_entities is not None
            and self._drag_original_constraints is not None
            and self._drag_last_entities is not None
            and self._drag_last_constraints is not None
            and self._drag_entity_id is not None
        ):
            self.entities = list(self._drag_original_entities)
            self.constraints = list(self._drag_original_constraints)
            self._snap_candidates_cache = None
            target, snap_kind = self._drag_target(self.screen_to_local(event.position()))
            updated = self._solve_handle_drag(
                self._drag_original_entities,
                self._drag_original_constraints,
                self._drag_reference,
                target,
            )
            if updated is not None:
                self._drag_last_entities, self._drag_last_constraints = updated
                self.entities = list(self._drag_last_entities)
                self.constraints = list(self._drag_last_constraints)
                self.message = (
                    f"拖动预览中 · {len(self.constraints)} 条关系已保留"
                    if self.constraints
                    else "拖动预览中 · 松开鼠标确认草稿变化"
                )
                if self._drag_branch_warning:
                    self.message += f" · 分支变化：{self._drag_branch_warning}"
            else:
                self.entities = list(self._drag_last_entities)
                self.constraints = list(self._drag_last_constraints)
                if not self.message or self.message.startswith("拖动预览中"):
                    self.message = (
                        "已有草图约束；当前拖动位置无法满足约束。"
                        if self._drag_original_constraints
                        else "当前控制点无法移动到该位置。"
                    )
            self._cursor = target
            self._snap_kind = snap_kind
            self.cursor_changed.emit(*target, snap_kind)
            self.changed.emit()
            self.update()
            event.accept()
            return
        if self._transform_operation is not None:
            raw = self.screen_to_local(event.position())
            point, kind = self._transform_pointer_point(
                raw, disable_snapping=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            )
            self._cursor, self._snap_kind = point, kind
            self._transform_point(point, commit=False)
            self.cursor_changed.emit(*point, kind)
            self.update()
            event.accept()
            return
        if self._trim_drag_start is not None:
            self._update_trim_drag(self.screen_to_local(event.position()))
            self._cursor = self.screen_to_local(event.position())
            self._hovered_line_edit_entity_id = self._trim_target_at(self._cursor)
            self._refresh_line_edit_preview(None)
            self.cursor_changed.emit(*self._cursor, "")
            self.update()
            event.accept()
            return
        raw_point = self.screen_to_local(event.position())
        self._last_placement_raw = raw_point
        self._cursor, self._snap_kind = (
            (raw_point, "")
            if self.tool in {"修剪", "延伸", "分割"}
            else self._placement_point(
                raw_point,
                temporarily_disable_snapping=bool(
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                )
                and self.tool in {"直线", "多段线", "圆", "圆弧", "矩形", "多边形", "样条曲线"},
            )
        )
        if self._first is not None and self.dynamic_point_resolver is not None:
            try:
                resolved = self.dynamic_point_resolver(self._first, self._cursor)
                if resolved != self._cursor:
                    self._snap_kind = ""
                self._cursor = resolved
            except ValueError as exc:
                self.message = str(exc)
                self.changed.emit()
        if self.tool == "选择元素":
            self._hovered_entity_id = self._hit_entity_at(self._cursor)
        elif self.tool == "修剪":
            temporary_extend = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._hovered_line_edit_entity_id = (
                self._extend_target_at(self._cursor)
                if temporary_extend
                else self._trim_target_at(self._cursor)
            )
            self._refresh_line_edit_preview("延伸" if temporary_extend else "修剪")
        elif self.tool == "延伸":
            self._hovered_line_edit_entity_id = self._extend_target_at(self._cursor)
            self._refresh_line_edit_preview("延伸")
        elif self.tool == "分割":
            self._hovered_line_edit_entity_id = self._trim_target_at(self._cursor, lines_only=True)
            self._refresh_line_edit_preview(None)
        else:
            self._hovered_line_edit_entity_id = None
            self._refresh_line_edit_preview(None)
            self._hovered_entity_id = None
        self.cursor_changed.emit(*self._cursor, self._snap_kind)
        self.pointer_moved.emit(position)
        self.update()
        event.accept()

    @override
    def leaveEvent(self, event: QEvent) -> None:
        self.pointer_left.emit()
        super().leaveEvent(event)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._selection_anchor is not None:
            delta = event.position() - self._selection_anchor
            if not self._selection_waiting_click and math.hypot(delta.x(), delta.y()) > 4.0:
                self._finish_selection_box(event.position())
            else:
                self._selection_waiting_click = True
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._transform_operation in {"move", "copy"}
            and self._transform_base is not None
            and self._transform_preview
        ):
            raw = self.screen_to_local(event.position())
            point, _kind = self._transform_pointer_point(
                raw, disable_snapping=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            )
            if _distance(point, self._transform_base) * self._scale > 3.0:
                self._transform_point(point, commit=True)
                event.accept()
                return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._finish_trim_drag():
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_reference is not None:
            self._finish_handle_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        self._cancel_selection_box()
        before = self.screen_to_local(event.position())
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self._scale = min(60.0, max(1e-6, self._scale * factor))
        after = self.local_to_screen(before)
        self._pan += event.position() - QPointF(after)
        self.update()
        event.accept()

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.dynamic_key_handler is not None and self.dynamic_key_handler(event):
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._cancel_circle_fillet():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete:
            self.delete_selected()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._cancel_selection_box():
            event.accept()
            return
        if (
            self._selection_anchor is not None
            and self._transform_operation is None
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            self._finish_selection_box(self._selection_corner)
            event.accept()
            return
        if self._transform_operation is not None:
            if event.key() == Qt.Key.Key_Escape:
                self.cancel_transform()
                event.accept()
                return
            if self._transform_operation == "copy" and event.key() == Qt.Key.Key_U:
                self.undo_copy_placement()
                event.accept()
                return
            if self._transform_operation == "rotate" and self._transform_base is not None:
                if event.key() == Qt.Key.Key_Backspace:
                    self._transform_angle_text = self._transform_angle_text[:-1]
                elif event.text() and all(char in "0123456789+-." for char in event.text()):
                    self._transform_angle_text += event.text()
                elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                    if self._transform_angle_text:
                        try:
                            angle = float(self._transform_angle_text)
                        except ValueError:
                            self.message = "请输入有效旋转角度；Backspace 修改，Esc 取消。"
                            self.changed.emit()
                        else:
                            self.apply_rotation_angle(angle)
                    event.accept()
                    return
                else:
                    super().keyPressEvent(event)
                    return
                self.message = f"旋转角度：{self._transform_angle_text}°；Enter 确认。"
                self.changed.emit()
                event.accept()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                self._confirm_transform_default()
                event.accept()
                return
        if event.matches(QKeySequence.StandardKey.Undo):
            if self.preserve_document_layers:
                self.undo_requested.emit()
            else:
                self.undo_last_operation()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            if self.preserve_document_layers:
                self.redo_requested.emit()
            else:
                self.redo_last_operation()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Shift and self.tool == "修剪" and self._cursor is not None:
            self._hovered_line_edit_entity_id = self._extend_target_at(self._cursor)
            self._refresh_line_edit_preview("延伸")
            self.update()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._cancel_trim_drag():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._cancel_handle_drag():
            event.accept()
            return
        if self.tool in {"直线", "多段线"} and event.key() == Qt.Key.Key_C:
            self.close_chain()
            event.accept()
            return
        if self.tool == "直线" and self.continuous_lines and self._points:
            if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape):
                self.end_line_chain()
                event.accept()
                return
            if event.key() == Qt.Key.Key_U:
                self.undo_last_operation()
                event.accept()
                return
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return) and self.tool in {
            "多段线",
            "样条曲线",
        }:
            self.finish_polyline()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.has_pending_geometry:
            self._first = None
            self._points.clear()
            self._snap_kind = ""
            self.message = "已清除未完成图元；草图草稿仍保留。"
            self.changed.emit()
            self.update()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and (
            self.selected_entity_ids or self.selected_constraint_ids
        ):
            self.selected_entity_ids.clear()
            self.selected_constraint_ids.clear()
            self.message = "已清除选择。"
            self.changed.emit()
            self.update()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.continuous_lines:
            self.set_tool("选择元素")
            event.accept()
            return
        super().keyPressEvent(event)

    @override
    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Shift and self.tool == "修剪" and self._cursor is not None:
            self._hovered_line_edit_entity_id = self._trim_target_at(self._cursor)
            self._refresh_line_edit_preview("修剪")
            self.update()
            event.accept()
            return
        super().keyReleaseEvent(event)


class SketchEditorDialog(QDialog):
    """Non-modal drawing window; Finish returns data and Cancel leaves Bus untouched."""

    view_3d_requested = Signal()
    layer_change_requested = Signal(object)
    document_undo_requested = Signal()
    document_redo_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        constraint_preview: Callable[[Sketch, SketchConstraint], SketchConstraintSolveResult]
        | None = None,
        constraint_update_preview: Callable[[Sketch, SketchConstraint], SketchConstraintSolveResult]
        | None = None,
        can_finish: Callable[[], bool] | None = None,
        drag_preview: Callable[
            [Sketch, SketchGeometryReference, Point2D], SketchConstraintSolveResult
        ]
        | None = None,
        attached_frame: WorkPlaneFrame | None = None,
        support_face: SketchSupportFace | None = None,
        continuous_lines: bool = False,
        select_committed_entities: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("草图")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(1080, 720)
        self.result_sketch: Sketch | None = None
        self._constraint_preview = constraint_preview
        self._constraint_update_preview = constraint_update_preview
        self._can_finish = can_finish
        self._drag_preview = drag_preview
        self._drag_preview_sketch_id = uuid4().hex
        self._selected_plane = "所选面" if support_face is not None else "XY"
        self._attached_frame = attached_frame
        self._support_face = support_face
        self._initial_support_face = support_face
        self._context_sketches: tuple[Sketch, ...] = ()
        self._context_frame: WorkPlaneFrame | None = None
        self.layer_table = SketchLayerTable().add(DEFAULT_DIM_LAYER)
        self.dimension_layer = "DIM"
        self.document_layer_mode = False
        self.layer_history_boundaries: dict[int, int] = {}
        self.layer_history_redo: list[tuple[int, int]] = []
        self.active_layer_manager: DrawingLayerPanel | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.toolbar_host = QMainWindow(self)
        self.toolbar_host.setWindowFlags(Qt.WindowType.Widget)
        outer.addWidget(self.toolbar_host)
        central = QWidget()
        self.toolbar_host.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        self._suspended_toolbar_state: QByteArray | None = None
        self.drawing_toolbar = self._make_toolbar("绘图", "draftingDrawingToolbar")
        self.modify_toolbar = self._make_toolbar("修改", "draftingModifyToolbar")
        self.dimension_toolbar = self._make_toolbar("尺寸标注", "draftingDimensionToolbar")
        self.reset_toolbar_layout()
        layer_bar = QHBoxLayout()
        root.addLayout(layer_bar)
        body = QHBoxLayout()
        root.addLayout(body, 1)
        self.tool_panel = QScrollArea()
        self.tool_panel.setWidgetResizable(True)
        self.tool_panel.setMinimumWidth(250)
        self.tool_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(4, 4, 4, 4)
        panel.setStyleSheet(
            "QToolButton:checked { background: #dceafa; border: 1px solid #2472ba; }"
        )
        self.tool_panel.setWidget(panel)
        self.parameter_tabs = QTabWidget()
        self.parameter_dock = QDockWidget("二维功能", self.toolbar_host)
        self.parameter_dock.setObjectName("draftingParameterDock")
        self.parameter_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.parameter_dock.setWidget(self.parameter_tabs)
        self.toolbar_host.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.parameter_dock)
        self.toolbar_host.resizeDocks([self.parameter_dock], [270], Qt.Orientation.Horizontal)
        self.navigator = SketchNavigator()
        self.navigator.selection_requested.connect(self._select_navigation)
        self.navigator.constraint_activated.connect(self._activate_navigation_constraint)
        drawing = QVBoxLayout()
        body.addLayout(drawing, 1)
        controls = QGridLayout()
        self.plane_combo = QComboBox()
        self.plane_combo.addItems(("XY", "XZ", "YZ"))
        if support_face is not None and attached_frame is not None:
            self.plane_combo.addItem("所选面")
            self.plane_combo.setCurrentText("所选面")
        self.tool_combo = QComboBox()
        self.tool_combo.addItems(
            (
                "直线",
                "选择元素",
                "多段线",
                "圆",
                "圆弧",
                "矩形",
                "多边形",
                "样条曲线",
                "修剪",
                "延伸",
                "分割",
            )
        )
        if select_committed_entities:
            self.tool_combo.addItem("二维圆角")
        self.snap_check = QCheckBox("捕捉")
        self.snap_check.setChecked(True)
        self.snap_check.setToolTip(
            "吸附到 UCS 原点与既有几何；绘图时按住 Shift 临时关闭对象和栅格捕捉。"
            "候选同距离时优先级为端点、交点、垂足、切点、圆心、中点、中心。"
        )
        self.grid_visible_check = QCheckBox("网格 F7")
        self.grid_visible_check.setChecked(True)
        self.grid_visible_check.setToolTip("显示/隐藏点阵网格（F7），不改变栅格捕捉。")
        self.grid_shortcut = QShortcut(QKeySequence("F7"), self)
        self.grid_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.grid_shortcut.activated.connect(self.grid_visible_check.toggle)
        self.grid_snap_check = QCheckBox("栅格捕捉")
        self.grid_snap_check.setToolTip(
            "捕捉当前栅格交点，隐藏网格后仍生效；对象捕捉优先。按住 Shift 临时关闭所有捕捉。"
        )
        self.orthogonal_check = QCheckBox("正交")
        self.orthogonal_check.setToolTip(
            "直线和折线按位移较大的方向锁定水平/竖直；捕捉到既有几何时保留捕捉点。"
        )
        self.dynamic_input_check = QCheckBox("动态输入")
        self.dynamic_input_check.setToolTip("为直线、矩形和圆锁定尺寸；其他工具尚不支持。")
        self.drawing_status_shortcuts: list[QShortcut] = []
        if select_committed_entities:
            for key, check in (
                ("F3", self.snap_check),
                ("F8", self.orthogonal_check),
                ("F9", self.grid_snap_check),
                ("F12", self.dynamic_input_check),
            ):
                check.setToolTip(f"{check.toolTip()}（{key}）")
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
                shortcut.activated.connect(check.toggle)
                self.drawing_status_shortcuts.append(shortcut)
        self.auto_relation_check = QCheckBox("自动关系")
        self.auto_relation_check.setChecked(True)
        self.auto_relation_check.setToolTip(
            "捕捉到既有端点/圆心时保存重合关系；直线接近水平或竖直时自动对齐并保存关系。"
        )
        self.construction_check = QCheckBox("构造几何")
        self.closed_check = QCheckBox("闭合多段线")
        self.polygon_sides_field = QSpinBox()
        self.polygon_sides_field.setRange(3, 128)
        self.polygon_sides_field.setValue(6)
        self.polygon_mode_combo = QComboBox()
        self.polygon_mode_combo.addItems(("内接圆", "外切圆"))
        self.polygon_mode_combo.setToolTip("内接圆：中心到顶点；外切圆：中心到边中点。")
        self.arc_direction_combo = QComboBox()
        self.arc_direction_combo.addItems(("逆时针", "顺时针"))
        self.layer_combo = QComboBox()
        self.layer_combo.addItems(
            tuple(layer.name for layer in self.layer_table.layers if not layer.frozen)
        )
        active_layer = self.layer_table.layers[0].name
        self.layer_combo.setCurrentText(active_layer)
        self.layer_manager_button = QPushButton("图层管理…")
        self.layer_manager_button.setToolTip(
            "统一管理草稿和已提交对象的显示、冻结、锁定、颜色、线型和线宽。"
        )
        set_button_icon(self.layer_manager_button, "layers")
        layer_bar.addWidget(QLabel("当前图层"))
        layer_bar.addWidget(self.layer_combo, 1)
        layer_bar.addWidget(self.layer_manager_button)
        self.view_3d_button = QPushButton("三维视图")
        set_button_icon(self.view_3d_button, "view-isometric")
        self.view_3d_button.setToolTip("切换到已提交模型的三维视图，保留当前二维草稿。")
        self.view_3d_button.clicked.connect(self.view_3d_requested)
        layer_bar.addWidget(self.view_3d_button)
        for check in (
            self.grid_visible_check,
            self.snap_check,
            self.grid_snap_check,
            self.orthogonal_check,
        ):
            if not select_committed_entities:
                layer_bar.addWidget(check)
        self.toolbar_menu_button = QToolButton()
        self.toolbar_menu_button.setText("工具栏与面板")
        self.toolbar_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar_menu = QMenu(self.toolbar_menu_button)
        for bar in self.drafting_toolbars:
            toolbar_menu.addAction(bar.toggleViewAction())
        toolbar_menu.addSeparator()
        for dock in self.drafting_docks:
            toolbar_menu.addAction(dock.toggleViewAction())
        toolbar_menu.addSeparator()
        toolbar_menu.addAction("恢复二维布局", self.reset_toolbar_layout)
        self.toolbar_menu_button.setMenu(toolbar_menu)
        layer_bar.addWidget(self.toolbar_menu_button)
        self.tool_buttons: dict[str, QToolButton] = {}
        for tool in (
            "选择元素",
            "直线",
            "多段线",
            "矩形",
            "多边形",
            "圆",
            "圆弧",
            "样条曲线",
            "修剪",
            "延伸",
            "分割",
        ):
            button = QToolButton()
            button.setText("选择" if tool == "选择元素" else "样条" if tool == "样条曲线" else tool)
            icon_name = dict(
                zip(
                    (
                        "选择元素",
                        "直线",
                        "多段线",
                        "矩形",
                        "多边形",
                        "圆",
                        "圆弧",
                        "样条曲线",
                        "修剪",
                        "延伸",
                        "分割",
                    ),
                    (
                        "select",
                        "line",
                        "polyline",
                        "rectangle",
                        "polygon",
                        "circle",
                        "arc",
                        "spline",
                        "trim",
                        "extend",
                        "split",
                    ),
                    strict=True,
                )
            )[tool]
            set_button_icon(button, "draw-" + icon_name)
            button.setIconSize(QSize(26, 26))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setToolTip(tool + "：在画布中选点；右键 / Enter 结束连线，Esc 退出当前操作。")
            button.setCheckable(True)
            button.setMinimumHeight(54)
            button.clicked.connect(
                lambda _checked=False, name=tool: self.tool_combo.setCurrentText(name)
            )
            self.tool_buttons[tool] = button
            button.setMinimumWidth(44)
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            toolbar = (
                self.modify_toolbar if tool in {"修剪", "延伸", "分割"} else self.drawing_toolbar
            )
            toolbar.addWidget(button)
        if select_committed_entities:
            fillet_button = QToolButton()
            fillet_button.setText("圆角")
            set_button_icon(fillet_button, "fillet")
            fillet_button.setIconSize(QSize(26, 26))
            fillet_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            fillet_button.setToolTip(
                "两圆外切圆角；不修剪原圆，也不创建相切约束。命令栏 R 设置半径。"
            )
            fillet_button.setCheckable(True)
            fillet_button.setMinimumSize(44, 54)
            fillet_button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            fillet_button.clicked.connect(
                lambda _checked=False: self.tool_combo.setCurrentText("二维圆角")
            )
            self.tool_buttons["二维圆角"] = fillet_button
            self.modify_toolbar.addWidget(fillet_button)
        self.tool_buttons["样条曲线"].setToolTip(
            "三次 B 样条（控制点方式）：至少四个控制点；Enter / 右键完成。首尾点在曲线上，中间点控制曲线形状。"
        )
        options_group = QGroupBox("绘图设置")
        options_group.setLayout(controls)
        for row, (label, widget) in enumerate(
            (
                ("工具", self.tool_combo),
                ("工作平面", self.plane_combo),
                ("圆弧方向", self.arc_direction_combo),
                ("多边形边数", self.polygon_sides_field),
                ("多边形模式", self.polygon_mode_combo),
            )
        ):
            controls.addWidget(QLabel(label), row, 0)
            controls.addWidget(widget, row, 1)
        for index, check in enumerate(
            (
                self.auto_relation_check,
                self.construction_check,
                self.closed_check,
            )
        ):
            controls.addWidget(check, 6 + index // 2, index % 2)
        panel_layout.addWidget(options_group)
        self.parameter_tabs.addTab(self.tool_panel, "绘图")

        origin = QFormLayout()
        self.origin_fields: dict[str, QDoubleSpinBox] = {}
        for axis in ("X", "Y", "Z"):
            field = QDoubleSpinBox()
            field.setRange(-1_000_000.0, 1_000_000.0)
            field.setDecimals(4)
            field.setSuffix(" mm")
            field.setPrefix(f"{axis}₀ ")
            if attached_frame is not None and support_face is not None:
                field.setValue(attached_frame.origin_mm[("X", "Y", "Z").index(axis)])
                field.setReadOnly(True)
                field.setToolTip("原点由所选模型面定义。")
            self.origin_fields[axis] = field
            origin.addRow(axis + "₀", field)
        origin_group = QGroupBox("UCS 原点 / mm")
        origin_group.setLayout(origin)
        self.parameter_tabs.addTab(self._parameter_page(origin_group), "UCS")

        self.canvas = SketchCanvas(self, select_committed_entities=select_committed_entities)
        self.canvas.continuous_lines = continuous_lines
        self.canvas.set_layer_table(self.layer_table, active_layer)
        if self._drag_preview is not None:
            self.canvas.set_drag_solver(self._preview_drag)
        self.ucs_label = QLabel("UCS · XY · X→ / Y↑ · mm")
        drawing.addWidget(self.ucs_label)
        self.dimension_controls_layout = QVBoxLayout()
        drawing.addLayout(self.dimension_controls_layout)
        drawing.addWidget(self.canvas, 1)
        self.dynamic_input = SketchDynamicInput(self)
        self._drawing_cursor_position: QPoint | None = None
        self._drawing_cursor_dimensions = QLabel(self.canvas)
        self._drawing_cursor_dimensions.setObjectName("drawingCursorDimensions")
        self._drawing_cursor_dimensions.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._drawing_cursor_dimensions.setStyleSheet(
            "QLabel { background: #f3f7fb; color: #243b53; "
            "border: 1px solid #849bb1; padding: 3px; }"
        )
        self._drawing_cursor_dimensions.hide()
        self._drawing_cursor_entry = _CursorDimensionEntry(self.canvas)
        self._drawing_cursor_entry.setObjectName("drawingCursorEntry")
        self._drawing_cursor_entry.setMaximumWidth(140)
        self._drawing_cursor_entry.setMaxLength(32)
        self._drawing_cursor_entry.hide()
        self._drawing_cursor_entry.next_requested.connect(self._advance_cursor_entry)
        self._drawing_cursor_entry.accept_requested.connect(self._accept_cursor_entry)
        self._drawing_cursor_entry.cancel_requested.connect(self._cancel_cursor_entry)
        self._drawing_cursor_field = 0
        self._dynamic_configured_tool = ""
        self._dynamic_was_pending = False
        self.canvas.dynamic_point_resolver = self._resolve_dynamic_point
        self.canvas.dynamic_key_handler = self._start_cursor_entry
        self.canvas.dynamic_click_guard = self._accept_cursor_entry
        self.canvas.changed.connect(self._sync_dynamic_input)
        self.canvas.point_accepted.connect(self._clear_dynamic_locks)
        self.dynamic_input_check.toggled.connect(self._sync_dynamic_input)
        self.dynamic_input_check.toggled.connect(self.canvas.refresh_dynamic_preview)
        self.dynamic_input.changed.connect(self.canvas.refresh_dynamic_preview)
        self.dynamic_input.changed.connect(self._update_drawing_cursor_dimensions)
        self.canvas.pointer_moved.connect(self._on_drawing_pointer_moved)
        self.canvas.pointer_left.connect(self._on_drawing_pointer_left)
        drawing.addWidget(self.dynamic_input)
        self._sync_dynamic_input()
        self.drawing_command_bar = Drawing2DCommandBar(
            self.canvas, self._activate_command_tool, self._activate_command_transform, self
        )
        self.dynamic_input.escape_requested.connect(self.drawing_command_bar.cancel)
        self.drawing_command_bar.setVisible(select_committed_entities)
        drawing.addWidget(self.drawing_command_bar)
        self.drawing_status_bar = QWidget()
        self.drawing_status_bar.setObjectName("drawing2dStatusBar")
        status_controls = QHBoxLayout(self.drawing_status_bar)
        status_controls.setContentsMargins(0, 0, 0, 0)
        status_controls.addStretch(1)
        if select_committed_entities:
            for check in (
                self.grid_visible_check,
                self.grid_snap_check,
                self.orthogonal_check,
                self.snap_check,
                self.dynamic_input_check,
            ):
                status_controls.addWidget(check)
        self.drawing_status_bar.setVisible(select_committed_entities)
        drawing.addWidget(self.drawing_status_bar)
        coordinate_group = QGroupBox("坐标输入 / mm")
        coordinate_layout = QVBoxLayout(coordinate_group)
        coordinates = QFormLayout()
        self.u_field = QDoubleSpinBox()
        self.v_field = QDoubleSpinBox()
        for field in (self.u_field, self.v_field):
            field.setRange(-1_000_000.0, 1_000_000.0)
            field.setDecimals(4)
            field.setSuffix(" mm")
        coordinates.addRow("U", self.u_field)
        coordinates.addRow("V", self.v_field)
        coordinate_layout.addLayout(coordinates)
        self.coordinate_add_button = QPushButton("按坐标点")
        self.finish_polyline_button = QPushButton("完成多段线")
        self.finish_polyline_button.setEnabled(False)
        self.undo_entity_button = QPushButton("撤销草稿操作")
        self.undo_entity_button.setEnabled(False)
        self.redo_entity_button = QPushButton("重做草稿操作")
        self.redo_entity_button.setEnabled(False)
        self.undo_entity_button.setToolTip("撤销上一项草稿操作；画布中按 Ctrl+Z。")
        self.redo_entity_button.setToolTip("重做已撤销的草稿操作；画布中按 Ctrl+Shift+Z。")
        coordinate_layout.addWidget(self.coordinate_add_button)
        panel_layout.addWidget(coordinate_group)
        self.end_chain_button = QPushButton("结束连线 ↵")
        self.close_chain_button = QPushButton("闭合 C")
        self.end_chain_button.clicked.connect(self.canvas.end_line_chain)
        self.close_chain_button.clicked.connect(self.canvas.close_chain)
        chain_controls = QHBoxLayout()
        chain_controls.addWidget(self.end_chain_button)
        chain_controls.addWidget(self.close_chain_button)
        panel_layout.addLayout(chain_controls)
        panel_layout.addWidget(self.finish_polyline_button)
        panel_layout.addStretch()

        transform_grid = QGridLayout()
        self.delta_u_field = QDoubleSpinBox()
        self.delta_v_field = QDoubleSpinBox()
        self.center_u_field = QDoubleSpinBox()
        self.center_v_field = QDoubleSpinBox()
        self.angle_field = QDoubleSpinBox()
        self.pattern_angle_field = QDoubleSpinBox()
        self.offset_distance_field = QDoubleSpinBox()
        for field in (
            self.delta_u_field,
            self.delta_v_field,
            self.center_u_field,
            self.center_v_field,
            self.angle_field,
            self.pattern_angle_field,
            self.offset_distance_field,
        ):
            field.setRange(-1_000_000.0, 1_000_000.0)
            field.setDecimals(4)
        self.delta_u_field.setPrefix("ΔU ")
        self.delta_v_field.setPrefix("ΔV ")
        self.center_u_field.setPrefix("中心 U ")
        self.center_v_field.setPrefix("中心 V ")
        self.angle_field.setSuffix("°")
        self.angle_field.setPrefix("角度 ")
        self.angle_field.setValue(90.0)
        self.pattern_angle_field.setSuffix("°")
        self.pattern_angle_field.setPrefix("环阵角 ")
        self.pattern_angle_field.setValue(360.0)
        self.offset_distance_field.setPrefix("偏移 ")
        self.offset_distance_field.setSuffix(" mm")
        self.offset_distance_field.setValue(1.0)
        self.count_field = QSpinBox()
        self.count_field.setRange(2, 1000)
        self.count_field.setValue(3)
        self.count_field.setPrefix("数量 ")
        self.rotation_reference_check = QCheckBox("参考旋转（三点）")
        self.rotation_reference_check.setToolTip("依次指定旋转中心、起始参考点和目标方向点。")
        self.mirror_keep_source_check = QCheckBox("镜像保留原对象")
        self.mirror_keep_source_check.setChecked(True)
        self.mirror_axis_combo = QComboBox()
        self.mirror_axis_combo.addItems(("水平轴", "竖直轴"))
        fields = (
            ("参考旋转", self.rotation_reference_check),
            ("镜像副本", self.mirror_keep_source_check),
            ("变换步距", self.delta_u_field),
            ("", self.delta_v_field),
            ("旋转/阵列中心", self.center_u_field),
            ("", self.center_v_field),
            ("角度", self.angle_field),
            ("环阵总角", self.pattern_angle_field),
            ("偏移距离", self.offset_distance_field),
            ("数量", self.count_field),
            ("数值镜像方向", self.mirror_axis_combo),
        )
        for row, (label, field) in enumerate(fields):
            field.setToolTip(label)
            transform_grid.addWidget(field, row, 0)
        self.transform_buttons: dict[str, QToolButton] = {}
        operations = (
            ("move", "移动"),
            ("copy", "复制"),
            ("rotate", "旋转"),
            ("mirror", "镜像"),
            ("offset", "偏移"),
            ("linear_array", "线性阵列"),
            ("circular_array", "环形阵列"),
        )
        for operation, label in operations:
            button = QToolButton()
            button.setText({"linear_array": "线阵", "circular_array": "环阵"}.get(operation, label))
            set_button_icon(button, "edit-" + operation)
            button.setIconSize(QSize(26, 26))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setMinimumHeight(54)
            button.setToolTip(label + "：先选择草稿图元，再设置下方修改参数。")
            button.setEnabled(False)
            button.clicked.connect(
                lambda _checked=False, selected_operation=operation: self._start_transform(
                    selected_operation
                )
            )
            self.transform_buttons[operation] = button
            button.setMinimumWidth(44)
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            self.modify_toolbar.addWidget(button)
        transform_group = QGroupBox("修改参数 · 先选择元素")
        transform_group.setLayout(transform_grid)
        self.numeric_move_button = QPushButton("按 ΔU / ΔV 移动")
        self.numeric_copy_button = QPushButton("按 ΔU / ΔV 复制")
        self.numeric_move_button.clicked.connect(lambda: self._apply_transform("move"))
        self.numeric_copy_button.clicked.connect(lambda: self._apply_transform("copy"))
        transform_grid.addWidget(self.numeric_move_button, len(fields), 0)
        transform_grid.addWidget(self.numeric_copy_button, len(fields) + 1, 0)
        self.numeric_rotate_button = QPushButton("应用输入角度")
        self.numeric_rotate_button.setToolTip("已拾取中心时绕该点旋转；否则使用中心 U / V。")
        self.numeric_rotate_button.clicked.connect(self._apply_numeric_rotation)
        transform_grid.addWidget(self.numeric_rotate_button, len(fields) + 2, 0)
        self.numeric_mirror_button = QPushButton("按输入中心 / 方向镜像")
        self.numeric_mirror_button.clicked.connect(lambda: self._apply_transform("mirror"))
        transform_grid.addWidget(self.numeric_mirror_button, len(fields) + 3, 0)
        self.transform_buttons["rotate"].setToolTip(
            "旋转：选择对象 → 中心 → 鼠标指定方向或键入角度；可选三点参考旋转。"
        )
        self.transform_buttons["mirror"].setToolTip(
            "镜像：选择对象 → 镜像轴两点；默认保留原对象，可取消勾选以替换。"
        )
        self.transform_buttons["move"].setToolTip(
            "移动：选择对象、指定基点和目标点；鼠标预览，Esc 取消。"
        )
        self.transform_buttons["copy"].setToolTip(
            "复制：选择对象、指定基点和目标点；原对象保留，单击放置副本。"
        )
        transform_grid.addWidget(self.undo_entity_button, transform_grid.rowCount(), 0, 1, 2)
        transform_grid.addWidget(self.redo_entity_button, transform_grid.rowCount(), 0, 1, 2)
        self.modify_page = self._parameter_page(transform_group)
        self.parameter_tabs.addTab(self.modify_page, "修改")
        self.parameter_tabs.addTab(self.navigator, "图形")

        self.status_label = MessageLabel(self.canvas.message)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.dimensions = DimensionTools(self)
        self.canvas.deleting.connect(self.dimensions.cancel)
        self.navigator.delete_requested.connect(self.canvas.delete_selected)
        self.entity_count_label = QLabel("0 个草图元素")
        self.finish_button = QPushButton("完成草图")
        self.finish_button.setEnabled(False)
        self.cancel_button = QPushButton("取消")
        self.drawing_toolbar.addSeparator()
        self.drawing_toolbar.addWidget(self.finish_button)
        self.drawing_toolbar.addWidget(self.cancel_button)
        self.toolbar_host.statusBar().addWidget(self.entity_count_label)
        self.toolbar_host.statusBar().addWidget(self.status_label, 1)

        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        for field in self.origin_fields.values():
            field.valueChanged.connect(self._sync_state)
        self.plane_combo.currentTextChanged.connect(self._change_plane)
        self.tool_combo.currentTextChanged.connect(self._change_tool)
        self.construction_check.toggled.connect(self.canvas.set_construction)
        self.snap_check.toggled.connect(self.canvas.set_snapping_enabled)
        self.grid_snap_check.toggled.connect(self.canvas.set_grid_snapping_enabled)
        self.grid_visible_check.toggled.connect(self.canvas.set_grid_visible)
        self.polygon_sides_field.valueChanged.connect(self._update_polygon_options)
        self.polygon_mode_combo.currentTextChanged.connect(self._update_polygon_options)
        self.rotation_reference_check.toggled.connect(self._update_transform_options)
        self.mirror_keep_source_check.toggled.connect(self._update_transform_options)
        self.orthogonal_check.toggled.connect(self.canvas.set_orthogonal_enabled)
        self.auto_relation_check.toggled.connect(self.canvas.set_auto_inference_enabled)
        self.closed_check.toggled.connect(self.canvas.set_closed_polyline)
        self.arc_direction_combo.currentTextChanged.connect(self.canvas.set_arc_direction)
        self.layer_combo.currentTextChanged.connect(self._set_active_layer)
        self.layer_manager_button.clicked.connect(self.open_layer_manager)
        self.coordinate_add_button.clicked.connect(self._add_coordinate_point)
        self.finish_polyline_button.clicked.connect(lambda: self.canvas.finish_polyline())
        self.undo_entity_button.clicked.connect(self._undo_draft_operation)
        self.redo_entity_button.clicked.connect(self._redo_draft_operation)
        self.canvas.history_recorded.connect(self.layer_history_redo.clear)
        self.canvas.undo_requested.connect(self._undo_draft_operation)
        self.canvas.redo_requested.connect(self._redo_draft_operation)
        self.finish_button.clicked.connect(self.finish_sketch)
        self.cancel_button.clicked.connect(self.reject)
        self.canvas.changed.connect(self._sync_state)
        self.canvas.cursor_changed.connect(self._show_cursor)
        self._compact_toolbar_states: dict[QToolButton, tuple[int, QSize, Qt.ToolButtonStyle]] = {}
        self._compact_layout = False
        self._sync_state()

    def set_compact_layout(self, compact: bool) -> None:
        """Reduce toolbar height on small logical screens while retaining tooltips."""
        if compact == self._compact_layout:
            return
        self._compact_layout = compact
        if compact:
            self.ucs_label.hide()
            for toolbar in self.drafting_toolbars:
                for action in toolbar.actions():
                    button = toolbar.widgetForAction(action)
                    if isinstance(button, QToolButton):
                        self._compact_toolbar_states[button] = (
                            button.minimumHeight(),
                            button.iconSize(),
                            button.toolButtonStyle(),
                        )
                        button.setMinimumHeight(32)
                        button.setIconSize(QSize(18, 18))
                        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        else:
            self.ucs_label.show()
            for button, (height, icon_size, style) in self._compact_toolbar_states.items():
                button.setMinimumHeight(height)
                button.setIconSize(icon_size)
                button.setToolButtonStyle(style)
            self._compact_toolbar_states.clear()

    @staticmethod
    def _parameter_page(group: QGroupBox) -> QScrollArea:
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(group)
        layout.addStretch()
        page.setWidget(content)
        return page

    @property
    def drafting_docks(self) -> tuple[QDockWidget, ...]:
        return (self.parameter_dock,)

    @property
    def drafting_toolbars(self) -> tuple[QToolBar, QToolBar, QToolBar]:
        return (self.drawing_toolbar, self.modify_toolbar, self.dimension_toolbar)

    def _make_toolbar(self, title: str, name: str) -> QToolBar:
        bar = QToolBar(title, self.toolbar_host)
        bar.setObjectName(name)
        bar.setMovable(True)
        bar.setFloatable(True)
        bar.setAllowedAreas(Qt.ToolBarArea.AllToolBarAreas)
        bar.setStyleSheet(
            "QToolButton:checked { background: palette(alternate-base); border: 1px solid palette(highlight); }"
        )
        return bar

    def reset_toolbar_layout(self) -> None:
        self._suspended_toolbar_state = None
        for bar in self.drafting_toolbars:
            self.toolbar_host.removeToolBarBreak(bar)
            self.toolbar_host.removeToolBar(bar)
        for bar in (self.drawing_toolbar, self.modify_toolbar):
            self.toolbar_host.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
            bar.show()
        self.toolbar_host.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.toolbar_host.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.dimension_toolbar)
        self.dimension_toolbar.show()
        if hasattr(self, "parameter_dock"):
            self.parameter_dock.setFloating(False)
            self.toolbar_host.addDockWidget(
                Qt.DockWidgetArea.RightDockWidgetArea, self.parameter_dock
            )
            self.parameter_dock.show()
            self.toolbar_host.resizeDocks([self.parameter_dock], [270], Qt.Orientation.Horizontal)

    def _navigation_scope(self) -> tuple[frozenset[str], frozenset[str]]:
        selectable = frozenset(e.entity_id for e in self.canvas.selectable_entities())
        # An independently displayed DIM annotation remains selectable even when
        # its referenced geometry's layer is off. Keep that geometry unselected.
        in_scope = {e.entity_id for e in self.canvas.entities} | {
            e.entity_id
            for e, _layer in self.canvas.background_entities
            if self.canvas.select_committed_entities
        }
        constraints = frozenset(
            c.constraint_id
            for c in self.canvas.dimension_constraints()
            if self.canvas.annotation_layer(c).displayed
            and all(ref.entity_id in in_scope for ref in c.references)
        )
        return selectable, constraints

    def _sync_navigation(self) -> None:
        selectable, constraints = self._navigation_scope()
        self.canvas.selected_constraint_ids.intersection_update(constraints)
        self.canvas.selected_constraint_ids.intersection_update(
            c.constraint_id
            for c in self.canvas.dimension_constraints()
            if all(
                r.entity_id not in selectable or r.entity_id in self.canvas.selected_entity_ids
                for r in c.references
            )
        )
        self.navigator.sync(
            self.dimension_sources(),
            frozenset(self.canvas.selected_entity_ids),
            frozenset(self.canvas.selected_constraint_ids),
            selectable,
            constraints,
        )

    def _navigation_busy(self) -> bool:
        return (
            self.canvas.has_pending_geometry
            or self.canvas.has_active_edit_gesture
            or self.dimensions.mode is not None
            or self.dimensions.candidate is not None
        )

    def _select_navigation(self, entity_ids: object, constraint_ids: object) -> None:
        if self._navigation_busy():
            self.status_label.setText("请先完成当前操作或按 Esc 退出，再选择导航对象。")
            self._sync_navigation()
            target = (
                self.dimensions.value_editor
                if self.dimensions.value_editor.isVisible()
                else self.canvas
            )
            target.window().activateWindow()
            target.setFocus()
            return
        selectable, constraints = self._navigation_scope()
        selected_constraints = set(cast("frozenset[str]", constraint_ids)) & constraints
        selected = set(cast("frozenset[str]", entity_ids)) & selectable
        selected.update(
            r.entity_id
            for c in self.canvas.dimension_constraints()
            if c.constraint_id in selected_constraints
            for r in c.references
            if r.entity_id in selectable
        )
        self.dimensions.cancel()
        self.canvas.set_tool("选择元素")
        self.canvas.selected_entity_ids = selected
        self.canvas.selected_constraint_ids = selected_constraints
        self.canvas.message = (
            f"图形导航：已选 {len(selected)} 个图元、{len(selected_constraints)} 个约束。"
        )
        self.canvas.changed.emit()
        self.canvas.update()

    def _activate_navigation_constraint(self, identity: str) -> None:
        if self._navigation_busy() or identity not in self._navigation_scope()[1]:
            return
        for sketch in self.dimension_sources():
            for constraint in sketch.constraints:
                if constraint.constraint_id == identity and constraint.kind in DIMENSION_KINDS:
                    self.dimensions.edit(sketch, constraint)
                    return

    def toolbar_layout_state(self) -> QByteArray:
        return (
            self._suspended_toolbar_state
            if self._suspended_toolbar_state is not None
            else self.toolbar_host.saveState()
        )

    def restore_toolbar_layout(self, state: QByteArray | None) -> None:
        if state is not None:
            if self._suspended_toolbar_state is not None:
                self._suspended_toolbar_state = state
            else:
                self.toolbar_host.restoreState(state)

    def set_toolbars_locked(self, locked: bool) -> None:
        for bar in self.drafting_toolbars:
            bar.setMovable(not locked)
            bar.setFloatable(not locked)

    @override
    def hideEvent(self, event: QHideEvent) -> None:
        if self._suspended_toolbar_state is None:
            self._suspended_toolbar_state = self.toolbar_host.saveState()
        for widget in (*self.drafting_toolbars, *self.drafting_docks):
            widget.hide()
        super().hideEvent(event)

    @override
    def showEvent(self, event: QShowEvent) -> None:
        if self._suspended_toolbar_state is not None:
            state = self._suspended_toolbar_state
            self._suspended_toolbar_state = None
            self.toolbar_host.restoreState(state)
        super().showEvent(event)

    @property
    def draft_sketch_id(self) -> str:
        return self._drag_preview_sketch_id

    def dimension_sources(self) -> tuple[Sketch, ...]:
        draft = Sketch(
            self._drag_preview_sketch_id,
            self.current_frame(),
            tuple(self.canvas.entities),
            tuple(self.canvas.constraints),
            self.layer_table,
            self._support_face,
        )
        return (draft, *self._context_sketches)

    def preview_dimension(
        self, original: Sketch, candidate: SketchConstraint
    ) -> SketchConstraintSolveResult:
        preview = (
            self._constraint_update_preview
            if any(c.constraint_id == candidate.constraint_id for c in original.constraints)
            else self._constraint_preview
        )
        if preview is None:
            return SketchConstraintSolveResult(
                "unavailable", None, None, message="尺寸求解服务不可用"
            )
        return preview(original, candidate)

    def _open_draft_dimension(self) -> None:
        self.dimensions.start("smart")

    def show_dimension_preview(self, result: SketchConstraintSolveResult) -> None:
        self.clear_dimension_preview()
        if result.status != "success":
            candidate = self.dimensions.candidate
            conflicts = set(result.conflicting_constraint_ids)
            if candidate is not None:
                conflicts.add(candidate.constraint_id)
            constraints = (
                *self.canvas.constraints,
                *self.canvas.background_constraints,
                *((candidate,) if candidate is not None else ()),
            )
            self.canvas.dimension_error_constraint_ids = frozenset(conflicts)
            self.canvas.dimension_error_entity_ids = frozenset(
                ref.entity_id
                for constraint in constraints
                if constraint.constraint_id in conflicts
                for ref in constraint.references
            )
        sketch = result.sketch
        frame = self.current_frame()
        if result.status == "success" and sketch is not None:
            source = sketch.frame
            delta = tuple(a - b for a, b in zip(source.origin_mm, frame.origin_mm, strict=True))
            if (
                source.u_axis == frame.u_axis
                and source.v_axis == frame.v_axis
                and abs(sum(a * b for a, b in zip(delta, frame.normal, strict=True))) <= 1e-7
            ):
                shift = (
                    sum(a * b for a, b in zip(delta, frame.u_axis, strict=True)),
                    sum(a * b for a, b in zip(delta, frame.v_axis, strict=True)),
                )
                entities = move_entities(
                    sketch.entities, tuple(e.entity_id for e in sketch.entities), shift
                )
                constraints = tuple(
                    replace(
                        c,
                        position_mm=None
                        if c.position_mm is None
                        else (c.position_mm[0] + shift[0], c.position_mm[1] + shift[1]),
                        text_position_mm=None
                        if c.text_position_mm is None
                        else (c.text_position_mm[0] + shift[0], c.text_position_mm[1] + shift[1]),
                    )
                    for c in sketch.constraints
                )
                self.canvas.dimension_preview = replace(
                    sketch,
                    frame=frame,
                    entities=entities,
                    constraints=constraints,
                    support_face=None,
                )
        self.canvas.update()

    def clear_dimension_preview(self) -> None:
        self.canvas.dimension_preview = None
        self.canvas.dimension_error_entity_ids = frozenset()
        self.canvas.dimension_error_constraint_ids = frozenset()
        self.canvas.update()

    def set_context_sketches(self, sketches: tuple[Sketch, ...]) -> None:
        self._context_sketches = sketches
        if not self.document_layer_mode:
            self.layer_table = merge_layer_tables(
                *(s.layers for s in sketches), self.layer_table, include_dim=True
            )
            self.canvas.layer_table = self.layer_table
        self._context_frame = self.current_frame()
        self.canvas.set_background_sketches(sketches, self._context_frame)
        self._sync_state()

    def continue_workspace_from(self, previous: SketchEditorDialog) -> None:
        self.plane_combo.setCurrentText(previous.plane_combo.currentText())
        for axis, field in self.origin_fields.items():
            field.setValue(previous.origin_fields[axis].value())
        self.canvas.copy_view_from(previous.canvas)
        self.canvas.set_layer_table(previous.layer_table, previous.layer_combo.currentText())
        self._sync_state()
        self.snap_check.setChecked(previous.snap_check.isChecked())
        self.grid_snap_check.setChecked(previous.grid_snap_check.isChecked())
        self.grid_visible_check.setChecked(previous.grid_visible_check.isChecked())
        self.polygon_sides_field.setValue(previous.polygon_sides_field.value())
        self.polygon_mode_combo.setCurrentText(previous.polygon_mode_combo.currentText())
        self.orthogonal_check.setChecked(previous.orthogonal_check.isChecked())
        self.dynamic_input_check.setChecked(previous.dynamic_input_check.isChecked())
        self.canvas.circle_fillet_radius = previous.canvas.circle_fillet_radius
        self.drawing_command_bar.continue_from(previous.drawing_command_bar)

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self.canvas.continuous_lines:
            # Esc exits the command, never the whole in-place editing session.
            self.canvas.keyPressEvent(event)
            event.accept()
            return
        super().keyPressEvent(event)

    def _preview_drag(
        self,
        entities: tuple[SketchEntity, ...],
        constraints: tuple[SketchConstraint, ...],
        reference: SketchGeometryReference,
        target_mm: Point2D,
    ) -> SketchConstraintSolveResult:
        if self._drag_preview is None:
            return SketchConstraintSolveResult(
                "unavailable", None, None, message="草图约束拖动求解器不可用。"
            )
        sketch = Sketch(
            self._drag_preview_sketch_id,
            self.current_frame(),
            entities,
            constraints,
            self.layer_table,
            self._support_face,
        )
        return self._drag_preview(sketch, reference, target_mm)

    def current_frame(self) -> WorkPlaneFrame:
        if self.plane_combo.currentText() == "所选面" and self._attached_frame is not None:
            return self._attached_frame
        plane = {
            "XY": WorkPlaneFrame.xy(),
            "XZ": WorkPlaneFrame.xz(),
            "YZ": WorkPlaneFrame.yz(),
        }[self.plane_combo.currentText()]
        origin = tuple(self.origin_fields[axis].value() for axis in ("X", "Y", "Z"))
        return WorkPlaneFrame(
            cast("tuple[float, float, float]", origin),
            plane.u_axis,
            plane.v_axis,
            plane.normal,
        )

    def _set_active_layer(self, name: str) -> None:
        if not name:
            return
        self.canvas.set_layer_table(self.layer_table, name)
        layer = self.layer_table.get(name)
        if self.active_layer_manager is not None:
            self.active_layer_manager.set_layers(self.layer_table, self.dimension_layer, name)
        if layer.locked or not layer.displayed:
            self.status_label.setText("当前图层隐藏或已锁定，不能放置新图元。")

    def _apply_layer_table(self, layers: SketchLayerTable, active_layer_name: str) -> None:
        self.layer_table = layers
        if active_layer_name not in {layer.name for layer in layers.layers}:
            active_layer_name = "0"
        blocker = QSignalBlocker(self.layer_combo)
        self.layer_combo.clear()
        self.layer_combo.addItems(tuple(layer.name for layer in layers.layers))
        self.layer_combo.setCurrentText(active_layer_name)
        del blocker
        self.canvas.set_layer_table(layers, active_layer_name, record_history=True)
        self.canvas.changed.emit()

    @property
    def draft_signature(self) -> tuple[tuple[SketchEntity, ...], tuple[SketchConstraint, ...]]:
        return (tuple(self.canvas.entities), tuple(self.canvas.constraints))

    def set_document_layers(self, layers: SketchLayerTable, dimension_layer: str) -> None:
        if dimension_layer != ".":
            layers.get(dimension_layer)
        changed = layers != self.layer_table or dimension_layer != self.dimension_layer
        if (
            not changed
            and self.canvas.document_layer_table == layers
            and self.canvas.preserve_document_layers == self.document_layer_mode
        ):
            self.dimensions.sync_layer_combo()
            if self.active_layer_manager is not None:
                self.active_layer_manager.set_layers(
                    layers, dimension_layer, self.layer_combo.currentText()
                )
            return
        if changed:
            self.dimensions.cancel()
        self.layer_table = layers
        self.dimension_layer = dimension_layer
        self.canvas.document_layer_table = layers
        self.canvas.preserve_document_layers = self.document_layer_mode
        active = self.layer_combo.currentText() or "0"
        try:
            if layers.get(active).frozen:
                active = next((layer.name for layer in layers.layers if not layer.frozen), "0")
        except KeyError:
            active = "0"
        blocker = QSignalBlocker(self.layer_combo)
        self.layer_combo.clear()
        self.layer_combo.addItems(tuple(layer.name for layer in layers.layers if not layer.frozen))
        self.layer_combo.setCurrentText(active)
        del blocker
        self.canvas.set_layer_table(layers, active)
        self.canvas.set_background_sketches(self._context_sketches, self.current_frame())
        self.dimensions.sync_layer_combo()
        if self.active_layer_manager is not None:
            self.active_layer_manager.set_layers(layers, dimension_layer, active)
        self._sync_state()

    def request_layer_update(
        self,
        layers: SketchLayerTable,
        dimension_layer: str,
        assignments: tuple[dict[str, object], ...] = (),
        *,
        migrate_draft: bool = False,
    ) -> None:
        try:
            for sketch in self.dimension_sources():
                for entity in sketch.entities:
                    layers.get(entity.layer_name)
                for constraint in sketch.constraints:
                    if constraint.layer_name is not None:
                        layers.get(constraint.layer_name)
        except KeyError as exc:
            self.status_label.setText(f"图层 {exc} 仍被图元或标注使用，不能删除。")
            if self.active_layer_manager is not None:
                self.active_layer_manager.set_layers(
                    self.layer_table, self.dimension_layer, self.layer_combo.currentText()
                )
            return
        if (
            layers == self.layer_table
            and dimension_layer == self.dimension_layer
            and not assignments
            and not migrate_draft
        ):
            return
        if layers.get(self.layer_combo.currentText() or "0").frozen:
            self.status_label.setText("当前绘图层不能冻结，请先切换图层。")
            if self.active_layer_manager is not None:
                self.active_layer_manager.set_layers(
                    self.layer_table, self.dimension_layer, self.layer_combo.currentText()
                )
            return
        if self._can_finish is not None and not self._can_finish():
            self.status_label.setText("工作线程忙碌，请稍后修改图层。")
            return
        params: dict[str, object] = {
            "layers": layers.to_mapping(),
            "dimension_layer": dimension_layer,
            "assignments": list(assignments),
        }
        if self.document_layer_mode:
            self.layer_change_requested.emit({"params": params, "migrate_draft": migrate_draft})
            return
        self.canvas.set_layer_table(layers, self.canvas.active_layer_name, record_history=True)
        self.set_document_layers(layers, dimension_layer)
        if migrate_draft:
            self.apply_draft_dim_migration()

    def apply_draft_dim_migration(self) -> None:
        if any(c.kind in DIMENSION_KINDS and c.layer_name is None for c in self.canvas.constraints):
            original = self.dimension_sources()[0]
            solved = replace(
                original,
                constraints=tuple(
                    replace(c, layer_name="DIM")
                    if c.kind in DIMENSION_KINDS and c.layer_name is None
                    else c
                    for c in original.constraints
                ),
            )
            self.canvas.apply_constraint_solution(original, solved)

    def migrate_legacy_dimensions(self) -> None:
        table = merge_layer_tables(self.layer_table, include_dim=True)
        assignments: tuple[dict[str, object], ...] = tuple(
            {
                "sketch_id": s.sketch_id,
                "constraint_ids": [
                    c.constraint_id
                    for c in s.constraints
                    if c.kind in DIMENSION_KINDS and c.layer_name is None
                ],
                "layer_name": "DIM",
            }
            for s in self._context_sketches
            if any(c.kind in DIMENSION_KINDS and c.layer_name is None for c in s.constraints)
        )
        self.request_layer_update(table, self.dimension_layer, assignments, migrate_draft=True)

    def open_layer_manager(self) -> None:
        if self.active_layer_manager is not None:
            self.active_layer_manager.show()
            self.active_layer_manager.raise_()
            return
        used = tuple(e.layer_name for s in self.dimension_sources() for e in s.entities)
        used += tuple(
            c.layer_name
            for s in self.dimension_sources()
            for c in s.constraints
            if c.layer_name is not None
        )
        panel = DrawingLayerPanel(
            self.layer_table, self.layer_combo.currentText(), self.dimension_layer, used, self
        )
        self.active_layer_manager = panel
        panel.properties_changed.connect(self.request_layer_update)
        panel.current_layer_changed.connect(self.layer_combo.setCurrentText)
        panel.migrate_requested.connect(self.migrate_legacy_dimensions)
        panel.show()

    def finish_sketch(self) -> None:
        if self.canvas.has_active_edit_gesture:
            self.status_label.setText("先松开鼠标确认当前草稿预览，或按 Esc 取消后再完成草图。")
            return
        if self._can_finish is not None and not self._can_finish():
            self.status_label.setText("应用正在执行其他命令；草图仍保留在编辑器中。")
            return
        if self.canvas.has_pending_geometry:
            self.status_label.setText("当前图元未完成；先完成图元或按 Esc 清除后再完成草图。")
            return
        if not self.canvas.entities:
            self.status_label.setText("草图至少需要一个有效元素。")
            return
        try:
            self.result_sketch = Sketch(
                uuid4().hex,
                self.current_frame(),
                tuple(self.canvas.entities),
                constraints=tuple(self.canvas.constraints),
                layers=self.layer_table,
                support_face=self._support_face,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.accept()

    def _change_tool(self, tool: str) -> None:
        if hasattr(self, "dimensions"):
            self.dimensions.cancel()
        return_to_zero = (
            tool in {"直线", "多段线", "圆", "圆弧", "矩形", "多边形", "样条曲线"}
            and self.canvas.active_layer_name.casefold() == "dim"
        )
        if return_to_zero and self.layer_table.get("0").frozen:
            self.canvas.message = "0 图层已冻结，请先解冻后开始绘图。"
        elif self.canvas.set_tool(tool):
            if tool != "选择元素":
                self.parameter_tabs.setCurrentWidget(self.tool_panel)
            if hasattr(self, "drawing_command_bar"):
                self.drawing_command_bar.remember_tool(tool)
            if return_to_zero:
                self.layer_combo.setCurrentText("0")
            self.canvas.setFocus()
            return
        blocker = QSignalBlocker(self.tool_combo)
        self.tool_combo.setCurrentText(self.canvas.tool)
        del blocker
        self.status_label.setText(self.canvas.message)

    def _activate_command_tool(self, tool: str) -> bool:
        self._change_tool(tool)
        if self.canvas.tool != tool or self.canvas.has_pending_geometry:
            return False
        with QSignalBlocker(self.tool_combo):
            self.tool_combo.setCurrentText(tool)
        return True

    def _change_plane(self, plane: str) -> None:
        if self.canvas.entities or self.canvas.has_pending_geometry:
            blocker = QSignalBlocker(self.plane_combo)
            self.plane_combo.setCurrentText(self._selected_plane)
            del blocker
            self.status_label.setText("草图已有元素，工作平面已锁定；请取消并重新开始以更换平面。")
            return
        was_attached = self._support_face is not None
        if plane == "所选面" and self._attached_frame is not None:
            self._support_face = self._initial_support_face
            for axis, value in zip(("X", "Y", "Z"), self._attached_frame.origin_mm, strict=True):
                self.origin_fields[axis].setValue(value)
                self.origin_fields[axis].setReadOnly(True)
                self.origin_fields[axis].setToolTip("原点由所选模型面定义。")
        else:
            self._support_face = None
            for axis in ("X", "Y", "Z"):
                field = self.origin_fields[axis]
                if was_attached:
                    field.setValue(0.0)
                field.setReadOnly(False)
                field.setToolTip("")
        self._selected_plane = plane
        self.canvas.ucs_plane = plane
        self._sync_state()
        self.canvas.update()

    def _undo_draft_operation(self) -> None:
        if self.document_layer_mode:
            self.document_undo_requested.emit()
        else:
            self.canvas.undo_last_operation()

    def _redo_draft_operation(self) -> None:
        if self.document_layer_mode:
            self.document_redo_requested.emit()
        else:
            self.canvas.redo_last_operation()

    def _add_coordinate_point(self) -> None:
        self.canvas.add_coordinate_point(
            (self.u_field.value(), self.v_field.value()), exact_point=True
        )

    def _update_transform_options(self) -> None:
        self.canvas.configure_active_transform(
            reference_rotation=self.rotation_reference_check.isChecked(),
            keep_source=self.mirror_keep_source_check.isChecked(),
        )

    def _update_polygon_options(self) -> None:
        self.canvas.configure_polygon(
            self.polygon_sides_field.value(),
            circumscribed=self.polygon_mode_combo.currentText() == "外切圆",
        )

    def _apply_numeric_rotation(self) -> None:
        if self.canvas.rotation_center is not None:
            self.canvas.apply_rotation_angle(self.angle_field.value())
        else:
            self._apply_transform("rotate")

    def _start_transform(self, operation: str) -> None:
        self.parameter_tabs.setCurrentWidget(self.modify_page)
        if operation in {"move", "copy", "rotate", "mirror"}:
            self.canvas.begin_transform(
                operation,
                reference_rotation=self.rotation_reference_check.isChecked(),
                keep_source=self.mirror_keep_source_check.isChecked(),
            )
        else:
            self._apply_transform(operation)

    def _sync_dynamic_input(self) -> None:
        pending = self.canvas.has_pending_geometry
        finished = self._dynamic_was_pending and not pending
        self._dynamic_was_pending = pending
        ended_line = (
            self.canvas.tool == "直线"
            and self.canvas.continuous_lines
            and self.canvas.pending_point_count == 0
        )
        if finished or ended_line:
            self.dynamic_input.clear_locks()
        if not self.dynamic_input_check.isChecked():
            self.dynamic_input.clear_locks()
            self.dynamic_input.hide()
            self._dynamic_configured_tool = ""
            self._drawing_cursor_dimensions.hide()
            self._drawing_cursor_entry.hide()
            return
        tool = {"直线": "line", "矩形": "rectangle", "圆": "circle"}.get(self.canvas.tool, "select")
        if tool != self._dynamic_configured_tool:
            self.dynamic_input.configure(tool)
            self._dynamic_configured_tool = tool
        self.dynamic_input.setVisible(tool != "select")
        continuous_line = (
            self.canvas.tool == "直线"
            and self.canvas.continuous_lines
            and self.canvas.pending_point_count > 0
        )
        if tool == "select" or not (self.canvas.has_pending_geometry or continuous_line):
            self._drawing_cursor_entry.hide()
        self._update_drawing_cursor_dimensions()

    def _start_cursor_entry(self, event: QKeyEvent) -> bool:
        text = event.text()
        if (
            not self.dynamic_input_check.isChecked()
            or self._dynamic_configured_tool not in {"line", "rectangle", "circle"}
            or self.canvas.active_transform is not None
            or self._drawing_cursor_position is None
            or not (self.canvas.has_pending_geometry or self.canvas.pending_point_count > 0)
            or len(text) != 1
            or text not in "0123456789+-."
            or event.modifiers()
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.AltModifier
                | Qt.KeyboardModifier.MetaModifier
            )
        ):
            return False
        entry = self._drawing_cursor_entry
        self._drawing_cursor_field = 0
        entry.setText(text)
        entry.setPlaceholderText("尺寸")
        entry.setMaximumWidth(max(1, min(140, self.canvas.width())))
        entry.adjustSize()
        position = self._drawing_cursor_position
        x = position.x() + 14
        if x + entry.width() > self.canvas.width():
            x = max(0, position.x() - entry.width() - 14)
        y = position.y() + 38
        if y + entry.height() > self.canvas.height():
            y = max(0, position.y() - entry.height() - 14)
        entry.move(x, y)
        entry.show()
        entry.raise_()
        entry.setFocus()
        entry.setCursorPosition(len(text))
        return True

    def _commit_cursor_entry(self) -> bool:
        entry = self._drawing_cursor_entry
        if entry.isHidden():
            return True
        try:
            value = float(entry.text().strip())
        except ValueError:
            value = math.nan
        angle = self._dynamic_configured_tool == "line" and self._drawing_cursor_field == 1
        if not math.isfinite(value) or abs(value) > 1e9 or (not angle and round(value, 6) <= 0):
            message = "请输入有效的角度。" if angle else "请输入大于零的有效尺寸。"
            entry.setToolTip(message)
            entry.setStyleSheet("border: 1px solid #b42318;")
            self.canvas.message = message
            self.canvas.changed.emit()
            entry.setFocus()
            return False
        field = (
            self.dynamic_input.first_value
            if self._drawing_cursor_field == 0
            else self.dynamic_input.second_value
        )
        lock = (
            self.dynamic_input.first_lock
            if self._drawing_cursor_field == 0
            else self.dynamic_input.second_lock
        )
        lock.setChecked(True)
        field.setValue(value)
        entry.setStyleSheet("")
        entry.setToolTip("")
        return True

    def _accept_cursor_entry(self) -> bool:
        if not self._commit_cursor_entry():
            return False
        if not self._drawing_cursor_entry.isHidden():
            self._drawing_cursor_entry.hide()
            self.canvas.setFocus()
        return True

    def _advance_cursor_entry(self) -> None:
        if not self._commit_cursor_entry():
            return
        if self._drawing_cursor_field == 0 and self._dynamic_configured_tool != "circle":
            self._drawing_cursor_field = 1
            self._drawing_cursor_entry.clear()
            self._drawing_cursor_entry.setPlaceholderText(
                "角度" if self._dynamic_configured_tool == "line" else "高度"
            )
            self._drawing_cursor_entry.setFocus()
        else:
            self._accept_cursor_entry()

    def _cancel_cursor_entry(self) -> None:
        self._drawing_cursor_entry.hide()
        self.canvas.setFocus()
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        QCoreApplication.sendEvent(self.canvas, event)

    def _on_drawing_pointer_moved(self, position: QPoint) -> None:
        self._drawing_cursor_position = position
        self._update_drawing_cursor_dimensions()

    def _on_drawing_pointer_left(self) -> None:
        self._drawing_cursor_position = None
        self._drawing_cursor_dimensions.hide()

    def _update_drawing_cursor_dimensions(self) -> None:
        hint = self._drawing_cursor_dimensions
        position = self._drawing_cursor_position
        continuous_line = (
            self.canvas.tool == "直线"
            and self.canvas.continuous_lines
            and self.canvas.pending_point_count > 0
        )
        if (
            not self.dynamic_input_check.isChecked()
            or self._dynamic_configured_tool == "select"
            or not (self.canvas.has_pending_geometry or continuous_line)
            or position is None
        ):
            hint.hide()
            return
        dynamic = self.dynamic_input
        label = dynamic.first_label.text() or dynamic.circle_mode.currentText()
        first = f"{label} {dynamic.first_value.text()}"
        if dynamic.first_lock.isChecked():
            first += "（锁定）"
        parts = [first]
        if not dynamic.second_value.isHidden():
            second = f"{dynamic.second_label.text()} {dynamic.second_value.text()}"
            if dynamic.second_lock.isChecked():
                second += "（锁定）"
            parts.append(second)
        hint.setText("   ".join(parts))
        hint.setMaximumWidth(max(1, self.canvas.width()))
        hint.adjustSize()
        x = min(max(0, position.x() + 14), max(0, self.canvas.width() - hint.width()))
        y = min(max(0, position.y() + 16), max(0, self.canvas.height() - hint.height()))
        hint.move(x, y)
        hint.show()
        hint.raise_()

    def _resolve_dynamic_point(self, start: Point2D, point: Point2D) -> Point2D:
        if not self.dynamic_input_check.isChecked() or self._dynamic_configured_tool == "select":
            return point
        self.dynamic_input.update_from_pointer(start, point)
        return self.dynamic_input.resolve(start, point)

    def _clear_dynamic_locks(self, _point: object) -> None:
        self.dynamic_input.clear_locks()

    def _activate_command_transform(self, operation: str) -> bool:
        self._start_transform(operation)
        return self.canvas.active_transform == operation

    def _apply_transform(self, operation: str) -> None:
        self.canvas.cancel_transform()
        error = self.canvas.transform_selection_error(operation)
        if error:
            self.canvas.message = error
            self.canvas.changed.emit()
            return
        if operation == "move" and any(
            entity.entity_id in self.canvas.selected_entity_ids
            for entity, _layer in self.canvas.background_entities
        ):
            delta = (self.delta_u_field.value(), self.delta_v_field.value())
            if math.hypot(*delta) <= 1e-9:
                self.status_label.setText("请指定非零 ΔU / ΔV。")
                return
            self.canvas.committed_move_requested.emit(tuple(self.canvas.selected_entity_ids), delta)
            return
        if operation == "rotate" and any(
            entity.entity_id in self.canvas.selected_entity_ids
            for entity, _layer in self.canvas.background_entities
        ):
            center = (self.center_u_field.value(), self.center_v_field.value())
            error = self.canvas.rotation_draft_error(center, self.angle_field.value())
            if error:
                self.canvas.message = error
                self.canvas.changed.emit()
                return
            self.canvas.committed_rotation_requested.emit(
                tuple(self.canvas.selected_entity_ids), center, self.angle_field.value()
            )
            return
        if operation == "mirror" and any(
            entity.entity_id in self.canvas.selected_entity_ids
            for entity, _layer in self.canvas.background_entities
        ):
            start = (self.center_u_field.value(), self.center_v_field.value())
            end = (
                (start[0] + 1.0, start[1])
                if self.mirror_axis_combo.currentText() == "水平轴"
                else (start[0], start[1] + 1.0)
            )
            if self.mirror_keep_source_check.isChecked():
                try:
                    updated = self.canvas.mirror_selected_to_draft(start, end)
                except ValueError as exc:
                    self.status_label.setText(str(exc))
                    return
                self.canvas.message = "已镜像所选元素；副本获得新的草图身份。"
                self.canvas.replace_draft_entities(updated, select_new=True)
            else:
                error = self.canvas.mirror_draft_error(start, end)
                if error:
                    self.canvas.message = error
                    self.canvas.changed.emit()
                    return
                self.canvas.committed_mirror_requested.emit(
                    tuple(self.canvas.selected_entity_ids), start, end
                )
            return
        if operation == "copy" and any(
            entity.entity_id in self.canvas.selected_entity_ids
            for entity, _layer in self.canvas.background_entities
        ):
            delta = (self.delta_u_field.value(), self.delta_v_field.value())
            if math.hypot(*delta) <= 1e-9:
                self.status_label.setText("请指定非零 ΔU / ΔV。")
                return
            try:
                updated = self.canvas.copy_selected_to_draft(delta)
            except ValueError as exc:
                self.status_label.setText(str(exc))
                return
            self.canvas.message = "已复制所选元素；副本获得新的草图身份。"
            self.canvas.replace_draft_entities(updated, select_new=True)
            return
        selected_ids = tuple(
            entity.entity_id
            for entity in self.canvas.entities
            if entity.entity_id in self.canvas.selected_entity_ids
        )
        if not selected_ids:
            self.status_label.setText("先切换到“选择元素”并选择要变换的草图元素。")
            return
        locked_layers = tuple(
            sorted(
                {
                    entity.layer_name
                    for entity in self.canvas.entities
                    if entity.entity_id in selected_ids
                    and self.layer_table.get(entity.layer_name).locked
                },
                key=str.casefold,
            )
        )
        if locked_layers:
            self.status_label.setText(f"选择包含已锁定图层 {locked_layers[0]}；草图未修改。")
            return
        delta = (self.delta_u_field.value(), self.delta_v_field.value())
        if operation in {"move", "copy"} and math.hypot(*delta) <= 1e-9:
            self.status_label.setText(
                "请指定非零 ΔU / ΔV，或使用工具栏按钮在画布上指定基点和目标点。"
            )
            return
        center = (self.center_u_field.value(), self.center_v_field.value())
        angle = self.angle_field.value()
        pattern_angle = self.pattern_angle_field.value()
        offset_distance = self.offset_distance_field.value()
        count = self.count_field.value()

        def transform(entities: tuple[SketchEntity, ...]) -> tuple[SketchEntity, ...]:
            if operation == "move":
                return move_entities(entities, selected_ids, delta)
            if operation == "copy":
                return copy_entities(entities, selected_ids, delta)
            if operation == "rotate":
                return rotate_entities(entities, selected_ids, center, angle)
            if operation == "offset":
                return offset_entities(entities, selected_ids, offset_distance)
            if operation == "mirror":
                axis_end = (
                    (center[0] + 1.0, center[1])
                    if self.mirror_axis_combo.currentText() == "水平轴"
                    else (center[0], center[1] + 1.0)
                )
                mirrored_ids = selected_ids
                if self.mirror_keep_source_check.isChecked():
                    source_ids = {entity.entity_id for entity in entities}
                    entities = copy_entities(entities, selected_ids, (0.0, 0.0))
                    mirrored_ids = tuple(
                        entity.entity_id
                        for entity in entities
                        if entity.entity_id not in source_ids
                    )
                return mirror_entities(entities, mirrored_ids, center, axis_end)
            if operation == "linear_array":
                return linear_array_entities(entities, selected_ids, count=count, step_mm=delta)
            return circular_array_entities(
                entities,
                selected_ids,
                count=count,
                center_mm=center,
                total_angle_deg=pattern_angle,
            )

        try:
            updated = transform(tuple(self.canvas.entities))
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.canvas.message = {
            "move": "已移动所选元素；草图元素身份保持不变。",
            "copy": "已复制所选元素；副本获得新的草图身份。",
            "rotate": "已绕输入中心逆时针旋转所选元素。",
            "mirror": "已按选择的水平/竖直轴镜像所选元素。",
            "offset": "已创建所选元素的平行偏移副本。",
            "linear_array": "已生成线性阵列；数量包含原始元素。",
            "circular_array": "已生成环形阵列；完整 360° 阵列不重复首末元素。",
        }[operation]
        self.canvas.replace_draft_entities(
            updated,
            select_new=operation in {"copy", "offset", "linear_array", "circular_array"}
            or (operation == "mirror" and self.mirror_keep_source_check.isChecked()),
        )

    def _show_cursor(self, u: float, v: float, snap_kind: str) -> None:
        self.u_field.setValue(u)
        self.v_field.setValue(v)
        suffix = f" · 捕捉：{snap_kind}" if snap_kind else ""
        if self.canvas.tool in {"修剪", "延伸", "分割"}:
            suffix += (
                " · 目标已预选"
                if self.canvas.hovered_line_edit_target_id is not None
                else " · 移到唯一可操作曲线、线段或端点以预选"
            )
        if self.canvas.message:
            suffix += f" · {self.canvas.message}"
        self.status_label.set_transient_text(f"U {u:.4f} mm，V {v:.4f} mm{suffix}")

    def _sync_state(self) -> None:
        if (
            self.layer_table != self.canvas.layer_table
            or self.layer_combo.currentText() != self.canvas.active_layer_name
        ):
            self.layer_table = self.canvas.layer_table
            with QSignalBlocker(self.layer_combo):
                self.layer_combo.clear()
                self.layer_combo.addItems(
                    tuple(layer.name for layer in self.layer_table.layers if not layer.frozen)
                )
                self.layer_combo.setCurrentText(self.canvas.active_layer_name)
            if self.active_layer_manager is not None:
                self.active_layer_manager.set_layers(
                    self.layer_table, self.dimension_layer, self.canvas.active_layer_name
                )
        for name, button in self.tool_buttons.items():
            button.setChecked(self.canvas.tool == name)
        with QSignalBlocker(self.tool_combo):
            self.tool_combo.setCurrentText(self.canvas.tool)
        plane = self.plane_combo.currentText()
        horizontal, vertical = {"XY": ("X", "Y"), "XZ": ("X", "−Z"), "YZ": ("Y", "Z")}.get(
            plane, ("U", "V")
        )
        self.canvas.ucs_plane = plane
        origin = ", ".join(f"{self.origin_fields[axis].value():g}" for axis in ("X", "Y", "Z"))
        self.ucs_label.setText(f"UCS · {plane} · {horizontal}→ / {vertical}↑ · 原点 ({origin}) mm")
        self.close_chain_button.setEnabled(self.canvas.can_close_chain)
        self.end_chain_button.setEnabled(
            self.canvas.tool == "直线" and self.canvas.pending_point_count > 0
        )
        selected_count = len(self.canvas.selected_entity_ids)
        suffix = f" · 已选 {selected_count}" if selected_count else ""
        if self._context_frame != self.current_frame():
            self._context_frame = self.current_frame()
            self.canvas.set_background_sketches(self._context_sketches, self._context_frame)
        background_count = sum(
            layer.displayed for _entity, layer in self.canvas.background_entities
        )
        if background_count:
            label = "已提交图元" if self.canvas.select_committed_entities else "已提交参照"
            suffix += f" · {label} {background_count}"
        self.entity_count_label.setText(f"{len(self.canvas.entities)} 个草图元素{suffix}")
        self.finish_button.setEnabled(
            bool(self.canvas.entities)
            and not self.canvas.has_pending_geometry
            and not self.canvas.has_active_edit_gesture
        )
        self.finish_polyline_button.setEnabled(
            (self.canvas.tool == "多段线" and self.canvas.pending_point_count >= 2)
            or (self.canvas.tool == "样条曲线" and self.canvas.pending_point_count >= 4)
        )
        self.finish_polyline_button.setText(
            "完成样条" if self.canvas.tool == "样条曲线" else "完成多段线"
        )
        self.undo_entity_button.setEnabled(
            self.canvas.can_undo or bool(self.layer_history_boundaries)
        )
        self.redo_entity_button.setEnabled(self.canvas.can_redo or bool(self.layer_history_redo))
        for operation, button in self.transform_buttons.items():
            button.setEnabled(
                not self.canvas.has_pending_geometry
                and not self.canvas.has_active_edit_gesture
                and (
                    operation in {"move", "copy", "rotate", "mirror"}
                    or (self.canvas.tool == "选择元素" and bool(selected_count))
                )
            )
        if self.canvas.message:
            self.status_label.setText(self.canvas.message)
        self._sync_navigation()
