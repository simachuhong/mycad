# SPDX-FileCopyrightText: 2026 MyCAD contributors
# SPDX-License-Identifier: Apache-2.0
"""Interactive 2D command input and explicit planar coordinate parsing."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal, cast, override

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QMimeData,
    QObject,
    QPoint,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QInputMethodEvent, QKeyEvent, QKeySequence, QMouseEvent, QTextCursor
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget

from mycad.core.drawing_measurement import polyline_area_perimeter
from mycad.core.drawing_quick_measure import CurvePairMeasurement, QuickRadiusMeasurement
from mycad.core.drawing_quick_regions import (
    LinearRegion,
    SampledMeasuredRegion,
    build_quick_regions,
)
from mycad.core.sketch import (
    ArcEntity,
    CircleEntity,
    LineEntity,
    Point2D,
    PolylineEntity,
    RectangleEntity,
    SketchEntity,
    SplineEntity,
    polyline_self_intersection,
)
from mycad.core.sketch_constraints import SketchGeometryReference
from mycad.ui.workspace_console import MessageLabel

if TYPE_CHECKING:
    from mycad.ui.dimension_tools import DimensionTools
    from mycad.ui.sketch_editor import SketchCanvas


class _QuickRegionSignals(QObject):
    finished = Signal(object)


class _QuickRegionTask(QRunnable):
    """Build immutable region geometry without touching Qt widgets off-thread."""

    def __init__(
        self,
        token: int,
        lines: tuple[LineEntity, ...],
        circles: tuple[CircleEntity, ...],
        curved_polylines: tuple[PolylineEntity, ...] = (),
        arcs: tuple[ArcEntity, ...] = (),
        open_curved_polylines: tuple[PolylineEntity, ...] = (),
        spline_request: tuple[
            Callable[[tuple[SketchEntity, ...], Point2D], SampledMeasuredRegion | None],
            tuple[SketchEntity, ...],
            Point2D,
        ]
        | None = None,
    ) -> None:
        super().__init__()
        self.spline_request = spline_request
        self.token = token
        self.lines = lines
        self.circles = circles
        self.curved_polylines = curved_polylines
        self.arcs = arcs
        self.open_curved_polylines = open_curved_polylines
        self.signals = _QuickRegionSignals()

    @override
    def run(self) -> None:
        try:
            if self.spline_request is not None:
                measure, entities, point = self.spline_request
                result = measure(entities, point)
                self.signals.finished.emit((self.token, result, None))
                return
            result = (
                build_quick_regions(
                    self.lines,
                    self.circles,
                    self.curved_polylines,
                    self.arcs,
                    self.open_curved_polylines,
                )
                if self.open_curved_polylines
                else build_quick_regions(self.lines, self.circles, self.curved_polylines, self.arcs)
                if self.arcs
                else build_quick_regions(self.lines, self.circles, self.curved_polylines)
                if self.curved_polylines
                else build_quick_regions(self.lines, self.circles)
            )
            self.signals.finished.emit((self.token, result, None))
        except Exception as exc:
            self.signals.finished.emit((self.token, (), str(exc)))


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


class _CommandInput(QPlainTextEdit):
    return_pressed = Signal()
    escape_requested = Signal()
    space_requested = Signal()
    shift_changed = Signal(bool)
    history_requested = Signal(int)
    drawing_history_key = Signal(object)
    completion_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._composing = False
        self._input_start = 0
        self.setUndoRedoEnabled(False)
        self.setTabChangesFocus(False)
        self.setAcceptDrops(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

    def text(self) -> str:
        cursor = self.textCursor()
        cursor.setPosition(self._input_start)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        return cursor.selectedText().replace("\u2029", "\n")

    def setText(self, text: str) -> None:  # noqa: N802
        self.clear()
        self.insertPlainText(text)

    @override
    def clear(self) -> None:
        cursor = self.textCursor()
        cursor.setPosition(self._input_start)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.setTextCursor(cursor)

    def set_history(self, lines: list[str], prompt: str) -> None:
        typed = self.text()
        visible = lines[:-1] if lines and lines[-1] == prompt else lines
        prefix = "\n".join((*visible, prompt, "命令: "))
        self.setPlainText(prefix)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._input_start = cursor.position()
        cursor.insertText(typed)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _prepare_edit(self) -> bool:
        cursor = self.textCursor()
        if cursor.hasSelection():
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            if end <= self._input_start:
                cursor.movePosition(QTextCursor.MoveOperation.End)
            else:
                cursor.setPosition(max(start, self._input_start))
                cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        elif cursor.position() < self._input_start:
            cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)
        return cursor.position() == self._input_start and not cursor.hasSelection()

    @override
    def inputMethodEvent(self, event: QInputMethodEvent) -> None:  # noqa: N802
        if event.preeditString() or event.commitString():
            self._prepare_edit()
        self._composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    @override
    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        self._prepare_edit()
        self.insertPlainText(" ".join(source.text().splitlines()))

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._composing and event.key() in (
            Qt.Key.Key_Tab,
            Qt.Key.Key_Backtab,
            Qt.Key.Key_Space,
        ):
            event.accept()
            return
        if not self._composing and event.key() == Qt.Key.Key_Tab and not event.modifiers():
            self.completion_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Shift and not event.isAutoRepeat():
            self.shift_changed.emit(True)
        if not self._composing and (
            event.matches(QKeySequence.StandardKey.Undo)
            or event.matches(QKeySequence.StandardKey.Redo)
            or (
                event.key() == Qt.Key.Key_Y
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier
            )
        ):
            self.drawing_history_key.emit(event)
            event.accept()
            return
        if self._composing and event.key() == Qt.Key.Key_Escape:
            super().keyPressEvent(event)
            # Do not let an ignored Escape bubble up and cancel the CAD gesture.
            event.accept()
            return
        if self._composing and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            return
        if not self._composing and event.key() == Qt.Key.Key_Escape:
            self.escape_requested.emit()
            event.accept()
            return
        if not self._composing and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.return_pressed.emit()
            event.accept()
            return
        if not self._composing and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.history_requested.emit(-1 if event.key() == Qt.Key.Key_Up else 1)
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
        editing = (
            (bool(event.text()) and event.text().isprintable())
            or event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete)
            or event.matches(QKeySequence.StandardKey.Paste)
            or event.matches(QKeySequence.StandardKey.Cut)
        )
        if editing:
            at_start = self._prepare_edit()
            if event.key() == Qt.Key.Key_Backspace and at_start:
                event.accept()
                return
        super().keyPressEvent(event)

    @override
    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Shift and not event.isAutoRepeat():
            self.shift_changed.emit(False)
        super().keyReleaseEvent(event)


class Drawing2DCommandBar(QWidget):
    """Route explicit 2D commands and coordinates to the active sketch canvas."""

    history_line = Signal(str)
    history_reset = Signal()
    activate_requested = Signal()
    panel_requested = Signal(str)
    group_requested = Signal()
    ungroup_requested = Signal()
    group_edit_requested = Signal()
    block_requested = Signal()
    block_insert_requested = Signal()
    block_explode_requested = Signal()
    block_edit_requested = Signal()
    block_library_requested = Signal()
    block_write_requested = Signal()

    _DIMENSIONS = {
        "DIM": "smart",
        "DIMLINEAR": "linear",
        "DLI": "linear",
        "DIMALIGNED": "aligned",
        "DAL": "aligned",
        "DIMANGULAR": "angle",
        "DAN": "angle",
        "DIMRADIUS": "radius",
        "DRA": "radius",
        "DIMDIAMETER": "diameter",
        "DDI": "diameter",
        "DIMARC": "arc_length",
        "DAR": "arc_length",
        "DIMCONTINUE": "continue",
        "DCO": "continue",
        "DIMBASELINE": "baseline",
        "DBA": "baseline",
        "DIMORDINATE": "ordinate",
        "DOR": "ordinate",
    }

    _TOOLS = {
        "PO": "点",
        "POINT": "点",
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
        "ELLIPSE": "椭圆",
        "A": "圆弧",
        "ARC": "圆弧",
        "SPL": "样条曲线",
        "SPLINE": "样条曲线",
        "TR": "修剪",
        "TRIM": "修剪",
        "EX": "延伸",
        "EXTEND": "延伸",
        "SPLIT": "分割",
        "BREAKATPOINT": "单点打断",
        "F": "二维圆角",
        "FILLET": "二维圆角",
        "CHA": "二维倒角",
        "CHAMFER": "二维倒角",
    }
    _DRAWING_TOOLS = frozenset(
        {"点", "直线", "多段线", "矩形", "多边形", "圆", "圆弧", "椭圆", "样条曲线"}
    )
    _TRANSFORMS = {
        "E": "erase",
        "ERASE": "erase",
        "O": "offset",
        "OFFSET": "offset",
        "M": "move",
        "MOVE": "move",
        "CO": "copy",
        "CP": "copy",
        "COPY": "copy",
        "RO": "rotate",
        "ROTATE": "rotate",
        "SC": "scale",
        "SCALE": "scale",
        "MI": "mirror",
        "MIRROR": "mirror",
    }

    def __init__(
        self,
        canvas: SketchCanvas,
        activate: Callable[[str], bool],
        start_transform: Callable[[str], bool],
        parent: QWidget | None = None,
        *,
        apply_rectangular_array: Callable[[int, int, float, float, float], tuple[bool, str]],
        commit_rectangular_array: Callable[
            [bool, int, int, float, float, float, Point2D | SketchGeometryReference | None],
            tuple[bool, str],
        ],
        configure_polygon: Callable[[int, bool], None],
        measure_planar_region: Callable[
            [tuple[SketchEntity, ...], Point2D], SampledMeasuredRegion | None
        ]
        | None = None,
    ) -> None:
        super().__init__(parent)
        self._measure_planar_region = measure_planar_region
        self.setObjectName("drawing2dCommandBar")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._canvas = canvas
        self.quick_region_tooltip = QLabel(canvas)
        self.quick_region_tooltip.setObjectName("quickRegionTooltip")
        self.quick_region_tooltip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.quick_region_tooltip.setStyleSheet(
            "QLabel { background: #f3f7fb; color: #243b53; "
            "border: 1px solid #849bb1; padding: 3px; }"
        )
        self.quick_region_tooltip.hide()
        self._quick_pointer: QPoint | None = None
        self._dimensions: DimensionTools | None = None
        self._activate = activate
        self._start_transform = start_transform
        self._apply_rectangular_array = apply_rectangular_array
        self._commit_rectangular_array = commit_rectangular_array
        self._configure_polygon = configure_polygon
        self._polygon_stage = ""
        self._collection_selecting: Literal["group", "block"] | None = None
        self._view_stage = ""
        self._view_first: Point2D | None = None
        self._distance_active = False
        self._distance_first: Point2D | None = None
        self._area_points: list[Point2D] | None = None
        self._area_object = False
        self._area_mode = ""
        self._area_total = 0.0
        self._area_total_perimeter = 0.0
        self._area_terms: list[float] = []
        self._area_perimeter_terms: list[float] = []
        self._measurement_mode = ""
        self._quick_generation = 0
        self._quick_tasks: dict[int, _QuickRegionTask] = {}
        self._quick_snapshot: tuple[SketchEntity, ...] | None = None
        self._quick_cache: tuple[LinearRegion, ...] = ()
        self._quick_request: tuple[int, Point2D, bool, tuple[SketchEntity, ...]] | None = None
        self._angle_points: list[Point2D] = []
        self._angle_object: (
            tuple[SketchEntity, LineEntity | CircleEntity | ArcEntity, int | None, Point2D] | None
        ) = None
        self._linear_rotation_pending = False
        self._polygon_edge_first: Point2D | None = None
        self._rect_stage = ""
        self._polar_stage = ""
        self._array_stage = ""
        self._polar_center: Point2D = (0.0, 0.0)
        self._polar_count = 6
        self._polar_angle = 360.0
        self._polar_selected: frozenset[str] = frozenset()
        self._polar_sources: tuple[SketchEntity, ...] = ()
        self._polar_history = 0
        self._polar_revision: int | None = None
        self._rect_associative = False
        self._rect_rows = 1
        self._rect_columns = 1
        self._rect_row_spacing = 0.0
        self._rect_column_spacing = 0.0
        self._rect_angle = 0.0
        self._rect_base: Point2D | SketchGeometryReference | None = None
        self._rect_pending_rows = 1
        self._rect_pending_columns = 1
        self._rect_pending_row_spacing = 0.0
        self._rect_pending_column_spacing = 0.0
        self._rect_pending_angle = 0.0
        self._rect_edit_mode = ""
        self._rect_unit_first: Point2D | None = None
        self._rect_selected: frozenset[str] = frozenset()
        self._rect_sources: tuple[SketchEntity, ...] = ()
        self._rect_history = 0
        self._rect_revision: int | None = None
        self._last_point: Point2D | None = None
        self._last_command: str | None = None
        self._last_is_transform = False
        self._accepted = False
        self._circle_diameter = False
        self._chamfer_stage = ""
        self._chamfer_distance = 0.0
        self._chamfer_system_pending = ""
        self._fillet_radius_pending = False
        self._filletrad_system_pending = False
        self._fillet_trim_pending = False
        self._copy_mode_pending = False
        self._copy_command_mode_pending = False
        self._line_edge_pending = False
        self._edge_system_pending = False
        self._offsetdist_pending = False
        self._offsetgaptype_pending = False
        self._trim_mode_system_pending = False
        self._corner_trim_system_pending = False
        self._line_mode_pending = False
        self._projection_pending = ""
        self.history: list[str] = []
        self._input_history: list[str] = []
        self._history_index = 0
        self._history_draft = ""
        self._completion_prefix = ""
        self._completion_last = ""
        self._completion_index = -1
        self.status = MessageLabel("输入命令或坐标。", self)
        self.status.text_changed.connect(self._record_history)
        self.input = _CommandInput(self)
        self.input.installEventFilter(self)
        self.input.setObjectName("drawing2dCommandInput")
        self.input.set_history(self.history, self.status.text())
        self.status.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.input, 1)
        self.input.return_pressed.connect(self.submit)
        self.input.space_requested.connect(self.submit)
        self.input.escape_requested.connect(self.cancel)
        self.input.shift_changed.connect(canvas.set_temporary_snap_disabled)
        self.input.history_requested.connect(self._recall_input)
        self.input.completion_requested.connect(self._complete_command)
        self.input.drawing_history_key.connect(self._forward_drawing_history_key)
        canvas.point_accepted.connect(self._point_accepted)
        canvas.changed.connect(self._sync_canvas_prompt)
        canvas.visible_snap_entities_changed.connect(self._invalidate_quick_for_visible_change)
        canvas.installEventFilter(self)

    def bind_dimensions(self, dimensions: DimensionTools) -> None:
        self._dimensions = dimensions
        # Read-only commands must receive canvas picks before dimension selection.
        self._canvas.removeEventFilter(self)
        self._canvas.installEventFilter(self)
        dimensions.status_changed.connect(self.status.setText)
        dimensions.command_reset.connect(self._reset_dimension_input)
        dimensions.operation_started.connect(self._end_readonly_workflow)

    def begin_group_selection(self) -> bool:
        """Wait for an object selection made after the GROUP command."""
        return self._begin_collection_selection("group")

    def begin_block_selection(self) -> bool:
        """Wait for an object selection made after the BLOCK command."""
        return self._begin_collection_selection("block")

    def _begin_collection_selection(self, operation: Literal["group", "block"]) -> bool:
        if not self._activate("选择元素"):
            return False
        self._collection_selecting = operation
        subject = "要编组的对象" if operation == "group" else "要创建块的几何或文字"
        self._canvas.message = f"请先选择{subject}（Ctrl 多选），按 Enter 或右键确认，Esc 取消。"
        self.status.setText(self._canvas.message)
        self._canvas.setFocus()
        return True

    def _confirm_collection_selection(self) -> None:
        operation = self._collection_selecting
        self._collection_selecting = None
        self.input.clear()
        if operation == "group":
            self.group_requested.emit()
        elif operation == "block":
            self.block_requested.emit()
        self.status.setText(self._canvas.message)

    def remember_collection_command(
        self,
        operation: Literal[
            "group",
            "block",
            "ungroup",
            "groupedit",
            "insert",
            "explode",
            "bedit",
            "blocklib",
            "wblock",
        ],
    ) -> None:
        """Keep toolbar and command-line collection actions available for repeat."""
        self._last_command = operation.upper()
        self._last_is_transform = False

    def _can_repeat_on_canvas_right_click(self) -> bool:
        canvas = self._canvas
        return bool(
            canvas.select_committed_entities
            and canvas.tool == "选择元素"
            and not self.input.text().strip()
            and not canvas.has_pending_geometry
            and not canvas.has_active_edit_gesture
            and not canvas.selected_entity_ids
            and not canvas.selected_constraint_ids
            and not canvas.selected_raster_ids
            and not canvas.selected_block_instance_ids
            and not (
                canvas.text_tools and (canvas.text_tools.pending or canvas.text_tools.selected_ids)
            )
            and not (
                canvas.geometric_tolerance_tools
                and (
                    canvas.geometric_tolerance_tools.pending
                    or canvas.geometric_tolerance_tools.selected_ids
                )
            )
            and not self._collection_selecting
            and not self._distance_active
            and self._area_points is None
            and not self._measurement_mode
            and not self._view_stage
            and not self._polygon_stage
            and not self._array_stage
            and not self._polar_stage
            and not self._rect_stage
            and not self._chamfer_stage
            and not self._chamfer_system_pending
            and not self._fillet_radius_pending
            and not self._filletrad_system_pending
            and not self._fillet_trim_pending
            and not self._copy_mode_pending
            and not self._copy_command_mode_pending
            and not self._line_edge_pending
            and not self._edge_system_pending
            and not self._offsetdist_pending
            and not self._offsetgaptype_pending
            and not self._trim_mode_system_pending
            and not self._corner_trim_system_pending
            and not self._line_mode_pending
            and not self._projection_pending
            and not self._linear_rotation_pending
            and not (self._dimensions and self._dimensions.mode is not None)
        )

    def _end_readonly_workflow(self) -> bool:
        active = bool(
            self._distance_active
            or self._area_points is not None
            or self._measurement_mode
            or self._view_stage
        )
        self._distance_active = False
        self._distance_first = None
        self._area_points = None
        self._area_object = False
        self._area_mode = ""
        self._area_total = 0.0
        self._area_total_perimeter = 0.0
        self._area_terms.clear()
        self._area_perimeter_terms.clear()
        self._canvas.set_area_preview(())
        self._canvas.update_quick_measure(None)
        self._invalidate_quick_regions()
        self._measurement_mode = ""
        self._angle_points = []
        self._angle_object = None
        self._view_stage = ""
        self._view_first = None
        self._canvas.set_zoom_window_preview(None)
        if active:
            self.input.clear()
        return active

    def _reset_dimension_input(self) -> None:
        self._linear_rotation_pending = False

    def _forward_drawing_history_key(self, value: object) -> None:
        if isinstance(value, QKeyEvent):
            QCoreApplication.sendEvent(
                self._canvas,
                QKeyEvent(value.type(), value.key(), value.modifiers(), value.text()),
            )

    def _command_names(self) -> list[str]:
        return sorted(
            set(self._TOOLS)
            | set(self._TRANSFORMS)
            | set(self._DIMENSIONS)
            | {
                "ARRAY",
                "AR",
                "ARRAYRECT",
                "ARRAYPOLAR",
                "COPYCLIP",
                "PASTECLIP",
                "LAYER",
                "LA",
                "PROPERTIES",
                "MO",
                "OPTIONS",
                "OP",
                "ZOOM",
                "Z",
                "PAN",
                "GROUP",
                "UNGROUP",
                "GROUPEDIT",
                "BLOCK",
                "INSERT",
                "EXPLODE",
                "BEDIT",
                "BLOCKLIB",
                "WBLOCK",
                "P",
                "HELP",
                "FILLETRAD",
                "OFFSETDIST",
                "CHAMFERA",
                "CHAMFERB",
                "CHAMFERC",
                "CHAMFERD",
                "CHAMMODE",
                "TEXT",
                "DTEXT",
                "MTEXT",
                "STYLE",
                "DIMSTYLE",
                "TOLERANCE",
                "AMFCFRAME",
                "AMDATUMID",
                "DATUMLABEL",
                "DATUMSTYLE",
                "DATUMSYMBOL",
                "DATUMARROW",
                "SURFACEEXTEDIT",
                "SURFACEINDICATION",
                "EDGESYMBOL",
                "DETACHDATUM",
                "DETACHFRAME",
                "REATTACH",
                "REPAIRANNOTATIONIDS",
                "CURVEIDUPGRADE",
                "D",
                "DIST",
                "DI",
                "AREA",
                "MEASUREGEOM",
                "MEA",
                "QSELECT",
                "OFFSETGAPTYPE",
                "PROJMODE",
                "TRIMEXTENDMODE",
                "EDGEMODE",
                "COPYMODE",
                "TRIMMODE",
            }
        )

    def _complete_command(self) -> None:
        active_dimension = self._dimensions is not None and self._dimensions.mode is not None
        options_active = True
        if any(
            (
                self._chamfer_system_pending,
                self._filletrad_system_pending,
                self._corner_trim_system_pending,
                self._edge_system_pending,
                self._offsetdist_pending,
                self._offsetgaptype_pending,
                self._trim_mode_system_pending,
                self._projection_pending == "system",
            )
        ):
            return
        if (
            active_dimension
            and self._dimensions is not None
            and self._dimensions.mode in {"linear", "horizontal", "vertical"}
            and not self._dimensions.command_editing_value
            and not self._linear_rotation_pending
        ):
            candidates = ["HORIZONTAL", "ROTATED", "VERTICAL"]
        elif self._polygon_stage == "center":
            candidates = ["EDGE"]
        elif self._polygon_stage == "mode":
            candidates = ["CIRCUMSCRIBED", "INSCRIBED"]
        elif self._measurement_mode == "options":
            candidates = ["ANGLE", "AREA", "DISTANCE", "QUICK", "RADIUS"]
        elif self._measurement_mode == "angle" and not self._angle_points:
            candidates = ["OBJECT"]
        elif self._area_points is not None and not self._area_object:
            candidates = ["CLOSE", "UNDO"]
            if not self._area_points:
                candidates.extend(["ADD", "OBJECT", "SUBTRACT"])
        elif self._area_points is not None and self._area_mode:
            candidates = ["ADD", "SUBTRACT"]
        elif self._view_stage == "zoom":
            candidates = ["ALL", "EXTENTS", "PREVIOUS", "WINDOW"]
        elif self._array_stage == "kind":
            candidates = ["POLAR", "RECTANGULAR"]
        elif self._polar_stage == "preview":
            candidates = ["ANGLE", "EXIT", "ITEMS"]
        elif self._rect_stage == "preview":
            candidates = [
                "ANGLE",
                "ASSOCIATIVE",
                "BASE",
                "COLUMNS",
                "COUNT",
                "EXIT",
                "ROWS",
                "SPACING",
            ]
        elif self._rect_stage == "edit_base":
            candidates = ["DEFAULT", "KEY"]
        elif self._rect_stage == "edit_associative":
            candidates = ["NO", "YES"]
        elif self._rect_stage in {
            "row_spacing",
            "column_spacing",
            "edit_row_spacing",
            "edit_column_spacing",
        }:
            candidates = ["TOTAL"]
            if self._rect_edit_mode == "S" and self._rect_stage.startswith("edit_"):
                candidates.append("UNIT")
        elif self._line_mode_pending:
            candidates = ["QUICK", "STANDARD"]
        elif self._projection_pending == "command":
            candidates = ["NONE", "UCS", "VIEW"]
        elif self._line_edge_pending:
            candidates = ["EXTEND", "NOEXTEND"]
        elif self._canvas.tool == "二维倒角":
            if self._canvas.chamfer_polyline_pending:
                return
            if self._chamfer_stage == "trim":
                candidates = ["NOTRIM", "TRIM"]
            elif self._chamfer_stage == "method":
                candidates = ["ANGLE", "DISTANCE"]
            elif self._chamfer_stage:
                return
            elif self._canvas.has_active_edit_gesture:
                candidates = ["MULTIPLE", "UNDO"]
            else:
                candidates = ["ANGLE", "DISTANCE", "METHOD", "MULTIPLE", "POLYLINE", "TRIM", "UNDO"]
        elif self._canvas.tool == "二维圆角":
            if self._fillet_trim_pending:
                candidates = ["NOTRIM", "TRIM"]
            elif (
                self._fillet_radius_pending
                or self._canvas.circle_fillet_radius_pending
                or self._canvas.circle_fillet_polyline_pending
            ):
                return
            else:
                candidates = ["MULTIPLE", "POLYLINE", "RADIUS", "TRIM", "UNDO"]
        elif self._canvas.tool == "圆":
            if self._canvas.circle_ttr_active or self._circle_diameter:
                return
            candidates = ["DIAMETER"] if self._canvas.has_pending_geometry else ["TTR"]
        elif self._canvas.tool == "圆弧":
            if not self._canvas.arc_mode_prompt_active or self._canvas.arc_ttr_active:
                return
            candidates = ["3POINT", "CENTER", "TTR"]
        elif self._canvas.tool == "椭圆" and self._canvas.ellipse_mode_prompt_active:
            candidates = ["ARC"]
        elif self._canvas.tool == "椭圆" and self._canvas.ellipse_arc_mode:
            candidates = ["CW", "CCW"]
        elif self._canvas.tool == "多段线" and self._canvas.pending_point_count:
            if self._canvas.polyline_arc_stage:
                return
            candidates = (
                ["ANGLE", "CENTER", "CLOSE", "LINE", "RADIUS", "SECOND", "UNDO"]
                if self._canvas.polyline_arc_mode
                else ["ARC", "UNDO", "CLOSE"]
            )
        elif self._canvas.tool == "直线" and (
            self._last_command == "直线" or self._canvas.has_pending_geometry
        ):
            if self._canvas.line_tangent_awaiting_pick:
                return
            candidates = ["TANGENT"]
            if self._canvas.pending_point_count:
                candidates.extend(("CLOSE", "UNDO"))
        elif self._canvas.tool in {"修剪", "延伸"}:
            if self._canvas.has_active_edit_gesture:
                return
            candidates = ["CROSSING", "EDGE", "FENCE", "MODE", "PROJECT", "UNDO"]
            if self._canvas.tool == "修剪":
                candidates.append("ERASE")
        elif (
            self._view_stage
            or self._distance_active
            or self._area_points is not None
            or self._measurement_mode
            or self._polygon_stage
            or self._array_stage
            or self._polar_stage
            or self._rect_stage
            or self._canvas.has_pending_geometry
            or self._canvas.has_active_edit_gesture
            or active_dimension
        ):
            return
        else:
            options_active = False
            candidates = self._command_names()
        current = self.input.text().strip().upper()
        if self._view_stage == "zoom" and current and current[0] in "+-.0123456789":
            return
        if current != self._completion_last:
            self._completion_prefix = current
            self._completion_index = -1
        if not self._completion_prefix:
            return
        matches = [name for name in candidates if name.startswith(self._completion_prefix)]
        if not matches:
            self.status.setText(
                "没有匹配的选项。"
                if options_active
                else "没有匹配的命令；输入 HELP 查看支持的命令。"
            )
            return
        self._completion_index = (self._completion_index + 1) % len(matches)
        self._completion_last = matches[self._completion_index]
        self.input.setText(self._completion_last)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if self._collection_selecting and watched is self._canvas:
            if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self.cancel()
                    return True
                if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
                    if not self._canvas.has_active_edit_gesture:
                        self._confirm_collection_selection()
                    return True
            if (
                isinstance(event, QMouseEvent)
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.RightButton
                and not self._canvas.has_active_edit_gesture
            ):
                self._canvas.suppress_next_mouse_context_menu()
                self._confirm_collection_selection()
                return True
        if (
            watched is self._canvas
            and isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.RightButton
            and self._can_repeat_on_canvas_right_click()
        ):
            self._canvas.suppress_next_mouse_context_menu()
            self.submit()
            return True
        tools = self._canvas.geometric_tolerance_tools
        if (
            watched in (self._canvas, self.input)
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_F
            and event.modifiers() == Qt.KeyboardModifier.ShiftModifier
            and tools is not None
            and (tools.mechanical_datum_active or tools.mechanical_frame_active)
        ):
            if event.type() == QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            if event.type() == QEvent.Type.KeyPress:
                tools.toggle_mechanical_leader_orthogonal()
                event.accept()
                return True
        if watched is self._canvas and self._measurement_mode:
            if self._measurement_mode == "quick":
                if event.type() in {QEvent.Type.Leave, QEvent.Type.Wheel}:
                    self._canvas.update_quick_measure(None)
                    if event.type() == QEvent.Type.Leave:
                        self._quick_pointer = None
                        self.quick_region_tooltip.hide()
                elif isinstance(event, QMouseEvent) and event.type() == QEvent.Type.MouseMove:
                    self._quick_pointer = event.position().toPoint()
                    if self._canvas.quick_measure_regions:
                        self._canvas.update_quick_measure(None)
                        self._show_quick_region_totals()
                    else:
                        self._canvas.update_quick_measure(
                            self._canvas.screen_to_local(event.position())
                        )
                        preview = self._canvas.quick_measure_preview
                        self.status.setText(
                            f"快速测量：半径 {preview.radius_mm:g} mm，直径 {2 * preview.radius_mm:g} mm；Esc 退出。"
                            if isinstance(preview, QuickRadiusMeasurement)
                            else f"快速测量：距离 {preview.distance_mm:g} mm；Esc 退出。"
                            if isinstance(preview, CurvePairMeasurement)
                            else f"快速测量：距离 {preview.distance_mm:g} mm，夹角 {preview.angle_deg:g}°；Esc 退出。"
                            if preview is not None
                            else "快速测量：移动到两条直线或圆弧附近；Esc 退出。"
                        )
                elif (
                    isinstance(event, QMouseEvent)
                    and event.type() == QEvent.Type.MouseButtonPress
                    and event.button() == Qt.MouseButton.LeftButton
                ):
                    self._quick_pointer = event.position().toPoint()
                    self._select_quick_region(
                        self._canvas.screen_to_local(event.position()),
                        bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                    )
                    return True
            if (
                isinstance(event, QKeyEvent)
                and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape
            ):
                self.cancel()
                return True
            if (
                self._measurement_mode == "options"
                and isinstance(event, QMouseEvent)
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self.status.setText("请输入 D 距离、R 半径、A 角度或 AR 面积。")
                return True
            if (
                self._measurement_mode in {"radius", "angle", "angle_object", "angle_circle"}
                and isinstance(event, QMouseEvent)
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                point = self._canvas.screen_to_local(event.position())
                if self._measurement_mode == "radius":
                    self._measure_radius_at(point)
                elif self._measurement_mode == "angle_object":
                    self._measure_angle_object(point)
                elif self._measurement_mode == "angle_circle":
                    self._measure_angle_circle(self._canvas.snap_measurement_point(point))
                else:
                    self._accept_angle_point(self._canvas.snap_measurement_point(point))
                return True
        if watched is self._canvas and self._area_points is not None:
            if event.type() in {QEvent.Type.Leave, QEvent.Type.Wheel}:
                self._canvas.set_area_preview(
                    tuple(self._area_points), subtract=self._area_mode == "subtract"
                )
            if (
                isinstance(event, QMouseEvent)
                and (
                    event.type() == QEvent.Type.MouseMove
                    or (
                        event.type() == QEvent.Type.MouseButtonRelease
                        and event.button() == Qt.MouseButton.MiddleButton
                    )
                )
                and not self._area_object
            ):
                cursor = (
                    None
                    if event.buttons() & Qt.MouseButton.MiddleButton
                    else self._canvas.snap_measurement_point(
                        self._canvas.screen_to_local(event.position())
                    )
                )
                self._canvas.set_area_preview(
                    tuple(self._area_points), cursor, subtract=self._area_mode == "subtract"
                )
            if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self.cancel()
                    return True
                if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
                    self._area_enter()
                    return True
            if isinstance(event, QMouseEvent) and event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.RightButton:
                    self._area_enter()
                    return True
                if event.button() == Qt.MouseButton.LeftButton:
                    point = self._canvas.screen_to_local(event.position())
                    if self._area_object:
                        self._measure_area_object(point)
                    else:
                        self._accept_area_point(self._canvas.snap_measurement_point(point))
                    return True
        if watched is self._canvas and self._distance_active:
            if (
                isinstance(event, QKeyEvent)
                and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape
            ):
                self.cancel()
                return True
            if (
                isinstance(event, QMouseEvent)
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                point = self._canvas.snap_measurement_point(
                    self._canvas.screen_to_local(event.position())
                )
                self._accept_distance_point(point)
                return True
        if watched is self._canvas and self._view_stage:
            if self._view_stage == "zoom_window_second":
                if event.type() == QEvent.Type.Leave:
                    self._canvas.set_zoom_window_preview(self._view_first)
                elif isinstance(event, QMouseEvent) and event.type() in {
                    QEvent.Type.MouseMove,
                    QEvent.Type.MouseButtonRelease,
                }:
                    self._canvas.set_zoom_window_preview(self._view_first, event.position())
            if (
                isinstance(event, QKeyEvent)
                and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape
            ):
                self.cancel()
                return True
            if (
                (
                    self._view_stage == "zoom"
                    or self._view_stage.startswith(("pan_", "zoom_window_"))
                )
                and isinstance(event, QMouseEvent)
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                point = self._canvas.screen_to_local(event.position())
                self._submit_view(f"{point[0]!r},{point[1]!r}")
                return True
        if (
            watched is self._canvas
            and self._canvas.select_committed_entities
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.ShortcutOverride
            and len(event.text()) == 1
            and event.text().isprintable()
            and not event.text().isspace()
            and not event.modifiers()
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.AltModifier
                | Qt.KeyboardModifier.MetaModifier
            )
        ):
            event.accept()
            return True
        if (
            watched is self._canvas
            and self._canvas.arc_ttr_active
            and isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.RightButton
        ):
            if (
                self._canvas.dynamic_submit_handler is not None
                and self._canvas.dynamic_submit_handler()
            ):
                return True
            if (
                self._canvas.dynamic_click_guard is not None
                and not self._canvas.dynamic_click_guard()
            ):
                return True
            self.submit()
            return True
        if (
            watched is self._canvas
            and self._canvas.tool == "圆弧"
            and (not self._canvas.arc_ttr_active or self._canvas.arc_ttr_radius_pending)
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and self._canvas.dynamic_key_handler is not None
            and self._canvas.dynamic_key_handler(event)
        ):
            return True
        if (
            watched is self._canvas
            and self._canvas.arc_ttr_active
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}
        ):
            if (
                self._canvas.dynamic_submit_handler is not None
                and self._canvas.dynamic_submit_handler()
            ):
                return True
            if (
                self._canvas.dynamic_click_guard is not None
                and not self._canvas.dynamic_click_guard()
            ):
                return True
            self.submit()
            return True
        if (
            watched is self._canvas
            and (
                self._canvas.tool in {"二维圆角", "二维倒角"}
                or (self._canvas.tool == "圆弧" and self._canvas.select_committed_entities)
                or (
                    self._canvas.circle_ttr_radius_pending
                    and self._canvas.select_committed_entities
                )
            )
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and len(event.text()) == 1
            and event.text().isprintable()
            and not event.text().isspace()
            and not event.modifiers()
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.AltModifier
                | Qt.KeyboardModifier.MetaModifier
            )
        ):
            self.activate_requested.emit()
            self.input.setFocus()
            QCoreApplication.sendEvent(
                self.input,
                QKeyEvent(event.type(), event.key(), event.modifiers(), event.text()),
            )
            return True
        if (
            watched is self._canvas
            and self._array_stage
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            self.cancel()
            return True
        if (
            watched is self._canvas
            and self._array_stage == "select"
            and isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.RightButton
            and not self._canvas.has_active_edit_gesture
        ):
            self._submit_array("")
            return True
        if watched is self._canvas and self._polygon_stage:
            if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self.cancel()
                    return True
                if self._polygon_stage in {"sides", "mode"} and event.key() in {
                    Qt.Key.Key_Return,
                    Qt.Key.Key_Enter,
                    Qt.Key.Key_Space,
                }:
                    self._submit_polygon("")
                    self.input.setFocus()
                    return True
                if (
                    len(event.text()) == 1
                    and event.text().isprintable()
                    and not event.text().isspace()
                    and not event.modifiers()
                    & (
                        Qt.KeyboardModifier.ControlModifier
                        | Qt.KeyboardModifier.AltModifier
                        | Qt.KeyboardModifier.MetaModifier
                    )
                ):
                    self.activate_requested.emit()
                    self.input.setFocus()
                    QCoreApplication.sendEvent(
                        self.input,
                        QKeyEvent(event.type(), event.key(), event.modifiers(), event.text()),
                    )
                    return True
            if (
                isinstance(event, QMouseEvent)
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                if self._polygon_stage in {"center", "radius", "edge_first", "edge_second"}:
                    point = self._canvas.rectangular_array_unit_point(
                        event.position(),
                        disable_snapping=bool(
                            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                        ),
                    )
                    self._submit_polygon(f"{point[0]!r},{point[1]!r}")
                return True
        if watched is self._canvas and self._polar_stage:
            if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self.cancel()
                    return True
                if self._polar_stage in {"select", "preview"} and event.key() in {
                    Qt.Key.Key_Return,
                    Qt.Key.Key_Enter,
                    Qt.Key.Key_Space,
                }:
                    self._submit_polar_array("")
                    return True
                if (
                    self._polar_stage != "select"
                    and len(event.text()) == 1
                    and event.text().isprintable()
                    and not event.text().isspace()
                    and not event.modifiers()
                    & (
                        Qt.KeyboardModifier.ControlModifier
                        | Qt.KeyboardModifier.AltModifier
                        | Qt.KeyboardModifier.MetaModifier
                    )
                ):
                    self.activate_requested.emit()
                    self.input.setFocus()
                    QCoreApplication.sendEvent(
                        self.input,
                        QKeyEvent(event.type(), event.key(), event.modifiers(), event.text()),
                    )
                    return True
            if isinstance(event, QMouseEvent) and event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.RightButton and self._polar_stage in {
                    "select",
                    "preview",
                }:
                    self._submit_polar_array("")
                    return True
                if event.button() == Qt.MouseButton.LeftButton and self._polar_stage == "center":
                    point = self._canvas.rectangular_array_unit_point(
                        event.position(),
                        disable_snapping=bool(
                            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                        ),
                    )
                    self._submit_polar_array(f"{point[0]!r},{point[1]!r}")
                    self.input.setFocus()
                    return True
        if watched is self._canvas and self._rect_stage:
            if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self.cancel()
                    return True
                if (
                    self._rect_stage in {"select", "preview"}
                    and event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}
                    and (self._rect_stage == "preview" or not self._canvas.has_active_edit_gesture)
                ):
                    self._submit_rectangular_array("")
                    self.input.setFocus()
                    return True
            if (
                self._rect_stage
                in {
                    "edit_unit_first",
                    "edit_unit_second",
                    "edit_angle",
                    "edit_angle_second",
                    "edit_base",
                    "edit_base_key",
                }
                and isinstance(event, QMouseEvent)
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                point = self._canvas.rectangular_array_unit_point(
                    event.position(),
                    disable_snapping=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                )
                self._submit_rectangular_array(f"{point[0]!r},{point[1]!r}")
                self.input.setFocus()
                return True
            if (
                self._rect_stage in {"select", "preview"}
                and isinstance(event, QMouseEvent)
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.RightButton
                and (self._rect_stage == "preview" or not self._canvas.has_active_edit_gesture)
            ):
                self._submit_rectangular_array("")
                self.input.setFocus()
                return True
        if (
            watched is self._canvas
            and self._canvas.select_committed_entities
            and not self._canvas.has_active_edit_gesture
            and not self._rect_stage
            and not self._polar_stage
            and self._canvas.tool
            in {
                "选择元素",
                "点",
                "直线",
                "多段线",
                "圆",
                "矩形",
                "多边形",
                "样条曲线",
                "修剪",
                "延伸",
                "分割",
                "单点打断",
            }
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and not event.modifiers()
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.AltModifier
                | Qt.KeyboardModifier.MetaModifier
            )
        ):
            if self._canvas.tool == "选择元素" and event.key() in {
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
                Qt.Key.Key_Space,
            }:
                self.activate_requested.emit()
                self.submit()
                return True
            if len(event.text()) == 1 and event.text().isprintable() and not event.text().isspace():
                if (
                    self._canvas.dynamic_key_handler is not None
                    and self._canvas.dynamic_key_handler(event)
                ):
                    return True
                self.activate_requested.emit()
                self.input.setFocus()
                QCoreApplication.sendEvent(
                    self.input,
                    QKeyEvent(event.type(), event.key(), event.modifiers(), event.text()),
                )
                return True
        return super().eventFilter(watched, event)

    def _invalidate_quick_for_visible_change(self) -> None:
        if self._measurement_mode != "quick":
            return
        had_result = bool(
            self._canvas.quick_measure_regions
            or self._canvas.quick_measure_preview is not None
            or self._quick_request is not None
        )
        self._invalidate_quick_regions()
        self._canvas.update_quick_measure(None)
        if had_result:
            self.status.setText("图形或图层已变化，请重新选择区域。")

    def _sync_canvas_prompt(self) -> None:
        self._invalidate_quick_for_visible_change()
        if self._collection_selecting and self._canvas.tool != "选择元素":
            self._collection_selecting = None
        if self._canvas.active_transform is not None:
            self._end_readonly_workflow()
        if self._measurement_mode and self._canvas.tool != "选择元素":
            self._canvas.update_quick_measure(None)
            self._measurement_mode = ""
            self._angle_points = []
            self._angle_object = None
        if self._area_points is not None and self._canvas.tool != "选择元素":
            self._area_points = None
            self._area_object = False
            self._area_mode = ""
            self._area_total = 0.0
            self._area_total_perimeter = 0.0
            self._area_terms.clear()
            self._area_perimeter_terms.clear()
            self._canvas.set_area_preview(())
        if self._distance_active and self._canvas.tool != "选择元素":
            self._distance_active = False
            self._distance_first = None
        if self._view_stage and self._canvas.tool != "选择元素":
            self._view_stage = ""
            self._view_first = None
            self._canvas.set_zoom_window_preview(None)
        if self._polygon_stage and self._canvas.tool != "多边形":
            self._polygon_stage = ""
        if self._array_stage and self._canvas.tool != "选择元素":
            self._array_stage = ""
        if self._polar_stage and (
            self._canvas.tool != "选择元素"
            or (
                self._polar_stage in {"preview", "edit_count", "edit_angle"}
                and self._canvas.active_transform != "polar_array_preview"
            )
        ):
            self._polar_stage = ""
        if self._rect_stage and (
            self._canvas.tool != "选择元素"
            or (
                self._canvas.active_transform is not None
                and self._canvas.active_transform != "rectangular_array_preview"
            )
            or (
                (self._rect_stage == "preview" or self._rect_stage.startswith("edit_"))
                and self._canvas.active_transform != "rectangular_array_preview"
            )
        ):
            self._rect_stage = ""
        if self._canvas.tool != "圆" or not self._canvas.has_pending_geometry:
            self._circle_diameter = False
        if self._canvas.tool != "二维圆角":
            self._fillet_radius_pending = False
            self._fillet_trim_pending = False
            self._canvas.circle_fillet_trim_pending = False
            self._canvas.circle_fillet_radius_pending = False
        else:
            self._fillet_radius_pending = self._canvas.circle_fillet_radius_pending
        if self._collection_selecting and "按 Enter 或右键确认" not in self._canvas.message:
            self._canvas.message += " 按 Enter 或右键确认，Esc 取消。"
        self.status.setText(self._canvas.message)
        self.status.setToolTip(self._canvas.message)

    def continue_from(self, previous: Drawing2DCommandBar) -> None:
        """Retain this document's command and coordinate history across draft commits."""
        self.history = list(previous.history)
        self._input_history = list(previous._input_history)
        self._history_index = len(self._input_history)
        self._history_draft = ""
        self.input.set_history(self.history, self.status.text())
        self.history_reset.emit()
        self._last_point = previous._last_point
        self._last_command = previous._last_command
        self._last_is_transform = previous._last_is_transform

    def start_offset(self) -> None:
        """Start the same offset operation from a visible button."""
        if self._start_transform("offset"):
            self._canvas.enable_offset_direct_pick()
            self._last_command = "offset"
            self._last_is_transform = True
            self.input.clear()
        self.status.setText(self._canvas.message)
        self.input.setFocus()

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
            if self._canvas.tool == "点":
                self._activate("选择元素")

    def _canvas_key(self, key: Qt.Key) -> None:
        event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
        QCoreApplication.sendEvent(self._canvas, event)

    def cancel(self) -> None:
        self._collection_selecting = None
        if self._canvas.text_tools is not None:
            self._canvas.text_tools.cancel()
        if self._end_readonly_workflow():
            self.status.setText("命令已取消。")
            self.input.setFocus()
            return
        if self._dimensions is not None and self._dimensions.mode is not None:
            self._dimensions.cancel()
        self._chamfer_stage = ""
        self._chamfer_system_pending = ""
        self._rect_stage = ""
        self._polar_stage = ""
        self._array_stage = ""
        self._polygon_stage = ""
        self._linear_rotation_pending = False
        line_submode = (
            self._canvas.line_edit_erasing
            or self._canvas.trim_fence_active
            or self._canvas.selecting_line_edit_boundaries
            or self._canvas.line_tangent_active
        )
        self._line_edge_pending = False
        self._edge_system_pending = False
        self._offsetdist_pending = False
        self._offsetgaptype_pending = False
        self._trim_mode_system_pending = False
        self._corner_trim_system_pending = False
        self._line_mode_pending = False
        self._projection_pending = ""
        self._fillet_radius_pending = False
        self._filletrad_system_pending = False
        self._fillet_trim_pending = False
        self._canvas.circle_fillet_trim_pending = False
        self._copy_mode_pending = False
        self._copy_command_mode_pending = False
        self._canvas.circle_fillet_radius_pending = False
        self._canvas_key(Qt.Key.Key_Escape)
        if line_submode:
            self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        self._activate("选择元素")
        self.input.clear()
        self.status.setText("命令已取消；草稿保留。")
        self.input.setFocus()

    def start_measurement(self, command: str) -> None:
        """Start a read-only measurement from the toolbar without replacing active input."""
        if self.input.text().strip() or any(
            (
                self._distance_active,
                self._area_points is not None,
                self._measurement_mode,
                self._view_stage,
                self._polygon_stage,
                self._collection_selecting,
                self._array_stage,
                self._polar_stage,
                self._rect_stage,
                self._chamfer_stage,
                self._chamfer_system_pending,
                self._fillet_radius_pending,
                self._filletrad_system_pending,
                self._fillet_trim_pending,
                self._copy_mode_pending,
                self._copy_command_mode_pending,
                self._line_edge_pending,
                self._edge_system_pending,
                self._offsetdist_pending,
                self._offsetgaptype_pending,
                self._trim_mode_system_pending,
                self._corner_trim_system_pending,
                self._line_mode_pending,
                self._projection_pending,
                self._dimensions is not None and self._dimensions.mode is not None,
                self._canvas.has_pending_geometry,
                self._canvas.has_active_edit_gesture,
                self._canvas.active_transform is not None,
            )
        ):
            self.status.setText("请先完成或取消当前操作，再开始测量。")
            return
        if command in {"DIST", "AREA"}:
            self.input.setText(command)
            self.submit()
        elif command in {"Q", "R", "A"}:
            self.input.setText("MEASUREGEOM")
            self.submit()
            if self._measurement_mode == "options":
                self.input.setText(command)
                self.submit()
        self._canvas.setFocus()

    def _begin_distance(self) -> None:
        if (
            self._canvas.has_pending_geometry
            or self._canvas.has_active_edit_gesture
            or self._canvas.active_transform is not None
        ):
            self.status.setText("请先完成或取消当前操作，再测量距离。")
            return
        if not self._activate("选择元素"):
            self.status.setText(self._canvas.message)
            return
        self._distance_active = True
        self._distance_first = None
        self._last_command = "DIST"
        self._last_is_transform = False
        self.input.clear()
        self.status.setText("DIST：指定第一点。")

    def _begin_measuregeom(self) -> None:
        if (
            self._canvas.has_pending_geometry
            or self._canvas.has_active_edit_gesture
            or self._canvas.active_transform is not None
        ):
            self.status.setText("请先完成或取消当前操作，再开始测量。")
            return
        if not self._activate("选择元素"):
            self.status.setText(self._canvas.message)
            return
        self._measurement_mode = "options"
        self._angle_points = []
        self._last_command = "MEASUREGEOM"
        self._last_is_transform = False
        self.input.clear()
        self.status.setText("MEASUREGEOM：快速测量 Q、距离 D、半径 R、角度 A、面积 AR。")

    def _invalidate_quick_regions(self) -> None:
        self._quick_generation += 1
        self._quick_request = None
        self._quick_snapshot = None
        self._quick_cache = ()
        self.quick_region_tooltip.hide()
        if self._canvas.quick_measure_regions:
            self._canvas.quick_measure_regions = ()
            self._canvas.update()

    def _select_quick_region(self, point: Point2D, additive: bool) -> None:
        snapshot = self._canvas.visible_snap_entities()
        has_splines = any(isinstance(entity, SplineEntity) for entity in snapshot)
        if has_splines and self._measure_planar_region is None:
            self.status.setText("快速区域测量无法使用样条几何内核。")
            return
        if not has_splines and snapshot == self._quick_snapshot:
            self._apply_quick_region(point, additive)
            return
        if self._quick_tasks:
            self.status.setText("正在计算区域，请稍候。")
            return
        self._quick_generation += 1
        token = self._quick_generation
        self._quick_request = (token, point, additive, snapshot)
        curved_polylines = tuple(
            entity
            for entity in snapshot
            if isinstance(entity, PolylineEntity) and entity.closed and entity.bulges
        )
        curved_ids = {entity.entity_id for entity in curved_polylines}
        task = _QuickRegionTask(
            token,
            tuple(
                line
                for line in self._canvas.quick_measure_linework()
                if line.entity_id not in curved_ids
            ),
            tuple(entity for entity in snapshot if isinstance(entity, CircleEntity)),
            curved_polylines,
            tuple(entity for entity in snapshot if isinstance(entity, ArcEntity)),
            tuple(
                entity
                for entity in snapshot
                if isinstance(entity, PolylineEntity) and not entity.closed and entity.bulges
            ),
            (self._measure_planar_region, snapshot, point)
            if has_splines and self._measure_planar_region is not None
            else None,
        )
        self._quick_tasks[token] = task
        task.signals.finished.connect(self._complete_quick_regions)
        QThreadPool.globalInstance().start(task)
        self.status.setText("正在计算封闭区域…")

    def _complete_quick_regions(self, payload: object) -> None:
        if not isinstance(payload, tuple):
            return
        values = cast("tuple[object, ...]", payload)
        if len(values) != 3:
            return
        token, regions, error = values
        if not isinstance(token, int):
            return
        self._quick_tasks.pop(token, None)
        request = self._quick_request
        if request is None or request[0] != token or self._measurement_mode != "quick":
            return
        self._quick_request = None
        if request[3] != self._canvas.visible_snap_entities():
            self.status.setText("图形已变化，请重新选择区域。")
            return
        if isinstance(error, str):
            self.status.setText(f"无法计算区域：{error}")
            return
        if any(isinstance(entity, SplineEntity) for entity in request[3]):
            if regions is None:
                self.status.setText("未找到唯一封闭区域；请避开边界重新选择。")
            elif isinstance(regions, SampledMeasuredRegion):
                self._select_measured_region(regions, request[2])
            else:
                self.status.setText("无法计算区域，请重试。")
            return
        if not isinstance(regions, tuple) or not all(
            isinstance(item, LinearRegion) for item in cast("tuple[object, ...]", regions)
        ):
            self.status.setText("无法计算区域，请重试。")
            return
        self._quick_snapshot = request[3]
        self._quick_cache = cast("tuple[LinearRegion, ...]", regions)
        self._apply_quick_region(request[1], request[2])

    def _apply_quick_region(self, point: Point2D, additive: bool) -> None:
        matches = tuple(region for region in self._quick_cache if region.contains(point))
        if len(matches) != 1:
            self.status.setText("未找到唯一封闭区域；请避开边界重新选择。")
            return
        self._select_measured_region(matches[0], additive)

    def _select_measured_region(
        self, region: LinearRegion | SampledMeasuredRegion, additive: bool
    ) -> None:
        selected = list(self._canvas.quick_measure_regions) if additive else []
        if additive and region in selected:
            selected.remove(region)
        else:
            selected.append(region)
        self._canvas.quick_measure_regions = tuple(selected)
        self._canvas.update_quick_measure(None)
        self._show_quick_region_totals()

    def _show_quick_region_totals(self) -> None:
        selected = self._canvas.quick_measure_regions
        area = math.fsum(item.area_mm2 for item in selected)
        perimeter = math.fsum(item.perimeter_mm for item in selected)
        self.status.setText(
            f"快速区域：面积 {area:g} mm²，周长 {perimeter:g} mm；Shift 单击增减，Esc 退出。"
        )
        pointer = self._quick_pointer
        if not selected or pointer is None:
            self.quick_region_tooltip.hide()
            return
        self.quick_region_tooltip.setText(f"面积 {area:g} mm²\n周长 {perimeter:g} mm")
        self.quick_region_tooltip.adjustSize()
        x = max(0, min(pointer.x() + 16, self._canvas.width() - self.quick_region_tooltip.width()))
        y = max(
            0, min(pointer.y() + 16, self._canvas.height() - self.quick_region_tooltip.height())
        )
        self.quick_region_tooltip.move(x, y)
        self.quick_region_tooltip.show()
        self.quick_region_tooltip.raise_()

    def _measure_radius_at(self, point: Point2D) -> None:
        try:
            picked = self._canvas.measurement_curve_at(point)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        entity = picked[1] if picked is not None else None
        if not isinstance(entity, CircleEntity | ArcEntity):
            self.status.setText("请选择唯一的圆或圆弧。")
            return
        diameter = entity.radius_mm * 2.0
        if not math.isfinite(diameter):
            self.status.setText("直径超出可用范围。")
            return
        self._measurement_mode = ""
        self.input.clear()
        self.status.setText(f"半径：{entity.radius_mm:g} mm；直径：{diameter:g} mm。")

    def _measure_angle_object(self, point: Point2D) -> None:
        first = self._angle_object
        if first is not None and first[0] not in self._canvas.selectable_entities():
            self._angle_object = None
            self.status.setText("测量对象已变化，请重新选择第一个对象。")
            return
        try:
            picked = self._canvas.measurement_curve_at(point)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        if picked is None:
            self.status.setText("请选择唯一的直线、圆、圆弧或多段线段。")
            return
        source, curve, index = picked
        if first is None:
            if isinstance(curve, ArcEntity):
                self._finish_angle_measurement(abs(curve.sweep_angle_deg))
            elif isinstance(curve, CircleEntity):
                if math.dist(point, curve.center_mm) <= 1e-9:
                    self.status.setText("选择点不能与圆心重合；请重新选择圆周上的点。")
                    return
                self._angle_object = (source, curve, index, point)
                self._measurement_mode = "angle_circle"
                self.input.clear()
                self.status.setText("角度：指定圆心到第二点的方向。")
            else:
                self._angle_object = (source, curve, index, point)
                self.input.clear()
                self.status.setText("角度：选择第二条直线或多段线直线段。")
            return
        if not isinstance(first[1], LineEntity) or not isinstance(curve, LineEntity):
            self.status.setText("请选择第二条直线或多段线直线段。")
            return
        if source.entity_id == first[0].entity_id and index == first[2]:
            self.status.setText("请选择另一条直线或多段线段。")
            return
        line = first[1]
        self._finish_vector_angle(
            (line.end_mm[0] - line.start_mm[0], line.end_mm[1] - line.start_mm[1]),
            (curve.end_mm[0] - curve.start_mm[0], curve.end_mm[1] - curve.start_mm[1]),
        )

    def _measure_angle_circle(self, point: Point2D) -> None:
        first = self._angle_object
        if first is None or not isinstance(first[1], CircleEntity):
            return
        if first[0] not in self._canvas.selectable_entities():
            self._angle_object = None
            self._measurement_mode = "angle_object"
            self.status.setText("测量对象已变化，请重新选择第一个对象。")
            return
        center = first[1].center_mm
        self._finish_vector_angle(
            (first[3][0] - center[0], first[3][1] - center[1]),
            (point[0] - center[0], point[1] - center[1]),
            directed=True,
        )

    def _finish_vector_angle(
        self, first: Point2D, second: Point2D, *, directed: bool = False
    ) -> None:
        lengths = (math.hypot(*first), math.hypot(*second))
        if not all(math.isfinite(length) and length > 1e-9 for length in lengths):
            self.status.setText("角度方向无效；请重新指定。")
            return
        ax, ay = first[0] / lengths[0], first[1] / lengths[0]
        bx, by = second[0] / lengths[1], second[1] / lengths[1]
        dot, cross = ax * bx + ay * by, ax * by - ay * bx
        self._finish_angle_measurement(
            math.degrees(math.atan2(abs(cross), dot if directed else abs(dot)))
        )

    def _finish_angle_measurement(self, angle: float) -> None:
        self._measurement_mode = ""
        self._angle_object = None
        self._angle_points = []
        self.input.clear()
        self.status.setText(f"夹角：{angle:g}°。")

    def _accept_angle_point(self, point: Point2D) -> None:
        if self._angle_points and math.dist(point, self._angle_points[0]) <= 1e-9:
            self.status.setText("角度边上的点不能与顶点重合。")
            return
        self._angle_points.append(point)
        self.input.clear()
        if len(self._angle_points) < 3:
            self.status.setText(
                "角度：指定第一条边上的点。"
                if len(self._angle_points) == 1
                else "角度：指定第二条边上的点。"
            )
            return
        origin, first, second = self._angle_points
        u = (first[0] - origin[0], first[1] - origin[1])
        v = (second[0] - origin[0], second[1] - origin[1])
        ulength, vlength = math.hypot(*u), math.hypot(*v)
        if not math.isfinite(ulength) or not math.isfinite(vlength):
            self._angle_points.pop()
            self.status.setText("角度输入超出可用范围，请重新指定第二条边上的点。")
            return
        ux, uy = u[0] / ulength, u[1] / ulength
        vx, vy = v[0] / vlength, v[1] / vlength
        angle = abs(math.degrees(math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)))
        self._measurement_mode = ""
        self._angle_points = []
        self.status.setText(f"夹角：{angle:g}°。")

    def _begin_area(self) -> None:
        if (
            self._canvas.has_pending_geometry
            or self._canvas.has_active_edit_gesture
            or self._canvas.active_transform is not None
        ):
            self.status.setText("请先完成或取消当前操作，再测量面积。")
            return
        if not self._activate("选择元素"):
            self.status.setText(self._canvas.message)
            return
        self._area_points = []
        self._area_object = False
        self._area_mode = ""
        self._area_total = 0.0
        self._area_total_perimeter = 0.0
        self._area_terms.clear()
        self._area_perimeter_terms.clear()
        self._last_command = "AREA"
        self._last_is_transform = False
        self.input.clear()
        self.status.setText("AREA：指定边界点或选择对象(O)、增加(A)、扣减(S)。")

    def _measure_area_object(self, point: Point2D) -> None:
        entity = self._canvas.measurement_entity_at(point)
        if isinstance(entity, CircleEntity):
            area = math.pi * entity.radius_mm * entity.radius_mm
            perimeter = 2 * math.pi * entity.radius_mm
        elif isinstance(entity, RectangleEntity):
            dx = abs(entity.first_corner_mm[0] - entity.opposite_corner_mm[0])
            dy = abs(entity.first_corner_mm[1] - entity.opposite_corner_mm[1])
            area = dx * dy
            perimeter = 2 * (dx + dy)
        elif isinstance(entity, PolylineEntity) and entity.closed and not entity.bulges:
            self._area_points = list(entity.points_mm)
            self._finish_area()
            return
        elif isinstance(entity, PolylineEntity) and entity.closed:
            try:
                area, perimeter = polyline_area_perimeter(entity)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
        else:
            self.status.setText("请选择唯一的圆、矩形或闭合多段线。")
            return
        if not math.isfinite(area) or not math.isfinite(perimeter):
            self.status.setText("面积结果超出可用范围。")
            return
        self._report_area(area, perimeter)

    def _report_area(self, area: float, perimeter: float) -> None:
        self._canvas.set_area_preview(())
        if self._area_mode:
            sign = 1 if self._area_mode == "add" else -1
            try:
                total = math.fsum((*self._area_terms, sign * area))
                total_perimeter = math.fsum((*self._area_perimeter_terms, sign * perimeter))
            except (OverflowError, ValueError):
                self.status.setText("累计测量结果超出可用范围；本次测量未计入。")
                self._area_points = []
                return
            if not math.isfinite(total) or not math.isfinite(total_perimeter):
                self.status.setText("累计测量结果超出可用范围；本次测量未计入。")
                self._area_points = []
                return
            self._area_terms.append(sign * area)
            self._area_perimeter_terms.append(sign * perimeter)
            self._area_total, self._area_total_perimeter = total, total_perimeter
            self._area_points = []
            self.input.clear()
            next_step = (
                "继续选择对象，Enter 返回选项。"
                if self._area_object
                else "继续指定边界，或选择对象(O)、增加(A)、扣减(S)，Enter 结束。"
            )
            self.status.setText(
                f"面积：{area:g} mm²；周长：{perimeter:g} mm；"
                f"总面积：{total:g} mm²；总周长：{total_perimeter:g} mm。{next_step}"
            )
            return
        self._area_points = None
        self._area_object = False
        self.input.clear()
        self.status.setText(f"面积：{area:g} mm²；周长：{perimeter:g} mm。")

    def _area_enter(self) -> None:
        if self._area_mode and self._area_object:
            self._area_object = False
            self.input.clear()
            self.status.setText("AREA：指定边界点或选择对象(O)、增加(A)、扣减(S)，Enter 结束。")
        elif self._area_object:
            self.status.setText("AREA：请在画布上选择对象，或按 Esc 取消。")
        elif self._area_mode and not self._area_points:
            total, perimeter = self._area_total, self._area_total_perimeter
            self._end_readonly_workflow()
            self.status.setText(f"总面积：{total:g} mm²；总周长：{perimeter:g} mm。")
        else:
            self._finish_area()

    def _accept_area_point(self, point: Point2D) -> None:
        points = self._area_points
        if points is None:
            return
        if len(points) >= 1000:
            self.status.setText("AREA 最多支持 1000 个边界点；请按 Enter 完成。")
            return
        if points and math.dist(points[-1], point) <= 1e-9:
            self.status.setText("相邻边界点不能重合。")
            return
        if len(points) >= 3 and math.dist(points[0], point) <= 1e-9:
            self._finish_area()
            return
        points.append(point)
        self._canvas.set_area_preview(tuple(points), subtract=self._area_mode == "subtract")
        self.input.clear()
        self.status.setText(f"AREA：已指定 {len(points)} 点；继续指定点，Enter 完成，U 撤销。")

    def _finish_area(self) -> None:
        points = self._area_points
        if points is None:
            return
        if len(points) < 3:
            self.status.setText("AREA 至少需要三个边界点。")
            return
        if polyline_self_intersection(tuple(points), closed=True) is not None:
            self.status.setText("面积边界自交或重叠；输入 U 撤销点，或 Esc 取消。")
            return
        origin = points[0]
        local = [(p[0] - origin[0], p[1] - origin[1]) for p in points]
        edges = list(zip(local, local[1:] + local[:1], strict=True))
        try:
            area = abs(math.fsum(a[0] * b[1] - b[0] * a[1] for a, b in edges)) / 2
            perimeter = math.fsum(math.dist(a, b) for a, b in edges)
        except (OverflowError, ValueError):
            self.status.setText("面积结果超出可用范围，请取消后重新测量。")
            return
        if not math.isfinite(area) or not math.isfinite(perimeter) or area <= 1e-12:
            self.status.setText("面积结果无效或边界退化；输入 U 撤销点，或 Esc 取消。")
            return
        self._report_area(area, perimeter)

    def _accept_distance_point(self, point: Point2D) -> None:
        if self._distance_first is None:
            self._distance_first = point
            self.input.clear()
            self.status.setText("DIST：指定第二点。")
            return
        dx = point[0] - self._distance_first[0]
        dy = point[1] - self._distance_first[1]
        distance = math.hypot(dx, dy)
        if not all(math.isfinite(value) for value in (dx, dy, distance)):
            self.status.setText("测量结果超出可用范围，请重新指定第二点。")
            return
        angle = math.degrees(math.atan2(dy, dx)) % 360.0
        self._distance_active = False
        self._distance_first = None
        self.input.clear()
        self.status.setText(
            f"距离：{distance:g} mm；ΔX：{dx:g} mm；ΔY：{dy:g} mm；角度：{angle:g}°。"
        )

    def _submit_view(self, text: str) -> None:
        if self._view_stage == "zoom":
            upper = text.upper()
            if upper in {"P", "PREVIOUS"}:
                restored = self._canvas.restore_previous_view()
                self._view_stage = ""
                self.input.clear()
                self.status.setText("已恢复上一视图。" if restored else "没有可恢复的上一视图。")
                return
            if upper in {"W", "WINDOW"}:
                self._view_stage = "zoom_window_first"
                self.input.clear()
                self.status.setText("ZOOM：指定窗口第一角点。")
                return
            if any(character in text for character in (",", "<", "@")):
                try:
                    parse_coordinate(text, None)
                except ValueError as exc:
                    self.status.setText(str(exc))
                    return
                self._view_stage = "zoom_window_first"
                self._submit_view(text)
                return
            if upper in {"E", "EXTENTS", "A", "ALL"}:
                self._canvas.fit_view()
            else:
                try:
                    factor = float(upper.removesuffix("X"))
                    if not math.isfinite(factor) or factor <= 0:
                        raise ValueError
                except ValueError:
                    self.status.setText("ZOOM：指定窗口角点、输入 W、E，或输入相对比例（如 2X）。")
                    return
                self._canvas.zoom_view_factor(factor)
            self._view_stage = ""
            self.input.clear()
            self.status.setText("视图缩放完成。")
            return
        try:
            point = parse_coordinate(text, self._view_first)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        if self._view_stage == "zoom_window_first":
            self._view_first = point
            self._view_stage = "zoom_window_second"
            self._canvas.set_zoom_window_preview(point)
            self.input.clear()
            self.status.setText("ZOOM：指定窗口对角点。")
            return
        if self._view_stage == "zoom_window_second" and self._view_first is not None:
            if not self._canvas.zoom_view_window(self._view_first, point):
                self.status.setText("ZOOM：窗口无效或超出视图范围，请重新指定对角点。")
                return
            self._view_stage = ""
            self._view_first = None
            self._canvas.set_zoom_window_preview(None)
            self.input.clear()
            self.status.setText("窗口缩放完成。")
            return
        if self._view_stage == "pan_first":
            self._view_first = point
            self._view_stage = "pan_second"
            self.status.setText("PAN：指定第二点。")
        elif self._view_first is not None:
            if not self._canvas.pan_view_between(self._view_first, point):
                self.status.setText("PAN：平移距离超出可用范围，请重新指定第二点。")
                return
            self._view_stage = ""
            self._view_first = None
            self.status.setText("视图平移完成。")
        self.input.clear()

    def _begin_polygon(self) -> None:
        if not self._activate("多边形"):
            return
        self._polygon_stage = "sides"
        self._polygon_edge_first = None
        self._last_command = "POLYGON"
        self._last_is_transform = False
        self.status.setText(f"请输入边数 <{self._canvas.polygon_sides}>（3–128）。")
        self.input.clear()

    def _submit_polygon(self, text: str) -> None:
        if self._polygon_stage == "sides":
            try:
                sides = int(text) if text else self._canvas.polygon_sides
                if not 3 <= sides <= 128:
                    raise ValueError
            except ValueError:
                self.status.setText("请输入 3–128 的整数边数。")
                return
            self._configure_polygon(sides, self._canvas.polygon_circumscribed)
            self._polygon_stage = "center"
            self.status.setText("指定正多边形中心，或选择 E（边）。")
        elif self._polygon_stage == "center" and text.upper() in {"E", "EDGE"}:
            self._polygon_stage = "edge_first"
            self.status.setText("指定边的第一个端点。")
        elif self._polygon_stage in {"edge_first", "edge_second"}:
            try:
                point = parse_coordinate(text, self._last_point)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            if self._polygon_stage == "edge_first":
                self._polygon_edge_first = point
                self._last_point = point
                self._polygon_stage = "edge_second"
                self.status.setText("指定边的第二个端点。")
            else:
                first = self._polygon_edge_first
                if first is None:
                    self.status.setText("边的起点已失效，请重新开始。")
                    return
                dx, dy = point[0] - first[0], point[1] - first[1]
                if not math.isfinite(dx) or not math.isfinite(dy) or math.hypot(dx, dy) <= 1e-9:
                    self.status.setText("边的两个端点必须不同且在有效范围内。")
                    return
                offset = 0.5 / math.tan(math.pi / self._canvas.polygon_sides)
                center = (
                    (first[0] + point[0]) / 2 - dy * offset,
                    (first[1] + point[1]) / 2 + dx * offset,
                )
                if not all(math.isfinite(value) for value in center):
                    self.status.setText("边的端点超出可用范围。")
                    return
                self._configure_polygon(self._canvas.polygon_sides, False)
                self._canvas.add_coordinate_point(center, exact_point=True)
                self._accepted = False
                self._canvas.add_coordinate_point(first, exact_point=True)
                if not self._accepted:
                    self.status.setText(self._canvas.message)
                    return
                self._last_point = point
                self._polygon_stage = ""
                self._activate("选择元素")
                self.status.setText("正多边形已创建；可撤销。")
        elif self._polygon_stage == "mode":
            if text.upper() not in {"", "I", "INSCRIBED", "C", "CIRCUMSCRIBED"}:
                self.status.setText("请输入 I（内接）或 C（外切）。")
                return
            self._configure_polygon(
                self._canvas.polygon_sides, text.upper() in {"C", "CIRCUMSCRIBED"}
            )
            self._polygon_stage = "radius"
            self.status.setText("指定半径或半径端点。")
        else:
            try:
                if self._polygon_stage == "radius" and not any(
                    separator in text for separator in (",", "<", "@")
                ):
                    radius = float(text)
                    center = self._canvas.pending_last_point
                    if center is None or not math.isfinite(radius) or radius <= 0:
                        raise ValueError("请输入大于零的有限半径。")
                    point = (center[0] + radius, center[1])
                    if not math.isfinite(point[0]) or point == center:
                        raise ValueError("正多边形半径超出可用范围。")
                else:
                    point = parse_coordinate(text, self._last_point)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            self._accepted = False
            self._canvas.add_coordinate_point(point, exact_point=True)
            if not self._accepted:
                self.status.setText(self._canvas.message)
                return
            if self._polygon_stage == "center":
                self._polygon_stage = "mode"
                self.status.setText("选择 I（内接）或 C（外切）<I>。")
            else:
                self._polygon_stage = ""
                self._activate("选择元素")
                self.status.setText("正多边形已创建；可撤销。")
        self.input.clear()

    def _begin_array(self) -> None:
        if self._canvas.has_pending_geometry or self._canvas.has_active_edit_gesture:
            self.status.setText("请先完成或取消当前操作，再创建阵列。")
            return
        if not self._activate("选择元素"):
            return
        self._array_stage = "select"
        self.input.clear()
        if self._canvas.selected_entity_ids:
            self._submit_array("")
        else:
            self.status.setText("阵列：选择二维图元，Enter / 右键确认。")

    def _submit_array(self, text: str) -> None:
        if self._array_stage == "select":
            if text or not self._canvas.selected_entity_ids:
                self.status.setText("请选择二维图元，然后按 Enter 或右键。")
                return
            if self._canvas.selected_raster_ids or self._canvas.selected_constraint_ids:
                self.status.setText("阵列目前只支持二维图元，请取消图片或尺寸选择。")
                return
            self._array_stage = "kind"
            self.input.clear()
            self.status.setText("阵列类型：R 矩形 / PO 环形；路径阵列尚未实现。")
            return
        option = text.upper()
        if option in {"", "R", "RECTANGULAR"}:
            self._array_stage = ""
            if self._begin_rectangular_array():
                self._submit_rectangular_array("")
        elif option in {"P", "PO", "POLAR"}:
            self._array_stage = ""
            self._begin_polar_array()
        else:
            self.status.setText("请选择 R 矩形或 PO 环形；路径阵列尚未实现。")
            return
        self.input.clear()

    def _begin_polar_array(self) -> bool:
        if self._canvas.has_pending_geometry or self._canvas.has_active_edit_gesture:
            self.status.setText("请先完成或取消当前操作，再创建环形阵列。")
            return False
        if not self._activate("选择元素"):
            return False
        self._polar_stage = "select"
        self._polar_count = 6
        self._polar_angle = 360.0
        self._last_command = "ARRAYPOLAR"
        self._last_is_transform = False
        self.input.clear()
        if self._canvas.selected_entity_ids:
            self._submit_polar_array("")
        else:
            self.status.setText("环形阵列：选择图元，Enter / 右键确认选择。")
        return True

    def _submit_polar_array(self, text: str) -> None:
        if self._polar_stage == "select":
            if text or not self._canvas.selected_entity_ids:
                self.status.setText("请选择二维图元，然后按 Enter 或右键。")
                return
            if self._canvas.selected_raster_ids or self._canvas.selected_constraint_ids:
                self.status.setText("环形阵列目前只支持二维图元，请取消图片或尺寸选择。")
                return
            error = self._canvas.transform_selection_error("circular_array")
            if error:
                self.status.setText(error)
                return
            self._polar_selected = frozenset(self._canvas.selected_entity_ids)
            self._polar_sources = tuple(
                entity
                for entity in self._canvas.selectable_entities()
                if entity.entity_id in self._polar_selected
            )
            self._polar_history = self._canvas.history_position
            provider = self._canvas.source_revision_provider
            self._polar_revision = provider() if provider is not None else None
            self._polar_stage = "center"
            self.status.setText("环形阵列：指定中心点。")
            return
        provider = self._canvas.source_revision_provider
        if (
            frozenset(self._canvas.selected_entity_ids) != self._polar_selected
            or tuple(
                entity
                for entity in self._canvas.selectable_entities()
                if entity.entity_id in self._polar_selected
            )
            != self._polar_sources
            or self._canvas.history_position != self._polar_history
            or (provider is not None and provider() != self._polar_revision)
        ):
            if self._canvas.active_transform == "polar_array_preview":
                self._canvas.cancel_transform()
            self._polar_stage = ""
            self.input.clear()
            self.status.setText("选择或文档已变化；请重新开始环形阵列。")
            return
        if self._polar_stage == "center":
            try:
                self._polar_center = parse_coordinate(text, self._last_point)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            self._last_point = self._polar_center
            self._polar_stage = "count"
            self.input.clear()
            self.status.setText("环形阵列：输入数量（包含原对象，2–1000；Enter 使用 6）。")
            return
        if self._polar_stage in {"count", "edit_count"}:
            try:
                count = int(text) if text else self._polar_count
                if not 2 <= count <= 1000:
                    raise ValueError
            except ValueError:
                self.status.setText("请输入 2–1000 的整数数量。")
                return
            if (count - 1) * len(self._polar_selected) > 10000:
                self.status.setText("环形阵列最多生成 10000 个图元，请减少数量。")
                return
            self._polar_count = count
            if self._polar_stage == "edit_count":
                self._preview_polar_array()
            else:
                self._polar_stage = "angle"
                self.input.clear()
                self.status.setText("环形阵列：输入总角度（±360° 内，Enter 使用 360°）。")
            return
        if self._polar_stage in {"angle", "edit_angle"}:
            try:
                angle = float(text) if text else self._polar_angle
                if not math.isfinite(angle) or not 0 < abs(angle) <= 360:
                    raise ValueError
            except ValueError:
                self.status.setText("请输入非零、绝对值不超过 360 的有限角度。")
                return
            self._polar_angle = angle
            self._preview_polar_array()
            return
        if self._polar_stage == "preview":
            option = text.upper()
            if option in {"I", "ITEMS"}:
                self._polar_stage = "edit_count"
                self.input.clear()
                self.status.setText("环形阵列：输入总数量。")
            elif option in {"A", "ANGLE"}:
                self._polar_stage = "edit_angle"
                self.input.clear()
                self.status.setText("环形阵列：输入总角度。")
            elif not text or option in {"X", "EXIT"}:
                if self._canvas.commit_polar_array_preview():
                    self._polar_stage = ""
                    self.input.clear()
                    self.status.setText(self._canvas.message)
                else:
                    self._polar_stage = ""
                    self.status.setText("环形阵列无法提交；图元未修改。")
            else:
                self.status.setText("环形阵列：输入 I、A 或 Enter；当前仅创建独立副本。")

    def _preview_polar_array(self) -> None:
        try:
            self._canvas.begin_polar_array_preview(
                self._polar_count, self._polar_center, self._polar_angle
            )
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._polar_stage = "preview"
        self.input.clear()
        self.status.setText(self._canvas.message)

    def _begin_rectangular_array(self) -> bool:
        if self._canvas.has_pending_geometry or self._canvas.has_active_edit_gesture:
            self.status.setText("请先完成或取消当前操作，再创建矩形阵列。")
            return False
        if not self._activate("选择元素"):
            return False
        self._rect_edit_mode = ""
        self._rect_associative = False
        self._rect_angle = 0.0
        self._rect_base = None
        self._rect_pending_angle = 0.0
        self._rect_stage = "select"
        self._last_command = "ARRAYRECT"
        self._last_is_transform = False
        self.status.setText("矩形阵列：选择对象，Enter / 右键确认选择。")
        self.input.clear()
        return True

    def _finish_rectangular_edit(self) -> None:
        success, message = self._apply_rectangular_array(
            self._rect_pending_rows,
            self._rect_pending_columns,
            self._rect_pending_row_spacing,
            self._rect_pending_column_spacing,
            self._rect_pending_angle,
        )
        if success:
            self._rect_rows = self._rect_pending_rows
            self._rect_columns = self._rect_pending_columns
            self._rect_row_spacing = self._rect_pending_row_spacing
            self._rect_column_spacing = self._rect_pending_column_spacing
            self._rect_angle = self._rect_pending_angle
            self._rect_stage = "preview"
            self.input.clear()
        self.status.setText(message)

    def _rectangular_spacing_prompt(self, *, row: bool) -> str:
        axis = "行间距 ΔV" if row else "列间距 ΔU"
        options = "T 总距离或 U 单元格" if self._rect_edit_mode == "S" else "T 总距离"
        return f"矩形阵列：输入{axis}，或 {options}。"

    def _submit_rectangular_array(self, text: str) -> None:
        if self._rect_stage == "select":
            if text or not self._canvas.selected_entity_ids:
                self.status.setText("请选择对象，然后按 Enter 或右键。")
                return
            error = self._canvas.transform_selection_error("rectangular_array")
            if error:
                self.status.setText(error)
                return
            self._rect_selected = frozenset(self._canvas.selected_entity_ids)
            self._rect_sources = tuple(
                entity
                for entity in self._canvas.selectable_entities()
                if entity.entity_id in self._rect_selected
            )
            self._rect_history = self._canvas.history_position
            provider = self._canvas.source_revision_provider
            self._rect_revision = provider() if provider is not None else None
            self._rect_stage = "rows"
            self.status.setText("矩形阵列：输入行数（1–1000）。")
            return
        provider = self._canvas.source_revision_provider
        if (
            frozenset(self._canvas.selected_entity_ids) != self._rect_selected
            or tuple(
                entity
                for entity in self._canvas.selectable_entities()
                if entity.entity_id in self._rect_selected
            )
            != self._rect_sources
            or self._canvas.history_position != self._rect_history
            or (provider is not None and provider() != self._rect_revision)
        ):
            if self._canvas.active_transform == "rectangular_array_preview":
                self._canvas.cancel_transform()
            self._rect_stage = ""
            self.status.setText("选择或文档已变化；请重新开始矩形阵列。")
            self.input.clear()
            return
        if self._rect_stage == "preview":
            option = text.upper()
            if option in {"B", "BASE"}:
                self._rect_stage = "edit_base"
                self.status.setText("矩形阵列：指定基点，K 选择源关键点，D 恢复默认。")
                self.input.clear()
                return
            if option in {"AN", "ANGLE"}:
                self._rect_pending_rows = self._rect_rows
                self._rect_pending_columns = self._rect_columns
                self._rect_pending_row_spacing = self._rect_row_spacing
                self._rect_pending_column_spacing = self._rect_column_spacing
                self._rect_pending_angle = self._rect_angle
                self._rect_stage = "edit_angle"
                self.status.setText("矩形阵列：输入方向角或指定第一方向点。")
                self.input.clear()
                return
            if option in {"AS", "ASSOCIATIVE"}:
                self._rect_stage = "edit_associative"
                self.status.setText("关联阵列？输入 Y 建立关联，或 N 创建独立副本。")
                self.input.clear()
                return
            if option in {"R", "ROWS", "C", "COLUMNS", "S", "SPACING", "CO", "COUNT"}:
                self._rect_pending_rows = self._rect_rows
                self._rect_pending_columns = self._rect_columns
                self._rect_pending_row_spacing = self._rect_row_spacing
                self._rect_pending_column_spacing = self._rect_column_spacing
                self._rect_pending_angle = self._rect_angle
                self._rect_edit_mode = "COUNT" if option in {"CO", "COUNT"} else option[0]
                self._rect_stage = (
                    "edit_rows"
                    if self._rect_edit_mode == "R"
                    else "edit_columns"
                    if self._rect_edit_mode == "C"
                    else "edit_count_rows"
                    if self._rect_edit_mode == "COUNT"
                    else "edit_row_spacing"
                    if self._rect_rows > 1
                    else "edit_column_spacing"
                )
                self.status.setText(
                    {
                        "edit_rows": "矩形阵列：输入行数。",
                        "edit_columns": "矩形阵列：输入列数。",
                        "edit_count_rows": "矩形阵列：输入行数。",
                        "edit_row_spacing": self._rectangular_spacing_prompt(row=True),
                        "edit_column_spacing": self._rectangular_spacing_prompt(row=False),
                    }[self._rect_stage]
                )
                self.input.clear()
                return
            if option not in {"", "X", "EXIT"}:
                self.status.setText(
                    "矩形阵列：R 行、C 列、CO 数量、S 间距、AN 角度、B 基点、AS 关联；Enter / X 确认。"
                )
                return
            success, message = self._commit_rectangular_array(
                self._rect_associative,
                self._rect_rows,
                self._rect_columns,
                self._rect_row_spacing,
                self._rect_column_spacing,
                self._rect_angle,
                self._rect_base,
            )
            if success or self._canvas.active_transform != "rectangular_array_preview":
                self._rect_stage = ""
            self.input.clear()
            self.status.setText(message)
            return
        if self._rect_stage in {"edit_base", "edit_base_key"}:
            if self._rect_stage == "edit_base" and text.upper() in {"D", "DEFAULT"}:
                self._rect_base = None
                self._rect_stage = "preview"
                self.status.setText("已恢复默认阵列基点；Enter / X 确认。")
                self.input.clear()
                return
            if self._rect_stage == "edit_base" and text.upper() in {"K", "KEY"}:
                self._rect_stage = "edit_base_key"
                self.status.setText("矩形阵列：指定所选源对象的关键点。")
                self.input.clear()
                return
            try:
                point = parse_coordinate(text, self._last_point)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            if self._rect_stage == "edit_base_key":
                pointer = self._canvas.local_to_screen(point)
                candidates = [
                    (
                        (self._canvas.local_to_screen(position) - pointer).manhattanLength(),
                        reference,
                    )
                    for entity in self._rect_sources
                    for reference, position in self._canvas.entity_point_references(entity)
                ]
                candidates.sort(key=lambda item: item[0])
                if (
                    not candidates
                    or candidates[0][0] > 10
                    or (len(candidates) > 1 and candidates[0][0] == candidates[1][0])
                ):
                    self.status.setText("请选择唯一的源对象关键点。")
                    return
                self._rect_base = candidates[0][1]
            else:
                self._rect_base = point
            self._last_point = point
            self._rect_stage = "preview"
            self.status.setText("已设置阵列基点；Enter / X 确认。")
            self.input.clear()
            return
        if self._rect_stage in {"edit_angle", "edit_angle_second"}:
            if self._rect_stage == "edit_angle" and not any(c in text for c in (",", "@", "<")):
                try:
                    angle = self._rect_angle if not text else float(text)
                    if not math.isfinite(angle):
                        raise ValueError
                except ValueError:
                    self.status.setText("请输入有限方向角或指定第一方向点。")
                    return
                self._rect_pending_angle = angle
                self._finish_rectangular_edit()
                return
            try:
                point = parse_coordinate(
                    text,
                    self._rect_unit_first
                    if self._rect_stage == "edit_angle_second"
                    else self._last_point,
                )
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            if self._rect_stage == "edit_angle":
                self._rect_unit_first = point
                self._last_point = point
                self._rect_stage = "edit_angle_second"
                self.status.setText("矩形阵列：指定第二方向点。")
                self.input.clear()
                return
            assert self._rect_unit_first is not None
            dx, dy = point[0] - self._rect_unit_first[0], point[1] - self._rect_unit_first[1]
            if math.hypot(dx, dy) <= 1e-9:
                self.status.setText("方向点不能重合；请重新指定第二点。")
                return
            self._rect_pending_angle = math.degrees(math.atan2(dy, dx))
            self._last_point = point
            self._finish_rectangular_edit()
            return
        if self._rect_stage == "edit_associative":
            option = text.upper()
            if option in {"", "N", "NO"}:
                self._rect_associative = False
                self._rect_stage = "preview"
                self.status.setText(self._canvas.message)
                self.input.clear()
            elif option in {"Y", "YES"}:
                self._rect_associative = True
                self._rect_stage = "preview"
                self.status.setText("已选择关联阵列；Enter / X 确认。")
                self.input.clear()
            else:
                self.status.setText("请输入 Y 或 N，或按 Esc 取消。")
            return
        if self._rect_stage in {"edit_unit_first", "edit_unit_second"}:
            try:
                point = parse_coordinate(
                    text,
                    self._rect_unit_first
                    if self._rect_stage == "edit_unit_second"
                    else self._last_point,
                )
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            if self._rect_stage == "edit_unit_first":
                self._rect_unit_first = point
                self._last_point = point
                self._rect_stage = "edit_unit_second"
                self.status.setText("矩形阵列：指定单元格第二角点。")
                self.input.clear()
                return
            assert self._rect_unit_first is not None
            dx = point[0] - self._rect_unit_first[0]
            dy = point[1] - self._rect_unit_first[1]
            radians = math.radians(self._rect_pending_angle % 360)
            dx, dy = (
                dx * math.cos(radians) + dy * math.sin(radians),
                -dx * math.sin(radians) + dy * math.cos(radians),
            )
            values = ((dx, self._rect_pending_columns), (dy, self._rect_pending_rows))
            if any(
                not math.isfinite(value)
                or (count > 1 and abs(value) <= 1e-9)
                or abs(value) > 1_000_000
                for value, count in values
            ):
                self.status.setText("单元格间距须有限，活动轴非零，且不能超过 1000000。")
                return
            self._rect_pending_column_spacing = dx if self._rect_pending_columns > 1 else 0.0
            self._rect_pending_row_spacing = dy if self._rect_pending_rows > 1 else 0.0
            self._last_point = point
            self._finish_rectangular_edit()
            return
        if self._rect_stage in {"edit_count_rows", "edit_count_columns"}:
            try:
                value = int(text)
                if not 1 <= value <= 1000:
                    raise ValueError
            except ValueError:
                self.status.setText("请输入 1 到 1000 的整数。")
                return
            if self._rect_stage == "edit_count_rows":
                self._rect_pending_rows = value
                self._rect_stage = "edit_count_columns"
                self.status.setText("矩形阵列：输入列数。")
                self.input.clear()
                return
            if not 2 <= self._rect_pending_rows * value <= 1000:
                self.status.setText("矩形阵列的位置数必须为 2 到 1000。")
                return
            self._rect_pending_columns = value
            if self._rect_pending_rows == 1:
                self._rect_pending_row_spacing = 0.0
            if value == 1:
                self._rect_pending_column_spacing = 0.0
            if self._rect_pending_rows > 1 and self._rect_pending_row_spacing == 0:
                self._rect_stage = "edit_row_spacing"
                self.status.setText(self._rectangular_spacing_prompt(row=True))
                self.input.clear()
            elif value > 1 and self._rect_pending_column_spacing == 0:
                self._rect_stage = "edit_column_spacing"
                self.status.setText(self._rectangular_spacing_prompt(row=False))
                self.input.clear()
            else:
                self._finish_rectangular_edit()
            return
        if self._rect_stage in {"edit_rows", "edit_columns"}:
            try:
                value = int(text)
                rows = value if self._rect_stage == "edit_rows" else self._rect_pending_rows
                columns = (
                    value if self._rect_stage == "edit_columns" else self._rect_pending_columns
                )
                if value < 1 or value > 1000 or not 2 <= rows * columns <= 1000:
                    raise ValueError
            except ValueError:
                self.status.setText("行列必须为正整数，总位置数为 2 到 1000。")
                return
            self._rect_pending_rows, self._rect_pending_columns = rows, columns
            if self._rect_stage == "edit_rows":
                if rows == 1:
                    self._rect_pending_row_spacing = 0.0
                    self._finish_rectangular_edit()
                else:
                    self._rect_stage = "edit_row_spacing"
                    self.status.setText(self._rectangular_spacing_prompt(row=True))
                    self.input.clear()
            elif columns == 1:
                self._rect_pending_column_spacing = 0.0
                self._finish_rectangular_edit()
            else:
                self._rect_stage = "edit_column_spacing"
                self.status.setText(self._rectangular_spacing_prompt(row=False))
                self.input.clear()
            return
        if self._rect_stage in {"rows", "columns"}:
            try:
                value = int(text)
                if value < 1 or value > 1000:
                    raise ValueError
            except ValueError:
                self.status.setText("请输入 1 到 1000 的整数。")
                return
            if self._rect_stage == "rows":
                self._rect_rows = value
                self._rect_stage = "columns"
                self.status.setText("矩形阵列：输入列数（1–1000）。")
            elif not 2 <= self._rect_rows * value <= 1000:
                self.status.setText("矩形阵列的位置数必须为 2 到 1000。")
                return
            else:
                self._rect_columns = value
                self._rect_row_spacing = 0.0
                self._rect_stage = "row_spacing" if self._rect_rows > 1 else "column_spacing"
                self.status.setText(
                    self._rectangular_spacing_prompt(row=True)
                    if self._rect_rows > 1
                    else self._rectangular_spacing_prompt(row=False)
                )
            self.input.clear()
            return
        if (
            self._rect_edit_mode == "S"
            and self._rect_stage in {"edit_row_spacing", "edit_column_spacing"}
            and text.upper() in {"U", "UNIT"}
        ):
            self._rect_unit_first = None
            self._rect_stage = "edit_unit_first"
            self.status.setText("矩形阵列：指定单元格第一角点。")
            self.input.clear()
            return
        if self._rect_stage in {
            "row_spacing",
            "column_spacing",
            "edit_row_spacing",
            "edit_column_spacing",
        } and text.upper() in {"T", "TOTAL"}:
            self._rect_stage = self._rect_stage.replace("spacing", "total")
            self.status.setText("矩形阵列：输入首尾位置的总距离。")
            self.input.clear()
            return
        total_stage = self._rect_stage.endswith("_total")
        try:
            spacing = float(text)
            if total_stage:
                is_row = "row_total" in self._rect_stage
                count = (
                    (self._rect_pending_rows if is_row else self._rect_pending_columns)
                    if self._rect_stage.startswith("edit_")
                    else (self._rect_rows if is_row else self._rect_columns)
                )
                spacing /= count - 1
            if not math.isfinite(spacing) or abs(spacing) <= 1e-9 or abs(spacing) > 1_000_000:
                raise ValueError
        except ValueError:
            self.status.setText("请输入有限非零、绝对值不超过 1000000 的间距。")
            return
        if total_stage:
            self._rect_stage = self._rect_stage.replace("total", "spacing")
        if self._rect_stage == "edit_row_spacing":
            self._rect_pending_row_spacing = spacing
            if (self._rect_edit_mode == "S" and self._rect_pending_columns > 1) or (
                self._rect_edit_mode == "COUNT"
                and self._rect_pending_columns > 1
                and self._rect_pending_column_spacing == 0
            ):
                self._rect_stage = "edit_column_spacing"
                self.status.setText(self._rectangular_spacing_prompt(row=False))
                self.input.clear()
            else:
                self._finish_rectangular_edit()
            return
        if self._rect_stage == "edit_column_spacing":
            self._rect_pending_column_spacing = spacing
            self._finish_rectangular_edit()
            return
        if self._rect_stage == "row_spacing":
            self._rect_row_spacing = spacing
            if self._rect_columns > 1:
                self._rect_stage = "column_spacing"
                self.status.setText(self._rectangular_spacing_prompt(row=False))
                self.input.clear()
                return
            column_spacing = 0.0
        else:
            column_spacing = spacing
        prior_stage = self._rect_stage
        self._rect_stage = "preview"
        success, message = self._apply_rectangular_array(
            self._rect_rows,
            self._rect_columns,
            self._rect_row_spacing,
            column_spacing,
            self._rect_angle,
        )
        if success:
            self._rect_column_spacing = column_spacing
            self.input.clear()
        else:
            self._rect_stage = prior_stage
        self.status.setText(message)

    def _record_history(self, text: str) -> None:
        if text:
            self.history.append(text)
            del self.history[:-500]
            self.input.set_history(self.history, self.status.text())
            self.history_line.emit(text)

    def _recall_input(self, direction: int) -> None:
        if not self._input_history:
            return
        if self._history_index == len(self._input_history) and direction < 0:
            self._history_draft = self.input.text()
        self._history_index = max(0, min(len(self._input_history), self._history_index + direction))
        self.input.setText(
            self._history_draft
            if self._history_index == len(self._input_history)
            else self._input_history[self._history_index]
        )

    def submit(self) -> None:
        text = self.input.text().strip()
        self._completion_last = ""
        if text:
            self._input_history.append(text)
            del self._input_history[:-500]
        self._history_index = len(self._input_history)
        self._history_draft = ""
        self._record_history(f"命令: {text}")
        upper = text.upper()
        if self._collection_selecting:
            if not text or upper == self._collection_selecting.upper():
                self._confirm_collection_selection()
                return
            self._collection_selecting = None
        if (
            self._canvas.geometric_tolerance_tools is not None
            and self._canvas.geometric_tolerance_tools.handle_command(text)
        ):
            self.input.clear()
            self.status.setText(self._canvas.message)
            return
        corner_trim_option = (
            upper == "T"
            and self._canvas.tool in {"二维倒角", "二维圆角"}
            and self._canvas.text_tools is not None
            and not self._canvas.text_tools.pending
        )
        if self._canvas.text_tools is not None and not corner_trim_option:
            try:
                handled = self._canvas.text_tools.handle_command(text)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            if handled:
                self.input.clear()
                self.status.setText(self._canvas.message)
                return
        if self._measurement_mode:
            if self._measurement_mode == "options":
                if upper in {"Q", "QUICK"}:
                    self._measurement_mode = "quick"
                    self.input.clear()
                    self.status.setText("快速测量：移动到两条直线或圆弧附近；Esc 退出。")
                elif upper in {"D", "DISTANCE"}:
                    self._measurement_mode = ""
                    self._begin_distance()
                elif upper in {"AR", "AREA"}:
                    self._measurement_mode = ""
                    self._begin_area()
                elif upper in {"R", "RADIUS"}:
                    self._measurement_mode = "radius"
                    self.input.clear()
                    self.status.setText("半径：选择圆或圆弧。")
                elif upper in {"A", "ANGLE"}:
                    self._measurement_mode = "angle"
                    self.input.clear()
                    self.status.setText("角度：指定顶点，或输入 O 选择对象。")
                else:
                    self.status.setText("请输入 Q 快速测量、D 距离、R 半径、A 角度或 AR 面积。")
                return
            if self._measurement_mode == "quick":
                self.status.setText("快速测量：移动到两条直线或圆弧附近；Esc 退出。")
                return
            if (
                self._measurement_mode == "angle"
                and not self._angle_points
                and upper in {"O", "OBJECT"}
            ):
                self._measurement_mode = "angle_object"
                self._angle_object = None
                self.input.clear()
                self.status.setText("角度：选择直线、圆、圆弧或多段线段。")
                return
            if self._measurement_mode in {"angle_object", "angle_circle"}:
                try:
                    base = self._angle_object[3] if self._angle_object is not None else None
                    point = parse_coordinate(text, base)
                except ValueError as exc:
                    self.status.setText(str(exc))
                    return
                if self._measurement_mode == "angle_object":
                    self._measure_angle_object(point)
                else:
                    self._measure_angle_circle(point)
                return
            try:
                point = parse_coordinate(
                    text, self._angle_points[-1] if self._angle_points else None
                )
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            if self._measurement_mode == "radius":
                self._measure_radius_at(point)
            else:
                self._accept_angle_point(point)
            return
        if self._area_points is not None:
            if upper in {"A", "ADD", "S", "SUBTRACT"} and not self._area_points:
                self._area_mode = "add" if upper in {"A", "ADD"} else "subtract"
                self._area_object = False
                self._canvas.set_area_preview(())
                self.input.clear()
                self.status.setText("AREA：指定边界点或输入 O 选择对象；可切换增加(A)或扣减(S)。")
                return
            if upper in {"O", "OBJECT"} and not self._area_points:
                self._area_object = True
                self._canvas.set_area_preview(())
                self.input.clear()
                self.status.setText("AREA：选择圆、矩形或闭合多段线。")
                return
            if self._area_object:
                if not text and self._area_mode:
                    self._area_enter()
                    return
                self.status.setText("AREA：请在画布上选择对象，或按 Esc 取消。")
                return
            if not text or upper in {"C", "CLOSE"}:
                self._area_enter()
                return
            if upper in {"U", "UNDO"}:
                if self._area_points:
                    self._area_points.pop()
                self._canvas.set_area_preview(
                    tuple(self._area_points), subtract=self._area_mode == "subtract"
                )
                self.input.clear()
                self.status.setText(f"AREA：已指定 {len(self._area_points)} 点。")
                return
            try:
                point = parse_coordinate(text, self._area_points[-1] if self._area_points else None)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            self._accept_area_point(point)
            return
        if self._distance_active:
            try:
                point = parse_coordinate(text, self._distance_first)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            self._accept_distance_point(point)
            return
        if self._view_stage:
            self._submit_view(text)
            return
        if upper == "HELP":
            self.input.clear()
            self.status.setText("支持的命令：" + "、".join(self._command_names()))
            return
        if upper == "QSELECT":
            self.input.clear()
            if any(
                (
                    self._polygon_stage,
                    self._array_stage,
                    self._polar_stage,
                    self._rect_stage,
                    self._chamfer_stage,
                    self._chamfer_system_pending,
                    self._fillet_radius_pending,
                    self._filletrad_system_pending,
                    self._fillet_trim_pending,
                    self._copy_mode_pending,
                    self._copy_command_mode_pending,
                    self._line_edge_pending,
                    self._edge_system_pending,
                    self._offsetdist_pending,
                    self._offsetgaptype_pending,
                    self._trim_mode_system_pending,
                    self._corner_trim_system_pending,
                    self._line_mode_pending,
                    self._projection_pending,
                )
            ):
                self.status.setText("请先完成或取消当前命令，再快速选择。")
                return
            self.panel_requested.emit("quickselect")
            return
        if self._dimensions is not None and (
            upper == "DIMSTYLE"
            or (
                upper == "D"
                and self._dimensions.mode is None
                and self._canvas.tool in self._DRAWING_TOOLS | {"选择元素"}
                and not self._canvas.has_pending_geometry
                and self._canvas.active_transform is None
                and not self._canvas.has_active_edit_gesture
            )
        ):
            self.input.clear()
            self._dimensions.open_format_presets()
            return
        if self._polygon_stage:
            self._submit_polygon(text)
            return
        if self._array_stage:
            self._submit_array(text)
            return
        dimension_mode = self._DIMENSIONS.get(upper)
        if dimension_mode is not None and self._dimensions is not None:
            self._dimensions.start(dimension_mode)
            self._last_command = upper
            self._last_is_transform = False
            self.input.clear()
            return
        if self._dimensions is not None and self._dimensions.mode is not None:
            if self._linear_rotation_pending:
                try:
                    angle = float(text)
                    if not math.isfinite(angle):
                        raise ValueError
                except ValueError:
                    self.status.setText("请输入有限的旋转角度（度）。")
                    return
                if self._dimensions.command_linear_rotation(angle):
                    self._linear_rotation_pending = False
                    self.input.clear()
                return
            if not text:
                if self._dimensions.command_editing_value:
                    if self._dimensions.command_accept_value():
                        self.input.clear()
                    return
                self._dimensions.cancel()
                self.status.setText("标注已结束。")
                self.input.clear()
                return
            if (
                upper in {"R", "ROTATED"}
                and not self._dimensions.command_editing_value
                and self._dimensions.mode in {"linear", "horizontal", "vertical"}
            ):
                self._linear_rotation_pending = True
                self.status.setText("旋转线性尺寸：输入角度（度）。")
                self.input.clear()
                return
            if upper in {"H", "HORIZONTAL", "V", "VERTICAL"}:
                axis = "horizontal" if upper in {"H", "HORIZONTAL"} else "vertical"
                if self._dimensions.command_linear_axis(axis):
                    self.input.clear()
                    return
            if self._dimensions.command_editing_value:
                try:
                    value = float(text)
                except ValueError:
                    self.status.setText("请输入有效的尺寸值。")
                    return
                if self._dimensions.command_value(value):
                    self.input.clear()
                return
            try:
                point = parse_coordinate(text, self._last_point)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            if self._dimensions.command_point(point):
                self._last_point = point
                self.input.clear()
                if self._dimensions.command_editing_value:
                    self.input.setFocus()
            return
        if self._chamfer_system_pending:
            name = self._chamfer_system_pending
            if name == "CHAMMODE":
                if text and text not in {"0", "1"}:
                    self.status.setText("CHAMMODE 请输入 0 或 1。")
                    return
                if text:
                    self._canvas.set_chamfer_method(text == "1")
                self._chamfer_system_pending = ""
                self.status.setText(
                    f"CHAMMODE 当前值 {int(self._canvas.chamfer_angle is not None)}。"
                )
                self.input.clear()
                return
            names = ("CHAMFERA", "CHAMFERB", "CHAMFERC", "CHAMFERD")
            values = [
                self._canvas.chamfer_distance_first,
                self._canvas.chamfer_second_distance,
                self._canvas.chamfer_angle_length,
                self._canvas.chamfer_last_angle,
            ]
            index = names.index(name)
            try:
                value = float(text) if text else values[index]
                if not math.isfinite(value) or value < 0 or (name == "CHAMFERD" and value >= 180):
                    raise ValueError
            except ValueError:
                self.status.setText(f"{name} 请输入有效的非负有限数值。")
                return
            values[index] = value
            try:
                self._canvas.set_chamfer_values((values[0], values[1], values[2], values[3]))
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            self._chamfer_system_pending = ""
            self.status.setText(f"{name} 当前值 {value:g}。")
            self.input.clear()
            return
        if self._filletrad_system_pending:
            try:
                radius = float(text) if text else self._canvas.circle_fillet_radius
            except ValueError:
                self.status.setText("FILLETRAD 请输入非负有限半径。")
                return
            if not math.isfinite(radius) or radius < 0:
                self.status.setText("FILLETRAD 请输入非负有限半径。")
                return
            try:
                self._canvas.set_circle_fillet_radius(radius)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            self._filletrad_system_pending = False
            self.status.setText(f"FILLETRAD 当前值 {radius:g}。")
            self.input.clear()
            return
        if self._corner_trim_system_pending:
            if text and text not in {"0", "1"}:
                self.status.setText("TRIMMODE 请输入 0 或 1。")
                return
            if text:
                self._canvas.chamfer_trim = text == "1"
            self._corner_trim_system_pending = False
            self.status.setText(f"TRIMMODE 当前值 {int(self._canvas.chamfer_trim)}。")
            self.input.clear()
            return
        if (self._canvas.tool == "二维倒角" and self._canvas.chamfer_polyline_pending) or (
            self._canvas.tool == "二维圆角"
            and self._canvas.circle_fillet_polyline_pending
            and not (upper in {"T", "TRIM"} or self._fillet_trim_pending)
        ):
            self.status.setText("请选择多段线；Esc 取消。")
            self.input.clear()
            return
        if self._canvas.tool != "二维倒角":
            self._chamfer_stage = ""
        if self._canvas.tool == "二维倒角":
            if self._chamfer_stage:
                stage = self._chamfer_stage
                if stage in {"trim", "method"}:
                    choices = {
                        "trim": {"T": True, "TRIM": True, "N": False, "NOTRIM": False},
                        "method": {"D": False, "DISTANCE": False, "A": True, "ANGLE": True},
                    }[stage]
                    if not text:
                        self._chamfer_stage = ""
                        self.status.setText("二维倒角：设置保持不变。")
                        self.input.clear()
                        return
                    if upper not in choices:
                        self.status.setText("请输入 T/N。" if stage == "trim" else "请输入 D/A。")
                        return
                    if stage == "trim":
                        self._canvas.chamfer_trim = choices[upper]
                    else:
                        self._canvas.set_chamfer_method(choices[upper])
                    self._chamfer_stage = ""
                    self.status.setText("二维倒角：请选择第一条直线。")
                else:
                    try:
                        default = (
                            self._canvas.chamfer_distance_first
                            if stage == "distance_first"
                            else self._canvas.chamfer_angle_length
                            if stage == "angle_first"
                            else self._canvas.chamfer_second_distance
                            if stage == "distance_second"
                            else self._canvas.chamfer_last_angle
                        )
                        value = float(text) if text else default
                        if (
                            not math.isfinite(value)
                            or value < 0
                            or (
                                stage == "angle"
                                and not (
                                    0 < value < 180 or (value == 0 and self._chamfer_distance == 0)
                                )
                            )
                        ):
                            raise ValueError
                    except ValueError:
                        self.status.setText("请输入有效的非负距离或 0 至 180 度之间的角度。")
                        return
                    if stage in {"distance_first", "angle_first"}:
                        self._chamfer_distance = value
                        self._chamfer_stage = (
                            "distance_second" if stage == "distance_first" else "angle"
                        )
                        self.status.setText(
                            "请输入第二距离。" if stage == "distance_first" else "请输入角度。"
                        )
                    elif stage == "distance_second":
                        try:
                            self._canvas.set_chamfer_values(
                                (
                                    self._chamfer_distance,
                                    value,
                                    self._canvas.chamfer_angle_length,
                                    self._canvas.chamfer_last_angle,
                                )
                            )
                        except ValueError as exc:
                            self.status.setText(str(exc))
                            return
                        self._canvas.set_chamfer_method(False)
                        self._chamfer_stage = ""
                        self.status.setText("二维倒角：选择第一条边或拖过两边；M 连续。")
                    else:
                        try:
                            self._canvas.set_chamfer_values(
                                (
                                    self._canvas.chamfer_distance_first,
                                    self._canvas.chamfer_second_distance,
                                    self._chamfer_distance,
                                    value,
                                )
                            )
                        except ValueError as exc:
                            self.status.setText(str(exc))
                            return
                        self._canvas.set_chamfer_method(True)
                        self._chamfer_stage = ""
                        self.status.setText("二维倒角：选择第一条边或拖过两边；M 连续。")
                self.input.clear()
                return
            if not text:
                if self._canvas.has_active_edit_gesture:
                    self.status.setText("二维倒角：请选择第二个对象，或按 Esc 取消。")
                else:
                    self._activate("选择元素")
                    self.status.setText("二维倒角已结束。")
                self.input.clear()
                return
            if upper in {"D", "DISTANCE", "A", "ANGLE", "T", "TRIM", "E", "METHOD"}:
                if self._canvas.has_active_edit_gesture:
                    self.status.setText("请先完成或取消当前选取。")
                    return
                self._chamfer_stage = {
                    "D": "distance_first",
                    "DISTANCE": "distance_first",
                    "A": "angle_first",
                    "ANGLE": "angle_first",
                    "T": "trim",
                    "TRIM": "trim",
                    "E": "method",
                    "METHOD": "method",
                }[upper]
                self.status.setText(
                    {
                        "distance_first": "请输入第一距离。",
                        "angle_first": "请输入第一距离。",
                        "trim": "选择 T（修剪）或 N（不修剪）。",
                        "method": "选择 D（距离）或 A（角度）。",
                    }[self._chamfer_stage]
                )
                self.input.clear()
                return
            if upper in {"P", "POLYLINE"}:
                if self._canvas.has_active_edit_gesture:
                    self.status.setText("请先完成或取消当前选取。")
                else:
                    self._canvas.chamfer_polyline_pending = True
                    self.status.setText("二维倒角：请选择多段线。")
                self.input.clear()
                return
            if upper in {"M", "MULTIPLE"}:
                self._canvas.circle_fillet_multiple = True
                self.status.setText("二维倒角已启用连续操作。")
                self.input.clear()
                return
            if upper in {"U", "UNDO"}:
                self._canvas.undo_fillet()
                self.input.clear()
                return
        if self._polar_stage:
            self._submit_polar_array(text)
            return
        if upper == "ARRAYPOLAR":
            self._begin_polar_array()
            return
        if self._rect_stage:
            self._submit_rectangular_array(text)
            return
        if upper == "ARRAYRECT":
            self._begin_rectangular_array()
            return
        if self._offsetgaptype_pending:
            if text and text not in {"0", "1", "2"}:
                self.status.setText("OFFSETGAPTYPE 请输入 0、1 或 2。")
                return
            if text:
                self._canvas.set_offset_gap_type(int(text))
            self._offsetgaptype_pending = False
            self.status.setText(f"OFFSETGAPTYPE 当前值 {self._canvas.offset_gap_type}。")
            self.input.clear()
            return
        if upper == "OFFSETGAPTYPE":
            if (
                self._canvas.has_pending_geometry
                or self._canvas.has_active_edit_gesture
                or self._canvas.active_transform is not None
            ):
                self.status.setText("请先完成或取消当前操作，再设置 OFFSETGAPTYPE。")
            else:
                self._offsetgaptype_pending = True
                self.status.setText(
                    f"OFFSETGAPTYPE 当前值 {self._canvas.offset_gap_type}；输入 0、1 或 2。"
                )
                self.input.clear()
            return
        if self._offsetdist_pending:
            if text:
                try:
                    self._canvas.set_offset_default_distance(float(text))
                except ValueError:
                    self.status.setText("OFFSETDIST 请输入有限实数。")
                    return
            self._offsetdist_pending = False
            self.status.setText(f"OFFSETDIST 当前值 {self._canvas.offset_default_distance:g}。")
            self.input.clear()
            return
        if upper == "OFFSETDIST":
            if self._canvas.has_pending_geometry or self._canvas.has_active_edit_gesture:
                self.status.setText("请先完成或取消当前操作，再设置 OFFSETDIST。")
            else:
                self._offsetdist_pending = True
                self.status.setText(
                    f"OFFSETDIST 当前值 {self._canvas.offset_default_distance:g}；输入新值。"
                )
                self.input.clear()
            return
        if self._projection_pending:
            system = self._projection_pending == "system"
            choices = (
                {"0": 0, "1": 1, "2": 2}
                if system
                else {"N": 0, "NONE": 0, "U": 1, "UCS": 1, "V": 2, "VIEW": 2}
            )
            if text and upper not in choices:
                self.status.setText(
                    "请输入 0、1 或 2。" if system else "请输入 N / None、U / UCS 或 V / View。"
                )
                return
            if text:
                self._canvas.set_line_edit_projection_mode(choices[upper])
            self._projection_pending = ""
            self.status.setText("投影模式已设置；异面边界支持直线、圆、圆弧及多段线目标。")
            self.input.clear()
            self.input.setFocus()
            return
        if upper == "PROJMODE":
            if self._canvas.has_pending_geometry or self._canvas.has_active_edit_gesture:
                self.status.setText("请先完成或取消当前操作，再设置 PROJMODE。")
            else:
                self._projection_pending = "system"
                self.status.setText(
                    f"PROJMODE 当前值 {self._canvas.line_edit_projection_mode}；输入 0、1 或 2。"
                )
                self.input.clear()
            return
        if self._trim_mode_system_pending or self._line_mode_pending:
            system_mode = self._trim_mode_system_pending
            valid = {"0", "1"} if system_mode else {"Q", "QUICK", "S", "STANDARD"}
            if text and upper not in valid:
                self.status.setText(
                    "请输入 0 或 1。" if system_mode else "请输入 Q / Quick 或 S / Standard。"
                )
                return
            if text:
                standard = upper == "0" if system_mode else upper in {"S", "STANDARD"}
                self._canvas.set_line_edit_standard_mode(standard)
                if not system_mode and self._canvas.tool in {"修剪", "延伸"}:
                    if standard:
                        self._canvas.begin_line_edit_boundary_selection()
                    else:
                        if self._canvas.selecting_line_edit_boundaries:
                            self._canvas_key(Qt.Key.Key_Escape)
                        self._canvas.set_line_edit_boundaries(None)
                self.status.setText("已设为标准模式。" if standard else "已设为快速模式。")
            else:
                self.status.setText("修剪／延伸模式保持不变。")
            self._trim_mode_system_pending = False
            self._line_mode_pending = False
            self.input.clear()
            self.input.setFocus()
            return
        if upper == "TRIMEXTENDMODE":
            if self._canvas.has_pending_geometry or self._canvas.has_active_edit_gesture:
                self.status.setText("请先完成或取消当前操作，再设置 TRIMEXTENDMODE。")
            else:
                self._trim_mode_system_pending = True
                current = 0 if self._canvas.line_edit_standard_mode else 1
                self.status.setText(f"TRIMEXTENDMODE 当前值 {current}；输入 0 或 1。")
                self.input.clear()
            return
        if self._edge_system_pending:
            if not text:
                self.status.setText("EDGEMODE 保持不变。")
            elif text in {"0", "1"}:
                self._canvas.set_line_edit_edge_mode(text == "1")
                self.status.setText(f"EDGEMODE 已设为 {text}。")
            else:
                self.status.setText("EDGEMODE 请输入 0 或 1。")
                return
            self._edge_system_pending = False
            self.input.clear()
            self.input.setFocus()
            return
        if upper == "EDGEMODE":
            if self._canvas.has_pending_geometry or self._canvas.has_active_edit_gesture:
                self.status.setText("请先完成或取消当前操作，再设置 EDGEMODE。")
            else:
                self._edge_system_pending = True
                current = int(self._canvas.line_edit_extend_boundaries)
                self.status.setText(f"EDGEMODE 当前值 {current}；输入 0 或 1。")
                self.input.clear()
            return
        if self._canvas.copy_array_needs_count:
            try:
                self._canvas.set_copy_array_count(int(text))
            except ValueError:
                self.status.setText("请输入 2 到 1000 的整数数量。")
                return
            self.input.clear()
            self.input.setFocus()
            return
        if self._canvas.copy_array_available and upper in {"A", "ARRAY"}:
            if self._canvas.begin_copy_array():
                self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        if self._canvas.copy_array_waiting_point and upper in {"F", "FIT"}:
            try:
                self._canvas.set_copy_array_fit()
            except ValueError as exc:
                self.status.setText(str(exc))
                self.input.setFocus()
                return
            self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        if self._canvas.awaiting_mirror_erase:
            if upper not in {"", "Y", "YES", "N", "NO"}:
                self.status.setText("请输入 Y / Yes 删除源对象，或 N / No 保留。")
                return
            self._canvas.confirm_mirror_erase(upper in {"Y", "YES"})
            self.status.setText(self._canvas.message)
            self.input.clear()
            self.input.setFocus()
            return
        if self._canvas.active_transform == "offset" and self._canvas.offset_layer_pending:
            if upper not in {"", "C", "CURRENT", "S", "SOURCE"}:
                self.status.setText("偏移图层：请输入 C / Current 或 S / Source。")
                return
            current = self._canvas.offset_layer_current if not upper else upper in {"C", "CURRENT"}
            self._canvas.set_interactive_offset_layer(current)
            self.status.setText(self._canvas.message)
            self.input.clear()
            return
        if self._canvas.active_transform == "offset" and self._canvas.offset_erase_pending:
            if upper not in {"", "Y", "YES", "N", "NO"}:
                self.status.setText("偏移：请输入 Y 删除源对象，或 N 保留。")
                return
            if upper:
                self._canvas.offset_erase_source = upper in {"Y", "YES"}
            self._canvas.offset_erase_pending = False
            self.status.setText(
                "偏移：已设置删除源对象。"
                if self._canvas.offset_erase_source
                else "偏移：已设置保留源对象。"
            )
            self.input.clear()
            return
        if self._canvas.active_transform == "offset" and upper in {"E", "ERASE"}:
            self._canvas.offset_erase_pending = True
            current = "Y" if self._canvas.offset_erase_source else "N"
            self.status.setText(f"偏移后删除源对象？输入 Y 或 N，Enter 保持 {current}。")
            self.input.clear()
            return
        if self._canvas.active_transform == "offset" and upper in {"L", "LAYER"}:
            self._canvas.offset_layer_pending = True
            self.status.setText("偏移图层：输入 C / Current 或 S / Source。")
            self.input.clear()
            return
        if self._canvas.active_transform == "offset" and upper in {"M", "MULTIPLE"}:
            try:
                self._canvas.set_interactive_offset_multiple()
            except ValueError as exc:
                self.status.setText(str(exc))
            else:
                self.status.setText(self._canvas.message)
            self.input.clear()
            return
        if self._canvas.active_transform == "offset" and upper in {"U", "UNDO"}:
            self._canvas.undo_interactive_offset()
            self.status.setText(self._canvas.message)
            self.input.clear()
            return
        if self._canvas.active_transform == "offset" and upper in {"X", "EXIT"}:
            self._canvas.cancel_transform()
            self.status.setText(self._canvas.message)
            self.input.clear()
            return
        if self._canvas.interactive_offset_needs_distance:
            try:
                if not text:
                    self._canvas.use_interactive_offset_default()
                elif upper in {"T", "THROUGH"}:
                    self._canvas.set_interactive_offset_through()
                elif any(separator in text for separator in (",", "<", "@")):
                    self._canvas.set_interactive_offset_distance_point(
                        parse_coordinate(text, self._last_point)
                    )
                else:
                    self._canvas.set_interactive_offset_distance(float(text))
            except ValueError as exc:
                message = (
                    str(exc)
                    if not text or any(separator in text for separator in (",", "<", "@"))
                    else "请输入大于零的有限距离，或 T 指定通过点。"
                )
                self.status.setText(f"偏移：{message}")
                return
            self.input.clear()
            self.input.setFocus()
            return
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
        if self._canvas.selecting_line_edit_boundaries and not text:
            self._canvas_key(Qt.Key.Key_Return)
            self.status.setText(self._canvas.message)
            self.input.clear()
            self.input.setFocus()
            return
        if self._canvas.line_edit_erasing and not text:
            self._canvas_key(Qt.Key.Key_Return)
            self.status.setText(self._canvas.message)
            self.input.clear()
            self.input.setFocus()
            return
        if self._canvas.tool == "修剪" and upper in {"R", "ERASE"}:
            try:
                self._canvas.begin_line_edit_erase()
            except ValueError as exc:
                self.status.setText(str(exc))
            else:
                self.status.setText(self._canvas.message)
            self.input.clear()
            self.input.setFocus()
            return
        if self._canvas.tool in {"修剪", "延伸"} and upper in {"O", "MO", "MODE"}:
            if (
                self._canvas.has_active_edit_gesture
                and not self._canvas.selecting_line_edit_boundaries
            ):
                self.status.setText("请先完成或取消当前操作，再设置模式。")
            else:
                self._line_mode_pending = True
                self.status.setText("输入 Q / Quick 或 S / Standard。")
                self.input.clear()
            return
        if self._canvas.tool in {"修剪", "延伸"} and upper in {"P", "PROJECT"}:
            if (
                self._canvas.has_active_edit_gesture
                and not self._canvas.selecting_line_edit_boundaries
            ):
                self.status.setText("请先完成或取消当前操作，再设置投影模式。")
            else:
                self._projection_pending = "command"
                self.status.setText(
                    "投影：N / None、U / UCS 或 V / View；支持异面边界与多段线目标。"
                )
                self.input.clear()
            return
        if self._line_edge_pending:
            if self._canvas.tool not in {"修剪", "延伸"}:
                self._line_edge_pending = False
            elif not text:
                self._line_edge_pending = False
                self.status.setText("边界模式保持不变。")
                self.input.clear()
                self.input.setFocus()
                return
            elif upper in {"E", "EXTEND", "N", "NOEXTEND"}:
                self._canvas.set_line_edit_edge_mode(upper in {"E", "EXTEND"})
                self._line_edge_pending = False
                self.status.setText(
                    "边界模式：延长。"
                    if self._canvas.line_edit_extend_boundaries
                    else "边界模式：不延长。"
                )
                self.input.clear()
                self.input.setFocus()
                return
            else:
                self.status.setText("请输入 E / Extend 或 N / No Extend。")
                return
        if (
            self._canvas.tool in {"修剪", "延伸"}
            and not self._canvas.trim_fence_active
            and upper in {"E", "EDGE"}
        ):
            self._line_edge_pending = True
            self.status.setText("边界模式：输入 E / Extend 或 N / No Extend。")
            self.input.clear()
            self.input.setFocus()
            return
        if self._canvas.trim_fence_active and not text:
            self._canvas_key(Qt.Key.Key_Return)
            self.status.setText(self._canvas.message)
            self.input.clear()
            self.input.setFocus()
            return
        if self._canvas.tool in {"修剪", "延伸"} and upper in {"F", "FENCE"}:
            try:
                self._canvas.begin_trim_fence()
            except ValueError as exc:
                self.status.setText(str(exc))
            else:
                self.status.setText(self._canvas.message)
            self.input.clear()
            self.input.setFocus()
            return
        if self._canvas.tool in {"修剪", "延伸"} and upper in {"CR", "CROSSING"}:
            try:
                self._canvas.begin_line_crossing()
            except ValueError as exc:
                self.status.setText(str(exc))
            else:
                self.status.setText(self._canvas.message)
            self.input.clear()
            self.input.setFocus()
            return
        if self._canvas.tool in {"修剪", "延伸"} and upper in {"U", "UNDO"}:
            self._canvas.undo_line_edit_action()
            self.status.setText(self._canvas.message)
            self.input.clear()
            self.input.setFocus()
            return
        if (
            self._canvas.tool in {"修剪", "延伸"}
            and not self._canvas.trim_fence_active
            and upper in {"C", "CUTTING"}
        ):
            self._canvas.begin_line_edit_boundary_selection()
            self.input.clear()
            self.input.setFocus()
            return
        if not text:
            if self._canvas.tool == "对象相切选择":
                self._canvas_key(Qt.Key.Key_Return)
                self.status.setText(self._canvas.message)
                self.input.setFocus()
                return
            if self._canvas.tool == "单点打断":
                self._canvas_key(Qt.Key.Key_Return)
                self.status.setText(self._canvas.message)
                self.input.clear()
                self.input.setFocus()
                return
            if self._canvas.tool == "直线" and self._canvas.line_tangent_active:
                self.status.setText(self._canvas.message)
                return
            if self._canvas.tool == "圆弧" and self._canvas.arc_ttr_active:
                if (
                    self._canvas.arc_ttr_radius_pending
                    and self._canvas.arc_ttr_last_radius is not None
                ):
                    self._canvas.finish_arc_ttr(self._canvas.arc_ttr_last_radius)
                self.status.setText(self._canvas.message)
                return
            if self._canvas.tool == "圆" and self._canvas.circle_ttr_active:
                if (
                    self._canvas.circle_ttr_radius_pending
                    and self._canvas.circle_ttr_last_radius is not None
                ):
                    self._canvas.finish_circle_ttr(self._canvas.circle_ttr_last_radius)
                self.status.setText(self._canvas.message)
                return
            if self._canvas.tool == "二维圆角" and self._fillet_trim_pending:
                self._fillet_trim_pending = False
                self._canvas.circle_fillet_trim_pending = False
                self.status.setText(
                    "二维圆角：已启用修剪。"
                    if self._canvas.circle_fillet_trim
                    else "二维圆角：已启用不修剪。"
                )
                self.input.setFocus()
                return
            if self._canvas.tool == "二维圆角" and self._fillet_radius_pending:
                if self._canvas.circle_fillet_radius_measuring:
                    self.status.setText("二维圆角：请指定量距第二点。")
                    return
                self._fillet_radius_pending = False
                self._canvas.circle_fillet_radius_pending = False
                self._canvas.set_circle_fillet_radius(self._canvas.circle_fillet_radius)
                self.status.setText(self._canvas.message)
                self.input.setFocus()
                return
            if self._canvas.tool == "二维圆角" and self._canvas.has_active_edit_gesture:
                self.status.setText("二维圆角：请选择第二个对象；Esc 取消。")
                return
            if self._canvas.tool == "二维圆角":
                self._activate("选择元素")
                self.status.setText("二维圆角已结束。")
                self.input.clear()
                return
            if (
                self._canvas.has_pending_geometry
                or self._canvas.active_transform is not None
                or (self._canvas.tool == "直线" and self._canvas.pending_point_count > 0)
            ):
                self._canvas_key(Qt.Key.Key_Return)
                self.status.setText(self._canvas.message)
            elif self._last_command is not None:
                if self._last_command in {
                    "GROUP",
                    "BLOCK",
                    "UNGROUP",
                    "GROUPEDIT",
                    "INSERT",
                    "EXPLODE",
                    "BEDIT",
                    "BLOCKLIB",
                    "WBLOCK",
                    "ZOOM",
                    "PAN",
                }:
                    self.input.setText(self._last_command)
                    self.submit()
                    return
                if self._last_command == "MEASUREGEOM":
                    self._begin_measuregeom()
                    return
                if self._last_command == "AREA":
                    self._begin_area()
                    return
                if self._last_command == "DIST":
                    self._begin_distance()
                    return
                if self._last_command == "POLYGON":
                    self._begin_polygon()
                    return
                if self._last_command == "ARRAYRECT":
                    self._begin_rectangular_array()
                    return
                if self._last_command == "ARRAYPOLAR":
                    self._begin_polar_array()
                    return
                if self._last_command in self._DIMENSIONS and self._dimensions is not None:
                    self._dimensions.start(self._DIMENSIONS[self._last_command])
                    self.input.clear()
                    return
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
        if self._canvas.tool == "二维圆角" and self._fillet_radius_pending:
            try:
                if any(separator in text for separator in (",", "<", "@")):
                    self._canvas.set_circle_fillet_radius_point(
                        parse_coordinate(text, self._last_point)
                    )
                else:
                    radius = float(text)
                    if not math.isfinite(radius) or radius < 0:
                        raise ValueError("请输入非负的有限圆角半径。")
                    self._canvas.circle_fillet_radius_pending = False
                    try:
                        self._canvas.set_circle_fillet_radius(radius)
                    except ValueError:
                        self._canvas.circle_fillet_radius_pending = True
                        raise
            except ValueError as exc:
                message = str(exc)
                self.status.setText(
                    "请输入非负的有限圆角半径。"
                    if message.startswith("could not convert string to float:")
                    else message
                )
                return
            self._fillet_radius_pending = self._canvas.circle_fillet_radius_pending
            self.input.clear()
            return
        if self._canvas.tool == "二维圆角" and self._fillet_trim_pending:
            if upper not in {"T", "TRIM", "N", "NOTRIM"}:
                self.status.setText("请输入 T（修剪）或 N（不修剪）。")
                return
            self._canvas.circle_fillet_trim = upper in {"T", "TRIM"}
            self._fillet_trim_pending = False
            self._canvas.circle_fillet_trim_pending = False
            self.status.setText(
                "二维圆角：已启用修剪。"
                if self._canvas.circle_fillet_trim
                else "二维圆角：已启用不修剪。"
            )
            self.input.clear()
            return
        if self._canvas.tool == "二维圆角" and upper in {"T", "TRIM"}:
            self._fillet_trim_pending = True
            self._canvas.circle_fillet_trim_pending = True
            self.status.setText("二维圆角：选择 T（修剪）或 N（不修剪）。")
            self.input.clear()
            return
        if self._canvas.tool == "二维圆角" and upper in {"U", "UNDO"}:
            self._canvas.undo_fillet()
            self.status.setText(self._canvas.message)
            self.input.clear()
            return
        if self._canvas.tool == "二维圆角" and upper in {"M", "MULTIPLE"}:
            self._canvas.circle_fillet_multiple = True
            self.status.setText("二维圆角已启用连续操作；Esc 结束。")
            self.input.clear()
            return
        if self._canvas.tool == "二维圆角" and upper in {"P", "POLYLINE"}:
            if self._canvas.fillet_open_polyline_ends():
                self.status.setText(self._canvas.message)
            elif self._canvas.has_active_edit_gesture:
                self.status.setText("请先完成或取消当前选取。")
            else:
                self._canvas.circle_fillet_polyline_pending = True
                self.status.setText("请选择多段线；Esc 取消。")
            self.input.clear()
            return
        if self._canvas.tool == "二维圆角" and upper in {"R", "RADIUS"}:
            self._fillet_radius_pending = True
            self._canvas.begin_circle_fillet_radius()
            self.status.setText("二维圆角：输入非负半径或指定两点。")
            self.input.clear()
            return
        if upper == "TRIMMODE":
            if self._canvas.has_pending_geometry or self._canvas.has_active_edit_gesture:
                self.status.setText("请先完成或取消当前操作，再设置 TRIMMODE。")
            else:
                self._corner_trim_system_pending = True
                self.status.setText(
                    f"TRIMMODE 当前值 {int(self._canvas.chamfer_trim)}；输入 0 或 1。"
                )
                self.input.clear()
            return
        if upper in {"CHAMFERA", "CHAMFERB", "CHAMFERC", "CHAMFERD", "CHAMMODE"}:
            if self._canvas.has_pending_geometry or self._canvas.has_active_edit_gesture:
                self.status.setText(f"请先完成或取消当前操作，再设置 {upper}。")
            else:
                self._chamfer_system_pending = upper
                current = {
                    "CHAMFERA": self._canvas.chamfer_distance_first,
                    "CHAMFERB": self._canvas.chamfer_second_distance,
                    "CHAMFERC": self._canvas.chamfer_angle_length,
                    "CHAMFERD": self._canvas.chamfer_last_angle,
                    "CHAMMODE": int(self._canvas.chamfer_angle is not None),
                }[upper]
                self.status.setText(f"{upper} 当前值 {current:g}；输入非负数值或按 Enter。")
                self.input.clear()
            return
        if upper == "FILLETRAD":
            if self._canvas.has_pending_geometry or self._canvas.has_active_edit_gesture:
                self.status.setText("请先完成或取消当前操作，再设置 FILLETRAD。")
            else:
                self._filletrad_system_pending = True
                self.status.setText(
                    f"FILLETRAD 当前值 {self._canvas.circle_fillet_radius:g}；输入非负半径。"
                )
                self.input.clear()
            return
        if self._canvas.tool == "多段线" and self._canvas.pending_point_count:
            handled = True
            if upper in {"U", "UNDO"}:
                self._canvas.undo_polyline_segment()
                self._last_point = self._canvas.pending_last_point
            elif self._canvas.polyline_arc_stage in {"radius", "angle"}:
                try:
                    value = float(text)
                except ValueError:
                    self.status.setText("请输入有限数值，或用 U 取消当前选项。")
                    return
                if not self._canvas.set_polyline_arc_number(value):
                    self.status.setText(self._canvas.message)
                    return
            elif upper in {"A", "ANGLE"} and self._canvas.polyline_arc_mode:
                self._canvas.begin_polyline_arc_option("angle")
            elif upper in {"A", "ARC"}:
                self._canvas.set_polyline_arc_mode(True)
            elif upper in {"L", "LINE"} and self._canvas.polyline_arc_mode:
                self._canvas.set_polyline_arc_mode(False)
            elif upper in {"S", "SECOND", "SECONDPOINT"} and self._canvas.polyline_arc_mode:
                self._canvas.begin_polyline_arc_second_point()
            elif upper in {"R", "RADIUS"} and self._canvas.polyline_arc_mode:
                self._canvas.begin_polyline_arc_option("radius")
            elif upper in {"CE", "CENTER"} and self._canvas.polyline_arc_mode:
                self._canvas.begin_polyline_arc_option("center")
            else:
                handled = False
            if handled:
                self.status.setText(self._canvas.message)
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
        if upper in {"TAN", "TANGENT"} and self._canvas.tool == "直线":
            self._canvas.begin_line_tangent_pick()
            self.status.setText(self._canvas.message)
            self.input.clear()
            return
        if (
            upper in {"A", "ARC"}
            and self._canvas.tool == "椭圆"
            and self._canvas.ellipse_mode_prompt_active
        ):
            if self._canvas.begin_ellipse_arc():
                self.input.clear()
            self.status.setText(self._canvas.message)
            return
        if upper in {"CW", "CCW"} and self._canvas.tool == "椭圆" and self._canvas.ellipse_arc_mode:
            self._canvas.set_ellipse_arc_direction(upper == "CW")
            self.input.clear()
            self.status.setText(self._canvas.message)
            return
        if (
            upper in {"3P", "3POINT"}
            and self._canvas.tool == "圆弧"
            and self._canvas.arc_mode_prompt_active
        ):
            if self._canvas.begin_arc_three_point():
                self.input.clear()
            self.status.setText(self._canvas.message)
            return
        if (
            upper in {"C", "CENTER"}
            and self._canvas.tool == "圆弧"
            and self._canvas.arc_mode_prompt_active
            and not self._canvas.has_pending_geometry
            and not self._canvas.arc_ttr_active
        ):
            if self._canvas.begin_arc_center():
                self.input.clear()
            self.status.setText(self._canvas.message)
            return
        if (
            upper in {"T", "TTR"}
            and self._canvas.tool == "圆弧"
            and self._canvas.arc_mode_prompt_active
            and not self._canvas.has_pending_geometry
            and not self._canvas.arc_ttr_active
        ):
            if self._canvas.begin_arc_ttr():
                self.input.clear()
            self.status.setText(self._canvas.message)
            return
        if self._canvas.tool == "圆弧" and self._canvas.arc_ttr_active:
            if not self._canvas.arc_ttr_radius_pending:
                self.status.setText("相切圆弧：请先选择两个对象。")
                return
            try:
                radius = float(text)
                if not math.isfinite(radius) or radius <= 0:
                    raise ValueError
            except ValueError:
                self.status.setText("相切圆弧：请输入大于零的有限半径。")
                return
            if self._canvas.finish_arc_ttr(radius):
                self.input.clear()
            self.status.setText(self._canvas.message)
            return
        if (
            upper in {"T", "TTR"}
            and self._canvas.tool == "圆"
            and not self._canvas.has_pending_geometry
            and not self._canvas.circle_ttr_active
        ):
            self._canvas.begin_circle_ttr()
            self.status.setText(self._canvas.message)
            self.input.clear()
            return
        if self._canvas.tool == "圆" and self._canvas.circle_ttr_active:
            if not self._canvas.circle_ttr_radius_pending:
                self.status.setText("圆 TTR：请先选择两个切线对象。")
                return
            try:
                radius = float(text)
                if not math.isfinite(radius) or radius <= 0:
                    raise ValueError
            except ValueError:
                self.status.setText("圆 TTR：请输入大于零的有限半径。")
                return
            if self._canvas.finish_circle_ttr(radius):
                self.input.clear()
            self.status.setText(self._canvas.message)
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
        if self._canvas.scale_center is not None and upper in {"C", "COPY"}:
            if self._canvas.enable_scale_copy():
                self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        if self._canvas.scale_center is not None and upper in {"R", "REFERENCE"}:
            if self._canvas.start_scale_reference():
                self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        if self._canvas.scale_reference_active and upper in {"P", "POINTS"}:
            if self._canvas.start_scale_target_points():
                self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        if self._canvas.rotation_center is not None and upper in {"R", "REFERENCE"}:
            if self._canvas.start_rotation_reference():
                self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        if self._canvas.rotation_center is not None and upper in {"C", "COPY"}:
            if self._canvas.enable_rotation_copy():
                self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        if self._canvas.rotation_uses_reference and upper in {"P", "POINTS"}:
            if self._canvas.start_rotation_target_points():
                self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        if self._canvas.scale_center is not None and not any(
            separator in text for separator in (",", "<", "@")
        ):
            if self._canvas.scale_target_points_active:
                self.status.setText("请指定目标长度的两个点。")
                return
            try:
                factor = float(text)
                if not math.isfinite(factor) or factor <= 0:
                    raise ValueError
            except ValueError:
                self.status.setText("请输入大于零的有限缩放比例。")
                return
            accepted = (
                self._canvas.apply_scale_length(factor)
                if self._canvas.scale_reference_active
                else self._canvas.apply_scale_factor(factor)
            )
            if accepted:
                self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        if (
            self._canvas.rotation_center is not None
            and self._canvas.rotation_uses_reference
            and not self._canvas.rotation_target_points_active
            and not any(separator in text for separator in (",", "<", "@"))
        ):
            try:
                angle = float(text)
                if not math.isfinite(angle):
                    raise ValueError
                if self._canvas.rotation_reference_angle is None:
                    self._canvas.set_rotation_reference_angle(angle)
                    accepted = True
                else:
                    accepted = self._canvas.apply_rotation_target_angle(angle)
            except ValueError:
                self.status.setText("请输入有限的参考角或目标角。")
                return
            if accepted:
                self.input.clear()
            self.status.setText(self._canvas.message)
            self.input.setFocus()
            return
        if upper in {"COPYCLIP", "PASTECLIP"}:
            if upper == "COPYCLIP":
                self._canvas.copy_to_clipboard()
            else:
                self._canvas.begin_clipboard_paste()
            self.status.setText(self._canvas.message)
            self.input.clear()
            self._canvas.setFocus()
            return
        if upper in {"ARRAY", "AR"}:
            self._begin_array()
            return
        if upper in {"DIST", "DI"}:
            self._begin_distance()
            return
        if upper in {"MEASUREGEOM", "MEA"}:
            self._begin_measuregeom()
            return
        if upper == "AREA":
            self._begin_area()
            return
        if upper in {"ZOOM", "Z", "PAN", "P"}:
            if self._canvas.has_pending_geometry or self._canvas.has_active_edit_gesture:
                self.status.setText("请先完成或取消当前操作，再调整视图。")
                return
            if not self._activate("选择元素"):
                self.status.setText(self._canvas.message)
                return
            self._last_command = "ZOOM" if upper in {"ZOOM", "Z"} else "PAN"
            self._last_is_transform = False
            self._view_stage = "zoom" if upper in {"ZOOM", "Z"} else "pan_first"
            self._view_first = None
            self.input.clear()
            self.status.setText(
                "ZOOM：指定窗口角点、输入 W、E、P，或输入相对比例（如 2X）。"
                if self._view_stage == "zoom"
                else "PAN：指定第一点。"
            )
            return
        if upper in {"LAYER", "LA", "PROPERTIES", "MO", "OPTIONS", "OP"}:
            self.input.clear()
            panel = (
                "layer"
                if upper in {"LAYER", "LA"}
                else "properties"
                if upper in {"PROPERTIES", "MO"}
                else "options"
            )
            self.panel_requested.emit(panel)
            return
        if upper == "GROUP":
            self.input.clear()
            self.group_requested.emit()
            self.status.setText(self._canvas.message)
            return
        if upper == "UNGROUP":
            self.input.clear()
            self.remember_collection_command("ungroup")
            self.ungroup_requested.emit()
            return
        if upper == "GROUPEDIT":
            self.input.clear()
            self.remember_collection_command("groupedit")
            self.group_edit_requested.emit()
            return
        if upper in {"BLOCKLIB", "WBLOCK"}:
            self.input.clear()
            self.remember_collection_command("blocklib" if upper == "BLOCKLIB" else "wblock")
            (
                self.block_library_requested if upper == "BLOCKLIB" else self.block_write_requested
            ).emit()
            return
        if upper == "BLOCK":
            self.input.clear()
            self.block_requested.emit()
            self.status.setText(self._canvas.message)
            return
        if upper == "INSERT":
            self.input.clear()
            self.remember_collection_command("insert")
            self.block_insert_requested.emit()
            return
        if upper == "EXPLODE":
            self.input.clear()
            self.remember_collection_command("explode")
            self.block_explode_requested.emit()
            return
        if upper == "BEDIT":
            self.input.clear()
            self.remember_collection_command("bedit")
            self.block_edit_requested.emit()
            return
        if upper in {"POL", "POLYGON"}:
            self._begin_polygon()
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
        if self._canvas.ellipse_arc_angle_pending and not any(
            separator in text for separator in (",", "<", "@")
        ):
            try:
                angle = float(text)
                self._canvas.add_ellipse_arc_angle(angle)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            self.input.clear()
            self.status.setText(self._canvas.message)
            return
        if self._canvas.object_tracking_distance_available and not any(
            separator in text for separator in (",", "<", "@")
        ):
            try:
                value = float(text)
            except ValueError:
                pass
            else:
                try:
                    point = self._canvas.object_tracking_distance_point(value)
                except ValueError as exc:
                    self.status.setText(str(exc))
                    return
                self._accepted = False
                self._canvas.add_coordinate_point(point, exact_point=True)
                self.status.setText(self._canvas.message)
                if self._accepted:
                    self.input.clear()
                self.input.setFocus()
                return
        if self._canvas.polar_distance_available and not any(
            separator in text for separator in (",", "<", "@")
        ):
            try:
                value = float(text)
            except ValueError:
                pass
            else:
                try:
                    point = self._canvas.polar_distance_point(value)
                except ValueError as exc:
                    self.status.setText(str(exc))
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
        if (
            self._canvas.tool not in self._DRAWING_TOOLS | {"单点打断", "分割"}
            and self._canvas.active_transform is None
            and not self._canvas.trim_fence_active
            and not self._canvas.clipboard_paste_active
        ):
            self.status.setText("未知命令或当前工具不接受坐标。")
            return
        try:
            point = parse_coordinate(text, self._last_point)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._accepted = False
        selecting = self._canvas.transform_selecting
        tangent_pick = self._canvas.line_tangent_awaiting_pick
        self._canvas.add_coordinate_point(point, exact_point=True)
        self.status.setText(self._canvas.message)
        if (
            self._accepted
            or self._canvas.tool == "分割"
            or selecting
            or (tangent_pick and not self._canvas.line_tangent_awaiting_pick)
        ):
            self.input.clear()
        self.input.setFocus()
